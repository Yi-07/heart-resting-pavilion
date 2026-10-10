// 回合 ID 边界语义验证。
//
// 覆盖 5 个边界,其中第 3 项是**已确认的协议限制**,不是待修的 bug:
// 协议没有把回合顺序暴露给前端(见文件末尾「协议限制」),所以
// 「没见过的 round_id」在前端无法区分「新回合」与「迟到的未知旧回合」。
// 这里把当前行为钉死并写明依据,避免以后有人误以为它已被解决。

import { describe, it, expect } from 'vitest'
import { AudioHub } from '../index'
import type { AudioContextLike } from '../pcm_player'

class FakeSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  stopped = false
  connect(): void {}
  start(): void {}
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
  createBuffer(_c: number, _l: number, _s: number): { copyToChannel: () => void } {
    return { copyToChannel: () => {} }
  }
  createBufferSource(): FakeSource {
    const s = new FakeSource()
    this.created.push(s)
    return s
  }
}

function makeHub(): { hub: AudioHub; ctx: FakeCtx } {
  const ctx = new FakeCtx()
  const hub = new AudioHub({
    ctxCtor: function Ctor(this: unknown) {
      return ctx
    } as unknown as new () => AudioContextLike,
  })
  return { hub, ctx }
}

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

describe('边界 1:正常连续回合', () => {
  it('tts-0 后接 tts-1,第二轮正常排程', () => {
    const { hub, ctx } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    const r1 = ctx.created.length
    expect(r1).toBeGreaterThan(0)
    expect(hub.roundId).toBe('tts-0')

    hub.enqueue(chunk('tts-1', 0))
    expect(hub.roundId).toBe('tts-1')
    expect(ctx.created.length).toBeGreaterThan(r1)
  })
})

describe('边界 2:已出现过的旧回合迟到帧', () => {
  it('新回合建立后,旧回合帧仍被丢弃', () => {
    const { hub, ctx } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    hub.enqueue(chunk('tts-1', 0))
    expect(hub.roundId).toBe('tts-1')

    const before = ctx.created.length
    hub.enqueue(chunk('tts-0', 5))
    expect(hub.roundId).toBe('tts-1')
    expect(ctx.created.length).toBe(before)
  })
})

describe('边界 3:尚未出现过的旧回合首帧迟到【协议限制】', () => {
  it('当前实现会认领它 —— 这是协议限制,不是回归', () => {
    const { hub } = makeHub()
    // 新回合先建立
    hub.enqueue(chunk('tts-1', 0))
    expect(hub.roundId).toBe('tts-1')

    // 一个**更早**、但此前从未出现过的回合,首帧迟到
    hub.enqueue(chunk('tts-0', 0))

    // 实际行为:被当成新回合认领,抢回当前回合。
    // 期望值刻意写成实际行为 —— 若将来协议补上回合顺序信号,
    // 这条断言会失败,提醒维护者同步更新成「仍为 tts-1」。
    expect(hub.roundId).toBe('tts-0')
  })

  it('协议限制的成因:前端拿不到回合顺序', () => {
    // 契约层能用的排序字段只有:
    //   - audio_seq:回合内单调,跨回合会重置 → 不能用来判回合新旧
    //   - seq      :连接级单调,但抢占后旧回合的 in-flight 帧可能拿到更大的 seq
    //   - round_id :不透明字符串,契约未规定可解析出单调编号
    // 因此「没见过的 round_id」无法在前端区分新旧。
    // 详见交付报告中的协议限制一节。
    const { hub } = makeHub()
    hub.enqueue(chunk('tts-7', 0))
    expect(hub.roundId).toBe('tts-7')
    // 纯字典序与到达序无关:证明前端没有、也不应依赖字符串排序
    hub.enqueue(chunk('tts-2', 0))
    expect(hub.roundId).toBe('tts-2')
  })
})

describe('边界 4:新回合抢占时旧音频停止', () => {
  it('旧回合已排程的 source 全部被停', () => {
    const { hub, ctx } = makeHub()
    for (let i = 0; i < 4; i += 1) hub.enqueue(chunk('tts-0', i))
    const before = ctx.created.length
    expect(before).toBeGreaterThan(0)

    hub.enqueue(chunk('tts-1', 0))

    const old = ctx.created.slice(0, before)
    expect(old.length).toBeGreaterThan(0)
    expect(old.every((s) => s.stopped)).toBe(true)
    expect(hub.stats()?.active).toBe(1)
  })
})

describe('边界 5:flush 不破坏下一轮归属', () => {
  it('flush 只停声,不改 round;下一轮仍能自认领', () => {
    const { hub, ctx } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    expect(hub.roundId).toBe('tts-0')

    hub.flush()
    // flush 的语义是「停声」,不是「换回合」
    expect(hub.roundId).toBe('tts-0')
    expect(hub.stats()?.active).toBe(0)
    expect(hub.stats()?.pending).toBe(0)

    const after = ctx.created.length
    hub.enqueue(chunk('tts-1', 0))
    expect(hub.roundId).toBe('tts-1')
    expect(ctx.created.length).toBeGreaterThan(after)
  })

  it('flush 之后当前回合自己的后续帧仍可继续播放', () => {
    const { hub } = makeHub()
    hub.enqueue(chunk('tts-0', 0))
    hub.flush()
    // flush 不改归属,所以同一回合的下一帧仍应被接受
    expect(hub.roundId).toBe('tts-0')
    hub.enqueue(chunk('tts-0', 1))
    expect(hub.roundId).toBe('tts-0')
  })
})