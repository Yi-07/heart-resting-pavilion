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

export function registerTemplates(): void {
  register(beckFormulation)
  register(emotionWheel)
  register(stageMap)
}

registerTemplates()
