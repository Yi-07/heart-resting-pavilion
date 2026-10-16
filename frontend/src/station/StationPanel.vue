<script setup lang="ts">
// 心灵补给站面板(frontend-plan §2 station 行):外层浮层 + 报告详情(复用原有详情布局
// 与 md 渲染)；列表视图挂 ReportList.vue(场景 B)。等待态「正在为你整理…▍」/
// md 预览(renderMarkdown,子集受控+先转义)/导出 .md/重新整理(只针对当前轮)。
// 重新生成期间保留旧稿可读可导出，失败回退旧稿；不显示别轮报告。
import { computed } from 'vue'
import {
  backToList,
  closeStation,
  exportStationReport,
  regenerateStation,
  station,
} from './station'
import { renderMarkdown } from './markdown'
import ReportList from './ReportList.vue'

const rendered = computed(() =>
  station.reportMd === '' ? '' : renderMarkdown(station.reportMd),
)

/** 首次生成中(无旧稿可显) */
const firstGenWaiting = computed(
  () => station.phase === 'loading' || (station.phase === 'pending' && station.reportMd === ''),
)
/** 保留旧稿:ready / 重新生成中 / 失败回退 */
const showMd = computed(
  () => station.reportMd !== '' && station.phase !== 'loading' && station.phase !== 'pending'
    ? true
    : station.reportMd !== '' && station.phase === 'pending' && station.regenerating,
)
const showNote = computed(
  () => !firstGenWaiting.value && !showMd.value && (station.phase === 'empty' || station.phase === 'error'),
)
/** 重生成失败但旧稿仍在:旧稿照常展示,另给一条失败说明 */
const errorWithOld = computed(
  () => station.phase === 'error' && showMd.value && !station.regenerating,
)
const actionsVisible = computed(
  () => station.view === 'detail' && (showMd.value || station.phase === 'ready'),
)
const metaText = computed(() => {
  const label = station.currentTitle
  const m = station.currentMeta
  const stamp = (iso?: string | null): string | null => {
    if (!iso) return null
    const s = iso.slice(5, 16).replace('T', ' ')
    return s.length >= 11 ? s : null
  }
  const created = stamp(m?.created_at)
  const updated = stamp(m?.updated_at)
  const exp = stamp(m?.expires_at)
  const parts: string[] = []
  if (label !== '') parts.push(label)
  if (created !== null) parts.push(`${created} 生成`)
  // 重新生成过才显示「更新于」——否则用户会以为没生效
  if (updated !== null && updated !== created) parts.push(`${updated} 更新`)
  if (exp !== null) parts.push(`有效期至 ${exp}`)
  return parts.join(' · ')
})
</script>

<template>
  <section class="station glass" :class="{ open: station.open }" data-testid="station-panel">
    <header class="st-h">
      心灵补给站
      <button
        v-if="station.view === 'detail'"
        class="back"
        type="button"
        title="返回报告列表"
        data-testid="station-back"
        @click="backToList()"
      >‹ 列表</button>
      <button class="st-x" title="收起" data-testid="station-close" @click="closeStation()">✕</button>
    </header>

    <div class="st-body" data-testid="station-body">
      <template v-if="station.view === 'detail'">
        <p v-if="metaText !== ''" class="st-meta" data-testid="station-meta">{{ metaText }}</p>
        <p v-if="firstGenWaiting" class="st-wait" data-testid="station-wait">
          正在为你整理<span class="st-caret">▍</span>
        </p>
        <div v-if="showMd" class="md" data-testid="station-md" v-html="rendered"></div>
        <p v-if="station.regenerating" class="st-regen" data-testid="station-regen-bar">
          正在重新整理<span class="st-caret">▍</span>
        </p>
        <p v-else-if="showNote" class="st-note" data-testid="station-note">{{ station.message }}</p>
        <p v-else-if="errorWithOld" class="st-note" data-testid="station-note">{{ station.message }}</p>
      </template>
      <ReportList v-else />
    </div>

    <footer v-if="actionsVisible" class="st-actions">
      <button
        type="button"
        :disabled="station.regenerating"
        data-testid="station-regen"
        @click="regenerateStation()"
      >重新生成</button>
      <button type="button" data-testid="station-export" @click="exportStationReport()">导出 Markdown</button>
    </footer>
  </section>
</template>

<style scoped>
.station {
  position: fixed;
  top: 74px;
  right: 16px;
  z-index: 54;
  width: min(560px, 94vw);
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
.st-h .back {
  border: 0;
  background: rgba(255, 255, 255, 0.7);
  color: var(--primary-deep);
  font-size: 11px;
  font-weight: 600;
  font-family: var(--sans);
  border-radius: 999px;
  padding: 4px 10px;
  cursor: pointer;
  transition: background 0.2s;
}
.st-h .back:hover {
  background: rgba(139, 174, 151, 0.18);
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
/* 轮次元信息行(详情顶部):与列表行同一信息密度 */
.st-meta {
  font-size: 11px;
  color: var(--muted);
  margin: -2px 0 9px;
  line-height: 1.7;
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
  line-height: 1.8;
}
/* 重新生成中:旧稿保留，仅底部浮条提示 */
.st-regen {
  flex: none;
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: var(--primary-deep);
  background: rgba(139, 174, 151, 0.12);
  border-radius: 999px;
  padding: 7px 13px;
}
.st-regen .st-caret {
  animation: pulse 1s infinite;
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
  font-family: var(--sans);
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
.st-actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}
</style>
