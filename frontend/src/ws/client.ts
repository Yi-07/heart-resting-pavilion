// ws/client.ts —— 连接/重连/seq 校验/消息分发(frontend-plan §4)。
// seq 校验单点在此:丢弃 seq≤已处理 的旧帧,下游收到即新帧;
// first_frame/error 无 seq 直通。断线重连内部处理,带原 session_id。
import { logger } from '../logger'
import type { CSMsg, WSMsg, WSMsgType } from './messages'

export class WSError extends Error {}

/** 测试可注入的最小 socket 形状(浏览器原生 WebSocket 满足同一接口) */
export interface WSLike {
  send(data: string): void
  close(): void
  onopen: (() => void) | null
  onclose: (() => void) | null
  onerror: (() => void) | null
  onmessage: ((ev: { data: unknown }) => void) | null
}

export type SocketFactory = (url: string) => WSLike

const RECONNECT_BACKOFF_MS = [1000, 2000, 5000]

const KNOWN_TYPES: ReadonlySet<WSMsgType> = new Set<WSMsgType>([
  'first_frame',
  'draw',
  'text_delta',
  'audio_chunk',
  'done',
  'error',
  'user_input',
  'mood_select',
])

export class WSClient {
  private socket: WSLike | null = null
  private handlers = new Map<WSMsgType, Set<(msg: WSMsg) => void>>()
  private lastSeq = 0
  private sessionId: string | null = null
  private connected = false
  private attempts = 0
  private manualClose = false

  constructor(
    private readonly url: string,
    private readonly socketFactory: SocketFactory = (u) => new WebSocket(u) as WSLike,
  ) {}

  get isConnected(): boolean {
    return this.connected
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      let settled = false
      const socket = this.socketFactory(this.url)
      this.socket = socket
      socket.onopen = () => {
        this.connected = true
        this.attempts = 0
        if (!settled) {
          settled = true
          resolve()
        }
      }
      socket.onclose = () => {
        this.connected = false
        if (!settled) {
          settled = true
          reject(new WSError(`连接失败: ${this.url}`))
          return
        }
        if (!this.manualClose) this.scheduleReconnect()
      }
      socket.onerror = () => {
        /* 错误后必有 close,统一在 onclose 处理 */
      }
      socket.onmessage = (ev) => this.handleMessage(String(ev.data))
    })
  }

  close(): void {
    this.manualClose = true
    this.socket?.close()
  }

  private scheduleReconnect(): void {
    const delay = RECONNECT_BACKOFF_MS[Math.min(this.attempts, RECONNECT_BACKOFF_MS.length - 1)]
    this.attempts += 1
    logger.warn('ws', `连接断开,${delay}ms 后第 ${this.attempts} 次重连`)
    setTimeout(() => {
      this.connect().catch(() => {
        /* 失败进入下一轮退避 */
      })
    }, delay)
  }

  on<M extends WSMsgType>(
    type: M,
    handler: (msg: Extract<WSMsg, { type: M }>) => void,
  ): () => void {
    const set = this.handlers.get(type) ?? new Set<(msg: WSMsg) => void>()
    const wrapped = handler as (msg: WSMsg) => void
    set.add(wrapped)
    this.handlers.set(type, set)
    return () => set.delete(wrapped)
  }

  send(msg: CSMsg): void {
    if (!this.connected || !this.socket) throw new WSError('未连接')
    const enriched =
      this.sessionId !== null && msg.session_id == null
        ? { ...msg, session_id: this.sessionId }
        : msg
    this.socket.send(JSON.stringify(enriched))
  }

  private handleMessage(raw: string): void {
    let msg: WSMsg
    try {
      msg = JSON.parse(raw) as WSMsg
    } catch {
      logger.warn('ws', `非 JSON 帧: len=${raw.length}`)
      return
    }
    if (!KNOWN_TYPES.has(msg.type)) {
      logger.warn('ws', `未知消息类型: ${String((msg as { type?: unknown }).type)}`)
      return
    }
    if ('seq' in msg && typeof msg.seq === 'number') {
      if (msg.seq <= this.lastSeq) {
        logger.debug('ws', `旧帧丢弃: seq=${msg.seq} ≤ ${this.lastSeq}`)
        return
      }
      this.lastSeq = msg.seq
    }
    if (msg.type === 'first_frame' || msg.type === 'done') {
      this.sessionId = msg.session_id
    }
    const set = this.handlers.get(msg.type)
    if (set === undefined) return
    // forEach:迭代中退订安全(跳过已删项)
    set.forEach((handler) => handler(msg))
  }
}
