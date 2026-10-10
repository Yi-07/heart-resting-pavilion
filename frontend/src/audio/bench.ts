// 前端 benchmark 埋点(plan §25/§26/§27)。
//
// 与 backend/app/voice/tts_bench.py、TTS 服务的 bench.py 共用**同一套事件名**。
// 浏览器侧的 AudioBuffer.sampleRate / AudioContext.sampleRate 只存在于前端,
// 只能从这里上报,所以这一层不是可选的。
//
// 落盘路径由后端代劳(浏览器写不进本地文件):攒批 POST 到 /v1/tts/bench/events,
// 后端原样追加进同一个 JSONL,聚合脚本不用特判来源。
//
// 默认关闭:TTS_BENCH=1(或后端开了 TTS_BENCH 且带了 bench 标记)才上报。
// 关闭时 mark() 是一次布尔判空。

const FLUSH_INTERVAL_MS = 500
const MAX_BATCH = 200

export interface BenchEvent {
  ts_ms: number
  ev: string
  round_id?: string
  [k: string]: string | number | boolean | undefined
}

// 与后端 bench.py 逐字一致的冻结事件名
export const T7 = 'T7_frontend_flush'
export const P8 = 'P8_frontend_enqueue'
export const FIRST_SOURCE_SCHEDULED = 'first_source_scheduled'
export const PLAYBACK_TIMELINE = 'playback_timeline'
export const CHUNK = 'chunk_audio_metrics'
export const AUDIOCONTEXT_RATE = 'audio_context_sample_rate'
export const AUDIOBUFFER_RATE = 'audio_buffer_sample_rate'
export const BUFFER_DEPTH = 'playback_buffer_depth'
export const PROTOCOL_MISMATCH = 'protocol_mismatch'
export const STALE_FRAME_DROP = 'stale_frame_drop'

let queue: BenchEvent[] = []
let enabled = false
let timer: number | null = null
let endpoint = '/v1/tts/bench/events'

export function configureBench(opts: { enabled?: boolean; endpoint?: string }): void {
  if (opts.endpoint !== undefined) endpoint = opts.endpoint
  if (opts.enabled !== undefined) {
    enabled = opts.enabled
    if (enabled && timer === null) {
      timer = window.setInterval(flush, FLUSH_INTERVAL_MS)
    }
    if (!enabled && timer !== null) {
      window.clearInterval(timer)
      timer = null
      queue = []
    }
  }
}

/** mark():关着时是一次布尔判空,播放热路径零开销。 */
export function mark(ev: string, fields?: Omit<BenchEvent, 'ev' | 'ts_ms'>): void {
  if (!enabled) return
  queue.push({ ts_ms: Date.now(), ev, ...fields })
  if (queue.length >= MAX_BATCH) flush()
}

export function flush(): void {
  if (queue.length === 0) return
  const batch = queue
  queue = []
  // sendBeacon:页面关闭/抢占瞬间也能把已攒的量送出去;fetch 不保活
  const body = JSON.stringify(batch)
  if (navigator.sendBeacon !== undefined) {
    const ok = navigator.sendBeacon(
      endpoint,
      new Blob([body], { type: 'application/json' }),
    )
    if (ok) return
  }
  void fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => {
    // 埋点失败不影响播放,静默
  })
}

/** 命名空间:事件名与 mark 绑在一起,避免调用点到处裸字符串(拼错只能编译期发现) */
export const bench = {
  mark,
  flush,
  configureBench,
  T7,
  P8,
  FIRST_SOURCE_SCHEDULED,
  PLAYBACK_TIMELINE,
  CHUNK,
  AUDIOCONTEXT_RATE,
  AUDIOBUFFER_RATE,
  BUFFER_DEPTH,
  PROTOCOL_MISMATCH,
  STALE_FRAME_DROP,
}