<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { Pause, Play, RotateCcw, X } from 'lucide-vue-next'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; phase: [value: 'inhale' | 'exhale' | 'idle'] }>()
const running = ref(false)
const elapsed = ref(0)
const mode = ref<'calm' | 'box' | '478'>('calm')
let timer: ReturnType<typeof setInterval> | null = null

const modeText = computed(() => ({ calm: '舒缓 4·6', box: '方形 4·4', '478': '4·7·8' })[mode.value])
const cycle = computed(() => mode.value === 'calm' ? 10 : mode.value === 'box' ? 16 : 19)
const phase = computed(() => {
  const offset = elapsed.value % cycle.value
  return offset < (mode.value === '478' ? 4 : 4) ? 'inhale' : 'exhale'
})
const phaseLabel = computed(() => phase.value === 'inhale' ? '吸气' : '呼气')

function syncPhase(): void {
  emit('phase', running.value ? phase.value : 'idle')
}

function toggle(): void {
  running.value = !running.value
  if (running.value) {
    elapsed.value = 0
    timer = setInterval(() => { elapsed.value += 1; syncPhase() }, 1000)
  } else if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
  syncPhase()
}

function reset(): void {
  running.value = false
  elapsed.value = 0
  if (timer !== null) clearInterval(timer)
  timer = null
  syncPhase()
}

onBeforeUnmount(() => { if (timer !== null) clearInterval(timer) })
</script>

<template>
  <section class="practice-overlay" :class="{ open }" aria-label="心灵练习">
    <article class="practice-panel">
      <button class="panel-close" type="button" title="关闭练习" aria-label="关闭练习" @click="emit('close')"><X :size="17" /></button>
      <div class="practice-grid">
        <div class="practice-copy"><span class="eyebrow">心灵练习 · 01</span><h2>温柔呼吸</h2><p>跟着光环慢慢打开，再慢慢收回。小栖会在旁边陪你，不催你抵达任何地方。</p><div class="mode-list"><button v-for="item in (['calm','box','478'] as const)" :key="item" type="button" :class="{ selected: mode === item }" @click="mode = item">{{ ({ calm:'舒缓 4·6', box:'方形 4·4', '478':'4·7·8' } as Record<string,string>)[item] }}</button></div><span class="practice-tip">时长不限 · 随时可以暂停</span></div>
        <div class="breath-stage"><div class="breath-ring" :class="{ breathe: running, inhale: phase === 'inhale' }"><div><b>{{ running ? phaseLabel : '准备好了吗' }}</b><span>{{ running ? '跟着光环慢慢呼吸' : modeText }}</span></div></div><div class="breath-meta">{{ running ? `第 ${Math.floor(elapsed / 60) + 1} 分钟 · 练习中` : '中央呼吸环会告诉你节奏' }}</div></div>
        <div class="practice-companion"><div class="companion-orb"></div><span>Live2D 会跟着节奏轻轻起伏</span></div>
      </div>
      <div class="practice-actions"><button class="secondary-action" type="button" @click="reset"><RotateCcw :size="15" />重置</button><button class="primary-action" type="button" @click="toggle"> <Pause v-if="running" :size="15" /><Play v-else :size="15" />{{ running ? '暂停练习' : '开始练习' }}</button></div>
    </article>
  </section>
</template>

<style scoped>
.practice-overlay{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:24px;background:rgba(56,70,60,.12);backdrop-filter:blur(8px);opacity:0;pointer-events:none;visibility:hidden;transition:.2s ease}.practice-overlay.open{opacity:1;pointer-events:auto;visibility:visible}.practice-panel{position:relative;width:min(920px,calc(100vw - 40px));padding:28px;border:1px solid rgba(255,255,255,.92);border-radius:28px;background:rgba(249,252,248,.94);box-shadow:0 30px 90px rgba(44,63,49,.24)}.panel-close{position:absolute;right:18px;top:18px;display:grid;place-items:center;width:32px;height:32px;border:0;border-radius:50%;background:rgba(255,255,255,.76);color:#6f7d73;cursor:pointer}.practice-grid{display:grid;grid-template-columns:1.05fr 1fr .7fr;gap:24px;align-items:center}.eyebrow{color:#77947e;font-size:10px;letter-spacing:.1em}.practice-copy h2{margin:8px 0;color:#2f4035;font:700 28px Georgia,serif}.practice-copy p{max-width:290px;margin:0;color:#728078;font-size:13px;line-height:1.8}.mode-list{display:flex;flex-wrap:wrap;gap:7px;margin:20px 0 14px}.mode-list button{border:1px solid rgba(118,150,126,.2);border-radius:999px;padding:8px 11px;background:rgba(255,255,255,.68);color:#708078;font-size:11px;cursor:pointer}.mode-list button.selected{border-color:#a9c5ad;background:#e5f0e6;color:#4e765a}.practice-tip{color:#a0aaa3;font-size:10px}.breath-stage{text-align:center}.breath-ring{width:min(250px,42vw);aspect-ratio:1;margin:auto;display:grid;place-items:center;border-radius:50%;background:radial-gradient(circle,#fff 0 34%,#e7f2e7 35% 52%,rgba(161,196,166,.5) 53% 55%,rgba(215,234,218,.46) 56% 70%,transparent 71%);transition:transform 4s ease-in-out}.breath-ring.breathe{animation:breathe 10s ease-in-out infinite}.breath-ring>div{display:flex;flex-direction:column;gap:8px}.breath-ring b{color:#58755f;font:700 18px Georgia,serif}.breath-ring span{color:#8a998e;font-size:11px}.breath-meta{margin-top:14px;color:#85938a;font-size:11px}.practice-companion{display:flex;flex-direction:column;align-items:center;gap:12px;color:#839087;text-align:center;font-size:11px;line-height:1.6}.companion-orb{width:112px;height:170px;border-radius:50% 50% 44% 44%;background:linear-gradient(160deg,#e9d5bb,#f5e9d4 52%,#a0b69e);box-shadow:0 20px 30px rgba(83,105,87,.18);animation:float 4s ease-in-out infinite}.practice-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:22px}.primary-action,.secondary-action{display:inline-flex;align-items:center;gap:7px;border:0;border-radius:999px;padding:10px 15px;font-size:12px;cursor:pointer}.primary-action{background:#dcecdf;color:#4d7459}.secondary-action{background:#f0f4ef;color:#68766c}@keyframes breathe{0%,100%{transform:scale(.88)}40%,60%{transform:scale(1.08)}}@keyframes float{50%{transform:translateY(-7px)}}@media(max-width:720px){.practice-grid{grid-template-columns:1fr}.practice-copy p{max-width:none}.practice-companion{display:none}.breath-ring{width:min(250px,62vw)}}
</style>
