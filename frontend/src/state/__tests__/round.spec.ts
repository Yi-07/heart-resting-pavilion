// state/round 接缝钉测试(frontend-plan §8):状态机全迁移+非法迁移忽略、
// emotionLabel 写序(first_frame → draw 覆盖,first_frame 重置;
// mood_select 手点写情绪联动已随自动浮出废弃,T5)。
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
    mood_select: false,
    text: '',
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

  it('analysis 期 text_delta:单帧 final=true(P7 等待话术)不推相,精稿照常接管;非 final 流式转 final', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff() })
    store.transition({ kind: 'user_sent' })
    expect(store.phase).toBe('analysis')

    // P7 等待话术单帧:phase 保持 analysis(推了会让精稿走 illegal 丢情绪复核)
    store.transition({ kind: 'frame', msg: { type: 'text_delta', seq: 2, text: '嗯，好的…', final: true } })
    expect(store.phase).toBe('analysis')

    // 精稿 draw 正常接管(不被等待话术破坏)
    store.transition({ kind: 'frame', msg: draw({ seq: 3 }) })
    expect(store.phase).toBe('final')

    // 异常时序:analysis 期流式文本(final=false)= 内容提前到,按原语义转 final
    store.transition({ kind: 'user_sent' })
    expect(store.phase).toBe('analysis')
    store.transition({ kind: 'frame', msg: { type: 'text_delta', seq: 4, text: '总结…', final: false } })
    expect(store.phase).toBe('final')
  })

  it('crisis:first_frame(crisis) 置危机态,draw/done 走完回 idle', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff({ route: 'crisis', template: null, emotion_label: null }) })
    expect(store.phase).toBe('collecting')
    expect(store.crisis).toBe(true)
    store.transition({
      kind: 'frame',
      msg: { type: 'draw', seq: 1, template: 'stage_map', data: { nodes: ['现在'], current: 0, from: '你不是一个人' } },
    })
    expect(store.phase).toBe('collecting')
    store.transition({ kind: 'frame', msg: { type: 'done', session_id: 's1', seq: 2 } })
    expect(store.phase).toBe('idle')
  })

  it('crisis 展示态随 done 复位:后续 answer 回合(无 first_frame)不残留', () => {
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: ff({ route: 'crisis', template: null, emotion_label: null }) })
    expect(store.crisis).toBe(true)
    expect(store.route).toBe('crisis')

    store.transition({ kind: 'frame', msg: { type: 'done', session_id: 's1', seq: 2 } })
    expect(store.crisis).toBe(false)
    expect(store.route).toBe('collect')

    // 危机后问其他链路:answer 无 first_frame,危机态不得延续到新回合
    store.transition({ kind: 'user_sent' })
    store.transition({ kind: 'frame', msg: { type: 'text_delta', seq: 3, text: '正念是…', final: true } })
    expect(store.crisis).toBe(false)
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
  it('first_frame 写 → draw 覆盖 → 新 first_frame 重置', () => {
    store.transition({ kind: 'frame', msg: ff({ emotion_label: '焦虑' }) })
    expect(store.emotionLabel).toBe('焦虑')

    // draw 复核出不同 label → 覆盖
    store.transition({ kind: 'frame', msg: draw({ data: { situation: null, emotion: { label: '担心', intensity: 0.6 }, thought: null, behavior: null, intermediate_belief: null, core_belief: null } }) })
    expect(store.emotionLabel).toBe('担心')

    // 新回合 first_frame:重置
    store.transition({ kind: 'frame', msg: ff({ emotion_label: null }) })
    expect(store.emotionLabel).toBeNull()
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
