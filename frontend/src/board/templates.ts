// 三个测试模板声明(布局坐标单源,源自 preview/l1-ui-mockup-v7 粉笔布局)。
// beck 树状三层:顶=情境,中=情绪圆+想法,左=中间信念/右=行为(镜像对称,mockup 未画中间信念,
// 按 behavior 镜像补 (88,318,62×26)),底=核心信念;连线自 connectFrom 起画到格上缘。

import type { TemplateDecl } from './types'
import { register } from './templateRegistry'

/** beck_formulation:认知概念化六字段(situation 在顶,emotion 居中,thought 第三层…) */
const beckFormulation: TemplateDecl = {
  id: 'beck_formulation',
  title: '心里的那棵树',
  zones: {
    top: { cx: 320, cy: 52, rx: 148, ry: 26 },
    center: { cx: 320, cy: 180, rx: 44, ry: 44 },
    thought: { cx: 320, cy: 320, rx: 140, ry: 27, connectFrom: { x: 320, y: 240 } },
    left: { cx: 88, cy: 318, rx: 62, ry: 26, connectFrom: { x: 180, y: 318 } },
    right: { cx: 560, cy: 318, rx: 62, ry: 26, connectFrom: { x: 460, y: 318 } },
    bottom: { cx: 320, cy: 406, rx: 158, ry: 24, connectFrom: { x: 320, y: 352 } },
  },
  fields: [
    { key: 'situation', anchor: 'zone:top', widget: 'rough_ellipse+text', size: 17 },
    { key: 'emotion', anchor: 'zone:center', widget: 'highlight', size: 15 },
    { key: 'thought', anchor: 'zone:thought', widget: 'highlight', size: 16 },
    { key: 'intermediate_belief', anchor: 'zone:left', widget: 'rough_ellipse+text', label: '中间信念', size: 12 },
    { key: 'behavior', anchor: 'zone:right', widget: 'rough_ellipse+text', size: 13 },
    { key: 'core_belief', anchor: 'zone:bottom', widget: 'highlight', label: '核心信念', size: 14 },
  ],
}

/** emotion_wheel:中心圆+轮辐+外圈情绪小圆(每情绪一色,半径随 intensity) */
const emotionWheel: TemplateDecl = {
  id: 'emotion_wheel',
  title: '情绪轮盘',
  zones: {
    center: { cx: 320, cy: 220, rx: 40, ry: 40 },
    note: { cx: 320, cy: 412 },
  },
  fields: [{ key: 'emotions', anchor: 'zone:center', widget: 'wheel_mini', group: 'wheel' }],
}

/**
 * stage_map:阶段路线图。nodes/current 同画一组(group=path):二次贝塞尔主径
 * M80,330 Q220,360 300,260 Q380,160 540,96 + 终点小太阳 + 虚线延伸;N 节点按弧长
 * 均匀采样(3 节点恰落 start/mid/end 锚点),current 放大高亮。from=底部寄语。
 */
const stageMap: TemplateDecl = {
  id: 'stage_map',
  title: '你不需要一个人扛',
  zones: {
    start: { cx: 80, cy: 330 },
    mid: { cx: 300, cy: 260 },
    end: { cx: 540, cy: 96 },
    note: { cx: 320, cy: 412 },
  },
  fields: [
    { key: 'nodes', anchor: 'zone:start', widget: 'stage_nodes', group: 'path' },
    { key: 'current', anchor: 'zone:start', widget: 'stage_nodes', group: 'path' },
    { key: 'from', anchor: 'zone:note', widget: 'text', size: 17 },
  ],
}

/**
 * scene 板式族(固定板式+序号图例+纯粉笔白,blackboard-v1):
 * 构图坐标迁移自已验收原型(prototype/index.html 三幅板式+固定场景),观感基准=原型。
 * scene_default=兜底暖场景兼开场(无字段槽位,纯陪伴);scene_focus=正题聚焦板
 * (实质披露后切上,主体与字段图标全由选材驱动);两者 collect 用,字段走 icon+text 槽位。
 * scene_answer/scene_crisis 固定场景,图标全预绑定无 LLM:
 * 纯 answer 回合首帧/采集期打岔发 scene_answer,危机发 scene_crisis。
 */

/** scene_default:兜底暖场景(夜色房子+壁炉+扶手椅+猫+热饮)——信息少时的起步画面 */
const sceneDefault: TemplateDecl = {
  id: 'scene_default',
  title: '心栖的黑板',
  zones: { note: { cx: 320, cy: 420 } },
  scene: [
    { icon: 'warm.house-night', x: 380, y: 60, w: 230, h: 170, tone: 'sub' },
    { icon: 'warm.fireplace', x: 60, y: 190, w: 160, h: 130 },
    { icon: 'warm.reading-armchair', x: 240, y: 170, w: 190, h: 190 },
    { icon: 'warm.cat', x: 440, y: 300, w: 110, h: 90, tone: 'warm' },
    { icon: 'warm.mug', x: 120, y: 330, w: 80, h: 70, tone: 'warm' },
  ],
  fields: [],
}

/** scene_focus:正题聚焦板——主体与字段图标全由选材驱动(说什么画什么,无默认兜底);骨架自带注释分隔线 */
const sceneFocus: TemplateDecl = {
  id: 'scene_focus',
  title: '心里那摊事',
  zones: {
    subject: { cx: 320, cy: 200, rx: 120, ry: 110 },
    emotion: { cx: 175, cy: 90, rx: 55, ry: 50 },
    thought: { cx: 470, cy: 87, rx: 50, ry: 47 },
    situation: { cx: 125, cy: 305, rx: 65, ry: 55 },
    behavior: { cx: 515, cy: 305, rx: 55, ry: 55 },
    intermediate_belief: { cx: 140, cy: 195, rx: 50, ry: 45 },
    core_belief: { cx: 505, cy: 195, rx: 45, ry: 45 },
  },
  scene: [{ kind: 'line', x1: 60, y1: 372, x2: 580, y2: 372 }],
  fields: [
    { key: 'emotion', anchor: 'zone:emotion', widget: 'icon+text', icon: 'state.storm-cloud', size: 13 },
    { key: 'thought', anchor: 'zone:thought', widget: 'icon+text', icon: 'state.rain-cloud', size: 13 },
    { key: 'situation', anchor: 'zone:situation', widget: 'icon+text', icon: 'desk.cluttered', size: 13 },
    { key: 'behavior', anchor: 'zone:behavior', widget: 'icon+text', icon: 'state.scrolling-phone', size: 13 },
    { key: 'intermediate_belief', anchor: 'zone:intermediate_belief', widget: 'icon+text', icon: 'self.compare-figures', size: 12 },
    { key: 'core_belief', anchor: 'zone:core_belief', widget: 'icon+text', icon: 'self.crossroads', size: 12 },
  ],
}

/** scene_answer:answer 固定场景(阅读与思考)——纯 answer 回合/采集期打岔接管黑板 */
const sceneAnswer: TemplateDecl = {
  id: 'scene_answer',
  title: '让我想一想',
  zones: { note: { cx: 320, cy: 420 } },
  scene: [
    { icon: 'read.big-book', x: 200, y: 70, w: 240, h: 230 },
    { icon: 'read.open-book', x: 80, y: 250, w: 120, h: 100, tone: 'sub' },
    { icon: 'read.magnifier', x: 450, y: 90, w: 100, h: 95, tone: 'sub' },
    { icon: 'read.quill', x: 440, y: 260, w: 100, h: 90, tone: 'sub' },
    { icon: 'read.candle', x: 90, y: 110, w: 80, h: 90, tone: 'warm' },
  ],
  fields: [],
}

/** scene_crisis:危机固定场景(被接住)——图标预绑定零 LLM,确定性保住(定稿:纯场景帧) */
const sceneCrisis: TemplateDecl = {
  id: 'scene_crisis',
  title: '你不需要一个人扛',
  zones: { note: { cx: 320, cy: 420 } },
  scene: [
    { icon: 'crisis.catching', x: 190, y: 70, w: 250, h: 230 },
    { icon: 'crisis.lighthouse', x: 60, y: 230, w: 130, h: 140, tone: 'sub' },
    { icon: 'crisis.parachute', x: 440, y: 70, w: 110, h: 110, tone: 'sub' },
    { icon: 'crisis.holding-hand', x: 450, y: 250, w: 100, h: 90, tone: 'warm' },
    { icon: 'crisis.umbrella', x: 100, y: 90, w: 110, h: 100, tone: 'sub' },
  ],
  fields: [],
}

export function registerTemplates(): void {
  register(beckFormulation)
  register(emotionWheel)
  register(stageMap)
  register(sceneDefault)
  register(sceneFocus)
  register(sceneAnswer)
  register(sceneCrisis)
}

registerTemplates()
