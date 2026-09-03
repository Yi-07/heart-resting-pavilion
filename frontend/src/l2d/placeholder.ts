// Live2D 留位(步骤 7 换 pixi-live2d-display):SVG 手绘立绘兜底 + 情绪→表情映射。
// expressionFor 供 setExpression 同款语义:未知标签落 neutral 兜底。

export type AvatarExpr = 'neutral' | 'tired' | 'warm' | 'calm' | 'worried'

const FACE: Record<AvatarExpr, string> = {
  neutral:
    '<ellipse cx="68" cy="78" rx="5" ry="7" fill="#3A2E26"/><ellipse cx="92" cy="78" rx="5" ry="7" fill="#3A2E26"/><circle cx="70" cy="76" r="1.5" fill="#fff"/><circle cx="94" cy="76" r="1.5" fill="#fff"/><path d="M74 94 Q80 98 86 94" stroke="#C9705B" stroke-width="2.3" fill="none" stroke-linecap="round"/>',
  tired:
    '<ellipse cx="68" cy="84" rx="5" ry="4.6" fill="#3A2E26"/><ellipse cx="92" cy="84" rx="5" ry="4.6" fill="#3A2E26"/><path d="M63 76 Q68 79 73 76" stroke="#3A2E26" stroke-width="1.7" fill="none" stroke-linecap="round"/><path d="M87 76 Q92 79 97 76" stroke="#3A2E26" stroke-width="1.7" fill="none" stroke-linecap="round"/><path d="M73 95 Q80 91 87 95" stroke="#C9705B" stroke-width="2.3" fill="none" stroke-linecap="round"/>',
  warm:
    '<path d="M61 76 Q68 71 75 76" stroke="#3A2E26" stroke-width="2.1" fill="none" stroke-linecap="round"/><path d="M85 76 Q92 71 99 76" stroke="#3A2E26" stroke-width="2.1" fill="none" stroke-linecap="round"/><path d="M70 92 Q80 101 90 92" stroke="#C9705B" stroke-width="2.3" fill="none" stroke-linecap="round"/>',
  calm:
    '<path d="M63 80 Q68 76 73 80" stroke="#3A2E26" stroke-width="1.9" fill="none" stroke-linecap="round"/><path d="M87 80 Q92 76 97 80" stroke="#3A2E26" stroke-width="1.9" fill="none" stroke-linecap="round"/><path d="M74 94 Q80 97 86 94" stroke="#C9705B" stroke-width="2.2" fill="none" stroke-linecap="round"/>',
  worried:
    '<path d="M63 70 L71 73" stroke="#3A2E26" stroke-width="1.8" fill="none" stroke-linecap="round"/><path d="M97 70 L89 73" stroke="#3A2E26" stroke-width="1.8" fill="none" stroke-linecap="round"/><ellipse cx="68" cy="81" rx="4.6" ry="6.2" fill="#3A2E26"/><ellipse cx="92" cy="81" rx="4.6" ry="6.2" fill="#3A2E26"/><circle cx="70" cy="79" r="1.4" fill="#fff"/><circle cx="94" cy="79" r="1.4" fill="#fff"/><path d="M74 95 Q80 92 86 95" stroke="#C9705B" stroke-width="2.3" fill="none" stroke-linecap="round"/>',
}

/** 情绪标签 → 表情(喂 state.emotionLabel;未知落 neutral) */
export function expressionFor(label: string | null): AvatarExpr {
  if (label === null) return 'neutral'
  if (/疲惫|累|倦/.test(label)) return 'tired'
  if (/焦虑|担心|不安|紧张|害怕/.test(label)) return 'worried'
  if (/平静|放松|安宁/.test(label)) return 'calm'
  if (/开心|高兴|愉快|不错|幸福/.test(label)) return 'warm'
  return 'neutral'
}

export function avatarSvg(expr: AvatarExpr): string {
  return `<svg viewBox="0 0 160 190" xmlns="http://www.w3.org/2000/svg">
    <path d="M32 52 Q30 16 80 14 Q130 16 128 52 L122 70 Q116 44 80 42 Q44 44 38 70 Z" fill="#4A3B32"/>
    <path d="M54 152 Q56 110 80 110 Q104 110 106 152 L103 190 L57 190 Z" fill="#8BAE97"/>
    <path d="M80 22 Q116 24 120 60 Q120 88 111 101 L102 97 Q113 80 113 56 Q113 32 80 30 Z" fill="#4A3B32"/>
    <ellipse cx="80" cy="70" rx="33" ry="36" fill="#F5DCC8"/>
    <path d="M47 60 Q45 36 80 34 Q115 36 113 60 Q113 44 80 42 Q47 44 47 60 Z" fill="#4A3B32"/>
    <path d="M47 60 Q45 84 53 96 Q59 109 68 118 L63 115 Q50 99 50 78 Z" fill="#4A3B32"/>
    <path d="M113 60 Q115 84 107 96 Q101 109 92 118 L97 115 Q110 99 110 78 Z" fill="#4A3B32"/>
    ${FACE[expr]}
  </svg>`
}
