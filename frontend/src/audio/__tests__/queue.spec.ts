// audio/queue 接缝钉测试(frontend-plan §8):入队顺序播放、抢占淡出清队断链、
// onPlayback 广播、播放失败跳块。
import { describe, expect, it, vi } from 'vitest'
import { AudioQueue, type VoiceLike } from '../queue'
import type { AudioChunk } from '../../ws/messages'

class FakeVoice implements VoiceLike {
  volume = 1
  paused = false
  played = 0
  ended: (() => void) | null = null
  constructor(readonly tag: string) {}

  play(): void {
    this.played += 1
  }

  pause(): void {
    this.paused = true
  }

  addEventListener(_event: 'ended', listener: () => void): void {
    this.ended = listener
  }

  finish(): void {
    this.ended?.()
  }
}

function chunk(seq: number): AudioChunk {
  return { type: 'audio_chunk', seq, format: 'wav', data: `fake-${seq}`, final: true }
}

function at(voices: FakeVoice[], i: number): FakeVoice {
  const v = voices[i]
  if (v === undefined) throw new Error(`voices[${i}] 未创建`)
  return v
}

function flush(times = 8, stepMs = 25): Promise<void> {
  // 真定时器下推进若干 tick,覆盖淡出阶梯(interval 20ms×5)
  return new Promise((resolve) => {
    let i = 0
    const t = setInterval(() => {
      i += 1
      if (i >= times) {
        clearInterval(t)
        resolve()
      }
    }, stepMs)
  })
}

describe('AudioQueue', () => {
  it('顺序播放:逐块播完,顺序不乱;播空广播停止', async () => {
    const voices: FakeVoice[] = []
    const queue = new AudioQueue((c) => {
      const v = new FakeVoice(c.data)
      voices.push(v)
      return v
    })
    const states: boolean[] = []
    queue.onPlayback((a) => states.push(a))

    queue.enqueue(chunk(1))
    queue.enqueue(chunk(2))
    queue.enqueue(chunk(3))
    expect(voices.map((v) => v.tag)).toEqual(['fake-1']) // 只起了第一块

    at(voices, 0).finish()
    expect(voices.map((v) => v.tag)).toEqual(['fake-1', 'fake-2'])
    at(voices, 1).finish()
    expect(voices.map((v) => v.tag)).toEqual(['fake-1', 'fake-2', 'fake-3'])
    at(voices, 2).finish()
    expect(states).toEqual([true, false])
  })

  it('抢占淡出:当前块音量降 0 并暂停,队列清空,旧链 ended 不再续播', async () => {
    const voices: FakeVoice[] = []
    const queue = new AudioQueue((c) => {
      const v = new FakeVoice(c.data)
      voices.push(v)
      return v
    }, 100)
    const states: boolean[] = []
    queue.onPlayback((a) => states.push(a))

    queue.enqueue(chunk(1))
    queue.enqueue(chunk(2))
    queue.stopAndFade()
    await flush()

    const cur = at(voices, 0)
    expect(cur.paused).toBe(true)
    expect(cur.volume).toBeLessThanOrEqual(0.001)
    expect(states).toEqual([true, false])

    // 旧链 ended:被 chain 断掉,不再起第二块
    cur.finish()
    expect(voices.map((v) => v.tag)).toEqual(['fake-1'])

    // 抢占后新块入队正常起播
    queue.enqueue(chunk(3))
    expect(voices.map((v) => v.tag)).toEqual(['fake-1', 'fake-3'])
    expect(states).toEqual([true, false, true])
  })

  it('播放失败跳块:工厂抛错降级继续下一块', () => {
    const err = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const played: string[] = []
    const queue = new AudioQueue((c) => {
      if (c.data === 'fake-1') throw new Error('no audio')
      const v = new FakeVoice(c.data)
      played.push(v.tag)
      return v
    })
    queue.enqueue(chunk(1))
    queue.enqueue(chunk(2))
    expect(played).toEqual(['fake-2'])
    expect(err).toHaveBeenCalledOnce()
    err.mockRestore()
  })
})
