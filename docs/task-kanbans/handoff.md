# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `architecture/*`、`CLAUDE.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| 步骤5 黑板动效/视觉决策 | `emil-design-eng` · `animate` · UI 定稿前 `design-taste-frontend` |
| E2E 验证(真实前后端) | `webapp-testing`(playwright);改 HTML 预览后 chrome-devtools 复验 |
| 改架构/大方向前 | `grilling`;决策定案落 `docs/adr/` |
| 写/改交付文档、清扫避用词 | `doc-standards`(十判据) |
| 默认生效 | `i-have-adhd`(输出友好) |

## 2. 环境现场(命令与判据单源=CLAUDE.md §4/§8,此处只记坑)

- **模型缓存**:`HF_HOME=D:\MetaverseStudy\hf_cache`(bge-small-zh-v1.5 与 bge-reranker-v2-m3 已就位);Chroma 持久化在 `backend/.rag_store/`(已灌 15 条种子语料)。
- **5173 有常驻 vite**(同目录热更,直接用);后端 uvicorn 8000 按需起停,不用 --reload(改完重启)。
- **Windows 坑**:仓库文本 CRLF——前端读 `architecture/*.md` 的正则要 `\r?\n` 且跨行匹配加 `s` 标志;git-bash 管道下 Python print 中文是 GBK 乱码(仅显示,不影响逻辑);TestClient 的 WS 测试是同步函数,不能 `await`,等待后端异步任务用 `time.sleep`(portal 线程继续跑)。
- **冷启动**:首次 RAG 查询懒加载模型 ~30s(后续秒级);演示前先打一条知识问题预热。

## 3. 已定案的架构裁定(勿重开,详见 git log 与各模块 docstring)

- done 帧**带** session_id(ws-contract §1 赢家,§3.5 示例已补);user_input/mood_select 的 session_id **可空**(首条消息前端尚无 id,网关按连接补全)。
- **轮次回答=同回合连续,不发 first_frame**(契约 §6.2 语义);「等待期抢占」落到 answer/危机类输入(弃采集态转直答/热线);**分析中抢占**=cancel 任务+弃 state+emitter dead(未发帧蒸发)→ entry 用承接安抚语。
- 模糊输入 `classify_rules` 规则速判按 collect 兜底(first_frame ≤300ms 不等 LLM);LLM 异步精化 emotion_label 尚未接(spec §4 L4 允许,非必须)。
- 种子语料 15 条**人审定稿**(`backend/data/rag_seeds.jsonl`);队友全量语料到位后走 `docs/data-contract.md` §4 回验替换。
- StageMapData 字段 `from_`(Python 关键字),一切序列化必须 `model_dump_json(by_alias=True)`。

## 4. 工程约定与陷阱(ruff/mypy/框架)

- **ruff 0.16 默认规则集已扩**(I/RUF/TRY/BLE 都在默认):import 与 `__all__` 排序可 `--fix`;pydantic 校验器要 ValueError → `# noqa: TRY004`(注释写理由);降级路径盲捕 Exception → `# noqa: BLE001`。
- **TYPE_CHECKING 前向引用 + 运行时注解求值会 NameError** → 相关模块顶部 `from __future__ import annotations`(emitter/analysis/gateway 均因此炸过,现已带)。
- **LangGraph**:节点签名 `(state, config)`,emitter 从 `config["configurable"]["emitter"]` 取(不进 state);条件边函数收 GraphState 包装纯函数 `where_next(cs)`;图模块级编译一次。
- pytest-asyncio `asyncio_mode=auto` 已配;loguru 内存 sink 的 record:`extra` 是 dict、`level` 用 `.name` 属性。
- **懒加载分层**:chroma/sentence-transformers/langgraph 全部函数内 import(网关启动零成本);`app.rag`、`app.agents` 的入口模块保持轻 import。
- mypy:jieba/rank_bm25 无 stub → pyproject `[tool.mypy] overrides` 已配;openai TypedDict 联合用 `cast(ChatCompletionMessageParam, ...)` 收窄。
- 模块环:`app.collect.questions ↔ app.agents.state` 单向依赖可忍(partial package init 时 submodule 直import 可用),新增 import 前想清方向。

## 5. 步骤5(黑板)现场规划

任务分解与勾选在 kanban-v1 §2。此处只存 v7 mockup 蒸馏(源:`architecture/preview/l1-ui-mockup-v7.html`,963 行,**勿整读**,按下行号跳读):

- **设计变量**(L12-19):`--bg:#FAF6EF; --ink:#3E3A35; --muted:#6E675E; --line:#EDE6DB; --primary:#8BAE97; --primary-deep:#6E937C; --accent:#D58A63; --moodv:#C8A2C8; --board:#3A4638; --chalk:#F3EBDD; --chalk-sub:#B9C4B4`;`--canvas-ratio:1.4545`(板宽高比=模板画布 640/440,消除 letterbox);`--ease:cubic-bezier(.23,1,.32,1)`;`.glass`=玻璃拟态(渐变+blur22+saturate1.5)。
- **黑板框架**(L74-90):`.board-frame` 左 0 宽 64%,细橡木 repeating-gradient 边框 7px 内衬;四角 `.hud-*` 金色 L 角标(hudpulse 呼吸);`.board` breathglow 呼吸光晕;`.zoom-btn` 右下放大;`.bt` 板标题(serif 粉笔白),`.bnote` 板底注(chalk-sub,手写体 Ma Shan Zheng)。
- **粉笔绘制**(L445-460,照搬即可):`roughLine`(中点抖动+二次贝塞尔)/`roughEllipse`(半径噪声)/`chalkText`/`chalkGoto`(粉笔光标沿点移动)+ dash-reveal 描边动画;feDisplacementMap 滤镜**只套图形不套文字**(保标签可读)。
- **beck 布局坐标**(L479-504):顶部椭圆标题(320,52,148×26)→ 树状三层:情境(320,320,140×27)/中间信念(320,406,158×24)等,竖线连接;布局即模板声明的锚点来源。
- **stage_map**(L544-547):节点圆(首节点 18 半径高亮)+ 连线 + 右上小太阳(540,96)。**emotion_wheel**(L483-484):中心圆+轮辐线+外圈小圆(每情绪一色)。
- **组件样式**:toolbar(logo+route-tabs+mood-pill+设置 icon,L26-70)/`.bubble` 头部旁气泡(L117-121,点开 `.chat` 抽屉 L128-142)/`.mood-overlay` 右上 6 表情+conic 计时环(L232-248)/`.crisis-banner` 暖橙横幅+`.audit-tag`(L250-256)/`.rail` 磁吸右缘+`.timeline`(L148-180)/`.proto` 帧控制台(L262-276,**建议保留**给后续演示验帧)。
- Live2D 区(L107-114 `.l2d-stage` 叠黑板右下)与语音 mic 仅留位,步骤 7/8 接。

## 6. 遗留小事(不阻塞,顺手可做)

- RAG 冷启动预热(启动时后台 warm-up 一次,可选优化)。
- mood pill 文案静态「此刻·平静」→ 步骤6 记忆接真值。
- station(心灵补给站)入口 UI 留位,步骤9 接 REST 后补交互。
- 前端 `logger.ts` 尚无统一接入点约定(模块内直接 import 即可,暂无需改)。
