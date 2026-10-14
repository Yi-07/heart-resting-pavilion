// 音频总入口:按 audio_chunk.format 分派到 legacy wav 队列或 PCM 流式播放器。
//
// 为什么不直接改 queue.ts:它承担安抚语/总结语/危机热线这些**单发**路径,
// 那些场景整句 wav 一次到位,用 <audio> 简单可靠。改成 Web Audio 调度器只会
// 给它们增加回归面,收益为零。所以两条链路并存,由 format 决定走哪条。
//
// 分派规则(契约,不是启发式):
//   format === 'pcm_s16le' → PcmPlayer(round_id 隔离 + flush)
//   format === 'wav'       → AudioQueue(legacy <audio> 队列)
// 未知 format 一律按 wav 处理并记一条 warn —— 宁可退回已知可用路径,
// 不要因为服务端加了新编码就整段没声音。
//
// 回合仲裁两条链路共用同一套 currentRoundId/seenRounds(§3.4):
// PCM 首块与预置 wav 组号(preset-*)都能认领回合——新组双链 flush 后接管
// (setRound = legacy stopAndFade + pcm flush),同组排队续播,旧组迟到帧丢弃。
// 真重叠场景(总结 PCM 播放中点心情回执)由此收敛为「旧声淡出、新声独播」。

import type { AudioChunk } from '../ws/messages'
import { logger } from '../logger'
import { bench } from './bench'
import { AudioQueue, type VoiceFactory } from './queue'
import { PcmPlayer, decodePcm16, type AudioContextLike } from './pcm_player'

export interface AudioHubOptions {
  /** PCM 目标缓冲深度(秒);plan §22 的 80/120/200ms 由 benchmark 定 */
  targetBufferSeconds?: number
  createVoice?: VoiceFactory
  ctxCtor?: new (...args: never[]) => AudioContextLike
  /** bench 上报开关 */
  benchEnabled?: boolean
}

export class AudioHub {
  private readonly legacy: AudioQueue
  private readonly pcm: PcmPlayer | null
  private currentRoundId = ''
  /** 本连接见过的所有 round_id(按到达顺序)。用于区分「新回合」与「旧回合迟到帧」。 */
  private readonly seenRounds = new Set<string>()

  constructor(options: AudioHubOptions = {}) {
    this.legacy = new AudioQueue(options.createVoice)
    // 无 Web Audio 的环境(jsdom / 老浏览器)降级为 legacy,不留 null 分支给调用方
    try {
      this.pcm = new PcmPlayer(
        options.targetBufferSeconds === undefined
          ? {}
          : { targetBufferSeconds: options.targetBufferSeconds },
        options.ctxCtor,
      )
    } catch (err) {
      logger.warn('audio', `PCM 播放器不可用,PCM 流式降级为不播放: ${String(err)}`)
      this.pcm = null
    }
  }

  /**
   * 显式切回合。**一般不需要主动调** —— round 由第一块带 round_id 的帧自���认领。
   *
   * 保留这个方法是为了「抢占但新回合还没发出任何音频」的窗口:
   * first_frame 到了、音频还没来,这时把旧回合的余音立刻掐掉。
   */
  setRound(roundId: string): void {
    if (roundId === this.currentRoundId) return
    this.currentRoundId = roundId
    this.seenRounds.add(roundId)
    this.legacy.stopAndFade()
    this.pcm?.setRound(roundId)
  }

  get roundId(): string {
    return this.currentRoundId
  }

  enqueue(chunk: AudioChunk): void {
    if (chunk.format !== 'pcm_s16le') {
      if (chunk.format !== 'wav') {
        logger.warn('audio', `未知音频格式,按 wav 处理: ${chunk.format}`)
      }
      if (chunk.round_id === undefined) {
        // 缺组号:无仲裁依据,按 legacy 现状入队(整句到齐才播,可观测降级)
        logger.warn('audio', 'wav 帧缺 round_id,无组仲裁,按 legacy 入队')
        this.legacy.enqueue(chunk)
        return
      }
      // 组路由(§3.4「预置 wav 组号」):与 PCM 共用回合状态。
      // 新组(没见过)→ setRound 双链 flush 后接管;同组 → legacy 队列顺播
      // (危机两句同组,顺序契约靠它保);旧组(见过但非当前)→ 迟到帧丢弃。
      const incoming = chunk.round_id
      if (this.currentRoundId === '') {
        this.setRound(incoming)
      } else if (incoming !== this.currentRoundId) {
        if (!this.seenRounds.has(incoming)) {
          this.setRound(incoming)
        } else {
          bench.mark(bench.STALE_FRAME_DROP, {
            round_id: incoming,
            current: this.currentRoundId,
            audio_seq: -1,
          })
          return
        }
      }
      this.legacy.enqueue(chunk)
      return
    }
    if (this.pcm === null) {
      logger.warn('audio', '收到 PCM 块但 PCM 播放器不可用,跳过该块')
      return
    }

    const incoming = chunk.round_id
    if (incoming === undefined) {
      // 服务端没带 round_id:无法做回合隔离,按当前回合处理并记一条 warn。
      // 不静默 —— 这正是「协议没跟上」该被发现的时刻。
      logger.warn('audio', 'PCM 块缺 round_id,无法隔离回合')
      const bare = decodePcm16(chunk.data)
      if (bare === null) return
      this.pcm.enqueue({
        roundId: this.currentRoundId,
        seq: chunk.audio_seq ?? chunk.seq,
        pcm: bare,
        sampleRate: chunk.sample_rate ?? 32000,
        channels: chunk.channels ?? 1,
      })
      return
    }

    if (this.currentRoundId === '') {
      // 自认领首个回合:answer 路不发 first_frame,不能要求外部先 setRound
      this.setRound(incoming)
    } else if (incoming !== this.currentRoundId) {
      // 没见过的 round_id = **新回合**,不是旧帧。
      //
      // 曾经这里只有「认领第一个」和「丢弃不匹配的」两种结果,于是 currentRoundId
      // 一旦被 tts-0 占住就再也不更新:第二轮的 tts-1 被当成旧回合迟到帧整轮丢掉。
      // 症状是后端 pcm_sent 正常、浏览器完全无声(实测两轮各 21/27 帧全部抵达)。
      // flush() 不复位 currentRoundId(它的语义是「停声」不是「换回合」),
      // 而 answer 路连 first_frame 都不发 —— 没有任何外部信号能推进它,只能自认领。
      if (!this.seenRounds.has(incoming)) {
        this.setRound(incoming)
      } else {
        // 见过的旧 round 迟到帧:正常丢弃,但必须留下可观测记录(plan §14.3/§23)
        bench.mark(bench.STALE_FRAME_DROP, {
          round_id: incoming,
          current: this.currentRoundId,
          audio_seq: chunk.audio_seq ?? -1,
        })
        return
      }
    }

    const decoded = decodePcm16(chunk.data)
    if (decoded === null) return
    this.pcm.enqueue({
      roundId: incoming,
      seq: chunk.audio_seq ?? chunk.seq,
      pcm: decoded,
      sampleRate: chunk.sample_rate ?? 32000,
      channels: chunk.channels ?? 1,
    })
  }

  /** cancel / audio_stop → 两条链路一起停(plan §24) */
  flush(): void {
    this.pcm?.flush()
    this.legacy.stopAndFade()
  }

  onPlayback(cb: (active: boolean) => void): () => void {
    const offPcm = this.pcm?.onPlayback(cb) ?? (() => undefined)
    const offLegacy = this.legacy.onPlayback(cb)
    return () => {
      offPcm()
      offLegacy()
    }
  }

  /** 只读快照,供 benchmark / 调试面板 */
  stats(): ReturnType<PcmPlayer['stats']> | null {
    return this.pcm?.stats() ?? null
  }
}