// ChatPanel 气泡文案钉测(验收 4):等待期文案统一——无旧文本且回合活跃
// 一律「小栖正在梳理你说的…」(首轮等待不闪跳);「我在听。」分支已死不复活;
// 中间轮等待显示上一问;回合结束回 idle 气泡收起。
import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import ChatPanel from '../ChatPanel.vue'
import { chat } from '../messages'
import { useRoundStore } from '../../state/round'

const THINKING = '小栖正在梳理你说的…'

/** 空帧 first_frame(collect 路 text 恒空,契约 §3.1) */
const EMPTY_FIRST_FRAME = {
  type: 'first_frame',
  session_id: 'sess_test',
  route: 'collect',
  template: 'beck_formulation',
  text: '',
  mood_select: false,
  emotion_label: null,
  assets: null,
} as const

/** 挂载到 document + nextTick(bubbleText 断言走 DOM 查询,过渡后须等渲染) */
async function mountPanel() {
  const wrapper = mount(ChatPanel, { attachTo: document.body })
  await nextTick()
  return wrapper
}

function bubbleText(): string {
  return document.querySelector('[data-testid="bubble"] .btx')?.textContent ?? ''
}
function bubbleOn(): boolean {
  return document.querySelector('[data-testid="bubble"]')?.classList.contains('on') ?? false
}

beforeEach(() => {
  setActivePinia(createPinia())
  chat.msgs.splice(0)
  chat.drawerOpen = false
})

describe('等待期气泡文案统一(验收 4)', () => {
  it('全新会话首条输入:idle→awaiting,无旧文本 → 「正在梳理」持续可见(无「我在听」闪跳)', async () => {
    const wrapper = await mountPanel()
    const round = useRoundStore()
    round.transition({ kind: 'user_sent' }) // idle → awaiting
    await nextTick()
    expect(round.phase).toBe('awaiting')
    expect(bubbleText()).toBe(THINKING)
    expect(bubbleOn()).toBe(true)
    wrapper.unmount()
  })

  it('awaiting→collecting(first_frame 到达,text 空):文案不变,不闪跳', async () => {
    const wrapper = await mountPanel()
    const round = useRoundStore()
    round.transition({ kind: 'user_sent' })
    round.transition({ kind: 'frame', msg: { ...EMPTY_FIRST_FRAME } })
    await nextTick()
    expect(round.phase).toBe('collecting')
    expect(bubbleText()).toBe(THINKING)
    expect(bubbleOn()).toBe(true)
    wrapper.unmount()
  })

  it('中间轮等待:有旧文本显示上一问(问话收口后,回答提交转 analysis)', async () => {
    const wrapper = await mountPanel()
    const round = useRoundStore()
    round.transition({ kind: 'user_sent' })
    round.transition({ kind: 'frame', msg: { ...EMPTY_FIRST_FRAME } })
    chat.beginBot('那种睡不着的时候,脑子里在想什么?')
    chat.finalize()
    round.transition({ kind: 'user_sent' }) // collecting → analysis
    await nextTick()
    expect(round.phase).toBe('analysis')
    expect(bubbleText()).toBe('那种睡不着的时候,脑子里在想什么?')
    expect(bubbleOn()).toBe(true)
    wrapper.unmount()
  })

  it('问话文字到达:text_delta 开 bot 消息,气泡切实际问句', async () => {
    const wrapper = await mountPanel()
    const round = useRoundStore()
    round.transition({ kind: 'user_sent' })
    round.transition({ kind: 'frame', msg: { ...EMPTY_FIRST_FRAME } })
    chat.appendDelta('那种睡不着的时候,脑子里在想什么?')
    await nextTick()
    expect(bubbleText()).toBe('那种睡不着的时候,脑子里在想什么?')
    wrapper.unmount()
  })

  it('回合收口(done→idle,无文本):气泡收起,文案清空', async () => {
    const wrapper = await mountPanel()
    const round = useRoundStore()
    round.transition({ kind: 'user_sent' })
    round.transition({ kind: 'frame', msg: { type: 'done', session_id: 's', seq: 1 } })
    await nextTick()
    expect(round.phase).toBe('idle')
    expect(bubbleText()).toBe('')
    expect(bubbleOn()).toBe(false)
    wrapper.unmount()
  })

  it('长旧文本截断:超 64 字显示前 64 字+省略号', async () => {
    const wrapper = await mountPanel()
    chat.beginBot('长'.repeat(70))
    chat.finalize()
    await nextTick()
    expect(bubbleText()).toBe(`${'长'.repeat(64)}…`)
    wrapper.unmount()
  })
})
