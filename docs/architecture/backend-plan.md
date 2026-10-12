# 后端实施方案 · 技术原型

> **权威源**：`architecture-spec.md`（架构）· `ws-contract.md`（契约）
> **不管面**：机制与参数以 spec 为准，消息格式以 ws-contract 为准，本文件不复制；日志红线唯一记录处见 [ws-contract.md](ws-contract.md)「日志范式（双输出）」。
> **目标**：技术原型后端——跑通三路路由全链路（危机闸门 / 分类器 / 多轮采集 / Agent / 记忆 / 语音），日志与审计齐备。

---

## 1. 技术栈

| 项 | 选型 |
|---|---|
| 框架 | FastAPI + WebSocket |
| Agent | LangGraph 1.x（确定性 StateGraph，条件边编排） |
| 环境 | uv（python）|
| 日志 | loguru（双输出：控制台彩色 + 文件结构化）|
| 存储 | SQLite（冷层）+ Redis（热/温层）|
| 语音 | GPT-SoVITS（TTS，remote PCM 流式；情感标签）+ SenseVoice（ASR，含情感识别）|
| LLM | DeepSeek（OpenAI 兼容）+ Ollama 本地，双源抽象 |

---

## 2. 模块职责表

> **目录风格**：一个职能一个深模块目录——对外接口小，背后行为多；删除测试：删掉该目录，复杂度应消失而非散到调用方；文件不散放 app 根。
> **文件真源为文件系统**：本表只记职责与接口；文件增删改不回本表，**职责变化才改行**；接口相关事实留接口列，纯实现细节由代码实施时入该模块 docstring、同 commit 出表。

| 模块 | 职责 | 关键接口 |
|---|---|---|
| app/main | 入口装配 | 挂 /ws·/station·/admin |
| ws_gateway | 连接/发号/抢占/消息分发 | 每条 user_input 先过闸门；S→C 帧统一盖章即发（发号与帧映射见「WS 网关」）；error 帧收口 |
| admin | 管理通道 REST | — |
| config | 模型配置 | LLM/ASR/TTS 读环境变量；config 传递 emitter |
| logger | 日志与审计 | 双输出+危机审计（见「日志（双输出，对齐 ws-contract）」） |
| router | 闸门+分类+话术 | `gate.check(text)→GateResult{hit, matched: list[str], severity: float}`（hit 即 severity≥阈值，阈值走配置；matched 供审计；词典与打分为实现细节，实施时入 docstring） · `classifier→{route,label,conf}` · phrases 为预设话术库（危机话术/邀请语/心情回执/等待语音文案，预置文本+预生成 wav 同步直发；问话不落预置——归 LLM 流式，见 spec「L4」采集器规格）；隔离约束见 [architecture-spec.md](architecture-spec.md)「L3 · 智能路由决策器」 |
| collect | 采集三件 | 字段选择/问序（预置结构单源）/充分度（`sufficiency(f)→float`，权重表为实现细节实施时入 docstring）/三降级检测；问话归 LLM 流式生成，见 [architecture-spec.md](architecture-spec.md)「L4 · 空窗期策略（横切编排）+ 多轮采集器」 |
| agents | 图编排+共享黑板 | CollectState 17 字段（§3，answer/collect 共用）·图出口为 CollectEvent（§3.4）·确定性条件边分派；Agent 名单见 [architecture-spec.md](architecture-spec.md)「L5 · 异步推理层 · 多 Agent」 |
| rag | 检索三件套（混合知识库） | `retrieve(query, k=None, *, library=CASE)`·`ingest(refs, *, library, reset=False)`·`RagLibrary{KNOWLEDGE, CASE}`；`Ref={id, question, answer, score, category}`（k=None 走配置默认）；两 Chroma 集合为 hrp_kb_knowledge（科普知识库，answer 直答用）·hrp_kb_case（案例库，collect/station 用）；Chroma+bge-m3·BM25+jieba·bge-reranker-v2-m3；深模块：两库/召回融合重排/分批/BM25 回建藏模块内，调用方只传 library；ingest 脚本与 Chroma collection 归本模块，数据对接见 [data-contract.md](data-contract.md)（换 embedding 模型即重跑 ingest，代码不动） |
| llm | LLM 双源 | `LLMProvider`: `chat(messages)→str` · `stream(messages)→Iterator[str]` · `chat_json(messages, schema)→T`（`Message={role, content}`）；出错抛 LLMError，由调用方捕获降级（问话失败走 error 帧+辐条，不落预置话术——见 spec「L4」问话失败行）；DeepSeek/Ollama 同接口由 config 切换（§7） |
| memory | 热/温/冷记忆+治理 | `snapshot(session_id)→SessionContext` · `append_turn(session_id, role, text)`（热层轮次原话，ADR-005） · `save_round_summary(session_id, summary)` · `record_mood(mood)`（同日同源 upsert，最新胜）；层介质与 TTL 见 [architecture-spec.md](architecture-spec.md)「L7 · 数据与知识层」（数值不复制） |
| voice | 语音引擎 | `transcribe(audio: bytes)→str`（ffmpeg 转码在内）·`synthesize_stream(text)→Iterator[bytes]`（按句流式；情感标签属接口预留未接线，见 spec「L6 · 工具与执行层」）·`synthesize_pcm_stream(text)→Iterator[PcmChunk]`（PCM 流式，round_id 透传）；ASR（SenseVoice；ffmpeg 转码 webm/opus→wav16k 后进引擎，只取转写文本（情感识别结果丢弃），音频即弃）·TTS（GPT-SoVITS remote；问话逐句/总结+邀请/危机；失败跳过音频，文字照常收尾）·fillers 为预生成等待语音文件（与 TTS 同音色；切块直发 audio_chunk，零运行时合成） |
| station | 补给站 REST+方案书存取 | 端点见 [ws-contract.md](ws-contract.md)「连接与会话」；生成素材 `station:input`（§3.3，回合末随归档触发生成）；SQLite reports 表（主键 (session_id, round_id)，历史保留——同会话每回合一份，latest 取最新回合） |
| schema | 契约类型单源 | Pydantic 对齐 ws-contract（formulation+ws_messages）；契约对齐测试抽 ws-contract「数据对象」formulation 字段名与本端比对，防两端漂移（§11） |

> **鉴权决策（原型期，显式裁定）**：station/admin REST **不鉴权是有意取舍**——依赖默认绑定 127.0.0.1 + CORS 白名单；局域网/公网暴露前必须加会话信物（D1 部署文档护栏，验收按此作答）。

---

## 3. 采集驱动与图内黑板（CollectState）

### 3.1 驱动模式

- 每条 user_input = **一次短图调用**：网关先过危机闸门 → 未命中则带着现有 CollectState 调图，跑到「等待下一条输入」或「回合终结」即返回
- CollectState 挂在 **WS 连接对象**上，图节点只读写、不持有；同一时刻至多一个调用在跑
- 销毁触发点（任一即弃，不抢救）：done 发出 · 新 user_input 抢占 · 超时 · 危机命中 · 断线/进程重启
- 相位不落 state：下一步动作由条件边纯函数 `where_next(state)` 从 route/degrade_reason/sufficiency/round_index 算出，出口事件见 §3.4，分派图见 §5

### 3.2 CollectState 字段（17）

**A · 身份与路由（网关写入，图内只读）**

| 字段 | 类型 | 初始值 | 写入者 |
|---|---|---|---|
| session_id | str | 连接分配 | 网关（entry） |
| route | `"answer"\|"collect"` | 分层判定 | 网关（entry），图内不可变 |
| template | TemplateId\|None | collect→`beck_formulation`；answer→None | 网关（entry） |
| emotion_label | str\|None | 快速研判标签 | 分层判定一次写入，图内不回写 |
| confidence | float | 分层判定 conf | 分层判定（留档调试） |

**B · 采集进度（图内写入）**

| 字段 | 类型 | 初始值 | 写入者 |
|---|---|---|---|
| formulation | Formulation | 全 null | entry 提取（填实质字段+emotion）→ 轮次填格 → 分析（emotion_review 合入） |
| round_index | int | 0 | 轮次处理（每条回答 +1） |
| sufficiency | float | 0.0 | 充分度打分（每次填格后重算，§4） |
| degrade_reason | DegradeReason\|None | None | 降级检测；None 表示未降级，布尔派生 |
| pending_question | PendingQuestion\|None | None | 问话 LLM 产出时写，下条回答消费（回答填哪格由它定） |
| max_rounds | int | 配置注入（上限 3，见 [architecture-spec.md](architecture-spec.md)「L4 · 空窗期策略（横切编排）+ 多轮采集器」） | 网关（entry） |
| escalated | bool | False | risk 复核命中写 True → 调用即止，网关转危机序列+审计 |

**C · 上下文（网关写 entry；图内只读/追加 turns）**

| 字段 | 类型 | 初始值 | 写入者 |
|---|---|---|---|
| turns | `list[Turn]`（追加式） | [] | 网关（entry input 为 turns[0]）→ 轮次节点（问答追加） |
| session_context | SessionContext | 记忆层快照 | 网关（entry），回合内不刷新 |

辅助类型：`Turn={role:"user"|"assistant", text:str}` · `DegradeReason="too_short"|"off_topic"|"negative"` · `PendingQuestion={text:str, target_field:FieldKey}` · `SessionContext={history_summary:str|None, mood_recent:list[MoodKey], recent_turns:list[Turn]}`（温层摘要+冷层心情+热层轮次原话（ADR-001/005），来源为 memory/）

脱敏：state 含用户原文，只活连接内存；日志只记长度/哈希（见「9. 日志（双输出，对齐 ws-contract）」）；落盘唯一出口为回合结束 `station:input`（3.3）

### 3.3 回合生命周期

```
entry 调用:字段提取+选材(首条输入即提取,entry 即提取)→ 粗稿 draw(带实质字段)→ 第 1 问
每轮:softscan 软预筛+新增命中 LLM 复核(spec §4 L5「每轮预筛/命中复核」;
  risk_reviewed_terms 去重,同一软词整会话只复核一次)
轮次调用:填 formulation → draw 增量 → 充分度重算 → where_next
  → 继续问:第 i 问(问话 LLM 流式,确认语自然带出;陪聊轮不填格、无 draw)
  → 终结:充分度 ≥0.7 ｜ round_index ≥ max_rounds ｜ 降级收尾
终结调用:risk 增量复核(命中→escalated=True 即止)→ emotion_review 合入 → 精稿 draw → 总结+邀请语 → done
回合结束(网关三动作):温层写本回合摘要 → Redis 写 station:input{formulation,summary,round_id}(TTL 7 天)→ 弃 state
  → 方案书后台自动生成(Finish 归档触发,spec「L5 · 计划制定者」;done 照发不等待)
```

**每轮输出（问话 LLM 流式生成，文字攒批发帧+句子泵逐句 TTS）**：
问话由 LLM 按采集信息需求生成（target_field 由字段选择单源定，文本不落预置；
AskNext 事件只携带问句与所问字段，confirm 由问话流自然带出不再独立成字段）。

### 3.4 图出口事件（CollectEvent）

每次图调用结束时只产出一个事件，网关按事件收尾，不读 state 内部字段：

```
CollectEvent =
    AskNext{question, target_field}                  # 继续问,问话 LLM 流式产出,写入 pending_question
  | EmpathChat{reply}                                # 陪聊轮:不填格、无 draw(LLM 回应)
  | Finish{cause, summary}                           # cause = "sufficient" | "max_rounds" | DegradeReason
  | Escalate                                         # risk 复核命中,escalated=True 即止
```

网关收到 AskNext/EmpathChat 就等待下一条输入；Finish 触发回合结束三动作（§3.3）；Escalate 转危机序列并落审计（§6）。帧不进事件，由 emitter 直发（§8）。

---

## 4. 充分度打分

```python
WEIGHTS = {"situation": .20, "emotion": .20, "thought": .20,
           "behavior": .15, "intermediate_belief": .15, "core_belief": .10}

def sufficiency(f: Formulation) -> float:
    return sum(w for k, w in WEIGHTS.items() if getattr(f, k) is not None)
# 高阈值 0.7(可调常量);测试档 0.85 → 约 3 轮挖信念
```

---

## 5. LangGraph 图定义（骨架）

> Agent 职责/激活/安全边界见 [architecture-spec.md](architecture-spec.md)「L5 · 异步推理层 · 多 Agent」，彼处为唯一权威。

```
nodes: empath · knowledge · risk · planner(派活=确定性条件边,无 LLM 主管)
gate(网关前置,每条 user_input 先过)+classifier 定 route;危机不入图。条件边分派:
    answer → (需 RAG ?) knowledge → 直答流式
    collect → empath(采集循环,黑板=CollectState §3)
            → risk(软预筛→LLM 复核;命中→escalated=True,调用即止,网关发危机序列+审计)
            → 停采 → analysis(同步:emotion 复核 + 总结 + RAG 引用)
            → empath 总结(末尾拼心灵补给站邀请语)
    planner = 心灵补给站方案书(用户点击触发,异步,REST 通道)
```

---

## 6. 危机与审计

- **gate.py**：危机词典 + 严重度打分（硬判，目标 ≤10ms/条），与 L6 规则引擎**共享单一词典来源**
- 词典/降级阈值走配置数据，MVP 最小占位（危机核心词先跑），内容运行时补
- 每轮输入过 gate；命中 → CRISIS，落**审计日志**（WARN：命中项 + 是否转热线，不含原文）
- **risk.py**：软信号关键词预筛（低档位）→ 命中才 LLM 复核，控成本

---

## 7. LLM 双源抽象

```python
# llm/provider.py —— OpenAI 兼容统一入口
# DeepSeek: base_url=https://api.deepseek.com, model=deepseek-flash
# Ollama:   base_url=http://localhost:11434/v1, model=qwen3:8b(示例)
# 由 config.py 切换;R3 配置 UI 后续接管
```

> **provider 策略（mock 边界）**：
> - 真 provider：LLM（DeepSeek/Ollama） · ASR（SenseVoice/FunASR） · TTS（GPT-SoVITS remote） · Live2D 真模型打包 · 记忆 SQLite 真存
> - **RAG 以预置问答对灌入 Chroma 跑真检索**（种子语料）；数据集就绪后往 Chroma 加数据，代码不变
> - 配置占位：危机/软信号词典、降级阈值（结构定、内容后补）
> - 收尾优化：本地兜底，单机离线演示
> - 不 mock 边界：契约（ws-contract）/WS 网关/采集状态机/充分度/黑板渲染 全真实现；provider 抽象接口保留，真实现与兜底同接口

---

## 8. WS 网关

- 每连接：建 session_id；`user_input/mood_select` 入口；输入单源文本（语音经 `/asr/transcribe` REST 转写预览、用户确认后按文本发送，ADR-004；网关无 audio 分支）
- **发号**：所有 S→C 帧经网关发送函数，盖章即发送（seq 预增，首帧为 1）；仅 draw/text_delta/audio_chunk/done 消耗号，first_frame/error 不带不消耗；计数器为连接对象内存（会话内全局递增，ws-contract「3.2 draw」）
- **两条来路**：网关直发（first_frame/危机序列/error/done）；图内 emitter 注入（config 传递，不进 state）发 draw/text_delta/audio_chunk——Emitter 协议三方法：draw（formulation） · text（s） · audio（chunk）
- 抢占：等待期弃 state 直接 entry；分析中 cancel 图调用 + 旧 emitter 标记 dead（未发帧蒸发）→ entry；前端淡出停播（frontend-plan「6. WS 消息 → 前端行为」）
- 非法消息 → `error(invalid_message)`；超时（锚点见 [ws-contract.md](ws-contract.md)「回合与中断」）→ `error(timeout)` + 降级话术 + done；异常 → `error(server_error)`

**帧映射（发射侧唯一事实）**

| 帧 | 发送者 | 触发 | data 来源 |
|---|---|---|---|
| first_frame | 网关 | 分层判定 collect/crisis 后、进图前 | route/template/emotion_label + text（collect 置空，crisis 携危机安抚） |
| draw | emitter | 节点改 formulation 后显式发；粗稿/逐轮/精稿同一调用，全量 | state.formulation |
| text_delta | emitter | 问话/陪聊 LLM 流式（攒批：~100ms 窗或 ~30 字，每批一帧）· 知识直答/分析总结流式 · 邀请语（话术库模板，总结末尾） | 对应文本流 |
| audio_chunk | 网关+emitter | 网关：危机话术/等待语音/心情回执（预置 wav 直发，随文同步）；emitter：问话逐句 TTS（句子泵）+ 总结 TTS | TTS 流式（pcm_s16le）/ 预生成 wav（同音色） |
| done | 网关 | 图调用终结且 emitter 排空 → 随后回合结束三动作（§3.3） | — |
| error | 网关 | 非法/超时/异常 | code + message（ws-contract「3.7 error」） |

- 危机序列（网关，闸门任意命中）：first_frame（crisis） → draw（scene_crisis） → text_delta（热线话术） → audio_chunk（预置 wav，失败跳过） → done + WARN 审计（§6）
- mood_select：独立到达时回预置回执 text_delta + 预置语音 + done；回合内到达仅更新 profile 不回帧（ws-contract「4.2 mood_select」）

---

## 9. 日志（双输出，对齐 ws-contract「日志范式（双输出）」）

双输出（loguru 控制台彩色 INFO + 文件 DEBUG）与脱敏/审计硬约束见 [ws-contract.md](ws-contract.md)「日志范式（双输出）」；本节不复制参数（轮转/保留数值）与红线细则。

---

## 10. 验收（后端视角，4 用例）

用 WS 客户端或脚本各跑一遍，查链路消息顺序 + 日志：

1. **answer**：`user_input("什么是正念")` → text_delta 流式 → done；无 draw
2. **collect**：`user_input("最近很焦虑睡不着")` → first_frame（text 空）→ entry 提取 draw（带选材）→ 问话 text_delta+audio_chunk 流式 → 2 轮 draw 增量 → 精稿 → 分析总结+心灵补给站邀请语 → done（方案书回合末自动生成，不在回合内等待）；日志含 `crisis_gate_hit(hit:false)`、`route_decided(collect)`、`sufficiency_scored`
3. **crisis**：`user_input("我不想活了")` → first_frame（crisis） → 热线内容；日志含 **crisis_gate_hit（hit：true， audit）** 审计
4. **voice**：`POST /asr/transcribe`（webm/opus base64 → 转写文本，前端回填确认后按文本发送，ADR-004；音频转写后即弃）+ 问话与总结各出 audio_chunk ×N；分析中发新 user_input 抢占 → 未发帧蒸发 + 新 first_frame；日志无音频无原文

---

## 11. 测试

- **框架与布局**：pytest（已配）；测试文件放 `tests/`，一接缝一文件，文件名即接缝名，不设 unit/integration 分层
- **接缝钉测试**（只钉接缝，不测内部）：

| 接缝 | 测什么 |
|---|---|
| gate.check | 命中/未命中/阈值边界；matched 覆盖审计所需命中项 |
| sufficiency | 字段组合覆盖权重；停采两档边界（数值见「4. 充分度打分」） |
| retrieve | 种子语料命中（id/question 稳定返回）；k 截断 |
| where_next | CollectEvent 四变体各分支：继续问/陪聊/终结三因/升级 |
| LLMProvider | chat_json 校验失败路径；LLMError 降级（stub 实现） |
| Emitter | dead 标记后发帧蒸发 |
| 契约对齐 | 抽 ws-contract「数据对象」formulation 字段名与 schema 比对，防两端漂移 |

- **分步冒烟**：构建顺序每步完成即跑对应用例（用例定义见 [acceptance-v1.md](../tests/acceptance-v1.md)「三链路验收」，后端链路判据见「10. 验收（后端视角，4 用例）」），不全套重跑
