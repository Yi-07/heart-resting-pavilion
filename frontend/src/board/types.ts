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
}

export interface TemplateDecl {
  id: string
  /** anchor 坐标表(模板布局单源) */
  zones: Readonly<Record<string, Zone>>
  fields: FieldDecl[]
  /** 板标题(板 chrome 用) */
  title?: string
}
