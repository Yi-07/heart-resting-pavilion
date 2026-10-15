# 全库遗留盘点（一次性扫描）

> **职能**：2026-10-06 全库遗留待解决问题扫描的盘点清单，供维护者审视后分派各条目去向。
> 扫描范围：docs/ 全树、根五文档、backend/、frontend/、看板与交接、配置文件；标准 TODO/FIXME 注记前后端均零命中，遗留全部以中文注记、契约注记与文档落点形式存在。
> 条目只写路径与符号名，不写行号；行号随改动漂移，agent 处理时按符号 grep 自查实况。
> 既有落点（[backlog.md](backlog.md)、[ARCHITECTURE_PROGRESS.md](../architecture/ARCHITECTURE_PROGRESS.md)「二期范围总表」、看板）为那些条目的唯一记录处，本文件只列指针不复制。
> 各条目处置后在行尾补去向；全档处理完即归档或删除，结论归 git。

## 1. 代码预留接口未实现（已留位、待接线）

- `backend/app/router/classifier.py` `classify()`：LLM 分层判定全路径已实现并导出，网关 `ws_gateway/gateway.py` 只调 `classify_rules`，`classify()` 无任何调用方。接线时同步 spec「三路路由」节与 AGENTS.md「规则边界」职责隔离句。
- `backend/app/agents/state.py` `CollectState.suspended`：gateway 三处赋值、无读取点，恢复实际由路由分支驱动。删字段或补挂起恢复逻辑，二选一。
- `backend/app/memory/store.py` 热层 `mood_recent`：写入与恢复齐全，无消费方（注释称喂 snapshot/Live2D 语境，Live2D 侧未接）；`agents/state.py` docstring「memory 步骤 6 接入；MVP 恒空档」滞后于现状。
- `backend/app/schema/formulation.py` `emotion_wheel`：测试模板仅 schema 定义与契约对齐测试，无生产调用方（stage_map 有危机横幅在用，wheel 无）。
- `backend/app/voice/tts.py` 情感标签：spec 与 backend-plan 注明「接口预留，现行未接线」，`synthesize_stream` 无情感参数。
- `frontend/src/ws/messages.ts` `TextDelta.final`、`AudioChunk.final`：契约镜像字段前端未消费（ws-contract 已注明可不依赖），保留注记或删字段二选一。
- `frontend/src/board/types.ts` `FieldDecl.emptyIfNull`：渲染器从不读取，与 backlog「C1 审查留档项」已挂的 `TemplateDecl.title` 死字段同族。
- `frontend/src/admin/settings.ts` `TrendRow.intensity`：随 /admin/trends 拉回但不渲染。
- `frontend/src/l2d/live2d.ts` 口型：播放中以点头动作示意，真口型（音频幅值驱动）待步骤 8；`frontend/src/audio/queue.ts` 自述「真音频帧步骤 8 到，本步只立骨架」。

## 2. MVP 占位待补（运行时补内容、换真实现）

- 危机与路由词表四张 MVP 最小占位，均注「内容运行时补」：`router/gate.py`（纯子串匹配，无否定与语境消歧，「不是不想活」会误命中）、`router/classifier.py` 路由三级词表、`router/classifier.py` 纯概念问句词表、`collect/degrade.py` 三降级词表。
- 采集问句 LLM 润色跳过：`agents/graph.py` 与 `collect/questions.py` 注明 MVP 预置优先。backlog「原 kanban 待办池迁入」只挂了短答回接润色，问句侧此前无落点。
- 每日聚合按机器本地日、无时区处理，三处同型：`memory/store.py`、`station/reports.py`、`admin/config_store.py`。
- `rag/engine.py` `_LEGACY_COLLECTION`：旧单库迁移兜底，迁移彻底后移除。
- Live2D 简化四处：`live2d.ts` 表情序号按 haru 单模型硬编码（越界落 0）、包围盒缺失按经验值 600×700 缩放、主入口硬要求 Cubism2 只能走 /cubism4 子路径；`env.d.ts` pixi-live2d-display 与 pixi.js 6 泛型对不齐，手写最小面类型声明。
- `frontend/src/state/round.ts`：增量 draw 与精稿 draw 契约无专用信号，前端按纯推断映射状态机（契约缺口，处置时可提 ws-contract 议题）。
- `frontend/src/App.vue` 协议帧调试控制台常驻产品构建，未按 DEV 环境裁剪。

## 3. 设计已有、实现未做

- 等待体验补全（15s「还在处理」提示、等待卡死 15s 补播第二句）：backlog「原 kanban 待办池迁入」已挂；ws-contract「15s 无消息」条款与 backend-plan 补播注记同源，三处表述一致。
- answer 空窗桥接语「让我查一下资料——」：Inspiration.md 设计（RAG 检索约 1.7s 空白），前后端 grep 零命中，待实现。
- ASR/TTS 引擎配置化：spec「L7 · 数据与知识层」节「模型配置存储」段声称 LLM/ASR/TTS 统一可配，`/admin/config` 实际仅 LLM，`frontend/src/admin/SettingsPanel.vue` 中 ASR/TTS 只读展示。（2026-10-15 处置：旧 `/admin/config` 口已随 PR #3 融合 T4 清理退场，模型配置走 `/admin/llm/*` profiles 仍仅 LLM，spec「模型配置存储」段已同步为 LLM profiles；ASR/TTS 配置化仍留位未实现，本条对 ASR/TTS 部分继续有效）
- station/admin 鉴权：backlog「C1 审查留档项」已挂 WS session 信物项；backend-plan 注明局域网/公网暴露前必须加，现无任何鉴权。
- 非医疗声明补「AI 非专业咨询 / 对话会被记录」告知文案：Inspiration.md 挂 21号令语境告知义务，前后端文案均未写。

## 4. 扫描发现的问题

### 过时注记（清理，非补做）

- [x] [ARCHITECTURE_PROGRESS.md](../architecture/ARCHITECTURE_PROGRESS.md)「科普库 1022 条已交付未接线」：已修——地图行更新为「科普库已接线（1022 条，.rag_store 双集合）」。
- `frontend/src/App.vue` 与 `frontend/src/l2d/placeholder.ts` 头注「Live2D/语音留位（步骤 7/8）」：两者均已实现，注释滞后。
- [backend-plan.md](../architecture/backend-plan.md)「R3 配置 UI 后续接管」：LLM 配置 UI 已实现；ASR/TTS 未配部分归本档「设计已有、实现未做」。
- [x] `backend/scripts/freeze_sidecar_rollback.txt` 头注引 option.md「6.1」已废节号：已修——改「TTS · CosyVoice 2」节名。
- [d1a-survey.md](../tests/reviews/d1a-survey.md) 快照 P13/P14/P18 已随后续批次修复未标销；同档 P16（frontend/README 零定制）仍真欠，见下「文档欠账」。
- `workspace/README.md` 调研报告清单 3 份标「进行中」，与 workspace/HANDOFF「前置轮全部完结」矛盾，清单未刷。（workspace/ 将整目录删除，随删自消）
- `prototypes/README.md` 启动命令过时（旧 uvicorn 直启命令，现行 `uv run hrp`），且「后期统一清理」的临时区声明未兑现（.gitignore 同注）。

### 文档欠账（待补写）

- [ws-contract.md](../architecture/ws-contract.md) 事件清单自称「全量事件名清单，与代码同步维护」，代码另有 8 个事件未列：config_applied、config_saved、planner_llm_ok、risk_review_failed、station_report_accepted、station_report_ready、tts_sidecar_spawned、tts_sidecar_version_respawn。⚠ 与 commit da4c8bd 审计批「事件清单全量」的表述冲突，补前列需先对账归因（可能是 42eb184 一批新引入）。
- 「心理状态`→`模板」映射表：ARCHITECTURE_PROGRESS「核心决策摘要」挂「后期维护」未建。
- 黑板 canvas 规范（viewBox 640×440 与 safeArea）只在 `frontend/src/board/types.ts` 注释携带，未落 frontend-plan。
- `frontend/README.md` create-vue 脚手架原文零定制：VITE_WS_URL 语义、scripts/fetch-l2d.mjs 用法无文档。

### 裁定残项（新增，待人拍板）

- replay 幕布横幅「上次聊到 HH:MM」文案 vs 契约 replay 帧无时间字段，二选一（c1-review 挂出，backlog「裁定残项」未收）。裁定前不动行为。

### 测试缺口

- `backend/tests/test_voice.py` 两处条件 skip：CosyVoice 仓库 asset 不在场、SenseVoice 模型不可用。
- `backend/tests/e2e/e2e3_d_asr.py`：素材 wav gitignore 不入库，缺素材整用例判 FAIL。
- `backend/tests/e2e/e2e3_g_redis_down.py`：依赖 docker 容器 hrp-redis 在跑，否则整用例跳过。
- `backend/tests/e2e/e2e3_c_gate_variants.py`：C1 复杂概念变体为观察性软断言（记录实测不硬判）；`e2e3_b_complex.py`：acceptance 原判据（「想离开这个世界」）与现行纯子串词表存在已知预期差异。
- frontend 五个源文件无对应 spec：`voice/asr.ts`、`l2d/live2d.ts`、`l2d/placeholder.ts`、`logger.ts`、`board/templateRegistry.ts`。

### 演示

- 演示脚本用户消息不可见（评委看不到用户说了什么）：Inspiration.md 挂出，口头补讲与自动展开两案未选。

## 5. 二期散见注记（PROGRESS 总表之外，待收编）

「二期范围总表」（20 条，多模态协同至 SenseVoice 情感接入）唯一记录处在 ARCHITECTURE_PROGRESS，不在此复制。以下注记标了二期但未入总表，收编时逐条裁去向：

- 情绪强度环比上升检测：`backend/app/agents/graph.py` 头注、spec「三路路由」节（现行只走软预筛词典路径）。
- 充分度≥0.4 后台分析启动线：spec「L4 · 空窗期策略（横切编排）+ 多轮采集器」节分析就绪行，MVP 无操作语义，代码无启动线。
- 危机词典与 L6 规则引擎共享单一词典来源：`backend/app/router/gate.py` 头注，二期接线。
- 停采后分析后台并行：spec 与 ws-contract 注（与总表「真·边采边算」近缘，是否归并一条由人裁）。
- 日志聚合接 ELK / Datadog：ws-contract 观测节。
- ASR GPU 化、真·LLM 流式逐句合成（边生成边播）：ADR-002 遗留段；分句合成 per-call prompt 重编码约 0.5-1s 开销，与 TTS 延迟修复线（CUDA torch+分句合成）直接相关。
- formulation 与 round_index 持久、采集进度恢复：ADR-001、`ws_gateway/gateway.py`「黑板重画，采集从首轮计」局限注。

## 6. 既有落点指针（扫描确认仍开放，明细不复制）

- backlog「C1 审查留档项」：C1 审查留档 27 条全开放；抽查 5 条与代码实况一致（热层非原子、gate 0.4 权重、`refs: list = []`、AUDIO_INPUT_MAX_S、needs_rag）。
- backlog「裁定残项」：两条待拍板（「生不如死」分档、mood_select 回写）。
- backlog「原 kanban 待办池迁入」：9 条全开放；「等待体验补全」与本档「设计已有、实现未做」首条同源。
- backlog「D1-d 后置项」：推远程后两项（Redis compose 起草人审、临时目录 clone 全流程实测）；option.md Redis 节现仍为裸 docker run。
- workspace/HANDOFF：skill 执行轮八项中①②③④⑤⑥⑦已随 commit 合入，⑧workspace/ 清理进行中（HANDOFF 已写终态，整目录删除待执行）。
- 未 commit 差异：git status 实况已收口——e62d6ae（coding-standards 补全+backlog 挂账）、f31b7c4（CONTRIBUTING §6 重写）、后续 doc-style-human 删除与 W6 标点统一批次按 workspace/HANDOFF 终态安排。
- 推远程：origin 已配置，本地领先多笔，推不推由人定。
- 看板 blackboard-v1（gitignored 活看板）：P1 四子项（素材目录、ws 契约草案、渲染器 asset 层、静态原型）与 P2/P3 未完；「语料关系分析」脚本 `docs/task-kanbans/yxw/blackboard-v1/scripts/corpus_cluster.py` 已存在而报告 corpus-analysis.md 未落，状态待核。
- workspace2/3 残留：backend/.env 的 DEEPSEEK_MODEL 旧名与尾随空格处置待裁定；TTS RTF Round 2（provider 核验、实测、报告终稿）未做，且 workspace2 善后记录与 workspace3 前置「手动换 ort-gpu」存在跨线漂移，先核实现状。
- `.claude/skills/scene-walkthrough-TODO.md`：场景演绎 skill 未创建。
