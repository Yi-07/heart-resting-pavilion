// chat 消息模块钉测试:splitStationMention 邀请语提法分段(可点性来源);
// 流式封口语义(user_sent 即 finalize,抢占保留采集态后半截问句不续写,契约 §7)。
import { beforeEach, describe, expect, it } from 'vitest'
import { chat, splitStationMention } from '../messages'

describe('splitStationMention', () => {
  it('邀请语整句:提法前后分段+mention 标记', () => {
    expect(splitStationMention('我把梳理放进了「心灵补给站」,随时点开。')).toEqual([
      { text: '我把梳理放进了「', mention: false },
      { text: '心灵补给站', mention: true },
      { text: '」,随时点开。', mention: false },
    ])
  })

  it('无提法:整段一条不标记', () => {
    expect(splitStationMention('最近很焦虑睡不着')).toEqual([
      { text: '最近很焦虑睡不着', mention: false },
    ])
  })

  it('多次提法:交替标记,提法间文本独立成段', () => {
    const segs = splitStationMention('去心灵补给站看心灵补给站')
    expect(segs.map((s) => s.mention)).toEqual([false, true, false, true])
    expect(segs[1]?.text).toBe('心灵补给站')
    expect(segs[2]?.text).toBe('看')
    expect(segs[3]?.text).toBe('心灵补给站')
  })

  it('空串与纯提法', () => {
    expect(splitStationMention('')).toEqual([])
    expect(splitStationMention('心灵补给站')).toEqual([{ text: '心灵补给站', mention: true }])
  })
})

describe('chat 流式封口', () => {
  beforeEach(() => {
    chat.msgs.splice(0)
  })

  it('finalize 后 appendDelta 另起新消息,不续写旧流(抢占防串写钉)', () => {
    chat.beginBot('嗯,那这件事')
    chat.finalize()
    chat.appendDelta('之后呢?')
    expect(chat.msgs).toHaveLength(2)
    expect(chat.msgs[0]?.text).toBe('嗯,那这件事')
    expect(chat.msgs[0]?.streaming).toBe(false)
    expect(chat.msgs[1]?.text).toBe('之后呢?')
    expect(chat.msgs[1]?.streaming).toBe(true)
  })
})
