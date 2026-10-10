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