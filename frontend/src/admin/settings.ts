// admin/settings.ts —— 设置面板控制器(frontend-plan §2 设置行):
// 记忆治理(情绪趋势 R7 口径 mood_select 单源 + 语义记忆列表查看/单条删除
// + 一键清除带 GitHub 删库式两步确认)。模型配置走 /admin/llm/*(面板组件内直连,
// profiles 多配置+单激活),旧 /admin/config 双源口已随 T4 清理移除。
// REST 基址由 VITE_WS_URL 换算(同 station.ts);全局 admin 操作无需 session_id,不必 bindStation。
// 状态为模块级响应式单例;确认门:confirmInput === CONFIRM_PHRASE 才真正调 clear。

import { reactive } from 'vue'
import { logger } from '../logger'
import { clearPersistedSession } from '../ws/client'

export type SettingsPhase = 'idle' | 'loading' | 'saved' | 'error'

interface TrendRow {
  date: string
  source: string
  mood_label: string
  intensity: number | null
}

export interface MemoryItem {
  id: string
  text: string
  status: string
  date: string
}

export const CONFIRM_PHRASE = '清除记忆'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'
const REST_BASE = new URL(WS_URL.replace(/^ws/, 'http')).origin

export const settings = reactive({
  open: false,
  phase: 'idle' as SettingsPhase,
  trends: [] as TrendRow[],
  memories: [] as MemoryItem[],
  message: '',
  confirmOpen: false,
  confirmInput: '',
})

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<{ status: number; body: T | null }> {
  const res = await fetch(`${REST_BASE}${path}`, init)
  try {
    const body = await res.json()
    return { status: res.status, body: body as T }
  } catch {
    return { status: res.status, body: null }
  }
}

function errorDetail(body: unknown): string {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === 'string') return d
  }
  return '后端暂时没反应,稍后再试。'
}

export function openSettings(): void {
  settings.open = true
  settings.phase = 'idle'
  void loadTrends()
  void loadMemories()
}

export function closeSettings(): void {
  settings.open = false
  settings.confirmOpen = false
}

export async function loadTrends(): Promise<void> {
  const { status, body } = await requestJson<{ moods: TrendRow[] }>('/admin/trends')
  if (status !== 200) {
    settings.phase = 'error'
    settings.message = '情绪趋势读取失败。'
    return
  }
  settings.trends = body?.moods ?? []
}

export async function loadMemories(): Promise<void> {
  // 治理「用户可查看」:打开设置即拉语义记忆列表;失败不弹全局错误(记忆区自带空态)
  const { status, body } = await requestJson<{ items: MemoryItem[] }>('/admin/memories')
  settings.memories = status === 200 ? (body?.items ?? []) : []
}

export async function deleteMemory(id: string): Promise<void> {
  const { status } = await requestJson(`/admin/memories/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (status === 200) {
    settings.memories = settings.memories.filter((m) => m.id !== id)
  } else {
    settings.phase = 'error'
    settings.message = '删除没有完成,请稍后再试。'
  }
}

export function requestClear(): void {
  settings.confirmOpen = true
  settings.confirmInput = ''
}

export function cancelClear(): void {
  settings.confirmOpen = false
  settings.confirmInput = ''
}

/** 高危确认门:输入必须等于 CONFIRM_PHRASE 才能清除(同 GitHub 删库提示)。 */
export function confirmMatches(input: string): boolean {
  return input === CONFIRM_PHRASE
}

export async function clearMemory(): Promise<void> {
  // 门:未输入确认短语不发请求(防护前置,破坏性操作)
  if (!confirmMatches(settings.confirmInput)) {
    settings.phase = 'error'
    settings.message = '请输入确认短语再清除。'
    return
  }
  settings.confirmOpen = false
  settings.confirmInput = ''
  try {
    // ADR-005 治理联动:先清浏览器存的身份再调端点——共用电脑暴露面闭环
    // (后端清 Redis/SQLite,前端清 localStorage;后端失败则不落,顺序不可倒)
    clearPersistedSession()
    const { status, body } = await requestJson<{ ok?: boolean; detail?: string }>(
      '/admin/clear_memory',
      { method: 'POST' },
    )
    if (status === 200) {
      settings.message = '记忆已清除。'
      settings.trends = []
      settings.phase = 'saved'
    } else {
      settings.phase = 'error'
      settings.message = body !== null && body.detail ? body.detail : errorDetail(body)
    }
  } catch (err) {
    settings.phase = 'error'
    settings.message = errorDetail(null)
    logger.error('settings', String(err))
  }
}

/** 测试口:重置模块态。 */
export function resetSettingsForTest(): void {
  settings.open = false
  settings.phase = 'idle'
  settings.trends = []
  settings.memories = []
  settings.message = ''
  settings.confirmOpen = false
  settings.confirmInput = ''
}
