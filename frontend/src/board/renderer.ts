// render —— 通用粉笔渲染器(frontend-plan §4/§5.2):
//   render(templateId, data):diff 出变化字段 → 清该字段组重画(连线随组重画);null=擦除不画。
//   未知 templateId:记 WARN 跳帧不崩(黑板保留上一帧)。
//   clear():first_frame 清黑板(取消进行中的绘制计时器)。
// 场景化(blackboard-v1):模板声明可带 scene 预绑定底图(构图沿已验收原型),
//   字段声明可带 icon 槽位图标(data.assets 携 LLM 选材 id,未知 id 跳过兜底);
//   换模板/清板走转场管线(0.55s 淡出→清→新内容随 prim 渐现),同模板增量不转场。
// 粉笔效果:线中点抖动(二次贝塞尔)/椭圆半径噪声/dash-reveal 起笔/粉笔光标跟随;
// feDisplacementMap 滤镜只套图形组不套文字组(保标签可读,定案优于 mockup 原样)。
// 新鲜度由 ws 层保证(client seq 单点校验),收到即新帧。

import { logger } from '../logger'
import type { Emotion, EmotionWheelData, SceneFormulationData, StageMapData, TemplateData } from '../ws/messages'
import { diff, fieldOf } from './diff'
import { assetSvg } from './manifests'
import { get } from './templateRegistry'
import type { FieldDecl, SceneItem, TemplateDecl, Zone } from './types'

const NS = 'http://www.w3.org/2000/svg'
const CHALK = '#F3EBDD'
const CHALK_SUB = '#B9C4B4'
const WARM = '#E8D9A8'
const HAND = '"Ma Shan Zheng","Noto Serif SC",serif'
/** 字段绘制间的起笔间隔(秒),逐字段错峰 */
const FIELD_STAGGER_S = 0.45
/** 末笔后光标驻留时长(秒) */
const CURSOR_LINGER_S = 1.6
/** 场景切换淡出时长(秒;淡入走 .board-primitive 的 0.55s 过渡) */
const FADE_OUT_S = 0.55

/** stage_map 主径:两段二次贝塞尔(3 节点恰落端点/中点,源自 mockup) */
const STAGE_PATH = {
  p0: { x: 80, y: 330 },
  c1: { x: 220, y: 360 },
  p1: { x: 300, y: 260 },
  c2: { x: 380, y: 160 },
  p2: { x: 540, y: 96 },
} as const

/** 整体 t∈[0,1] 分两段贝塞尔采样 */
function stagePoint(t: number): { x: number; y: number } {
  const seg = (p0: { x: number; y: number }, c: { x: number; y: number }, p1: { x: number; y: number }, u: number) => {
    const a = 1 - u
    return { x: a * a * p0.x + 2 * a * u * c.x + u * u * p1.x, y: a * a * p0.y + 2 * a * u * c.y + u * u * p1.y }
  }
  if (t <= 0.5) return seg(STAGE_PATH.p0, STAGE_PATH.c1, STAGE_PATH.p1, t * 2)
  return seg(STAGE_PATH.p1, STAGE_PATH.c2, STAGE_PATH.p2, (t - 0.5) * 2)
}

/**
 * 粉笔文字折行(纯函数):估宽 CJK≈1em/字、ASCII≈0.6em/字;按词边界(空格/·/顿号/
 * 逗号等标点之后)优先切,单词超行宽才硬切,避免「焦虑 · 0.」+「8」这类断词;
 * 最多 3 行,超出截断加 …。黑板是速写不是全文,防长文本溢出画布。
 */
export function wrapChalk(str: string, size: number, maxWidth: number): string[] {
  const widthOf = (s: string): number =>
    [...s].reduce((w, ch) => w + (ch.charCodeAt(0) > 0x2e80 ? 1 : 0.6), 0) * size
  // 1) 切词:自然边界后分;单词仍超宽的硬切成 ≤maxWidth 的段
  const tokens: string[] = []
  for (const seg of str.split(/(?<=\s|·|、|,|,|。|;|;)/u)) {
    if (seg === '') continue
    if (widthOf(seg) <= maxWidth) {
      tokens.push(seg)
      continue
    }
    let hard = ''
    for (const ch of seg) {
      if (hard !== '' && widthOf(hard + ch) > maxWidth) {
        tokens.push(hard)
        hard = ch
      } else {
        hard += ch
      }
    }
    if (hard !== '') tokens.push(hard)
  }
  // 2) 贪心装行
  const lines: string[] = []
  let line = ''
  for (const tok of tokens) {
    if (line !== '' && widthOf(line + tok) > maxWidth) {
      lines.push(line)
      line = tok
    } else {
      line += tok
    }
  }
  if (line !== '') lines.push(line)
  // 3) 超过 3 行截断
  if (lines.length > 3) {
    const kept = lines.slice(0, 3)
    const last = kept[2] ?? ''
    kept[2] = `${last.slice(0, Math.max(0, [...last].length - 1))}…`
    return kept
  }
  return lines
}

/** 连线就近接椭圆边:水平接近接左右缘,垂直接近接上下缘(缩放到椭圆归一坐标比较) */
function edgePoint(zone: Zone, from: { x: number; y: number }): { x: number; y: number } {
  const rx = zone.rx ?? 60
  const ry = zone.ry ?? 24
  const dx = from.x - zone.cx
  const dy = from.y - zone.cy
  if (Math.abs(dx) * ry > Math.abs(dy) * rx) {
    return dx < 0 ? { x: zone.cx - rx - 4, y: zone.cy } : { x: zone.cx + rx + 4, y: zone.cy }
  }
  return dy < 0 ? { x: zone.cx, y: zone.cy - ry - 4 } : { x: zone.cx, y: zone.cy + ry + 4 }
}

interface Prim {
  el: SVGElement
  delay: number // 秒
  cursor: { x: number; y: number } | null
}

interface ChalkOpts {
  stroke?: string
  width?: number
  fill?: string
  dashed?: string // dash 数组串,如 "3 9";缺省走 dash-reveal
  opacity?: number
}

let filterSeq = 0

export class BoardRenderer {
  private templateId: string | null = null
  private lastData: TemplateData | null = null
  private lastSubjectId: string | null = null
  private timers: number[] = []
  private prims: Prim[] = []
  /** 转场淡出计时器:非空=淡出进行中,期间新 render 立即完成切换(最新帧赢,不排队) */
  private fadeTimer: number | null = null
  /** 淡出后的续画动作(转场状态机单字段:pending 动作即实现,不引入队列) */
  private pendingPaint: (() => void) | null = null
  private readonly svg: SVGSVGElement
  private readonly gfxRoot: SVGGElement // 图形层(滤镜)
  private readonly textRoot: SVGGElement // 文字层(不滤镜)
  private readonly cursorCircles: SVGCircleElement[]
  private readonly cursorG: SVGGElement

  constructor(private readonly mount: HTMLElement) {
    const doc = mount.ownerDocument
    const mk = <T extends SVGElement>(name: string): T => doc.createElementNS(NS, name) as T
    const svg = mk<SVGSVGElement>('svg')
    svg.setAttribute('viewBox', '0 0 640 440')
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet')
    svg.setAttribute('width', '100%')
    svg.setAttribute('height', '100%')

    // 滤镜只挂图形组;id 加实例序号防多实例冲突
    const fid = `chalk-${++filterSeq}`
    const defs = mk<SVGElement>('defs')
    const filter = mk<SVGElement>('filter')
    filter.setAttribute('id', fid)
    filter.setAttribute('x', '-5%')
    filter.setAttribute('y', '-5%')
    filter.setAttribute('width', '110%')
    filter.setAttribute('height', '110%')
    const turb = mk<SVGElement>('feTurbulence')
    turb.setAttribute('type', 'fractalNoise')
    turb.setAttribute('baseFrequency', '0.85')
    turb.setAttribute('numOctaves', '2')
    turb.setAttribute('result', 'n')
    const disp = mk<SVGElement>('feDisplacementMap')
    disp.setAttribute('in', 'SourceGraphic')
    disp.setAttribute('in2', 'n')
    disp.setAttribute('scale', '1.3')
    filter.append(turb, disp)
    defs.append(filter)

    const gfx = mk<SVGGElement>('g')
    gfx.setAttribute('filter', `url(#${fid})`)
    const text = mk<SVGGElement>('g')

    const cursor = mk<SVGGElement>('g')
    cursor.setAttribute('id', 'chalkCursor')
    cursor.setAttribute('opacity', '0')
    const halo = mk<SVGCircleElement>('circle')
    halo.setAttribute('r', '9')
    halo.setAttribute('fill', 'rgba(243,235,221,.08)')
    const tip = mk<SVGCircleElement>('circle')
    tip.setAttribute('r', '3.5')
    tip.setAttribute('fill', 'rgba(243,235,221,.85)')
    cursor.append(halo, tip)

    svg.append(defs, gfx, text, cursor)
    mount.replaceChildren(svg)
    this.svg = svg
    this.gfxRoot = gfx
    this.textRoot = text
    this.cursorG = cursor
    this.cursorCircles = [halo, tip]
  }

  render(templateId: string, data: TemplateData): void {
    let decl: TemplateDecl
    try {
      decl = get(templateId)
    } catch {
      logger.warn('board', `未知模板,跳帧: ${templateId}`)
      return
    }
    if (templateId !== this.templateId) {
      // 换模板:走转场管线(淡出旧画面→清→新画面随 prim 渐现);淡出中到达则直接换(最新帧赢)
      this.transitionTo(() => {
        this.templateId = templateId
        this.lastData = null
        this.lastSubjectId = null
        this.paintScene(decl, data)
        this.paintFields(decl, data)
      })
      return
    }
    this.paintFields(decl, data)
  }

  /** 字段绘制:diff 出变化字段 → 清该字段组重画(连线随组重画);null=擦除不画 */
  private paintFields(decl: TemplateDecl, data: TemplateData): void {
    const changed = diff(this.lastData, data)
    let delay = 0.1
    let drew = false
    for (const key of changed) {
      const field = decl.fields.find((f) => f.key === key)
      if (field === undefined) continue
      const groupKey = field.group ?? field.key
      this.clearField(groupKey)
      const value = fieldOf(data, key)
      if (value === null || value === undefined) continue // 留白格:擦除旧组即止
      this.paintField(field, decl, data, groupKey, delay)
      delay += FIELD_STAGGER_S
      drew = true
    }
    this.lastData = data
    this.paintSubject(decl, data)
    if (drew) this.schedulePrims()
  }

  /** 画面主体:与字段图标平等的选材项(assets.subject)——选材与 zones.subject 声明都在才画。
   *  随每帧比对选材值,变了清旧组重画;无选材=主体位空着(不兜底,避免语义不明图标突兀)。 */
  private paintSubject(decl: TemplateDecl, data: TemplateData): void {
    const subjectAsset =
      'assets' in data ? (data as SceneFormulationData).assets?.['subject'] : undefined
    const prev = this.lastSubjectId
    this.lastSubjectId = typeof subjectAsset === 'string' ? subjectAsset : null
    if (this.lastSubjectId === prev) return
    this.clearField('subject')
    if (
      this.lastSubjectId !== null &&
      assetSvg(this.lastSubjectId) !== null &&
      decl.zones['subject'] !== undefined
    ) {
      const zone = decl.zones['subject']
      const rx = zone.rx ?? 120
      const ry = zone.ry ?? 110
      this.paintSceneItem(
        { icon: this.lastSubjectId, x: zone.cx - rx, y: zone.cy - ry, w: rx * 2, h: ry * 2 },
        0.2,
      )
      this.schedulePrims()
    }
  }

  /** first_frame 清黑板:淡出旧画面(如有)→ 回到空板 */
  clear(): void {
    this.transitionTo(() => {
      this.templateId = null
      this.lastData = null
      this.lastSubjectId = null
    })
  }

  destroy(): void {
    this.clearTimers()
    if (this.fadeTimer !== null) {
      window.clearTimeout(this.fadeTimer)
      this.fadeTimer = null
    }
    this.pendingPaint = null
  }

  /**
   * 转场管线:所有场景切换走这一条——
   * 有旧画面 → gfx/text 双层整体淡出 0.55s → 清板 → 执行 pending;
   * 板上无内容(空板起步/淡出中再切)→ 立即执行 pending 不转场。
   * 最新帧赢:淡出期间新请求直接取替 pending,不排队。
   */
  private transitionTo(paint: () => void): void {
    this.pendingPaint = paint
    const hasContent =
      this.gfxRoot.firstElementChild !== null || this.textRoot.firstElementChild !== null
    if (!hasContent) {
      this.finishTransition()
      return
    }
    if (this.fadeTimer !== null) return // 淡出已在途:pending 已更新,等现有计时器触发即可
    this.clearTimers()
    this.prims = []
    this.cursorG.setAttribute('opacity', '0')
    this.gfxRoot.style.transition = `opacity ${FADE_OUT_S}s ease`
    this.textRoot.style.transition = `opacity ${FADE_OUT_S}s ease`
    this.gfxRoot.style.opacity = '0'
    this.textRoot.style.opacity = '0'
    this.fadeTimer = window.setTimeout(() => {
      this.fadeTimer = null
      this.finishTransition()
    }, FADE_OUT_S * 1000)
  }

  /** 淡出完成:清板+复位透明度+执行挂起动作 */
  private finishTransition(): void {
    const paint = this.pendingPaint
    this.pendingPaint = null
    this.resetCanvas()
    this.gfxRoot.style.transition = ''
    this.textRoot.style.transition = ''
    this.gfxRoot.style.opacity = ''
    this.textRoot.style.opacity = ''
    paint?.()
  }

  /** resetCanvas:取消未落笔的绘制,清空双层(转场管线终态;同步直清语义保留给测试) */
  private resetCanvas(): void {
    this.clearTimers()
    this.prims = []
    for (const g of [this.gfxRoot, this.textRoot]) {
      while (g.firstElementChild !== null) g.firstElementChild.remove()
    }
    this.cursorG.setAttribute('opacity', '0')
  }

  private clearField(groupKey: string): void {
    for (const root of [this.gfxRoot, this.textRoot]) {
      root.querySelector(`g[data-field="${groupKey}"]`)?.remove()
    }
  }

  private ensureFieldGroup(root: SVGGElement, groupKey: string): SVGGElement {
    const existing = root.querySelector(`g[data-field="${groupKey}"]`)
    if (existing !== null) return existing as SVGGElement
    const g = this.svg.ownerDocument.createElementNS(NS, 'g') as SVGGElement
    g.setAttribute('data-field', groupKey)
    root.append(g)
    return g
  }

  private zoneOf(decl: TemplateDecl, field: FieldDecl): Zone | undefined {
    const id = field.anchor.startsWith('zone:') ? field.anchor.slice(5) : field.anchor
    const zone = decl.zones[id]
    if (zone === undefined) logger.warn('board', `模板 ${decl.id} 缺锚点 ${field.anchor}`)
    return zone
  }

  private paintField(field: FieldDecl, decl: TemplateDecl, data: TemplateData, groupKey: string, delay: number): void {
    const zone = this.zoneOf(decl, field)
    if (zone === undefined) return
    const gfx = this.ensureFieldGroup(this.gfxRoot, groupKey)
    const text = this.ensureFieldGroup(this.textRoot, groupKey)
    switch (field.widget) {
      case 'rough_ellipse+text':
      case 'highlight': {
        const warm = field.widget === 'highlight'
        if (zone.connectFrom) {
          const to = edgePoint(zone, zone.connectFrom)
          this.roughLine(gfx, zone.connectFrom.x, zone.connectFrom.y, to.x, to.y, {
            stroke: CHALK_SUB,
            width: 1.6,
          }, delay)
        }
        this.roughEllipse(gfx, zone.cx, zone.cy, zone.rx ?? 60, zone.ry ?? 24, {
          stroke: warm ? WARM : CHALK,
          width: warm ? 2.4 : 2,
        }, delay + 0.2)
        const label = displayText(field, fieldOf(data, field.key))
        if (label !== '') {
          this.chalkText(text, zone.cx, zone.cy + 5, label, {
            size: field.size ?? 15,
            color: warm ? WARM : CHALK,
            maxWidth: (zone.rx ?? 60) * 2 - 8,
          }, delay + 0.45)
        }
        break
      }
      case 'rough_box+text': {
        this.roughRect(gfx, (zone.cx ?? 320) - (zone.rx ?? 100), (zone.cy ?? 220) - (zone.ry ?? 30), (zone.rx ?? 100) * 2, (zone.ry ?? 30) * 2, { stroke: CHALK, width: 2 }, delay)
        const label = displayText(field, fieldOf(data, field.key))
        if (label !== '') {
          this.chalkText(text, zone.cx, zone.cy + 5, label, {
            size: field.size ?? 15,
            maxWidth: (zone.rx ?? 100) * 2 - 18,
          }, delay + 0.45)
        }
        break
      }
      case 'text': {
        const label = displayText(field, fieldOf(data, field.key))
        if (label !== '') this.chalkText(text, zone.cx, zone.cy, label, { size: field.size ?? 16, maxWidth: 500 }, delay)
        break
      }
      case 'wheel_mini':
        this.paintWheel(gfx, text, data as EmotionWheelData, zone, delay)
        break
      case 'stage_nodes':
        this.paintStage(gfx, text, data as StageMapData, delay)
        break
      case 'icon+text': {
        // 场景槽位:图标为主(选材 id 优先,未知/缺省落声明默认),文字弱化为图标下小字
        const assets = 'assets' in data ? (data as SceneFormulationData).assets : undefined
        const chosen = assets?.[field.key as keyof typeof assets]
        const iconId = typeof chosen === 'string' && assetSvg(chosen) !== null ? chosen : field.icon
        if (iconId !== undefined) {
          const rx = zone.rx ?? 60
          const ry = zone.ry ?? 60
          this.paintSceneItem(
            { icon: iconId, x: zone.cx - rx, y: zone.cy - ry, w: rx * 2, h: ry * 2 },
            delay,
          )
        }
        const label = displayText(field, fieldOf(data, field.key))
        if (label !== '') {
          this.chalkText(text, zone.cx, zone.cy + (zone.ry ?? 60) + 16, label, {
            size: field.size ?? 13,
            color: CHALK_SUB,
            maxWidth: (zone.rx ?? 60) * 2 + 40,
          }, delay + 0.3)
        }
        break
      }
    }
  }

  /** 情绪轮:中心圆 + 轮辐 + 外圈小圆(每情绪一色,半径随 intensity) */
  private paintWheel(gfx: SVGGElement, text: SVGGElement, data: EmotionWheelData, zone: Zone, delay: number): void {
    const { cx, cy } = zone
    const r = zone.rx ?? 40
    this.roughEllipse(gfx, cx, cy, r, zone.ry ?? r, { stroke: WARM, width: 2.4 }, delay)
    this.chalkText(text, cx, cy + 5, '此刻', { size: 14, color: WARM }, delay + 0.2)
    const n = data.emotions.length
    if (n === 0) return
    const R = 150
    data.emotions.forEach((e, i) => {
      const angle = ((-90 + (i * 360) / n) * Math.PI) / 180
      const ox = cx + R * Math.cos(angle)
      const oy = cy + R * Math.sin(angle)
      this.roughLine(gfx, cx + (r + 4) * Math.cos(angle), cy + (r + 4) * Math.sin(angle), ox, oy, { stroke: CHALK_SUB, width: 1.4 }, delay + 0.4 + i * 0.35)
      const orb = 10 + Math.min(Math.max(e.intensity, 0), 1) * 8
      this.roughEllipse(gfx, ox, oy, orb, orb, { stroke: e.color, width: 2, fill: `${e.color}22` }, delay + 0.6 + i * 0.35)
      this.chalkText(text, ox, oy + 26, e.label, { size: 12 }, delay + 0.8 + i * 0.35)
    })
  }

  /** 阶段路线图:主径 + 虚线延伸 + 节点圆(current 高亮)+ 终点小太阳 */
  private paintStage(gfx: SVGGElement, text: SVGGElement, data: StageMapData, delay: number): void {
    this.roughPath(gfx, `M${STAGE_PATH.p0.x} ${STAGE_PATH.p0.y} Q${STAGE_PATH.c1.x} ${STAGE_PATH.c1.y} ${STAGE_PATH.p1.x} ${STAGE_PATH.p1.y} Q${STAGE_PATH.c2.x} ${STAGE_PATH.c2.y} ${STAGE_PATH.p2.x} ${STAGE_PATH.p2.y}`, { stroke: CHALK, width: 2.4 }, delay)
    this.roughPath(gfx, `M${STAGE_PATH.p2.x} ${STAGE_PATH.p2.y} Q600 70 660 60`, { stroke: CHALK, width: 2, dashed: '3 9', opacity: 0.5 }, delay + 1.0)
    const n = data.nodes.length
    data.nodes.forEach((label, i) => {
      const t = n === 1 ? 0 : i / (n - 1)
      const p = stagePoint(t)
      const isCur = i === data.current
      this.roughEllipse(gfx, p.x, p.y, isCur ? 18 : 15, isCur ? 18 : 15, {
        stroke: isCur ? WARM : CHALK,
        width: isCur ? 2.4 : 2,
        fill: isCur ? 'rgba(232,217,168,.18)' : 'none',
      }, delay + 0.5 + i * 0.5)
      this.chalkText(text, p.x, p.y + 34, label, { size: isCur ? 16 : 14, color: isCur ? WARM : CHALK }, delay + 0.7 + i * 0.5)
    })
    this.roughEllipse(gfx, STAGE_PATH.p2.x, STAGE_PATH.p2.y, 24, 24, { stroke: WARM, width: 2, fill: 'rgba(232,217,168,.14)' }, delay + 0.8 + n * 0.5)
  }

  // ── 场景化(blackboard-v1):预绑定底图 + 槽位图标 ──

  /** 场景底图:模板声明预绑定元素序列,一次性画入(仅换模板/清板后的首绘路径)。
   *  场景层只画预绑定装饰(分隔线等);主体/字段图标全由选材驱动,不在此层兜底 */
  private paintScene(decl: TemplateDecl, data: TemplateData): void {
    const items = decl.scene
    if (items !== undefined) {
      items.forEach((item, i) => {
        if (item.kind === 'line') {
          this.roughLine(this.gfxRoot, item.x1 ?? 0, item.y1 ?? 0, item.x2 ?? 0, item.y2 ?? 0, {
            stroke: 'rgba(243,235,221,.35)',
            width: 1.2,
          }, item.delay ?? i * 0.35)
        } else if (item.icon !== undefined) {
          this.paintSceneItem(item as SceneItem & { icon: string }, item.delay ?? i * 0.35)
        }
      })
    }
    // 固定场景的注释行(scene_answer/scene_crisis):note 进底部小字区
    if ('note' in data) {
      const note = (data as { note: string | null }).note
      if (note !== null && note !== '') this.chalkText(this.textRoot, 320, 420, note, { size: 15, color: CHALK_SUB, maxWidth: 520 }, 0.1)
    }
    this.schedulePrims()
  }

  /** 单个场景图标:SVG 内联进 <g>,等比 contain 适配放置区,currentColor 继承粉笔色 */
  private paintSceneItem(item: SceneItem & { icon: string }, delay: number): void {
    const svgText = assetSvg(item.icon)
    if (svgText === null) {
      logger.warn('board', `未知素材 id,跳过: ${item.icon}`)
      return
    }
    const x = item.x ?? 0
    const y = item.y ?? 0
    const w = item.w ?? 100
    const h = item.h ?? 100
    // 外层 g 定位+着色,内层 g 作动画单元(koboyo 内层是散装 path,需自己包一层)
    const outer = this.el(this.gfxRoot, 'g', { 'data-scene-icon': item.icon })
    const prim = this.svg.ownerDocument.createElementNS(NS, 'g')
    this.inlineSvg(outer, prim, svgText, { ...item, x, y, w, h })
    prim.classList.add('board-primitive')
    this.prims.push({ el: prim, delay, cursor: { x: x + w / 2, y: y + h / 2 } })
  }

  /**
   * SVG 内联:取根 <svg> 内层装进动画 g(koboyo 根标签 fill=currentColor 提取内层后会丢,
   * 外层必须补 fill,否则回落黑色——原型页踩过的坑);viewBox 等比 contain 缩放居中。
   */
  private inlineSvg(outer: SVGElement, prim: SVGElement, svgText: string, item: { x: number; y: number; w: number; h: number }): void {
    const vb = svgText.match(/viewBox="([^"]+)"/)?.[1]
    const inner = svgText.match(/<svg[^>]*>([\s\S]*)<\/svg>/)?.[1] ?? ''
    const [vx = 0, vy = 0, vw = 100, vh = 100] = (vb ?? '').split(/[\s,]+/).map(Number)
    const s = Math.min(item.w / vw, item.h / vh)
    const x = item.x + (item.w - vw * s) / 2
    const y = item.y + (item.h - vh * s) / 2
    outer.setAttribute('fill', 'currentColor')
    outer.setAttribute('transform', `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${s.toFixed(4)}) translate(${-vx} ${-vy})`)
    // 纯粉笔白定稿:一律粉笔白;tone 声明保留作对照,暖点缀方案时按 tone 分色
    outer.setAttribute('color', CHALK)
    prim.innerHTML = inner
    outer.append(prim)
  }

  // ── 粉笔原语(中点抖动/半径噪声/dash-reveal/光标跟随)──

  private jitter(scale = 2.2): number {
    return (Math.random() - 0.5) * 2 * scale
  }

  private addPrim(el: SVGElement, delay: number, cursor: { x: number; y: number } | null, reveal: boolean): void {
    el.classList.add('board-primitive')
    if (reveal) el.classList.add('dash')
    this.prims.push({ el, delay, cursor })
  }

  private roughLine(g: SVGGElement, x1: number, y1: number, x2: number, y2: number, o: ChalkOpts, delay: number): void {
    const mx = (x1 + x2) / 2 + this.jitter()
    const my = (y1 + y2) / 2 + this.jitter()
    const attrs: Record<string, string | number> = {
      d: `M${x1} ${y1} Q${mx.toFixed(1)} ${my.toFixed(1)} ${x2} ${y2}`,
      stroke: o.stroke ?? CHALK,
      'stroke-width': o.width ?? 2,
      fill: 'none',
      'stroke-linecap': 'round',
    }
    if (o.dashed !== undefined) attrs['stroke-dasharray'] = o.dashed
    const el = this.el(g, 'path', attrs)
    this.addPrim(el, delay, { x: (x1 + x2) / 2, y: (y1 + y2) / 2 }, o.dashed === undefined)
  }

  private roughEllipse(g: SVGGElement, cx: number, cy: number, rx: number, ry: number, o: ChalkOpts, delay: number): void {
    const attrs: Record<string, string | number> = {
      cx,
      cy,
      rx: rx + (Math.random() - 0.5) * 1.6,
      ry: ry + (Math.random() - 0.5) * 1.6,
      fill: o.fill ?? 'none',
      stroke: o.stroke ?? CHALK,
      'stroke-width': o.width ?? 2,
    }
    if (o.dashed !== undefined) attrs['stroke-dasharray'] = o.dashed
    const el = this.el(g, 'ellipse', attrs)
    this.addPrim(el, delay, { x: cx, y: cy }, o.dashed === undefined)
  }

  private roughRect(g: SVGGElement, x: number, y: number, w: number, h: number, o: ChalkOpts, delay: number): void {
    const j = () => this.jitter(1.6)
    const r = 10
    const d = [
      `M${x + r + j()} ${y + j()}`,
      `L${x + w - r + j()} ${y + j()}`,
      `Q${x + w} ${y} ${x + w + j()} ${y + r + j()}`,
      `L${x + w + j()} ${y + h - r + j()}`,
      `Q${x + w} ${y + h} ${x + w - r + j()} ${y + h + j()}`,
      `L${x + r + j()} ${y + h + j()}`,
      `Q${x} ${y + h} ${x + j()} ${y + h - r + j()}`,
      `L${x + j()} ${y + r + j()}`,
      `Q${x} ${y} ${x + r + j()} ${y + j()}`,
    ].join(' ')
    const el = this.el(g, 'path', {
      d,
      stroke: o.stroke ?? CHALK,
      'stroke-width': o.width ?? 2,
      fill: o.fill ?? 'none',
      'stroke-linecap': 'round',
    })
    this.addPrim(el, delay, { x: x + w / 2, y: y + h / 2 }, true)
  }

  private roughPath(g: SVGGElement, d: string, o: ChalkOpts, delay: number): void {
    const attrs: Record<string, string | number> = {
      d,
      stroke: o.stroke ?? CHALK,
      'stroke-width': o.width ?? 2,
      fill: 'none',
      'stroke-linecap': 'round',
    }
    if (o.dashed !== undefined) attrs['stroke-dasharray'] = o.dashed
    if (o.opacity !== undefined) attrs.opacity = o.opacity
    const el = this.el(g, 'path', attrs)
    this.addPrim(el, delay, null, o.dashed === undefined)
  }

  private chalkText(
    g: SVGGElement,
    x: number,
    y: number,
    str: string,
    o: { size?: number; color?: string; anchor?: string; maxWidth?: number },
    delay: number,
  ): void {
    const size = o.size ?? 16
    // 有 maxWidth 则折行(≤3 行,超出 …),多行绕中心纵排
    const lines = o.maxWidth !== undefined ? wrapChalk(str, size, o.maxWidth) : [str]
    const lineH = size * 1.3
    lines.forEach((line, i) => {
      const ly = y - ((lines.length - 1) * lineH) / 2 + i * lineH
      const el = this.el(g, 'text', {
        x,
        y: ly,
        'text-anchor': o.anchor ?? 'middle',
        'font-size': size,
        fill: o.color ?? CHALK,
        'font-family': HAND,
        'letter-spacing': '.03em',
      })
      el.textContent = line
      this.addPrim(el, delay + i * 0.15, { x, y: ly }, false)
    })
  }

  private el(parent: SVGGElement, name: string, attrs: Record<string, string | number>): SVGElement {
    const e = this.svg.ownerDocument.createElementNS(NS, name) as SVGElement
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v))
    parent.append(e)
    return e
  }

  /** 按延迟落笔 + 光标跟随,末笔后驻留隐藏 */
  private schedulePrims(): void {
    let maxDelay = 0
    for (const p of this.prims) {
      maxDelay = Math.max(maxDelay, p.delay)
      const cur = p.cursor
      this.timers.push(
        window.setTimeout(() => {
          p.el.classList.add('on')
          if (cur !== null) {
            this.cursorG.setAttribute('opacity', '1')
            for (const c of this.cursorCircles) {
              c.setAttribute('cx', String(cur.x))
              c.setAttribute('cy', String(cur.y))
            }
          }
        }, p.delay * 1000),
      )
    }
    const prims = this.prims
    this.prims = []
    this.timers.push(
      window.setTimeout(() => {
        if (prims.length > 0) this.cursorG.setAttribute('opacity', '0')
      }, (maxDelay + CURSOR_LINGER_S) * 1000),
    )
  }

  private clearTimers(): void {
    for (const t of this.timers) window.clearTimeout(t)
    this.timers = []
  }
}

/** 字段值 → 粉笔展示文字:字符串加标签前缀;emotion 对象只取 label(intensity 不上黑板,黑板非仪表盘) */
function displayText(field: FieldDecl, value: unknown): string {
  const prefix = field.label !== undefined ? `${field.label} · ` : ''
  if (typeof value === 'string') return `${prefix}${value}`
  if (isEmotion(value)) {
    return value.label !== null && value.label !== '' ? `${prefix}${value.label}` : ''
  }
  return ''
}

function isEmotion(v: unknown): v is Emotion {
  return typeof v === 'object' && v !== null && 'label' in v && 'intensity' in v
}
