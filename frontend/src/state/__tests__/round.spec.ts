// state/round 接缝钉测试(frontend-plan §8):状态机全迁移+非法迁移忽略、
// emotionLabel 写序(first_frame → draw → mood 手点锁,first_frame 解锁)。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRoundStore } from '../round'
import type { Draw, FirstFrame, S2CMsg } from '../../ws/messages'

function ff(over: Partial<FirstFrame> = {}): FirstFrame {
  return {
    type: 'first_frame',
    session_id: 's1',
    route: 'collect',
    template: 'beck_formulation',
    emotion_label: '焦虑',
    mood_select: true,
    text: '我在听',
    ...over,
  }
}

function draw(over: { data?: Draw['data']; seq?: number } = {}): Draw {
  return {
    type: 'draw',
    seq: over.seq ?? 1,
    template: 'beck_formulation',
    data:
      over.data ?? {
        situation: null,
        emotion: { label: '焦虑', intensity: 0.7 },
        thought: null,
        behavior: null,
        intermediate_belief: null,
        core_belief: null,
      },
  }
}

let store: ReturnType<typeof useRoundStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useRoundStore()
})

describe('round 状态机', () => {
  it('collect 全程:idle→awaiting→collecting→(轮答)analysis→(精稿)final→idle', () => {
    expect(store.phase).toBe('idle')
    store.transition({ kind: 'user_sent' })
    expect(store.phase).toBe('awaiting')

    store.transition({ kind: 'frame', msg: ff() })
    expect(store.phase).toBe('collecting')
    expect(store.crisis).toBe(false)
    expect(store.moodVisible).toBe(true)
    expect(store.emotionLabel).toBe('焦虑')
    expect(store.roundId).toBe(1)

    // 粗稿 draw:留 collecting
    store.transition({ kind: 'frame', msg: draw() })
    expect(store.phase).toBe('collecting')

    // 轮次回答提交 → analysis(收尾中)
    store.transition({ kind: 'user_sent' })
    expect(store.phase).toBe('analysis')

    // 精稿 draw → final;done → idle
    store.transition({ kind: 'frame', msg: draw({ seq: 5 }) })
    expect(store.phase).toBe('final')
    store.transition({ kind: 'frame', msg: { type: 'done', session_id: 's1', seq: 6 } })
    expect(store.phase).toBe('idle')
    expect(store.moodVisible).toBe(false)
  })

  it('轮次连续:final 中再答(user_sent)→analysis,再 draw 回 final', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff() })
    store.transition({ kind: 'frame', msg: draw() })
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: draw({ seq: 2 }) })
    expect(store.phase).toBe('final')
    // 第二轮回答:同回合继续,不发 first_frame
    store.transition({ kind: 'user_sent' })
    expect(store.phase).toBe('analysis')
    store.transition({ kind: 'frame', msg: draw({ seq: 3 }) })
    expect(store.phase).toBe('final')
  })

  it('answer 直答:无 first_frame,text_delta 直通 final → done', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: { type: 'text_delta', seq: 1, text: '正念是…', final: true } })
    expect(store.phase).toBe('final')
    store.transition({ kind: 'frame', msg: { type: 'done', session_id: 's1', seq: 2 } })
    expect(store.phase).toBe('idle')
  })

  it('crisis:first_frame(crisis) 不浮选择器,draw/done 走完回 idle', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff({ route: 'crisis', template: null, mood_select: false, emotion_label: null }) })
    expect(store.phase).toBe('collecting')
    expect(store.crisis).toBe(true)
    expect(store.moodVisible).toBe(false)
    store.transition({
      kind: 'frame',
      msg: { type: 'draw', seq: 1, template: 'stage_map', data: { nodes: ['现在'], current: 0, from: '你不是一个人' } },
    })
    expect(store.phase).toBe('collecting')
    store.transition({ kind: 'frame', msg: { type: 'done', session_id: 's1', seq: 2 } })
    expect(store.phase).toBe('idle')
  })

  it('新回合抢占:任意状态新 first_frame → collecting,roundId 递增', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff() })
    store.transition({ kind: 'user_sent' })
    expect(store.phase).toBe('analysis')
    store.transition({ kind: 'frame', msg: ff({ emotion_label: '担心' }) })
    expect(store.phase).toBe('collecting')
    expect(store.roundId).toBe(2)
    expect(store.emotionLabel).toBe('担心')
  })

  it('非法迁移忽略不崩(idle 收 draw/done),error 任意态回 idle', () => {
    const debug = vi.spyOn(console, 'log').mockImplementation(() => {})
    store.transition({ kind: 'frame', msg: draw() })
    expect(store.phase).toBe('idle')
    store.transition({ kind: 'frame', msg: { type: 'done', session_id: 's1', seq: 1 } })
    expect(store.phase).toBe('idle')

    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff() })
    store.transition({ kind: 'frame', msg: { type: 'error', code: 'server_error', message: 'x' } satisfies S2CMsg })
    expect(store.phase).toBe('idle')
    debug.mockRestore()
  })
})

describe('error 分派(契约 §8:ask_llm_failed 挂起,其余回 idle)', () => {
  it('ask_llm_failed:采集态挂起不动(phase 不变,下一条输入重试)', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff() })
    expect(store.phase).toBe('collecting')

    store.transition({ kind: 'frame', msg: { type: 'error', code: 'ask_llm_failed', message: '辐条' } satisfies S2CMsg })
    expect(store.phase).toBe('collecting') // 挂起:状态冻结
    expect(store.moodVisible).toBe(true) // mood 面板也不动

    // 下一条输入重试:user_sent 照常推进(analysis 等待),新 first_frame 重开
    store.transition({ kind: 'user_sent' })
    expect(store.phase).toBe('analysis')
    store.transition({ kind: 'frame', msg: ff({ emotion_label: '平静' }) })
    expect(store.phase).toBe('collecting')
    expect(store.emotionLabel).toBe('平静')
  })

  it('timeout/server_error:任意态回 idle(辐条呈现归 App,状态机只管 phase)', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff() })
    store.transition({ kind: 'frame', msg: { type: 'error', code: 'timeout', message: 'x' } satisfies S2CMsg })
    expect(store.phase).toBe('idle')

    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: { type: 'error', code: 'server_error', message: 'x' } satisfies S2CMsg })
    expect(store.phase).toBe('idle')
  })
})

describe('emotionLabel 写序', () => {
  it('first_frame 写 → draw 无手点时覆盖 → mood 手点锁住后续 draw → 新 first_frame 解锁', () => {
    store.transition({ kind: 'frame', msg: ff({ emotion_label: '焦虑' }) })
    expect(store.emotionLabel).toBe('焦虑')

    // draw 复核出不同 label:未手点 → 覆盖
    store.transition({ kind: 'frame', msg: draw({ data: { situation: null, emotion: { label: '担心', intensity: 0.6 }, thought: null, behavior: null, intermediate_belief: null, core_belief: null } }) })
    expect(store.emotionLabel).toBe('担心')

    // 手点:写 + 上锁
    store.setManualMood('平静')
    expect(store.emotionLabel).toBe('平静')
    store.transition({ kind: 'frame', msg: draw({ seq: 2, data: { situation: null, emotion: { label: '难过', intensity: 0.8 }, thought: null, behavior: null, intermediate_belief: null, core_belief: null } }) })
    expect(store.emotionLabel).toBe('平静') // 手点不被精稿回退

    // 新回合 first_frame:重置锁
    store.transition({ kind: 'frame', msg: ff({ emotion_label: null }) })
    expect(store.emotionLabel).toBeNull()
    expect(store.manualMood).toBe(false)
  })

  it('wheel/stage_map 的 draw 不触碰 emotionLabel', () => {
    store.transition({ kind: 'frame', msg: ff({ emotion_label: '焦虑' }) })
    store.transition({
      kind: 'frame',
      msg: { type: 'draw', seq: 2, template: 'stage_map', data: { nodes: ['现在'], current: 0, from: '你不是一个人' } },
    })
    expect(store.emotionLabel).toBe('焦虑')
  })
})
