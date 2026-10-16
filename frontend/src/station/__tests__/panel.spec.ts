// StationPanel 钉测试:open 态类切换 / detail 视图(pending 等待语 · ready 渲染 md+操作钮 ·
// 重新生成保留旧稿 · 返回列表) / list 视图挂 ReportList / 关闭回调。
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import StationPanel from '../StationPanel.vue'
import { backToList, resetStationForTest, station } from '../station'

afterEach(() => {
  resetStationForTest()
})

function openDetail(): void {
  station.open = true
  station.view = 'detail'
  station.currentRoundId = '3'
}

describe('StationPanel', () => {
  it('ready 态:渲染 md 结构与操作按钮', async () => {
    openDetail()
    station.phase = 'ready'
    station.reportMd = '# 心理成长方案\n\n## 这次的梳理\n- 情境:加班\n\n> 声明'
    station.currentTitle = '加班到很晚 · 疲惫'
    station.currentMeta = { created_at: '2026-10-14T21:23:05', expires_at: '2026-10-21T21:22:48', updated_at: '2026-10-14T21:23:05' }
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-panel"]').classes()).toContain('open')
    expect(wrapper.find('[data-testid="station-md"] h1').text()).toBe('心理成长方案')
    expect(wrapper.find('[data-testid="station-md"] h2').text()).toBe('这次的梳理')
    expect(wrapper.find('[data-testid="station-md"] li').text()).toContain('情境')
    expect(wrapper.find('[data-testid="station-md"] blockquote').exists()).toBe(true)
    expect(wrapper.find('[data-testid="station-meta"]').text()).toContain('加班到很晚 · 疲惫')
    expect(wrapper.find('[data-testid="station-meta"]').text()).not.toContain('第 ')
    expect(wrapper.find('[data-testid="station-export"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="station-regen"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="station-back"]').exists()).toBe(true)
  })

  it('pending 态:等待语', async () => {
    openDetail()
    station.phase = 'pending'
    station.message = '正在为你整理'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-wait"]').text()).toContain('正在为你整理')
    expect(wrapper.find('[data-testid="station-md"]').exists()).toBe(false)
  })

  it('重新生成中:旧稿保留 + 浮条提示 + 重生成钮禁用', async () => {
    openDetail()
    station.phase = 'pending'
    station.regenerating = true
    station.reportMd = '# 旧稿'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-md"]').text()).toContain('旧稿')
    expect(wrapper.find('[data-testid="station-regen-bar"]').text()).toContain('正在重新整理')
    expect(wrapper.find('[data-testid="station-wait"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="station-regen"]').attributes('disabled')).toBeDefined()
  })

  it('失败但有旧稿:旧稿可读 + 导出可用', async () => {
    openDetail()
    station.phase = 'error'
    station.reportMd = '# 旧稿'
    station.message = '刚才那次整理被打断了'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-md"]').text()).toContain('旧稿')
    expect(wrapper.find('[data-testid="station-note"]').text()).toContain('打断了')
    expect(wrapper.find('[data-testid="station-export"]').exists()).toBe(true)
  })

  it('空态/错态:话术可见', async () => {
    openDetail()
    station.phase = 'empty'
    station.message = '这一轮还没有可整理的素材'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-note"]').text()).toContain('素材')
  })

  it('list 视图:挂 ReportList(列表页承担列表,详情不重复实现)', async () => {
    station.open = true
    station.view = 'list'
    station.phase = 'idle'
    const wrapper = mount(StationPanel)
    await nextTick()
    expect(wrapper.find('[data-testid="station-list"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="station-back"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="station-md"]').exists()).toBe(false)
  })

  it('点返回 → 回到列表', async () => {
    openDetail()
    station.phase = 'ready'
    station.reportMd = '# 稿'
    const wrapper = mount(StationPanel)
    await nextTick()
    await wrapper.find('[data-testid="station-back"]').trigger('click')
    await nextTick()
    expect(station.view).toBe('list')
  })

  it('点关闭 → open=false', async () => {
    openDetail()
    station.phase = 'ready'
    station.reportMd = '# 稿'
    const wrapper = mount(StationPanel)
    await nextTick()
    await wrapper.find('[data-testid="station-close"]').trigger('click')
    expect(station.open).toBe(false)
    expect(wrapper.find('[data-testid="station-panel"]').classes()).not.toContain('open')
  })

  it('backToList 暴露给列表页之外的动作(返回值不被组件吞)', () => {
    expect(typeof backToList).toBe('function')
  })
})
