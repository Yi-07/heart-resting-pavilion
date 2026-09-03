// diff —— 纯函数:按声明字段比对新旧数据,返回新增/变化/置 null 的字段 key 列表。
// 嵌套对象(emotion)与数组(emotions/nodes)按稳定序列化比对(键排序),与键序无关。
// prev=null(首帧/换模板)→ 返回全部 key,由渲染器跳过 null 值。

import type { EmotionWheelData, Formulation, StageMapData, TemplateData } from '../ws/messages'

/** 按 union 判别取字段 key 集(类型收窄,不做 Record 逃逸) */
export function keysOf(data: TemplateData): readonly string[] {
  if ('situation' in data) {
    const f = data as Formulation
    return [
      'situation',
      'emotion',
      'thought',
      'behavior',
      'intermediate_belief',
      'core_belief',
    ].filter((k) => k in f)
  }
  if ('emotions' in data) return Object.keys(data as EmotionWheelData)
  return Object.keys(data as StageMapData)
}

/** 取单字段值(unknown:仅用于比对/判空,不做类型逃逸) */
export function fieldOf(data: TemplateData, key: string): unknown {
  if ('situation' in data) return (data as Formulation)[key as keyof Formulation]
  if ('emotions' in data) return (data as EmotionWheelData)[key as keyof EmotionWheelData]
  return (data as StageMapData)[key as keyof StageMapData]
}

/** 稳定序列化:对象键排序后拼接,数组保序 */
function serialize(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'undefined'
  if (Array.isArray(value)) return `[${value.map(serialize).join(',')}]`
  const pairs = Object.entries(value as object)
    .map(([k, v]) => `${JSON.stringify(k)}:${serialize(v)}`)
    .sort()
  return `{${pairs.join(',')}}`
}

export function diff(prev: TemplateData | null, next: TemplateData): string[] {
  const keys = keysOf(next)
  if (prev === null) return [...keys]
  return keys.filter((k) => serialize(fieldOf(prev, k)) !== serialize(fieldOf(next, k)))
}
