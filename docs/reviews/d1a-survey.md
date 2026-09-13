# D1-a 文档摸查(问题清单)

> 摸查日 2026-09-13,基线 commit `698b394`(工作区 clean)。三面判据:时效性/互联性/遗漏。每条结论附文件:行+引文,无推测项。另:c1-review §3 文档冲突批 7 项已挂账未执行,本文不重复立项,见 §2 末尾对照行。

## 1 现况文档树

判定口径:**活**=内容与代码/git 实况一致;**疑死**=内容被后续 ADR/commit 取代或与代码矛盾;**缓存**=工具产物非交付文档。

| 文件 | 职能一句话 | 判定 | 证据 |
|---|---|---|---|
| `CLAUDE.md` | coding agent 开工必读:指针表/边界/命令/红线 | 活 | §1 指针 10 路径逐一实存;§4 命令全真(hrp=pyproject:23,--reload=cli.py:15,ingest --reset=ingest.py:42);§8 冒烟 3 条与 acceptance §1 话术一致 |
| `architecture/architecture-spec.md` | 架构权威源(三路路由/容器/DrawProtocol) | 活 | §0/§10 引 PROGRESS §五/§四均实存;§4 L7 记忆参数与 config.py TTL 一致 |
| `architecture/ws-contract.md` | WS 消息契约权威源 | 活 | 9 消息与 schema/messages.ts 钉测过(c1-review §6);3 处已知冲突挂 c1 §3(§3.4 mp3/§9.1 --verbose/§9.3 事件名) |
| `architecture/frontend-plan.md` | 前端实施方案(模块/状态机/接口) | 活(带伤) | §2 UI 范式段重复两遍且裁定矛盾,见 P01 |
| `architecture/backend-plan.md` | 后端实施方案(模块/图/网关) | 活(带伤) | §3.2 max_rounds 已按 C1-D11 改「上限 3」;§8 error 行节号漂移,见 P04 |
| `architecture/CONTEXT.md` | 术语表(正词/避用) | 活 | 与 spec/契约用词抽查一致 |
| `architecture/ARCHITECTURE_PROGRESS.md` | 决策台账+二期总表+恢复锚点 | 活(带伤) | 地图研究记录行失实(P02)、§四断链(P03)、头注日期漂移(P09) |
| `architecture/preview/l1-ui-mockup-v7.html` | UI 布局参考 | 活 | 文件实存;被 CLAUDE.md:18 与 frontend-plan §2 引用 |
| `architecture/preview/l1-ui-taste.html` | 组件范式参考 | 活 | 文件实存;被 CLAUDE.md:18 与 frontend-plan:41 引用 |
| `docs/adr/001-memory-tiering.md` | 记忆分层(热层轮次原话) | 活 | 状态「已接受」;随 6cf2c41 落地,spec §4 L7 已回写 |
| `docs/adr/002-tts-streaming-and-sidecar-management.md` | TTS 分句流式+sidecar 统一管理 | 活 | 状态「已定案」;4bbf144 定案,ws-contract §3.4/§6.2 已同步 |
| `docs/adr/003-in-round-gating-and-loop-hygiene.md` | 采集态门控+防阻塞 | 活 | 状态「已定案」;5dfeea6 落地;softscan 行已回写 backend-plan §3.3 |
| `docs/adr/004-asr-transcribe-preview.md` | 语音两步式(输入单源文本) | 活 | 状态「已定案」;0fe967e 落地;voice/routes.py 实存 |
| `docs/adr/005-replay-and-digest.md` | replay 帧+小结卡+身份持久化 | 活 | 状态「已定案」;6cf2c41 落地;契约 §3.6 replay 实存 |
| `docs/tests/acceptance-v1.md` | 第一版交付验收判据单源 | 活 | B2 全节实况过(kanban §2 B2 落定);素材 backend/tests/e2e/ 16 脚本实存 |
| `docs/task-kanbans/kanban-v1.md` | 跨会话执行看板(状态单源) | 活(带伤) | 勾选状态与 git log 一致(A1-C1 全 [x]);D2 括注半过时,见 P10 |
| `docs/task-kanbans/handoff.md` | 交接现场快照 | 活(带伤) | 描述至 C1 完成,与 698b394 一致;行 30 字节损坏,见 P08 |
| `docs/todos/backlog.md` | 遗留待办池单源 | 活 | C1 留档+看板迁入项在册;指向的文件:行抽查实存 |
| `docs/reviews/c1-review.md` | C1 审查快照与销账 | 活 | §3 文档冲突批 7 项待执行(本文 §2 末对照) |
| `docs/option.md` | 环境搭建操作手册(人做 0-5) | 活(带伤) | 进度勾选 0-4;步骤 4 模型陈述过时(P05)、路径失实(P06)、会话一断链(P07)、步骤 5 语音栈未勾而语音已落地 |
| `docs/data-contract.md` | 队友数据集对接契约 | 活 | §2「[待回填] 队友实际格式」占位仍在=未回填,待队友 50 条样本;PROGRESS:33 状态一致 |
| `docs/tasks-arrangement.md` | 里程碑/阶段排期(人看) | 活(带伤) | 第一阶段 08-23 已过无状态标注,见 P11 |
| `docs/references.md` | 开源参考溯源(人看) | 活 | 静态内容,无实况依赖 |
| `docs/prds/rag-full-corpus-bge-m3.md` | RAG 全量语料+bge-m3 换模型的 PRD | **疑死** | 任务已完结且 3 处现状陈述被后续 commit 取代,见 P12 |
| `frontend/README.md` | create-vue 脚手架默认 README | 疑活(零定制) | 全文脚手架原文,无项目信息;`VITE_WS_URL` 等项目事实零覆盖,见 P16 |
| `.claude/rules/doc-style-human.md` | 人看文档写作规范 | 活 | 被 kanban D1-c/handoff §1 引用为 D1 依据 |
| `.claude/rules/tools.md` | 工具/Skill 扩展清单 | 活(轻出入) | CLAUDE.md §9 @引用实存;i-have-adhd 未装载,见 P17 |
| `.firecrawl/*.md`(8 份) | firecrawl 抓取缓存 | 缓存 | 工具产物,非交付文档,不入 D1 树 |
| `.pytest_cache/README.md`、`backend/.pytest_cache/README.md` | pytest 自生成说明 | 缓存 | 同上 |

备注:`docs/Inspiration.txt`(备忘录)、`docs/research/preview/*.html`(6 份研究期 preview)实存;`backup/Architecture-historys.zip` 实存,与 PROGRESS:44 归档脚注一致。`backend/` 无 README(基线事实)。

## 2 问题清单

硬伤(错误事实/断链)在前;每条含位置/问题/证据/处置(结构类|台账类|D1-d类|待裁)。

**硬伤·错误事实**

- **P01** `architecture/frontend-plan.md:41-49 vs 51-56` — §2「UI 范式」段整段重复两遍,且两份冲突裁定互相矛盾:41-49 引 `preview/l1-ui-taste.html`、裁定「停下问人,不自动择一」;51-56 引 `prototypes/ui-taste/index.html`、裁定「冲突处以 ui-taste 为准」。同文自相矛盾(按 CLAUDE.md 冲突规则属「同文自相矛盾→停下问人」级)。证据:两段除路径与裁定句外逐字相同,如「材质分层:面板=重玻璃,按钮/输入条=tinted 轻玻璃」出现两次。处置:**结构类**(删一份;现行正源=preview/l1-ui-taste.html,prototypes 副本已排除出摸查范围,建议保 41-49 删 51-56,留人核)。
- **P02** `architecture/ARCHITECTURE_PROGRESS.md:38` — 文档地图「研究记录(docs/research/ 下 *-research-*.md)|✓」,实际 `docs/research/` 仅剩 `preview/*.html`,五份 *-research-*.md 已于 3465b01/995eeae 按「验证过即清理」删除。状态列定义=「文件存在性核验」(PROGRESS:19),✓ 为失实。处置:**台账类**(D2 刷新地图:行改「已清理,产出归位见 commit 3465b01」或删行)。
- **P05** `docs/option.md:139,142` — 步骤 4 陈述「其中 bge-small-zh-v1.5 已在本机缓存,只缺重排模型」且下载命令仅 `hf download BAAI/bge-reranker-v2-m3`;现行配置=`backend/app/config.py:57,61` `RAG_EMBED_MODEL=backend/models/bge-m3`+reranker 本地路径,embedding 早已换 bge-m3(PRD/ingest.py:9「换模型(bge-small→bge-m3)后维度 512→1024」)。照手册操作装不齐 RAG 模型。处置:**D1-d类**(kanban 已把模型下载并入 D1;步骤 4 全段按 bge-m3+bge-reranker 重写)。
- **P06** `docs/option.md:245` — 「存 `backend/data/rag_seeds.jsonl`(进 git)」;该文件不存在。实况:科普种子=`rag_knowledge_corpus.jsonl`、案例全量=`rag_corpus.jsonl`、测试夹具=`rag_retrieve_test_seeds.jsonl`(backend/data/ 实测清单;PRD §语料与命名记录了 git mv)。处置:**D1-d类**(路径改 `rag_knowledge_corpus.jsonl` 或改指 data-contract)。
- **P08** `docs/task-kanbans/handoff.md:30` — 字节损坏:「冻结蓝本两文件仍<u+FFFD><u+FFFD> prototypes/…」。「在」字为两个 U+FFFD 替换符(od 实测:`e4 bb 8d ef bf bd ef bf bd`)。处置:**结构类**(改回「仍在」,随手修)。

**硬伤·断链/节号漂移**

- **P03** `architecture/ARCHITECTURE_PROGRESS.md:64-84`(§四二期总表) — 8 行引用「research-v1 Q2/Q3/Q4/Q6/Q7/§4 C7」,目标研究 md 已删(同 P02)。§五为只读快照豁免(3465b01 commit message:「历史台账 research-v1 来源标注保留=只读快照性质」);§四头注「改二期只改本表」=活表,引用应自解。处置:**台账类**(D2:§四 research-v1 引用改落点文档或加「研究档已清理」脚注)。
- **P04** `architecture/backend-plan.md:200` — 帧映射表 error 行「code + message(契约 §3.6)」;ws-contract §3.6=replay,error 实为 §3.7(ws-contract.md:139,152)。同族问题 messages.ts:13 已随 C1-D11 修,此处漏网。处置:**结构类**(§3.6→§3.7,一字修)。
- **P07** `docs/option.md:218` — 会话一提示词引 `docs/research/seam-research-v1.md`,该文件已删(995eeae「seam-research-v1 定案落实即删」)。块头标「已完结;留档勿再开」,但新会话误粘贴即踩空。处置:**待裁**(留档块加「文件已删,定案在两 plan」注,或整块收进 backup)。

**时效漂移**

- **P09** `architecture/ARCHITECTURE_PROGRESS.md:4` — 头注「最新更新:2026-08-27」;本文件末次实改=2026-09-12(commit ae255d2,§三 ADR 行等已更新)。日期未随内容刷新。处置:**台账类**(D2 连同地图一起刷;或按 doc-meta-hygiene 直接删日期行)。
- **P10** `docs/task-kanbans/kanban-v1.md:50` — D2 条括注「现文档地图已过时:ADR 实有 5 篇仍写『首篇待首个编码期决策』」;PROGRESS:31 现状已是「✓ 实有 5 篇(001-005)」,前半句失实(后半句「头注日期停在旧值」仍真,见 P09)。处置:**台账类**(D2 开工时按摸查实况重写该括注)。
- **P11** `docs/tasks-arrangement.md:11-12` — 第一阶段交付日期「08-23」已过 3 周,无完成/延期标注;第二阶段「09-20左右」临近。文档无勾选机制,阶段实况只能从 kanban 推。处置:**待裁**(人看文档:补一行阶段状态,或声明以 kanban 为准)。
- **P12** `docs/prds/rag-full-corpus-bge-m3.md:37,64,75-76` — 三处现状陈述被后续 commit 取代:①「已 mock 掉 answer 直答…留待后期再议」→ f8ee2f0(2026-09-07)混合知识库分流定论,answer 直答走科普库已实现;②「(见 kanban 待议)」→ kanban 现无此待议项;③ Out of Scope「启动 RAG warm-up 预热——遗留」→ 5dfeea6 随 ADR-003 落地。时点 PRD 可存档,但读者会误当现状。处置:**待裁**(加一行「本 PRD 已执行完结,后续演进见 f8ee2f0/5dfeea6」头注,或归档)。
- **P17** `.claude/rules/tools.md`(i-have-adhd 行) — 「i-have-adhd | ADHD 友好输出 | 默认生效」;当前会话 skill 清单未装载该 skill。可能为用户环境变化。处置:**待裁**(向人核实后删行或留)。

**遗漏/缺失**

- **P13** `backend/.env.example` — 两键代码读了但 example 全无(含注释):`OLLAMA_MODEL`(config.py:27,默认 qwen3:8b)、`HRP_VERBOSE`(app/main.py:23,verbose 日志开关)。逐键全表见 §3。处置:**D1-d类**(补注释键;HRP_VERBOSE 与契约 §9.1 `--verbose` 的实现取舍同 c1 §3 待裁项联动)。
- **P14** `CLAUDE.md:58-64`(§4 前端命令块) — 未收 `npm run test:unit`(vitest);前端 13 个 spec 文件、69 用例在跑(handoff §5),属「验证入口」。`l2d:fetch` 未收已知,kanban D1-d 已计划「CLAUDE.md §4 命令块同步」。处置:**待裁**(按收录判据裁定 test:unit 是否入块)。
- **P16** `frontend/README.md` — 脚手架原文零定制;`VITE_WS_URL` 是前端唯一环境变量,在 App.vue/station.ts/settings.ts/asr.ts 四处读取(backlog §1 已挂复制问题),但无 `.env.example`、无任何文档说明;`frontend/scripts/fetch-l2d.mjs` 也无使用说明(kanban D1-d「README 补可见性」已计划)。处置:**D1-d类**(随 D1-b/D1-d 一并落)。
- **P18** 根 `README.md` 缺失;`backend/` 无 README — 基线事实,不作问题展开:PROGRESS:34-35 已有计划行(「README △ 编码后」),D1-b 渐进式披露链第一环即 README。处置:**结构类**(D1-b 生成相位覆盖,无需单独立项)。

**互联性·待裁**

- **P15** 用例/判据单源口径成环 — 链路:`acceptance-v1.md:23,34,47` 各节标「判据=CLAUDE.md §8-x」→ `CLAUDE.md:93` 声明「交付验收判据单源=docs/tests/acceptance-v1.md」→ `frontend-plan.md:209`/`backend-plan.md:241` 声明「用例定义单源=CLAUDE.md §8」。每跳可解读(冒烟话术单源=CLAUDE.md §8;细判据单源=acceptance),但「判据=CLAUDE.md §8-x」的措辞与 CLAUDE.md 自己的「判据单源」声明方向相反。处置:**待裁**(D2 拧口径:acceptance 节内改「话术=CLAUDE.md §8-x,判据=下述清单」)。

**已挂账对照(不重复立项)** — c1-review.md §3 文档冲突批 7 项与本文重叠关系:契约 §3.4 mp3→wav、§9.1 `--verbose` vs HRP_VERBOSE、§9.3 事件名补全、backend-plan §2 tts emotion_label、replay HH:MM、station 404/409 语义、若干注释措辞——均为已裁定赢家待执行,归 C1 销账流程,D2 验收时核对即可。本文 P13 的 HRP_VERBOSE 缺键是该批的新增侧面(example 缺文档),不与冲突。

## 3 .env.example 逐键核对表

读键来源:`backend/app/config.py`(os.getenv)+ `app/main.py:23` + `voice/tts_sidecar.py:42`;tests/ 仅复用 sidecar 端口键。

| 键名 | example 有无 | config.py/app 读否 | 结论 |
|---|---|---|---|
| LLM_PROVIDER | 有(:2) | 读(config.py:22) | 正常 |
| DEEPSEEK_BASE_URL | 有(:4) | 读(:23) | 正常 |
| DEEPSEEK_API_KEY | 有(:5) | 读(:24) | 正常 |
| DEEPSEEK_MODEL | 有(:7) | 读(:25) | 正常 |
| OLLAMA_URL | 有·注释(:10) | 读(:26) | 正常 |
| **OLLAMA_MODEL** | **无** | **读(:27,默认 qwen3:8b)** | **缺失**(P13) |
| REDIS_URL | 有(:13) | 读(:79) | 正常 |
| HF_HOME | 有·注释(:19) | config.py 不读;HF 库直读 | 正常(第三方变量,注释即文档) |
| MODELSCOPE_CACHE | 有·注释(:20) | config.py 不读;ModelScope 直读 | 正常(同上) |
| TTS_SIDECAR_PORT | 有·注释(:23) | 读(config.py:116 + tts_sidecar.py:42) | 正常 |
| TTS_SIDECAR_PYTHON | 有·注释(:24) | 读(config.py:119) | 正常 |
| TTS_SIDECAR_KILL_ON_EXIT | 有·注释(:26) | 读(config.py:128) | 正常 |
| CRISIS_GATE_THRESHOLD | 有(:29) | 读(config.py:17) | 正常 |
| HRP_CONFIG_AES_KEY | 有·注释(:34) | 读(config.py:102) | 正常 |
| CORS_ALLOW_ORIGINS | 有·注释(:37) | 读(config.py:105) | 正常 |
| **HRP_VERBOSE** | **无** | **读(app/main.py:23,verbose 日志开关)** | **缺失**(P13) |

失效键(example 有、代码不读):**0**。前端 `VITE_WS_URL` 不在本表范围(backend example 之外,见 P16)。

## 4 backend/scripts 与 package.json scripts 清单

**backend/scripts/**:不存在。相关事实两则:①kanban A2 曾计划「freeze 两文件迁 backend/scripts/ 或随 D1 落位」,人裁定=留原地,现仍在 `prototypes/tts-latency/freeze_gpu_blueprint.txt`+`freeze_sidecar_rollback.txt`(实测存在),D1-d 落位时再迁;②后端约定命令全在 `pyproject.toml [project.scripts]`(仅 `hrp = "app.cli:main"`)与模块入口(`python -m app.rag.ingest`,--reset/--library)。

**frontend/package.json scripts 全清单**(`frontend/package.json:6-17`):

| script | 命令 | CLAUDE.md §4 收录 |
|---|---|---|
| dev | vite | ✓ |
| build | run-p type-check "build-only {@}" -- | 未收(交付构建,D1-d 范围) |
| preview | vite preview | 未收 |
| test:unit | vitest | 未收(P14 待裁) |
| build-only | vite build | 未收(build 内部件) |
| type-check | vue-tsc --build | ✓ |
| l2d:fetch | node scripts/fetch-l2d.mjs | 未收(D1-d 已计划补) |
| lint | run-s "lint:*" | ✓ |
| lint:oxlint / lint:eslint | oxlint . --fix / eslint . --fix --cache | lint 内部件 |

## 5 统计

| 类别 | 数量 | 编号 |
|---|---|---|
| 硬伤·错误事实/损坏/同文矛盾 | 5 | P01 P02 P05 P06 P08 |
| 硬伤·断链/节号漂移 | 3 | P03 P04 P07 |
| 时效漂移 | 5 | P09 P10 P11 P12 P17 |
| 遗漏/缺失 | 4 | P13 P14 P16 P18 |
| 互联性待裁 | 1 | P15 |
| **合计** | **18** | 另:c1-review §3 已挂账 7 项不重复计 |

**散篇死活判定汇总**:tasks-arrangement=活(带 P11);references=活;data-contract=活(待回填占位仍在,回验未执行);option=活(带 P05/P06/P07);prds/rag-full-corpus-bge-m3=**疑死**(P12,建议归档加完成注)。
