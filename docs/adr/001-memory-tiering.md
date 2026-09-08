# ADR 001 · Memory Tiering(记忆分层:近期原始轮次 / 长期摘要)

- **决策名**:`MemoryTiering`
- **标题**:记忆改为近期原始轮次(工作记忆)+ 长期摘要(gist),精修「原始文本只短期存」的隐私边界
- **状态**:已接受
- **背景**:
  - 现有记忆层三层均为摘要(`backend/app/memory/store.py`):热层 `hrp:v1:hot:{sid}`=`{history_summary, mood_recent}`(Redis,30min)、温层 `hrp:v1:warm:{sid}`=回合摘要列表 + `station:input`(7天)、冷层=`mood_daily` 每日心情(SQLite,无TTL)。
  - 会话内连贯靠 `agents/state.py` L59 `CollectState.turns` 持有的原始往返;L4 `state 含用户原文,只活连接内存`。
  - 断线/重连(`ws_gateway/gateway.py` L227-231 认领原 session_id)→ `_collect_sequence` L378 `snapshot` 重建**空** CollectState,仅把 `history_summary` 注入 `session_context`;该摘要**collect 图内不消费**(`agents/graph.py` 只读 formulation/turns 等)。重连后近期连贯性**实际归零**。
- **决策**:
  1. 分四面:近期原始(最近 N 轮 `{role,text}`,Redis `hrp:v1:hot`,短 TTL 30min,供重连重建 `turns`)· 长期摘要(warm 7天,沿用)· 冷层每日心情(沿用)· station 方案书库(不动)。
  2. 隐私线精修(spec §4 L7 / §9.4 / state.py 注释):原始文本只留短期工作记忆(30min),不自留持久;中长期只存摘要,冷层只存心情;音频/凭证红线不变。
  3. 重连重建:读热层 `recent_turns` 重建 `state.turns`;`formulation`/`round_index` 未持久=已知局限,采集进度恢复列二期。
  4. 摘要 LLM 成本不变(回合末摘要本就生成);新增为廉价原存储。
- **落选方案**:
  - A · 纯摘要制(维持现状):无法满足近期连贯,重连恢复形同虚设。
  - B · 全量原始持久:突破隐私红线(spec §9.4)。
  - C · 近期原始按条数控:与 TTL 双控复杂化,MVP 先 TTL 单控。
  - D · 只存情绪不存对话:丢轮次连贯,无法支撑采集一致性。
- **后果**:
  - 正面:重连/换窗口近期相干;符合"近期记细、久远概括"预期;隐私有下限。
  - 负面:热层存原始文本,需关注容量与去标识;短 TTL 过期自然降为摘要。
  - 涟漪:spec §4 L7 + §9.4 · `state.py`(`SessionContext` 加 `recent_turns`)· `memory/store.py`(热层结构)· `gateway.py`(`_collect_sequence` 重建 turns)· 测试补重连一致用例。落地为独立步骤,不进 A#2。
