# D1-b 重复叙述与指针规范搜查

> 范围:全部 .md(排除 .venv/node_modules/prototypes/.claude/.git);交付组逐份细查,工作组只查与交付组的真重复。基线:根四入口+docs 树迁移(cba6fa3)已落,CLAUDE.md 仍为全量版,薄壳化未执行。
> 裁定基线(四条):开头职能声明;跳转指针统一摆头部职能区;文内只留行内轻标记;同一事实单源。单源方向权威序:spec>plan>地图>入口;入口只留「是什么」。
> 与 d1a-survey 关系:P15(用例口径成环)、P07(option 断链)等已挂账项本文不重复立项,只在对应条标注衔接。

## 1 逐文档职能声明核查表

| 文档 | 开头职能声明(引原文) | 判定 |
|---|---|---|
| `README.md` | 无。L3 直接进入「## 项目定位」 | 缺 |
| `CONTRIBUTING.md` | 无。L3 直接进入「## 协作节奏」 | 缺 |
| `AGENTS.md` | L3「**职能**:coding agent 开工前必读。改代码前先读完本文;改架构先讨论」+L4 护栏 | 合规 |
| `ARCHITECTURE.md` | L3「全貌入口。……本文只画地图,不复制参数。」管与不管都写明 | 合规(范本) |
| `CLAUDE.md` | L3「本文件是 coding agent 的**开工前必读**」 | 合规(待薄壳化,见 §4) |
| `docs/README.md` | 无声明行,直接进入分类表 | 缺(索引职能自明,仍应补一行) |
| `docs/guides/option.md` | L3-L5 图例/分工/依据;L250「**边界**:本手册只列操作分工,不涉及实现代码」 | 合规 |
| `docs/guides/deep-module.md` | L3「**职能**:全代码库新模块设计与重构的判据单源」+L4 术语外指 | 合规 |
| `docs/architecture/architecture-spec.md` | L3「**关系**:**本文件为权威源**」;§0 历史外指 PROGRESS | 弱(只声明权威,未划不管面;消息格式归 ws-contract 一句未写) |
| `docs/architecture/ws-contract.md` | L3 权威源+L4「**范围**:……前端内部(模板声明/渲染器)不在此文档」 | 合规(管/不管双写) |
| `docs/architecture/frontend-plan.md` | L3 权威源+L4 目标 | 弱(未声明不管面;「文件真源=文件系统」在 §2 表头,不在开头) |
| `docs/architecture/backend-plan.md` | L3 权威源+L4 目标 | 弱(同上) |
| `docs/architecture/CONTEXT.md` | L3 职能(正词/避用标准)+L4 维护规则 | 合规 |
| `docs/architecture/ARCHITECTURE_PROGRESS.md` | L3「**用途**:会话压缩/恢复时的上下文锚点」;「本文件只留进度与历史」在 L54(§三内) | 弱(不管面声明藏在文中,应上移头注) |
| `docs/tests/acceptance-v1.md` | L3 职能+L4 范围+L5 口径单源+L6 指标基线 | 合规(范本) |
| `docs/prds/rag-full-corpus-bge-m3.md` | L3 需求描述+「契约与字段定义单源=……本 PRD 只写改动面」+L5 完结注 | 合规 |
| `docs/architecture/data-contract.md` | L3「**范围**:数据生产者≠消费者的数据接口……RAG 机器……归本项目」 | 合规 |
| `docs/references.md` | L3「开发文档只留规范与采纳成果;本文档统一存放来源、溯源」 | 合规 |
| `docs/todos/tasks-arrangement.md` | 无 | 缺 |
| `docs/Inspiration.md`(附加查) | L3「记录……的想法。与正式方案(architecture-spec-v2.md)分离」 | 弱(有管/不管,但引用旧文件名,见 L10) |

小计:合规 11 · 弱 5 · 缺 4(共 20 份;工作组 10 份不适用声明判据)。

## 2 重复叙述清单

严重在前。引文均为原文摘录。

### R01 冒烟/验收话术与判据:5 处叙述 + 单源方向成环(衔接近 d1a P15,升级立项)

**事实主题**:三链路验收话术(`什么是正念`/`最近很焦虑睡不着`/`我不想活了`)与基础帧序判据。

| 位置 | 引文 |
|---|---|
| `CLAUDE.md:96-98` | 「1. **answer**:`什么是正念` → 无 first_frame、无 draw 帧,直接流式答」(§8 共 3 条) |
| `AGENTS.md:97-99` | 同上三行,逐字同 |
| `docs/tests/acceptance-v1.md:23` | 「### 1.1 answer(判据=CLAUDE.md §8-1)」;L26「无 first_frame、无 draw 帧」——§1 简单用例与冒烟同话术同判据 |
| `docs/architecture/frontend-plan.md:192` | 「1. **answer**:输入"什么是正念" → 无黑板,气泡流式文本,结束」 |
| `docs/architecture/backend-plan.md:219` | 「1. **answer**:`user_input("什么是正念")` → text_delta 流式 → done;无 draw」 |

环:acceptance L23/34/47 称判据来自 CLAUDE §8;CLAUDE.md:93 与 AGENTS.md:95 称「交付验收判据单源=docs/tests/acceptance-v1.md」;frontend-plan:202 与 backend-plan:241 又称「用例定义单源=CLAUDE.md §8」。三方互指,读者无终点。

**裁定**:话术与判据单源=`docs/tests/acceptance-v1.md` §1(它已自含双用例与全判据,且被两处声明为单源)。理由:权威序 spec>plan>地图>入口不适用此题,改用「判据载体>速查入口」;acceptance 是唯一含完整判据的文档。落点:acceptance §1.1-1.3 节头删「(判据=CLAUDE.md §8-x)」(判据就在本节);frontend-plan §8 / backend-plan §11 的「单源=CLAUDE.md §8」改「话术与判据单源=docs/tests/acceptance-v1.md §1」;AGENTS §8 三行保留(速查入口,补一句「话术=acceptance §1 简单用例」);frontend-plan §7 / backend-plan §10 只留端视角独有判据(前端 UI 断言/后端日志事件断言),与 acceptance 重复的基础帧序行改行内标记;CLAUDE §8 薄壳化删除。此修同时销 d1a P15。

### R02 CLAUDE.md 全文与 AGENTS.md 重复(已知项,单列;差异清单归 §4)

CLAUDE §1 指针表/§2 边界表/§3 约定/§4 命令/§5 风格/§6 性能/§7 红线/§8 用例/§9 工具 ↔ AGENTS §1/§2/§3/§4/§5/§6/§7/§8/§11,九节对应、大段逐字同。不逐条引文(量太大,抽样:CLAUDE:31-35 与 AGENTS:30-34 边界表五行完全一致)。差异与薄壳方案见 §4。

### R03 红线/日志脱敏叙述:三处实质重复

**事实主题**:日志双输出、脱敏(不落原文/音频/凭证)、危机审计 WARN。

| 位置 | 引文 |
|---|---|
| `AGENTS.md:88-91` | 「1. **日志双输出**:控制台彩色可读(INFO)/文件结构化(DEBUG);loguru 2. **脱敏**:用户文本不落原文(记长度/哈希)· 音频绝不落库 · 凭证……绝不落 3. **危机审计**:危机命中必落审计日志(WARN……)」 |
| `docs/architecture/ws-contract.md:334-339`(§9.4) | 「1. 用户文本:不落日志;需要时记**长度或哈希**……4. **危机命中必须落审计日志**(WARN,event=crisis_gate_hit……)」 |
| `docs/architecture/backend-plan.md:207-212`(§9) | 「**审计**:危机命中必落(WARN);用户文本只记长度/哈希;音频/凭证绝不落」+轮转 10MB/30 天(数值重述 ws-contract §9.5:343) |

CLAUDE.md:88-91 同 AGENTS(R02 已覆盖)。CONTRIBUTING:45 已是指针型(「细则见 AGENTS.md『日志与安全红线』节」),合规。

**裁定**:细则单源=ws-contract §9(日志工程范式与脱敏硬约束)+spec §8(危机判定只在后端)。理由:参数与事件名属契约层,机制归属属 spec;AGENTS/backend-plan 是下游。落点:AGENTS §7 压成一行红线声明+行内标记「细则=ws-contract §9.4 · spec §8」;backend-plan §9 压两行指针,数值(10MB/30 天)删去不复写。

### R04 项目定位整段:PROGRESS §一 复制 spec §1

**事实主题**:项目一句话+产品形态+目标。

| 位置 | 引文 |
|---|---|
| `docs/architecture/architecture-spec.md:15,17,20` | 「面向轻中度情绪困扰人群的情感陪伴 + 心理知识科普工具……」「产品形态:引导式对话,不是回答机器——不等用户一次给完整答案,按节奏分多轮梳理」「目标:中国大学生计算机设计大赛……」 |
| `docs/architecture/ARCHITECTURE_PROGRESS.md:10-13` | L10「面向轻中度情绪困扰人群的情感陪伴 + 心理知识科普工具(明确不提供医疗诊断)」;L11「产品形态:引导式对话……按节奏分多轮梳理」(逐字同 spec:17);L13「目标:中国大学生计算机设计大赛……+ 求职作品集」 |
| `README.md:5` | 「面向轻中度情绪困扰人群的情感陪伴 + 心理知识科普工具。」 |
| `CLAUDE.md:10` | 同句+(非医疗诊断)(归 R02) |

**裁定**:单源=spec §1。README 保留一句(入口「是什么」,合规)。PROGRESS §一 与自身声明冲突:L54 已写「现行架构/参数/契约/技术栈以 spec 与 ws-contract 为准(单源),本文件只留进度与历史」,§一 却整段复制现行定位。落点:PROGRESS §一 压到一行「定位单源=spec §1」+仅留「当前阶段:技术原型」此进度事实。

### R05 命令块与环境前提:README 快速上手复写 AGENTS §4 与 option.md

**事实主题**:`uv sync`/`uv run hrp`/`npm install`/`npm run dev` 及其注释、Redis/.env 前提。

| 位置 | 引文 |
|---|---|
| `README.md:29-41` | 「前提:本机跑起 Redis;`backend/.env.example` 复制出 `backend/.env` 并填密钥」+两段命令块,`uv run hrp        # 启动后端,127.0.0.1:8000` |
| `AGENTS.md:48-65` | 同命令集;L50「uv run hrp # 启动(默认 127.0.0.1:8000;--reload 热载开发,配 TTS_SIDECAR_KILL_ON_EXIT=0)……」 |
| `docs/guides/option.md:55-59,85-87` | 「cp .env.example .env」+redis 容器命令(职能=0-5 步搭建手册) |
| `docs/tests/acceptance-v1.md:11-13` | 「服务 `cd backend && uv run hrp`……| Redis | 6379 在跑」(职能=验收前置验证) |

**裁定**:开发命令单源=AGENTS §4;环境搭建全步骤单源=option.md。理由:入口只留「是什么」;命令语义与收录判据已由 AGENTS §4 L68 声明。落点:README 快速上手压成一行指针(「跑起来:环境=docs/guides/option.md,日常命令=AGENTS.md §4」);若人裁定保留三行欢迎性命令,须删注释复写。acceptance §0 保留验证判据列,前提事实不再展开叙述。

### R06 改动后验证纪律:两份活表 + 一份过时表

**事实主题**:按改动面选跑的检查清单(后端三件/前端两三件/文档)。

| 位置 | 引文 |
|---|---|
| `AGENTS.md:69` | 「**改动后验证**:按改动面选跑对应端检查(后端=ruff/mypy/pytest 三件;前端=type-check/lint/test:unit);改文档 → doc-standards 十判据+收尾 grep……」 |
| `CONTRIBUTING.md:17-25` | 表:「| 后端 | `uv run ruff check app` · `uv run mypy app` · `uv run pytest`(backend/) |」「| 前端 | `npm run type-check` · `npm run lint` · `npm run test:unit`(frontend/) |」 |
| `CLAUDE.md:69` | 「前端=type-check/lint;测试建立前空跑即绿,前端骨架后生效」——**与上两处不一致**(缺 test:unit,且「空跑即绿」已过时,前端 69 用例在跑) |

**裁定**:验证清单单源=CONTRIBUTING「改动后验证」表(格式最全,人/agent 共用);AGENTS §4 L69 压一行指针。理由:同事实双活表必漂移,CLAUDE 版漂移已发生即证据。CLAUDE L69 随薄壳化消失。

### R07 机制速览同层双写:AGENTS §3 ↔ ARCHITECTURE §3

**事实主题**:三路路由、draw 全量+seq、语音单源文本、危机只在后端的速览级叙述。

| 位置 | 引文 |
|---|---|
| `AGENTS.md:38,41` | 「**三路路由**:每条 user_input 先过 `crisis` 危机闸门……」;「**契约要点**:9 种消息……`draw` 传全量 formulation+`seq`(前端 diff);危机判定只在后端;语音输入单源文本」 |
| `ARCHITECTURE.md:58,60,62` | 「| 三路路由 | 每条 user_input 先过危机闸门,再分流 answer / collect | spec §3 |」「| 黑板一图逐步深化 | ……draw 传全量 formulation + seq,前端 diff | spec §5-§6 |」「| 语音输入单源文本 | 录音 → REST 转写 → 文本框确认 → 按文本发送 | ADR-004 |」 |

README:11-17 三链路表判合规(入口「是什么」,只写触发/行为)。spec §3 为权威叙述。

**裁定**:速览单源=ARCHITECTURE §3(地图职能)。理由:两文档同为「根级速览」,事实与粒度重叠;地图管速览,开发指南管约定。落点:AGENTS §3 保留 1-3 条编码约定(路由/隔离/模板),第 4 条「契约要点」(L41)与地图逐项撞车,压成一行行内标记「契约速览=ARCHITECTURE §3 · 格式=ws-contract §2」。AGENTS:43 已有的「机制与参数细节单源」尾注保留。

### R08 ADR 一句话索引双份:ARCHITECTURE §4 ↔ docs/README

**事实主题**:5 篇 ADR 各自的一句话职能。

| 位置 | 引文 |
|---|---|
| `ARCHITECTURE.md:69-73` | 「| [001 记忆分层](docs/adr/001-memory-tiering.md) | 热层存近期轮次原话(短 TTL),中长期只留摘要 |」等 5 行 |
| `docs/README.md:19-23` | 「| [001-memory-tiering.md](adr/001-memory-tiering.md) | 记忆分层(热层轮次原话) |」等 5 行 |

PROGRESS §三 L55 的 ADR 行是台账(「现行规则原文以此为准」),职能不同,不算重复。

**裁定**:ADR 索引单源=ARCHITECTURE §4(架构地图的自然组成,含链接)。落点:docs/README 决策记录节保留文件名链接、职能句删(或整节压一行「5 篇,索引=ARCHITECTURE.md §4」)。理由:索引文档列文件合法,同一句话两写才是重复。

### R09 任务/待办清单职能句三写(轻)

**事实主题**:kanban 与 backlog 的职能描述。

| 位置 | 引文 |
|---|---|
| `CONTRIBUTING.md:40-41` | 「`docs/todos/backlog.md` | 团队任务与系统发现待裁决问题的统一回放处」「`docs/task-kanbans/kanban-v1.md` | 排程执行状态单源(勾选 = 已完成并 commit)」 |
| `docs/README.md:35,37` | 「跨会话执行看板(步骤状态单源)」「遗留待办池单源」 |
| `AGENTS.md:23` | 「跨会话看板/交接……(勾选状态单源,含工作方式 §0 与接力规程)」 |

**裁定**:职能句单源=两文档各自头注(kanban:3-5、backlog:3 已有更完整声明);CONTRIBUTING 表删(docs/README 已全量索引)。理由:入口不留可从索引获得的事实。

## 3 指针散乱与断链清单

类型标注:〔断链〕目标不存在;〔将废〕目标现存但薄壳化后失效;〔散乱〕违反「指针集中头部+行内轻标记」规范。

| # | 类型 | 文档:行 | 事实与引文 | 建议 |
|---|---|---|---|---|
| L01 | 〔断链〕 | `docs/README.md:38,59`;节头 `:31,:54` | L38「[tasks-arrangement.md](tasks-arrangement.md)」指向已删的 docs/tasks-arrangement.md(现=docs/todos/);L59「[data-contract.md](data-contract.md)」指向已删的 docs/data-contract.md(现=docs/architecture/);L31/L54 节头亦写旧路径 | 改新路径;顺手修 |
| L02 | 〔断链〕 | `docs/architecture/backend-plan.md:37` | 「数据对接走 docs/data-contract.md」(旧路径) | 改 `docs/architecture/data-contract.md`;顺手修 |
| L03 | 〔断链〕 | `docs/prds/rag-full-corpus-bge-m3.md:3` | 「契约与字段定义单源=`docs/data-contract.md`」(旧路径) | 同上;顺手修 |
| L04 | 〔断链〕 | `docs/architecture/data-contract.md:23` | 「种子语料起草流程与文件路径单源=docs/option.md」(旧路径) | 改 `docs/guides/option.md`;顺手修 |
| L05 | 〔断链〕 | `docs/architecture/ARCHITECTURE_PROGRESS.md:28,33,38,39,40,41` + `:19` + `:37` | L28「`docs/option.md`」、L33「`docs/data-contract.md`」、L38「docs/research/」(目录已删,d1a P02)、L39「`preview/l1-ui-mockup-v7.html`」(现=docs/architecture/preview/)、L40「`docs/Inspiration.txt`」(现=Inspiration.md)、L41「`docs/tasks-arrangement.md`」;L19「核心文档的指针与性质以 CLAUDE.md §1 为准」;L37「AGENT.md 副本 △ 交付前批」(AGENTS.md 已建,状态失实) | 树迁移 cba6fa3 未同步本表。路径类(L28/33/39/40/41)可顺手修;L19 改指 AGENTS §1;L37/L38 状态行归 D2(与 P02/P09/P10 合并刷新) |
| L06 | 〔断链〕+〔将废〕 | `docs/guides/option.md:218` + `:3,:226-240` | L218「读 docs/research/seam-research-v1.md」(=d1a P07 未销);L3「按 CLAUDE.md 护栏」、会话二/三提示词内「按 CLAUDE.md 开发:构建顺序照 §8」共 5 处 CLAUDE 引用 | L07 随 d1a 裁定(留档块加「文件已删」注);CLAUDE 引用随薄壳化加注「CLAUDE.md 已薄壳,按 AGENTS.md 执行」 |
| L07 | 〔将废〕 | `docs/tests/acceptance-v1.md:23,34,47,113` | 「(判据=CLAUDE.md §8-1/2/3)」×3+「安全红线复核(§7 of CLAUDE.md)」 | 与 R01 同批修:节头括注删;L113 改「红线=AGENTS.md §7/ws-contract §9.4」 |
| L08 | 〔将废〕 | `docs/task-kanbans/kanban-v1.md:4,5,20,59,60`、`docs/task-kanbans/handoff.md:4,23` | kanban L5「构建顺序/命令/构建验收判据单源 = CLAUDE.md §4/§8」、handoff L23「命令与判据单源=CLAUDE.md §4/§8」等 | 工作组合理互引不算问题;单源地址随薄壳化同批改指 AGENTS §4/§8(R01 裁后 §8 再指 acceptance) |
| L09 | 〔散乱〕 | `README.md:43`(正文显链)、`CONTRIBUTING.md:34,45`(正文显链)、`ARCHITECTURE.md:69-73`(§4 显链表,非头部) | README L43「见 [CONTRIBUTING.md](CONTRIBUTING.md)」;CONTRIBUTING L34/L45 文内显链;ARCHITECTURE §4/§5 两个指针簇在中下部 | 各文档头部职能区加 3-5 行指针表(或指针行),文内显链改行内轻标记(如「环境=option.md」);ARCHITECTURE §4/§5 合并上移至头部指针区。AGENTS/spec/ws-contract/双 plan/CONTEXT/deep-module 全部零显链,已合规;docs/README 本身即索引文档,豁免 |
| L10 | 〔断链〕 | `docs/Inspiration.md:3,:45` | L3「与正式方案(architecture-spec-v2.md)分离」(旧文件名,现=architecture-spec.md);L45「`preview/l1-ui-mockup-v5.html` 已被 v6 取代」(v6 亦已被 v7 取代) | 灵感随手档,轻;顺手改或挂 backlog |
| L11 | 补遗 | `docs/README.md` 全文 | 总索引漏收 `docs/Inspiration.md`(实存);另 frontend/README.md 为脚手架原文(d1a P16 已挂,不重复立项) | 补一行 |

## 4 CLAUDE.md 薄壳化节清单

依据:AGENTS.md 已覆盖九节对应内容。逐节比对差异如下。

**删节(内容已被 AGENTS.md 覆盖)**

| CLAUDE.md 节 | 覆盖处 | 差异核验 |
|---|---|---|
| §1 项目一句话+文档指针表(L8-25) | AGENTS §1(L10-24)+L6 冲突解决 | AGENTS 表多「文档总索引」行,是超集;一句话已单源于 spec §1/README L5(R04) |
| §2 边界表(L27-35) | AGENTS §2(L26-34) | 五行逐字同 |
| §3 核心架构约定(L37-43) | AGENTS §3(L36-43) | CLAUDE 独有「数据填充」「测试模板 3 个(emotion_wheel/beck_formulation/stage_map)」——模板名单源已在 ws-contract §5.2(L217-218)与 frontend-plan §2(L28),无需迁移 |
| §4 开发命令(L45-69) | AGENTS §4(L45-69) | AGENTS 增 `npm run test:unit`(L62);CLAUDE 独有注「测试建立前空跑即绿」已过时(d1a P14 已裁),不迁移 |
| §5 代码风格(L71-78) | AGENTS §5(L71-78) | 深模块指针 CLAUDE 版指 backend-plan §2,AGENTS 版已改指 `docs/guides/deep-module.md`(更准),取 AGENTS 版 |
| §6 性能热点(L80-84) | AGENTS §6(L80-84) | 逐字同 |
| §7 日志与安全红线(L86-91) | AGENTS §7(L86-91) | 逐字同;两处同受 R03 裁定约束 |
| §8 验收用例+构建顺序(L93-100) | AGENTS §8(L93-101) | 两版均含冒烟 3 条与构建顺序;R01 裁定后 AGENTS §8 补话术来源声明 |
| §9 工具与 Skill(L102-104) | AGENTS §11(L122-124) | AGENTS 版为单源指针式,更合规 |

**保留节(Claude 专属)**

- 标题+一行职能声明:「coding agent 规则单源=AGENTS.md;本文件仅 Claude Code 入口」
- `@AGENTS.md` 引用(或「先读 AGENTS.md」指令行)
- Claude 专属差异节:当前无内容,预留空位(有差异再开)

**薄壳化同批连锁改(下游指针重定向)**

PROGRESS:19(L05);acceptance:23/34/47/113(L07);frontend-plan:202、backend-plan:241(R01);data-contract:29/37(「复用 CLAUDE.md §8」改指 acceptance §1);option.md:3/226-240(L06);kanban:4/5/20/59/60、handoff:4/23(L08);tasks-arrangement:34(交付物「`CLAUDE.md` / `Agent.md`」名单过时,改 AGENTS.md)。

## 5 统计与处置分派

| 类别 | 数量 | 编号 |
|---|---|---|
| 重复叙述 | 9 | R01-R09 |
| 指针断链/将废/散乱 | 11 | L01-L11 |
| 职能声明 | 合规 11 · 弱 5 · 缺 4 | 见 §1 |
| 检查文档数 | 30 | 交付组 20 + 工作组 10 |

**D1-b 顺手修候选**(改动小、方向已由本报告裁定、不涉新架构):L01、L02、L03、L04、L05 的纯路径行(28/33/39/40/41)、L10、L11(docs/README 补 Inspiration 行)。修时遵守 CLAUDE/AGENTS 冲突规则:路径类断链属「改输家对齐赢家」。

**挂 D2 台账**(涉判据重排或人审):R01(=d1a P15 升级版,拧 acceptance↔双 plan↔入口口径)、R03/R04/R06/R07/R08/R09(叙述压缩,逐处改写需人审)、L05 状态行(与 P02/P09/P10 合并)、L06 前半(=P07)。

**随 CLAUDE 薄壳化同批执行**(独立工作项,依据=§4 清单):§4 删节+连锁改 8 处;R02 随之销。

**写作规范面**(D1-b 后续逐份正文重写时落实):各交付文档补职能声明(§1 判「缺/弱」的 9 份);指针收拢头部(§1 判「缺」+L09 涉及的 README/CONTRIBUTING/ARCHITECTURE/docs-README 四份先行)。
