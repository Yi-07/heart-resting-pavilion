// Web Audio PCM 流式播放器(plan §22/§23/§24)。
//
// 为什么不用 <audio>:整句 wav 路径必须等整句合成完才出声,首包延迟 = 整句耗时。
// PCM 分块 + AudioBufferSourceNode 调度可以在合成还在跑的时候就开始播。
//
// 三条硬约束(都是契约,不是实现细节):
//   1. **round 隔离**:只接受 frame.round_id == currentRoundId 的帧。旧 round 的
//      迟到帧正常丢弃(抢占后旧音频继续出声是最伤体验的 bug)。
//   2. **flush 不是 current.stop()**:已经 schedule 但还没播完的 source 有多个,
//      只停当前一个的话后面的会接着响。flush 必须清 pending 队列 + 让**所有**
//      已 schedule 的 source 失效,之后旧 round 的帧也不许再进队。
//   3. **不预设采样率一致**:32000 Hz 的 PCM 交给 AudioContext 播放时,浏览器会在
//      播放链路里做重采样。我们只负责观测(见 recordRate),不去改 AudioContext 的
//      sampleRate —— 改它会让所有已在播的 source 重建,反而制造 click。

import { logger } from '../logger'
import { bench } from './bench'

/** flush 淡出时长(ms):gain ramp 到 0 再 stop(PRD:旧声让位不爆音) */
export const FLUSH_FADE_MS = 120
/** 新回合首块淡入时长(ms):从 0 ramp 到 1,防爆音 */
export const LEAD_IN_MS = 50

/** 一块 PCM16(base64 解码后) */
export interface PcmBlock {
  roundId: string
  seq: number
  pcm: Int16Array
  sampleRate: number
  /** 仅支持 MONO_CHANNELS;其他值由 enqueue 显式拒绝(多声道无正确实现) */
  channels: number
}

/** 播放器可观测状态,供 benchmark 与 UI 读取 */
export interface PcmPlayerStats {
  /** 已 schedule 的 source 总数(含已播完的) */
  scheduled: number
  /** 当前仍在播放的 source 数 */
  active: number
  /** 待播队列里的块数 */
  pending: number
  /** 待播音频总时长(秒) */
  pendingSeconds: number
  /** AudioContext 实际采样率 */
  contextSampleRate: number
  /** 最近一个 AudioBuffer 的采样率 */
  bufferSampleRate: number
}

export interface PcmPlayerOptions {
  /** 目标缓冲深度(秒)。plan §22:80/120/200ms 由 benchmark 决定,不在此预锁。 */
  targetBufferSeconds: number
  /** 播放起点相对当前时间的提前量,留出调度余量 */
  scheduleAheadSeconds: number
  /** 采样率不一致时的回调(plan §25:观测,不自动干预) */
  onSampleRateMismatch?: (pcm: number, ctx: number) => void
}

const DEFAULT_OPTIONS: PcmPlayerOptions = {
  targetBufferSeconds: 0.12,
  scheduleAheadSeconds: 0.02,
}

type Ctor<T> = new (...args: never[]) => T

/** AudioContext 在 TS lib 里常缺席;用注入的构造器,测试与真机都能给 */
export interface AudioContextLike {
  sampleRate: number
  currentTime: number
  state: string
  destination: unknown
  resume(): Promise<void>
  createBuffer(
    channels: number,
    length: number,
    sampleRate: number,
  ): { copyToChannel(src: Float32Array, ch: number): void }
  createBufferSource(): {
    buffer: unknown
    connect(dest: unknown): void
    start(when?: number): void
    stop(when?: number): void
    onended: (() => void) | null
  }
  createGain(): {
    gain: {
      value: number
      setValueAtTime(value: number, when: number): void
      linearRampToValueAtTime(value: number, when: number): void
      cancelScheduledValues?(when: number): void
    }
    connect(dest: unknown): void
    disconnect(dest?: unknown): void
  }
}

interface LiveSource {
  node: { stop(when?: number): void; onended: (() => void) | null }
  endTime: number
  /** 挂在 source 与 destination 之间的增益节点;flush 淡出在此 ramp */
  gain: {
    gain: {
      value: number
      setValueAtTime(value: number, when: number): void
      linearRampToValueAtTime(value: number, when: number): void
      cancelScheduledValues?(when: number): void
    }
    connect(dest: unknown): void
    disconnect(dest?: unknown): void
  }
}

/** 本播放器支持的声道数。
 *
 * 单声道是协议实际产出的唯一形态:TTS 引擎 `tts_service/engine.py` 的
 * `PcmChunk(channels=1)` 是硬编码,ws-contract §3.4 的示例也是 1,
 * 历次真实抓包的 channels 集合恒为 {1}。多声道交错从未被定义,
 * 也没有被正确实现(见 enqueue 的说明),所以这里显式收敛到 1。
 */
export const MONO_CHANNELS = 1

/**
 * base64 → Int16Array(LE)。TTS 侧固定 pcm_s16le(plan §12)。
 *
 * 返回 `null` 表示**字节层就不完整**:PCM16 每样本 2 字节,字节数必须是偶数。
 * 奇数字节意味着流在样本中间被截断(半个样本),不存在「合法的样本数」。
 * 这里必须显式拒绝并留痕 —— 早先只用 `bytes.length >> 1` 悄悄丢掉最后一个字节,
 * 会把「少半个样本」伪装成正常音频,排程出去就是错位与杂音,而且无从追溯。
 */
export function decodePcm16(b64: string): Int16Array | null {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i)
  if (bytes.length % 2 !== 0) {
    logger.warn(
      'audio',
      `PCM16 字节数为奇数(${bytes.length}),样本不完整,拒绝该块(不静默截断)`,
    )
    return null
  }
  // 逐样本读,显式处理小端:不依赖平台字节序
  const view = new DataView(bytes.buffer)
  const out = new Int16Array(bytes.length >> 1)
  for (let i = 0; i < out.length; i += 1) out[i] = view.getInt16(i * 2, true)
  return out
}

/** Int16 → Float32,除以 32768 而不是 32767(与 int16 的负端对称) */
export function pcm16ToFloat32(pcm: Int16Array): Float32Array {
  const out = new Float32Array(pcm.length)
  for (let i = 0; i < pcm.length; i += 1) {
    const v = pcm[i] ?? 0
    out[i] = v / 32768
  }
  return out
}

/**
 * plan §28:peak = max(|sample|),RMS = sqrt(mean(sample²)),单位为 int16 的 LSB。
 * duration = sample_count / (sample_rate * channels),单位秒。
 *
 * 这里**不设故障阈值**:用途是 observation / detection,
 * 「相邻 chunk 音量跳变」先当现象记,不预设它等于 bug(plan §28)。
 */
export function chunkAudioMetrics(
  pcm: Int16Array,
  sampleRate: number,
  channels: number,
): { peak: number; rms: number; durationS: number } {
  let peak = 0
  let sumSq = 0
  for (let i = 0; i < pcm.length; i += 1) {
    const v = pcm[i] ?? 0
    const a = v < 0 ? -v : v
    if (a > peak) peak = a
    sumSq += v * v
  }
  return {
    peak,
    rms: pcm.length === 0 ? 0 : Math.sqrt(sumSq / pcm.length),
    durationS: pcm.length / (sampleRate * channels),
  }
}

export class PcmPlayer {
  private readonly options: PcmPlayerOptions
  private readonly ctxCtor: Ctor<AudioContextLike>
  private ctx: AudioContextLike | null = null
  /** 待播队列;flush 时整体清空 */
  private pending: PcmBlock[] = []
  private pendingSamples = 0
  /** 所有已 schedule、尚未结束的 source。flush 要让它们**全部**失效。 */
  private live = new Set<LiveSource>()
  private nextStartTime = 0
  private currentRoundId = ''
  /** 刚自认领/切到新回合:下一块(新回合首块)挂淡入 gain ramp */
  private roundJustClaimed = false
  private scheduled = 0
  private lastBufferRate = 0
  private playing = false
  private callbacks = new Set<(active: boolean) => void>()
  private sawMismatch = false

  constructor(options?: Partial<PcmPlayerOptions>, ctxCtor?: Ctor<AudioContextLike>) {
    this.options = { ...DEFAULT_OPTIONS, ...options }
    const g = globalThis as unknown as {
      AudioContext?: Ctor<AudioContextLike>
      webkitAudioContext?: Ctor<AudioContextLike>
    }
    const ctor = ctxCtor ?? g.AudioContext ?? g.webkitAudioContext
    if (ctor === undefined) throw new Error('当前环境无 Web Audio,PCM 播放器不可用')
    this.ctxCtor = ctor
  }

  /** 当前回合。设新值即隐式 flush 旧回合(抢占路径只调这一个)。 */
  setRound(roundId: string): void {
    if (roundId === this.currentRoundId) return
    this.flush()
    this.currentRoundId = roundId
    this.roundJustClaimed = true // 新回合首块淡入
  }

  get roundId(): string {
    return this.currentRoundId
  }

  /**
   * 收一块 PCM。返回是否真的收下了。
   *
   * false 有三种含义,调用方按需区分:
   *   - 旧 round 的迟到帧 → 正常丢弃(plan §23)
   *   - 声道数/采样率非法 → 参数不成立,排不进 createBuffer
   *   - 空块 → 没有可播内容
   *
   * 声道:协议只产出单声道(TTS 引擎 `channels=1` 硬编码,契约示例亦为 1),
   * 多声道交错在本播放器里**没有正确实现**(drain 只把全部样本写进声道 0,
   * 且帧数算错),所以显式拒绝而不是放行后播出错位音频。
   *
   * 样本完整性因此**不看奇偶**:`Int16Array.length` 是样本数,单声道下
   * 任意样本数都合法(包括 22977 这种奇数),用奇偶判损坏会误丢合法音频。
   */
  enqueue(block: PcmBlock): boolean {
    if (block.roundId !== this.currentRoundId) {
      bench.mark(bench.STALE_FRAME_DROP, {
        round_id: block.roundId,
        current: this.currentRoundId,
        seq: block.seq,
      })
      return false
    }
    if (block.channels !== MONO_CHANNELS) {
      logger.warn('audio', `不支持的声道数: ${String(block.channels)}(仅支持单声道)`)
      return false
    }
    if (!Number.isFinite(block.sampleRate) || block.sampleRate <= 0) {
      logger.warn('audio', `采样率非法: ${String(block.sampleRate)}`)
      return false
    }
    if (block.pcm.length === 0) {
      logger.warn('audio', 'PCM 块样本数为空')
      return false
    }
    // 单声道下任意样本数都是合法音频,不做任何奇偶/整帧判定。
    // 字节层是否完整由 decodePcm16 保证(奇数字节已在那里被拒绝)。

    const ctx = this.ensureContext()
    // plan §25:只观测,不自动干预。三者都要能看到:TTS PCM / AudioBuffer / AudioContext
    this.lastBufferRate = block.sampleRate
    if (block.sampleRate !== ctx.sampleRate && !this.sawMismatch) {
      this.sawMismatch = true
      logger.info(
        'audio',
        `采样率不一致: PCM=${block.sampleRate} AudioContext=${ctx.sampleRate},由播放链路重采样`,
      )
      this.options.onSampleRateMismatch?.(block.sampleRate, ctx.sampleRate)
      bench.mark(bench.AUDIOCONTEXT_RATE, {
        round_id: block.roundId,
        pcm_rate: block.sampleRate,
        ctx_rate: ctx.sampleRate,
        mismatch: true,
      })
    }

    const m = chunkAudioMetrics(block.pcm, block.sampleRate, block.channels)
    bench.mark(bench.CHUNK, {
      round_id: block.roundId,
      seq: block.seq,
      sample_rate: block.sampleRate,
      channels: block.channels,
      n_samples: block.pcm.length,
      peak: m.peak,
      rms: m.rms,
      duration_s: m.durationS,
    })

    this.pending.push(block)
    this.pendingSamples += block.pcm.length
    bench.mark(bench.P8, { round_id: block.roundId, seq: block.seq })
    this.drain()
    return true
  }

  /**
   * 清空:pending 队列 + 所有已 schedule 未播完的 source + 播放态。
   *
   * 淡出(PRD:打断清理):已 schedule 的 source 先 ~120ms gain ramp 到 0 再停,
   * 旧声让位不爆音;user_sent(first_frame 同)即调,~120ms 内旧回合余音消失。
   * ramp 期间该回合的新帧照常进队——它们属于同一回合,flush 只清「当时的余音」。
   */
  flush(): void {
    const n = this.live.size
    this.pending = []
    this.pendingSamples = 0
    const now = this.ctx?.currentTime ?? 0
    for (const s of this.live) {
      s.node.onended = null
      try {
        const g = s.gain.gain
        g.cancelScheduledValues?.(now)
        g.setValueAtTime(g.value, now)
        g.linearRampToValueAtTime(0, now + FLUSH_FADE_MS / 1000)
        // ramp 完再停;真实 AudioContext 的 stop(when) 精确到采样,假实现立即停也无碍
        s.node.stop(now + FLUSH_FADE_MS / 1000)
      } catch {
        // 已经结束的 source 再 stop 会抛,忽略即可
      }
    }
    this.live.clear()
    this.nextStartTime = 0
    if (this.playing) {
      this.playing = false
      this.broadcast(false)
    }
    if (n > 0) bench.mark(bench.T7, { round_id: this.currentRoundId, stopped: n })
  }

  onPlayback(cb: (active: boolean) => void): () => void {
    this.callbacks.add(cb)
    return () => this.callbacks.delete(cb)
  }

  stats(): PcmPlayerStats {
    return {
      scheduled: this.scheduled,
      active: this.live.size,
      pending: this.pending.length,
      pendingSeconds: this.pendingSamples / Math.max(1, this.ctx?.sampleRate ?? 1),
      contextSampleRate: this.ctx?.sampleRate ?? 0,
      bufferSampleRate: this.lastBufferRate,
    }
  }

  private ensureContext(): AudioContextLike {
    if (this.ctx !== null) return this.ctx
    const ctx = new this.ctxCtor()
    this.ctx = ctx
    if (ctx.state === 'suspended') void ctx.resume()
    return ctx
  }

  /** 缓冲不足 targetBufferSeconds 就不开新 source —— 这是「小块 + 小缓冲」的节流阀。 */
  private shouldSchedule(): boolean {
    const ctx = this.ctx
    if (ctx === null) return false
    const buffered = this.nextStartTime - ctx.currentTime
    if (this.live.size === 0) return true
    return buffered < this.options.targetBufferSeconds
  }

  private drain(): void {
    const ctx = this.ctx
    if (ctx === null || this.pending.length === 0) return
    if (!this.shouldSchedule()) {
      bench.mark(bench.BUFFER_DEPTH, {
        round_id: this.currentRoundId,
        pending: this.pending.length,
        buffered_s: this.nextStartTime - ctx.currentTime,
        scheduled: false,
      })
      return
    }

    const now = ctx.currentTime
    if (this.live.size === 0 || this.nextStartTime < now) {
      this.nextStartTime = now + this.options.scheduleAheadSeconds
    }

    const block = this.pending.shift()
    if (block === undefined) return
    this.pendingSamples -= block.pcm.length

    // createBuffer 的第二参是**帧数**,单声道下帧数 = 样本数(enqueue 已锁定
    // channels === MONO_CHANNELS,所以这里传样本数是对的)。
    const buffer = ctx.createBuffer(block.channels, block.pcm.length, block.sampleRate)
    buffer.copyToChannel(pcm16ToFloat32(block.pcm), 0)

    const node = ctx.createBufferSource()
    node.buffer = buffer

    // gain 节点挂 source 与 destination 之间:flush 淡出 ramp / 新回合首块淡入都走它
    const gain = ctx.createGain()
    node.connect(gain)
    gain.connect(ctx.destination)
    if (this.roundJustClaimed) {
      // 新回合首块 ~50ms 淡入(防爆音: PCM 块边界若从非零样本起播会「啪」一声)
      const t0 = this.nextStartTime
      gain.gain.setValueAtTime(0, t0)
      gain.gain.linearRampToValueAtTime(1, t0 + LEAD_IN_MS / 1000)
      this.roundJustClaimed = false
    }

    const duration = block.pcm.length / (block.sampleRate * block.channels)
    const startAt = this.nextStartTime
    this.nextStartTime = startAt + duration

    const entry: LiveSource = { node, endTime: this.nextStartTime, gain }
    this.live.add(entry)
    this.scheduled += 1

    node.onended = () => {
      this.live.delete(entry)
      this.drain()
      if (this.live.size === 0 && this.pending.length === 0) {
        this.nextStartTime = 0
        if (this.playing) {
          this.playing = false
          this.broadcast(false)
        }
      }
    }

    node.start(startAt)
    if (this.scheduled === 1) {
      bench.mark(bench.FIRST_SOURCE_SCHEDULED, {
        round_id: block.roundId,
        seq: block.seq,
        buffered_ms: Math.round(this.options.targetBufferSeconds * 1000),
      })
    }
    bench.mark(bench.BUFFER_DEPTH, {
      round_id: this.currentRoundId,
      pending: this.pending.length,
      buffered_s: this.nextStartTime - now,
      scheduled: true,
    })

    if (!this.playing) {
      this.playing = true
      this.broadcast(true)
    }

    // 一块排完可能又够了,继续排(通常只多排一块)
    if (this.shouldSchedule()) this.drain()
  }

  private broadcast(active: boolean): void {
    for (const cb of this.callbacks) cb(active)
  }
}