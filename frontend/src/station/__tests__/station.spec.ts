// station 控制器钉测试:取稿链 latest→(404 则 generate)→轮询 pending→ready;
// 409 空态 / 已 ready 直显 / 请求失败 error 态 / 关闭即停轮询 / 重新整理。
// fetch 全 stub;轮询用 fake timers 驱动;session_id 经真 WSClient+假 socket 喂 done 帧学到。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  bindStation,
  closeStation,
  openStation,
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

let latestQueue: FakeRes[] = []
let generateStatus = 200
let latestCalls = 0
let generateCalls = 0

async function fetchStub(input: RequestInfo | URL): Promise<FakeRes> {
  const url = String(input)
  if (url.includes('/station/report/generate')) {
    generateCalls += 1
    return new FakeRes(generateStatus)
  }
  if (url.includes('/station/report/latest')) {
    latestCalls += 1
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

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', fetchStub)
  latestQueue = []
  generateStatus = 200
  latestCalls = 0
  generateCalls = 0
  resetStationForTest()
  bindWith(null)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('station 控制器', () => {
  it('session_id getter:done 帧学到,重连不变', () => {
    const client = bindWith('sess_getter')
    expect(client.sessionId).toBe('sess_getter')
  })

  it('无会话:空态引导,不发请求', async () => {
    openStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.open).toBe(true)
    expect(station.phase).toBe('empty')
    expect(station.message).toContain('聊几句')
    expect(latestCalls).toBe(0)
  })

  it('latest 404 → generate 受理 → 轮询 pending → ready', async () => {
    bindWith('sess_a')
    latestQueue = [
      new FakeRes(404),
      new FakeRes(200, { status: 'pending' }),
      new FakeRes(200, { status: 'ready', report_md: '# 心理成长方案\n\n稿' }),
    ]
    openStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('pending')
    expect(generateCalls).toBe(1)
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('pending') // 第一轮轮询:生成中
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toContain('# 心理成长方案')
  })

  it('generate 409 → 空态话术', async () => {
    bindWith('sess_b')
    latestQueue = [new FakeRes(404)]
    generateStatus = 409
    openStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('empty')
    expect(station.message).toContain('素材')
  })

  it('latest 已 ready → 直显不触发 generate', async () => {
    bindWith('sess_c')
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 旧稿' })]
    openStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toBe('# 旧稿')
    expect(generateCalls).toBe(0)
  })

  it('请求失败 → error 态温和话术', async () => {
    bindWith('sess_d')
    latestQueue = [new FakeRes(500)]
    openStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('error')
    expect(station.message).toContain('顺畅')
  })

  it('closeStation 停轮询', async () => {
    bindWith('sess_e')
    latestQueue = [new FakeRes(404)]
    openStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('pending')
    const before = latestCalls
    closeStation()
    expect(station.open).toBe(false)
    await vi.advanceTimersByTimeAsync(6000)
    expect(latestCalls).toBe(before) // 无新轮询
  })

  it('regenerateStation:强制再生成,最新胜覆盖旧稿', async () => {
    bindWith('sess_f')
    latestQueue = [new FakeRes(200, { status: 'ready', report_md: '# 新稿' })]
    station.phase = 'ready'
    station.reportMd = '# 旧稿'
    regenerateStation()
    await vi.advanceTimersByTimeAsync(0)
    expect(station.phase).toBe('pending')
    expect(generateCalls).toBe(1)
    await vi.advanceTimersByTimeAsync(1500)
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toBe('# 新稿')
  })
})
