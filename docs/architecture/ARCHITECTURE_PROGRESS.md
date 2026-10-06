# 心栖阁 · 架构进度记录

> **用途**：会话压缩/恢复时的上下文锚点。恢复时先读本文件 + `architecture-spec.md`。
> **不管面**：现行架构/参数/契约/技术栈以 spec 与 ws-contract 为准（单源），本文件只留进度与历史。

---

## 一、项目定位

定位唯一记录处见 [architecture-spec.md](architecture-spec.md)「项目概述」；目标与产品形态亦在彼处。**当前阶段：技术原型**（第一版软件链路全通，文档体系为根入口+docs/ 树）。

---

## 二、文档地图

> 触发器制（一行一型：何时才需要这份文档）；状态列为文件存在性核验。单份职能与链接索引见 `docs/README.md`（单源），本表管全量与状态。

| 文档型 | 触发器 | 状态 |
|---|---|---|
| CLAUDE.md（薄壳）+ AGENTS.md | 用 coding agent | ✓ |
| 文档总索引（docs/README.md） | 找文档 | ✓ |
| 入口四件（README/CONTRIBUTING/ARCHITECTURE/AGENTS.md） | 队友入口/协作/架构地图 | ✓ |
| spec（HLD，`architecture-spec`） | 架构想清楚 | ✓ |
| 实施方案（LLD，frontend/backend-plan） | 对应端开工 | ✓ |
| 接口契约（`ws-contract`） | 两端分离协作 | ✓ |
| 术语表（`CONTEXT.md`） | 命名分歧出现 | ✓ |
| 设计基准（docs/guides/deep-module.md） | 新模块开工 | ✓ |
| 环境/操作手册（`docs/guides/option.md`） | 有人要跑起来 | ✓ |
| 进度/恢复台账（PROGRESS） | agent 跨会话工作 | ✓ |
| 答辩溯源（`docs/references.md`） | 评审场景 | ✓ |
| 决策记录（`docs/adr/NNN-标题.md`） | 架构级决策发生 | ✓ 实有 5 篇（001-005） |
| 业务验收清单（`docs/tests/acceptance-v1.md`） | 第一版交付验收（B1 产出） | ✓ |
| 数据契约（`docs/architecture/data-contract.md`） | 数据生产者≠消费者 | ✓ 案例库已接入（14944 条）；科普库已接线（1022 条，.rag_store 双集合） |
| 执行状态（kanban+handoff / backlog） | agent 跨会话 | ✓ |
| 审查快照（docs/tests/reviews/） | 审查/摸查发生 | ✓ 3 份 |
| 研究记录（docs/research/ 下 *-research-*.md） | 专题调研发生 | 已清理（3465b01/995eeae），触发再建 |
| UI 参考（`docs/architecture/preview/l1-ui-mockup-v7.html`） | 前端 UI 实现 | ✓ |
| 备忘录（`docs/Inspiration.md`） | 随手记 | ✓ 人看 |
| 任务排期（`docs/todos/tasks-arrangement.md`） | 里程碑/阶段排期 | ✓ 人看 |
| PRD（docs/prds/） | 多干系人需求 | ✓ 已完结 1 篇 |

> 域外型，触发才建：LICENSE/SECURITY 俟开源或公开产品期 · CHANGELOG 俟对外发版（git tag 即内部替代）· runbook 俟多环境部署 · tutorial=产品有外部学习者 · 正式 RFC=团队扩大需评审流程。
> 旧版方案归档于维护者本机 `backup/Architecture-historys.zip`（gitignored，不入库；勿作实现依据）。

---

## 三、核心决策摘要

**架构**：三路路由（危机/直接答/多轮采集）· 危机闸门作用于每条 user_input · 多轮采集即共情式对话（L4 管状态、L5 管话术）· formulation schema 按 Beck 认知概念化 · DrawProtocol 模板级（draw 传全量）。

**模板模型**：一个会话一个模板，粗稿/精稿**同一张图逐步深化**（表层→深层），数据填充；测试模板 3 个；"心理状态→模板"映射表后期维护。

> 第一版交付期 ADR（编号即 docs/adr/ 文件，现行规则原文以此为准）：ADR-001 记忆分层（热层轮次原话）· ADR-002 TTS 分句流式+sidecar 进程统一 · ADR-003 采集态路由门控+RAG 预热 · ADR-004 语音输入两步式（输入单源文本）· ADR-005 对话回放与小结卡片（replay 帧+身份持久化）。

---

## 四、二期范围总表

> 改二期只改本表，防双维护；[architecture-spec.md](architecture-spec.md)「开发范围（MVP vs 二期）」引用本表。「research-v1 Qx/§4 C7」引用指历史研究档已清理（commit 3465b01/995eeae），依据沉淀在「历史决策台账」与 spec，条目原文不再可查。

| 分类 | 二期项 | 依据 | 状态 |
|---|---|---|---|
| 交互 | 多模态节奏协同（黑板/语音/Live2D 编排） | spec「开发范围（MVP vs 二期）」 | 已定 |
| 交互 | WebRTC 打断式语音 | spec「开发范围（MVP vs 二期）」 | 已定 |
| 交互 | ASR 强化 | spec「开发范围（MVP vs 二期）」 | 已定 |
| 智能 | 知识图谱（knowledge.query 接口缝） | spec「开发范围（MVP vs 二期）」/Q6 | 已定 |
| 智能 | 语义级记忆检索 | spec「开发范围（MVP vs 二期）」 | 已定 |
| 智能 | 温层结构化抽取（Mem0） | 讨论 | 方向 |
| 产品 | 心灵练习/留言墙 | frontend-plan 工具范围 | UI TODO |
| 产品 | 设置-偏好/通知 | frontend-plan 工具范围 | 二期 |
| 插件化 | 组件插件框架（Provider/BoardTheme/ToolPlugin/registry） | 讨论 | 方向 |
| 合规 | 21号令（单独同意/禁默认训练/极端情绪主动联络/未成年） | 讨论 | 真实产品前 |
| 工程 | 多人并发 | spec「开发范围（MVP vs 二期）」 | 已定 |
| 工程 | Tauri 打包 | spec「开发范围（MVP vs 二期）」 | 已定 |
| 产品 | 日历/量表工具（方案书执行层+度量层） | research-v1 Q7 | 二期 |
| 智能 | 真·边采边算（formulation 版本号+可取消任务） | research-v1 Q4 | 二期 |
| 智能 | supervisor 模式 revisit（手工工具式，不用库） | research-v1 Q2 | 二期方向 |
| 产品 | 心灵补给站历史列表（MVP 只留最新一份） | research-v1 Q3 | 二期 |
| 智能 | BM25/重排增益实测（真语料上量后） | research-v1 Q6 | 二期 |
| 交互 | 字级视听同步（词边界卡拉OK） | research-v1 §4 C7 | 二期 |
| 交互 | 后端流式无缝拼接（LiveKit 式） | research-v1 §4 C7 | 二期 |
| 智能 | SenseVoice 情感输出接入 | research-v1 §4 C7 | 二期 |

---

## 五、历史决策台账

> 只读快照——spec 变更不回写本表；现行规则以 spec 为准。编号（Q/R/V2.x）被引用时查本表。

| # | 决策 |
|---|---|
| Q1 | 流水线第一帧（300ms 安抚 + 流式增量）|
| Q2 | 路由三分支 + 危机闸门前置（危机走规则硬判安全通道，热线 12356）|
| Q3 | 多 Agent 按需门控激活（监督者=门控路由）。已修订（research-v1 Q2）：门控=确定性条件边，无 LLM supervisor |
| Q4 | 黑板 = 路线 B：模板库 + DrawProtocol，LLM 只填数据 |
| Q5 | MVP 直接上 Live2D（情绪一源三用）；语音双引擎可插拔 |
| Q6 | 砍掉症状关联推理，留 `knowledge.query` 接口缝 |
| Q7 | WebSocket 单连接多消息；实时感交应用层，WebRTC 二期 |
| Q8 | 记忆四级金字塔 + Key 隔离 + 版本号 + 治理层（用户可查可清）|
| Q9 | FastAPI + LangGraph（supervisor） + Chroma + SQLite + Redis + Vue3/Vite/TS。已修订（research-v1 Q2）：无 LLM supervisor，改为确定性条件边编排 |
| Q10 | MVP 切片 + 二期边界（见 §10）|
| R1 | L4 去重 →「空窗期策略」：第一帧缓冲 + 黑板渐进绘制 + 语音安抚协同 |
| R2 | 黑板情感标签驱动多模板：标签聚类→模板（非每标签一模板）|
| R3 | 模型配置 UI：LLM/ASR/TTS 统一可配置；敏感凭证 AES-GCM 入库 |
| R4 | L1 前端先出 UI 预览样稿 → 评审 → 服务对接 |
| **V2.1** | 三路命名：**answer（直接答）/ collect（多轮采集）/ crisis（危机）** |
| **V2.2** | **共情前置**：采集 = 共情式对话。分工：**采集器（状态机/充分度/轮控）在 L4，问话由 L5 共情 Agent 出**。每轮输出 = 确认情绪 + 下一问；预置库只供骨架。不合并成单一无边界组件（L4 管状态，L5 管话术）|
| **V2.3** | **隔离约束（写死）**：`crisis 与 route 走规则判定，确定性；emotion_label 只喂黑板/Live2D，绝不进路由` |
| **V2.4** | **采集降级三路径** + 触发检测：答案过短 / 话题漂移 / 负面词 → ①停止采集转共情陪聊 ②已采字段收尾 ③情绪变差再过闸门（危机转热线）|
| **V2.5** | **风险评估者：软信号预筛→LLM 复核**。每轮先跑规则硬判 + 软信号关键词预筛，仅预筛命中才跑 LLM 复核（不每轮跑，控成本）|
| **V2.6** | **边采边算保留**（**可降级为采集结束再分析，协议不变**）：充分度 ≥0.4 启动后台分析；最后一轮→精稿空窗由后台分析填充。**MVP 采用降级档（停采后同步分析，research-v1 Q4）** |
| **V2.7** | **L4 口径 = 横切编排策略**：横切是分布方式，编排是职责。答辩按此表述 |
| **V2.8** | **记忆治理层 + R3 模型配置 UI 保留**（继承 v1，不砍）|
| **V2.9** | **计划制定者 Agent 进 MVP**：分流"建议型"才激活；安全边界=非医疗声明 / 危机绕过 / 方案基于 RAG 知识不凭空编。**已修订（research-v1 Q3）：互斥分流废除，方案书=用户点击"心灵补给站"触发的懒生成** |
| **V2.10** | **危机闸门贯穿每一轮采集输入**，非仅入口 |

---

## 六、技术核查记录

> "为什么钉这个版本"类调研细节的存放处；编码文档只留结论，疑惑时查本表。

| 事项 | 结论 | 核查细节 |
|---|---|---|
| pixi-live2d-display 版本配套 | 钉 0.4.0 + pixi.js 6.5.10（frontend-plan §1） | stable 0.4.0 peer 仅 pixi ^6；0.5.0-beta 配 pixi 7；均不兼容 pixi 8.20.0（2026-08-22 过时技术事实排查） |
| Python 钉 3.10 | 3.10.11 | 全栈官方交汇：CosyVoice 要求 python=3.10；langgraph/fastapi ≥3.10；funasr 实测 3.8–3.10 |
| onnxruntime 钉 <1.24 | 1.23.2=cp310 末版 | 1.24+ 不再发 cp310 wheel 且 requires_python 未同步（解析过、安装炸）；chromadb 兼容；全树 cp310 干跑解析通过（chromadb 1.5.9/torch 2.13.0/funasr 1.4.3/langgraph 1.2.11） |
| DeepSeek 模型名 | deepseek-flash（现行唯一落配置的模型名） | 官方全域弃 deepseek-chat/reasoner（官方文档 grep 零出现）；调用锁 openai>=3.6.0（uv.lock 实况）；值落 backend/.env.example |
| Ollama 备选端点 | localhost：11434/v1（官方标 experimental） | api_key="ollama" 必填但被忽略；用前先 pull；支持流式/JSON mode/tools |
| Node 选 24 LTS | winget OpenJS.NodeJS.LTS | create-vue 引擎要求 ^22.18.0或≥24.12.0，本机 22.15 不满足；v24 Active LTS 维护至 2028-04；flag 拼法对 create-vue --help 逐条核实 |
| Live2D 采纳与弃用 | pixi-live2d-display 路线（frontend-plan §1 单源） | @proj-airi/unplugin-live2d-sdk 未采纳（npm 存在≠方案采纳）；CosyVoice 仓库 FunAudioLLM 已 301 迁至 QwenAudio，clone 用新地址 |
| gitignore 三层防线 | 根 .gitignore=唯一手工维护点 | frontend 产物由脚手架生成的 frontend/.gitignore 挡；backend/.venv 由 uv 自动挡；嵌套 ignore 不合并不删除；检查点 git status --porcelain 自查=总闸 |
