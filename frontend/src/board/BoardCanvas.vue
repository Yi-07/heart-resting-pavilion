<script setup lang="ts">
// 黑板画布:v7 板框(细橡木+四角 HUD+呼吸光晕)+ 板 chrome(标题/底注/状态/zoom)。
// 绘制委托 BoardRenderer(imperative SVG);暴露 render/clear 给 App 的 WS 帧接线。
import { onMounted, onUnmounted, ref } from 'vue'
import type { TemplateData } from '../ws/messages'
import { BoardRenderer } from './renderer'
import './templates'

const props = defineProps<{
  title: string
  note: string
  status?: string
  warn?: boolean
}>()

const stageEl = ref<HTMLElement | null>(null)
const zoomed = ref(false)
let renderer: BoardRenderer | null = null

onMounted(() => {
  if (stageEl.value !== null) renderer = new BoardRenderer(stageEl.value)
})

onUnmounted(() => {
  renderer?.destroy()
  renderer = null
})

function render(templateId: string, data: TemplateData): void {
  renderer?.render(templateId, data)
}

function clear(): void {
  renderer?.clear()
}

defineExpose({ render, clear })
</script>

<template>
  <div class="board-frame" :class="{ zoomed }" data-testid="board-frame">
    <span class="hud hud-tl"></span><span class="hud hud-tr"></span><span class="hud hud-bl"></span><span class="hud hud-br"></span>
    <div class="board">
      <div class="bt">{{ props.title }}</div>
      <div ref="stageEl" class="bstage" data-testid="board-stage"></div>
      <div class="bs-status" :class="{ on: props.status !== undefined && props.status !== '', warn: props.warn }">
        {{ props.status }}
      </div>
      <div class="bnote">✎ {{ props.note }}</div>
      <button class="zoom-btn" title="放大查看完整绘图" @click="zoomed = !zoomed">
        <svg viewBox="0 0 24 24"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.board-frame {
  --hud: rgba(214, 178, 102, 0.85);
  position: absolute;
  left: 0;
  top: 0;
  width: 64%;
  aspect-ratio: var(--canvas-ratio);
  border-radius: 16px;
  padding: 7px;
  background:
    repeating-linear-gradient(100deg, rgba(255, 255, 255, 0.05) 0 2px, transparent 2px 6px),
    linear-gradient(140deg, #e6d2b0, #cbae82 55%, #b69567);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.4),
    0 24px 60px -28px rgba(47, 58, 49, 0.55);
}
.board-frame.zoomed {
  position: fixed;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: min(calc(100vw - 80px), calc((100vh - 80px) * var(--canvas-ratio)));
  z-index: 90;
  border-radius: 22px;
  box-shadow: 0 40px 90px -30px rgba(47, 58, 49, 0.6);
}
.hud {
  position: absolute;
  width: 26px;
  height: 26px;
  z-index: 5;
  animation: hudpulse 2.8s ease-in-out infinite;
  filter: drop-shadow(0 1px 3px rgba(62, 58, 53, 0.28));
}
.hud-tl { left: -9px; top: -9px; border-left: 2px solid var(--hud); border-top: 2px solid var(--hud); border-top-left-radius: 6px; }
.hud-tr { right: -9px; top: -9px; border-right: 2px solid var(--hud); border-top: 2px solid var(--hud); border-top-right-radius: 6px; }
.hud-bl { left: -9px; bottom: -9px; border-left: 2px solid var(--hud); border-bottom: 2px solid var(--hud); border-bottom-left-radius: 6px; }
.hud-br { right: -9px; bottom: -9px; border-right: 2px solid var(--hud); border-bottom: 2px solid var(--hud); border-bottom-right-radius: 6px; }
@keyframes hudpulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
.board {
  position: absolute;
  inset: 7px;
  border-radius: 8px;
  overflow: hidden;
  background: linear-gradient(160deg, #41503f, #2f3a31 60%);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12);
  animation: breathglow 3.6s ease-in-out infinite;
}
@keyframes breathglow {
  0%, 100% { box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12), 0 0 18px -10px rgba(232, 217, 168, 0.16); }
  50% { box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12), 0 0 42px -8px rgba(232, 217, 168, 0.38); }
}
/* 粉笔颗粒噪点 */
.board::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.3;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E");
}
/* 暗角 */
.board::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(90% 90% at 50% 40%, transparent 60%, rgba(0, 0, 0, 0.32) 100%);
}
.bt {
  position: absolute;
  left: 22px;
  top: 16px;
  font-family: var(--serif);
  font-size: 18px;
  color: var(--chalk);
  letter-spacing: 0.05em;
  z-index: 3;
}
.bstage {
  position: absolute;
  inset: 0;
  z-index: 2;
}
.bstage :deep(svg) {
  width: 100%;
  height: 100%;
}
.bnote {
  position: absolute;
  left: 22px;
  bottom: 14px;
  font-size: 14px;
  color: var(--chalk-sub);
  line-height: 1.7;
  z-index: 3;
  font-family: var(--hand);
}
.bs-status {
  position: absolute;
  right: 56px;
  bottom: 18px;
  font-size: 11px;
  color: #e8d9a8;
  z-index: 3;
  opacity: 0;
  transition: opacity 0.4s;
}
.bs-status.on { opacity: 1; }
.bs-status.warn { color: #e8b4a0; }
.zoom-btn {
  position: absolute;
  right: 16px;
  bottom: 16px;
  z-index: 30;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 0;
  background: rgba(243, 235, 221, 0.22);
  color: var(--chalk);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  box-shadow: 0 3px 10px -3px rgba(0, 0, 0, 0.4);
}
.zoom-btn:hover { background: rgba(243, 235, 221, 0.34); }
.zoom-btn svg {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
</style>
