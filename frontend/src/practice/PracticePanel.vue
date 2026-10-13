<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Pause, Play, RotateCcw, X } from 'lucide-vue-next'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const running = ref(false)
const elapsed = ref(0)
const mode = ref<'calm' | 'box' | '478'>('calm')
let timer: ReturnType<typeof setInterval> | null = null

const modeText = computed(() => ({ calm: '舒缓 4·6', box: '方形 4·4', '478': '4·7·8' })[mode.value])
const modeGuide = computed(() => ({ calm: '吸气 4 秒 · 呼气 6 秒', box: '吸气 4 秒 · 屏息 4 秒 · 呼气 4 秒 · 停顿 4 秒', '478': '吸气 4 秒 · 屏息 7 秒 · 呼气 8 秒' })[mode.value])
const cycle = computed(() => mode.value === 'calm' ? 10 : mode.value === 'box' ? 16 : 19)
const phase = computed(() => {
  const offset = elapsed.value % cycle.value
  if (offset < 4) return 'inhale'
  if (mode.value === 'box' && offset < 8) return 'hold'
  if (mode.value === '478' && offset < 11) return 'hold'
  if (mode.value === 'box' && offset >= 12) return 'rest'
  return 'exhale'
})
const phaseLabel = computed(() => ({ inhale: '吸气', hold: '屏息', exhale: '呼气', rest: '停顿' })[phase.value])
const phaseStart = computed(() => {
  if (phase.value === 'inhale') return 0
  if (mode.value === 'calm') return 4
  if (phase.value === 'hold') return 4
  if (phase.value === 'exhale') return mode.value === '478' ? 11 : mode.value === 'box' ? 8 : 4
  return 12
})
const phaseDuration = computed(() => {
  if (mode.value === 'calm') return phase.value === 'inhale' ? 4 : 6
  if (mode.value === 'box') return 4
  return phase.value === 'inhale' ? 4 : phase.value === 'hold' ? 7 : 8
})
const phaseCountdownLabel = computed(() => {
  const offset = elapsed.value % cycle.value
  const remaining = Math.max(1, phaseDuration.value - (offset - phaseStart.value))
  return `${remaining.toString().padStart(2, '0')}s`
})
const phaseStyle = computed<Record<string, string>>(() => ({
  '--phase-duration': `${phaseDuration.value}s`,
  transitionDuration: `${phaseDuration.value}s`,
}))

function toggle(): void {
  running.value = !running.value
  if (running.value) {
    timer = setInterval(() => { elapsed.value += 1 }, 1000)
  } else if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function reset(): void {
  running.value = false
  elapsed.value = 0
  if (timer !== null) clearInterval(timer)
  timer = null
}

watch(() => props.open, (open) => { if (!open && running.value) toggle() })
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer)
})
</script>

<template>
  <section class="practice-overlay" :class="{ open }" aria-label="心灵练习">
    <article class="practice-panel">
      <button class="panel-close" type="button" title="关闭练习" aria-label="关闭练习" @click="emit('close')"><X :size="17" /></button>
      <div class="practice-grid">
        <div class="practice-copy"><span class="eyebrow">心灵练习 · 01</span><h2>温柔呼吸</h2><p>跟着光环慢慢打开，再慢慢收回。小栖会在旁边陪你，不催你抵达任何地方。</p><div class="mode-list"><button v-for="item in (['calm','box','478'] as const)" :key="item" type="button" :class="{ selected: mode === item }" @click="mode = item">{{ ({ calm:'舒缓 4·6', box:'方形 4·4', '478':'4·7·8' } as Record<string,string>)[item] }}</button></div><span class="mode-guide">{{ modeGuide }}</span><span class="practice-tip">时长不限 · 随时可以暂停</span></div>
        <div class="breath-stage"><div class="breath-ring" :class="{ inhale: running && phase === 'inhale', hold: running && phase === 'hold', exhale: running && phase === 'exhale', rest: running && phase === 'rest' }" :style="phaseStyle"><div><b>{{ running ? phaseLabel : '准备好了吗' }}</b><span>{{ running ? '当前阶段倒计时' : modeText }}</span><strong>{{ phaseCountdownLabel }}</strong></div></div><div class="breath-meta">{{ running ? `${modeText} · 跟着光环呼吸` : elapsed > 0 ? '已暂停 · 随时可以继续' : '中央呼吸环会告诉你节奏' }}</div></div>
      </div>
      <div class="practice-actions"><button class="secondary-action" type="button" @click="reset"><RotateCcw :size="15" />重置</button><button class="primary-action" type="button" @click="toggle"> <Pause v-if="running" :size="15" /><Play v-else :size="15" />{{ running ? '暂停练习' : '开始练习' }}</button></div>
    </article>
  </section>
</template>

<style scoped>
.practice-overlay{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:24px;background:rgba(56,70,60,.12);backdrop-filter:blur(8px);opacity:0;pointer-events:none;visibility:hidden;transition:.2s ease}.practice-overlay.open{opacity:1;pointer-events:auto;visibility:visible}.practice-panel{position:relative;width:min(920px,calc(100vw - 40px));padding:28px;border:1px solid rgba(255,255,255,.92);border-radius:28px;background:rgba(249,252,248,.94);box-shadow:0 30px 90px rgba(44,63,49,.24)}.panel-close{position:absolute;right:18px;top:18px;display:grid;place-items:center;width:32px;height:32px;border:0;border-radius:50%;background:rgba(255,255,255,.76);color:#6f7d73;cursor:pointer}.practice-grid{display:grid;grid-template-columns:1.05fr 1fr .7fr;gap:24px;align-items:center}.eyebrow{color:#77947e;font-size:10px;letter-spacing:.1em}.practice-copy h2{margin:8px 0;color:#2f4035;font:700 28px Georgia,serif}.practice-copy p{max-width:290px;margin:0;color:#728078;font-size:13px;line-height:1.8}.mode-list{display:flex;flex-wrap:wrap;gap:7px;margin:20px 0 14px}.mode-list button{border:1px solid rgba(118,150,126,.2);border-radius:999px;padding:8px 11px;background:rgba(255,255,255,.68);color:#708078;font-size:11px;cursor:pointer}.mode-list button.selected{border-color:#a9c5ad;background:#e5f0e6;color:#4e765a}.practice-tip{color:#a0aaa3;font-size:10px}.breath-stage{text-align:center}.breath-ring{width:min(250px,42vw);aspect-ratio:1;margin:auto;display:grid;place-items:center;border-radius:50%;background:radial-gradient(circle,#fff 0 34%,#e7f2e7 35% 52%,rgba(161,196,166,.5) 53% 55%,rgba(215,234,218,.46) 56% 70%,transparent 71%);transition:transform 4s ease-in-out}.breath-ring.breathe{animation:breathe 10s ease-in-out infinite}.breath-ring>div{display:flex;flex-direction:column;gap:8px}.breath-ring b{color:#58755f;font:700 18px Georgia,serif}.breath-ring span{color:#8a998e;font-size:11px}.breath-meta{margin-top:14px;color:#85938a;font-size:11px}.practice-companion{display:flex;flex-direction:column;align-items:center;gap:12px;color:#839087;text-align:center;font-size:11px;line-height:1.6}.companion-orb{width:112px;height:170px;border-radius:50% 50% 44% 44%;background:linear-gradient(160deg,#e9d5bb,#f5e9d4 52%,#a0b69e);box-shadow:0 20px 30px rgba(83,105,87,.18);animation:float 4s ease-in-out infinite}.practice-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:22px}.primary-action,.secondary-action{display:inline-flex;align-items:center;gap:7px;border:0;border-radius:999px;padding:10px 15px;font-size:12px;cursor:pointer}.primary-action{background:#dcecdf;color:#4d7459}.secondary-action{background:#f0f4ef;color:#68766c}@keyframes breathe{0%,100%{transform:scale(.88)}40%,60%{transform:scale(1.08)}}@keyframes float{50%{transform:translateY(-7px)}}@media(max-width:720px){.practice-grid{grid-template-columns:1fr}.practice-copy p{max-width:none}.practice-companion{display:flex;width:100%;height:200px;min-height:200px}.companion-canvas{height:190px}.breath-ring{width:min(250px,62vw)}}
 .practice-grid{display:grid;grid-template-columns:1.05fr 1fr;gap:24px;align-items:center}.breath-ring{position:relative;isolation:isolate;transform:scale(.88);transition-property:transform}.breath-ring::before{content:"";position:absolute;inset:-18px;border-radius:50%;background:radial-gradient(circle,rgba(191,224,195,.68) 0%,rgba(191,224,195,.28) 44%,rgba(191,224,195,0) 72%);filter:blur(5px);opacity:.35;transform:scale(.84);transition:transform var(--phase-duration, 1s) ease-in-out,opacity var(--phase-duration, 1s) ease-in-out;z-index:-1;pointer-events:none}.breath-ring::after{content:"";position:absolute;inset:-8px;border-radius:50%;box-shadow:0 0 28px rgba(141,187,148,.35);opacity:.42;transform:scale(.92);transition:transform var(--phase-duration, 1s) ease-in-out,opacity var(--phase-duration, 1s) ease-in-out;z-index:-1;pointer-events:none}.breath-ring.inhale::before,.breath-ring.hold::before{transform:scale(1.12);opacity:.82}.breath-ring.inhale::after,.breath-ring.hold::after{transform:scale(1.08);opacity:.72}.breath-ring.exhale::before,.breath-ring.rest::before{transform:scale(.84);opacity:.22}.breath-ring.exhale::after,.breath-ring.rest::after{transform:scale(.92);opacity:.35}.breath-ring>div{position:relative;z-index:1}.mode-guide{display:block;margin:0 0 7px;color:#6f8375;font-size:10px;line-height:1.5}.breath-ring strong{color:#718b77;font:600 15px/1.1 ui-monospace,monospace;letter-spacing:.06em}.breath-meta{margin-top:14px;color:#85938a;font-size:11px}.practice-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:22px}.primary-action,.secondary-action{display:inline-flex;align-items:center;gap:7px;border:0;border-radius:999px;padding:10px 15px;font-size:12px;cursor:pointer}.primary-action{background:#dcecdf;color:#4d7459}.secondary-action{background:#f0f4ef;color:#68766c}@media(max-width:720px){.practice-grid{grid-template-columns:1fr}.practice-copy p{max-width:none}.breath-ring{width:min(250px,62vw)}}
.breath-ring::before{background:radial-gradient(circle,rgba(55,122,74,.72) 0%,rgba(55,122,74,.38) 44%,rgba(55,122,74,0) 74%);filter:blur(4px)}.breath-ring::after{box-shadow:0 0 34px rgba(39,104,58,.58)}.breath-ring.inhale::before,.breath-ring.hold::before{transform:scale(1.2);opacity:.95}.breath-ring.inhale::after,.breath-ring.hold::after{transform:scale(1.14);opacity:.9}.breath-ring.exhale::before,.breath-ring.rest::before{transform:scale(.74);opacity:.28}.breath-ring.exhale::after,.breath-ring.rest::after{transform:scale(.82);opacity:.42}
</style>
