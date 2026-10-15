// admin settings 控制器钉测试:clearMemory 确认门(未输短语不发请求,高危防护)·
// 输入短语才 POST 并清空 trends · loadMemories/deleteMemory 记忆列表闭环。
// 旧 /admin/config 双源口已随 T4 清理,getConfig/saveConfig 用例随之移除。fetch 全 stub。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  settings,
  clearMemory,
  loadMemories,
  deleteMemory,
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

// 记录每次 fetch 的 url/method/body,供断言请求侧
let requests: { url: string; init?: RequestInit }[] = []

async function fetchStub(input: RequestInfo | URL, init?: RequestInit): Promise<FakeRes> {
  requests.push({ url: String(input), init })
  const url = String(input)
  if (url.includes('/admin/clear_memory')) {
    return new FakeRes(200, { ok: true, redis_keys: 2, mood_rows: 3, reports: 1 })
  }
  if (url.includes('/admin/trends')) {
    return new FakeRes(200, {
      moods: [{ date: '2026-09-05', source: 'mood_select', mood_label: '低落', intensity: null }],
    })
  }
  if (url.includes('/admin/memories/')) {
    return new FakeRes(200, { ok: true })
  }
  if (url.includes('/admin/memories')) {
    return new FakeRes(200, {
      items: [
        { id: 'm1', text: '聊到工作压力', status: 'open', date: '2026-10-10' },
        { id: 'm2', text: '和室友和好了', status: 'settled', date: '2026-10-11' },
      ],
    })
  }
  return new FakeRes(404)
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

  it('loadMemories:拉取列表进 settings.memories', async () => {
    await loadMemories()
    expect(settings.memories).toHaveLength(2)
    expect(settings.memories[0]?.id).toBe('m1')
  })

  it('deleteMemory:DELETE 成功后本地摘除该条', async () => {
    await loadMemories()
    await deleteMemory('m1')
    const del = requests.find((r) => r.url.includes('/admin/memories/m1'))
    expect(del?.init?.method).toBe('DELETE')
    expect(settings.memories.map((m) => m.id)).toEqual(['m2'])
  })
})
