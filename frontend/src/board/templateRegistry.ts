// 模板声明注册表:register(decl)/get(templateId)(frontend-plan §4)。
// 重复 id throw(开发期错误);未注册由 renderer 捕获记 WARN 跳帧。

import type { TemplateDecl } from './types'

const registry = new Map<string, TemplateDecl>()

export function register(decl: TemplateDecl): void {
  if (registry.has(decl.id)) throw new Error(`模板重复注册: ${decl.id}`)
  registry.set(decl.id, decl)
}

export function get(templateId: string): TemplateDecl {
  const decl = registry.get(templateId)
  if (decl === undefined) throw new Error(`未注册模板: ${templateId}`)
  return decl
}

/** 测试隔离用:清空注册表 */
export function resetRegistry(): void {
  registry.clear()
}
