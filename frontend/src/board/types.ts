// 模板声明类型(frontend-plan §5.1)。
// 画布规范(DrawProtocol):viewBox 640×440,安全区 {x:60,y:40,w:520,h:360}。
// anchor 用 "zone:<id>" 引用 TemplateDecl.zones 坐标表——相对坐标单源在声明里,
// 不在渲染器里散落魔法数;connectFrom=该格连线的起点(连线画进字段自己的组,随字段重画)。

export type Widget =
  | 'text'
  | 'highlight'
  | 'rough_ellipse+text'
  | 'rough_box+text'
  | 'wheel_mini'
  | 'stage_nodes'
  /** 场景槽位:图标(field.icon 默认 / data.assets[key] 选材)+ 注释行小字 */
  | 'icon+text'

/** 画布内绝对坐标(单位=模板画布像素) */
export interface Zone {
  cx: number
  cy: number
  /** 椭圆/圆角盒半径;text 类 widget 可省 */
  rx?: number
  ry?: number
  /** 连线起点(绝对坐标),画到本格椭圆上缘 */
  connectFrom?: { x: number; y: number }
}

export interface FieldDecl {
  /** 数据字段名,须与该模板 TemplateData 字段一致 */
  key: string
  /** "zone:<id>" → decl.zones[id] */
  anchor: string
  widget: Widget
  /** 数据为 null 时不画该格(擦除旧组);默认即此行为,显式声明备用 */
  emptyIfNull?: boolean
  /** 文字前缀标签,如 核心信念(空格分隔用 ·) */
  label?: string
  /** 粉笔字号 */
  size?: number
  /** 共用绘制组 key(如 stage_map 的 nodes/current 同画一组);缺省=key */
  group?: string
  /** 槽位默认图标 id(manifests 登记;LLM 未选/未知 id 时兜底) */
  icon?: string
  /** LLM 可选图标 id 集合约束(清单对账用;前端渲染不走此字段) */
  iconPool?: string[]
}

export interface TemplateDecl {
  id: string
  /** anchor 坐标表(模板布局单源) */
  zones: Readonly<Record<string, Zone>>
  fields: FieldDecl[]
  /** 板标题(板 chrome 用) */
  title?: string
  /** 场景底图层:预绑定图标序列(板式级,换模板时随场景淡入淡出) */
  scene?: SceneItem[]
}

/** 场景层单项:预绑定元素。kind=icon(图标,默认)/line(手绘分隔线,注释行用) */
export interface SceneItem {
  kind?: 'icon' | 'line'
  /** kind=icon:图标 id(manifests 登记) */
  icon?: string
  /** kind=icon:放置区(画布绝对坐标,等比 contain 适配) */
  x?: number
  y?: number
  w?: number
  h?: number
  /** kind=icon 色调:main=粉笔白/sub=次级/warm=暖黄(定稿 A 纯粉笔白,渲染同 main,保留声明作对照) */
  tone?: 'main' | 'sub' | 'warm'
  /** kind=line:线段端点 */
  x1?: number
  y1?: number
  x2?: number
  y2?: number
  /** 错峰起笔延迟(秒);icon 缺省按序自动错开 */
  delay?: number
}
