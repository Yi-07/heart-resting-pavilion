# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `docs/architecture/*`、`AGENTS.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 0. 当前状态(下一窗口从这里接)

- **已完成并 commit**:A1-A4 / B1 / B2 / C1 / D1(a/b/c/d 全落) / D2;文档规范化轮推进至 #10(逐文档轮 13/13 过审替换,全库阅读审计修正批进行中;详情见 workspace/HANDOFF.md)。逐批 commit 见 git log。
- **当前:看板全清,待推远程**。远程已配置(origin=github.com/Yi-07/heart-resting-pavilion),推增量即可。
- **推远程后遗留(不阻塞)**:backlog §4 两项(Redis compose 拉起/临时 clone 实测)。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| 人看文档编写 | doc-standards skill(十判据+骨架库;文风叠加 doc-style-human) |
| agent 看文档 | mattpocock writing-for-agents(全套已入库 .claude/skills/mattpocock/) |
| 架构级决策盘问 | grill-with-docs(grilling+domain-modeling 连用);定案落 docs/adr/ |
| UI 定稿前 / 动效 | design-taste-frontend(用户级自备)/ emil-design-eng |

## 2. 环境现场(命令与判据见 `AGENTS.md` 与 `docs/guides/option.md`,此处只记坑)

- **e2e 脚本语义两处随 C1 变更**:e2e_a_collect 改自适应编排(LLM 跨字段提取一轮可填满四字段提前停采);e2e3_f F3 断言改新语义(`turns≥1 且 summary>0`)。改 LLM 提取行为再跑这两脚本先读其头注。
- **pytest 已知偶发**:test_routing_gate 偶发状态敏感(残留热层影响门控断言;单跑/重跑均绿)——隔离修法挂 backlog §3。
- **文档规范**:唯一记录处是 doc-standards skill(`.claude/skills/doc-standards/`)+doc-style-human(`.claude/rules/`)。
- **CosyVoice venv/RAG 模型(backend/models/,--local-dir 下载)/Chroma(backend/.rag_store)/Live2D 素材(public/vendor/,fetch-l2d.mjs 生成)/语音素材**:均 gitignored,clone 后按 option.md 补。
- **AGENTS.md 上下文形态**:CLAUDE.md 经 @ 引用 AGENTS.md 薄壳;改共享规范改 AGENTS.md,CLAUDE 专属差异记 CLAUDE.md「Claude Code 专属」节。

## 3. 已定案的架构裁定(勿重开)

- **C1 修复批定案**(细节见 `docs/tests/reviews/c1-review.md`):softscan 采用每轮软预筛+新增命中 LLM 复核(risk_reviewed_terms 去重);H4 日志脱敏记 type(exc).__name__;admin save() api_key 缺省保留旧值;admin/station 无鉴权是原型期有意决策(backend-plan §2,暴露前加信物);mood_select 回合内不推进 trace;二进制帧改 error 帧;session_id REST 约束;Formulation.is_filled 是填格判定唯一记录处;rag engine 顶部零重依赖;station 走 retrieve_async。
- **D1 批裁定细节见 kanban D1 各子条括注**:AGENTS.md 单源+CLAUDE 薄壳;六件套 git mv docs/architecture/ 原名;ARCHITECTURE.md 是地图+指针(spec 仍权威);中文;prototypes 不入摸查;摸查只出清单/结构类 D1-b~d 修/台账类归 D2;文档用职能声明+头部指针区+行内轻标记;AGENTS.md 简洁原则(规范必落实,细节指针按需加载)。
- **Memory() 构造异常泄连接串已裁定留档不修**(backlog §2);待办池唯一记录处见 docs/todos/backlog.md;二期范围见 ARCHITECTURE_PROGRESS §四。
- 其余裁定(ADR-001~005/危机词表分档/Finish shield)同 ADR 与 git log,不复制。

## 4. 工程约定与陷阱(ruff/mypy/框架)

- **后端**:ruff 0.16 干净(app+tests/e2e);mypy 48 文件干净;pytest 134 passed(全量,Redis 在跑)。loguru 内存 sink:`extra` 是 dict、`level` 用 `.name`。
- **conftest**:FakeMemory 需随 Memory 接口同步;app.main.get_memory monkeypatch(lifespan ping 用)。
- **前端**:type-check/lint 干净;scoped CSS 全局类在 main.css;`noUncheckedIndexedAccess` 收窄;运行时 SVG 吃不到 scoped CSS。
- **TaskStop 杀不掉 python 子进程**:按端口 taskkill //F(8000 后端/9880 sidecar 都要清);改后端代码必须重启 hrp(无 --reload 常驻)。
- **e2e 断言基准**:危机看 crisis_gate_hit 的 hit/severity(WARN 即 hit);软词命中是同事件 INFO;降级事件是 memory_degraded;ASR 指纹 `len={n} sha1:{8hex}`;stage_map wire 字段是 `from` 非 `from_`。

## 5. 现状

- 主线 1-9 + 交付批次 A/B/C + D1+D2 全部完成;测试盘:后端 pytest 134 + e2e 脚本 16 个 + 前端 69。
- **当前:文档规范化轮 #10 全库阅读审计进行中(详见 workspace/HANDOFF.md),看板主线全清待推远程**;推远程后遗留:backlog §4 两项。
