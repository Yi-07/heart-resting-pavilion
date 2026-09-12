# 心栖阁 · 跨会话执行看板 kanban-v1

> **职能**:多对话窗口接力的共享执行清单——步骤执行状态单源;勾选=已完成并 commit。
> **优先级**:新会话开工必读顺序 = CLAUDE.md → 本文 → 同目录 `handoff.md`;步骤状态与本文冲突时以本文为准(优于任何会话记忆)。
> **单源边界**:构建顺序/命令/构建验收判据单源 = CLAUDE.md §4/§8,业务测试判据单源 = `docs/tests/acceptance-v1.md`(B1 产出),本文只记执行状态与分派,不复制判据;完成一步的前提=跑过对应用例并停下汇报获人确认。

## 0. 工作方式(本看板的执行模式)

- 主会话只做:决策、编码(Edit/Write)、commit、看板与交接快照更新、向人汇报。
- 高噪音步骤派子 agent(Agent 工具)黑盒执行,主会话只回收结论,不进中间输出:
  - 跑后端三件套/前端检查 → 回收「过/挂 + 失败摘要(文件:行)」
  - 浏览器 E2E 验证(playwright 对真实前后端) → 回收「验收判据逐条命中/未中」
  - 大文件蒸馏(如 preview mockup 结构) → 回收结构化要点
  - 全库检索/多文件摸底 → 回收结论 + 文件:行号
- 依据:单窗口实测,工具中间输出(测试日志/浏览器快照/检索面)会快速吃掉主上下文并污染推理现场。
- 汇报纪律不变:每步完成停下汇报 → 人确认 → commit(勾选+handoff 同步)→ 继续。

## 1. 主线构建(全部完成)

步骤1-9(契约类型→WS 网关→answer→collect→黑板→记忆→Live2D→语音→工具)+ 排后·全量语料接入(bge-m3,14944 条)全部完成。逐项实现/验证口径单源=**git log 的详细 commit message**(git show <hash>);决策背景查 `ARCHITECTURE_PROGRESS.md`(注意:它是决策台账,无逐项 commit 指针,且文档地图待 D2 刷新)。构建顺序单源仍为 CLAUDE.md §8。

## 2. 第一版交付冲刺

### A. 遗留问题完善

- [x] **A1 危机核心词表扩充**:现仅 9 核心词,补常见真实表述 ~20 条(跳楼/割腕/吃安眠药/一了百了/熬不下去/想离开这个世界/没有我会更好/我是累赘/人间不值得等)入 `gate.CORE_TERMS/SOFT_TERMS` + 钉测试。安全底线,内测前置。(落定:核心 9→23·软 5→10;"吃安眠药"有医疗正用归软档,吞药入核心;词表逐条钉死,三件套全绿)
- [x] **A2 prototypes/tts-latency 归档**:判定标准——`e2e_lib.py` + ADR-003 五用例脚本(e2e2_*)迁 `backend/tests/` 作业务回归素材;**freeze_gpu_blueprint.txt / freeze_sidecar_rollback.txt 必须保留**(D1 venv 重建锚,迁 backend/scripts/ 或随 D1 落位);bench_*/FINDINGS.md 删(结论已沉淀 ADR-002/003);其余按同原则处置。(落定:e2e_lib+两轮 E2E 共 10 脚本已迁 `backend/tests/e2e/`,ruff/mypy 清零+ping_interval=None 修正+日志路径改 backend 相对+e2e_b_asr 语音素材改命令行传入;bench/FINDINGS/运行日志/中间产物已删;freeze 两文件按人裁定留原地随 D1 处置;实况回归待 B2)
- 注:~~RAG 启动 warm-up 预热~~ ✅ 已随 ADR-003 落地(lifespan warm() + retrieve_async 降级 + E2E 验证,commit `5dfeea6`);~~模型下载脚本~~ → 并入 D1(部署配置归属)。
- [x] **A3 语音输入两步式(ADR-004)**:B1 盘点发现 ASR 音频直入对话流→转写偏差可致危机漏检,改两步式:录音 → `POST /asr/transcribe` 转写(200/413/422/503)→ 追加式回填文本框(末尾非标点补逗号)→ 用户确认按文本发送。输入单源文本:`user_input` 删 mode/audio 字段,网关删 audio 分支,e2e_b_asr 作废删除;语音故障与 WS 解耦。(契约/schema/前后端/测试同步,三件套+前端检查全绿;交互实况归 B2 手测)
- [x] **A4 对话回放与小结卡片(ADR-001 落地+ADR-005)**:UI 原型定稿(prototypes/replay-ui,30min 内=幕布折叠/隔天=自然混流+小结卡)。ADR-001 落地=热层存 recent_turns(≤20 轮,30min TTL)+重连重建 turns;ADR-005=assistant 回复入轮次(修 turns 只记单边)+契约新增 `replay` 帧(S→C 9 种消息,重连认领后先推)+前端 localStorage 身份持久化+幕布/小结卡组件+治理清 localStorage 联动+聊天窗开立绘让位(v7 同款,顺手修)。(后端钉测 6 个+前端全绿;交互实况归 B2)

### B. 业务测试(新窗口执行)

- [x] **B1 验收清单落地**:清单文档写 `docs/tests/acceptance-v1.md`(判据载体),看板只挂状态。指标口径=三链路流畅度(帧序完整/无冻结/首包时长,基线=ADR-002/003 E2E 实测)+ 危机词表抽测 20-30 条真实表达(样本从 `backend/logs/` 的 crisis_gate_hit 反推,**筛 `"hit": true` 且 matched 非空的行**)+ 环境前置节(内测访问形态/Redis/模型/l2d)。达成「应对 80%+ 应用场景」即可交付第一版。(落定:7 节——环境前置/三链路/语音/ADR-003 场景/词表抽测/记忆恢复/工具;抽测样本实测=日志 82 条 hit 中 80 条"不想活"+2 条"自杀"分布单一,改以 A1 词表 33 条构造变体句全覆盖+误伤负样本;**双用例原则**=三链路+门控场景各配简单+复杂两条话术防偶然,复杂变体含裁量规则——概念问句变体判内容轮不硬判挂、求助句被抢占=硬挂)
- [ ] **B2 完整三链路业务测试**:answer/collect/crisis 全链实况(吸收原 B-6)。执行素材:`backend/tests/e2e/`(e2e_lib + 两轮 E2E 脚本,跑法见 e2e_lib 头注;`uv run python tests/e2e/e2e2_a_gate_concept.py`,Windows 直接 python 不经 pytest);本机需在跑 `uv run hrp`(lifespan 自动拉 sidecar+RAG 预热)。并纳入:station 方案书 REST 实测、Redis 宕机降级实测、跨会话 memory_restored、概念问句门控/求助句留场(ADR-003 场景)、词表抽测(依赖 A1)。判据挂 B1 的 acceptance-v1.md。

### C. code review

- [ ] **C1 全库代码审查**(子 agent 分片并行,kanban §0):三个现成 skill(/simplify·/security-review·mattpocock code-review)均为 diff 型不适配全库——**借 mattpocock 两轴方法学自定义**:
  - Standards 轴=CLAUDE.md §5 代码风格/§7 日志安全红线 + backend-plan §2 深模块原则 + Fowler smell 基线(该 skill SKILL.md 内置 12 项);
  - Spec 轴=实现是否符合 ADR-002/003 与架构文档原意(缺失/偏差/scope creep);
  - 独立安全轴=危机判定/脱敏/密钥/注入面(危机与脱敏相关改动逐条过);
  - 切片建议:voice+gateway / agents+collect / rag+memory / station+admin / frontend,各片一个子 agent 回收结论,主会话汇总分轴呈现。

### D. 交付文档(部署配置并入此处)

- [ ] **D1 新克隆环境一键就绪 + README/CONTRIBUTING**:全部模型/素材配置脚本化并实测一次(临时目录 clone 验证),再落 README:
  - **仓库文档大规模分类整理**(人裁定并入:防推远程时文档污染)——全库文档盘点去留/归位;`prototypes/` 区制品处置,含 freeze 两文件 venv 重建锚迁 `backend/scripts/`(或等价落位)并入库
  - RAG 两模型:`uv run hf download BAAI/bge-m3 BAAI/bge-reranker-v2-m3`(失败/超时切镜像 `HF_ENDPOINT=https://hf-mirror.com`);**缓存落点显式设 `HF_HOME=D:\hf_cache`**(hf 默认进 C 盘 `.cache\huggingface\hub`,GB 级且中文用户名有 sentencepiece 历史坑)或 `--local-dir` 直落 `backend/models/`
  - CosyVoice venv 重建脚本(重):GPU torch 蓝本安装(`prototypes/tts-latency/freeze_gpu_blueprint.txt`,setuptools<81 坑)+ CosyVoice2 权重(5.3GB,`models/voices/` gitignored)
  - SenseVoice:首用自动从 ModelScope 拉(~900MB),文档写清 `MODELSCOPE_CACHE` 落盘位
  - Live2D 素材:`npm run l2d:fetch`(已收录 package.json,README 补可见性);CLAUDE.md §4 命令块同步
  - 环境前提:Redis 6379、`HF_HOME`/`MODELSCOPE_CACHE` 系统变量、`.env` 从 example 复制
- [ ] **D2 交付批核对**:ADR 状态、PROGRESS 归档与文档地图刷新(现文档地图已过时:ADR 实有 3 篇仍写"首篇待首个编码期决策",头注日期停在旧值)。

## 3. 待办池(不排程;内测反馈后再定优先级)

- 记忆分层落地(ADR-001 `MemoryTiering` 已审定):热层改存 recent_turns 原始轮次+重连重建;涟漪=spec §4 L7(ADR 原文另引的 spec §9.4 编号在现行 spec 不存在,落地时按现行 spec 重新定位审计节)· state.py · memory/store.py · gateway.py · 测试。
- 陪聊轮保留 pending_question:E2E 观察的 UX 缺口(求助句走陪聊后,下一条内容只进转录不做字段提取);高频出现再修。
- 阶段 2 四问 LLM 结构化分类器(用户 discourse-stack 方案):仅门控命中时调用,等 route_decided 日志积累偏差数据。
- 路由准确率/回接率评估(需标注集;route_decided 日志已在积累)。
- 「不想聊了」显式退出采集(需词表设计)。
- 短答回接话术 LLM 润色(等恢复体验实况)。
- LLM_TIMEOUT_S 单值预算拆分(慢流式下总结被兜底截断的偶发风险)。

## 4. 接力规程

1. 收尾窗口(达成交接点):更新本文勾选与 §2 → 重写 `handoff.md` 为最新现状 → 一并 commit → 告知人可开新窗。
2. 新窗口开工:读 CLAUDE.md → 本文 → handoff.md → 按本文 §0 工作方式继续当前步骤。
3. 任何窗口发现本文与代码实况不符:以代码+git 为准,当场修正本文(文档 bug 处理同 CLAUDE.md 冲突解决)。
