<script setup lang="ts">
// 设置面板(frontend-plan §2 设置行):模型配置(读当前预填→编辑保存)+ 记忆治理
// (情绪趋势 + 一键清除带 GitHub 删库式两步确认)。材质=prototypes/ui-taste 定稿:
// 薄玻璃面板/分组卡/分段药丸/tinted 玻璃按钮+流光/确认弹窗居中。
import { computed } from 'vue'
import {
  settings,
  closeSettings,
  saveConfig,
  switchProvider,
  requestClear,
  cancelClear,
  clearMemory,
  confirmMatches,
  CONFIRM_PHRASE,
} from './settings'

const confirmEnabled = computed(() => confirmMatches(settings.confirmInput))
</script>

<template>
  <section class="set" :class="{ open: settings.open }" data-testid="settings-panel">
    <header class="set-h">
      设置
      <button
        class="set-x"
        title="收起"
        data-testid="settings-close"
        @click="closeSettings()"
      >✕</button>
    </header>

    <div class="set-body">
      <p v-if="settings.message" class="set-status" :data-phase="settings.phase" data-testid="cfg-msg">
        {{ settings.message }}
      </p>

      <!-- 模型配置 -->
      <div class="sec">
        <div class="g-t">模型配置</div>
        <div class="f">
          <span>LLM 服务</span>
          <div class="seg" :class="{ right: settings.provider === 'ollama' }" data-testid="cfg-provider">
            <div class="thumb"></div>
            <button
              type="button"
              :class="{ on: settings.provider === 'deepseek' }"
              @click="switchProvider('deepseek')"
            >DeepSeek</button>
            <button
              type="button"
              :class="{ on: settings.provider === 'ollama' }"
              @click="switchProvider('ollama')"
            >Ollama</button>
          </div>
        </div>
        <div class="f">
          <span>模型</span>
          <input v-model="settings.model" data-testid="cfg-model" placeholder="model" />
        </div>
        <div class="f">
          <span>API 地址</span>
          <input v-model="settings.baseUrl" data-testid="cfg-base" placeholder="base_url" />
        </div>
        <div class="f">
          <span>API Key</span>
          <input
            v-model="settings.apiKey"
            type="password"
            data-testid="cfg-key"
            :placeholder="settings.apiKeySet ? '已配置 · 留空即不改' : '未配置'"
          />
        </div>
        <div class="voice">
          <div class="v"><b>ASR</b> SenseVoice 本地 · 转写即弃</div>
          <div class="v"><b>TTS</b> CosyVoice2 · sidecar 进程隔离</div>
        </div>
        <div class="set-actions">
          <button
            type="button"
            class="btn-main"
            :disabled="settings.phase === 'loading'"
            data-testid="cfg-save"
            @click="saveConfig()"
          >保存并生效</button>
        </div>
      </div>

      <!-- 记忆治理 -->
      <div class="sec">
        <div class="g-t">记忆治理</div>
        <div class="trends" data-testid="trends">
          <p v-if="settings.trends.length === 0" class="muted">暂无情绪记录。</p>
          <div v-for="(t, i) in settings.trends" :key="`${t.date}-${i}`" class="t-row">
            <span class="t-d">{{ t.date }}</span>
            <span class="t-l">{{ t.mood_label }}</span>
            <span class="t-s">{{ t.source }}</span>
          </div>
        </div>
        <button
          type="button"
          class="btn-danger"
          data-testid="cfg-clear"
          @click="requestClear()"
        >一键清除记忆</button>
      </div>
    </div>

    <!-- 清除确认(高危,两步;文字与按钮居中) -->
    <div v-if="settings.confirmOpen" class="confirm" data-testid="cfg-confirm">
      <h4>确认清除全部记忆?</h4>
      <p class="cf-note">将永久删除:当前会话记忆、对话摘要、心情趋势、已生成方案书。<b>不可恢复。</b></p>
      <p class="cf-p">请输入 <code>{{ CONFIRM_PHRASE }}</code> 确认</p>
      <input
        v-model="settings.confirmInput"
        data-testid="cfg-confirm-input"
        :placeholder="CONFIRM_PHRASE"
      />
      <div class="cf-actions">
        <button type="button" class="btn-ghost" data-testid="cfg-confirm-cancel" @click="cancelClear()">取消</button>
        <button
          type="button"
          class="btn-danger ok"
          :disabled="!confirmEnabled"
          data-testid="cfg-confirm-ok"
          @click="clearMemory()"
        >确认清除</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* 材质单源=prototypes/ui-taste 定稿:面板=重玻璃(厚),控件=轻玻璃(薄) */
.set {
  position: fixed;
  top: 74px;
  right: 16px;
  z-index: 55;
  width: min(368px, 92vw);
  max-height: calc(100vh - 170px);
  border-radius: 22px;
  padding: 16px;
  display: flex;
  flex-direction: column;
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
.set.open {
  opacity: 1;
  pointer-events: auto;
  visibility: visible;
  transform: none;
}
.set-h {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  font-family: var(--serif);
  margin-bottom: 12px;
  flex: none;
}
.set-h::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #a3b18a;
}
.set-x {
  margin-left: auto;
  border: 0;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.75);
  cursor: pointer;
  color: var(--muted);
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.9);
  transition: all 0.2s;
}
.set-x:active {
  transform: scale(0.9);
}
.set-x:hover {
  background: var(--primary-deep);
  color: #fff;
}
.set-body {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  font-size: 12.5px;
  color: var(--ink);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.set-body::-webkit-scrollbar {
  width: 6px;
}
.set-body::-webkit-scrollbar-thumb {
  background: rgba(110, 147, 124, 0.3);
  border-radius: 3px;
}
.set-status {
  font-size: 12px;
  color: var(--primary-deep);
  background: rgba(227, 237, 226, 0.8);
  border-radius: 10px;
  padding: 7px 10px;
}
.set-status[data-phase='error'] {
  color: #a2563b;
  background: rgba(248, 235, 229, 0.95);
}
/* 分组卡 */
.sec {
  padding: 13px 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.5);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.85);
}
.g-t {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--primary-deep);
  margin-bottom: 11px;
}
/* 表单行 */
.f {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 11px;
}
.f span {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--muted);
}
.f input {
  border: 1px solid rgba(110, 147, 124, 0.22);
  border-radius: 11px;
  padding: 9px 12px;
  font-size: 13px;
  font-family: var(--sans);
  color: var(--ink);
  background: rgba(255, 255, 255, 0.62);
  outline: none;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background 0.18s ease;
}
.f input:focus {
  border-color: var(--primary-deep);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 0 0 3px rgba(110, 147, 124, 0.14);
}
/* 分段药丸(iOS segmented,ui-taste 定稿) */
.seg {
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 3px;
  border-radius: 999px;
  background: rgba(110, 147, 124, 0.12);
  box-shadow: inset 0 1px 3px rgba(47, 58, 49, 0.08);
}
.seg .thumb {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 3px;
  width: calc(50% - 3px);
  border-radius: 999px;
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.78));
  box-shadow:
    0 2px 8px -2px rgba(47, 58, 49, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition: transform 0.3s var(--ease);
  will-change: transform;
}
.seg.right .thumb {
  transform: translateX(100%);
}
.seg button {
  position: relative;
  z-index: 1;
  border: 0;
  background: transparent;
  padding: 7px 0;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  cursor: pointer;
  letter-spacing: 0.02em;
  transition: color 0.25s;
}
.seg button.on {
  color: var(--primary-deep);
}
/* 语音只读卡 */
.voice {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 4px 0 2px;
}
.voice .v {
  padding: 9px 11px;
  border-radius: 11px;
  background: rgba(227, 237, 226, 0.55);
  font-size: 10.5px;
  color: #6b7568;
  line-height: 1.55;
}
.voice .v b {
  color: var(--primary-deep);
  margin-right: 4px;
}
/* tinted 薄玻璃按钮(主/危险)+ 流光 */
.set-actions {
  margin-top: 10px;
}
.set button {
  font-family: var(--sans);
}
.btn-main {
  position: relative;
  width: 100%;
  border: 0;
  padding: 10px 0;
  border-radius: 999px;
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #3d5a49;
  background: linear-gradient(180deg, rgba(163, 177, 138, 0.3), rgba(110, 147, 124, 0.16));
  backdrop-filter: blur(10px) saturate(1.4);
  box-shadow:
    inset 0 0 0 1px rgba(163, 177, 138, 0.55),
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 6px 16px -10px rgba(94, 127, 106, 0.5);
  transition:
    transform 0.1s ease-out,
    background 0.2s;
}
.btn-main:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(163, 177, 138, 0.42), rgba(110, 147, 124, 0.26));
}
.btn-main:active:not(:disabled) {
  transform: scale(0.97);
}
.btn-main:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn-danger {
  position: relative;
  width: 100%;
  border: 0;
  margin-top: 12px;
  padding: 10px 0;
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #8a4a2c;
  background: linear-gradient(180deg, rgba(230, 190, 160, 0.38), rgba(213, 138, 99, 0.2));
  backdrop-filter: blur(10px) saturate(1.4);
  box-shadow:
    inset 0 0 0 1px rgba(213, 138, 99, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.6),
    0 6px 16px -10px rgba(201, 122, 82, 0.45);
  transition:
    transform 0.1s ease-out,
    background 0.2s;
}
.btn-danger:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(230, 190, 160, 0.5), rgba(213, 138, 99, 0.3));
}
.btn-danger:active:not(:disabled) {
  transform: scale(0.97);
}
.btn-danger::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  padding: 1.2px;
  background: conic-gradient(
    from var(--ang),
    transparent 0deg,
    transparent 108deg,
    rgba(224, 163, 124, 0.7) 187deg,
    rgba(255, 236, 220, 0.85) 240deg,
    transparent 342deg
  );
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  clip-path: inset(0 round 999px);
  animation: orbit 2s linear infinite;
  pointer-events: none;
}
.btn-ghost {
  border: 0;
  padding: 10px 18px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.65);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.9);
  transition: transform 0.1s ease-out;
}
.btn-ghost:active {
  transform: scale(0.96);
}
/* 趋势行 */
.trends {
  display: flex;
  flex-direction: column;
  gap: 5px;
  max-height: 150px;
  overflow-y: auto;
  margin-bottom: 2px;
}
.trends::-webkit-scrollbar {
  width: 5px;
}
.trends::-webkit-scrollbar-thumb {
  background: rgba(110, 147, 124, 0.3);
  border-radius: 3px;
}
.muted {
  color: var(--muted);
}
.t-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  padding: 5px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}
.t-d {
  color: var(--muted);
  font-family: ui-monospace, monospace;
  font-size: 10px;
}
.t-l {
  font-weight: 700;
  color: var(--primary-deep);
}
.t-s {
  margin-left: auto;
  color: var(--muted);
  font-size: 10px;
}
/* 确认层:文字与按钮居中(高危两步) */
.confirm {
  position: absolute;
  inset: 0;
  z-index: 5;
  border-radius: inherit;
  padding: 20px;
  background: rgba(250, 247, 240, 0.94);
  backdrop-filter: blur(8px);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 9px;
  text-align: center;
  animation: fadeup 0.2s var(--ease);
}
.confirm h4 {
  font-size: 14px;
  font-weight: 700;
  font-family: var(--serif);
}
.cf-note {
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.7;
}
.cf-p {
  font-size: 11px;
  color: var(--muted);
}
.cf-p code {
  font-family: ui-monospace, monospace;
  color: #a2563b;
  background: rgba(213, 138, 99, 0.12);
  padding: 1px 6px;
  border-radius: 6px;
}
.confirm input {
  border: 1px solid rgba(213, 138, 99, 0.4);
  border-radius: 10px;
  padding: 9px 11px;
  font-size: 12.5px;
  outline: none;
  text-align: center;
}
.confirm input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(213, 138, 99, 0.15);
}
.cf-actions {
  display: flex;
  gap: 24px;
  justify-content: center;
  margin-top: 12px;
}
.confirm .ok {
  width: auto;
  margin: 0;
  padding: 10px 18px;
}
@keyframes orbit {
  to {
    --ang: 360deg;
  }
}
</style>
