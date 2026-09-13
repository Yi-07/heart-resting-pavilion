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

## 2. 第一版交付待办

### A. 遗留问题完善

- [x] **A1 危机核心词表扩充**:现仅 9 核心词,补常见真实表述 ~20 条(跳楼/割腕/吃安眠药/一了百了/熬不下去/想离开这个世界/没有我会更好/我是累赘/人间不值得等)入 `gate.CORE_TERMS/SOFT_TERMS` + 钉测试。安全底线,内测前置。(落定:核心 9→23·软 5→10;"吃安眠药"有医疗正用归软档,吞药入核心;词表逐条钉死,三件套全绿)
- [x] **A2 prototypes/tts-latency 归档**:判定标准——`e2e_lib.py` + ADR-003 五用例脚本(e2e2_*)迁 `backend/tests/` 作业务回归素材;**freeze_gpu_blueprint.txt / freeze_sidecar_rollback.txt 必须保留**(D1 venv 重建锚,迁 backend/scripts/ 或随 D1 落位);bench_*/FINDINGS.md 删(结论已沉淀 ADR-002/003);其余按同原则处置。(落定:e2e_lib+两轮 E2E 共 10 脚本已迁 `backend/tests/e2e/`,ruff/mypy 清零+ping_interval=None 修正+日志路径改 backend 相对+e2e_b_asr 语音素材改命令行传入;bench/FINDINGS/运行日志/中间产物已删;freeze 两文件按人裁定留原地随 D1 处置;实况回归待 B2)
- 注:~~RAG 启动 warm-up 预热~~ ✅ 已随 ADR-003 落地(lifespan warm() + retrieve_async 降级 + E2E 验证,commit `5dfeea6`);~~模型下载脚本~~ → 并入 D1(部署配置归属)。
- [x] **A3 语音输入两步式(ADR-004)**:B1 盘点发现 ASR 音频直入对话流→转写偏差可致危机漏检,改两步式:录音 → `POST /asr/transcribe` 转写(200/413/422/503)→ 追加式回填文本框(末尾非标点补逗号)→ 用户确认按文本发送。输入单源文本:`user_input` 删 mode/audio 字段,网关删 audio 分支,e2e_b_asr 作废删除;语音故障与 WS 解耦。(契约/schema/前后端/测试同步,三件套+前端检查全绿;交互实况归 B2 手测)
- [x] **A4 对话回放与小结卡片(ADR-001 落地+ADR-005)**:UI 原型定稿(prototypes/replay-ui,30min 内=幕布折叠/隔天=自然混流+小结卡)。ADR-001 落地=热层存 recent_turns(≤20 轮,30min TTL)+重连重建 turns;ADR-005=assistant 回复入轮次(修 turns 只记单边)+契约新增 `replay` 帧(S→C 9 种消息,重连认领后先推)+前端 localStorage 身份持久化+幕布/小结卡组件+治理清 localStorage 联动+聊天窗开立绘让位(v7 同款,顺手修)。(后端钉测 6 个+前端全绿;交互实况归 B2)

### B. 业务测试(新窗口执行)

- [x] **B1 验收清单落地**:清单文档写 `docs/tests/acceptance-v1.md`(判据载体),看板只挂状态。指标口径=三链路流畅度(帧序完整/无冻结/首包时长,基线=ADR-002/003 E2E 实测)+ 危机词表抽测 20-30 条真实表达(样本从 `backend/logs/` 的 crisis_gate_hit 反推,**筛 `"hit": true` 且 matched 非空的行**)+ 环境前置节(内测访问形态/Redis/模型/l2d)。达成「应对 80%+ 应用场景」即可交付第一版。(落定:7 节——环境前置/三链路/语音/ADR-003 场景/词表抽测/记忆恢复/工具;抽测样本实测=日志 82 条 hit 中 80 条"不想活"+2 条"自杀"分布单一,改以 A1 词表 33 条构造变体句全覆盖+误伤负样本;**双用例原则**=三链路+门控场景各配简单+复杂两条话术防偶然,复杂变体含裁量规则——概念问句变体判内容轮不硬判挂、求助句被抢占=硬挂)
- [x] **B2 完整三链路业务测试**:answer/collect/crisis 全链实况(吸收原 B-6)。执行素材:`backend/tests/e2e/`(e2e_lib + 两轮 E2E 脚本,跑法见 e2e_lib 头注;`uv run python tests/e2e/e2e2_a_gate_concept.py`,Windows 直接 python 不经 pytest);本机需在跑 `uv run hrp`(lifespan 自动拉 sidecar+RAG 预热)。并纳入:station 方案书 REST 实测、Redis 宕机降级实测、跨会话 memory_restored、概念问句门控/求助句留场(ADR-003 场景)、词表抽测(依赖 A1)。判据挂 B1 的 acceptance-v1.md。(落定:acceptance 全节实况过——既有 8 脚本回归 + 新写 7 个 e2e3 脚本[词表抽测 126/126·复杂双用例·门控变体·ASR 两步式·station/admin·记忆回放 bubbles/digest·clear_memory 治理·Redis 宕机降级]+ 浏览器交互两段[心情点选/黑板视觉/回放幕布/Live2D/console 零 error];**顺手修 7 项真发现**:危机词表补消失族 3 词·跨字段提取[单字段瓶颈根治,一条回答可填多字段]·挂起问题填到才清·AskNext/EmpathChat 补 final 收尾·Finish 归档 asyncio.shield·ASR 近静音判空·启动提示标志文字;acceptance §1.3/§5 判据措辞随实测同步;遗留待办见 §3[概念句"一直"误捕获·off_topic 观测日志·心情选择器 10s×LLM 慢 UX];交互盲区留手测:真麦克风口播/digest 小结卡前端呈现)

### C. code review

- [x] **C1 全库代码审查**(落定:两轴+独立安全轴 5 片子 agent 并行;64 发现=硬违例 8+裁量 43+待核 13;**修复=硬违例 8[H1-H8]+裁量 11[D1-D11]+验证期顺手修 3[F3 digest 断链/planner as exc/engine TYPE_CHECKING]**+测试脚本 2[e2e_a_collect 自适应编排/e2e3_f F3 新语义]+backend-plan 鉴权决策等文档涟漪;审查快照与逐条销账=`docs/reviews/c1-review.md`;留档/待裁项=`docs/todos/backlog.md`;验证=三件套+前端+e2e 实况全绿,详见 git show)

### D. 交付文档(部署配置并入此处)

- [ ] **D1 交付前文档体系 + 新克隆一键就绪**(人裁定:开新窗口执行;分四相位,摸查结论/每份文档大纲与正文均停下待人审查):
  - **D1-a 全库文档摸查(子 agent 黑盒,只读)**:全库 .md 盘三面——时效性(陈述 vs 代码/git 实况:路径/命令/数值/ADR 数/近期大改是否反映)、互联性(交叉引用断链/节号漂移/单源指针断裂成环)、遗漏;**含 `backend/.env.example`:逐项对 config.py 实际读取的环境变量核时效性(失效键/改名键)与缺失性(代码读了但 example 没写的键,含注释说明是否跟齐)**;产出=现况文档树+问题清单(硬伤排序,逐条附证据)。**排查结束停下待人审查,不直接改。**(摸查范围/时机由新窗口与人裁量)(落定:18 项=硬伤 5+断链 3+时效 5+遗漏 4+待裁 1;.env.example 失效 0/缺 2[OLLAMA_MODEL/HRP_VERBOSE];散篇仅 prds/rag-full-corpus-bge-m3 判疑死;报告+逐条证据=`docs/reviews/d1a-survey.md`;范围含 .claude/rules、排除 prototypes[人裁定];待裁 P07/P11/P12/P14/P17 与 P15 判据口径成环,随 D1-b~d/D2 销账)
  - **D1-b 文档体系定稿(人主导)**:单根 `docs/` 树状递归分类;渐进式披露链=**README.md**(队友入口·文档指南·各文档跳转指针,简单)→ **CONTRIBUTING.md**(团队开发约束·①②③跳转指针,简单)→ **①AGENTS.md**(编码 agent 共享·开发指南·开发文档跳转指针,简单;与 CLAUDE.md 关系待裁)→ **②ARCHITECTURE.md**(项目架构图[信息]·功能模块职责,详细)→ **③其他开发文档**(详细)。文档编写需要的模块待裁确认（上面文档后面的括号中只给出部分期望）。**逐份流程:大纲→人审砍多余→正文→人审精修→交付。**
  - **未决问题(开工先裁,可请人手动调用 `/grill-with-docs` 盘问)**:① AGENTS.md 与 CLAUDE.md 单源分工;② architecture/ 五件套(spec/ws-contract/双 plan/CONTEXT/PROGRESS)迁 docs/ 新树还是原地+指针(引用面=CLAUDE.md 边界表+代码注释);③ 新 ARCHITECTURE.md 与 architecture-spec.md 分工(防双单源:地图+指针 or 自含);④ 文档语言;⑤ prototypes/ 制品是否入摸查与处置标准(含 freeze 两文件迁 backend/scripts/);⑥ D2 与摸查输出的分工线。目标:D1-D2 完成后队友+其 coding agent 可直接协作开发。(已裁 2026-09-13 grill-with-docs 盘问:①AGENTS.md 单源+CLAUDE.md 薄壳[@AGENTS.md+Claude 专属节];②六件套 git mv docs/architecture/ 原名+preview/;③ARCHITECTURE.md=地图+指针,spec 仍权威;④中文;⑤prototypes 不入摸查,freeze 蓝本随 D1-d 入库;⑥摸查只出清单/结构类 D1-b~d 修/台账类归 D2。追加裁定:README 承项目说明;根 4 入口+docs/README.md 总索引二次跳转;工具落库=.claude/rules+skills 入库[mattpocock 全套+emilkowalski;scene-walkthrough-TODO 留盘单独 ignore;MCP 三件走 CONTRIBUTING 部署指令不建 .mcp.json;design-taste-frontend/i-have-adhd 标用户级自备不拷];P01 重复段按「两 preview 互为参考互补/同组件两套并存/拿不准停下问人」合并一段;AGENTS.md 简洁原则=开发规范必落实[docs 存放规则/核心代码风格/日志审计边界等],细节指针内化按需加载,拿不准问人)
  - **D1-c 写作规范(两套)**:人看文档=`.claude/rules/doc-style-human.md`(技术文档工程师铁律:30 字红线/禁词表/主动语态/自检;大纲先行流程内嵌「输出格式」节),与 doc-standards 十判据叠加(十判据管删留/单源,新规范管句法文风);agent 看文档=mattpocock writing-for-agents skill 方法学。
  - **D1-d 一键就绪(原内容)**:全部模型/素材配置脚本化并实测一次(临时目录 clone 验证)——RAG 两模型 `uv run hf download BAAI/bge-m3 BAAI/bge-reranker-v2-m3`(失败/超时切镜像 `HF_ENDPOINT=https://hf-mirror.com`;**`HF_HOME=D:\hf_cache` 显式设**,hf 默认进 C 盘且中文用户名有 sentencepiece 历史坑,或 `--local-dir` 直落 `backend/models/`)· CosyVoice venv 重建脚本(GPU torch 蓝本 `prototypes/tts-latency/freeze_gpu_blueprint.txt`+setuptools<81 坑+权重 5.3GB `models/voices/` gitignored)· SenseVoice 首用 ModelScope 拉 ~900MB(文档写清 `MODELSCOPE_CACHE` 落盘位)· Live2D `npm run l2d:fetch`(README 补可见性;CLAUDE.md §4 命令块同步)· 环境前提(Redis 6379/`HF_HOME`/`MODELSCOPE_CACHE` 系统变量/`.env` 从 example 复制)。
  - **验收标准**:文档分类规整(单根树+渐进式披露链成立);内容符合人的设计品味(逐份过人审精修);各配置安装脚本与散落环境配置(`.env.example` 等)收集完善;**按文档从零操作能正常部署并使用本项目**(临时目录 clone 实测全流程通过)。
- [ ] **D2 交付批核对**(输入=D1-a 摸查问题清单):ADR 状态、PROGRESS 归档与文档地图刷新(现文档地图已过时:ADR 实有 5 篇仍写"首篇待首个编码期决策",头注日期停在旧值)。

## 3. 待办池(已迁出,防双单源)

待办内容单源已迁 **`docs/todos/backlog.md`**(C1 审查留档项 + 本节原条目 + 裁定残项统一管理;二期范围单源仍=ARCHITECTURE_PROGRESS §四「二期范围总表」)。本节不再维护条目。原条目核销记录:记忆分层已随 A4 完成;off_topic 观测日志已核销(B2 落 extract_empty 带 off_topic 位)。

## 4. 接力规程

1. 收尾窗口(达成交接点):更新本文勾选与 §2 → 重写 `handoff.md` 为最新现状 → 一并 commit → 告知人可开新窗。
2. 新窗口开工:读 CLAUDE.md → 本文 → handoff.md → 按本文 §0 工作方式继续当前步骤。
3. 任何窗口发现本文与代码实况不符:以代码+git 为准,当场修正本文(文档 bug 处理同 CLAUDE.md 冲突解决)。
