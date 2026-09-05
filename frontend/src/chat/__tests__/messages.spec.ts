// chat 消息模块钉测试:splitStationMention 邀请语提法分段(可点性来源)。
import { describe, expect, it } from 'vitest'
import { splitStationMention } from '../messages'

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
