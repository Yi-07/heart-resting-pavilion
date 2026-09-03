// 聊天消息列表(模块级单例响应式,ChatPanel/气泡/App 共读):
// 流式语义——beginBot 开一条 bot 消息,appendDelta 续写,finalize 收口;first_frame 安抚语
// 开新条;done/error 收口。latestBotText 供气泡展示。

import { reactive } from 'vue'

export interface ChatMessage {
  id: number
  who: 'u' | 'x' // u=用户 x=小栖
  text: string
  streaming: boolean
}

let seq = 0

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
})
