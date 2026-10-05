# ADR-001 · 记忆分层（近期原始轮次与长期摘要）

## 状态

已接受

## 背景

1. 现有记忆层三层均为摘要（`backend/app/memory/store.py`）：热层 `hrp:v1:hot:{sid}` 含 `{history_summary, mood_recent}`（Redis，30min）、温层 `hrp:v1:warm:{sid}` 为回合摘要列表 + `station:input`（7 天）、冷层为 `mood_daily` 每日心情（SQLite，无 TTL）。
2. 会话内连贯靠 `CollectState.turns`（`agents/state.py`）持有的原始往返；[backend-plan.md](../architecture/backend-plan.md)『采集驱动与图内黑板（CollectState）』载明「state 含用户原文，只活连接内存」。
3. 断线重连时（`ws_gateway/gateway.py` 认领原 session_id），`_collect_sequence` 经 snapshot 重建**空** CollectState，仅把 `history_summary` 注入 `session_context`；该摘要 **collect 图内不消费**（`agents/graph.py` 只读 formulation 与 turns 等）。重连后近期连贯性**实际归零**。

## 决策

1. 分四部分：近期原始（最近 N 轮 `{role,text}`，Redis `hrp:v1:hot`，短 TTL 30min，供重连重建 `turns`）· 长期摘要（warm 7 天，沿用）· 冷层每日心情（沿用）· station 方案书库（不动）。
2. 隐私线精修（[architecture-spec.md](../architecture/architecture-spec.md)『L7 · 数据与知识层』、[ws-contract.md](../architecture/ws-contract.md)『脱敏（硬约束）』、`memory/store.py` 注释）：原始文本只留短期工作记忆（30min），不自留持久；中长期只存摘要，冷层只存心情；音频与凭证红线不变。
3. 重连重建：读热层 `recent_turns` 重建 `state.turns`；`formulation` 与 `round_index` 未持久（已知局限），采集进度恢复列二期。
4. 摘要 LLM 成本不变（回合末摘要本就生成）；新增的只有廉价的原始轮次存储。

## 落选方案

- A · 纯摘要制（维持现状）：无法满足近期连贯，重连恢复形同虚设。
- B · 全量原始持久：突破隐私红线（脱敏硬约束）。
- C · 近期原始按条数控：与 TTL 双控复杂化，MVP 先 TTL 单控。
- D · 只存情绪不存对话：丢失轮次连贯，无法支撑采集一致性。

## 后果

- 正面：重连与换窗口后近期相干；符合「近期记细、久远概括」预期；隐私边界明确。
- 负面：热层存原始文本，需关注容量与去标识；短 TTL 过期自然降为摘要。
- 涟漪：[architecture-spec.md](../architecture/architecture-spec.md)『L7 · 数据与知识层』与 [ws-contract.md](../architecture/ws-contract.md)『脱敏（硬约束）』 · `state.py`（`SessionContext` 加 `recent_turns`） · `memory/store.py`（热层结构） · `gateway.py`（`_collect_sequence` 重建 turns） · 测试补重连一致用例。实施为独立步骤。
