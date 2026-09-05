// StationPanel 钉测试:open 态类切换 / pending 等待语 / ready 渲染 md+操作钮 / 关闭回调。
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import StationPanel from '../StationPanel.vue'
import { resetStationForTest, station } from '../station'

afterEach(() => {
  resetStationForTest()
})

describe('StationPanel', () => {
  it('ready 态:渲染 md 结构与操作按钮', async () => {
    station.open = true
    station.phase = 'ready'
    station.reportMd = '# 心理成长方案\n\n## 这次的梳理\n- 情境:加班\n\n> 声明'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-panel"]').classes()).toContain('open')
    expect(wrapper.find('[data-testid="station-md"] h1').text()).toBe('心理成长方案')
    expect(wrapper.find('[data-testid="station-md"] h2').text()).toBe('这次的梳理')
    expect(wrapper.find('[data-testid="station-md"] li').text()).toContain('情境')
    expect(wrapper.find('[data-testid="station-md"] blockquote').exists()).toBe(true)
    expect(wrapper.find('[data-testid="station-export"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="station-regen"]').exists()).toBe(true)
  })

  it('pending 态:等待语', async () => {
    station.open = true
    station.phase = 'pending'
    station.message = '正在为你整理'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-wait"]').text()).toContain('正在为你整理')
    expect(wrapper.find('[data-testid="station-md"]').exists()).toBe(false)
  })

  it('空态/错态:话术可见', async () => {
    station.open = true
    station.phase = 'empty'
    station.message = '这次对话还没有可整理的素材'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-note"]').text()).toContain('素材')
  })

  it('点关闭 → open=false', async () => {
    station.open = true
    station.phase = 'ready'
    station.reportMd = '# 稿'
    const wrapper = mount(StationPanel)
    await nextTick()
    await wrapper.find('[data-testid="station-close"]').trigger('click')
    expect(station.open).toBe(false)
    expect(wrapper.find('[data-testid="station-panel"]').classes()).not.toContain('open')
  })
})
