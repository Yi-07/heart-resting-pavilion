// voice/asr.ts —— 语音转写预览(ADR-004;端点单源=ws-contract §1 语音转写通道):
// 录音 blob → REST /asr/transcribe → 文本,调用方回填文本框。
// 成功(含空串="没听到")返回 string;4xx/5xx/网络异常返回 null(调用方提示转打字)。
// 与对话 WS 解耦:断线时录音回填仍可用,发送才依赖 WS。

import { logger } from '../logger'

const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'
/** REST 基址由 WS 地址换算(ws→http),单环境变量双用(同 station.ts) */
const REST_BASE = new URL(WS_URL.replace(/^ws/, 'http')).origin

function blobToBase64(blob: Blob): Promise<string> {
  return blob.arrayBuffer().then(arrayBufferToBase64)
}

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let binary = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return btoa(binary)
}

/** 转写一段录音;网络/服务端失败返 null,转写成功返文本(可能为空串) */
export async function transcribeAudio(blob: Blob): Promise<string | null> {
  const audio = await blobToBase64(blob)
  try {
    const res = await fetch(`${REST_BASE}/asr/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audio }),
    })
    if (!res.ok) {
      logger.warn('asr', `转写失败: HTTP ${res.status}`)
      return null
    }
    return ((await res.json()) as { text: string }).text
  } catch (err) {
    logger.warn('asr', `转写请求异常: ${String(err)}`)
    return null
  }
}

/** 追加式回填(ADR-004):draft 空=直接填入;非空=追加,末尾非标点/空白补逗号衔接 */
export function appendDraft(current: string, text: string): string {
  const trimmed = current.trimEnd()
  if (trimmed === '') return text
  const last = trimmed.slice(-1)
  const punctuated = /[。,、;:!?!?…~"'”』】)]|\s/.test(last)
  return trimmed + (punctuated ? '' : ',') + text
}
