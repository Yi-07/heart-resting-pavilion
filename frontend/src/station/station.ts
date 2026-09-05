// station/station.ts —— 心灵补给站控制器(frontend-plan §2 station 行):
// 入口点击→GET latest(404 则 POST generate 受理)→轮询 pending→ready 渲染 md;
// 409=本会话无素材(先完成一次梳理);端点/响应形状单源=ws-contract §1。
// 状态为模块级响应式单例(同 chat/messages 模式);session_id 经 bindStation 注入读取。

import { reactive } from 'vue'
import { logger } from '../logger'
import type { WSClient } from '../ws/client'

export type StationPhase = 'idle' | 'pending' | 'ready' | 'empty' | 'error'

/** ws-contract §1 补给站 REST 响应(report_md 仅 ready 返回) */
interface StationReport {
  status: 'pending' | 'ready'
  report_md?: string
}

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'
/** REST 基址由 WS 地址换算(ws→http),单环境变量双用 */
const REST_BASE = new URL(WS_URL.replace(/^ws/, 'http')).origin
const POLL_MS = 1500

export const station = reactive({
  open: false,
  phase: 'idle' as StationPhase,
  reportMd: '',
  message: '',
})

let getClient: (() => WSClient) | null = null
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollSeq = 0

/** App 装配时注入 WS 客户端源(读 session_id;重连不变) */
export function bindStation(source: () => WSClient): void {
  getClient = source
}

function stopPolling(): void {
  pollSeq += 1 // 使在途回调全部失效
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function latestUrl(sid: string): string {
  return `${REST_BASE}/station/report/latest?session_id=${encodeURIComponent(sid)}`
}
function generateUrl(sid: string): string {
  return `${REST_BASE}/station/report/generate?session_id=${encodeURIComponent(sid)}`
}

async function fetchReport(
  url: string,
  init?: RequestInit,
): Promise<{ status: number; body: StationReport | null }> {
  const res = await fetch(url, init)
  if (!res.ok) return { status: res.status, body: null }
  return { status: res.status, body: (await res.json()) as StationReport }
}

function showReady(md: string): void {
  station.phase = 'ready'
  station.reportMd = md
}

function schedulePoll(sid: string, seq: number): void {
  if (seq !== pollSeq) return
  pollTimer = setTimeout(() => {
    void fetchReport(latestUrl(sid))
      .then(({ status, body }) => {
        if (seq !== pollSeq) return
        if (status === 200 && body?.status === 'ready') {
          showReady(body.report_md ?? '')
          return
        }
        if (status !== 200) throw new Error(`latest ${status}`)
        schedulePoll(sid, seq)
      })
      .catch((err: unknown) => {
        if (seq !== pollSeq) return
        station.phase = 'error'
        station.message = '小栖整理到一半走神了,稍后再点开试试。'
        logger.error('station', String(err))
      })
  }, POLL_MS)
}

/** 打开面板并取稿(已 ready 直显;从未生成则触发生成=「邀请语点击触发生成」的入口) */
export function openStation(): void {
  station.open = true
  const sid = getClient?.().sessionId ?? null
  if (sid === null) {
    station.phase = 'empty'
    station.message = '先和小栖聊几句,这里才会有为你整理的方案。'
    return
  }
  station.phase = 'pending'
  station.message = '正在为你整理'
  stopPolling()
  const seq = pollSeq
  void fetchReport(latestUrl(sid))
    .then(async ({ status, body }) => {
      if (seq !== pollSeq) return
      if (status === 200 && body?.status === 'ready') {
        showReady(body.report_md ?? '')
        return
      }
      if (status === 404) {
        const gen = await fetchReport(generateUrl(sid), { method: 'POST' })
        if (gen.status === 409) {
          station.phase = 'empty'
          station.message = '这次对话还没有可整理的素材——先完成一次梳理,再来领取你的方案书。'
          return
        }
        if (gen.status !== 200) throw new Error(`generate ${gen.status}`)
      } else if (status !== 200) {
        throw new Error(`latest ${status}`)
      }
      schedulePoll(sid, seq)
    })
    .catch((err: unknown) => {
      if (seq !== pollSeq) return
      station.phase = 'error'
      station.message = '网络不太顺畅,稍后再点开试试。'
      logger.error('station', String(err))
    })
}

/** 重新整理:强制再生成一次(每会话最新胜,覆盖旧稿) */
export function regenerateStation(): void {
  const sid = getClient?.().sessionId ?? null
  if (sid === null) return
  stopPolling()
  const seq = pollSeq
  station.phase = 'pending'
  station.message = '正在为你整理'
  void fetchReport(generateUrl(sid), { method: 'POST' })
    .then(({ status }) => {
      if (seq !== pollSeq) return
      if (status === 409) {
        station.phase = 'empty'
        station.message = '这次对话还没有可整理的素材——先完成一次梳理,再来领取你的方案书。'
        return
      }
      if (status !== 200) throw new Error(`generate ${status}`)
      schedulePoll(sid, seq)
    })
    .catch((err: unknown) => {
      if (seq !== pollSeq) return
      station.phase = 'error'
      station.message = '网络不太顺畅,稍后再试一次。'
      logger.error('station', String(err))
    })
}

export function closeStation(): void {
  station.open = false
  stopPolling()
}

/** 导出 .md(spec MVP=预览/导出;pdf 二期);Blob 下载零依赖 */
export function exportStationReport(): void {
  if (station.reportMd === '' || typeof document === 'undefined') return
  const blob = new Blob([station.reportMd], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '心栖阁-心理成长方案.md'
  a.click()
  URL.revokeObjectURL(url)
}

/** 测试口:重置模块态 */
export function resetStationForTest(): void {
  stopPolling()
  station.open = false
  station.phase = 'idle'
  station.reportMd = ''
  station.message = ''
}
