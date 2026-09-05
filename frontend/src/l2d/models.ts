// l2d/models.ts —— 立绘模型目录与选用(内置几尊+用户可换):
// 目录单源=public/vendor/live2d/models.json(npm run l2d:fetch 生成,授权限制不入库);
// 自定义=往 vendor/models/<id>/ 丢一整套 Cubism4 模型并在 models.json 加一条。
// vendor 未生成(新克隆没跑脚本)→ 兜底目录走 CDN,保底有立绘。

import { logger } from '../logger'

export interface ModelEntry {
  id: string
  label: string
  file: string
  /** 上游 CDN 绝对地址;本地缺文件时回退 */
  source?: string
  default?: boolean
}

const VENDOR = '/vendor/live2d'

/** 兜底条目:vendor 缺席时保底(与 fetch 脚本默认模型同源) */
export const DEFAULT_ENTRY: ModelEntry = {
  id: 'haru',
  label: '小春',
  file: 'haru_greeter_t03.model3.json',
  default: true,
  source:
    'https://fastly.jsdelivr.net/gh/guansss/pixi-live2d-display@master/test/assets/haru/haru_greeter_t03.model3.json',
}

const FALLBACK_CATALOG: ModelEntry[] = [DEFAULT_ENTRY]
const SELECTED_KEY = 'hrp:l2d:model'

let catalog: ModelEntry[] | null = null

export async function loadCatalog(): Promise<ModelEntry[]> {
  if (catalog !== null) return catalog
  try {
    const res = await fetch(`${VENDOR}/models.json`)
    if (!res.ok) throw new Error(`models.json ${res.status}`)
    const list = (await res.json()) as ModelEntry[]
    catalog = list.length > 0 ? list : FALLBACK_CATALOG
  } catch {
    logger.warn('l2d', 'vendor 目录不可用(未跑 l2d:fetch?),兜底目录走 CDN')
    catalog = FALLBACK_CATALOG
  }
  return catalog
}

export function loadSelection(list: ModelEntry[]): ModelEntry {
  const saved = localStorage.getItem(SELECTED_KEY)
  const found = list.find((m) => m.id === saved)
  if (found !== undefined) return found
  return list.find((m) => m.default === true) ?? list[0] ?? DEFAULT_ENTRY
}

export function persistSelection(id: string): void {
  localStorage.setItem(SELECTED_KEY, id)
}

/** 轮换下一尊(到尾回卷;目录单条=自转) */
export function nextModel(list: ModelEntry[], currentId: string): ModelEntry {
  if (list.length === 0) return DEFAULT_ENTRY
  const i = list.findIndex((m) => m.id === currentId)
  const next = list[(i + 1 + list.length) % list.length]
  return next ?? list[0] ?? DEFAULT_ENTRY
}

/** 载入候选地址:本地 vendor 优先 → 上游 CDN 回退 */
export function modelUrls(entry: ModelEntry): string[] {
  const urls = [`${VENDOR}/models/${entry.id}/${entry.file}`]
  if (entry.source !== undefined) urls.push(entry.source)
  return urls
}

/** 测试口:清目录缓存 */
export function resetCatalogForTest(): void {
  catalog = null
}
