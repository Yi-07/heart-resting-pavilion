// 回合状态机(frontend-plan §3/§4):transition(event),非法迁移忽略记 DEBUG 不崩。
// 增量 draw 与精稿 draw 前端无法实时区分(契约无专用信号)→ 按「纯前端推断」落:
//   轮次回答提交(collecting/final)→ analysis(显示梳理中);draw 到达 → final(精稿绘制)。
// emotionLabel 写序:first_frame.emotion_label → draw.data.emotion.label;
// 只喂 Live2D/黑板,绝不进路由。(mood_select 手点写情绪联动已随自动浮出废弃,T5)

import { defineStore } from 'pinia'
import { logger } from '../logger'
import type { FirstFrame, S2CMsg, TemplateData } from '../ws/messages'

export type Phase = 'idle' | 'awaiting' | 'collecting' | 'analysis' | 'final'

export type RSEvent = { kind: 'user_sent' } | { kind: 'frame'; msg: S2CMsg }

export const useRoundStore = defineStore('round', {
  state: () => ({
    phase: 'idle' as Phase,
    /** 当前回合路由(first_frame 才有;answer 无 first_frame 沿用旧值,done 复位) */
    route: 'collect' as 'collect' | 'crisis',
    crisis: false,
    emotionLabel: null as string | null,
    /** first_frame 递增,驱动黑板清板 */
    roundId: 0,
    /** 后端下发的本轮稳定标识(first_frame.round_id/collect 才有);
     *  报告寻址一律以它为准——前端不自造编号。done 帧时同步到 lastCollectRoundId。 */
    backendRoundId: null as string | null,
    /** 最近一个 collect 回合结束时的 round_id(供回合结束后定位) */
    lastCollectRoundId: null as string | null,
    /** 最近一个 collect 回合的素材是否归档成功(done.station_ready) */
    stationReady: false,
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
          if (this.phase === 'awaiting') this.phase = 'final'
          else if (this.phase === 'analysis') {
            // P7 等待话术单帧 final=true(后随精稿 draw):不推 phase——
            // 推了 final 会让精稿走 illegal 丢情绪复核;final=false=流式文本
            // 提前到(异常时序),按原语义转 final 显示内容
            if (msg.final !== true) this.phase = 'final'
          } else if (this.phase === 'collecting' || this.phase === 'final') {
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
          // 危机展示态(热线横幅/chip/黑板状态行)随回合收口:answer 无 first_frame
          // 可复位(契约 §3.1),done 是全链路通用收口帧,挂到它身上
          this.crisis = false
          this.route = 'collect'
          {
            // PR 按回合寻址:done 回带本轮 round_id;answer/crisis 支线不带 →
            // 清掉当前轮次,免得支流文本消息(appendDelta 兜底)继承上一轮编号
            const roundId = msg.round_id ?? null
            if (roundId !== null) {
              this.lastCollectRoundId = roundId
              this.stationReady = msg.station_ready !== false
            } else {
              this.backendRoundId = null
              this.stationReady = false
            }
          }
          break
        case 'error':
          // 分派(frontend-plan §5.3):ask_llm_failed → 采集挂起不动(下一条输入
          // 重试,round 状态冻结);其余 → 回 idle。辐条呈现归 App.vue(状态外)
          if (msg.code !== 'ask_llm_failed') {
            this.phase = 'idle'
          }
          break
      }
    },
    enterCollect(msg: FirstFrame): void {
      this.phase = 'collecting'
      this.roundId += 1
      this.route = msg.route
      this.crisis = msg.route === 'crisis'
      this.emotionLabel = msg.emotion_label
      this.backendRoundId = msg.round_id ?? null  // 后端权威:报告寻址用它
      this.stationReady = false  // 回合未结束前不可认为素材已归档
    },
    /** draw 的 formulation.emotion 覆盖(wheel/stage 无此字段) */
    applyEmotion(data: TemplateData): void {
      if (!('situation' in data)) return
      if (data.emotion.label !== null) this.emotionLabel = data.emotion.label
    },
    illegal(frame: string): void {
      logger.debug('round', `非法迁移忽略: ${this.phase} × ${frame}`)
    },
  },
})
