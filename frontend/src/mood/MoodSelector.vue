<script setup lang="ts">
// 心情表情组浮层(工具栏「今日心情」点开):六档表情;置灰由控制器 disabled 驱动
// (冷却中/回合内),选中回调交给 App 持有的 MoodSelector 控制器(send mood_select)。
import { MOODS } from './selector'

defineProps<{ disabled: boolean }>()

const emit = defineEmits<{ select: [mood: (typeof MOODS)[number]['key']] }>()
</script>

<template>
  <div class="mood-overlay glass" data-testid="mood-overlay">
    <div class="mo-t">今天此刻的心情?</div>
    <div class="mo-faces">
      <button
        v-for="m in MOODS"
        :key="m.key"
        class="mf"
        :data-c="m.color"
        :style="{ color: m.color }"
        :disabled="disabled"
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
.mf:hover:not(:disabled) {
  opacity: 1;
  transform: translateY(-3px);
  background: #fff;
  box-shadow: 0 6px 16px -8px rgba(62, 58, 53, 0.35);
}
.mf:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
</style>
