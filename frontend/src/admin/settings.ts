// admin/settings.ts —— 设置面板控制器(frontend-plan §2 设置行):
//  模型配置(读当前预填→编辑保存)+ 记忆治理(情绪趋势 + 一键清除带 GitHub 删库式两步确认)。
// REST 基址由 VITE_WS_URL 换算(同 station.ts);全局 admin 操作无需 session_id,不必 bindStation。
// 状态为模块级响应式单例;确认门:confirmInput === CONFIRM_PHRASE 才真正调 clear。

import { reactive } from 'vue'
import { logger } from '../logger'

export type SettingsPhase = 'idle' | 'loading' | 'saved' | 'error'
export type LlmProvider = 'deepseek' | 'ollama'

export interface ProviderConfig {
  id: LlmProvider
  model: string
  base_url: string
}

interface ConfigGetBody {
  provider: LlmProvider
  api_key_set: boolean
  providers: ProviderConfig[]
}

interface TrendRow {
  date: string
  source: string
  mood_label: string
  intensity: number | null
}

export const CONFIRM_PHRASE = '清除记忆'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'
const REST_BASE = new URL(WS_URL.replace(/^ws/, 'http')).origin

export const settings = reactive({
  open: false,
  phase: 'idle' as SettingsPhase,
  provider: 'deepseek' as LlmProvider,
  model: '',
  baseUrl: '',
  apiKey: '',
  apiKeySet: false,
  providers: [] as ProviderConfig[],
  trends: [] as TrendRow[],
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
  void getConfig()
  void loadTrends()
}

export function closeSettings(): void {
  settings.open = false
  settings.confirmOpen = false
}

export async function getConfig(): Promise<void> {
  const { status, body } = await requestJson<ConfigGetBody>('/admin/config')
  if (status !== 200 || body === null) {
    settings.phase = 'error'
    settings.message = '读取模型配置失败,请确认后端已启动。'
    return
  }
  settings.provider = body.provider
  settings.apiKeySet = body.api_key_set
  settings.providers = body.providers
  const cur = body.providers.find((p) => p.id === body.provider)
  settings.model = cur?.model ?? ''
  settings.baseUrl = cur?.base_url ?? ''
}

export function switchProvider(id: LlmProvider): void {
  settings.provider = id
  const cur = settings.providers.find((p) => p.id === id)
  settings.model = cur?.model ?? ''
  settings.baseUrl = cur?.base_url ?? ''
  settings.apiKey = ''
}

export async function saveConfig(): Promise<void> {
  settings.phase = 'loading'
  const payload: { provider: LlmProvider; model: string; base_url: string; api_key?: string } = {
    provider: settings.provider,
    model: settings.model,
    base_url: settings.baseUrl,
  }
  if (settings.apiKey.trim() !== '') payload.api_key = settings.apiKey.trim()
  const { status, body } = await requestJson<{ ok?: boolean; detail?: string }>('/admin/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (status === 200) {
    settings.phase = 'saved'
    settings.message = '已保存并生效。'
    settings.apiKey = ''
    void getConfig() // 刷新 api_key_set / 预填
  } else {
    settings.phase = 'error'
    settings.message = body !== null && body.detail ? body.detail : errorDetail(body)
  }
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
  settings.provider = 'deepseek'
  settings.model = ''
  settings.baseUrl = ''
  settings.apiKey = ''
  settings.apiKeySet = false
  settings.providers = []
  settings.trends = []
  settings.message = ''
  settings.confirmOpen = false
  settings.confirmInput = ''
}
