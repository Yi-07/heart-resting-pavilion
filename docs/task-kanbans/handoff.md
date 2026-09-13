# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `architecture/*`、`CLAUDE.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 0. 当前停点(下一窗口从这里接)

- **已完成并 commit**:A1-A4 / B1 / B2 / C1 / **D1-a(本窗口)**。D1-a=全库文档摸查(子 agent 黑盒只读),18 项问题清单+.env.example 逐键核对落 `docs/reviews/d1a-survey.md`;人已审并据它拍板全部 D1 未决问题。
- **D1 盘问裁定单源=kanban D1 行括注**(grill-with-docs 两轮)。要点:树 v3=根 4 入口[README/CONTRIBUTING/AGENTS/ARCHITECTURE]+CLAUDE.md 薄壳+docs/ 单根树[六件套 git mv docs/architecture/ 原名;docs/README.md 总索引二次跳转;guides/option.md;prds 加完结注;删 research/preview];工具落库=.claude/rules+skills 入库[mattpocock 全套 426K 镜像+emilkowalski;scene-walkthrough-TODO.md 留盘单独 ignore;MCP 三件[chrome-devtools/playwright/context7]走 CONTRIBUTING 部署指令,不建 .mcp.json;design-taste-frontend/i-have-adhd 标用户级自备不拷];P01=frontend-plan §2 重复段按「两 preview 互为参考互补/同组件两套并存/拿不准停下问人」合并一段;AGENTS.md 简洁原则=开发规范必落实[docs 存放/代码风格/日志审计边界等],细节指针内化按需加载。
- **本窗口下一步**:笔2 vendor 批+tools.md 重写(草稿先呈人审)→ D1-b 逐份大纲(README→docs/README→CONTRIBUTING→AGENTS.md→ARCHITECTURE.md,每份大纲人审砍后再写正文)→ D1-d 脚本化+临时 clone 实测(freeze 蓝本入库+option.md 步骤 4 重写)。**D2 输入=d1a-survey.md**:台账类 P02/P03/P09/P10/P15,待裁 P07/P11/P12/P14/P17。
- **环境**:Redis=Docker 容器 `hrp-redis`(6379;另有无关容器 `docker-redis-1` 勿动);后端 `cd backend && uv run hrp`;破坏性 e2e3_g 会 stop/start 该容器。
- **已知陷阱**(沿用):全量 pytest 按 deselect 三真链路文件跑(test_voice/test_memory/test_retrieve);e2e 脚本串行(日志按时间窗断言);破坏性用例(g 与 `e2e3_f_replay.py --clear`)压轴;Windows GBK 下跑 e2e 若 UnicodeEncodeError,e2e_lib 已带 stdout UTF-8 兜底(仍崩就配 `PYTHONIOENCODING=utf-8`)。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| D1 人看文档编写 | **严格照 `.claude/rules/doc-style-human.md`**(技术文档工程师铁律)+ doc-standards 十判据叠加(十判据管删留/单源) |
| D1 agent 看文档 | mattpocock writing-for-agents skill 方法学(全套已入库 .claude/skills/mattpocock/) |
| UI 定稿前 / 动效 | `design-taste-frontend` / `emil-design-eng` |
| 改架构/大方向前 | `mattpocock-skills:grilling`;决策定案落 `docs/adr/` |

## 2. 环境现场(命令与判据单源=CLAUDE.md §4/§8,此处只记坑)

- **e2e 脚本语义两处随 C1 变更**:e2e_a_collect 改**自适应编排**(LLM 跨字段提取一轮可填满四字段提前停采,脚本按已填字段数/下一帧类型判定走向,不再假设固定轮次);e2e3_f F3 断言改新语义(`turns≥1 且 summary>0`——append_turn 热层过期冷启动会从温层播种摘要)。改 LLM 提取行为再跑这两脚本先读其头注。
- **pytest 已知偶发**:test_routing_gate 偶发状态敏感(固定 session 连真 Redis,残留热层影响门控断言;单跑/重跑均绿)——隔离修法挂 backlog §3。
- **启动提示标志化/日志事件两落点/e2e 断言口径/station·admin 路由日志只在 message**:沿用(见 git 历史版 handoff 与 e2e_lib)。
- **CosyVoice venv/RAG 模型/Chroma/Live2D 素材/WS ping_interval=None/语音素材**:同前(见 git log 历史 handoff;冻结蓝本两文件仍�� prototypes/tts-latency/ 待 D1 处置)。

## 3. 已定案的架构裁定(勿重开)

- **C1 修复批定案**(细节与场景演绎=`docs/reviews/c1-review.md`):softscan 节点=每轮软预筛+新增命中 LLM 复核(`risk_reviewed_terms` 去重,成本有界);H4 日志脱敏统一记 `type(exc).__name__` 不记报文;admin save() api_key 缺省=保留旧值;**admin/station 无鉴权=原型期有意决策**(backend-plan §2 决策段,暴露前必须加信物);mood_select 回合内不推进 trace;二进制帧→error 帧不崩连接;session_id REST 约束(≤64+字符集);Formulation.is_filled=填格判定单源;rag engine 顶部零重依赖;station 走 retrieve_async。
- **Memory() 构造异常泄连接串=已裁定留档不修**(触发组合=自设密码+URL 写错,原型不触发;修法记录在 backlog §2)。
- **待办池单源已迁 `docs/todos/backlog.md`**(kanban §3=指针);二期范围单源仍=ARCHITECTURE_PROGRESS §四。
- 其余裁定(ADR-001~005/危机词表分档/Finish shield/mood_select 采集态静默等)同 ADR 与 git log,不复制。

## 4. 工程约定与陷阱(ruff/mypy/框架)

- **后端**:ruff 0.16 干净(app+tests/e2e);mypy 48 文件干净;pytest 110 passed(deselect 三真链路)。loguru 内存 sink:`extra` 是 dict、`level` 用 `.name`。
- **conftest**:FakeMemory 需随 Memory 接口同步;app.main.get_memory monkeypatch(lifespan ping 用)。
- **前端**:type-check/lint 干净;scoped CSS 全局类在 main.css;`noUncheckedIndexedAccess` 收窄;运行时 SVG 吃不到 scoped CSS。
- **TaskStop 杀不掉 python 子进程**:按端口 taskkill //F(8000 后端/9880 sidecar 都要清);改后端代码必须重启 hrp(无 --reload 常驻)。
- **e2e 断言口径**:危机看 crisis_gate_hit 的 hit/severity(WARN=hit);软词命中=同事件 INFO;降级=memory_degraded;ASR 指纹 `len={n} sha1:{8hex}`;stage_map wire 字段是 `from` 非 `from_`。

## 5. 现状

- 主线 1-9 + 冲刺 A(A1-A4)+ B(B1/B2)+ **C(C1)** 全落;测试盘=后端 pytest 110 + e2e 脚本 16 个 + 前端 69。
- **当前=看板 §2 D1 进行中**(D1-a 摸查+盘问裁定已落;队列=笔2 工具落库→D1-b 逐份大纲→D1-d 实测);之后 D2 收尾即可推远程。
