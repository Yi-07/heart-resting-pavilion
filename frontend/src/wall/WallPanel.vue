<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Eraser, LoaderCircle, MessageCircleHeart, Send, X } from 'lucide-vue-next'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'
const REST_BASE = new URL(WS_URL.replace(/^ws/, 'http')).origin
const sessionKey = 'hrp:wall:session'
const sessionId = localStorage.getItem(sessionKey) ?? (() => {
  const value = `wall_${crypto.randomUUID()}`
  localStorage.setItem(sessionKey, value)
  return value
})()

interface WallMessage {
  id: string
  text: string
  reply: string | null
  status: 'pending' | 'replied' | 'failed'
  unread: boolean
  created_at: string
}

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; unread: [value: boolean] }>()
const messages = ref<WallMessage[]>([])
const draft = ref('')
const busy = ref(false)
const error = ref('')
const confirmClear = ref(false)
const hasUnread = computed(() => messages.value.some((message) => message.unread))

async function load(): Promise<void> {
  try {
    const response = await fetch(`${REST_BASE}/wall?session_id=${encodeURIComponent(sessionId)}`)
    if (!response.ok) throw new Error('load')
    const payload = await response.json() as { messages: WallMessage[]; unread: number }
    messages.value = payload.messages
    if (props.open) {
      await fetch(`${REST_BASE}/wall/read?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST' })
      messages.value = messages.value.map((message) => ({ ...message, unread: false }))
    }
    emit('unread', props.open ? false : payload.unread > 0)
  } catch {
    error.value = '留言暂时取不回来，稍后再试。'
  }
}

async function submit(): Promise<void> {
  const text = draft.value.trim()
  if (!text || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const response = await fetch(`${REST_BASE}/wall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, text }),
    })
    if (!response.ok) throw new Error('save')
    draft.value = ''
    await load()
  } catch {
    error.value = '这句话还没有放好，稍后再试。'
  } finally {
    busy.value = false
  }
}

async function clear(): Promise<void> {
  await fetch(`${REST_BASE}/wall?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  confirmClear.value = false
  messages.value = []
  emit('unread', false)
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

let poll: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  void load()
  poll = setInterval(() => void load(), 30000)
})
watch(() => props.open, (open) => { if (open) void load() })
onUnmounted(() => { if (poll !== null) clearInterval(poll) })
</script>

<template>
  <aside class="wall-panel" :class="{ open }" aria-label="留言墙">
    <div class="panel-head">
      <div class="panel-title"><MessageCircleHeart :size="18" /><div><h2>留言墙</h2><p>把今天的话留给明天的自己</p></div></div>
      <button class="icon-button" type="button" title="关闭留言墙" aria-label="关闭留言墙" @click="emit('close')"><X :size="17" /></button>
    </div>
    <p class="wall-lead">这里像一盏留给自己的小灯。回复准备好后，它会轻轻亮起；留言会陪你七天，再把空间还给新的心事。</p>
    <div v-if="hasUnread" class="wall-notice"><span></span>有新的回信，欢迎回来看看</div>
    <div class="wall-list" aria-live="polite">
      <div v-if="messages.length === 0" class="empty">还没有留言。想说什么，都可以从一句开始。</div>
      <article v-for="message in messages" :key="message.id" class="wall-message">
        <div class="message-meta"><time>{{ formatTime(message.created_at) }}</time><span :class="message.status">{{ message.status === 'replied' ? '已回信' : message.status === 'pending' ? '正在读' : '稍后再试' }}</span></div>
        <p class="message-text">{{ message.text }}</p>
        <div v-if="message.reply" class="message-reply"><b>小栖</b><span>{{ message.reply }}</span></div>
      </article>
    </div>
    <p v-if="error" class="wall-error">{{ error }}</p>
    <form class="wall-compose" @submit.prevent="submit">
      <textarea v-model="draft" :disabled="busy" maxlength="2000" rows="3" placeholder="写下此刻想说的话…" @keydown.enter.exact.prevent="submit" />
      <div class="compose-foot"><span>{{ draft.length }}/2000</span><button class="primary-action" type="submit" :disabled="busy || !draft.trim()"><LoaderCircle v-if="busy" class="spin" :size="15" /><Send v-else :size="15" />写下留言</button></div>
    </form>
    <button class="clear-wall" type="button" @click="confirmClear = true"><Eraser :size="14" />清空留言墙</button>
    <div v-if="confirmClear" class="wall-confirm" role="dialog" aria-modal="true">
      <div class="confirm-card"><h3>让这面墙重新安静一会儿？</h3><p>留言和回信都会从这台设备上移除，不能恢复。</p><div><button type="button" class="secondary-action" @click="confirmClear = false">先不清除</button><button type="button" class="danger-action" @click="clear">清空留言</button></div></div>
    </div>
  </aside>
</template>

<style scoped>
.wall-panel{position:fixed;top:74px;right:16px;z-index:55;width:min(430px,calc(100vw - 32px));max-height:calc(100vh - 96px);display:flex;flex-direction:column;gap:14px;padding:20px;border:1px solid rgba(255,255,255,.9);border-radius:24px;background:rgba(250,252,249,.92);backdrop-filter:blur(28px) saturate(1.45);box-shadow:0 30px 80px -35px rgba(62,74,65,.45);opacity:0;pointer-events:none;visibility:hidden;transform:translateY(-8px) scale(.98);transition:.2s ease}.wall-panel.open{opacity:1;pointer-events:auto;visibility:visible;transform:none}.panel-head{display:flex;justify-content:space-between;align-items:flex-start}.panel-title{display:flex;align-items:center;gap:10px;color:#4f705b}.panel-title h2{margin:0;color:#26352c;font:700 19px/1.1 Georgia,serif}.panel-title p{margin:4px 0 0;color:#7a887f;font-size:11px}.icon-button{display:grid;place-items:center;width:30px;height:30px;border:0;border-radius:50%;background:rgba(255,255,255,.72);color:#738078;cursor:pointer}.wall-lead{margin:0;color:#6c786f;font-size:12px;line-height:1.7}.wall-notice{display:flex;align-items:center;gap:8px;padding:9px 11px;border-radius:12px;background:#edf5ee;color:#5b7d66;font-size:12px}.wall-notice span{width:7px;height:7px;border-radius:50%;background:#e68b6d}.wall-list{min-height:120px;overflow:auto;display:flex;flex-direction:column;gap:9px;padding-right:3px}.empty{padding:28px 12px;text-align:center;color:#99a49c;font-size:12px}.wall-message{padding:12px 13px;border-radius:15px;background:rgba(255,255,255,.72);box-shadow:inset 0 0 0 1px rgba(255,255,255,.9)}.message-meta{display:flex;justify-content:space-between;color:#9aa39d;font-size:10px}.message-meta .replied{color:#6d977b}.message-meta .pending{color:#b28b69}.message-text{margin:8px 0 0;color:#344138;font-size:13px;line-height:1.6}.message-reply{display:flex;gap:7px;margin-top:9px;padding:9px 10px;border-radius:10px;background:#eef5ef;color:#627367;font-size:12px;line-height:1.65}.message-reply b{color:#4f795d;white-space:nowrap}.wall-compose{padding:11px;border-radius:16px;background:rgba(235,243,236,.62)}textarea{width:100%;box-sizing:border-box;resize:vertical;border:0;outline:0;background:transparent;color:#334238;font:13px/1.6 inherit}textarea::placeholder{color:#9aa69d}.compose-foot{display:flex;align-items:center;justify-content:space-between;color:#9aa69d;font-size:10px}.primary-action,.secondary-action,.danger-action{display:inline-flex;align-items:center;gap:6px;border:0;border-radius:999px;padding:9px 13px;font-size:12px;cursor:pointer}.primary-action{background:#dcecdf;color:#47705a}.primary-action:disabled{opacity:.45;cursor:not-allowed}.clear-wall{align-self:flex-start;display:inline-flex;align-items:center;gap:6px;border:0;background:transparent;color:#9b7565;font-size:11px;cursor:pointer}.wall-error{margin:0;color:#ad664f;font-size:11px}.wall-confirm{position:absolute;inset:0;display:grid;place-items:center;padding:20px;border-radius:24px;background:rgba(250,247,240,.72);backdrop-filter:blur(12px)}.confirm-card{width:100%;padding:20px;border-radius:18px;background:rgba(255,255,255,.92);text-align:center;box-shadow:0 20px 50px rgba(75,67,58,.16)}.confirm-card h3{margin:0;color:#334238;font:700 16px Georgia,serif}.confirm-card p{margin:9px 0 16px;color:#7c867f;font-size:12px;line-height:1.6}.confirm-card>div{display:flex;justify-content:center;gap:9px}.secondary-action{background:#f2f5f1;color:#647168}.danger-action{background:#f6e2da;color:#9b5944}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
</style>
