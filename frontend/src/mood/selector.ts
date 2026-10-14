// 心情选择器(frontend-plan §4):工具栏「今日心情」点开的表情组浮层。
// 点选 → send mood_select + Live2D 手点写情绪联动废弃(自动浮出已随 T5 废弃,
// 详见契约「mood_select」节);点选即置灰冷却,done 解除,连接异常 ~8s 兜底。
// 回合内置灰(采集/回答进行中不可点)由 App 经 setRoundActive 驱动。

import type { MoodKey, MoodSelect } from '../ws/messages'
import { logger } from '../logger'

/** 冷却兜底时长(ms):done 未达时防连接异常卡死在灰态 */
export const MOOD_COOLDOWN_FALLBACK_MS = 8_000

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
  /** 置灰状态落点:冷却中/回合内都置灰(reactive,由组件读) */
  setDisabled: (disabled: boolean) => void
  send: (msg: MoodSelect) => void
  /** done 帧到达回调挂点(App 接线 done → notifyDone) */
}

export class MoodSelector {
  private fallbackTimer = 0
  private disabled = false

  constructor(private readonly deps: MoodDeps) {}

  /** 点选表情:发 mood_select + 进冷却。回合内调用方已置灰,此处只管冷却 */
  select(mood: MoodKey): void {
    if (this.disabled) return
    this.deps.send({ type: 'mood_select', mood, ts: Math.floor(Date.now() / 1000) })
    this.setDisabled(true)
    // 兜底:done 未达(连接异常)时按固定时长解除
    this.fallbackTimer = window.setTimeout(() => this.setDisabled(false), MOOD_COOLDOWN_FALLBACK_MS)
    logger.debug('mood', `已上报:${mood}(冷却至 done)`)
  }

  /** done 帧到达(App 在 done 分支接线):解除冷却 */
  notifyDone(): void {
    window.clearTimeout(this.fallbackTimer)
    this.setDisabled(false)
  }

  /** 回合内置灰开关(App 由 round.phase 驱动);回合开始即打断冷却计时 */
  setRoundActive(active: boolean): void {
    if (active) {
      window.clearTimeout(this.fallbackTimer)
      this.setDisabled(true)
    } else {
      this.setDisabled(false)
    }
  }

  get isDisabled(): boolean {
    return this.disabled
  }

  private setDisabled(v: boolean): void {
    this.disabled = v
    this.deps.setDisabled(v)
  }
}
