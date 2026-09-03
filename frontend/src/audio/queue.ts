// 音频队列骨架(frontend-plan §4):enqueue 顺序播 · stopAndFade 淡出清队(first_frame
// 抢占时调,~100ms)· onPlayback 广播(l2d 订阅驱动口型;真音频帧步骤 8 到,本步只立骨架)。
// 测试可注入 VoiceLike 工厂;jsdom 无 Audio 时默认工厂抛错由队列降级跳过。

import type { AudioChunk } from '../ws/messages'
import { logger } from '../logger'

/** 最小播放器形状(浏览器 HTMLAudioElement 满足) */
export interface VoiceLike {
  volume: number
  play(): Promise<unknown> | void
  pause(): void
  addEventListener(event: 'ended', listener: () => void): void
}

export type VoiceFactory = (chunk: AudioChunk) => VoiceLike

function defaultVoice(chunk: AudioChunk): VoiceLike {
  if (typeof Audio === 'undefined') throw new Error('当前环境无 Audio,跳过播放')
  const el = new Audio(`data:audio/${chunk.format};base64,${chunk.data}`)
  return {
    volume: el.volume,
    play: () => el.play(),
    pause: () => el.pause(),
    addEventListener: (event, listener) => el.addEventListener(event, listener),
  }
}

export class AudioQueue {
  private queue: AudioChunk[] = []
  private current: VoiceLike | null = null
  private callbacks = new Set<(active: boolean) => void>()
  /** 链代次:stopAndFade 后旧链的 ended 回调不再续播 */
  private chain = 0
  private playing = false

  constructor(
    private readonly createVoice: VoiceFactory = defaultVoice,
    private readonly fadeMs = 100,
  ) {}

  enqueue(chunk: AudioChunk): void {
    this.queue.push(chunk)
    if (this.current === null) this.playNext()
  }

  /** 抢占:淡出当前声→暂停,清空队列,广播停止 */
  stopAndFade(): void {
    this.chain += 1
    this.queue = []
    this.playing = false
    const voice = this.current
    this.current = null
    this.broadcast(false)
    if (voice === null) return
    const step = 20
    const times = Math.max(1, Math.ceil(this.fadeMs / step))
    let i = 0
    const timer = window.setInterval(() => {
      i += 1
      voice.volume = Math.max(0, 1 - i / times)
      if (i >= times) {
        window.clearInterval(timer)
        voice.pause()
      }
    }, step)
  }

  onPlayback(cb: (active: boolean) => void): () => void {
    this.callbacks.add(cb)
    return () => this.callbacks.delete(cb)
  }

  private playNext(): void {
    const chunk = this.queue.shift()
    if (chunk === undefined) {
      if (this.playing) {
        this.playing = false
        this.broadcast(false)
      }
      return
    }
    const myChain = this.chain
    let voice: VoiceLike
    try {
      voice = this.createVoice(chunk)
    } catch (err) {
      logger.warn('audio', `无法创建播放器,跳块: ${String(err)}`)
      this.playNext()
      return
    }
    this.current = voice
    voice.addEventListener('ended', () => {
      if (myChain !== this.chain) return // 已被 stopAndFade 断链
      this.current = null
      this.playNext()
    })
    // 播放态翻转才广播(连续块之间不重复报 true)
    if (!this.playing) {
      this.playing = true
      this.broadcast(true)
    }
    const p = voice.play()
    if (p instanceof Promise) {
      p.catch((err: unknown) => {
        logger.warn('audio', `播放失败跳块: ${String(err)}`)
        if (myChain === this.chain) {
          this.current = null
          this.playNext()
        }
      })
    }
  }

  private broadcast(active: boolean): void {
    for (const cb of this.callbacks) cb(active)
  }
}
