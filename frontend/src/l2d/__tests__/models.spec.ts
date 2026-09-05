// l2d/models 钉测试:目录单源/兜底目录/选中持久化/轮换回卷/载入候选(本地优先+CDN 回退)。
import { beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_ENTRY,
  loadSelection,
  modelUrls,
  nextModel,
  resetCatalogForTest,
  type ModelEntry,
} from '../models'

const LIST: ModelEntry[] = [
  { id: 'haru', label: '小春', file: 'a.model3.json', default: true, source: 'https://x/a' },
  { id: 'hiyori', label: '日和', file: 'b.model3.json', source: 'https://x/b' },
  { id: 'mao', label: '真樱', file: 'c.model3.json' },
]

beforeEach(() => {
  localStorage.clear()
  resetCatalogForTest()
})

describe('loadSelection / persistSelection', () => {
  it('无存储:回默认(default 首位)', () => {
    expect(loadSelection(LIST).id).toBe('haru')
  })

  it('有存储:取当前项;存了不存在 id 回默认', () => {
    localStorage.setItem('hrp:l2d:model', 'hiyori')
    expect(loadSelection(LIST).id).toBe('hiyori')
    localStorage.setItem('hrp:l2d:model', 'ghost')
    expect(loadSelection(LIST).id).toBe('haru')
  })

  it('全无 default:取列表首;空列表:兜底默认', () => {
    const noDefault = LIST.slice(1)
    expect(loadSelection(noDefault).id).toBe('hiyori')
    expect(loadSelection([])).toBe(DEFAULT_ENTRY)
  })
})

describe('nextModel 轮换', () => {
  it('正向轮换,尾回卷到首', () => {
    expect(nextModel(LIST, 'haru').id).toBe('hiyori')
    expect(nextModel(LIST, 'hiyori').id).toBe('mao')
    expect(nextModel(LIST, 'mao').id).toBe('haru')
  })

  it('单条与空目录', () => {
    const haru = LIST[0]
    expect(haru).toBeDefined()
    expect(nextModel([haru as ModelEntry], 'haru')).toStrictEqual(LIST[0])
    expect(nextModel([], 'haru')).toBe(DEFAULT_ENTRY)
  })
})

describe('modelUrls 载入候选', () => {
  it('本地 vendor 优先 + 有 source 则追加 CDN 回退', () => {
    const hiyori = LIST[1]
    const mao = LIST[2]
    expect(hiyori).toBeDefined()
    expect(mao).toBeDefined()
    expect(modelUrls(hiyori as ModelEntry)).toEqual([
      '/vendor/live2d/models/hiyori/b.model3.json',
      'https://x/b',
    ])
    expect(modelUrls(mao as ModelEntry)).toEqual(['/vendor/live2d/models/mao/c.model3.json'])
  })

  it('默认条目始终含 CDN 兜底', () => {
    expect(modelUrls(DEFAULT_ENTRY).length).toBe(2)
  })
})
