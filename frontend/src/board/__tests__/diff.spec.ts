// board/diff 接缝钉测试(frontend-plan §8):新增/变化/置 null 三态、嵌套对象键序无关、
// prev=null 全量、异模板 keys 取自 next。
import { describe, expect, it } from 'vitest'
import { diff } from '../diff'
import type { Formulation, StageMapData } from '../../ws/messages'

const emptyFormulation: Formulation = {
  situation: null,
  emotion: { label: null, intensity: null },
  thought: null,
  behavior: null,
  intermediate_belief: null,
  core_belief: null,
}

describe('diff', () => {
  it('prev=null(首帧)→ 返回全部 key', () => {
    expect(diff(null, emptyFormulation)).toEqual([
      'situation',
      'emotion',
      'thought',
      'behavior',
      'intermediate_belief',
      'core_belief',
    ])
  })

  it('新增:新填字段计入', () => {
    const next: Formulation = { ...emptyFormulation, situation: '被否定', thought: '我不行' }
    expect(diff(emptyFormulation, next)).toEqual(['situation', 'thought'])
  })

  it('变化:值更新计入;嵌套对象(emotion)按内容比对,键序无关', () => {
    const prev: Formulation = { ...emptyFormulation, situation: '被否定', emotion: { label: '焦虑', intensity: 0.6 } }
    const reordered: Formulation = { ...emptyFormulation, situation: '被否定', emotion: { intensity: 0.6, label: '焦虑' } }
    expect(diff(prev, reordered)).toEqual([])
    const changed: Formulation = { ...emptyFormulation, situation: '被否定', emotion: { label: '焦虑', intensity: 0.85 } }
    expect(diff(prev, changed)).toEqual(['emotion'])
  })

  it('置 null:值清空也计入(渲染器擦除该格)', () => {
    const prev: Formulation = { ...emptyFormulation, situation: '被否定', thought: '我不行' }
    const next: Formulation = { ...emptyFormulation, situation: null, thought: '我不行' }
    expect(diff(prev, next)).toEqual(['situation'])
  })

  it('stage_map:数组字段变化计入(current 高亮迁移)', () => {
    const prev: StageMapData = { nodes: ['现在', '拨打热线'], current: 0, from: '你不是一个人' }
    const next: StageMapData = { nodes: ['现在', '拨打热线'], current: 1, from: '你不是一个人' }
    expect(diff(prev, next)).toEqual(['current'])
    const nodesChanged: StageMapData = { nodes: ['现在', '拨打热线', '专业支持'], current: 1, from: '你不是一个人' }
    expect(diff(prev, nodesChanged)).toEqual(['nodes', 'current'])
  })
})
