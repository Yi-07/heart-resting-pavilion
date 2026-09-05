<script setup lang="ts">
// v7 舞台布局 + WS 帧接线(frontend-plan §5.3):
//   first_frame:淡出音频+清黑板+开新 bot 消息+心情选择器浮出/收起
//   draw:黑板增量渲染;text_delta:气泡/抽屉流式;audio_chunk:入队;done/error:收口回 idle
// 工具栏 route-tabs 为被动指示(路由只在后端判定);Live2D/语音留位(步骤 7/8)。
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { logger } from './logger'
import { WSClient } from './ws/client'
import type { S2CMsg } from './ws/messages'
import { useRoundStore } from './state/round'
import { chat } from './chat/messages'
import { AudioQueue } from './audio/queue'
import { MoodSelector } from './mood/selector'
import { avatarSvg, expressionFor } from './l2d/placeholder'
import { createLive2D, type Live2DController } from './l2d/live2d'
import {
  loadCatalog,
  loadSelection,
  modelUrls,
  nextModel,
  persistSelection,
  type ModelEntry,
} from './l2d/models'
import BoardCanvas from './board/BoardCanvas.vue'
import ChatPanel from './chat/ChatPanel.vue'
import MoodOverlay from './mood/MoodSelector.vue'
import StationPanel from './station/StationPanel.vue'
import { bindStation, openStation } from './station/station'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'

const round = useRoundStore()
const client = new WSClient(WS_URL)
bindStation(() => client) // 补给站 REST 读 session_id(重连不变)
const audio = new AudioQueue()
const mood = new MoodSelector({ round, send: (m) => client.send(m) })

const boardRef = ref<InstanceType<typeof BoardCanvas> | null>(null)
const l2dStageEl = ref<HTMLElement | null>(null)
const l2dCanvasEl = ref<HTMLCanvasElement | null>(null)
const l2dReady = ref(false)
const l2dModelLabel = ref('')
const l2dBusy = ref(false)
let l2d: Live2DController | null = null
let l2dEntry: ModelEntry | null = null
const wsStatus = ref<'connecting' | 'open' | 'closed'>('connecting')
const draft = ref('')
const lastTemplate = ref<string | null>(null)
const protoOpen = ref(false)
const frames = ref<{ kind: string; brief: string }[]>([])

const avatar = computed(() => avatarSvg(expressionFor(round.emotionLabel)))

const ROUTE_TABS = [
  { id: 'answer', label: 'answer · 直接答' },
  { id: 'collect', label: 'collect · 多轮采集' },
  { id: 'crisis', label: 'crisis · 危机' },
] as const

const moodPillText = computed(() => `此刻 · ${round.emotionLabel ?? '平静'}`)
const boardTitle = computed(() => {
  if (round.crisis || lastTemplate.value === 'stage_map') return '你不需要一个人扛'
  if (lastTemplate.value === 'emotion_wheel') return '情绪轮盘'
  return '心里的那棵树'
})
const boardNote = computed(() => {
  if (round.crisis || lastTemplate.value === 'stage_map') return '热线 12356 一直在 · 先一起待一会儿'
  if (lastTemplate.value === null) return '等一句你的话,我在听。'
  return '小栖在听,黑板会慢慢长出来'
})
const boardStatus = computed(() => (round.crisis ? '危机通道 · 规则硬判' : ''))
const boardWarn = computed(() => round.crisis)

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
    const frame = msg as Extract<S2CMsg, { type: T }>
    frames.value.push({ kind: frame.type, brief: brief(frame) })
    if (frames.value.length > 50) frames.value.shift()
    fn(frame)
  })
}

// ── Live2D 载入/切换(目录=本地 vendor,缺文件回退 CDN;切换=轮换+持久化) ──

async function loadL2d(preferId?: string): Promise<void> {
  if (l2dStageEl.value === null || l2dCanvasEl.value === null) return
  l2dBusy.value = true
  try {
    const list = await loadCatalog()
    l2dEntry =
      preferId !== undefined
        ? (list.find((m) => m.id === preferId) ?? loadSelection(list))
        : loadSelection(list)
    persistSelection(l2dEntry.id)
    l2dModelLabel.value = l2dEntry.label
    l2d?.destroy()
    l2d = null
    l2dReady.value = false
    const ctrl = await createLive2D(l2dStageEl.value, l2dCanvasEl.value, modelUrls(l2dEntry))
    l2d = ctrl
    l2dReady.value = ctrl !== null
    if (ctrl !== null) ctrl.setExpression(expressionFor(round.emotionLabel))
  } finally {
    l2dBusy.value = false
  }
}

function switchL2d(): void {
  const cur = l2dEntry
  if (l2dBusy.value || cur === null) return
  void loadCatalog().then((list) => {
    const nx = nextModel(list, cur.id)
    void loadL2d(nx.id)
  })
}

onMounted(() => {
  // Live2D 真立绘(异步就绪;失败 null 落回 SVG 兜底);表情随情绪、口型随播放态
  void loadL2d()

  track('first_frame', (m) => {
    audio.stopAndFade()
    round.transition({ kind: 'frame', msg: m })
    boardRef.value?.clear()
    lastTemplate.value = m.template
    chat.beginBot(m.text)
    if (m.mood_select) mood.show()
    else mood.hide()
  })
  track('draw', (m) => {
    round.transition({ kind: 'frame', msg: m })
    lastTemplate.value = m.template
    boardRef.value?.render(m.template, m.data)
  })
  track('text_delta', (m) => {
    round.transition({ kind: 'frame', msg: m })
    chat.appendDelta(m.text)
  })
  track('audio_chunk', (m) => {
    audio.enqueue(m)
  })
  track('done', (m) => {
    round.transition({ kind: 'frame', msg: m })
    chat.finalize()
    mood.hide()
  })
  track('error', (m) => {
    round.transition({ kind: 'frame', msg: m })
    chat.finalize()
    chat.beginBot('小栖刚才走神了,我们再试一次好吗?换句话说说也可以。')
    mood.hide()
  })

  client
    .connect()
    .then(() => {
      wsStatus.value = 'open'
    })
    .catch((err: unknown) => {
      wsStatus.value = 'closed'
      logger.error('app', `连接失败: ${String(err)}`)
    })

  audio.onPlayback((active) => l2d?.setSpeaking(active))
})

// 表情驱动:emotionLabel 变化 → Live2D 表情(SVG 兜底未就绪时经 computed 重绘)
watch(
  () => round.emotionLabel,
  (label) => l2d?.setExpression(expressionFor(label)),
)

onUnmounted(() => {
  l2d?.destroy()
  l2d = null
})

function submit(): void {
  const text = draft.value.trim()
  if (text === '' || wsStatus.value !== 'open') return
  client.send({ type: 'user_input', mode: 'text', text, audio: null, ts: Math.floor(Date.now() / 1000) })
  round.transition({ kind: 'user_sent' })
  chat.appendUser(text)
  draft.value = ''
}

// ── 语音输入(步骤8):MediaRecorder webm/opus,单段 ≤15s;base64 上报,转写走后端同流 ──

const recording = ref(false)
let recorder: MediaRecorder | null = null

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let binary = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return btoa(binary)
}

function toggleMic(): void {
  if (recording.value) {
    recorder?.stop()
    return
  }
  void (async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      const rec = new MediaRecorder(stream, { mimeType: mime })
      const chunks: Blob[] = []
      rec.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) chunks.push(e.data)
      }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        recording.value = false
        const blob = new Blob(chunks, { type: rec.mimeType })
        if (blob.size === 0 || wsStatus.value !== 'open') return
        void blob.arrayBuffer().then((buf) => {
          client.send({
            type: 'user_input',
            mode: 'audio',
            text: null,
            audio: arrayBufferToBase64(buf),
            ts: Math.floor(Date.now() / 1000),
          })
          round.transition({ kind: 'user_sent' })
          chat.appendUser('🎙(语音消息)')
        })
      }
      recorder = rec
      recording.value = true
      rec.start()
      window.setTimeout(() => {
        if (rec.state === 'recording') rec.stop()
      }, 15_000) // 契约 §4.1 单段上限
    } catch (err) {
      logger.warn('app', `录音不可用: ${String(err)}`)
    }
  })()
}
</script>

<template>
  <div class="app">
    <!-- 工具栏 -->
    <header class="toolbar glass">
      <div class="logo">
        <div class="mark"></div>
        心栖阁<span class="tag">技术原型</span>
      </div>
      <div class="route-tabs">
        <span
          v-for="t in ROUTE_TABS"
          :key="t.id"
          class="rt"
          :class="{ on: round.crisis ? t.id === 'crisis' : t.id === round.route && round.phase !== 'idle' }"
        >
          {{ t.label }}
        </span>
      </div>
      <button class="tb" type="button" @click="mood.show()">今日心情</button>
      <button class="tb" type="button" data-testid="station-entry" @click="openStation()">心灵补给站</button>
      <button class="tb" type="button" disabled title="二期">心灵练习</button>
      <button class="tb" type="button" disabled title="二期">留言墙</button>
      <button class="tb" type="button" disabled title="模型配置单源=backend/.env.example">设置</button>
      <span class="sp"></span>
      <button class="mood-pill" type="button" data-testid="mood-pill" @click="mood.show()">
        {{ moodPillText }}
      </button>
    </header>

    <!-- 舞台:黑板 + Live2D 留位 + 气泡/聊天抽屉 + 心情选择器 -->
    <div class="stage">
      <BoardCanvas
        ref="boardRef"
        :title="boardTitle"
        :note="boardNote"
        :status="boardStatus"
        :warn="boardWarn"
      />

      <!-- Live2D 立绘(真模型就绪渐显;未就绪/失败显示 SVG 手绘兜底;⇄=轮换内置立绘) -->
      <div ref="l2dStageEl" class="l2d-stage" data-testid="l2d-stage">
        <div class="char-svg" :style="{ opacity: l2dReady ? 0 : 1 }" v-html="avatar"></div>
        <canvas ref="l2dCanvasEl" class="l2d-canvas" :class="{ 'l2d-ready': l2dReady }"></canvas>
        <div class="l2d-name">
          小栖
          <button
            class="l2d-switch"
            type="button"
            :title="`换立绘(当前:${l2dModelLabel || '—'})`"
            data-testid="l2d-switch"
            @click="switchL2d"
          >⇄</button>
        </div>
      </div>

      <ChatPanel />
      <MoodOverlay @select="(m) => mood.select(m)" />
    </div>

    <!-- 心灵补给站:方案书懒生成(点击触发)→轮询→md 预览/导出 -->
    <StationPanel />

    <!-- 输入条 -->
    <form class="inputbar glass" @submit.prevent="submit">
      <button
        class="mic"
        :class="{ rec: recording }"
        type="button"
        :disabled="wsStatus !== 'open'"
        title="按一下开始录音,再点结束(≤15 秒)"
        aria-label="语音输入"
        data-testid="mic-btn"
        @click="toggleMic"
      >
        <svg viewBox="0 0 24 24">
          <path d="M12 2a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z" />
          <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
          <line x1="12" y1="19" x2="12" y2="22" />
        </svg>
      </button>
      <input
        v-model="draft"
        :disabled="wsStatus !== 'open'"
        placeholder="想说什么都可以,我在听…(试试:最近很焦虑睡不着 / 什么是正念)"
        data-testid="chat-input"
      />
      <button class="send" type="submit" :disabled="wsStatus !== 'open' || draft.trim() === ''" data-testid="send-btn">
        发送
      </button>
    </form>
  </div>

  <!-- 危机横幅 + 审计标签(后端规则硬判才出现,前端零判定逻辑) -->
  <div v-if="round.crisis" class="crisis-banner" data-testid="crisis-banner">
    <span class="cb-ic">
      <svg viewBox="0 0 24 24">
        <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
        <path d="M12 5 9.04 7.96a2.17 2.17 0 0 0 0 3.08c.82.82 2.13.85 3 .07l2.07-1.9a2.82 2.82 0 0 1 3.79 0l2.96 2.66" />
        <path d="M18 15l-2-2" />
        <path d="m15 18-2-2" />
      </svg>
    </span>
    <div>
      <div class="cb-main">心理援助热线 12356</div>
      <div class="cb-sub">我们一直在 · 别一个人扛</div>
    </div>
  </div>
  <div v-if="round.crisis" class="audit-tag" data-testid="audit-tag">WARN · crisis_gate_hit · 已转热线引导</div>

  <!-- 协议帧控制台(演示验帧用) -->
  <button class="proto-toggle" type="button" @click="protoOpen = !protoOpen">协议帧 WS</button>
  <div class="proto glass" :class="{ open: protoOpen }">
    <div class="p-h">WebSocket 帧流(对齐 ws-contract · 8 消息)</div>
    <div class="p-body" data-testid="frame-log">
      <div v-for="(f, i) in [...frames].reverse()" :key="frames.length - i" class="fr" :class="{ w: f.kind === 'error' }">
        <span class="fd">{{ f.kind }}</span>{{ f.brief }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 16px;
  gap: 12px;
  max-width: 1340px;
  margin: 0 auto;
}

/* ── 工具栏 ── */
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  flex: none;
  border-radius: 999px;
  position: relative;
  z-index: 30;
}
.logo {
  font-family: var(--serif);
  font-weight: 700;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 9px;
  margin-right: 6px;
}
.logo .mark {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #a3b18a, #6e937c);
  box-shadow: 0 2px 8px rgba(110, 147, 124, 0.45);
}
.logo .tag {
  font-size: 10px;
  color: var(--muted);
  font-weight: 400;
  font-family: var(--sans);
  background: rgba(255, 255, 255, 0.6);
  padding: 2px 8px;
  border-radius: 999px;
  margin-left: 2px;
}
.route-tabs {
  display: flex;
  gap: 5px;
  margin-left: 4px;
}
.rt {
  font-size: 12px;
  color: var(--muted);
  padding: 6px 13px;
  border-radius: 999px;
  border: 1px solid transparent;
  transition: all 0.22s;
  background: transparent;
  white-space: nowrap;
}
.rt.on {
  color: #fff;
  background: var(--primary);
  box-shadow: 0 3px 12px -3px rgba(110, 147, 124, 0.5);
}
.sp { flex: 1; }
.tb {
  font-size: 12px;
  color: var(--muted);
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.22s;
  border: 1px solid transparent;
  background: transparent;
  white-space: nowrap;
}
.tb:hover:not(:disabled) {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.6);
}
.tb:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.mood-pill {
  font-size: 12px;
  color: #5e6b58;
  background: rgba(227, 237, 226, 0.9);
  padding: 6px 14px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  transition:
    transform 0.25s var(--ease),
    box-shadow 0.25s;
  border: 0;
}
.mood-pill::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary);
}
.mood-pill::after {
  content: '▾';
  font-size: 9px;
  opacity: 0.7;
}
.mood-pill:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 14px -6px rgba(110, 147, 124, 0.5);
}

/* ── 舞台 ── */
.stage {
  flex: 1;
  position: relative;
  min-height: 0;
}

/* ── Live2D 留位 ── */
.l2d-stage {
  position: absolute;
  left: calc(64% - 85px);
  bottom: 8px;
  width: 300px;
  height: 440px;
  z-index: 12;
  filter: drop-shadow(0 18px 26px rgba(47, 58, 49, 0.35));
}
.l2d-stage::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -6px;
  transform: translateX(-50%);
  width: 70%;
  height: 16px;
  border-radius: 50%;
  background: rgba(47, 58, 49, 0.16);
  filter: blur(7px);
  pointer-events: none;
}
.char-svg {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  transition: opacity 0.45s;
}
.char-svg :deep(svg) {
  height: 88%;
  filter: drop-shadow(0 10px 16px rgba(62, 58, 53, 0.2));
}
.l2d-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.5s;
  pointer-events: none;
}
.l2d-canvas.l2d-ready {
  opacity: 1;
  pointer-events: auto;
}
.l2d-name {
  position: absolute;
  bottom: -22px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.6);
  padding: 3px 12px;
  border-radius: 999px;
  backdrop-filter: blur(6px);
  white-space: nowrap;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 7px;
}
.l2d-switch {
  border: 0;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.7);
  color: var(--muted);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.l2d-switch:hover {
  background: var(--primary);
  color: #fff;
  transform: rotate(90deg);
}

/* ── 输入条 ── */
.inputbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  flex: none;
  border-radius: 999px;
  max-width: 720px;
  margin: 0 auto;
  width: 100%;
  position: relative;
  z-index: 30;
}
.mic {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--muted);
  flex: none;
  transition: all 0.25s;
  border: 0;
}
.mic:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.mic.rec {
  background: var(--accent);
  color: #fff;
  animation: pulse 1.2s infinite;
}
.mic svg {
  width: 17px;
  height: 17px;
  stroke: currentColor;
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.inputbar input {
  flex: 1;
  border: 0;
  background: transparent;
  outline: none;
  font-size: 13.5px;
  color: var(--ink);
  font-family: var(--sans);
}
.inputbar input::placeholder { color: var(--muted); }
.send {
  border: 0;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  padding: 10px 24px;
  border-radius: 999px;
  cursor: pointer;
  box-shadow: 0 3px 12px -3px rgba(110, 147, 124, 0.5);
  transition: transform 0.28s var(--ease);
  font-family: var(--sans);
}
.send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.send:hover:not(:disabled) { transform: translateY(-2px); }

/* ── 危机横幅 + 审计 ── */
.crisis-banner {
  position: fixed;
  top: 70px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 70;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 12px 22px;
  border-radius: 16px;
  background: linear-gradient(135deg, #e8c9b0, #f0d8c0);
  border: 1px solid rgba(213, 138, 99, 0.4);
  box-shadow: 0 18px 46px -20px rgba(213, 138, 99, 0.5);
}
.cb-ic {
  flex: none;
  color: #7a4a32;
  display: flex;
  align-items: center;
}
.cb-ic svg {
  width: 22px;
  height: 22px;
  stroke: currentColor;
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.cb-main {
  font-size: 14px;
  font-weight: 700;
  color: #7a4a32;
}
.cb-sub {
  font-size: 11.5px;
  color: #8a5a42;
}
.audit-tag {
  position: fixed;
  top: 118px;
  right: 20px;
  z-index: 70;
  font-size: 10px;
  font-family: ui-monospace, monospace;
  color: #a2563b;
  background: rgba(255, 248, 244, 0.92);
  border: 1px solid rgba(213, 138, 99, 0.4);
  padding: 6px 10px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.audit-tag::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #d58a63;
  animation: pulse 1.6s infinite;
}

/* ── 协议帧控制台 ── */
.proto-toggle {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 80;
  border: 0;
  font-size: 11px;
  padding: 8px 14px;
  border-radius: 999px;
  cursor: pointer;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(10px);
  box-shadow: 0 8px 24px -12px rgba(62, 58, 53, 0.4);
  font-family: ui-monospace, monospace;
  transition: all 0.25s;
}
.proto-toggle:hover { transform: translateY(-2px); }
.proto {
  position: fixed;
  right: 18px;
  bottom: 56px;
  z-index: 80;
  width: 404px;
  max-height: 244px;
  border-radius: 16px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  opacity: 0;
  pointer-events: none;
  visibility: hidden;
  transition: all 0.3s var(--ease);
}
.proto.open {
  opacity: 1;
  pointer-events: auto;
  visibility: visible;
}
.p-h {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: ui-monospace, monospace;
}
.p-h::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary);
  animation: pulse 1.6s infinite;
}
.p-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-family: ui-monospace, monospace;
  font-size: 10.5px;
  line-height: 1.5;
}
.p-body::-webkit-scrollbar { width: 5px; }
.p-body::-webkit-scrollbar-thumb { background: rgba(110, 147, 124, 0.3); border-radius: 3px; }
.fr {
  padding: 3px 8px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.5);
  animation: fadeup 0.3s var(--ease);
}
.fr .fd {
  display: inline-block;
  min-width: 74px;
  font-weight: 700;
  margin-right: 6px;
  color: #6e937c;
}
.fr.w { background: rgba(213, 138, 99, 0.12); }
.fr.w .fd { color: #c9705b; }
</style>
