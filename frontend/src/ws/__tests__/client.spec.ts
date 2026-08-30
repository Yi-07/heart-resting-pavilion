// ws/client 接缝钉测试(frontend-plan §8):seq 校验单点、分发与退订、
// 未连接发送、session_id 回填、断线重连。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WSClient, WSError, type WSLike } from '../client'
import type { S2CMsg } from '../messages'

class FakeSocket implements WSLike {
  sent: string[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((ev: { data: unknown }) => void) | null = null

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.onclose?.()
  }

  // 模拟服务端推帧
  push(msg: S2CMsg): void {
    this.onmessage?.({ data: JSON.stringify(msg) })
  }
}

function makeClient(): { client: WSClient; sockets: FakeSocket[] } {
  const sockets: FakeSocket[] = []
  const client = new WSClient('ws://test/ws', () => {
    const s = new FakeSocket()
    sockets.push(s)
    return s
  })
  return { client, sockets }
}

function socketAt(sockets: FakeSocket[], i: number): FakeSocket {
  const s = sockets[i]
  if (s === undefined) throw new Error(`sockets[${i}] 未创建`)
  return s
}

async function open(client: WSClient, sockets: FakeSocket[]): Promise<void> {
  const pending = client.connect() // factory 同步创建 socket
  socketAt(sockets, sockets.length - 1).onopen?.()
  await pending
}

describe('WSClient', () => {
  it('seq 单点校验:丢弃 seq≤已处理 的旧帧,无 seq 帧直通', async () => {
    const { client, sockets } = makeClient()
    const draws: number[] = []
    const passthrough: string[] = []
    client.on('draw', (m) => draws.push(m.seq))
    client.on('first_frame', () => passthrough.push('first_frame'))
    client.on('error', () => passthrough.push('error'))
    await open(client, sockets)

    const s = socketAt(sockets, 0)
    s.push({ type: 'draw', seq: 1, template: 'stage_map', data: { nodes: ['a'], current: 0, from: 'x' } })
    s.push({ type: 'draw', seq: 1, template: 'stage_map', data: { nodes: ['a'], current: 0, from: 'x' } }) // 旧帧,丢
    s.push({ type: 'error', code: 'timeout', message: 'x' }) // 无 seq,直通
    s.push({ type: 'first_frame', session_id: 's1', route: 'collect', template: 'beck_formulation', emotion_label: null, mood_select: true, text: '嗯' })
    s.push({ type: 'draw', seq: 2, template: 'stage_map', data: { nodes: ['a'], current: 0, from: 'x' } })

    expect(draws).toEqual([1, 2])
    expect(passthrough).toEqual(['error', 'first_frame'])
  })

  it('on 返回退订函数,卸载后不再收到', async () => {
    const { client, sockets } = makeClient()
    const seen: string[] = []
    const off = client.on('text_delta', (m) => seen.push(m.text))
    await open(client, sockets)

    const s = socketAt(sockets, 0)
    s.push({ type: 'text_delta', seq: 1, text: 'a', final: false })
    off()
    s.push({ type: 'text_delta', seq: 2, text: 'b', final: false })
    expect(seen).toEqual(['a'])
  })

  it('未连接时 send 抛 WSError', () => {
    const { client } = makeClient()
    expect(() =>
      client.send({ type: 'user_input', mode: 'text', text: 'hi', audio: null, ts: 1 }),
    ).toThrow(WSError)
  })

  it('session_id 回填:learn 后随 C→S 消息携带', async () => {
    const { client, sockets } = makeClient()
    await open(client, sockets)
    socketAt(sockets, 0).push({
      type: 'first_frame', session_id: 'sess_x', route: 'crisis',
      template: null, emotion_label: null, mood_select: false, text: '嗯',
    })

    client.send({ type: 'user_input', mode: 'text', text: 'hi', audio: null, ts: 2 })
    const sent = JSON.parse(socketAt(sockets, 0).sent[0] as string) as { session_id?: string }
    expect(sent.session_id).toBe('sess_x')
  })

  describe('断线重连', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('断开后按退避重连,成功后清零计数', async () => {
      const { client, sockets } = makeClient()
      await open(client, sockets)

      socketAt(sockets, 0).onclose?.() // 意外断开
      expect(client.isConnected).toBe(false)

      await vi.advanceTimersByTimeAsync(1000) // 第 1 次退避到期 → 新 socket
      socketAt(sockets, 1).onopen?.() // 重连 socket 打开
      expect(client.isConnected).toBe(true)

      socketAt(sockets, 1).onclose?.() // 再断 → attempts 已清零,仍从 1000ms 起
      await vi.advanceTimersByTimeAsync(999)
      expect(sockets.length).toBe(2)
      await vi.advanceTimersByTimeAsync(1)
      expect(sockets.length).toBe(3)
    })

    it('close() 主动关闭不触发重连', async () => {
      const { client, sockets } = makeClient()
      await open(client, sockets)
      client.close()
      await vi.advanceTimersByTimeAsync(10000)
      expect(sockets.length).toBe(1)
    })
  })
})
