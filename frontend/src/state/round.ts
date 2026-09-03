// 回合状态机(frontend-plan §3/§4):transition(event),非法迁移忽略记 DEBUG 不崩。
// 增量 draw 与精稿 draw 前端无法实时区分(契约无专用信号)→ 按「纯前端推断」落:
//   轮次回答提交(collecting/final)→ analysis(显示梳理中);draw 到达 → final(精稿绘制)。
// emotionLabel 写序:first_frame.emotion_label → draw.data.emotion.label(未被手点覆盖时)
//   → mood_select 本地写(手点锁回合,first_frame 解锁);只喂 Live2D/黑板,绝不进路由。

import { defineStore } from 'pinia'
import { logger } from '../logger'
import type { FirstFrame, S2CMsg, TemplateData } from '../ws/messages'

export type Phase = 'idle' | 'awaiting' | 'collecting' | 'analysis' | 'final'

export type RSEvent = { kind: 'user_sent' } | { kind: 'frame'; msg: S2CMsg }

export const useRoundStore = defineStore('round', {
  state: () => ({
    phase: 'idle' as Phase,
    /** 当前回合路由(first_frame 才有;answer 无 first_frame 保持旧值) */
    route: 'collect' as 'collect' | 'crisis',
    crisis: false,
    moodVisible: false,
    /** 选择器计时进度 0..1(mood/selector 维护) */
    moodElapsed: 0,
    emotionLabel: null as string | null,
    /** 本回合用户手点过心情(锁住后续 draw 的 emotion 覆盖) */
    manualMood: false,
    /** first_frame 递增,驱动黑板清板 */
    roundId: 0,
  }),
  actions: {
    transition(event: RSEvent): void {
      if (event.kind === 'user_sent') {
        this.onUserSent()
        return
      }
      this.onFrame(event.msg)
    },
    onUserSent(): void {
      switch (this.phase) {
        case 'idle':
          this.phase = 'awaiting'
          break
        case 'awaiting':
        case 'analysis':
          // 抢占再发(契约 §7 合法):等待新 first_frame
          break
        case 'collecting':
        case 'final':
          // 轮次回答提交:进入梳理等待(analysis 显示收尾中)
          this.phase = 'analysis'
          break
      }
    },
    onFrame(msg: S2CMsg): void {
      switch (msg.type) {
        case 'first_frame':
          this.enterCollect(msg)
          break
        case 'draw':
          if (this.phase === 'collecting') {
            // 增量:留在 collecting
          } else if (this.phase === 'analysis') {
            this.phase = 'final' // 精稿到达
          } else {
            this.illegal('draw')
            return
          }
          this.applyEmotion(msg.data)
          break
        case 'text_delta':
          if (this.phase === 'awaiting' || this.phase === 'analysis') this.phase = 'final'
          else if (this.phase === 'collecting' || this.phase === 'final') {
            // 流式继续
          } else {
            this.illegal('text_delta')
            return
          }
          break
        case 'audio_chunk':
          // 播放不改变回合状态
          break
        case 'done':
          if (this.phase === 'idle') {
            this.illegal('done')
            return
          }
          this.phase = 'idle'
          this.moodVisible = false
          break
        case 'error':
          this.phase = 'idle'
          this.moodVisible = false
          break
      }
    },
    enterCollect(msg: FirstFrame): void {
      this.phase = 'collecting'
      this.roundId += 1
      this.route = msg.route
      this.crisis = msg.route === 'crisis'
      this.moodVisible = msg.mood_select
      this.moodElapsed = 0
      this.emotionLabel = msg.emotion_label
      this.manualMood = false
    },
    /** draw 的 formulation.emotion 覆盖(手点锁时不覆盖;wheel/stage 无此字段) */
    applyEmotion(data: TemplateData): void {
      if (!('situation' in data)) return
      if (!this.manualMood && data.emotion.label !== null) this.emotionLabel = data.emotion.label
    },
    /** mood/selector 调用:手点写情绪并上锁 */
    setManualMood(label: string): void {
      this.emotionLabel = label
      this.manualMood = true
    },
    illegal(frame: string): void {
      logger.debug('round', `非法迁移忽略: ${this.phase} × ${frame}`)
    },
  },
})
