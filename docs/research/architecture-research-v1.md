# 架构研究记录 v1 · 多 Agent 编排与核心机制定案

> **日期**：2026-08-22 · **状态**：已定案
> **性质**：决策记录（ADR）——记录**为什么这么定**与证据；"现在是什么"以 5 份开发文档为准，本文件不作为实现依据被引用。
> **产生方式**：grilling 会话逐题决策；所有外部证据为当日实时查证（来源见 §3）。
> **配套**：本文 §5 为文档修改清单（A 范围·最小修改已批准）；§6.2 为 B 任务（文档规范化重构）待办，**执行前需再次审查讨论**。

---

## 0. 决策台账（速览）

| # | 问题 | 定案 |
|---|---|---|
| A1 | seq 语义两文档矛盾 | 以 ws-contract 为准：**会话内全局递增**；修 backend-plan §8 |
| A2 | ws-contract mood 示例值越界 | 示例改用 6 档内取值 |
| Q1 | L3 轻量分类器机制 | **分层判定**：规则先判 → 模糊才 LLM；低 conf 兜底 collect |
| Q2 | 多 Agent 编排 | **确定性 StateGraph**；监督者除名（职责三拆）；去 `langgraph-supervisor` 依赖 |
| Q3 | 分析型/建议型分流 | **废除互斥分流**：分析总结必给；方案书 = 用户点击"心灵补给站"触发的懒生成 |
| Q4 | 边采边算 | **MVP 用降级档**：停采后同步分析；`ANALYSIS_RUNNING` 留二期接口位 |
| Q5 | Redis 存废 | **上真 Redis**：本机 Docker Desktop 容器化 |
| Q6 | RAG 检索管线 | **三件套直接上**：Chroma+bge-small-zh-v1.5 / BM25+jieba / bge-reranker-v2-m3 |
| Q7 | L6 计划工具（日历/量表） | **不做**，二期（含"效果闭环"叙事价值，见 2.8） |
| B8 | ASR 音频链路 | webm/opus → **ffmpeg 转码** → SenseVoice；环境手册补 ffmpeg |
| C | 数据货币专项 | CollectState（14 字段）+ 事件→帧映射 + 语音念点/等待语音/承接语——**已定案**（§4） |

---

## 1. 背景与排查结论

**起因**：怀疑开发文档（CLAUDE.md 索引的 5 份）实现细节可能误导编码。排查证实：

- **2 处文档间硬矛盾**（A1/A2，有行号证据）；
- **7 处实现机制缺口**（B1~B7：只写"做什么"、没写"怎么做"，编码者被迫自由发挥）；
- **1 处链路缺口**（B8：音频格式契约与 ASR 引擎输入不衔接）。

**架构理解基线**（grilling 开场对齐通过）：一条 WS 连接 → L3 确定性危机闸门 → 轻量分类器三路（answer 直接答 / collect 多轮采集 / crisis 热线）→ L4 状态机管轮次、L5 Agent 管话术 → 黑板同图增量 → 停采后分析总结 → 记忆分层。铁律不变量：危机只在后端、emotion_label 不进路由、黑板=模板+全量 formulation+seq、信念字段可留白、音频转写即弃。

---

## 2. 决策记录

### 2.1 Q1 · L3 分类器：分层判定

**背景**：全文档只有一行"轻量分类器(route+emotion_label+conf)"，机制未定。三路路由的心脏。

**选项**：a 纯规则 / b 本地小模型 / c 每轮 LLM / **d 分层（定案）**。

**定案**：
- 规则先判明显 case（问候、明显知识词表），**模糊才调 LLM** 拿 `{route, emotion_label, confidence}`；
- 规则路径 conf 给保守值；LLM 低 conf → 兜底 collect（collect 比 answer 安全：错了只是多问一句）；
- RAG 门控（"知识查询才检索"）复用同一分层判定，与 V2.5 风险"预筛→复核"**同构**，架构叙事统一。

**依据**：CLAUDE.md 成本约束（LLM 每轮调用是热点）；两级标签设计（快速研判=关键词级）本已暗示分层。

### 2.2 Q2 · 多 Agent 编排：确定性 StateGraph

**背景**：原设计 5 Agent（监督者+四个业务 Agent），技术栈钉 `langgraph-supervisor`（LLM 动态派活）。用户直觉为"主管+技术团队"主从式。

**关键事实**：本流水线所有管理决策已被上游写死（route 由 L3 规则、轮次/充分度/降级由 L4 状态机），LLM 主管决策空间为零。

**选项**：a 确定性图（定案）/ b LLM supervisor / c 混合。

**证据链**（§3 链接）：
1. langgraph-supervisor-py 官方 README 顶部声明：大多数场景推荐**直接用工具手工实现**而非本库；
2. Anthropic《Building Effective Agents》：Workflow（预定义代码路径）vs Agent（LLM 自主决策）；可预测任务用 workflow；
3. 社区量化：3 Agent 的 supervisor 系统最少 7 次 LLM 调用（1 派活+3 干活+3 回收评估）；共识判据"路由可预写→确定性图"；
4. b 违反自家铁律：V2.3 确定性、验收用例需可复现、成本热点。

**定案**：
- 图形态：LangGraph `StateGraph`，**允许环**（采集循环=条件边回指，非 DAG）；
- 监督者职责三拆：委派→L3+L4+条件边函数（`where_next` 类纯 Python）；验收→gate 复查/充分度打分/**risk 软预筛→LLM 复核（唯一保留的 LLM 验收点）**；汇总→图 state 黑板+empath 收口；
- 触发机制：拆解只在入口发生一次（gateway+L3→`CollectState`）；Agent=被动函数，由条件边"叫号"，入参为共享黑板而非原始消息；
- 依赖：`langgraph-supervisor` 移除，仅留 `langgraph`；
- **答辩叙事**："四个语义专家+确定性监督编排（L3 门控+L4 状态机+条件边），管理开销为零、行为可复现，唯一 LLM 验收点=风险复核"；
- **二期 revisit 判据**：出现"任务分解不可预知"的功能（开放式知识图谱探索、工具自主规划）时，按官方推荐的手工工具式 supervisor 重新评估（仍不用库）。

### 2.3 Q3 · 分流重设计：心灵补给站

**背景**：原"分流"=停采后互斥二选一（分析型总结 / 建议型方案），**判据全文档未定义**（B2）。用户预期：总结必给、方案可选、用户主动取。

**定案**（废除互斥分流）：

```
collect 停采 → 精稿 draw → Live2D 人话总结（必发生）
     → 总结末尾拼"心灵补给站"邀请语（固定模板，不让 LLM 自由发挥）
     → 用户点击工具栏"心灵补给站"图标 = 触发 + 查看
     → planner 异步生成方案书（懒生成：默认不生成，点击才触发）
     → 面板等待态"正在为你整理…" → md 预览 → 可导出 md/pdf
```

- **组件名**："心灵补给站"（弃"诊疗方案书/诊疗报告"——医疗术语，与"非医疗诊断"红线冲突）；
- **邀请语（承诺式将来时，用户原案 95% 保留）**："通过我们的沟通，我可以为你起草一份观察总结，里面包含一些生活调整的小思路。我会把它放在'心灵补给站'。如果你觉得今天状态还不错，有兴趣的话可以去取来看看；如果你觉得现在不想看，或者还没准备好，完全没关系，它会一直在那里等你，你想好了再去拿。"
- **懒生成 vs 预生成**：懒生成（省 planner 调用），话术用承诺式时态弥合"已放好 vs 点击才生成"的错位；等待态演出承接；
- **REST 通道**（WS 8 消息零改动，复用契约 §1 管理通道先例）：`POST /station/report/generate`（点击触发）+ `GET /station/report/latest`（轮询）；
- **存储**：SQLite 冷层 reports 表（持久化）；**MVP 只留最新一份**（按 session 覆盖），历史列表二期；
- **空态**："这里还空着——等我们完成一次完整的梳理，我会为你准备一份"；
- **crisis 不生成**（V2.9 危机绕过 planner 不变）；
- **前端**：frontend-plan 工具栏范围+目录树补"心灵补给站"组件。

### 2.4 Q4 · 停采后分析：降级档 + analysis_node 规格

**背景**：V2.6"边采边算"三处文档互相矛盾（V2.6 留降级条款 / backend-plan 画 ANALYSIS_RUNNING / §10 列入 MVP），且"后台分析算什么、结果怎么用、竞态怎么办"均未定义（B3）。

**选项**：a 降级档（定案）/ b 真边采边算 / c 仅预跑检索。

**定案**：MVP 停采后同步分析；前端现成 `analysis→"收尾中"` 状态承接；`ANALYSIS_RUNNING` 标注二期接口位。选 a 的合法性：V2.6 自留降级条款且"协议不变"。

**analysis_node 规格**：
```
触发：STOP（充分度≥0.7 ｜ 轮数上限 ｜ 降级收尾〔formulation 允许带 null〕）
输入（此刻 formulation 已冻结，零并发）：完整 formulation + 本轮对话轮文（内存传递不落盘）+ L3 快速研判标签
处理：RAG 门控判定（知识相关才检索）→ 一次 LLM 结构化输出
输出与分发：
  ① emotion_review {label?, intensity?} ──非空才合入──▶ 精稿 draw（全量 data，seq+1）
  ② summary ──▶ text_delta ×N 流式，末尾拼"心灵补给站"邀请模板
  ③ knowledge_refs ──▶ 仅作 summary 上下文，不单独发前端
时序：draw(精稿) → text_delta(总结+邀请语) → [audio_chunk 可选] → done
```

**竞态结论**：降级档下版本/取消/游离写者问题整体消失。仅剩"分析等待期用户抢占"一种情况——单执行流内取消/丢弃 + text_delta 自带 seq（会话内全局递增、前端忽略旧帧）天然兜底，无需专门代码。

**b 方案难处存档**（二期设计输入）：版本作废、抢占取消（流式 HTTP cancel 有坑且可能照计费）、游离任务绕过图运行时双写 state、进程重启任务蒸发需内嵌同步兜底（复杂度叠加非替代）、超时联动。二期设计要点：formulation 版本号+可取消任务。

### 2.5 Q5 · Redis：上

**背景**：spec/backend-plan 均钉 Redis，但 Windows 无官方原生版，环境手册未装（B5）。

**事实**：本机已有 Docker Desktop 29.1.5（WSL2 后端）→ 最大门槛消失，实际成本 ≈30 分钟。

**定案**：真 Redis，Docker 容器化：
```bash
docker run -d --name mha-redis -p 6379:6379 --restart unless-stopped redis:7-alpine
```
- 代码：`uv add redis`；`hot.py`/`warm.py` 用 redis-py `set/get` + 原生 TTL（30min/7 天语义不变）；
- 配置：`.env` 加 `REDIS_URL=redis://localhost:6379/0`；
- 启动顺序：Docker Desktop 先起（容器自启）→ 后端；
- 可选保险（15 行）：连接失败降级内存 + WARN 日志，防演示翻车。

### 2.6 Q6 · RAG 三件套：直接上 + embedding 选型

**背景**：spec 写三件套，种子语料仅 10~20 条，原疑虑 BM25/重排杀鸡牛刀（B6）。用户定夺：三件套直接上，增益等真数据再评。

**embedding 调研结论**（当日查证）：
| 模型 | 体积 | 档位 |
|---|---|---|
| **bge-small-zh-v1.5（定案）** | ~100MB | C-MTEB 小模型第一梯队，CPU 百 ms 级 |
| Qwen3-Embedding-0.6B | ~1.2GB | MTEB 多语言登顶家族最小规格，备选 |
| BGE-M3 / GTE | 2GB+/400MB | 主流 |

维持 bge-small-zh-v1.5 的理由：混合检索（BM25+重排）补偿单一 embedding 弱点；100MB 体积与 CPU 速度是演示实利；**不锁死**——换模型=重跑灌库脚本，代码不动。

**实现细节**：BM25 中文必须先分词（依赖 `rank-bm25 + jieba`）；重排模型 `BAAI/bge-reranker-v2-m3`（~2GB，候选量级小、CPU 可跑）。

### 2.7 Q7 · 日历/量表：二期

**背景**：spec §4 L6"计划工具：日历/量表（供计划制定者调用）"与 §10 MVP 范围矛盾（B7）。 planner（Agent）本身 MVP 必在——方案书生成者；日历/量表是其**附属工具**。

- **日历**=执行层：方案条目变时间线打卡+依从性反哺记忆；
- **量表**=度量层：PHQ-9/GAD-7 类自评，量化方案效果（"自评分 12→8"）；
- **定案**：MVP 不做，纯"RAG+formulation→方案书"；二期再做，且**保留量表想法**（"效果闭环"答辩素材）。合规注意：量表只能呈现为"自我觉察"，禁"诊断/筛查出 XX 症"措辞。

### 2.8 B8 · ASR 音频链路

契约定 `user_input.audio` = base64 webm/opus ≤15s；SenseVoice/funasr 不直接吃 webm → **ffmpeg 转码**（wav 16k）后进引擎。落地：环境手册补 ffmpeg 安装（Windows：winget/官网）；`asr.py` 转码职责注明；音频转写即弃红线不变。

---

## 3. 证据源（当日实时查证）

| 来源 | 用途 |
|---|---|
| https://github.com/langchain-ai/langgraph-supervisor-py （官方 README 顶部 Note） | Q2：库作者劝退默认用法 |
| https://www.anthropic.com/engineering/building-effective-agents | Q2：Workflow vs Agent 官方方法论 |
| https://myengineeringpath.dev/genai-engineer/langgraph-multi-agent/ | Q2：supervisor 7 次调用量化 |
| https://medium.com/@subratati/langgraph-in-production-choosing-and-building-multi-agent-systems-c2b955f16429 | Q2：生产选型判据 |
| https://focused.io/lab/multi-agent-orchestration-in-langgraph-supervisor-vs-swarm-tradeoffs-and-architecture | Q2：模式对比 |
| https://qwenlm.github.io/zh/blog/qwen3-embedding/ | Q6：Qwen3-Embedding 家族 |
| https://github.com/ForceInjection/AI-fundamentals/blob/main/07_rag_and_tools/rag_basics/chinese_rag_embedding_model_selection.md | Q6：中文 embedding 选型 |
| https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models | Q6：2026 开源 embedding 综述 |
| https://www.memurai.com/ · https://redis.io/tutorials/howtos/how-to-run-redis-on-windows-natively-with-memurai/ | Q5：Redis Windows 现状 |
| PyPI JSON API（funasr/langgraph/fastapi/chromadb requires_python） | 主分支 Python 3.10 定案 |
| https://github.com/QwenAudio/CosyVoice （原 FunAudioLLM/CosyVoice 已 301 迁移） | 主分支语音安装路径 |

---

## 4. 数据货币专项定案（2026-08-23/24 · grilling 第二轮）

> 承接 §0 台账"数据货币三件套"待办。硬约束全程未破：契约 8 消息不变；seq 会话内全局递增；analysis_node 输出分发按 §2.4；类型只定义一份（Pydantic⇔TS 同构，字段名=模板 fields key）。
> 现行规则已落 ws-contract（W1~W4）/ backend-plan（B1~B5）/ frontend-plan（F1~F2）/ CONTEXT（等待语音、承接安抚语两词）；本节记**为什么**与取舍。

### 4.1 C1 · 状态边界：危机不入图，全图一份状态

- 危机闸门放**网关**：每条 user_input 进图前先过闸门；命中 → 网关直出危机序列 + WARN 审计 + 弃回合状态。理由：①闸门铁律=规则确定性、作用于每条输入——所有 user_input 天然先到网关，图内无需各节点自查；②审计单点落网关；③图内只剩 answer/collect 两条纯业务流，危机路径零 LLM 零图开销。
- answer/collect **共用同一份 CollectState**（answer 只填 route/turns，采集字段全空），不搞两套类型；formulation 字段引用领域货币（schema/formulation.py，类型单源）。

### 4.2 C2 · 驱动模式：短调用 + 网关持有

- **定案**：每条 user_input = 一次短图调用；网关在两次调用间保管 CollectState（挂 WS 连接对象）。抢占/超时=丢弃状态；仅分析中抢占需 cancel 前台任务。不上 checkpointer。
- **落选**：整回合一次长调用 + interrupt 挂起——跨调用恢复要 checkpointer，抢占要取消半成品执行流（§2.4 存档的 b 方案难处）。
- 生命周期 5 销毁点：done / 抢占 / 超时 / 危机命中 / 断线重启。**断线=回合作废不抢救**——重连恢复的是记忆（热层），不是半成品回合；黑板无重同步帧，作废最诚实。
- 相位不落 state：`where_next(state)` 纯函数从 route/degrade_reason/sufficiency/round_index 算下一步，相位与字段永不打架。

### 4.3 C3 · 字段表：14 格（现行单源=backend-plan §3.2）

- degrade_reason 单字段、布尔派生——不存两个会打架的字段；
- pending_question 显式存——跨调用记住"上一问问的哪个字段"，回答填格路由靠它；
- 顶层 emotion_label 只写一次（分层判定）；分析修订只进 formulation.emotion——契约无表情更新帧，回写了也发不出去；
- escalated（自查补的第 14 格）：risk 复核命中写 True → 调用即止 → 网关发危机序列+同款审计（危机不入图的配套出口）；
- 「回合由抢占而建」只做网关局部变量（选承接安抚语用完即弃），不进 state——图内无消费者，加进去即污染。

### 4.4 C4 · 回合边界一进一出

- 进：SessionContext 快照两字段（history_summary=温层摘要、mood_recent=冷层心情），entry 抄一次、回合内不刷新、图内只读。
- 出：心灵补给站懒生成素材 = {formulation, summary} 写 Redis `station:input:{session_id}`（TTL 7 天，覆盖式）；**不含 turns 全文**——对话原文回合结束即蒸发，素材给结构化结论就够。
- 回合结束三动作：温层写本回合摘要 → 写 station:input → 弃 state。

### 4.5 C5 · 发帧机制：emitter 注入

- **定案**：帧唯一出口=网关发送函数（盖章 seq→发送；单事件循环，发送序=因果序）。图节点经 config 注入 emitter 显式声明 draw/text_chunk；first_frame/危机序列/error/done 由网关直发。emitter 不进 state——state 保持纯数据，无 WS 可单测。
- **落选 a**（状态 diff 自动推导）：精稿 draw 会被总结流式 text_delta 抢到前面，违反 §2.4 时序。
- **落选 b**（事件列表进 state）：流式做不到边生成边发，且 state 不再纯数据。

### 4.6 C6 · seq 与抢占

- 发号：pre-increment 首帧=1；仅 draw/text_delta/audio_chunk/done 消耗号；first_frame/error 不带不消耗；text/audio 攒批（~100ms 窗或 ~30 字）每批一号。
- **计数器位置（会话内自纠）**：初版定 Redis INCR 防断线重连误杀——重读发现 CONTEXT 已定义"会话=单 WS 连接生命周期"，计数器住连接对象即满足"会话内全局递增"；误杀坑由契约 §3.1"first_frame 重置 seq 基线"承重（该行由疑似废话变承重墙，配套 W1 消歧）。Redis 出局：少一个机制、少一个降级分支。
- 抢占两场景：等待期=弃 state 直接 entry；分析中=cancel + 旧 emitter 标记 dead（**未发帧在发送前蒸发**）→ entry。已发帧靠 TCP 单连接有序必先于新 first_frame 到达，前端重置翻篇；draw 的 seq 忽略=双保险。原则：**能在发送前丢的绝不靠前端丢**。
- 超时锚点=后端处理单条 user_input 的时长（W4）——用户思考期不计时。

### 4.7 C7 · 语音：念三处 + 等待语音 + 降级

- **范围修正**：初判"TTS 二期占位"误读了构建顺序——文档事实是语音在 MVP（backend-plan 技术栈 / voice 双文件 / 真 provider / B8 链路）。实装并收窄：
- **念=三处**：开场安抚语 / 总结+邀请语 / 危机话术（平静语气预设，不喂情绪标签）；逐轮问答不念（拖节奏、演示噪音）。TTS 情感参数喂 formulation.emotion.label（=术语"情绪一源三用"）。
- **等待语音**（用户提议）：空窗期 filler 用 CosyVoice **同音色预生成**为文件（每句几百 KB），分析开始即播、卡死 15s 播第二句；文件切块直发 audio_chunk，零运行时合成；TTS 挂了照样播（演示保险）。逐轮间隙不播。
- **打断的"高情商"取舍**：采纳=承接安抚语（抢占建回合的话术库变体，搭 first_frame.text 槽位）+ 前端音频 ~100ms 淡出停播；否决=LLM 动态过渡语（预设优先哲学+危机确定性）、字级视听同步（当前拓扑文字先流完语音跟上，无对齐需求）、按响应时间动态路由（原无可路由的等待话术语音；等待语音落地后二期重估）、后端流式无缝拼接（需改契约改架构）。
- ASR：mode=audio 全程可用，ffmpeg→SenseVoice→文本即弃；**只取转写文本，情感识别结果丢弃**（接入即绕过分层判定，违反隔离不变量）。
- 降级：TTS 失败/超时 → 跳过 audio_chunk 直接收尾，文字照常。

### 4.8 C8 · 事件→帧映射表（决策版；现行单源=backend-plan §8 + ws-contract §6）

| 阶段 | 触发 | 帧 | seq |
|---|---|---|---|
| 进入 | 闸门命中（任意时刻） | first_frame(crisis) → draw(stage_map) → text(热线) → audio(平静预设) → done + WARN 审计 | 后四类各消耗 |
| 进入 | 分层判定=collect | first_frame(冷启动/承接变体安抚语) → audio(安抚语 TTS) | — / +N |
| 进入 | mode=audio | 无帧（转写即弃，与文字同流） | — |
| 采集 | entry 粗稿节点 | draw(粗稿，emotion=快速研判标签) | +1 |
| 采集 | 共情陪伴者发问 / 陪聊轮 | text_delta(1~2 帧；陪聊轮无 draw) | +1~2 |
| 采集 | 轮次填格完成 | draw(全量增量) | +1 |
| 分析 | 开始（网关 timer） | audio_chunk×N（等待语音文件） | +N |
| 分析 | emotion_review 合入（§2.4①） | draw(精稿) | +1 |
| 分析 | 总结流式 → 邀请语（§2.4②） | text_delta×N(攒批) → text_delta(固定模板) | +N+1 |
| 分析 | 总结 TTS | audio_chunk×N | +N |
| 终结 | 调用终结 + 排空 | done → 网关三动作（4.4） | +1 |
| 异常 | 非法 / 超时 / 异常 | error(无号)；超时补降级 text_delta + done | — / +2 |
| 抢占 | 等待期 / 分析中 | 见 4.6；新 first_frame 用承接安抚语 | — |
| mood | 独立 / 回合内 | 独立=短安抚 text+done；回合内=无帧仅 profile | +2 / — |

### 4.9 文档落点（本次执行清单）

W1~W4=ws-contract（seq 基线消歧 / §6.2 时序补全 / mood 回合内 / 超时锚点）；B1~B5=backend-plan（目录树 / §3 重写 / §5 risk 出口 / §8 发号与帧映射 / §10 语音验收）；F1~F2=frontend-plan（seq 基线对齐 / 淡出+队列）；C1=CONTEXT 新增"等待语音、承接安抚语"；PROGRESS 二期表 +3 行（字级视听同步 / 后端无缝拼接 / SenseVoice 情感输出接入）。CLAUDE.md 未动（3 条主验收判据保持）。

---

## 5. 文档修改清单（A 范围·已批准框架，执行前经用户过目）

> 执行顺序：**E0（git 基线）→ E8 → E1~E7 → 全库 grep 清扫**。清扫词：`langgraph-supervisor`、`监督者`、`边采边算`、`分流`、`ANALYSIS_RUNNING`。

**E0 · git 基线**（安全网）：`.gitignore` 移除 `Architecture`、`docs`（`.claude` 保留）→ `git add -A` → 提交"chore: 纳管架构与文档目录（修改前基线）"。

**E1 · backend-plan.md:142**（A1）：`seq` 回合内递增 → **`seq` 会话内全局递增（不随回合重置，对齐 ws-contract §3.2）**

**E2 · ws-contract.md:143**（A2）：示例 `"mood": "焦虑"` → `"mood": "低落"`（6 档内取值）

**E3 · architecture-spec-v3.md**（Q2/Q3/Q4，升 v3.1 并在头部注明变更来源=本文档）：
| 位置 | 改法 |
|---|---|
| :156 技术栈 | `LangGraph 1.x · langgraph-supervisor · 按需 handoff` → `LangGraph 1.x · 确定性 StateGraph（条件边编排，无 LLM 派活）` |
| :157 关键机制 | `监督者门控` → `条件边门控（确定性；risk 复核=唯一 LLM 验收点）` |
| :161 Agent 表 | 删"监督者"行 |
| :77-79 §3 分流段 | `→ 分流：分析型→… / 建议型→计划制定者生成方案（走 L6 工具）` → `→ 分析总结（Live2D 人话总结，末尾拼"心灵补给站"邀请语）→〔用户点击心灵补给站 → planner 异步生成方案书，懒生成〕` |
| :31 V2.6 行 | 追加 `；MVP 采用降级档（停采后同步分析）` |
| :34 V2.9 行 | 追加 `；已修订：方案书改为用户点击心灵补给站触发（research-v1 Q3）` |
| :174 L6 计划工具 | `日历 / 量表（供计划制定者调用）` → 追加 `（二期）` |
| :292 §10 MVP | `边采边算` → `停采后分析（边采边算降级档）`；`计划制定者（建议型分流）` → `心灵补给站（方案书懒生成 + md 预览/导出）` |

**E4 · backend-plan.md**（Q2/Q3/Q4）：
| 位置 | 改法 |
|---|---|
| :14 技术栈 | `LangGraph 1.x + langgraph-supervisor` → `LangGraph 1.x（确定性 StateGraph）` |
| :68 状态机 | `充分度 ≥0.4 → ANALYSIS_RUNNING(后台,边采边算)` → `充分度 ≥0.4 → ANALYSIS_RUNNING（二期接口位；MVP 不启动，停采后同步分析）` |
| :71 状态机 | `STOP → FINAL:精稿 draw + 分流(分析型/建议型)+ text_delta + done` → `STOP → FINAL:精稿 draw + 分析总结(text_delta) + 心灵补给站邀请语 + done` |
| :98-109 §5 图骨架 | `supervisor 每回合:` 全段重写为确定性条件边描述；planner 行 → `planner（心灵补给站方案书：用户点击触发，异步）` |
| :162 验收 2 | `分析型总结 或 建议型方案(按分流)` → `分析总结 + 心灵补给站邀请语（方案书由用户点击补给站触发，不在回合内）` |

**E5 · frontend-plan.md**（Q3）：
- §2 工具栏范围行：新增 `心灵补给站（方案书入口：MVP；点击触发生成 + md 预览 + 导出 md/pdf；分析总结末尾邀请语指向它）`；
- §2 目录树：新增 `station/StationPanel.vue # 心灵补给站：触发/等待态/预览/导出`。

**E6 · CLAUDE.md §8**（Q3 判据同步）：`精稿 → 分析型总结 或 建议型方案(按分流)` → `精稿 → 分析总结 + 心灵补给站邀请语（方案书=用户点击心灵补给站触发）`。其余判据（seq 单调、充分度、信念留白）**逐字不动**。

**E7 · ARCHITECTURE_PROGRESS.md §五**（唯一权威表）追加 5 行：
```
| 产品 | 日历/量表工具（方案书执行层+度量层） | research-v1 Q7 | 二期 |
| 智能 | 真·边采边算（formulation 版本号+可取消任务） | research-v1 Q4 | 二期 |
| 智能 | supervisor 模式 revisit（手工工具式，不用库） | research-v1 Q2 | 二期方向 |
| 产品 | 心灵补给站历史列表（MVP 只留最新一份） | research-v1 Q3 | 二期 |
| 智能 | BM25/重排增益实测（真语料上量后） | research-v1 Q6 | 二期 |
```

---

## 6. 文档写作规范（本次确立）与 B 任务

### 6.1 八条规范（新写/修订文档遵循）

1. 一份文档只回答一个问题（CLAUDE.md=开工指针+硬约束；spec=现在是什么；PROGRESS/本文=为什么；contract/plan=各自唯一事实）；
2. 单一权威，引用不复制（grep 检验：术语在 ≥2 处被"定义"即违规）；
3. 决策记录与现状分离（决议要么落为现行规则，要么标"已否决/二期"，不允许两选项并存）；
4. 规则可验证（学 CLAUDE.md §8"可 grep"写法）；
5. 正向表述（写做什么；硬红线例外且旁配正向做法）；
6. 删 no-op（不改变默认行为的句子整句删）;
7. 领头词（如"不变量"统一指代 V2.3 类铁律，定义一次各处引用）；
8. 环境即真源（已存在的目录树/脚本不复述）。

### 6.2 B 任务（文档规范化重构）——**待审查讨论后执行**

- spec §0 决策表（30 行）迁出：历史决议 → ARCHITECTURE_PROGRESS；正文只留现行规则；
- spec §12 答辩叙事点迁往 references.md（人类读者文件）；
- Agent 名单三处复述（spec/backend-plan/CLAUDE.md）收敛为 spec 单源，余处引用；
- 表格一表一义重排（容器规格表拆分）；
- 病灶清单：电报体歧义（"贯穿每轮""个位数 ms"）逐处量化。

### 6.3 已识别病灶存档（B 任务输入）

spec §0 历史与现状混住（V2.6 双选项并存的根因）；同一事实多处复述致漂移（A1 矛盾的根因）；读者混装（答辩点）；表格过载；CLAUDE.md §8 为正面样板。

---

## 7. 回主分支衔接（环境手册 option.md 同步项）

主分支已定案（另一会话）：Python 3.10 + 显式 `uv venv` / 人建骨架 Claude 写码 / DeepSeek+.env / 语音栈延后独立节（`model/voices/` 目录，QwenAudio/CosyVoice 新地址）/ 种子语料 Claude 起草人审。

本分支新增的环境/依赖同步项：
1. **Redis 容器**：§2.5 命令 + 启动顺序（Docker 先行）+ `.env` 加 `REDIS_URL`；
2. **ffmpeg**：已验证本机已装（`D:\Tools\ffmpeg-8.0-full_build`，v8.0 full，含 libopus，已在 PATH）——手册只需 `ffmpeg -version` 验证步骤，无需安装（ASR 转码依赖）；
3. **Python 依赖**：`langgraph`（**不含** supervisor）、`redis`、`rank-bm25`、`jieba`、`sentence-transformers`、`chromadb`、`funasr`；
4. **模型下载**：bge-small-zh-v1.5（~100MB）、bge-reranker-v2-m3（~2GB），HF 镜像备用 `HF_ENDPOINT=https://hf-mirror.com`；
5. 前端：`@proj-airi/unplugin-live2d-sdk` 包名有效性待验证（主分支遗留项）。
