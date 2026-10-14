// station/station.ts —— 心灵补给站控制器(frontend-plan §2 station 行):
//   场景 A:聊天邀请语链接 → openStationRound(roundId) —— 只针对该轮生成/取稿，
//          生成中显等待态；失败不显示别轮报告。
//   场景 B:设置栏入口 → openStationList() —— 报告列表，点行进入同一套详情。
//   详情复用 StationPanel:重新生成(只针对当前轮，失败保留旧稿)/ 导出(文件名带轮次)。
// 端点/响应形状单源=ws-contract §1(report_md 仅 ready 返回；list 见契约报告列表)。

import { reactive } from 'vue'
import { logger } from '../logger'
import type { WSClient } from '../ws/client'

export type StationPhase = 'idle' | 'loading' | 'pending' | 'ready' | 'empty' | 'error'
export type StationView = 'list' | 'detail'
export type CanRegenerate = 'yes' | 'no' | 'unknown'

/** ws-contract §1 报告列表行 */
export interface ReportRow {
  round_id: string
  title: string
  status: 'pending' | 'ready'
  created_at: string
  updated_at: string
  expires_at: string | null
  can_regenerate: CanRegenerate
}

/** ws-contract §1 补给站 REST 响应(report_md 仅 ready 返回) */
interface StationReport {
  status: 'pending' | 'ready'
  report_md?: string
  /** 报告标题(情境 · 情绪),取自报告自身数据;重新生成后可能变化 */
  title?: string
  /** 最近一次成功生成/重生成时刻 */
  updated_at?: string
}

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'
/** REST 基址由 WS 地址换算(ws→http),单环境变量双用 */
const REST_BASE = new URL(WS_URL.replace(/^ws/, 'http')).origin
const POLL_MS = 1500

export const station = reactive({
  open: false,
  view: 'list' as StationView,
  phase: 'idle' as StationPhase,
  /** 列表行(场景 B);按 created_at 降序，只含有效期内的报告 */
  rows: [] as ReportRow[],
  /** 当前详情对应的 collect 轮次(后端权威标识) */
  currentRoundId: null as string | null,
  currentTitle: '',
  currentMeta: null as { created_at: string; expires_at: string | null; updated_at?: string } | null,
  reportMd: '',
  message: '',
  /** 重新生成中:旧稿继续可读，仅底部浮条提示 */
  regenerating: false,
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

function latestUrl(sid: string, roundId: string): string {
  return `${REST_BASE}/station/report/latest?session_id=${encodeURIComponent(sid)}&round_id=${encodeURIComponent(roundId)}`
}
function generateUrl(sid: string, roundId: string): string {
  return `${REST_BASE}/station/report/generate?session_id=${encodeURIComponent(sid)}&round_id=${encodeURIComponent(roundId)}`
}
function listUrl(sid: string): string {
  return `${REST_BASE}/station/report/list?session_id=${encodeURIComponent(sid)}`
}

async function fetchReport(
  url: string,
  init?: RequestInit,
): Promise<{ status: number; body: unknown }> {
  const res = await fetch(url, init)
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  return { status: res.status, body }
}

type OpenResult = 'ready' | 'pending' | 'unavailable'

/** 按轮取稿一次:latest →(404 则 generate)→ 轮询。返回本轮是否可寻址。 */
async function _openRoundOnce(sid: string, rid: string, seq: number): Promise<OpenResult> {
  const { status, body } = await fetchReport(latestUrl(sid, rid))
  if (seq !== pollSeq) return 'unavailable'
  const report = body as StationReport | null
  if (status === 200 && report?.status === 'ready') {
    showReady(report.report_md ?? '', report.title, report.updated_at)
    return 'ready'
  }
  if (status === 200) {
    station.phase = 'pending'
    schedulePoll(sid, rid, seq)
    return 'pending'
  }
  if (status === 404) {
    const gen = await fetchReport(generateUrl(sid, rid), { method: 'POST' })
    if (seq !== pollSeq) return 'unavailable'
    if (gen.status === 409) {
      station.phase = 'error'
      station.message = detailText(gen.body) ?? '这一轮还没有可整理的素材。'
      return 'unavailable'
    }
    if (gen.status === 503) {
      station.phase = 'error'
      station.message = '暂时无法确认这一轮素材的有效期,稍后再点开试试。'
      return 'unavailable'
    }
    if (gen.status !== 200) throw new Error(`generate ${gen.status}`)
    station.phase = 'pending'
    schedulePoll(sid, rid, seq)
    return 'pending'
  }
  throw new Error(`latest ${status}`)
}

function _networkFallback(err: unknown): void {
  station.regenerating = false
  station.phase = 'error'
  station.message =
    station.reportMd !== ''
      ? '刚才那次整理被打断了——上面这份是之前为你整理的,仍可查看与导出。'
      : '小栖整理到一半走神了,稍后再点开试试。'
  logger.error('station', String(err))
}

function showReady(md: string, title?: string | null, updatedAt?: string | null): void {
  station.phase = 'ready'
  station.reportMd = md
  if (title !== null && title !== undefined && title !== '') station.currentTitle = title
  if (updatedAt !== null && updatedAt !== undefined) station.currentMeta = {
    created_at: station.currentMeta?.created_at ?? '',
    expires_at: station.currentMeta?.expires_at ?? null,
    updated_at: updatedAt,
  }
  station.regenerating = false
}

function schedulePoll(sid: string, roundId: string, seq: number): void {
  if (seq !== pollSeq) return
  pollTimer = setTimeout(() => {
    void fetchReport(latestUrl(sid, roundId))
      .then(({ status, body }) => {
        if (seq !== pollSeq) return
        const report = body as StationReport | null
        if (status === 200 && report?.status === 'ready') {
          showReady(report.report_md ?? '', report.title, report.updated_at)
          return
        }
        if (status !== 200) throw new Error(`latest ${status}`)
        schedulePoll(sid, roundId, seq)
      })
      .catch((err: unknown) => {
        if (seq !== pollSeq) return
        // 轮询失败:若有旧稿则保留(regenerating 复位即可查看)，否则报错态
        station.regenerating = false
        station.phase = station.reportMd !== '' ? 'error' : 'error'
        station.message =
          station.reportMd !== ''
            ? '刚才那次整理被打断了——上面这份是之前为你整理的,仍可查看与导出。'
            : '小栖整理到一半走神了,稍后再点开试试。'
        logger.error('station', String(err))
      })
  }, POLL_MS)
}

/** 场景 B:设置栏入口 → 报告列表 */
export function openStationList(): void {
  station.open = true
  station.view = 'list'
  station.phase = 'loading'
  station.message = ''
  station.regenerating = false
  stopPolling()
  const seq = pollSeq
  const sid = getClient?.().sessionId ?? null
  if (sid === null) {
    station.phase = 'empty'
    station.message = '先和小栖聊几句,这里才会有为你整理的方案。'
    return
  }
  void fetchReport(listUrl(sid))
    .then(({ status, body }) => {
      if (seq !== pollSeq) return
      if (status !== 200) throw new Error(`list ${status}`)
      const rows = ((body as { reports?: ReportRow[] } | null)?.reports ?? []) as ReportRow[]
      station.rows = rows
      station.phase = 'idle'
    })
    .catch((err: unknown) => {
      if (seq !== pollSeq) return
      station.phase = 'error'
      station.message = '报告列表没读出来,稍后再点开试试。'
      logger.error('station', String(err))
    })
}

/** 场景 A:邀请语链接 → 指定轮次的报告。
 *  roundId=null(非 collect 消息)→ 退回列表；
 *  stationReady=false 不硬失败:邀请语文本先于 done(归档信号)到达,本轮可能正在归档,
 *  给一段宽限重试;仍不可寻址才给显式失败态(不静默生成、不谎报可生成)。 */
export function openStationRound(
  roundId: string | null,
  stationReady = true,
  meta: { created_at: string; expires_at: string | null; updated_at?: string } | null = null,
): void {
  stopPolling()
  const sid = getClient?.().sessionId ?? null
  if (roundId === null || sid === null) {
    openStationList()
    return
  }
  station.open = true
  station.view = 'detail'
  station.currentRoundId = roundId
  station.currentTitle = '' // 由 latest 响应的 title 回填(情境 · 情绪),不用轮次序号
  station.currentMeta = meta
  station.reportMd = ''
  station.message = ''
  station.regenerating = false
  if (stationReady) {
    station.phase = 'loading'
    const seq = pollSeq
    void _openRoundOnce(sid, roundId, seq).catch(_networkFallback)
    return
  }
  // 宽限:归档窗口内点击,稍等再试(最多 3 次)
  station.phase = 'pending'
  const seq = pollSeq
  void (async () => {
    for (let attempt = 0; attempt < 3; attempt++) {
      if (attempt > 0) await new Promise((r) => setTimeout(r, 600))
      if (seq !== pollSeq) return
      try {
        const result = await _openRoundOnce(sid, roundId, seq)
        if (result !== 'unavailable') return
      } catch (err) {
        _networkFallback(err)
        return
      }
    }
    if (seq !== pollSeq) return
    station.phase = 'error'
    station.message = '这轮的整理还没存好,稍后我们重新聊聊,再为你补一份。'
  })()
}

/** 列表行点击 → 同一套详情 */
export function openStationRow(row: ReportRow): void {
  openStationRound(row.round_id, true, {
    created_at: row.created_at,
    updated_at: row.updated_at,
    expires_at: row.expires_at,
  })
}

/** 返回列表(场景 B) */
export function backToList(): void {
  stopPolling()
  openStationList()
}

/** 重新生成:只针对当前轮;失败保留旧稿可查看 */
export function regenerateStation(): void {
  const sid = getClient?.().sessionId ?? null
  const rid = station.currentRoundId
  if (sid === null || rid === null) return
  stopPolling()
  const seq = pollSeq
  station.regenerating = true
  station.phase = 'pending'
  station.message = ''
  void fetchReport(generateUrl(sid, rid), { method: 'POST' })
    .then(({ status }) => {
      if (seq !== pollSeq) return
      if (status === 409) {
        station.regenerating = false
        station.phase = 'error'
        station.message = '这一轮的素材已不在有效期,暂时不能重新整理;上面这份仍可查看与导出。'
        return
      }
      if (status === 503) {
        station.regenerating = false
        station.phase = 'error'
        station.message = '暂时无法确认这一轮素材的有效期,稍后再试一次。'
        return
      }
      if (status !== 200) throw new Error(`generate ${status}`)
      schedulePoll(sid, rid, seq)
    })
    .catch((err: unknown) => {
      if (seq !== pollSeq) return
      station.regenerating = false
      station.phase = 'error'
      station.message = '刚才那次整理被打断了——上面这份是之前为你整理的,仍可查看与导出。'
      logger.error('station', String(err))
    })
}

export function closeStation(): void {
  station.open = false
  stopPolling()
}

function roundLabel(roundId: string): string {
  return /^\d+$/.test(roundId) ? `第 ${roundId} 次梳理` : '早期方案 · 轮次未知'
}

function detailText(body: unknown): string | null {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === 'string') return d
  }
  return null
}

/** 导出 .md(spec MVP=预览/导出;pdf 二期);Blob 下载零依赖 */
export function exportStationReport(): void {
  if (station.reportMd === '' || typeof document === 'undefined') return
  const raw = station.currentTitle !== ''
    ? station.currentTitle
    : station.currentRoundId !== null
      ? roundLabel(station.currentRoundId)
      : '方案'
  const label = raw.replace(/[\\/:*?"<>|]/g, ' ').trim() // 文件名非法字符
  const blob = new Blob([station.reportMd], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `心栖阁-${label}.md`
  a.click()
  URL.revokeObjectURL(url)
}

/** 测试口:重置模块态 */
export function resetStationForTest(): void {
  stopPolling()
  station.open = false
  station.view = 'list'
  station.phase = 'idle'
  station.rows = []
  station.currentRoundId = null
  station.currentTitle = ''
  station.currentMeta = null
  station.reportMd = ''
  station.message = ''
  station.regenerating = false
}
