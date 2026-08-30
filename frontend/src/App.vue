<script setup lang="ts">
// 步骤2 联动调试视图:验证 WS 链路(发送/帧流/危机横幅)。
// 正式 UI(黑板/Live2D/聊天抽屉)随后续步骤按 preview/l1-ui-mockup-v7 落地。
import { onMounted, reactive, ref } from 'vue'
import { logger } from './logger'
import { WSClient } from './ws/client'
import type { S2CMsg } from './ws/messages'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'

const client = new WSClient(WS_URL)
const status = ref<'connecting' | 'open' | 'closed'>('connecting')
const draft = ref('')
const reply = ref('')
const crisis = ref(false)
const frames = reactive<{ kind: string; brief: string }[]>([])

function brief(msg: S2CMsg): string {
  switch (msg.type) {
    case 'first_frame':
      return `route=${msg.route} template=${msg.template ?? '-'} mood_select=${msg.mood_select}`
    case 'draw':
      return `seq=${msg.seq} template=${msg.template}`
    case 'text_delta':
      return `seq=${msg.seq} final=${msg.final}`
    case 'audio_chunk':
      return `seq=${msg.seq} format=${msg.format}`
    case 'done':
      return `seq=${msg.seq}`
    case 'error':
      return `code=${msg.code} ${msg.message}`
  }
}

function track<T extends S2CMsg['type']>(
  type: T,
  fn: (msg: Extract<S2CMsg, { type: T }>) => void,
): void {
  client.on(type, (msg) => {
    // T ⊆ S2C 类型集,on 按 type 分发,此处收窄是安全的
    const frame = msg as Extract<S2CMsg, { type: T }>
    frames.push({ kind: frame.type, brief: brief(frame) })
    if (frames.length > 50) frames.shift()
    fn(frame)
  })
}

onMounted(() => {
  track('first_frame', (m) => {
    crisis.value = m.route === 'crisis'
    reply.value = m.text
  })
  track('draw', () => {})
  track('text_delta', (m) => {
    reply.value += m.text
  })
  track('done', () => {})
  track('error', (m) => {
    reply.value += `\n[错误] ${m.code}:${m.message}`
  })

  client
    .connect()
    .then(() => {
      status.value = 'open'
    })
    .catch((err: unknown) => {
      status.value = 'closed'
      logger.error('app', `连接失败: ${String(err)}`)
    })
})

function submit(): void {
  const text = draft.value.trim()
  if (text === '') return
  client.send({ type: 'user_input', mode: 'text', text, audio: null, ts: Math.floor(Date.now() / 1000) })
  draft.value = ''
  reply.value = ''
}
</script>

<template>
  <div class="debug-shell">
    <header class="bar">
      <span class="title">心栖阁 · 步骤2 调试视图</span>
      <span class="status" :data-status="status">{{ status }}</span>
    </header>

    <div v-if="crisis" class="crisis-banner" data-testid="crisis-banner">
      如果你现在有伤害自己的念头,请立刻拨打全国心理援助热线 <strong>12356</strong>(24 小时)。
    </div>

    <section class="reply">{{ reply || '(等待输入…)' }}</section>

    <form class="input-row" @submit.prevent="submit">
      <input
        v-model="draft"
        :disabled="status !== 'open'"
        placeholder="说点什么…(试试:我不想活了 / 最近很焦虑睡不着)"
        data-testid="chat-input"
      />
      <button type="submit" :disabled="status !== 'open' || draft.trim() === ''">发送</button>
    </form>

    <ul class="frames" data-testid="frame-log">
      <li v-for="(f, i) in frames" :key="i"><span class="kind">{{ f.kind }}</span> {{ f.brief }}</li>
    </ul>
  </div>
</template>

<style scoped>
.debug-shell {
  max-width: 640px;
  margin: 2rem auto;
  padding: 1rem;
  font-family: system-ui, sans-serif;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.status[data-status='open'] {
  color: #16a34a;
}
.status[data-status='connecting'] {
  color: #ca8a04;
}
.status[data-status='closed'] {
  color: #dc2626;
}
.crisis-banner {
  background: #fef2f2;
  border: 1px solid #dc2626;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  color: #991b1b;
}
.reply {
  min-height: 4rem;
  white-space: pre-wrap;
  background: #f8fafc;
  border-radius: 8px;
  padding: 0.75rem 1rem;
}
.input-row {
  display: flex;
  gap: 0.5rem;
}
.input-row input {
  flex: 1;
  padding: 0.5rem 0.75rem;
}
.frames {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 0.8rem;
  color: #475569;
  max-height: 12rem;
  overflow-y: auto;
}
.frames .kind {
  display: inline-block;
  min-width: 5.5rem;
  color: #0369a1;
}
</style>
