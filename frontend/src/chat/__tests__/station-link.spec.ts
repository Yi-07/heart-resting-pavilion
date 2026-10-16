// 邀请语链接链路钉测试(修 2026-10-14 手动测试暴露的疑虑):
//   first_frame.round_id → beginBot 绑到消息 → done.station_ready → 点亮 → 点击按轮寻址。
// 覆盖 chat/messages.ts 的标记逻辑 + ChatPanel 点击到 station 控制器的取稿 URL。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { chat, resetChatForTest } from '../messages'
import ChatPanel from '../ChatPanel.vue'
import { bindStation, resetStationForTest, station } from '../../station/station'
import { WSClient, type WSLike } from '../../ws/client'

class FakeRes {
  constructor(readonly status: number, private readonly body?: unknown) {}
  get ok(): boolean { return this.status >= 200 && this.status < 300 }
  async json(): Promise<unknown> { return this.body }
}

let calls: string[] = []

function stub(input: RequestInfo | URL): FakeRes {
  const url = String(input)
  calls.push(url)
  return new FakeRes(200, { status: 'ready', report_md: '# 稿' })
}

function clientWith(sid: string | null): WSClient {
  const fake: WSLike = { send: () => {}, close: () => {}, onopen: null, onclose: null, onerror: null, onmessage: null }
  const c = new WSClient('ws://test/', () => fake)
  void c.connect().catch(() => {})
  if (sid !== null) fake.onmessage?.({ data: JSON.stringify({ type: 'done', session_id: sid, seq: 1, round_id: '1', station_ready: true }) })
  return c
}

const INVITE = '我把这次的梳理放进了右侧的「心灵补给站」,里面有一份为你整理的小方案,想看的时候随时点开。'

beforeEach(() => {
  vi.stubGlobal('fetch', stub)
  calls = []
  resetChatForTest()
  resetStationForTest()
  bindStation(() => clientWith('sess_x'))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('邀请语链接 → 按轮取稿', () => {
  it('beginBot 绑定 round_id;markStationReady 只点亮该轮', () => {
    chat.beginBot('安抚语', '1')
    chat.appendDelta('问句一')
    chat.beginBot('另一轮的安抚语', '2')
    expect(chat.msgs[0]?.roundId).toBe('1')
    expect(chat.msgs[1]?.roundId).toBe('2')
    expect(chat.msgs[0]?.stationReady).toBe(false)
    chat.markStationReady('1')
    expect(chat.msgs[0]?.stationReady).toBe(true)
    expect(chat.msgs[1]?.stationReady).toBe(false) // 不误点亮别轮
  })

  it('appendDelta 不会把内容分流到没绑轮次的新消息', () => {
    chat.beginBot('安抚语', '1')
    chat.appendDelta('确认+问句')
    chat.appendDelta('人话总结')
    chat.appendDelta(INVITE)
    expect(chat.msgs).toHaveLength(1) // 全程一条
    expect(chat.msgs[0]?.roundId).toBe('1')
    expect(chat.msgs[0]?.text).toContain('心灵补给站')
  })

  it('已点亮:点击邀请语链接 → 请求带该轮 round_id,并直接进详情', async () => {
    chat.beginBot('安抚语', '1')
    chat.appendDelta(INVITE)
    chat.markStationReady('1')
    station.open = true
    const wrapper = mount(ChatPanel, {
      global: { plugins: [createPinia()], stubs: { ReportList: true } },
    })
    await flushPromises()
    wrapper.findAll('[data-testid="station-mention"]').forEach((el) => void el.trigger('click'))
    await flushPromises()
    expect(calls).toHaveLength(1)
    expect(calls[0]).toContain('round_id=1')
    expect(calls[0]).toContain('/station/report/latest')
    expect(station.view).toBe('detail')
    expect(station.currentRoundId).toBe('1')
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toBe('# 稿')
  })

  it('链接置灰类:未点亮时点击不发请求(交给 station 的显式失败态)', async () => {
    chat.beginBot('安抚语', '1')
    chat.appendDelta(INVITE)
    // 注意:不调 markStationReady —— 模拟邀请语已到、done(归档信号)未到的窗口期
    const wrapper = mount(ChatPanel, {
      global: { plugins: [createPinia()], stubs: { ReportList: true } },
    })
    await flushPromises()
    const link = wrapper.find('[data-testid="station-mention"]')
    expect(link.classes()).toContain('off')
    await link.trigger('click')
    await flushPromises()
    // 宽限:不硬失败,照常按轮取稿(由后端权威应答)
    expect(calls).toHaveLength(1)
    expect(calls[0]).toContain('round_id=1')
    expect(station.phase).toBe('ready')
    expect(station.reportMd).toBe('# 稿')
  })

  it('回归:用户发言穿插时,邀请语仍绑在本轮 round_id 上(2026-10-14 线上bug)', () => {
    // 真实链路:first_frame 开消息 → 用户每答一句 appendUser → 下一句确认/问句/总结
    // 都由 appendDelta 走 beginBot 分支(上一条是用户消息)。若这里丢 roundId,
    // 邀请语就落在 roundId=null 的消息里 → 点击只能进列表(空)。
    chat.beginBot('安抚语', '1')          // first_frame
    chat.appendDelta('愿意说说最近发生了什么吗?') // 首问,追加进同一条
    chat.appendUser('上周开会汇报被领导当众批评')   // 用户第 1 答
    chat.appendDelta('嗯,那件事我记下了。当时脑子里闪过的第一个念头是什么?', '1') // 新消息,需带 roundId
    chat.appendUser('我做得不够好')                 // 用户第 2 答
    chat.appendDelta('谢谢你愿意说出来。那之后你做了什么?', '1')
    chat.appendUser('我躲开了那个会')               // 用户第 3 答
    chat.appendDelta('嗯,当时的你已经在用自己的方式应对了。') // 总结
    chat.appendDelta(INVITE)                                   // 邀请语
    chat.markStationReady('1')                                 // done.station_ready

    // 每条 bot 消息都应绑在本轮上
    const bot = chat.msgs.filter((m) => m.who === 'x')
    expect(bot.length).toBeGreaterThan(1) // 确实走过 beginBot 分支
    for (const m of bot) {
      expect(m.roundId).toBe('1')
      expect(m.stationReady).toBe(true)
    }
    // 邀请语落在绑了轮次的消息里
    const inviteMsg = bot.find((m) => m.text.includes('心灵补给站'))
    expect(inviteMsg?.roundId).toBe('1')
  })

  // ---- activeRoundId 兜底边界(审核意见:兜底不能污染无关消息) ----

  it('边界:省略 roundId → 沿用 activeRoundId(调用点漏传也不丢)', () => {
    chat.beginBot('安抚语', '1') // first_frame 设 activeRoundId='1'
    chat.appendUser('我做得不够好')
    chat.appendDelta('谢谢你愿意说出来') // 省略 → 兜底 '1'
    const last = chat.msgs[chat.msgs.length - 1]
    expect(last?.roundId).toBe('1')
    expect(chat.activeRoundId).toBe('1')
  })

  it('边界:显式传 null → 不绑轮次,也不改 activeRoundId', () => {
    chat.beginBot('安抚语', '1')
    chat.appendUser('什么是正念')
    chat.appendDelta('正念就是有意识地关注当下', null) // answer 支线:明确不绑
    const last = chat.msgs[chat.msgs.length - 1]
    expect(last?.roundId).toBeNull()
    expect(chat.activeRoundId).toBe('1') // 未被污染
  })

  it('边界:新一轮 first_frame → activeRoundId 切换到新轮次', () => {
    chat.beginBot('第1轮安抚语', '1')
    chat.appendDelta('问句')
    chat.appendUser('回答')
    chat.appendDelta('第2轮的确认', undefined) // 省略 → 此时 activeRoundId 已被第 2 轮首帧更新
    expect(chat.msgs[chat.msgs.length - 1]?.roundId).toBe('1') // 第 2 轮首帧还没到,仍是 1
    chat.beginBot('第2轮安抚语', '2') // first_frame(round_id=2)
    expect(chat.activeRoundId).toBe('2')
    chat.appendUser('第2轮回答')
    chat.appendDelta('第2轮的问句') // 省略 → 兜底 2
    const bots = chat.msgs.filter((m) => m.who === 'x')
    expect(bots[bots.length - 1]?.roundId).toBe('2')
    // 第 1 轮的消息不受影响
    expect(bots[0]?.roundId).toBe('1')
  })

  it('边界:resetChatForTest 清空 activeRoundId(测试/会话切换隔离)', () => {
    chat.beginBot('安抚语', '1')
    expect(chat.activeRoundId).toBe('1')
    resetChatForTest()
    expect(chat.activeRoundId).toBeNull()
    expect(chat.msgs).toHaveLength(0)
  })

  it('回归:点击上述邀请语 → 请求带 round_id(不再落空列表)', async () => {
    chat.beginBot('安抚语', '1')
    chat.appendUser('上周开会汇报被领导当众批评')
    chat.appendDelta('嗯,那件事我记下了。', '1')
    chat.appendDelta(INVITE, '1')
    chat.markStationReady('1')
    const wrapper = mount(ChatPanel, {
      global: { plugins: [createPinia()], stubs: { ReportList: true } },
    })
    await flushPromises()
    await wrapper.find('[data-testid="station-mention"]').trigger('click')
    await flushPromises()
    expect(calls).toHaveLength(1)
    expect(calls[0]).toContain('/station/report/latest')
    expect(calls[0]).toContain('round_id=1')
    expect(calls[0]).not.toContain('/station/report/list')
    expect(station.view).toBe('detail')
  })

  it('历史消息:点早先一轮的链接只请求那一轮', async () => {
    chat.beginBot('第1轮安抚语', '1')
    chat.appendDelta(INVITE)
    chat.markStationReady('1')
    chat.beginBot('第2轮安抚语', '2')
    chat.appendDelta(INVITE)
    chat.markStationReady('2')
    const wrapper = mount(ChatPanel, {
      global: { plugins: [createPinia()], stubs: { ReportList: true } },
    })
    await flushPromises()
    const links = wrapper.findAll('[data-testid="station-mention"]')
    expect(links).toHaveLength(2)
    await links[0]!.trigger('click') // 只点第 1 轮那条
    await flushPromises()
    expect(calls).toHaveLength(1)
    expect(calls[0]).toContain('round_id=1')
  })
})
