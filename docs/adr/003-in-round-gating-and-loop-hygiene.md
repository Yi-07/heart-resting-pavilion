# ADR-003 · 采集态路由门控与事件循环防阻塞

## 状态

已定案（与 ADR-002 同批实施）

## 背景

ADR-002 收尾的业务实况回归暴露两个问题：

1. **采集态被 answer 抢占丢弃**：路由规则分类器（KNOWLEDGE_PATTERNS 含"怎么办/建议"等求助性词）把采集中的自然追问（「我该怎么办？」）判为 answer 0.9，抢占路径**清空采集态**——已采字段无精稿即丢。心理陪伴场景里，采集中的提问绝大多数是当下对话的追问，不是独立知识问答。
2. **RAG 首次加载阻塞事件循环 ~18s**：chromadb + jieba + sentence-transformers 在请求路径同步懒加载，单事件循环被堵死——WS keepalive 无响应被踢、`wait_for` 超时定时器同样失灵、所有并发会话冻结、断连**零告警**（仅一条与正常下线无法区分的 session_close）。首个真实用户必踩。

外部评审意见（用户携专家反馈）：规则可继续做冷启动，但采集态须对路由有**否决权**；RAG 改启动预热；断连不能再无声。用户进一步提出 discourse-stack 式方案（四问判据 + 结构化输出 + 栈式恢复），采纳为演进方向，改造为门控式分层落地。

## 决策

1. **采集态门控**（`_process_user_input` answer 分支）：
   - 采集态（`collect_state` 非空）时，answer 命中不再抢占弃态，三分支：
     - 纯概念问句（`PURE_CONCEPT_PATTERNS`：什么是/原理/区别类，与场景无关）→ **短答支线**：`suspended=True` 挂起采集态（不清空），走 answer 帧序——无 first_frame，前端黑板天然保活；
     - 连续追问满 2 次或显式要求回答（`EXPLICIT_ASK_TERMS`）→ 同进短答支线（升级策略）；
     - 其余求助句（怎么办/建议类，依赖用户场景）→ 留 collect，由字段提取/共情陪聊路径轻回应（现有机制，零新增）。
   - 下一输入自动恢复采集（`suspended` 复位、追问计数清零），挂起前字段与待问问题原样保留。
   - 短答升级策略刻意**不做**：低置信澄清（违反"置信不足兜底 collect"的安全默认）、通用任务栈（当前穿插只有一层，bool 足够，接口留作深度-1 栈演进）。
2. **RAG 启动预热 + 异步检索**：lifespan 后台 `warm()`（to_thread 触发全部懒加载件）；请求侧统一走 `rag.retrieve_async`——等就绪上限 2s，超时抛 `RagNotReady` 由调用方按 `rag_failed` 降级直答；检索本体（encode/query/rerank 数百 ms 同步）一律 `to_thread`。不做独立 RAG 进程。
3. **事件循环看门狗**：lifespan 常驻 task，lag>2s 记 WARN（唯一能在同步阻塞时给出信号的机制）。
4. **断线不再无声**：WSClient 增加重连回调，前端挂"连接断开，正在重连…"提示（重连成功即撤；退避重连与 session 认领机制已有）。

## 后果

- 「什么是正念」既有验收用例语义变化：非采集态行为不变；采集态中变为短答支线+回接（黑板保留）。
- 短答支线沿用 answer 帧序，**ws-contract 无新帧、无时序变更**。
- 挂起态只活连接内存：重连后采集态本就重建（契约 §8.4 热层恢复不含 suspended），挂起中重连=采集上下文丢失，与既有重连语义一致。
- 求助词表/概念词表均为 MVP 占位（运行时补）；四问 LLM 结构化分类器（依赖场景/影响主线/回接判断）留阶段 2，仅门控命中时调用，且有 route_decided 日志（source/confidence/via/ask_count）积累评估数据。

## 影响

backend: `ws_gateway/gateway.py`、`router/classifier.py`、`agents/state.py`、`rag/__init__.py`、`main.py`；frontend: `ws/client.ts`、`App.vue`；测试: `tests/test_routing_gate.py`（状态组合矩阵钉）。
