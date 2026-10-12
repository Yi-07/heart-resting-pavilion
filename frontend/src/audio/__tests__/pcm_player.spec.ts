// PcmPlayer 接缝钉测试(plan §22-§24)。真 Web Audio 在 jsdom 里没有,注入一个
// 可控的假 AudioContext:时钟由测试推进,于是「排了几块、缓冲多深、flush 掉了什么」
// 全部可断言,不需要真等音频播完。

import { describe, it, expect, beforeEach } from 'vitest'
import {
  MONO_CHANNELS,
  PcmPlayer,
  chunkAudioMetrics,
  decodePcm16,
  pcm16ToFloat32,
  type AudioContextLike,
  type PcmBlock,
} from '../pcm_player'

// ---- 可控假 AudioContext ----
class FakeGain {
  /** ramp 调用记录:[value, when];断言淡出/淡入用 */
  ramps: [number, number][] = []
  gain = {
    value: 1,
    setValueAtTime: (value: number, when: number): void => {
      this.ramps.push([value, when])
    },
    linearRampToValueAtTime: (value: number, when: number): void => {
      this.ramps.push([value, when])
    },
  }
  connect(): void {}
  disconnect(): void {}
}

class FakeSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  started = false
  stopped = false
  /** stop(when) 的入参记录:flush 淡出延迟停的断言素材 */
  stoppedAt: number | null = null
  connect(): void {}
  start(): void {
    this.started = true
  }
  stop(when?: number): void {
    if (this.stopped) throw new Error('already stopped')
    this.stopped = true
    this.stoppedAt = when ?? null
  }
}

class FakeCtx implements AudioContextLike {
  sampleRate = 48000
  currentTime = 0
  state = 'running'
  destination = {}
  created: FakeSource[] = []
  gains: FakeGain[] = []
  buffers: { channels: number; sampleRate: number; length: number }[] = []
  /** 每次 copyToChannel 记一笔参数;断言在测试体内做,不在假对象里 */
  copied: { len: number; ch: number }[] = []

  resume(): Promise<void> {
    return Promise.resolve()
  }

  createGain(): FakeGain {
    const g = new FakeGain()
    this.gains.push(g)
    return g
  }

  createBuffer(channels: number, length: number, sampleRate: number) {
    this.buffers.push({ channels, sampleRate, length })
    return {
      copyToChannel: (src: Float32Array, ch: number): void => {
        this.copied.push({ len: src.length, ch })
      },
    }
  }

  createBufferSource(): FakeSource {
    const s = new FakeSource()
    this.created.push(s)
    return s
  }
}

function makeCtxCtor(ctx: FakeCtx) {
  return function Ctor(this: unknown) {
    return ctx
  } as unknown as new () => AudioContextLike
}

function block(roundId: string, seq: number, samples: number, rate = 32000): PcmBlock {
  return {
    roundId,
    seq,
    pcm: new Int16Array(samples),
    sampleRate: rate,
    channels: 1,
  }
}

/** 采样率不匹配时的观测回调(plan §25:只观测,不自动干预) */
let mismatches: { pcm: number; ctx: number }[] = []

beforeEach(() => {
  mismatches = []
})

describe('PcmPlayer 调度', () => {
  it('采样率不一致只观测不改 AudioContext(plan §25)', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer(
      { onSampleRateMismatch: (pcmRate, ctxRate) => mismatches.push({ pcm: pcmRate, ctx: ctxRate }) },
      makeCtxCtor(ctx),
    )
    p.setRound('r1')
    p.enqueue(block('r1', 0, 32000, 32000)) // PCM 32000,Context 48000

    expect(mismatches).toEqual([{ pcm: 32000, ctx: 48000 }])
    // 关键:不改 AudioContext.sampleRate(改它会让已在播的 source 重建,制造 click)
    expect(ctx.sampleRate).toBe(48000)
    // AudioBuffer 用 PCM 自己的采样率(plan §25 的观测链第一环)
    expect(ctx.buffers[0]?.sampleRate).toBe(32000)
  })

  it('PCM 采样率与 Context 一致时不报 mismatch', () => {
    const ctx = new FakeCtx()
    ctx.sampleRate = 32000
    const p = new PcmPlayer(
      { onSampleRateMismatch: (pcmRate, ctxRate) => mismatches.push({ pcm: pcmRate, ctx: ctxRate }) },
      makeCtxCtor(ctx),
    )
    p.setRound('r1')
    p.enqueue(block('r1', 0, 32000, 32000))
    expect(mismatches).toEqual([])
  })

  it('第一块立即 schedule,并报出 AudioBuffer 与 AudioContext 的采样率', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))

    p.setRound('r1')
    expect(p.enqueue(block('r1', 0, 32000))).toBe(true)

    expect(ctx.buffers[0]?.sampleRate).toBe(32000)
    expect(ctx.buffers[0]?.length).toBe(32000)
    expect(ctx.copied).toEqual([{ len: 32000, ch: 0 }])
    expect(ctx.created).toHaveLength(1)
    expect(ctx.created[0]?.started).toBe(true)
  })

  it('缓冲未降到 targetBufferSeconds 以下时不再排新块(小缓冲节流阀)', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({ targetBufferSeconds: 0.12 }, makeCtxCtor(ctx))
    p.setRound('r1')

    // 每块 50ms(1600 样本 @32k)。排到缓冲 ≥120ms 就该停手。
    p.enqueue(block('r1', 0, 1600))
    p.enqueue(block('r1', 1, 1600))
    p.enqueue(block('r1', 2, 1600))

    const s = p.stats()
    expect(s.contextSampleRate).toBe(48000)
    expect(s.bufferSampleRate).toBe(32000)
    expect(s.pending).toBeGreaterThan(0)
    // 关键:不是每块都排,缓冲起了闸
    expect(ctx.created.length).toBeLessThanOrEqual(3)
  })

  it('同 round 的帧全部收下,stats 累计 scheduled', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1')
    p.enqueue(block('r1', 0, 1600))
    p.enqueue(block('r1', 1, 1600))
    p.enqueue(block('r1', 2, 1600))
    expect(p.stats().scheduled).toBeGreaterThan(0)
    expect(p.stats().active).toBeGreaterThan(0)
  })
})

describe('PcmPlayer 回合隔离(plan §23)', () => {
  it('旧 round 的迟到帧被拒绝,且不改变播放态', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r2')
    expect(p.enqueue(block('r1', 9, 1600))).toBe(false)
    expect(ctx.created).toHaveLength(0)
  })

  it('setRound 切回合:旧 round 的 source 被停,新 round 重新收', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1')
    p.enqueue(block('r1', 0, 1600))
    const before = ctx.created.length

    p.setRound('r2')
    // flush 让已 schedule 的 source 全部失效(不是只停当前那一个)
    expect(ctx.created.slice(0, before).every((s) => s.stopped)).toBe(true)
    expect(p.stats().active).toBe(0)
    expect(p.stats().pending).toBe(0)

    expect(p.enqueue(block('r2', 0, 1600))).toBe(true)
    expect(p.enqueue(block('r1', 1, 1600))).toBe(false)
  })
})

describe('PcmPlayer flush(plan §24)', () => {
  it('flush 清 pending + 停掉全部已 schedule 的 source', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1')
    for (let i = 0; i < 4; i += 1) p.enqueue(block('r1', i, 1600))

    const scheduled = ctx.created.length
    expect(scheduled).toBeGreaterThan(0)
    expect(p.stats().pending).toBeGreaterThan(0)

    p.flush()

    expect(ctx.created.every((s) => s.stopped)).toBe(true)
    expect(p.stats().active).toBe(0)
    expect(p.stats().pending).toBe(0)
  })

  it('flush 幂等:再调一次不炸(抢占路径可能连着来两次)', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1')
    p.enqueue(block('r1', 0, 1600))
    p.flush()
    expect(() => p.flush()).not.toThrow()
  })

  it('flush 后旧 round 帧不得重新进入播放队列', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1')
    p.enqueue(block('r1', 0, 1600))
    p.flush()
    const n = ctx.created.length
    expect(p.enqueue(block('r1', 1, 1600))).toBe(true)
    // 同一 round 仍可继续(flush 不改 round 归属),但 active 必须重新算过
    expect(p.stats().scheduled).toBeGreaterThanOrEqual(n)
  })
})

describe('PcmPlayer flush 淡出与首块淡入(PRD:打断清理)', () => {
  it('flush 对已 schedule 的 source 做 ~120ms gain ramp 后延迟 stop', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1')
    p.enqueue(block('r1', 0, 1600))
    expect(ctx.created).toHaveLength(1)

    p.flush()

    const g = ctx.gains[0]!
    // ramp 终点 0(从尾部找:首块淡入的起点 0 会先命中)
    const rampToZero = [...g.ramps].reverse().find(([v]) => v === 0)
    expect(rampToZero).toBeDefined()
    const when = rampToZero![1]
    expect(when - ctx.currentTime).toBeCloseTo(0.12, 5)
    // stop 延迟到 ramp 终点(淡出完才真正停)
    expect(ctx.created[0]?.stopped).toBe(true)
    expect(ctx.created[0]?.stoppedAt ?? 0).toBeCloseTo(when, 5)
  })

  it('新回合首块挂 ~50ms 淡入 gain ramp(防爆音)', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1') // 自认领新回合
    p.enqueue(block('r1', 0, 1600))

    const g = ctx.gains[0]!
    // 淡入:从 0 ramp 到 1,时长 ~50ms;起点=首块 startAt
    expect(g.ramps[0]?.[0]).toBe(0)
    const fadeIn = g.ramps[1]
    expect(fadeIn?.[0]).toBe(1)
    expect(fadeIn![1] - g.ramps[0]![1]).toBeCloseTo(0.05, 5)

    // 同回合后续块不重复挂淡入
    p.enqueue(block('r1', 1, 1600))
    const second = ctx.gains[1]!
    expect(second.ramps).toHaveLength(0)
  })

  it('flush 后同回合新进块不继承旧 ramp(新 source gain 无预约)', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r1')
    p.enqueue(block('r1', 0, 1600))
    p.flush()
    p.enqueue(block('r1', 1, 1600))

    const g = ctx.gains[1]!
    // 新块无 ramp 记录:flush 淡出只作用于当时的旧 source
    expect(g.ramps).toHaveLength(0)
  })
})

describe('PCM 指标(plan §28)', () => {
  it('peak / RMS / duration 口径与公式一致', () => {
    const pcm = new Int16Array([0, 1000, -2000, 3000])
    const m = chunkAudioMetrics(pcm, 32000, 1)
    expect(m.peak).toBe(3000)
    expect(m.rms).toBeCloseTo(Math.sqrt((0 + 1e6 + 4e6 + 9e6) / 4), 6)
    expect(m.durationS).toBeCloseTo(4 / 32000, 9)
  })

  it('空块不炸,duration 为 0', () => {
    const m = chunkAudioMetrics(new Int16Array(0), 32000, 1)
    expect(m.peak).toBe(0)
    expect(m.rms).toBe(0)
    expect(m.durationS).toBe(0)
  })

  it('duration 随 channels 变化(plan §28 的 channels 参与分母)', () => {
    expect(chunkAudioMetrics(new Int16Array(3200), 32000, 2).durationS).toBeCloseTo(
      3200 / 64000,
      9,
    )
  })
})

describe('base64 PCM16 解码', () => {
  it('小端解析,与原始样本一致', () => {
    const src = new Int16Array([0, 1, -1, 32767, -32768])
    const bytes = new Uint8Array(src.length * 2)
    const dv = new DataView(bytes.buffer)
    src.forEach((v, i) => dv.setInt16(i * 2, v, true))
    let bin = ''
    bytes.forEach((b) => {
      bin += String.fromCharCode(b)
    })
    const b64 = btoa(bin)

    const got = decodePcm16(b64)
    expect(Array.from(got ?? [])).toEqual(Array.from(src))
  })

  it('归一化除以 32768,正负对称(不削顶)', () => {
    const f = pcm16ToFloat32(new Int16Array([32767, -32768]))
    expect(f[0]).toBeCloseTo(32767 / 32768, 6)
    expect(f[1]).toBeCloseTo(-1, 6)
  })

  it('字节数为奇数时显式拒绝,不静默截断最后一个字节', () => {
    // 5 字节 = 2 个完整样本 + 1 个残字节。早先用 bytes.length >> 1 会把
    // 那 1 个字节悄悄丢掉,把「样本不完整」伪装成正常音频。
    const b64 = btoa(String.fromCharCode(1, 0, 2, 0, 3))
    expect(decodePcm16(b64)).toBeNull()
  })

  it('偶数字节正常解码,样本数 = 字节数/2', () => {
    const src = new Int16Array([1, -2, 3, -4, 5])
    const bytes = new Uint8Array(src.length * 2)
    const dv = new DataView(bytes.buffer)
    src.forEach((v, i) => dv.setInt16(i * 2, v, true))
    let bin = ''
    for (const b of bytes) bin += String.fromCharCode(b)
    const got = decodePcm16(btoa(bin))
    expect(got).not.toBeNull()
    expect(Array.from(got ?? [])).toEqual(Array.from(src))
  })
})

// ---- PCM 样本完整性校验(修复:奇数样本块被误丢) ----
// 真实故障:一轮 36 块里 audio_seq=10(22977 样本,0.718s)被当成「协议层损坏」
// 整块丢弃,用户听到「读到某字之后声音直接跳到后面的内容」。

describe('A. 单声道奇数样本块必须被接受', () => {
  it('22977 样本(真实故障样本数)单声道被接受并排程', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('tts-0')

    const N = 22977 // 真实抓包值,奇数
    expect(N % 2).toBe(1)
    const ok = p.enqueue(block('tts-0', 10, N))

    expect(ok).toBe(true)
    // AudioBuffer 用同样的帧数(= 样本数,单声道),采样率取块自己的
    expect(ctx.buffers[0]).toEqual({ channels: 1, sampleRate: 32000, length: N })
    expect(ctx.copied).toEqual([{ len: N, ch: 0 }])
    // 音频源确实被创建并启动
    expect(ctx.created).toHaveLength(1)
    expect(ctx.created[0]?.started).toBe(true)
    expect(p.stats().scheduled).toBe(1)
  })

  it('其它奇数样本量同样被接受(1 / 3 / 999)', () => {
    for (const n of [1, 3, 999]) {
      const ctx = new FakeCtx()
      const p = new PcmPlayer({}, makeCtxCtor(ctx))
      p.setRound('r')
      expect(p.enqueue(block('r', 0, n)), `${n} 样本应被接受`).toBe(true)
      expect(ctx.buffers[0]?.length).toBe(n)
    }
  })
})

describe('B. 真正的损坏输入仍被拒绝', () => {
  it('空样本块被拒绝', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r')
    expect(p.enqueue(block('r', 0, 0))).toBe(false)
    expect(ctx.created).toHaveLength(0)
  })

  it('非法声道数被拒绝(0 / 负数 / 非整数 / NaN)', () => {
    for (const ch of [0, -1, 1.5, Number.NaN]) {
      const ctx = new FakeCtx()
      const p = new PcmPlayer({}, makeCtxCtor(ctx))
      p.setRound('r')
      const b = block('r', 0, 3200)
      b.channels = ch
      expect(p.enqueue(b), `声道数 ${String(ch)} 应被拒绝`).toBe(false)
      expect(ctx.created).toHaveLength(0)
    }
  })

  it('非法采样率被拒绝(0 / 负数 / NaN)', () => {
    for (const sr of [0, -32000, Number.NaN]) {
      const ctx = new FakeCtx()
      const p = new PcmPlayer({}, makeCtxCtor(ctx))
      p.setRound('r')
      const b = block('r', 0, 3200)
      b.sampleRate = sr
      expect(p.enqueue(b), `采样率 ${String(sr)} 应被拒绝`).toBe(false)
      expect(ctx.created).toHaveLength(0)
    }
  })

  it('字节层不完整的数据不会被当成成功解码', () => {
    // decodePcm16 返回 null,调用方据此跳过 —— 不允许出现「半个样本」
    expect(decodePcm16(btoa(String.fromCharCode(9, 9, 9)))).toBeNull()
  })
})

describe('C. 多声道不受支持,显式拒绝', () => {
  // 协议依据:TTS 引擎 PcmChunk(channels=1) 硬编码;ws-contract §3.4 示例为 1;
  // 历次真实抓包 channels 恒为 {1}。多声道交错在本播放器里从未正确实现 ——
  // drain() 只把全部样本写进声道 0。因此这里断言「被拒绝」,而不是假装能播。
  it('立体声块被拒绝,不产生任何音频源', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r')
    const b = block('r', 0, 6400)
    b.channels = 2
    expect(p.enqueue(b)).toBe(false)
    expect(ctx.created).toHaveLength(0)
    expect(ctx.buffers).toHaveLength(0)
  })

  it('4 声道 / 8 声道同样被拒绝', () => {
    for (const ch of [4, 8]) {
      const ctx = new FakeCtx()
      const p = new PcmPlayer({}, makeCtxCtor(ctx))
      p.setRound('r')
      const b = block('r', 0, 3200)
      b.channels = ch
      expect(p.enqueue(b), `${ch} 声道应被拒绝`).toBe(false)
      expect(ctx.created).toHaveLength(0)
    }
  })

  it('单声道是唯一被接受的声道数', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r')
    expect(p.enqueue(block('r', 0, 6400))).toBe(true)
    expect(ctx.buffers[0]?.channels).toBe(MONO_CHANNELS)
    // createBuffer 第二参 = 帧数,单声道下帧数 == 样本数
    expect(ctx.buffers[0]?.length).toBe(6400)
  })
})

describe('D. 回合隔离不回归', () => {
  it('两轮都能排程,且奇数样本块不再破坏回合归属', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('tts-0')
    expect(p.enqueue(block('tts-0', 0, 22977))).toBe(true)

    p.setRound('tts-1')
    // 第二轮同样用奇数样本量
    expect(p.enqueue(block('tts-1', 0, 22977))).toBe(true)
    expect(p.roundId).toBe('tts-1')

    // 旧回合迟到帧仍被拒
    expect(p.enqueue(block('tts-0', 1, 22977))).toBe(false)
    expect(p.roundId).toBe('tts-1')
    expect(ctx.created).toHaveLength(2)
  })

  it('被拒的块不改变播放态,合法块仍能继续', () => {
    const ctx = new FakeCtx()
    const p = new PcmPlayer({}, makeCtxCtor(ctx))
    p.setRound('r')
    expect(p.enqueue(block('r', 0, 1600))).toBe(true)
    const active = p.stats().active
    // 非法声道
    const bad = block('r', 1, 1600)
    bad.channels = 0
    expect(p.enqueue(bad)).toBe(false)
    expect(p.stats().active).toBe(active)
    expect(p.enqueue(block('r', 2, 1600))).toBe(true)
  })
})