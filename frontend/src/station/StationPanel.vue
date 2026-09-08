<script setup lang="ts">
// 心灵补给站面板(frontend-plan §2 station 行):等待态「正在为你整理…」/
// md 预览(renderMarkdown,子集受控+先转义)/导出 .md/重新整理。
// fixed 浮层 + .open 切换(同 .proto 模式,v7 tool-panel 同构);主题色=--moodv。
import { computed } from 'vue'
import { closeStation, exportStationReport, regenerateStation, station } from './station'
import { renderMarkdown } from './markdown'

const rendered = computed(() =>
  station.phase === 'ready' ? renderMarkdown(station.reportMd) : '',
)
</script>

<template>
  <section class="station glass" :class="{ open: station.open }" data-testid="station-panel">
    <header class="st-h">
      心灵补给站
      <button
        class="st-x"
        title="收起"
        data-testid="station-close"
        @click="closeStation()"
      >✕</button>
    </header>
    <div class="st-body" data-testid="station-body">
      <p v-if="station.phase === 'pending'" class="st-wait" data-testid="station-wait">
        {{ station.message }}…<span class="st-caret">▍</span>
      </p>
      <p
        v-else-if="station.phase === 'empty' || station.phase === 'error'"
        class="st-note"
        data-testid="station-note"
      >
        {{ station.message }}
      </p>
      <div v-else-if="station.phase === 'ready'" class="md" data-testid="station-md" v-html="rendered"></div>
      <p v-else class="st-note">完成一次梳理后,这里会为你留一份小方案。</p>
    </div>
    <!-- 操作钮钉在面板底部(滚动区外),长稿不折叠 -->
    <footer v-if="station.phase === 'ready'" class="st-actions">
      <button type="button" data-testid="station-export" @click="exportStationReport()">
        导出 .md
      </button>
      <button type="button" data-testid="station-regen" @click="regenerateStation()">
        重新整理
      </button>
    </footer>
  </section>
</template>

<style scoped>
.station {
  position: fixed;
  top: 74px;
  right: 16px;
  z-index: 54;
  width: min(368px, 92vw);
  max-height: calc(100vh - 170px);
  border-radius: 22px;
  padding: 16px 16px 14px;
  display: flex;
  flex-direction: column;
  /* 材质对齐 ui-taste 定稿:重玻璃面板(与 SettingsPanel 同构) */
  background: linear-gradient(150deg, rgba(255, 255, 255, 0.92), rgba(255, 255, 255, 0.82));
  backdrop-filter: blur(28px) saturate(1.6);
  -webkit-backdrop-filter: blur(28px) saturate(1.6);
  border: 1px solid rgba(255, 255, 255, 0.9);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    0 30px 80px -36px rgba(62, 58, 53, 0.45);
  opacity: 0;
  pointer-events: none;
  visibility: hidden;
  transform: scale(0.97) translateY(-6px);
  transform-origin: 85% 0;
  transition:
    opacity 0.2s var(--ease),
    transform 0.2s var(--ease),
    visibility 0.2s;
}
.station.open {
  opacity: 1;
  pointer-events: auto;
  visibility: visible;
  transform: none;
}
.st-h {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 10px;
  flex: none;
}
.st-h::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--moodv);
}
.st-x {
  margin-left: auto;
  border: 0;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  color: var(--muted);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.st-x:hover {
  background: var(--primary);
  color: #fff;
}
.st-body {
  flex: 1;
  overflow-y: auto;
  min-height: 120px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink);
}
.st-body::-webkit-scrollbar {
  width: 6px;
}
.st-body::-webkit-scrollbar-thumb {
  background: rgba(110, 147, 124, 0.3);
  border-radius: 3px;
}
.st-wait {
  color: var(--muted);
  animation: pulse 1.6s infinite;
}
.st-caret {
  color: var(--primary-deep);
}
.st-note {
  color: var(--muted);
  padding: 8px 2px;
}
.md :deep(h1) {
  font-family: var(--serif);
  font-size: 16px;
  margin: 2px 0 8px;
}
.md :deep(h2) {
  font-size: 13px;
  margin: 12px 0 6px;
  color: var(--primary-deep);
}
.md :deep(h3) {
  font-size: 12.5px;
  margin: 10px 0 4px;
}
.md :deep(p) {
  margin: 4px 0;
}
.md :deep(ul),
.md :deep(ol) {
  margin: 4px 0;
  padding-left: 18px;
}
.md :deep(li) {
  margin: 3px 0;
}
.md :deep(blockquote) {
  margin: 8px 0 2px;
  padding: 6px 10px;
  border-left: 3px solid var(--moodv);
  background: rgba(200, 162, 200, 0.09);
  border-radius: 0 8px 8px 0;
  color: var(--muted);
  font-size: 11.5px;
}
.md :deep(strong) {
  color: var(--ink);
}
.st-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex: none;
}
.st-actions button {
  position: relative;
  border: 0;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 9px 18px;
  border-radius: 999px;
  cursor: pointer;
  /* 主钮=tinted 绿玻璃(ui-taste 定稿);次钮=白玻璃 */
  background: rgba(255, 255, 255, 0.65);
  color: var(--ink);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.9);
  transition:
    transform 0.1s ease-out,
    background 0.2s;
}
.st-actions button:first-child {
  background: linear-gradient(180deg, rgba(163, 177, 138, 0.3), rgba(110, 147, 124, 0.16));
  color: #3d5a49;
  box-shadow:
    inset 0 0 0 1px rgba(163, 177, 138, 0.55),
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 6px 16px -10px rgba(94, 127, 106, 0.5);
}
.st-actions button:hover {
  transform: translateY(-1px);
}
.st-actions button:active {
  transform: scale(0.96);
}
</style>
