// ws/client.ts —— 连接/重连/seq 校验/消息分发(frontend-plan §4)。
// seq 校验单点在此:丢弃 seq≤已处理 的旧帧,下游收到即新帧;
// first_frame/error 无 seq 直通。断线/首连失败都续排退避重连,带原 session_id。
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

const SESSION_KEY = 'hrp.session'
/** 身份持久化(ADR-005):刷新后仍记得 session_id,重连带原 id → 后端认领+回放。
 * 治理联动:clear_memory 由 settings.ts 先清此键再调端点(共用电脑暴露面闭环)。 */
export function loadPersistedSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY)
  } catch {
    return null // 隐私模式等 localStorage 不可用:退化为不断线场景的内存身份
  }
}

export function clearPersistedSession(): void {
  try {
    localStorage.removeItem(SESSION_KEY)
  } catch {
    /* 同上,降级无副作用 */
  }
}

const KNOWN_TYPES: ReadonlySet<WSMsgType> = new Set<WSMsgType>([
  'first_frame',
  'draw',
  'text_delta',
  'audio_chunk',
  'done',
  'replay',
  'wall_reply',
  'error',
  'user_input',
  'mood_select',
])

export class WSClient {
  private socket: WSLike | null = null
  private handlers = new Map<WSMsgType, Set<(msg: WSMsg) => void>>()
  private lastSeq = 0
  private _sessionId: string | null = null
  private connected = false
  private attempts = 0
  private manualClose = false
  /** 重连回调(App 挂断线提示;null=不关心) */
  onReconnecting: ((attempt: number) => void) | null = null
  /** 重连成功回调(撤提示) */
  onReconnected: (() => void) | null = null

  constructor(
    private readonly url: string,
    private readonly socketFactory: SocketFactory = (u) => new WebSocket(u) as WSLike,
  ) {}

  get isConnected(): boolean {
    return this.connected
  }

  /** 当前会话 id(补给站 REST 等模块读;first_frame/done 学到,重连不变) */
  get sessionId(): string | null {
    return this._sessionId
  }

  /** 恢复持久化身份(ADR-005:App 装配时从 localStorage 注入;仅内存,学习后覆写) */
  restoreSession(sessionId: string): void {
    if (this._sessionId === null) this._sessionId = sessionId
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
        }
        // 首连/重连失败同样续排退避——否则一次失败即弃疗,后端恢复也不再重试
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
    this.onReconnecting?.(this.attempts)
    setTimeout(() => {
      this.connect()
        .then(() => {
          this.onReconnected?.()
        })
        .catch(() => {
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
      this._sessionId !== null && msg.session_id == null
        ? { ...msg, session_id: this._sessionId }
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
      this._sessionId = msg.session_id
      // ADR-005:身份持久化(learn 即存,刷新/重开浏览器仍能认领回放)
      try {
        localStorage.setItem(SESSION_KEY, this._sessionId)
      } catch {
        /* 不可用即退化,无副作用 */
      }
    }
    if (msg.type === 'replay') {
      // 回放帧带回认领后的会话身份(ADR-005;先于 first_frame 到达)
      this._sessionId = msg.session_id
    }
    const set = this.handlers.get(msg.type)
    if (set === undefined) return
    // forEach:迭代中退订安全(跳过已删项)
    set.forEach((handler) => handler(msg))
  }
}
