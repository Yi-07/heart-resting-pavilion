// 契约对齐接缝:抽 ws-contract §5.1 字段名与 messages.ts 比对,防两端漂移(frontend-plan §8)。
// *_KEYS 为接口的运行时镜像,satisfies 保证与接口字段同步——多/少键编译期即报。
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type {
  Emotion,
  EmotionWheelData,
  EmotionWheelDatum,
  Formulation,
  StageMapData,
} from '../messages'

// vitest 里 import.meta.url 被 vite 改写,走 cwd(测试恒从 frontend/ 跑)定位仓库根。
// 契约在 docs/architecture/ 下(cba6fa3 文档树迁移后;此前在 architecture/,
// 这次迁移漏改了本文件的路径,于是测试一直在 ENOENT —— 与其改测试去迁就旧路径,
// 不如让它指向契约的真位置,这样它才是真的在比对契约)
const CONTRACT_PATH = resolve(process.cwd(), '..', 'docs', 'architecture', 'ws-contract.md')

const FORMULATION_KEYS = {
  situation: true,
  emotion: true,
  thought: true,
  behavior: true,
  intermediate_belief: true,
  core_belief: true,
} as const satisfies Record<keyof Formulation, true>

const EMOTION_KEYS = {
  label: true,
  intensity: true,
} as const satisfies Record<keyof Emotion, true>

const WHEEL_KEYS = {
  emotions: true,
  label: true,
  intensity: true,
  color: true,
} as const satisfies Record<keyof EmotionWheelData | keyof EmotionWheelDatum, true>

const STAGE_MAP_KEYS = {
  nodes: true,
  current: true,
  from: true,
} as const satisfies Record<keyof StageMapData, true>

function contractText(): string {
  return readFileSync(CONTRACT_PATH, 'utf-8')
}

function section51Json(): Record<string, unknown> {
  // s=跨行(标题与代码块间有空行);\r?:node readFile 不做换行转换,仓库文件为 CRLF
  const block = contractText().match(/### 5\.1.*?```json\r?\n([\s\S]*?)```/s)?.[1]
  if (block === undefined) throw new Error('ws-contract §5.1 formulation JSON 块缺失')
  return JSON.parse(block) as Record<string, unknown>
}

function templateBullets(): Record<string, string> {
  const section = contractText().match(/\*\*测试模板 data\*\*：([\s\S]*?)### 5\.2/)?.[1]
  if (section === undefined) throw new Error('ws-contract §5.1 测试模板 bullet 缺失')
  const bullets: Record<string, string> = {}
  for (const group of section.matchAll(/`(\w+)`：`([^`]+)`/g)) {
    const name = group[1]
    const body = group[2]
    if (name !== undefined && body !== undefined) bullets[name] = body
  }
  return bullets
}

function bodyKeys(body: string): string[] {
  const keys: string[] = []
  for (const group of body.matchAll(/([A-Za-z_][A-Za-z0-9_]*)\s*:/g)) {
    const key = group[1]
    if (key !== undefined) keys.push(key)
  }
  return keys
}

function sortedKeys(keys: Record<string, boolean>): string[] {
  return Object.keys(keys).sort()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

describe('契约对齐:ws-contract §5.1 ↔ messages.ts', () => {
  it('Formulation 字段名与契约一致', () => {
    expect(Object.keys(section51Json()).sort()).toEqual(sortedKeys(FORMULATION_KEYS))
  })

  it('Emotion 子对象字段名与契约一致', () => {
    const emotion = section51Json().emotion
    if (!isRecord(emotion)) throw new Error('契约 §5.1 emotion 子对象缺失')
    expect(Object.keys(emotion).sort()).toEqual(sortedKeys(EMOTION_KEYS))
  })

  it('emotion_wheel 测试模板字段名与契约一致', () => {
    const bullets = templateBullets()
    expect(bodyKeys(bullets.emotion_wheel ?? '').sort()).toEqual(sortedKeys(WHEEL_KEYS))
  })

  it('stage_map 测试模板字段名与契约一致', () => {
    const bullets = templateBullets()
    expect(bodyKeys(bullets.stage_map ?? '').sort()).toEqual(sortedKeys(STAGE_MAP_KEYS))
  })
})
