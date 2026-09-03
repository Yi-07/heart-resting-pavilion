// board/renderer 接缝钉测试(frontend-plan §8):未知模板记 WARN 跳帧不崩、
// 已注册模板按 diff 增量画(字段组出现/擦除)、clear 清板。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoardRenderer } from '../renderer'
import '../templates'
import type { Formulation } from '../../ws/messages'

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

  it('模板切换:换模板重置画布,新模板字段组从头画', () => {
    renderer.render('beck_formulation', emptyFormulation)
    renderer.render('stage_map', { nodes: ['现在', '拨打热线', '专业支持'], current: 0, from: '你不是一个人' })
    expect(fieldNames(mount)).toEqual(['path', 'from'])
    // 节点标签来自数据
    const texts = [...mount.querySelectorAll('text')].map((t) => t.textContent)
    expect(texts).toContain('现在')
    expect(texts).toContain('专业支持')
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

  it('clear:清空字段组(清板)', () => {
    renderer.render('beck_formulation', emptyFormulation)
    renderer.clear()
    expect(mount.querySelectorAll('g[data-field]')).toHaveLength(0)
  })
})
