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
  appendUser(text: string): void {
    this.msgs.push({ id: ++seq, who: 'u', text, streaming: false })
  },
  /** 开新 bot 消息(first_frame 安抚语 / 新一段流式) */
  beginBot(text = ''): void {
    this.finalize()
    this.msgs.push({ id: ++seq, who: 'x', text, streaming: true })
  },
  appendDelta(text: string): void {
    const last = this.msgs[this.msgs.length - 1]
    if (last !== undefined && last.who === 'x' && last.streaming) last.text += text
    else this.beginBot(text)
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
