// mood 按钮组链路集成测试(T5):控制器 select/notifyDone/setRoundActive ↔ 置灰状态
// ↔ 浮层组件 disabled。自动浮出链路已废弃(契约「mood_select」节:首帧不再驱动)。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MoodOverlay from '../MoodSelector.vue'
import { MOOD_COOLDOWN_FALLBACK_MS, MoodSelector } from '../selector'

beforeEach(() => {
  vi.useFakeTimers()
})

function mountOverlay(disabled: boolean) {
  return mount(MoodOverlay, { props: { disabled } })
}

describe('mood 按钮组链路', () => {
  it('select() → 上报+进入冷却;notifyDone() → 解除', () => {
    const sent: string[] = []
    let disabled = false
    const controller = new MoodSelector({ setDisabled: (v) => (disabled = v), send: (m) => sent.push(m.mood) })

    controller.select('平静')
    expect(sent).toEqual(['平静'])
    expect(disabled).toBe(true)
    expect(controller.isDisabled).toBe(true)

    controller.notifyDone()
    expect(disabled).toBe(false)
    expect(controller.isDisabled).toBe(false)
  })

  it('冷却中重复点选不上报;done 未达时兜底计时器解除', () => {
    const sent: string[] = []
    const controller = new MoodSelector({ setDisabled: () => {}, send: (m) => sent.push(m.mood) })

    controller.select('低落')
    controller.select('开心') // 冷却中:忽略
    expect(sent).toEqual(['低落'])

    vi.advanceTimersByTime(MOOD_COOLDOWN_FALLBACK_MS)
    expect(controller.isDisabled).toBe(false)

    controller.select('开心') // 解除后可再点
    expect(sent).toEqual(['低落', '开心'])
  })

  it('setRoundActive(true) 回合内置灰并打断兜底计时;false 恢复可点', () => {
    const sent: string[] = []
    const controller = new MoodSelector({ setDisabled: () => {}, send: (m) => sent.push(m.mood) })
    controller.select('平静')

    controller.setRoundActive(true) // 回合开始:置灰,兜底计时打断
    vi.advanceTimersByTime(MOOD_COOLDOWN_FALLBACK_MS + 1)
    expect(controller.isDisabled).toBe(true) // 未被兜底解除

    controller.setRoundActive(false) // 回合结束:恢复可点
    expect(controller.isDisabled).toBe(false)
    controller.select('很好')
    expect(sent).toEqual(['平静', '很好'])
  })

  it('浮层组件:disabled 传导按钮 disabled;点选发 select 事件', async () => {
    const wrapper = mountOverlay(true)
    const btn = wrapper.find('button')
    expect(btn.attributes('disabled')).toBeDefined()

    const wrapperOn = mountOverlay(false)
    await wrapperOn.find('button').trigger('click')
    expect(wrapperOn.emitted('select')).toEqual([['难过']])
  })
})
