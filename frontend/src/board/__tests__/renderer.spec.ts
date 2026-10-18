// board/renderer 接缝钉测试(frontend-plan §8):未知模板记 WARN 跳帧不崩、
// 已注册模板按 diff 增量画(字段组出现/擦除)、clear 清板、转场管线、scene 板式。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoardRenderer } from '../renderer'
import '../templates'
import type { Formulation, SceneFormulationData, SceneNoteData } from '../../ws/messages'

const emptyFormulation: Formulation = {
  situation: null,
  emotion: { label: '焦虑', intensity: 0.85 },
  thought: null,
  behavior: null,
  intermediate_belief: null,
  core_belief: null,
}

let mount: HTMLElement
let renderer: BoardRenderer

/** 字段组名去重列表(同名字段在图形/文字双层各有一组,按名去重看绘制面) */
function fieldNames(root: HTMLElement): string[] {
  return [...new Set([...root.querySelectorAll('g[data-field]')].map((g) => g.getAttribute('data-field') ?? ''))]
}

beforeEach(() => {
  mount = document.createElement('div')
  document.body.append(mount)
  renderer = new BoardRenderer(mount)
})

afterEach(() => {
  renderer.destroy()
  mount.remove()
  vi.restoreAllMocks()
})

describe('BoardRenderer', () => {
  it('未知模板:记 WARN 跳帧,黑板不崩且保留原内容', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    renderer.render('beck_formulation', emptyFormulation)
    const before = mount.innerHTML
    expect(() => renderer.render('no_such_template', emptyFormulation)).not.toThrow()
    expect(warn).toHaveBeenCalledOnce()
    expect(mount.innerHTML).toBe(before)
  })

  it('增量:粗稿只画非空字段,新填字段追加新组,置 null 擦除该组', () => {
    renderer.render('beck_formulation', emptyFormulation)
    expect(fieldNames(mount)).toEqual(['emotion'])

    // +situation+thought:追加两组,emotion 组不重画(引用保持)
    const emotionG = mount.querySelector('g[data-field="emotion"]')
    const round1: Formulation = { ...emptyFormulation, situation: '被否定', thought: '我不行' }
    renderer.render('beck_formulation', round1)
    expect(fieldNames(mount)).toEqual(['emotion', 'situation', 'thought'])
    expect(mount.querySelector('g[data-field="emotion"]')).toBe(emotionG)

    // situation 置 null:擦除
    renderer.render('beck_formulation', { ...round1, situation: null })
    expect(fieldNames(mount)).toEqual(['emotion', 'thought'])
  })

  it('emotion 文字只显示 label:intensity 不上黑板(数据层照常流转)', () => {
    renderer.render('beck_formulation', emptyFormulation)
    const texts = [...mount.querySelectorAll('g[data-field="emotion"] text')].map((t) => t.textContent)
    expect(texts).toEqual(['焦虑'])
  })

  it('模板切换:淡出后重置画布,新模板字段组从头画', () => {
    vi.useFakeTimers()
    try {
      renderer.render('beck_formulation', emptyFormulation)
      renderer.render('stage_map', { nodes: ['现在', '拨打热线', '专业支持'], current: 0, from: '你不是一个人' })
      vi.advanceTimersByTime(600) // 过转场窗口(切换一律淡入淡出)
      expect(fieldNames(mount)).toEqual(['path', 'from'])
      // 节点标签来自数据
      const texts = [...mount.querySelectorAll('text')].map((t) => t.textContent)
      expect(texts).toContain('现在')
      expect(texts).toContain('专业支持')
    } finally {
      vi.useRealTimers()
    }
  })

  it('长文本折行:字段文字折到 ≤3 行且不溢出画布', () => {
    const long: Formulation = {
      ...emptyFormulation,
      behavior: '没跟人说,自己忍着,睡前刷手机到半夜,越忍越清醒',
    }
    renderer.render('beck_formulation', long)
    const texts = [...mount.querySelectorAll('g[data-field="behavior"] text')].map((t) => ({
      content: t.textContent ?? '',
      x: Number(t.getAttribute('x')),
    }))
    expect(texts.length).toBeGreaterThan(1) // 折行了
    expect(texts.length).toBeLessThanOrEqual(3)
    for (const t of texts) {
      const halfWidth = ([...t.content].length * 13) / 2 // behavior 字号 13,居中锚点
      expect(t.x + halfWidth).toBeLessThanOrEqual(638)
      expect(t.x - halfWidth).toBeGreaterThanOrEqual(2)
    }
  })

  it('clear:淡出后清空字段组(清板)', () => {
    vi.useFakeTimers()
    try {
      renderer.render('beck_formulation', emptyFormulation)
      renderer.clear()
      expect(mount.querySelectorAll('g[data-field]')).not.toHaveLength(0) // 淡出在途,旧画面还在
      vi.advanceTimersByTime(600)
      expect(mount.querySelectorAll('g[data-field]')).toHaveLength(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('clear 后淡出中同模板 draw:完整落纸不吞帧(crisis 连触回归)', () => {
    vi.useFakeTimers()
    try {
      // 第一次危机:场景上板
      renderer.render('scene_crisis', { note: null })
      vi.advanceTimersByTime(600)
      expect(mount.querySelectorAll('g[data-scene-icon="crisis.catching"]').length).toBeGreaterThanOrEqual(1)
      // 二连触发:clear(first_frame)与 draw 同模板,间隔短于淡出窗
      renderer.clear()
      renderer.render('scene_crisis', { note: null })
      vi.advanceTimersByTime(600)
      // 板式身份已在 clear 即失忆:draw 走转场重画整幅,不误判同模板增量吞帧
      expect(mount.querySelectorAll('g[data-scene-icon="crisis.catching"]').length).toBeGreaterThanOrEqual(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('scene 板式:底图预绑定图标渲染,collect 字段增量浮现', () => {
    const data: SceneFormulationData = {
      situation: '工作压力大',
      emotion: { label: '疲惫', intensity: 0.85 },
      thought: null,
      behavior: null,
      intermediate_belief: null,
      core_belief: null,
      assets: { emotion: 'state.rain-cloud' },
    }
    renderer.render('scene_focus', data)
    // 底图:预绑定图标 + 注释分隔线
    expect(mount.querySelectorAll('g[data-scene-icon]').length).toBeGreaterThanOrEqual(2)
    // 字段槽位:emotion 选材图标(rain-cloud)+ situation 默认图标
    expect(mount.querySelector('g[data-scene-icon="state.rain-cloud"]')).not.toBeNull()
    expect(mount.querySelector('g[data-scene-icon="desk.cluttered"]')).not.toBeNull()
    // 文字弱化小字:label+文本,intensity 不出现
    const texts = [...mount.querySelectorAll('g[data-field] text')].map((t) => t.textContent)
    expect(texts.join('|')).toContain('疲惫')
    expect(texts.join('|')).not.toContain('0.85')
  })

  it('scene 槽位:未知选材 id 落声明默认图标(渲染器兜底,不残缺)', () => {
    const data: SceneFormulationData = {
      situation: null,
      emotion: { label: '焦虑', intensity: null },
      thought: null,
      behavior: null,
      intermediate_belief: null,
      core_belief: null,
      assets: { emotion: 'no.such-icon' },
    }
    renderer.render('scene_focus', data)
    expect(mount.querySelector('g[data-scene-icon="no.such-icon"]')).toBeNull()
    expect(mount.querySelector('g[data-scene-icon="state.storm-cloud"]')).not.toBeNull()
  })

  it('scene 主体位:assets.subject 选材驱动,无选材不画(平等项,无默认兜底)', () => {
    vi.useFakeTimers()
    try {
      const base = {
        situation: null,
        emotion: { label: null, intensity: null },
        thought: null,
        behavior: null,
        intermediate_belief: null,
        core_belief: null,
      }
      // 无 subject 选材:主体位空着(不画默认图标)
      renderer.render('scene_focus', base)
      vi.advanceTimersByTime(600)
      expect(mount.querySelector('g[data-scene-icon="desk.plain"]')).toBeNull()
      expect(mount.querySelector('g[data-field="subject"]')).toBeNull()
      // 增量轮选出主体:落 zones.subject 声明区
      renderer.render('scene_focus', { ...base, assets: { subject: 'rel.alone-in-crowd' } })
      vi.advanceTimersByTime(600)
      expect(mount.querySelector('g[data-scene-icon="rel.alone-in-crowd"]')).not.toBeNull()
      // 未知 subject id:不画(渲染器兜底跳过)
      renderer.clear()
      vi.advanceTimersByTime(600)
      renderer.render('scene_focus', { ...base, assets: { subject: 'no.such-icon' } })
      vi.advanceTimersByTime(600)
      expect(mount.querySelector('g[data-scene-icon="no.such-icon"]')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('固定场景:scene_crisis 底图+note 注释行,无字段组', () => {
    renderer.render('scene_crisis', { note: '你不是一个人' } as SceneNoteData)
    expect(mount.querySelectorAll('g[data-scene-icon]').length).toBeGreaterThanOrEqual(5)
    const texts = [...mount.querySelectorAll('text')].map((t) => t.textContent)
    expect(texts).toContain('你不是一个人')
    expect(mount.querySelectorAll('g[data-field]')).toHaveLength(0)
  })

  it('转场管线:换模板不瞬清,0.55s 淡出后新画面落纸;空板首绘无转场', () => {
    vi.useFakeTimers()
    try {
      // 空板首绘:立即落纸(无内容可淡出)
      renderer.render('beck_formulation', emptyFormulation)
      expect(mount.querySelector('g[data-field="emotion"]')).not.toBeNull()
      // 换模板:淡出在途——旧画面还在,pending 未画
      renderer.render('scene_default', { note: null })
      expect(mount.querySelector('g[data-scene-icon]')).toBeNull()
      expect(mount.querySelector('g[data-field="emotion"]')).not.toBeNull()
      // 淡出完成:旧清空,新底图落纸
      vi.advanceTimersByTime(600)
      expect(mount.querySelector('g[data-field="emotion"]')).toBeNull()
      expect(mount.querySelectorAll('g[data-scene-icon]').length).toBeGreaterThanOrEqual(5)
    } finally {
      vi.useRealTimers()
    }
  })

  it('转场竞争:淡出期间再换模板,最新帧赢(只画最后的模板)', () => {
    vi.useFakeTimers()
    try {
      renderer.render('beck_formulation', emptyFormulation)
      renderer.render('scene_default', { note: null })
      renderer.render('scene_crisis', { note: null }) // 淡出在途中再切
      vi.advanceTimersByTime(600)
      expect(mount.querySelectorAll('g[data-scene-icon="warm.house-night"]')).toHaveLength(0)
      expect(mount.querySelectorAll('g[data-scene-icon="crisis.catching"]').length).toBeGreaterThanOrEqual(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('向后兼容:几何模板增量行为不受场景化影响(同模板增量不转场)', () => {
    renderer.render('beck_formulation', emptyFormulation)
    const emotionG = mount.querySelector('g[data-field="emotion"]')
    renderer.render('beck_formulation', { ...emptyFormulation, situation: '被否定' })
    // 同模板:无淡出窗口,字段组直接追加,旧组引用保持
    expect(mount.querySelector('g[data-field="emotion"]')).toBe(emotionG)
    expect(fieldNames(mount)).toEqual(['emotion', 'situation'])
  })
})
