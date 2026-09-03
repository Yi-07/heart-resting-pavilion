<script setup lang="ts">
// 心情选择器浮层(右上,非阻塞):六档表情 + conic 计时环;可见性/进度由 round store 驱动,
// 选中回调交给 App 持有的 MoodSelector 控制器(send mood_select + 手点写情绪)。
import { useRoundStore } from '../state/round'
import { MOODS } from './selector'

const round = useRoundStore()

const emit = defineEmits<{ select: [mood: (typeof MOODS)[number]['key']] }>()
</script>

<template>
  <div v-if="round.moodVisible" class="mood-overlay glass" data-testid="mood-overlay">
    <div class="mo-t">今天此刻的心情?</div>
    <div class="mo-faces">
      <button
        v-for="m in MOODS"
        :key="m.key"
        class="mf"
        :data-c="m.color"
        :style="{ color: m.color }"
        @click="emit('select', m.key)"
      >
        <svg viewBox="0 0 24 24">
          <circle cx="9" cy="9.5" r="1" fill="currentColor" />
          <circle cx="15" cy="9.5" r="1" fill="currentColor" />
          <path :d="m.mouth" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" />
        </svg>
        <b>{{ m.key }}</b>
      </button>
    </div>
    <div class="mo-timer">
      <span class="mo-ring" :style="{ '--p': `${(1 - round.moodElapsed) * 100}%` }"></span>
      <span>10s 不选会自动收起,回到工具栏主动选择</span>
    </div>
  </div>
</template>

<style scoped>
.mood-overlay {
  position: absolute;
  top: 10px;
  right: 8px;
  z-index: 60;
  width: 376px;
  border-radius: 18px;
  padding: 14px 16px;
  animation: fadeup 0.35s var(--ease);
}
.mo-t {
  font-size: 12.5px;
  font-weight: 600;
  margin-bottom: 9px;
  display: flex;
  align-items: center;
  gap: 7px;
}
.mo-t::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--moodv);
  animation: pulse 1.6s infinite;
}
.mo-faces {
  display: flex;
  justify-content: space-between;
  gap: 2px;
  padding: 2px 0;
}
.mf {
  width: 54px;
  border: 0;
  background: rgba(255, 255, 255, 0.65);
  border-radius: 12px;
  cursor: pointer;
  opacity: 0.62;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 6px 0 5px;
}
.mf svg {
  width: 26px;
  height: 26px;
}
.mf b {
  font-size: 10px;
  font-weight: 500;
  color: var(--ink);
}
.mf:hover {
  opacity: 1;
  transform: translateY(-3px);
  background: #fff;
  box-shadow: 0 6px 16px -8px rgba(62, 58, 53, 0.35);
}
.mo-timer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--muted);
}
.mo-ring {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: conic-gradient(var(--primary) var(--p, 100%), rgba(110, 147, 124, 0.18) 0);
  -webkit-mask: radial-gradient(circle, #000 55%, transparent 57%);
  mask: radial-gradient(circle, #000 55%, transparent 57%);
}
</style>
