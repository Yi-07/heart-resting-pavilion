<script setup lang="ts">
// 报告列表(场景 B:设置栏入口)。只列有效期内的报告(后端已过滤)，
// 行内带轮次/生成时间/状态徽标/可否重新生成(三态:未知≠可用)。
import { openStationRow, station, type ReportRow } from './station'

function shortTime(iso: string): string {
  // "2026-10-12T16:40:00" → "10-12 16:40"
  const m = /^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso)
  return m !== null && m[1] !== undefined && m[2] !== undefined ? `${m[1]} ${m[2]}` : iso
}

function badgeClass(r: ReportRow): string {
  if (r.status === 'pending') return 'run'
  if (r.can_regenerate === 'no') return 'old'
  if (r.can_regenerate === 'unknown') return 'unk'
  return 'ok'
}

function badgeText(r: ReportRow): string {
  if (r.status === 'pending') return '⏳ 生成中'
  if (r.can_regenerate === 'no') return '⌛ 素材已过期 · 仅可查看'
  if (r.can_regenerate === 'unknown') return '? 暂时无法确认素材'
  return '✓ 可查看'
}

function subText(r: ReportRow): string {
  if (r.status === 'pending') return '正在为你整理'
  if (r.can_regenerate === 'no') return '重新聊聊可以生成新的方案'
  if (r.can_regenerate === 'unknown') return '能否重新整理暂不确定'
  return '点开看看当时为你整理的小方案'
}
</script>

<template>
  <div class="r-list" data-testid="station-list">
    <p v-if="station.phase === 'loading'" class="st-wait" data-testid="station-loading">
      正在打开<span class="st-caret">▍</span>
    </p>
    <p v-else-if="station.phase === 'error'" class="st-note" data-testid="station-note">
      {{ station.message }}
    </p>
    <template v-else>
      <p class="st-sub">选择一次梳理,看看当时为你整理的小方案</p>
      <p v-if="station.rows.length === 0" class="st-note" data-testid="station-empty">
        完成一次梳理后,这里会为你留一份小方案。
      </p>
      <button
        v-for="r in station.rows"
        :key="r.round_id"
        class="r-row"
        type="button"
        data-testid="station-row"
        @click="openStationRow(r)"
      >
        <span class="r-l1">
          <span class="r-t">{{ r.title }}</span>
          <span class="r-time">{{ shortTime(r.created_at) }}</span>
        </span>
        <span class="r-l2">
          <span class="r-s">{{ subText(r) }}</span>
          <span class="bd" :class="badgeClass(r)">{{ badgeText(r) }}</span>
        </span>
      </button>
    </template>
  </div>
</template>

<style scoped>
.r-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.st-sub {
  font-size: 11px;
  color: var(--muted);
  margin: -4px 0 2px;
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
.r-row {
  display: block;
  width: 100%;
  text-align: left;
  cursor: pointer;
  font-family: var(--sans);
  background: #fffdf8;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 10px 12px;
  animation: fadeup 0.35s var(--ease);
  transition:
    transform 0.12s var(--ease),
    box-shadow 0.2s;
}
.r-row:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 24px -16px rgba(62, 58, 53, 0.4);
}
.r-l1 {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.r-t {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}
.r-time {
  margin-left: auto;
  font-size: 10px;
  color: var(--muted);
  flex: none;
}
.r-l2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 3px;
}
.r-s {
  font-size: 11px;
  color: var(--muted);
}
.bd {
  flex: none;
  margin-left: auto;
  font-size: 10px;
  border-radius: 999px;
  padding: 2px 9px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.bd.ok {
  color: var(--primary-deep);
  background: rgba(139, 174, 151, 0.13);
}
.bd.run {
  color: var(--accent);
  background: rgba(213, 138, 99, 0.12);
}
.bd.old {
  color: var(--muted);
  background: rgba(110, 103, 94, 0.1);
}
.bd.unk {
  color: var(--muted);
  border: 1px dashed rgba(110, 103, 94, 0.42);
}

@keyframes fadeup {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
