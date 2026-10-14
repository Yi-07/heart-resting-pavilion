// station 控制器钉测试(契约 §1 轮次维度):
//   场景 A 按轮取稿(latest→404→generate→轮询→ready 进详情)、历史消息链接只请求
//   该消息自己的 round_id、stationReady=false 不发请求、409/503/失败回退旧稿；
//   场景 B 列表→点行→详情;重新生成只针对当前轮;导出文件名含轮次。
// fetch 全 stub;轮询用 fake timers 驱动;session_id 经真 WSClient+假 socket 学 done 帧。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  backToList,
  openStationRow,
  bindStation,
  closeStation,
  exportStationReport,
  openStationList,
  openStationRound,
  regenerateStation,
  resetStationForTest,
  station,
} from '../station'
import { WSClient, type WSLike } from '../../ws/client'

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

interface Call {
  url: string
  method: string
}

let calls: Call[] = []
let latestQueue: FakeRes[] = []
let listQueue: FakeRes[] = []
let generateStatus = 200
let generateBody: unknown = undefined

function stubFor(input: RequestInfo | URL, init?: RequestInit): FakeRes {
  const url = String(input)
  const method = init?.method ?? 'GET'
  calls.push({ url, method })
  if (url.includes('/station/report/generate')) {
    return new FakeRes(generateStatus, generateBody)
  }
  if (url.includes('/station/report/list')) {
    return listQueue.shift() ?? new FakeRes(200, { reports: [] })
  }
  if (url.includes('/station/report/latest')) {
    return latestQueue.shift() ?? new FakeRes(200, { status: 'pending' })
  }
  return new FakeRes(404)
}

function bindWith(sid: string | null): WSClient {
  const fake: WSLike = {
    send: () => {},
    close: () => {},
    onopen: null,
    onclose: null,
    onerror: null,
    onmessage: null,
  }
  const client = new WSClient('ws://test/', () => fake)
  void client.connect().catch(() => {})
  if (sid !== null) {
    fake.onmessage?.({ data: JSON.stringify({ type: 'done', session_id: sid, seq: 1 }) })
  }
  bindStation(() => client)
  return client
}

function roundOf(url: string): string | null {
  if (url === '') return null
  return new URL(url, 'http://localhost').searchParams.get('round_id')
}

function row(roundId: string, over: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    round_id: roundId,
    title: `第 ${roundId} 次梳理`,
    status: 'ready',
    created_at: '2026-10-12T16:40:00',
    expires_at: '2026-10-19T16:40:00',
    can_regenerate: 'yes',
    ...over,
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', stubFor)
  calls = []
  latestQueue = []
  listQueue = []
  generateStatus = 200
  generateBody = undefined
  resetStationForTest()
  bindWith('sess_a')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('station 控制器', () => {
  it('无会话:空态引导,不发请求', async () => {
    bindWith(null)
    openStationList()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.open).toBe(true)
    expect(station.view).toBe('list')
    expect(station.phase).toBe('empty')
    expect(station.message).toContain('聊几句')
    expect(calls).toHaveLength(0)
  })

  // ---- 场景 A:按轮取稿 ----

  it('场景 A:latest 404 → generate 受理 → 轮询 pending → ready 进详情', async () => {
    latestQueue = [
      new FakeRes(404),
      new FakeRes(200, { status: 'pending' }),
      new FakeRes(200, { status: 'ready', report_md: '# 心理成长方案\n\n稿' }),
    ]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.view).toBe('detail')
    expect(station.currentRoundId).toBe('3')
    expect(station.phase).toBe('pending')
    // 只请求第 3 轮(不猜、不带别的轮)
    expect(roundOf(calls[0]?.url ?? '')).toBe('3') // latest 只问第 3 轮
    expect(calls[1]?.url ?? '').toContain('/station/report/generate')
    expect(calls[1]?.method).toBe('POST')
    expect(roundOf(calls[1]?.url ?? '')).toBe('3')
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('pending') // 第一轮轮询:生成中
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toContain('# 心理成长方案')
    expect(roundOf(calls[2]?.url ?? '')).toBe('3') // 轮询也按轮
  })

  it('场景 A:该轮已有报告 → 直显不触发生成(同一轮内幂等)', async () => {
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 第3轮的稿' })]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toBe('# 第3轮的稿')
    expect(calls).toHaveLength(1) // 未打 generate
  })

  it('场景 A:未点亮 → 宽限重试(归档窗口),持续不可寻址才显式失败', async () => {
    // 邀请语文本先于 done 到达:点击时可能正在归档 → 给 3 次宽限,不要硬失败
    latestQueue = [new FakeRes(404), new FakeRes(404), new FakeRes(404)]
    generateStatus = 409
    generateBody = { detail: '这一轮还没有可整理的素材' }
    openStationRound('3', false)
    await vi.advanceTimersByTimeAsync(2000)
    expect(calls).toHaveLength(6) // 3 次 latest + 3 次 generate
    expect(station.phase).toBe('error')
    expect(station.message).toContain('还没存好')
  })

  it('场景 A:宽限期内素材就绪 → 直接出稿(不误报失败)', async () => {
    latestQueue = [new FakeRes(404), new FakeRes(200, { status: 'ready', report_md: '# 宽限后拿到' })]
    openStationRound('3', false)
    await vi.advanceTimersByTimeAsync(0) // 第 1 次:404 → generate 受理 → pending
    await vi.advanceTimersByTimeAsync(1600) // 轮询到第 2 条:ready
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toBe('# 宽限后拿到')
  })

  it('场景 A:roundId=null(非 collect 消息)→ 退回列表', async () => {
    listQueue = [new FakeRes(200, { reports: [] })]
    openStationRound(null, true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.view).toBe('list')
    expect(calls[0]?.url ?? '').toContain('/station/report/list')
  })

  it('generate 409 → 错误态(不给别轮报告)', async () => {
    latestQueue = [new FakeRes(404)]
    generateStatus = 409
    generateBody = { detail: '这一轮梳理已过有效期(归档后 7 天)。' }
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('error')
    expect(station.message).toContain('已过有效期')
    expect(station.reportMd).toBe('')
  })

  it('generate 503(素材状态不可确认)→ 错误态,不臆测可重新生成', async () => {
    latestQueue = [new FakeRes(404)]
    generateStatus = 503
    generateBody = { detail: '暂时无法确认' }
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('error')
    expect(station.message).toContain('无法确认')
  })

  it('轮询失败:无旧稿 → error 态', async () => {
    latestQueue = [new FakeRes(404), new FakeRes(500)]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('error')
    expect(station.message).toContain('走神')
  })

  // ---- 场景 B:列表 ----

  it('场景 B:列表渲染与点行进详情(带该行元信息)', async () => {
    listQueue = [
      new FakeRes(200, {
        reports: [row('3'), row('2', { can_regenerate: 'no' }), row('1', { status: 'pending' })],
      }),
    ]
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 第2轮稿' })]
    openStationList()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.view).toBe('list')
    expect(station.rows).toHaveLength(3)
    expect(station.rows[0]?.round_id).toBe('3')
    // 过期行也给看(can_regenerate=no → 不可重新生成)
    const expiredRow = station.rows[1]
    expect(expiredRow).toBeDefined()
    openStationRow(expiredRow!)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.view).toBe('detail')
    expect(station.currentRoundId).toBe('2')
    expect(roundOf(calls[1]?.url ?? '')).toBe('2')
    expect(station.currentMeta?.created_at).toBe('2026-10-12T16:40:00')
  })

  it('场景 B:列表读取失败 → error 态', async () => {
    listQueue = [new FakeRes(500)]
    openStationList()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('error')
    expect(station.message).toContain('列表')
  })

  it('返回列表:重新拉列表', async () => {
    listQueue = [new FakeRes(200, { reports: [] })]
    openStationList()
    await vi.advanceTimersByTimeAsync(0)
    calls = []
    listQueue = [new FakeRes(200, { reports: [row('1')] })]
    backToList()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.view).toBe('list')
    expect(station.rows).toHaveLength(1)
  })

  // ---- 重新生成:保留旧稿 ----

  it('重新生成:旧稿继续在,新稿成功后替换', async () => {
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 旧稿' })]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    latestQueue = [
      new FakeRes(200, { status: 'pending' }),
      new FakeRes(200, { status: 'ready', report_md: '# 新稿' }),
    ]
    regenerateStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.regenerating).toBe(true)
    expect(station.phase).toBe('pending')
    expect(station.reportMd).toBe('# 旧稿') // 旧稿不丢
    expect(roundOf(calls[1]?.url ?? '')).toBe('3') // 只针对当前轮
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('pending')
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toBe('# 新稿')
    expect(station.regenerating).toBe(false)
  })

  it('重新生成 409(素材过期):保留旧稿 + 明确提示', async () => {
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 旧稿' })]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    generateStatus = 409
    generateBody = { detail: '已过有效期' }
    regenerateStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('error')
    expect(station.reportMd).toBe('# 旧稿') // 旧稿仍可查看/导出
    expect(station.message).toContain('有效期')
    expect(station.regenerating).toBe(false)
  })

  it('重新生成失败(网络):保留旧稿 + 提示', async () => {
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 旧稿' })]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    generateStatus = 500
    regenerateStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('error')
    expect(station.reportMd).toBe('# 旧稿')
    expect(station.message).toContain('之前为你整理')
  })

  // ---- 标题取自报告数据,不用轮次序号 ----

  it('标题用 latest 回传的 title(情境 · 情绪),不显示「第 N 次疆球」', async () => {
    latestQueue = [new FakeRes(200, {
      status: 'ready',
      report_md: '# 心理成长方案',
      title: '考试没考好 · 焦虑',
      updated_at: '2026-10-14T21:27:05',
    })]
    openStationRound('2', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.currentTitle).toBe('考试没考好 · 焦虑')
    expect(station.currentTitle).not.toContain('第 ')
  })

  it('列表行标题展示情境/情绪(backfill 后的真实格式)', async () => {
    listQueue = [new FakeRes(200, {
      reports: [row('5', { title: '把对方拉黑了 · 愤怒' }), row('2', { title: '考试没考好 · 焦虑' })],
    })]
    openStationList()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.rows.map((r) => r.title)).toEqual([
      '把对方拉黑了 · 愤怒',
      '考试没考好 · 焦虑',
    ])
    expect(station.rows[0]?.title).not.toContain('第 ')
  })

  it('导出文件名用报告标题(含非法字符过滤)', async () => {
    latestQueue = [new FakeRes(200, {
      status: 'ready',
      report_md: '# 稿',
      title: '考试/没考好: 焦虑?',
      updated_at: '2026-10-14T21:27:05',
    })]
    openStationRound('2', true)
    await vi.advanceTimersByTimeAsync(0)
    const created: string[] = []
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag)
      if (tag === 'a') {
        const a = el as HTMLAnchorElement
        a.click = () => created.push(a.download)
      }
      return el
    })
    exportStationReport()
    expect(created[0]).toBe('心栖阁-考试 没考好  焦虑.md') // 「焦虑?」→「焦虑 」→ trim
    vi.restoreAllMocks()
  })

  it('重新生成成功后更新时间到位(updated_at)', async () => {
    latestQueue = [new FakeRes(200, {
      status: 'ready', report_md: '# 旧稿', title: '考试没考好', updated_at: '2026-10-14T21:23:05',
    })]
    openStationRound('2', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.currentMeta?.updated_at).toBe('2026-10-14T21:23:05')
    latestQueue = [new FakeRes(200, {
      status: 'ready', report_md: '# 新稿', title: '考试没考好', updated_at: '2026-10-14T21:27:05',
    })]
    regenerateStation()
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1600)
    expect(station.currentMeta?.updated_at).toBe('2026-10-14T21:27:05')
    expect(station.reportMd).toBe('# 新稿')
  })

  it('closeStation 停轮询', async () => {
    latestQueue = [new FakeRes(404)]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    closeStation()
    const before = calls.length
    await vi.advanceTimersByTimeAsync(6000)
    expect(calls).toHaveLength(before)
  })

  it('导出文件名:报告有标题就用标题,不回落轮次标识', async () => {
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 稿', title: '考试没考好 · 焦虑' })]
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.currentTitle).toBe('考试没考好 · 焦虑')
    const created: string[] = []
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag)
      if (tag === 'a') {
        const a = el as HTMLAnchorElement
        a.click = () => created.push(a.download)
      }
      return el
    })
    exportStationReport()
    expect(created).toEqual(['心栖阁-考试没考好 · 焦虑.md'])
    expect(created[0]).not.toContain('第 3 次梳理')
    vi.restoreAllMocks()
  })

  it('导出文件名:接口没给标题时才用轮次兜底', async () => {
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 稿' })] // 无 title 字段
    openStationRound('3', true)
    await vi.advanceTimersByTimeAsync(0)
    expect(station.currentTitle).toBe('') // 正式标题不回落轮次
    const created: string[] = []
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag)
      if (tag === 'a') {
        const a = el as HTMLAnchorElement
        a.click = () => created.push(a.download)
      }
      return el
    })
    exportStationReport()
    expect(created).toEqual(['心栖阁-第 3 次梳理.md'])
    vi.restoreAllMocks()
  })
})
