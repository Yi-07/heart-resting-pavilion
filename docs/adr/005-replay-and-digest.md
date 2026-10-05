# ADR-005 · 对话回放与小结卡片（重开网页的记忆呈现）

## 状态

已定案（UI 形态经原型定稿：30min 内为幕布折叠，隔天为自然混流）

## 背景

ADR-001 审定记忆分层时遗留两个呈现层缺口：

1. **页面无回放**：网页刷新/重开后聊天窗口空白，即使小栖「心里记得」（热层）也无处显示——用户无法对上「上次聊到哪」。要做回放需解决：刷新后浏览器丢失 session_id（现仅不断线时内存持有）、assistant 回复不入轮次（`state.turns` 只在 user_input 时追加，回放会缺小栖一侧）、契约无回放帧。
2. **跨天衔接生硬**：热层 30min 过期后只剩温层摘要，新对话与昨日语境之间零呈现——用户不知道系统「还记不记得」。

ADR-001 本体（热层存 recent_turns 供重连重建 turns）随本决策一并实施——回放与轮次记忆同源，拆开做会出现「回放有但接不上话」的错位。

## 决策

1. **实施 ADR-001（前置）**：热层 `{history_summary, mood_recent}` 增存 `recent_turns`（最近 N 轮 `{role,text}`，N=20 上限，30min TTL 不变）；重连认领后 entry 处重建 `state.turns`；`formulation` 与 `round_index` 不持久（黑板重画，已知局限不变）。
2. **assistant 回复入轮次**：collect 链路中 emitter 发出的最终文本（AskNext 问句/EmpathChat 回应/Finish 总结）按回合追加为 `Turn(role="assistant")`——回放两侧完整，且「最后一问」用于重连续话。流式帧只记拼合全文，不逐帧记。
3. **契约新增回放帧 `replay`**（S→C，不占 seq，语义同 first_frame 类回合外帧）：重连认领（`user_input` 带原 session_id）后、first_frame 之前主动推一次。
   - `mode: "bubbles"`：热层 recent_turns 还在（30min 内）→ 携带 `turns: [{role, text}]` 原话 + `summary`（温层最新摘要，可 null）；
   - `mode: "digest"`：热层已过期 → 只带 `summary`（30min 前提下温层 7 天内才有，均无则不推帧）；
   - 前端身份持久化：session_id 存 localStorage（键 `hrp.session`）；重连带原 id 时后端认领并推回放；**治理联动**：`POST /admin/clear_memory` 前端先清 localStorage（后端清除覆盖 Redis/SQLite，浏览器侧由前端自理）。
4. **前端呈现（原型定稿）**：
   - **30min 内（回放 bubbles）**：幕布折叠式——历史收进「上次聊到 HH:MM · N 条对话 展开▾」横幅，主区干净只显小栖开场；展开后历史气泡降饱和（与实时区分）。
   - **隔天（回放 digest）**：自然混流式——顶部「距上次对话已超过 30 分钟 · 原话已按隐私设定抹去」横幅 + **小结卡片**（梳理主题/两行概括/心情印记，暖橙边框）+ 历史气泡缺省（原话已无）。
   - 小结卡数据源为温层最新摘要（现成，无需新存储）；30min 内也在气泡之后附小结卡（信息不冲突）。
   - 头像右上角常态气泡照旧（最新一句，点开抽屉）；抽屉打开时立绘左移让位（与既有交互一致，本次一并落生产）。
5. **隐私线不变**：recent_turns 原话仅热层 30min，不进温层/冷层/SQLite；日志照旧只记长度/指纹；隔天回放不出原话是设计而非缺陷。

## 后果

- 重连体验完整：心里记得（ADR-001 turns 重建）+ 眼里看得见（回放帧）。
- `replay` 帧使 S→C 消息 6→7 种（[ws-contract.md](../architecture/ws-contract.md)『消息总览（9）』需同步；消息总数从 8 变 9）。
- assistant 轮次入 turns 使 `turns[-1]` 语义变化（`agents/graph.py` 轮答消费点——须同步改为「最近一条 user 轮」，否则会把自己的问句当用户回答）。
- localStorage 存 session_id 引入共用电脑暴露面：30min 内原话可被回放——治理清 localStorage 联动必做，且回放帧仅推给**主动认领原 id** 的连接（新连接无 id 不推）。
- 热层容量：20 轮中文约 2-4KB/会话，Redis 内存影响可忽略。

## 影响

backend：`memory/store.py`（recent_turns 读写）、`agents/state.py`（SessionContext）、`ws_gateway/gateway.py`（重连重建+回放帧+assistant 追加）、`agents/graph.py`（轮答消费点改 user 侧）、`schema/ws_messages.py` 与 `schema/literals.py`（ReplayFrame）；frontend：`ws/client.ts`（localStorage 身份）、`ws/messages.ts`、`chat/messages.ts`（回放注入）、`chat/ChatPanel.vue`（幕布/小结卡组件）、`admin/settings.ts`（治理联动）；契约：[ws-contract.md](../architecture/ws-contract.md)『消息总览（9）』『消息定义（S→C）』『错误处理』；测试：重连一致与回放帧钉测。
