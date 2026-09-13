# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `docs/architecture/*`、`AGENTS.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 0. 当前停点(下一窗口从这里接)

- **已完成并 commit**:A1-A4 / B1 / B2 / C1 / **D1(本窗口,a/b/c 全落,d 部分落)**。文档体系=根 4 入口(README/CONTRIBUTING/AGENTS/ARCHITECTURE)+CLAUDE.md 薄壳(@AGENTS.md)+docs/ 单根树;工具落库(.claude/rules+skills,mattpocock 全套+emilkowalski);option.md 重写为七模块就绪手册(模型 --local-dir 落位 backend/models/);freeze 两蓝本入 backend/scripts/。逐批 commit 见 git log(cba6fa3 树迁移/f1e3186 工具/323a16a 六入口/db7ed53+8b3bb52+7ad801d 手册与蓝本)。
- **当前=看板全清,待推远程**:D2 已落定(kanban D2 行括注=销账明细)。git remote 未配,推前问人仓库地址。
- **推远程后遗留(不阻塞)**:backlog §4 两项(Redis compose 拉起/临时 clone 实测);data-contract 待队友 50 条样本回填。
- **D1-d 剩余两项(人裁定推远程后再做,backlog §4)**:①Redis compose 一次拉起(替换 option §2.1)②临时目录 clone 按 option.md 全流程实测。
- **D2 之后**:推远程(git remote 未配,推时问人仓库地址)。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| 人看文档编写 | `.claude/rules/doc-style-human.md` + doc-standards 十判据叠加 |
| agent 看文档 | mattpocock writing-for-agents(全套已入库 .claude/skills/mattpocock/) |
| 架构级决策盘问 | grill-with-docs(=grilling+domain-modeling 连招);定案落 docs/adr/ |
| UI 定稿前 / 动效 | design-taste-frontend(用户级自备)/ emil-design-eng |

## 2. 环境现场(命令与判据单源=AGENTS.md §3/§7,此处只记坑)

- **e2e 脚本语义两处随 C1 变更**:e2e_a_collect 改**自适应编排**(LLM 跨字段提取一轮可填满四字段提前停采);e2e3_f F3 断言改新语义(`turns≥1 且 summary>0`)。改 LLM 提取行为再跑这两脚本先读其头注。
- **pytest 已知偶发**:test_routing_gate 偶发状态敏感(残留热层影响门控断言;单跑/重跑均绿)——隔离修法挂 backlog §3。
- **文档规范**:每份交付文档开头=职能声明+头部统一指针区;文内只用行内轻标记(不散显链);单源裁定见 d1b-pointer-survey.md 头注。
- **CosyVoice venv/RAG 模型(backend/models/,--local-dir 落位)/Chroma(.rag_store)/Live2D 素材(public/vendor/,fetch-l2d.mjs 拉)/语音素材**:均 gitignored,clone 后按 option.md 补。
- **AGENTS.md 上下文形态**:CLAUDE.md=@AGENTS.md 薄壳;改共享规范改 AGENTS.md,CLAUDE 专属差异记 CLAUDE.md「Claude Code 专属」节。

## 3. 已定案的架构裁定(勿重开)

- **C1 修复批定案**(细节=`docs/reviews/c1-review.md`):softscan=每轮软预筛+新增命中 LLM 复核(risk_reviewed_terms 去重);H4 日志脱敏记 type(exc).__name__;admin save() api_key 缺省=保留旧值;admin/station 无鉴权=原型期有意决策(backend-plan §2,暴露前加信物);mood_select 回合内不推进 trace;二进制帧→error 帧;session_id REST 约束;Formulation.is_filled=填格判定单源;rag engine 顶部零重依赖;station 走 retrieve_async。
- **D1 批裁定单源=kanban D1 各子条括注**:AGENTS.md 单源+CLAUDE 薄壳;六件套 git mv docs/architecture/ 原名;ARCHITECTURE.md=地图+指针(spec 仍权威);中文;prototypes 不入摸查;摸查只出清单/结构类 D1-b~d 修/台账类归 D2;文档=职能声明+头部指针区+行内轻标记;AGENTS.md 简洁原则(规范必落实,细节指针按需加载);option.md=七模块全量安装单路径(无分档/可选概念)。
- **Memory() 构造异常泄连接串=已裁定留档不修**(backlog §2);待办池单源=docs/todos/backlog.md;二期范围单源=ARCHITECTURE_PROGRESS §四。
- 其余裁定(ADR-001~005/危机词表分档/Finish shield)同 ADR 与 git log,不复制。

## 4. 工程约定与陷阱(ruff/mypy/框架)

- **后端**:ruff 0.16 干净(app+tests/e2e);mypy 48 文件干净;pytest 110 passed(deselect 三真链路文件)。loguru 内存 sink:`extra` 是 dict、`level` 用 `.name`。
- **conftest**:FakeMemory 需随 Memory 接口同步;app.main.get_memory monkeypatch(lifespan ping 用)。
- **前端**:type-check/lint 干净;scoped CSS 全局类在 main.css;`noUncheckedIndexedAccess` 收窄;运行时 SVG 吃不到 scoped CSS。
- **TaskStop 杀不掉 python 子进程**:按端口 taskkill //F(8000 后端/9880 sidecar 都要清);改后端代码必须重启 hrp(无 --reload 常驻)。
- **e2e 断言口径**:危机看 crisis_gate_hit 的 hit/severity(WARN=hit);软词命中=同事件 INFO;降级=memory_degraded;ASR 指纹 `len={n} sha1:{8hex}`;stage_map wire 字段是 `from` 非 `from_`。

## 5. 现状

- 主线 1-9 + 冲刺 A/B/C + **D1(a/b/c 落,d 剩两项在 backlog)** 全落;测试盘=后端 pytest 110 + e2e 脚本 16 个 + 前端 69。
- **当前=看板全清待推远程**;推远程后遗留=backlog §4 两项+data-contract 回填。
