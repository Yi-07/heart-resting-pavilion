// admin settings 控制器钉测试:getConfig 预填 / saveConfig 只发已填字段(api_key 空不送)/
// clearMemory 确认门(未输短语不发请求,高危防护)· 输入短语才 POST 并清空 trends。fetch 全 stub。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  settings,
  getConfig,
  saveConfig,
  clearMemory,
  resetSettingsForTest,
  CONFIRM_PHRASE,
  confirmMatches,
} from '../settings'

class FakeRes {
  constructor(
    readonly status: number,
    private readonly body?: unknown,
  ) {}
  get ok(): boolean {
    return this.status >= 200 && this.status < 300
  }
  async json(): Promise<unknown> {
    return this.body
  }
}

const CONFIG_BODY = {
  provider: 'deepseek',
  api_key_set: true,
  providers: [
    { id: 'deepseek', model: 'm1', base_url: 'https://api.deepseek.com' },
    { id: 'ollama', model: 'qwen3:8b', base_url: 'http://localhost:11434/v1' },
  ],
}

// 记录每次 fetch 的 url/method/body,供断言请求侧
let requests: { url: string; init?: RequestInit }[] = []

async function fetchStub(input: RequestInfo | URL, init?: RequestInit): Promise<FakeRes> {
  requests.push({ url: String(input), init })
  const url = String(input)
  if (url.includes('/admin/clear_memory')) {
    return new FakeRes(200, { ok: true, redis_keys: 2, mood_rows: 3, reports: 1 })
  }
  if (url.includes('/admin/config')) {
    return init?.method === 'POST'
      ? new FakeRes(200, { ok: true, provider: 'deepseek', model: 'm1' })
      : new FakeRes(200, CONFIG_BODY)
  }
  if (url.includes('/admin/trends')) {
    return new FakeRes(200, {
      moods: [{ date: '2026-09-05', source: 'mood_select', mood_label: '低落', intensity: null }],
    })
  }
  return new FakeRes(404)
}

function sentBody(post: { init?: RequestInit } | undefined): Record<string, unknown> {
  return JSON.parse(String(post?.init?.body)) as Record<string, unknown>
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchStub)
  requests = []
  resetSettingsForTest()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('admin settings 控制器', () => {
  it('getConfig:预填 active provider 的 model/baseUrl + api_key_set', async () => {
    await getConfig()
    expect(settings.provider).toBe('deepseek')
    expect(settings.model).toBe('m1')
    expect(settings.baseUrl).toBe('https://api.deepseek.com')
    expect(settings.apiKeySet).toBe(true)
  })

  it('saveConfig:仅发已填字段,apiKey 空则不带 api_key', async () => {
    settings.provider = 'ollama'
    settings.model = 'qwen3:8b'
    settings.baseUrl = 'http://localhost:11434/v1'
    settings.apiKey = ''
    await saveConfig()
    const post = requests.find((r) => r.url.includes('/admin/config') && r.init?.method === 'POST')
    expect(post).toBeTruthy()
    const sent = sentBody(post)
    expect(sent.provider).toBe('ollama')
    expect(sent.api_key).toBeUndefined()
    expect(settings.phase).toBe('saved')
  })

  it('saveConfig:apiKey 非空则提交 api_key', async () => {
    settings.apiKey = 'sk-plain'
    await saveConfig()
    const post = requests.find((r) => r.url.includes('/admin/config') && r.init?.method === 'POST')
    expect(sentBody(post).api_key).toBe('sk-plain')
  })

  it('confirmMatches:输入须等于 CONFIRM_PHRASE', () => {
    expect(confirmMatches(CONFIRM_PHRASE)).toBe(true)
    expect(confirmMatches('别的')).toBe(false)
  })

  it('clearMemory:未输入确认短语不发请求(高危防护)', async () => {
    settings.confirmInput = '不是短语'
    await clearMemory()
    expect(requests.filter((r) => r.url.includes('/admin/clear_memory'))).toHaveLength(0)
    expect(settings.phase).toBe('error')
  })

  it('clearMemory:输入确认短语才 POST,并清空 trends', async () => {
    settings.confirmInput = CONFIRM_PHRASE
    settings.trends = [
      { date: '2026-09-05', source: 'mood_select', mood_label: '低落', intensity: null },
    ]
    await clearMemory()
    const post = requests.find((r) => r.url.includes('/admin/clear_memory'))
    expect(post?.init?.method).toBe('POST')
    expect(settings.trends).toHaveLength(0)
    expect(settings.message).toBe('记忆已清除。')
    expect(settings.phase).toBe('saved')
  })
})
