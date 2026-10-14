// AudioHub 回合推进回归测试。
//
// 钉的是实测故障:第一轮有声音、第二轮完全无声。
// 证据链:后端两轮 PCM 都完整送达(tts-0 21 帧 / tts-1 27 帧,audio_seq 连续),
// 但 AudioHub 只认领过 tts-0,此后 currentRoundId 再不更新,tts-1 被整轮丢弃。
//
// 这里同时钉住另一半语义:新回合推进后,**旧回合**的迟到帧仍必须被丢 ——
// 否则「抢占后旧音频继续出声」会重新变成 bug。

import { describe, it, expect } from 'vitest'
import { AudioHub } from '../index'
import type { AudioContextLike } from '../pcm_player'

class FakeSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  stopped = false
  startTimes: number[] = []
  connect(): void {}
  start(when?: number): void {
    this.startTimes.push(when ?? 0)
  }
  stop(): void {
    this.stopped = true
  }
}

class FakeCtx implements AudioContextLike {
  sampleRate = 48000
  currentTime = 0
  state = 'running'
  destination = {}
  created: FakeSource[] = []
  resume(): Promise<void> {
    return Promise.resolve()
  }
  createGain(): {
    gain: { value: number; setValueAtTime(): void; linearRampToValueAtTime(): void }
    connect(): void
    disconnect(): void
  } {
    return {
      gain: { value: 1, setValueAtTime: () => {}, linearRampToValueAtTime: () => {} },
      connect: () => {},
      disconnect: () => {},
    }
  }
  createBuffer(_ch: number, length: number, sampleRate: number) {
    return {
      copyToChannel: (_src: Float32Array, _ch: number): void => {
        void length
        void sampleRate
      },
    }
  }
  createBufferSource(): FakeSource {
    const s = new FakeSource()
    this.created.push(s)
    return s
  }
}

function makeHub(): { hub: AudioHub; ctx: FakeCtx } {
  const ctx = new FakeCtx()
  const hub = new AudioHub(
    { ctxCtor: function Ctor(this: unknown) {
      return ctx
    } as unknown as new () => AudioContextLike },
  )
  return { hub, ctx }
}

/** 一块最小可用的 PCM16 chunk(样本数取偶数,避开协议层校验) */
function chunk(roundId: string, audioSeq: number, samples = 1600) {
  const bytes = new Uint8Array(samples * 2)
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return {
    type: 'audio_chunk' as const,
    seq: audioSeq + 1,
    format: 'pcm_s16le' as const,
    data: btoa(bin),
    final: false,
    round_id: roundId,
    audio_seq: audioSeq,
    sample_rate: 32000,
    channels: 1,
  }
}

describe('AudioHub 连续两轮播放', () => {
  it('第二轮的 round_id 未被丢弃 —— 覆盖实测的「第二次询问无声」', () => {
    const { hub, ctx } = makeHub()

    // 第一轮
    hub.enqueue(chunk('tts-0', 0))
    hub.enqueue(chunk('tts-0', 1))
    expect(hub.roundId).toBe('tts-0')
    const afterRound1 = ctx.created.length
    expect(afterRound1).toBeGreaterThan(0)

    // 第二轮:这是修复前会被整轮丢掉的部分
    hub.enqueue(chunk('tts-1', 0))
    hub.enqueue(chunk('tts-1', 1))
    expect(hub.roundId).toBe('tts-1')
    expect(ctx.created.length).toBeGreaterThan(afterRound1)
  })

  it('first_frame 触发的 flush 后,新回合仍能出声(collect 路)', () => {
    const { hub, ctx } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    const afterRound1 = ctx.created.length

    // App.vue 在 first_frame 里调 flush():只停声,不改回合归属
    hub.flush()
    expect(hub.roundId).toBe('tts-0')

    hub.enqueue(chunk('tts-1', 0))
    expect(hub.roundId).toBe('tts-1')
    expect(ctx.created.length).toBeGreaterThan(afterRound1)
  })

  it('切到新回合时旧回合已排程的 source 全部失效', () => {
    const { hub, ctx } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    hub.enqueue(chunk('tts-0', 1))

    hub.enqueue(chunk('tts-1', 0))

    const stillPlaying = ctx.created.filter((s) => !s.stopped)
    // 旧回合的 source 必须已被停掉,不能盖在新回合开头上
    expect(stillPlaying.length).toBeGreaterThan(0)
    expect(ctx.created.slice(0, stillPlaying.length).every((s) => s.stopped)).toBe(true)
  })
})

describe('AudioHub 旧回合迟到帧仍被丢弃', () => {
  it('新回合已推进后,旧 round 的迟到帧不重新出声', () => {
    const { hub, ctx } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    hub.enqueue(chunk('tts-1', 0))
    expect(hub.roundId).toBe('tts-1')

    const before = ctx.created.length
    // tts-0 见过 → 判定为迟到帧,丢弃
    hub.enqueue(chunk('tts-0', 9))
    expect(hub.roundId).toBe('tts-1')
    expect(ctx.created.length).toBe(before)
  })

  it('抢占场景:tts-0 在播,tts-1 接管,随后 tts-0 迟到帧被丢', () => {
    const { hub } = makeHub()
    for (let i = 0; i < 4; i += 1) hub.enqueue(chunk('tts-0', i))
    hub.enqueue(chunk('tts-1', 0))
    expect(hub.roundId).toBe('tts-1')

    const stats = hub.stats()
    expect(stats).not.toBeNull()
    // 旧回合不该把 pending 重新灌满
    const pendingBefore = stats?.pending ?? 0
    hub.enqueue(chunk('tts-0', 4))
    expect(hub.roundId).toBe('tts-1')
    expect(stats?.pending ?? 0).toBeLessThanOrEqual(pendingBefore)
  })
})

describe('AudioHub 缺 round_id 的兜底不回归', () => {
  it('不带 round_id 的 PCM 块按当前回合处理,不被当作新回合', () => {
    const { hub } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    expect(hub.roundId).toBe('tts-0')

    const bare = chunk('tts-0', 1)
    delete (bare as { round_id?: string }).round_id
    hub.enqueue(bare)
    expect(hub.roundId).toBe('tts-0')
  })
})

// ---- wav 预置组号仲裁(契约 §3.4「预置 wav 组号」,T6) ----

function wav(seq: number, roundId: string | undefined, data = `w${seq}`) {
  return {
    type: 'audio_chunk' as const,
    seq,
    format: 'wav' as const,
    data,
    final: true,
    round_id: roundId,
  }
}

describe('AudioHub wav 组仲裁', () => {
  function makeRoutedHub(): {
    hub: AudioHub
    ctx: FakeCtx
    played: string[]
    ended: (() => void)[]
  } {
    const ctx = new FakeCtx()
    const played: string[] = []
    const ended: (() => void)[] = []
    const hub = new AudioHub({
      ctxCtor: function Ctor(this: unknown) {
        return ctx
      } as unknown as new () => AudioContextLike,
      createVoice: (c) => {
        played.push(c.data)
        return {
          volume: 1,
          play: () => undefined,
          pause: () => undefined,
          addEventListener: (_ev, cb) => {
            ended.push(cb)
          },
        }
      },
    })
    return { hub, ctx, played, ended }
  }

  it('同组排队续播:危机两句同组,顺播不互掐', () => {
    const { hub, played, ended } = makeRoutedHub()
    hub.enqueue(wav(1, 'preset-crisis-1'))
    hub.enqueue(wav(2, 'preset-crisis-1'))
    expect(hub.roundId).toBe('preset-crisis-1')
    // 第一块起播、第二块在队(队列语义:前块 ended 才起播)
    expect(played).toEqual(['w1'])
    ended[0]?.()
    expect(played).toEqual(['w1', 'w2']) // 同组顺播不互掐
  })

  it('新组接管:总结 PCM 播放中点心情回执 → 双链 flush 后独播(验收 6)', () => {
    const { hub, ctx } = makeHub()
    // 总结 PCM 在播
    for (let i = 0; i < 3; i += 1) hub.enqueue(chunk('tts-0', i))
    const playing = ctx.created.filter((s) => !s.stopped)
    expect(playing.length).toBeGreaterThan(0)

    // 心情回执 wav 新组到达
    hub.enqueue(wav(10, 'preset-mood-1'))
    expect(hub.roundId).toBe('preset-mood-1')
    // 双链 flush:旧 PCM 已排程 source 全停
    expect(ctx.created.filter((s) => !s.stopped).length).toBe(0)
    expect(hub.stats()?.pending).toBe(0)
  })

  it('新组接管方向对称:wav 在播、PCM 新组到达同样接管并掐 legacy 链', () => {
    const { hub, played, ended } = makeRoutedHub()
    hub.enqueue(wav(1, 'preset-crisis-1'))
    expect(hub.roundId).toBe('preset-crisis-1')

    hub.enqueue(chunk('tts-1', 0)) // PCM 新组
    expect(hub.roundId).toBe('tts-1')
    // legacy 链被 setRound 的 stopAndFade 断链: crisis 播完不再续播任何 wav
    ended[0]?.()
    expect(played).toEqual(['w1'])
  })

  it('旧组迟到帧丢弃:回执已接管后,旧总结组 wav 不再出声', () => {
    const { hub, played } = makeRoutedHub()
    hub.enqueue(wav(1, 'preset-mood-1'))
    expect(hub.roundId).toBe('preset-mood-1')

    hub.enqueue(wav(2, 'preset-wait-0')) // 新组接管
    expect(hub.roundId).toBe('preset-wait-0')

    hub.enqueue(wav(3, 'preset-mood-1')) // 旧组迟到帧
    expect(hub.roundId).toBe('preset-wait-0') // 不认领、不回播
    expect(played).toEqual(['w1', 'w2']) // w3 未入队
  })

  it('缺组号 wav 按 legacy 入队,不惊动回合状态', () => {
    const { hub, played } = makeRoutedHub()
    hub.enqueue(chunk('tts-0', 0))
    expect(hub.roundId).toBe('tts-0')

    hub.enqueue(wav(5, undefined))
    expect(hub.roundId).toBe('tts-0') // 组号缺失不改归属
    expect(played).toEqual(['w5']) // 照常进 legacy 队列
  })

  it('同回合等待语音(无组号)不破坏总结 PCM 归属——实测回归钉', () => {
    // 时序:问话 PCM(tts-5)认领 → 等待语音 wav(无组号,回合内过客)→
    // 总结 PCM 回归(与问话同组 tts-5)。等待语音若抢组号,总结会被判
    // 旧组迟到帧整段丢掉(实测回归);无组号走 legacy,归属不受扰。
    const { hub, ctx } = makeHub()
    hub.enqueue(chunk('tts-5', 0)) // 问话 PCM:认领 tts-5
    hub.enqueue(wav(1, undefined)) // 等待语音:legacy,不碰回合状态
    expect(hub.roundId).toBe('tts-5')
    const before = ctx.created.length
    hub.enqueue(chunk('tts-5', 10)) // 总结 PCM 回归(同 trace 同组)
    expect(hub.roundId).toBe('tts-5')
    expect(ctx.created.length).toBeGreaterThan(before) // 总结必须出声
  })
})