// 聊天消息列表(模块级单例响应式,ChatPanel/气泡/App 共读):
// 流式语义——beginBot 开一条 bot 消息,appendDelta 续写,finalize 收口;first_frame 安抚语
// 开新条;done/error 收口。latestBotText 供气泡展示。

import { reactive } from 'vue'

export interface ChatMessage {
  id: number
  who: 'u' | 'x' // u=用户 x=小栖
  text: string
  streaming: boolean
  /** 回放历史(ADR-005):降饱和呈现,与实时消息区分 */
  hist?: boolean
  /** 本条 bot 消息所属 collect 轮次(first_frame.round_id,后端权威) */
  roundId?: string | null
  /** 该轮素材是否已归档成功(done.station_ready);false=入口不可用 */
  stationReady?: boolean
}

let seq = 0

/** 回放数据(ADR-005):replay 帧到达后暂存,ChatPanel 据此渲染幕布/小结卡 */
export const replay = reactive({
  mode: null as 'bubbles' | 'digest' | null,
  turns: [] as { role: 'user' | 'assistant'; text: string }[],
  summary: null as string | null,
})

export const chat = reactive({
  msgs: [] as ChatMessage[],
  drawerOpen: false,
  /** 当前进行中的 collect 轮次(first_frame.round_id,后端权威)。
   *  只由 first_frame 更新、由 resetChatForTest/会话切换清空;
   *  appendDelta 在「未显式传 roundId」时沿用它兜底。挂在状态对象上而非模块级全局,
   *  便于测试隔离与会话切换时重置。 */
  activeRoundId: null as string | null,
  appendUser(text: string): void {
    this.msgs.push({ id: ++seq, who: 'u', text, streaming: false })
  },
  /** 开新 bot 消息(first_frame 安抚语 / 新一段流式)。
   *  roundId=本消息所属 collect 轮次(后端下发,显式传 null=明确不绑轮次,
   *  如心情应答/错误提示/answer 支线);stationReady 默认 false,
   *  等该轮 done.station_ready=true 才置真(素材已归档才可发起报告生成)。 */
  beginBot(text = '', roundId: string | null = null): void {
    if (roundId !== null) this.activeRoundId = roundId
    this.finalize()
    this.msgs.push({ id: ++seq, who: 'x', text, streaming: true, roundId, stationReady: false })
  },
  /** 该轮素材归档完成:只更新属于这一轮的消息(逐条绑定,不碰别轮) */
  markStationReady(roundId: string): void {
    for (const m of this.msgs) {
      if (m.roundId === roundId) m.stationReady = true
    }
  },
  /** 追加流式文本。上一条不是 streaming bot 消息(典型:用户刚发言过)时开新消息。
   *  roundId 省略 → 沿用 chat.activeRoundId(当前 collect 轮次);
   *  显式传 null → 明确不绑轮次(不拿旧编号兜底)。 */
  appendDelta(text: string, roundId?: string | null): void {
    const last = this.msgs[this.msgs.length - 1]
    if (last !== undefined && last.who === 'x' && last.streaming) {
      last.text += text
      return
    }
    const effective = roundId === undefined ? this.activeRoundId : roundId
    this.beginBot(text, effective)
  },
  finalize(): void {
    const last = this.msgs[this.msgs.length - 1]
    if (last !== undefined && last.streaming) last.streaming = false
  },
  latestBotText(): string {
    for (let i = this.msgs.length - 1; i >= 0; i -= 1) {
      const m = this.msgs[i]
      if (m !== undefined && m.who === 'x') return m.text
    }
    return ''
  },
  openDrawer(): void {
    this.drawerOpen = true
  },
  closeDrawer(): void {
    this.drawerOpen = false
  },
  /** ADR-005:回放帧落库(幕布/小结卡数据源;历史气泡不入 msgs——
   * 与实时流分离,新回合 first_frame 清的是等待态,不该清掉回放) */
  applyReplay(mode: 'bubbles' | 'digest', turns: { role: 'user' | 'assistant'; text: string }[], summary: string | null): void {
    replay.mode = mode
    replay.turns = turns
    replay.summary = summary
  },
})

/** 测试口:重置消息列表(同 station/settings 的重置口范式) */
export function resetChatForTest(): void {
  chat.msgs.length = 0
  chat.drawerOpen = false
  replay.mode = null
  replay.turns = []
  replay.summary = null
  chat.activeRoundId = null
}

/** 消息文本按「心灵补给站」提法分段(邀请语可点打开补给站;
 * 纯前端展示增强,不涉契约字段;提法=功能名,比整句匹配稳) */
export interface TextSegment {
  text: string
  mention: boolean
}

export function splitStationMention(text: string): TextSegment[] {
  const parts = text.split('心灵补给站')
  const segments: TextSegment[] = []
  parts.forEach((p, i) => {
    if (p !== '') segments.push({ text: p, mention: false })
    if (i < parts.length - 1) segments.push({ text: '心灵补给站', mention: true })
  })
  return segments
}
