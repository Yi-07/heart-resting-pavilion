<script setup lang="ts">
// 聊天面板:常态气泡(头部旁,点开抽屉)+ 抽屉完整记录(✕ 收起)。
// 等待期文案统一(T4):有旧文本显示旧文本(中间轮等待=上一问);无旧文本且回合
// 活跃一律「小栖正在梳理你说的…」——首轮/answer 开头不再闪跳,「我在听。」分支删。
// ADR-005:replay 帧回放——bubbles=幕布折叠(历史收横幅,展开降饱和气泡);
// digest=小结卡片+「原话已按隐私设定抹去」;历史气泡不入 msgs,不随新回合清除。
import { computed, ref } from 'vue'
import { chat, replay, splitStationMention } from './messages'
import { useRoundStore } from '../state/round'
import { openStationRound } from '../station/station'

const THINKING_TEXT = '小栖正在梳理你说的…'

const round = useRoundStore()
const histOpen = ref(false)

const bubbleText = computed(() => {
  const latest = chat.latestBotText()
  if (latest !== '') return latest.length > 64 ? `${latest.slice(0, 64)}…` : latest
  const active = round.phase !== 'idle'
  return active ? THINKING_TEXT : ''
})

const bubbleOn = computed(() => chat.latestBotText() !== '' || (round.phase !== 'idle' && round.phase !== 'final'))

function openDrawer(): void {
  chat.openDrawer()
}
</script>

<template>
  <!-- 气泡:抽屉打开时隐身 -->
  <div
    class="bubble"
    :class="{ on: bubbleOn && !chat.drawerOpen, ghost: chat.drawerOpen }"
    data-testid="bubble"
    title="点我看完整对话"
    @click="openDrawer"
  >
    <span class="who">小栖</span><span class="btx">{{ bubbleText }}</span>
    <span class="expand"><svg viewBox="0 0 24 24"><path d="M7 17 17 7M7 7h10v10" /></svg></span>
  </div>

  <!-- 抽屉:留白区展开 -->
  <div class="chat glass" :class="{ open: chat.drawerOpen }" data-testid="chat-panel">
    <div class="ch-h">
      对话记录
      <button class="ch-x" title="收起" @click="chat.closeDrawer()">✕</button>
    </div>
    <div class="ch-body" data-testid="chat-body">
      <!-- ADR-005 回放区(bubbles=幕布,digest=小结卡;仅 replay 帧到过才渲染) -->
      <template v-if="replay.mode === 'bubbles'">
        <button class="curtain" type="button" data-testid="replay-curtain" @click="histOpen = !histOpen">
          上次的对话 <span class="n">{{ replay.turns.length }} 条 {{ histOpen ? '收起 ▴' : '展开 ▾' }}</span>
        </button>
        <template v-if="histOpen">
          <div
            v-for="(t, i) in replay.turns"
            :key="`h${i}`"
            class="msg hist"
            :class="t.role === 'user' ? 'u' : 'x'"
          >
            <span class="who">{{ t.role === 'user' ? '你' : '小栖' }}</span>
            <p>{{ t.text }}</p>
          </div>
        </template>
      </template>
      <template v-else-if="replay.mode === 'digest'">
        <div class="day2-banner" data-testid="replay-digest">距上次对话已超过 30 分钟 · 原话已按隐私设定抹去</div>
      </template>
      <div v-if="replay.summary !== null" class="sumcard" data-testid="replay-summary">
        <span class="sc-tag">上次梳理小结</span>
        <div class="sc-body">{{ replay.summary }}</div>
      </div>
      <div v-for="m in chat.msgs" :key="m.id" class="msg" :class="m.who">
        <span class="who">{{ m.who === 'u' ? '你' : '小栖' }}</span>
        <p>
          <template v-for="(seg, i) in splitStationMention(m.text)" :key="i">
            <span
              v-if="seg.mention"
              class="st-link"
              :class="{ off: m.roundId == null || m.stationReady !== true }"
              data-testid="station-mention"
              :title="m.stationReady === true ? '点开看看为你整理的小方案' : '这轮的整理还没存好'"
              @click="openStationRound(m.roundId ?? null, m.stationReady === true)"
            >{{ seg.text }}</span>
            <template v-else>{{ seg.text }}</template>
          </template>
          <span v-if="m.streaming" class="caret">▍</span>
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bubble {
  position: absolute;
  left: calc(64% + 190px);
  bottom: 340px;
  max-width: 250px;
  padding: 11px 15px;
  border-radius: 16px 16px 16px 4px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ink);
  background: #fffdf8;
  border: 1px solid var(--line);
  box-shadow: 0 10px 30px -16px rgba(62, 58, 53, 0.35);
  opacity: 0;
  transform: translateY(6px);
  transition:
    opacity 0.4s var(--ease),
    transform 0.4s var(--ease);
  z-index: 13;
  cursor: pointer;
}
.bubble::before {
  content: '';
  position: absolute;
  left: -11px;
  top: 34px;
  width: 0;
  height: 0;
  border-right: 11px solid var(--line);
  border-top: 9px solid transparent;
  border-bottom: 9px solid transparent;
}
.bubble::after {
  content: '';
  position: absolute;
  left: -8px;
  top: 38px;
  width: 0;
  height: 0;
  border-right: 8px solid #c9c3b6;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
}
.bubble .who {
  font-size: 10px;
  color: var(--primary-deep);
  letter-spacing: 0.06em;
  display: block;
  margin-bottom: 4px;
}
.bubble .expand {
  position: absolute;
  right: -8px;
  bottom: -8px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px -3px rgba(110, 147, 124, 0.6);
}
.bubble .expand svg {
  width: 11px;
  height: 11px;
  stroke: currentColor;
  fill: none;
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.bubble.on { opacity: 1; transform: none; }
.bubble.ghost { opacity: 0; pointer-events: none; }

.chat {
  position: absolute;
  top: 0;
  right: 52px;
  bottom: 0;
  width: min(380px, 34%);
  border-radius: 18px;
  padding: 14px 14px 12px;
  display: flex;
  flex-direction: column;
  opacity: 0;
  transform: translateX(14px);
  pointer-events: none;
  visibility: hidden;
  transition: all 0.34s var(--ease);
  z-index: 16;
}
.chat.open {
  opacity: 1;
  transform: none;
  pointer-events: auto;
  visibility: visible;
}
.ch-h {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 10px;
  flex: none;
}
.ch-h::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary);
}
.ch-x {
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
.ch-x:hover { background: var(--primary); color: #fff; }
.ch-body {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.ch-body::-webkit-scrollbar { width: 6px; }
.ch-body::-webkit-scrollbar-thumb { background: rgba(110, 147, 124, 0.3); border-radius: 3px; }
.msg {
  max-width: 80%;
  padding: 9px 13px;
  font-size: 12.5px;
  line-height: 1.65;
  border-radius: 14px;
  animation: fadeup 0.35s var(--ease);
}
.msg.u {
  align-self: flex-end;
  background: var(--primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg.x {
  align-self: flex-start;
  background: #fffdf8;
  border: 1px solid var(--line);
  border-bottom-left-radius: 4px;
  color: var(--ink);
}
.msg .who {
  display: block;
  font-size: 9.5px;
  opacity: 0.7;
  margin-bottom: 3px;
  letter-spacing: 0.05em;
}
.msg p { margin: 0; white-space: pre-wrap; }
/* ── ADR-005 回放:幕布横幅 + 降饱和历史气泡 + 小结卡(形态=prototypes/replay-ui 定稿) ── */
.curtain {
  flex: none; align-self: center; display: flex; align-items: center; gap: 8px;
  font-size: 11px; color: var(--primary-deep); background: rgba(139, 174, 151, 0.12);
  border: 1px dashed rgba(110, 147, 124, 0.45); border-radius: 999px;
  padding: 6px 14px; cursor: pointer; margin-bottom: 4px; user-select: none;
  font-family: var(--sans); transition: background 0.2s;
}
.curtain:hover { background: rgba(139, 174, 151, 0.2); }
.curtain .n { font-size: 10px; opacity: 0.75; }
.msg.hist { opacity: 0.78; }
.msg.hist .who { opacity: 0.55; }
.day2-banner {
  flex: none; align-self: center; font-size: 10px; color: var(--muted);
  background: rgba(213, 138, 99, 0.1); border-radius: 999px; padding: 4px 12px; margin-bottom: 4px;
}
.sumcard {
  align-self: stretch; margin: 2px 6px 4px; padding: 11px 13px;
  border-radius: 14px 14px 14px 4px; background: #fffdf8;
  border: 1px solid rgba(213, 138, 99, 0.35);
}
.sumcard .sc-tag {
  display: inline-block; font-size: 10px; color: var(--accent);
  letter-spacing: 0.06em; margin-bottom: 5px; font-weight: 600;
}
.sumcard .sc-body { font-size: 11.5px; line-height: 1.7; color: var(--ink); opacity: 0.85; }
.st-link {
  color: var(--primary-deep);
  cursor: pointer;
  border-bottom: 1px dashed var(--primary-deep);
  transition: all 0.2s;
}
/* 素材未归档成功:入口置灰,点击给显式失败态(不静默生成) */
.st-link.off {
  color: var(--muted);
  border-bottom-color: rgba(110, 103, 94, 0.4);
  cursor: not-allowed;
  opacity: 0.7;
}
.st-link:hover {
  color: var(--primary);
  border-bottom-style: solid;
}
.caret {
  animation: pulse 1s infinite;
  color: var(--primary-deep);
}
</style>
