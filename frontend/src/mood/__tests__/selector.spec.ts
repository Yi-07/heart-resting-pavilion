// mood 自动浮出链路集成测试:控制器 show/hide/select ↔ round store ↔ 浮层组件 v-if。
// 背景:E2E 两次观察到 first_frame 后浮层未自动出现(手动点 pill 正常),钉住 App 侧同款接线。
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MoodOverlay from '../MoodSelector.vue'
import { MoodSelector } from '../selector'
import { useRoundStore } from '../../state/round'
import type { FirstFrame } from '../../ws/messages'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

function ff(moodSelect: boolean): FirstFrame {
  return {
    type: 'first_frame',
    session_id: 's1',
    route: 'collect',
    template: 'beck_formulation',
    emotion_label: '焦虑',
    mood_select: moodSelect,
    text: '我在听',
  }
}

describe('mood 自动浮出链路', () => {
  it('控制器 show() → 浮层渲染;select() → 上报+手点写情绪+收起', async () => {
    const round = useRoundStore()
    const wrapper = mount(MoodOverlay, { global: { plugins: [pinia] } })
    const sent: string[] = []
    const controller = new MoodSelector({ round, send: (m) => sent.push(m.mood) })

    expect(wrapper.find('[data-testid="mood-overlay"]').exists()).toBe(false)
    controller.show()
    await nextTick()
    expect(wrapper.find('[data-testid="mood-overlay"]').exists()).toBe(true)

    controller.select('平静')
    await nextTick()
    expect(wrapper.find('[data-testid="mood-overlay"]').exists()).toBe(false)
    expect(sent).toEqual(['平静'])
    expect(round.emotionLabel).toBe('平静')
    expect(round.manualMood).toBe(true)
  })

  it('first_frame 帧驱动:transition(mood_select=true) → moodVisible;false → 不浮', async () => {
    const round = useRoundStore()
    const wrapper = mount(MoodOverlay, { global: { plugins: [pinia] } })
    round.transition({ kind: 'frame', msg: ff(true) })
    await nextTick()
    expect(round.moodVisible).toBe(true)
    expect(wrapper.find('[data-testid="mood-overlay"]').exists()).toBe(true)
    round.transition({ kind: 'user_sent' })
    round.transition({ kind: 'frame', msg: ff(false) })
    await nextTick()
    expect(round.moodVisible).toBe(false)
    expect(wrapper.find('[data-testid="mood-overlay"]').exists()).toBe(false)
  })
})
