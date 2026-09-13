# 后端实施方案 · 技术原型

> **权威源**:`architecture-spec.md`(架构)· `ws-contract.md`(契约)
> **不管面**:机制/参数=spec,消息格式=ws-contract,本文件不复制;日志红线单源=ws-contract §9。
> **目标**:技术原型后端——跑通三路路由全链路(危机闸门 / 分类器 / 多轮采集 / Agent / 记忆 / 语音),日志与审计齐备。

---

## 1. 技术栈

| 项 | 选型 |
|---|---|
| 框架 | FastAPI + WebSocket |
| Agent | LangGraph 1.x(确定性 StateGraph,条件边编排) |
| 环境 | uv(python)|
| 日志 | loguru(双输出:控制台彩色 + 文件结构化)|
| 存储 | SQLite(冷层)+ Redis(热/温层)|
| 语音 | CosyVoice 2(TTS,情感标签)+ SenseVoice(ASR,含情感识别)|
| LLM | DeepSeek(OpenAI 兼容)+ Ollama 本地,双源抽象 |

---

## 2. 模块职责表

> **目录风格**:一个职能一个深模块目录——对外接口小,背后行为多;删除测试:删掉该目录,复杂度应消失而非散到调用方;文件不散放 app 根。
> **文件真源=文件系统**:本表只记职责与接口;文件增删改不回本表,**职责变化才改行**;接口相关事实留接口列,纯实现细节由代码落地时入该模块 docstring、同 commit 出表。

| 模块 | 职责 | 关键接口 |
|---|---|---|
| app/main | 入口装配 | 挂 /ws·/station·/admin |
| ws_gateway | 连接/发号/抢占/消息分发 | 每条 user_input 先过闸门;S→C 帧统一盖章即发(发号与帧映射=§8);error 帧收口 |
| admin | 管理通道 REST | — |
| config | 模型配置 | LLM/ASR/TTS 读环境变量;config 传递 emitter |
| logger | 日志与审计 | 双输出+危机审计(§9) |
| router | 闸门+分类+话术 | gate.check(text)→GateResult{hit, matched: list[str], severity: float}(hit=severity≥阈值,阈值=配置;matched 供审计;词典+打分=实现细节,落地入 docstring) · classifier→{route,label,conf} · phrases=预设话术库(安抚/承接/邀请/危机,场景×情绪组织,不经 LLM);隔离约束=spec §4 L3 |
| collect | 采集三件 | 预置问题库(按空缺字段组织)/充分度(sufficiency(f)→float,权重表=实现细节落地入 docstring)/三降级检测;管状态不管话术=spec §4 L4 |
| agents | 图编排+共享黑板 | CollectState 17 字段(§3,answer/collect 共用)·图出口=CollectEvent(§3.4)·确定性条件边分派;Agent 名单=spec §4 L5 |
| rag | 检索三件套(混合知识库) | retrieve(query, k=None, *, library=CASE)·ingest(refs, *, library, reset=False)·RagLibrary{KNOWLEDGE, CASE};Ref={id, question, answer, score, category}(k=None→配置默认);两 Chroma 集合=hrp_kb_knowledge(科普知识库,answer 直答用)·hrp_kb_case(案例库,collect/station 用);Chroma+bge-m3·BM25+jieba·bge-reranker-v2-m3;深模块:两库/召回融合重排/分批/BM25 回建藏模块内,调用方只传 library;ingest 脚本与 Chroma collection 归本模块,数据对接走 docs/architecture/data-contract.md(换 embedding 模型=重跑 ingest,代码不动) |
| llm | LLM 双源 | LLMProvider:chat(messages)→str · stream(messages)→Iterator[str] · chat_json(messages, schema)→T(Message={role, content});出错抛 LLMError,由调用方捕获后降级到话术库;DeepSeek/Ollama 同接口由 config 切换(§7) |
| memory | 热/温/冷记忆+治理 | snapshot(session_id)→SessionContext · append_turn(session_id, role, text)(热层轮次原话,ADR-005) · save_round_summary(session_id, summary) · record_mood(mood)(同日同源 upsert,最新胜);层介质与 TTL 单源=spec §4 L7(数值不复制) |
| voice | 语音引擎 | transcribe(audio: bytes)→str(ffmpeg 转码在内)·tts_stream(text, emotion_label)→Iterator[bytes];ASR(SenseVoice;ffmpeg 转码 webm/opus→wav16k 后进引擎,只取转写文本(情感识别结果丢弃),音频即弃)·TTS(CosyVoice 2;念=开场安抚/总结+邀请/危机;失败跳过音频,文字照常收尾)·fillers=预生成等待语音文件(与 TTS 同音色;切块直发 audio_chunk,零运行时合成) |
| station | 补给站 REST+方案书存取 | 端点单源=ws-contract §1;懒生成素材 station:input(§3.3);SQLite reports 表(每会话只留最新一份) |
| schema | 契约类型单源 | Pydantic 对齐 ws-contract(formulation+ws_messages);契约对齐测试抽 ws-contract §5.1 字段名与本端比对,防两端漂移(§11) |

> **鉴权决策(原型期,显式裁定)**:station/admin REST **不鉴权是有意取舍**——依赖默认绑定 127.0.0.1 + CORS 白名单;局域网/公网暴露前必须加会话信物(D1 部署文档护栏,验收按此作答)。

---

## 3. 采集驱动与图内黑板(CollectState)

### 3.1 驱动模式

- 每条 user_input = **一次短图调用**:网关先过危机闸门 → 未命中则带着现有 CollectState 调图,跑到「等待下一条输入」或「回合终结」即返回
- CollectState 挂在 **WS 连接对象**上,图节点只读写、不持有;同一时刻至多一个调用在跑
- 销毁触发点(任一即弃,不抢救):done 发出 · 新 user_input 抢占 · 超时 · 危机命中 · 断线/进程重启
- 相位不落 state:下一步动作由条件边纯函数 `where_next(state)` 从 route/degrade_reason/sufficiency/round_index 算出,出口事件见 §3.4,分派图见 §5

### 3.2 CollectState 字段(17)

**A · 身份与路由(网关写入,图内只读)**

| 字段 | 类型 | 初始值 | 写入者 |
|---|---|---|---|
| session_id | str | 连接分配 | 网关(entry) |
| route | `"answer"\|"collect"` | 分层判定 | 网关(entry),图内不可变 |
| template | TemplateId\|None | collect→`beck_formulation`;answer→None | 网关(entry) |
| emotion_label | str\|None | 快速研判标签 | 分层判定一次写入,图内不回写 |
| confidence | float | 分层判定 conf | 分层判定(留档调试) |

**B · 采集进度(图内写入)**

| 字段 | 类型 | 初始值 | 写入者 |
|---|---|---|---|
| formulation | Formulation | 全 null | entry 粗稿(填 emotion)→ 轮次填格 → 分析(emotion_review 合入) |
| round_index | int | 0 | 轮次处理(每条回答 +1) |
| sufficiency | float | 0.0 | 充分度打分(每次填格后重算,§4) |
| degrade_reason | DegradeReason\|None | None | 降级检测;None=未降级,布尔派生 |
| pending_question | PendingQuestion\|None | None | 共情陪伴者发问时写,下条回答消费(回答填哪格由它定) |
| max_rounds | int | 配置注入(上限 3,spec §4 L4) | 网关(entry) |
| escalated | bool | False | risk 复核命中写 True → 调用即止,网关转危机序列+审计 |

**C · 上下文(网关写 entry;图内只读/追加 turns)**

| 字段 | 类型 | 初始值 | 写入者 |
|---|---|---|---|
| turns | list[Turn](追加式) | [] | 网关(entry input 为 turns[0])→ 轮次节点(问答追加) |
| session_context | SessionContext | 记忆层快照 | 网关(entry),回合内不刷新 |

辅助类型:`Turn={role:"user"|"assistant", text:str}` · `DegradeReason="too_short"|"off_topic"|"negative"` · `PendingQuestion={text:str, target_field:FieldKey}` · `SessionContext={history_summary:str|None, mood_recent:list[MoodKey], recent_turns:list[Turn]}`(温层摘要+冷层心情+热层轮次原话(ADR-001/005),来源=memory/)

脱敏:state 含用户原文,只活连接内存;日志只记长度/哈希(§9);落盘唯一出口=回合结束 station:input(3.3)

### 3.3 回合生命周期

```
entry 调用:粗稿 draw(emotion=快速研判标签)→ 确认+第 1 问
每轮:softscan 软预筛+新增命中 LLM 复核(spec §4 L5「每轮预筛/命中复核」;
  risk_reviewed_terms 去重,同一软词整会话只复核一次)
轮次调用:填 formulation → draw 增量 → 充分度重算 → where_next
  → 继续问:确认+第 i 问(陪聊轮不填格、无 draw)
  → 终结:充分度 ≥0.7 ｜ round_index ≥ max_rounds ｜ 降级收尾
终结调用:risk 增量复核(命中→escalated=True 即止)→ emotion_review 合入 → 精稿 draw → 总结+邀请语 → done
回合结束(网关三动作):温层写本回合摘要 → Redis 写 station:input{formulation,summary}(TTL 7 天)→ 弃 state
```

**每轮输出(共情陪伴者结构化)**:
```json
{ "confirm": "被否定不等于你不配。", "next_question": "当时脑子里闪过了什么念头？", "target_field": "thought" }
```

### 3.4 图出口事件(CollectEvent)

每次图调用结束时只产出一个事件,网关按事件收尾,不读 state 内部字段:

```
CollectEvent =
    AskNext{confirm, next_question, target_field}    # 继续问,共情陪伴者产出,写入 pending_question
  | EmpathChat{reply}                                # 陪聊轮:不填格、无 draw
  | Finish{cause}                                    # cause = "sufficient" | "max_rounds" | DegradeReason
  | Escalate                                         # risk 复核命中,escalated=True 即止
```

网关收到 AskNext/EmpathChat 就等待下一条输入;Finish 触发回合结束三动作(§3.3);Escalate 转危机序列并落审计(§6)。帧不进事件,由 emitter 直发(§8)。

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

## 5. LangGraph 图定义(骨架)

> Agent 职责/激活/安全边界单源=spec §4 L5。

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

- **gate.py**:危机词典 + 严重度打分(硬判,目标 ≤10ms/条),与 L6 规则引擎**共享单一词典来源**
- 词典/降级阈值 = 配置数据,MVP 最小占位(危机核心词先跑),内容运行时补
- 每轮输入过 gate;命中 → CRISIS,落**审计日志**(WARN:命中项 + 是否转热线,不含原文)
- **risk.py**:软信号关键词预筛(低档位)→ 命中才 LLM 复核,控成本

---

## 7. LLM 双源抽象

```python
# llm/provider.py —— OpenAI 兼容统一入口
# DeepSeek: base_url=https://api.deepseek.com, model=deepseek-v4-flash
# Ollama:   base_url=http://localhost:11434/v1, model=qwen3:8b(示例)
# 由 config.py 切换;R3 配置 UI 后续接管
```

> **provider 策略(mock 边界)**：
> - 真 provider：LLM(DeepSeek/Ollama) · ASR(SenseVoice/FunASR) · TTS(CosyVoice 2) · Live2D 真模型打包 · 记忆 SQLite 真存
> - **RAG = 预置问答对灌入 Chroma 跑真检索**(种子语料)；数据集就绪 = 往 Chroma 加数据，代码不变
> - 配置占位：危机/软信号词典、降级阈值(结构定、内容后补)
> - 收尾优化：本地兜底，单机离线演示
> - 不 mock 边界：契约(ws-contract)/WS 网关/采集状态机/充分度/黑板渲染 全真实现；provider 抽象接口保留，真实现与兜底同接口

---

## 8. WS 网关

- 每连接:建 session_id;`user_input/mood_select` 入口;输入单源文本(语音经 `/asr/transcribe` REST 转写预览、用户确认后按文本发送,ADR-004;网关无 audio 分支)
- **发号**:所有 S→C 帧经网关发送函数,盖章即发送(seq 预增,首帧=1);仅 draw/text_delta/audio_chunk/done 消耗号,first_frame/error 不带不消耗;计数器=连接对象内存(会话内全局递增,契约 §3.2)
- **两条来路**:网关直发(first_frame/危机序列/error/done);图内 emitter 注入(config 传递,不进 state)发 draw/text_delta/audio_chunk——Emitter 协议三方法:draw(formulation) · text(s) · audio(chunk)
- 抢占:等待期=弃 state 直接 entry(安抚语用承接变体);分析中=cancel 图调用 + 旧 emitter 标记 dead(未发帧蒸发)→ entry;前端淡出停播(frontend-plan §6)
- 非法消息 → `error(invalid_message)`;超时(锚点=契约 §7)→ `error(timeout)` + 降级话术 + done;异常 → `error(server_error)`

**帧映射(发射侧唯一事实)**

| 帧 | 发送者 | 触发 | data 来源 |
|---|---|---|---|
| first_frame | 网关 | 分层判定 collect/crisis 后、进图前 | route/template/emotion_label + phrases.py 安抚语(冷启动/承接变体) |
| draw | emitter | 节点改 formulation 后显式发;粗稿/逐轮/精稿同一调用,全量 | state.formulation |
| text_delta | emitter | 共情陪伴者话术(1~2 帧)· 知识直答/分析总结流式(攒批:~100ms 窗或 ~30 字,每批一帧)· 邀请语(话术库模板,总结末尾) | 对应文本流 |
| audio_chunk | 网关+emitter | 网关:安抚语/危机话术/等待语音(voice/fillers 文件切块直发;分析开始即播,卡死 15s 播第二句);emitter:总结 TTS | CosyVoice 流式 / 预生成 wav(同音色) |
| done | 网关 | 图调用终结且 emitter 排空 → 随后回合结束三动作(§3.3) | — |
| error | 网关 | 非法/超时/异常 | code + message(契约 §3.7) |

- 危机序列(网关,闸门任意命中):first_frame(crisis) → draw(stage_map) → text_delta(热线话术) → audio_chunk(平静语气,失败跳过) → done + WARN 审计(§6)
- mood_select:独立到达=短安抚 text_delta + done;回合内=仅更新 profile 不回帧(契约 §4.2)

---

## 9. 日志(双输出,对齐 ws-contract §9)

双输出(loguru 控制台彩色 INFO + 文件 DEBUG)与脱敏/审计硬约束单源 = ws-contract §9;本节不复制参数(轮转/保留数值)与红线细则。

---

## 10. 验收(后端视角,4 用例)

用 WS 客户端或脚本各跑一遍,查链路消息顺序 + 日志:

1. **answer**:`user_input("什么是正念")` → text_delta 流式 → done;无 draw
2. **collect**:`user_input("最近很焦虑睡不着")` → first_frame → 2 轮 draw 增量 → 精稿 → 分析总结+心灵补给站邀请语 → done(方案书由用户点击补给站触发,不在回合内);日志含 `crisis_gate_hit(hit:false)`、`route_decided(collect)`、`sufficiency_scored`
3. **crisis**:`user_input("我不想活了")` → first_frame(crisis) → 热线内容;日志含 **crisis_gate_hit(hit:true, audit)** 审计
4. **voice**:`POST /asr/transcribe`(webm/opus base64 → 转写文本,前端回填确认后按文本发送,ADR-004;音频转写后即弃)+ 安抚语与总结各出 audio_chunk ×N;分析中发新 user_input 抢占 → 未发帧蒸发 + 新 first_frame(承接安抚语);日志无音频无原文

---

## 11. 测试

- **框架与布局**:pytest(已配);测试文件放 `tests/`,一接缝一文件,文件名即接缝名,不设 unit/integration 分层
- **接缝钉测试**(只钉接缝,不测内部):

| 接缝 | 测什么 |
|---|---|
| gate.check | 命中/未命中/阈值边界;matched 覆盖审计所需命中项 |
| sufficiency | 字段组合覆盖权重;停采两档边界(数值单源=§4) |
| retrieve | 种子语料命中(id/question 稳定返回);k 截断 |
| where_next | CollectEvent 四变体各分支:继续问/陪聊/终结三因/升级 |
| LLMProvider | chat_json 校验失败路径;LLMError 降级(stub 实现) |
| Emitter | dead 标记后发帧蒸发 |
| 契约对齐 | 抽 ws-contract §5.1 字段名与 schema 比对,防两端漂移 |

- **分步冒烟**:构建顺序每步完成即跑对应用例(用例定义单源=docs/tests/acceptance-v1.md §1,后端链路判据见 §10),不全套重跑
