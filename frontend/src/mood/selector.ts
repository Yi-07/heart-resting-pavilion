// 心情选择器(frontend-plan §4):show/hide + onSelect(send mood_select 并手点写情绪)。
// 10s 超时自动收起回工具栏 pill(pill 可点击再开);计时进度写 store.moodElapsed 供 conic 环。

import type { MoodKey, MoodSelect } from '../ws/messages'
import type { useRoundStore } from '../state/round'
import { logger } from '../logger'

export const MOOD_TIMEOUT_MS = 10_000

export interface MoodOption {
  key: MoodKey
  color: string
  /** 嘴形 path(24×24 视窗,难过→很好渐变) */
  mouth: string
}

/** 六档心情单源(颜色源自 v7 mood faces) */
export const MOODS: readonly MoodOption[] = [
  { key: '难过', color: '#C9806B', mouth: 'M8 16 Q12 12 16 16' },
  { key: '低落', color: '#9A9A9A', mouth: 'M8 15.5 Q12 12.5 16 15.5' },
  { key: '平静', color: '#7E9A79', mouth: 'M8 15 H16' },
  { key: '还好', color: '#7A9EC7', mouth: 'M8 14.5 Q12 17 16 14.5' },
  { key: '开心', color: '#A88BC4', mouth: 'M8 14 Q12 17.5 16 14' },
  { key: '很好', color: '#C8A24C', mouth: 'M7.5 13.5 Q12 18 16.5 13.5' },
]

export interface MoodDeps {
  round: ReturnType<typeof useRoundStore>
  send: (msg: MoodSelect) => void
}

export class MoodSelector {
  private timeout = 0
  private ticker = 0

  constructor(private readonly deps: MoodDeps) {}

  show(): void {
    this.hideTimers()
    this.deps.round.moodVisible = true
    // B2 排查:浮层为瞬态(10s 自动收起),现场区分「未触发」与「已收起」
    logger.debug('mood', '浮层显示(10s 自动收起)')
    this.deps.round.moodElapsed = 0
    const startedAt = Date.now()
    this.ticker = window.setInterval(() => {
      this.deps.round.moodElapsed = Math.min(1, (Date.now() - startedAt) / MOOD_TIMEOUT_MS)
    }, 100)
    this.timeout = window.setTimeout(() => this.hide(), MOOD_TIMEOUT_MS)
  }

  hide(): void {
    this.hideTimers()
    this.deps.round.moodVisible = false
    logger.debug('mood', '浮层收起')
  }

  /** 选中:上报 mood_select + 手点写情绪(锁住后续 draw 覆盖)+ 收起 */
  select(mood: MoodKey): void {
    this.deps.send({ type: 'mood_select', mood, ts: Math.floor(Date.now() / 1000) })
    this.deps.round.setManualMood(mood)
    this.hide()
  }

  private hideTimers(): void {
    window.clearTimeout(this.timeout)
    window.clearInterval(this.ticker)
  }
}
