# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `architecture/*`、`CLAUDE.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| 步骤7 Live2D 动效 / 步骤8 语音 | `emil-design-eng` · `animate`;UI 定稿前 `design-taste-frontend` |
| E2E 验证(真实前后端) | `webapp-testing`(playwright);截图**视觉复核**派多模态子 agent(见 §4 末条) |
| 改架构/大方向前 | `grilling`;决策定案落 `docs/adr/` |
| 写/改交付文档、清扫避用词 | `doc-standards`(十判据) |
| 默认生效 | `i-have-adhd`(输出友好) |

## 2. 环境现场(命令与判据单源=CLAUDE.md §4/§8,此处只记坑)

- **模型缓存**:`HF_HOME=D:\MetaverseStudy\hf_cache`(bge-small-zh-v1.5 与 bge-reranker-v2-m3 已就位);Chroma 持久化在 `backend/.rag_store/`(已灌 15 条种子语料)。
- **5173 常驻 vite** 曾与 8000 后端双双被杀过——**开工先探活**两端;后端不用 --reload。当前 8000 由冒烟 agent 用 `Start-Process` 脱离任务系统常驻(PID 39728,`taskkill //F //PID 39728` 可停;只绑 127.0.0.1,`localhost` 解析成 ::1 会拒——浏览器走 IPv4 幸存,脚本直连用 `127.0.0.1`)。
- **Redis 6379 本机常驻**(步骤6 起生产用 db0,键 `hrp:v1:*`;测试用 db15 收尾清键)。冷层 SQLite=`backend/data/profile.db`(gitignored)。
- **WS 测试脚本坑**:`websockets` 库默认 keepalive ping 20s,RAG 冷加载 ~63s 会把客户端断掉——脚本传 `ping_interval=None`;前端浏览器原生 WebSocket 不受影响。
- **RAG 冷启动实测 ~2min**(远超早估 30s):超 answer 60s 预算触发设计内 timeout 降级话术;模型热后秒级。演示/验收前先打一条知识问题预热(遗留优化见 §6)。
- **Windows 坑**:仓库文本 CRLF——前端读 `architecture/*.md` 的正则要 `\r?\n` 且跨行匹配加 `s` 标志;git-bash 管道下 Python print 中文 GBK 乱码(仅显示);TestClient 的 WS 测试是同步函数不能 `await`,等后端异步任务用 `time.sleep`;reload 断 WS 时 asyncio ProactorBasePipeTransport ERROR 是 Windows 已知噪音,非业务错。
- `e2e-shots/`(E2E 截图)已 gitignore,可随手清。

## 3. 已定案的架构裁定(勿重开,详见 git log 与各模块 docstring)

- done 帧**带** session_id(ws-contract §1 赢家,§3.5 示例已补);user_input/mood_select 的 session_id **可空**。
- **轮次回答=同回合连续,不发 first_frame**(契约 §6.2);「等待期抢占」落到 answer/危机类输入;**分析中抢占**=cancel 任务+弃 state+emitter dead(未发帧蒸发)→ entry 承接安抚语。
- 模糊输入 `classify_rules` 规则速判按 collect 兜底(first_frame ≤300ms);LLM 异步精化 emotion_label 未接(spec §4 L4 允许,非必须)。
- 种子语料 15 条**人审定稿**;全量语料=队友 `dataset/`(已到位,未跟踪不入库)——**排后单做**(看板「排后」项),走 `docs/data-contract.md` §4 回验替换。
- StageMapData 字段 `from_`(Python 关键字),序列化必须 `model_dump_json(by_alias=True)`。
- **增量 draw 与精稿 draw 前端无法实时区分**(契约无专用信号)→ 已按 frontend-plan §3「纯前端推断」落地:轮次回答提交(collecting/final)→ analysis(显示收尾中)→ draw 到达 → final。emotionLabel 写序落地形态:first_frame → draw(未手点锁时覆盖)→ mood_select(手点锁回合,first_frame 解锁),见 `state/round.ts`。

## 4. 工程约定与陷阱(ruff/mypy/框架)

### 后端

- **ruff 0.16 默认规则集已扩**(I/RUF/TRY/BLE):import/`__all__` 排序 `--fix`;pydantic 校验器 ValueError → `# noqa: TRY004`;降级盲捕 → `# noqa: BLE001`。
- **TYPE_CHECKING 前向引用+运行时注解求值 NameError** → 模块顶部 `from __future__ import annotations`。
- **LangGraph**:节点签名 `(state, config)`,emitter 从 `config["configurable"]["emitter"]` 取;条件边收 `where_next(cs)` 纯函数;图模块级编译一次。
- pytest-asyncio `asyncio_mode=auto`;loguru 内存 sink 的 record:`extra` 是 dict、`level` 用 `.name`。
- **懒加载分层**:chroma/sentence-transformers/langgraph 全部函数内 import;`app.rag`、`app.agents` 入口模块保持轻 import。
- mypy:jieba/rank_bm25 无 stub → pyproject overrides;openai TypedDict 联合 `cast(ChatCompletionMessageParam, ...)`。
- 模块环:`app.collect.questions ↔ app.agents.state` 单向可忍;新增 import 前想清方向。
- **记忆模块(步骤6)**:单例 `get_memory()`;网关测试 conftest autouse 假记忆(新用例默认不触 Redis);真链路 `tests/test_memory.py` 需 6379 在线。DTZ005 按本地日聚合是裁定(noqa 单点 `_now_local`)。mood_daily 主键=(date, source)。

### 前端(步骤5 新积)

- **运行时创建的 SVG 元素吃不到 scoped CSS**——黑板粉笔动画类(`.board-primitive`/`.dash`/`#chalkCursor`)在 `main.css` 全局;组件模板内元素才用 scoped。
- **组件测试 DOM 断言必须 `await nextTick()`**(reactive 变更→DOM 异步;store 断言不需)。
- **oxlint `no-useless-spread` 两类炸点**:for-of 里 `[...collection]`(HTMLCollection 防活集合变异的真 spread 也判多余——改 `while firstElementChild`);条件展开 `...(cond ? {} : {...})`(改显式赋值)。lint 带 --fix 会改文件,故检查顺序=lint→type-check→test,并发改文件后要重跑。
- 黑板排版单源:`board/templates.ts`(zones 坐标)/`renderer.ts`(粉笔原语+`wrapChalk` 词边界折行≤3行,单测钉住不溢出)。
- **pixi-live2d-display 必须走 `'pixi-live2d-display/cubism4'` 子路径**:主入口=Cubism2+4 全量构建,模块顶层硬要求 `window.Live2D`(Cubism 2 runtime),缺即抛——model3.json 必现炸。cubism core 走 index.html defer 脚本,`window.Live2DCubismCore` 轮询等待。
- Pinia store 跨「setup 构造的控制器类 ↔ 组件」共享同一实例,直接赋值即响应;E2E 观察与事实不符时先用页内轮询打点(工具往返时延可造成 10s 窗口类假象)。
- **截图视觉复核**:派子 agent 指定 `model: "sonnet"`(环境已映射 glm-5.3-flash[1M] 多模态)Read 本地图逐项判基准;文本判据之外的溢出/遮挡问题它抓得准(步骤5 曾据此修三处)。

## 5. 前端现状(步骤5 已落地,`089165e`)

模块:`board/`(diff·registry·templates·renderer·BoardCanvas)· `state/round.ts`(Pinia 五态机)· `mood/`(selector+浮层)· `chat/`(messages 单例响应式+ChatPanel 气泡/抽屉)· `audio/queue.ts`(骨架,真音频帧步骤8 接)· `l2d/live2d.ts`(步骤7 `fdeaa46`:真立绘 HARU,失败落 `placeholder.ts` SVG 兜底;表情 watch emotionLabel、口型 setSpeaking)· ws/client 重连链已修(`1db9e72`,步骤2 遗留单发断裂)。App=v7 舞台布局+WS 帧接线(frontend-plan §5.3);设计变量单源 `main.css` :root(照 mockup v7)。

后端步骤6(`c82a343`):`app/memory/` 三层+网关四接线(详见 commit);`station:input` 已在回合末写入,步骤9 补给站直接 `load_station_input` 消费。

**v7 mockup(`architecture/preview/l1-ui-mockup-v7.html`,963 行,勿整读)仍有用行段**——步骤7/8 接:
- Live2D 区 L107-114(`.l2d-stage` 叠黑板右下,chat-open 左移避让;`#l2dCanvas` 就绪渐显)+ L402-430 初始化参考(pixi Application+Live2DModel.from+锚点缩放+hit);表情映射 `L2D_EXPR` L387。
- 语音 mic L321(输入条内,已留位 disabled);audio_chunk→队列已接(`App.vue` track)。
- 工具面板 tool-panel L57-69/L328(心灵练习/留言墙入口,二期);模型配置 cfg L234-242/L348(设置入口待接)。
- **beck 坐标勘误(旧蒸馏误标)**:mockup 实况 thought@(320,320,140×27)、core_belief@(320,406,158×24)——旧 handoff 曾对调成「情境/中间信念」;intermediate_belief mockup 未画,按 behavior(560,318,62×26)镜像补 (88,318,62×26)。**坐标单源现已=board/templates.ts,以代码为准。**

## 6. 遗留小事(不阻塞,顺手可做)

- **RAG 冷启动预热**:启动时后台 warm-up 一次(实测 2min 冷启会吃掉首问 60s 预算)——涉后端启动行为,做前与人打招呼。
- mood pill 已显**回合内** emotionLabel;步骤6 记忆接持久 profile(gateway `_on_mood_select` 有 TODO 标记)。
- station(心灵补给站)入口 UI 留位,步骤9 接 REST。
- 前端 `logger.ts` 模块内直接 import 即可,暂无需改。
