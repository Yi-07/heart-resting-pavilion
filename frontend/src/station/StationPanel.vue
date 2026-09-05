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
  border-radius: 18px;
  padding: 14px 14px 12px;
  display: flex;
  flex-direction: column;
  opacity: 0;
  pointer-events: none;
  visibility: hidden;
  transform: translateY(-8px);
  transition: all 0.3s var(--ease);
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
  border: 0;
  font-size: 11.5px;
  padding: 7px 14px;
  border-radius: 999px;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.7);
  color: var(--ink);
  transition: all 0.22s;
  font-family: var(--sans);
}
.st-actions button:first-child {
  background: var(--primary);
  color: #fff;
}
.st-actions button:hover {
  transform: translateY(-1px);
}
</style>
