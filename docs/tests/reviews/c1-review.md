# C1 全库代码审查结论与销账清单

> **职能**:C1 审查(5 片子 agent 并行,Standards/Spec/安全三轴)全部发现的落档与销账;勾选=该条已修复并 commit。修复范围由人裁定;全部处置完成后按 doc-standards 清理本档(结论归 git log)。
> **方法学**:借 mattpocock 两轴(Standards=CLAUDE.md §5/§7+Fowler 12 项基线;Spec=ADR/契约/spec 原意)+ 独立安全轴(危机判定/脱敏/密钥/注入面)。切片:voice+gateway / agents+collect / rag+memory / station+admin / frontend。
> **总盘**:64 发现 = 硬违例 8 + 裁量 43 + 待核 13;正面确认见 §6。

## 1. 硬违例(违反明文标准/红线/契约)

- [x] **H1 热层覆写丢 recent_turns** `backend/app/memory/store.py:232-250`(违反 ADR-001 决策3/ADR-005 决策1/spec §4 L7)
  - 场景:用户与系统采集对话 10 轮,期间每轮回答都追加进热层 recent_turns。第 10 轮 Finish 归档时次序为 save_round_summary(整键覆写,新 dict 不带 recent_turns)→ record_mood(再覆写)→ append_turn(此时 turns 已被清空,只追加一条 assistant 总结)。用户随后关页,5 分钟内回来 → 网关按 ADR-005 用热层重建对话 → **聊天窗只剩最后一条总结,前 10 轮全没**。首轮重连正常(B2 实测过),第二回合起回放/续话形同虚设。
  - 修向:`_push_mood_recent`/`_refresh_hot` 两处 write 载荷带上 `data.get("recent_turns", [])`(截断至 cap)。
- [x] **H2 RAG 重依赖模块顶部 import** `backend/app/rag/engine.py:23-29`(违反 CLAUDE.md §5.6 点名禁;链路 `rag/__init__.py:17` → `main.py` `_warm_rag`)
  - 场景 A:`uv run hrp` 启动,`startup_ready` 刚打出来,lifespan 预热在事件循环上执行 `from app.rag import warm` → 顶部 import 链现场加载 chromadb/sentence_transformers 数秒 → watchdog 报 lag,启动后段停摆。
  - 场景 B:预热失败(模型目录缺失等)后第一个用户问「什么是正念」→ needs_rag 分支才第一次触发这条 import → 在事件循环上加载十几秒,**期间所有连接(含正在采集的用户)的 WS 帧全部冻结**。
  - 修向:重 import 下沉 `_ensure_*` 函数内。
- [x] **H3 station 同步检索堵事件循环** `backend/app/station/planner.py:93`(违反 ADR-003 决策2「请求侧统一 retrieve_async」)
  - 场景:用户点补给站生成报告 → planner 同步调 `get_engine().retrieve()` → 若 RAG 预热没成功,这次调用在事件循环上现场加载 chroma/模型 ~18s → 整个后端假死,前端表现为所有面板点不动。
  - 修向:改 `retrieve_async`(同 `rag/__init__.py:9` 的既有约定)。
- [x] **H4 degraded 日志泄用户原文片段** `backend/app/station/routes.py:84`(planner.py:151 同模式;违反 §7 脱敏红线/ws-contract §9.4)
  - 场景:用户采集里说「我最近总想哭」,Finish 后 station 拿素材调 LLM 生成报告,校验抛 ValidationError → `reason=str(exc)[:120]` 把 pydantic 报文(含 input_value,即用户原话片段「我最近总想哭」)记进控制台+文件日志 → 用户文本落原文,红线破。
  - 修向:只记异常类型/长度/指纹。
- [x] **H5 二进制 WS 帧崩连接** `backend/app/ws_gateway/gateway.py:195`(违反 ws-contract §8.1「非法消息不崩连接」)
  - 场景:任一客户端(或前端将来的功能演化)发来一帧二进制消息 → `receive_text()` 抛 KeyError → 网关只捕 WebSocketDisconnect → 异常穿透 → 连接死、无 error 帧、无 session_close → 前端「没说断就断了」,黑板/Live2D 停在原地。
  - 修向:收包层补 except → error 帧 + session_close。
- [x] **H6 wsStatus 双向失效** `frontend/src/App.vue:34,214-229`(违反 frontend-plan §4 输入门控)
  - 场景 A:用户先开页面、后端还没起 → 首连失败 wsStatus='closed' → 客户端自动重连成功 → 但 wsStatus 不再更新 → **输入框永久禁用**,界面能看打不了字,只能刷新。
  - 场景 B:聊着聊着后端重启 → 前端 wsStatus 停在 'open' → 用户发消息 → `client.send` 抛 WSError 未捕获 → 按钮无响应且无提示。
  - 修向:onclose/onReconnected 同步 wsStatus,或改读 `client.isConnected`。
- [x] **H7 risk 软预筛只在终结调用** `backend/app/agents/graph.py:207-236,307-319`(违反 spec §4 L5「每轮预筛/命中复核」;backend-plan §3.3 只写终结复核,冲突按规则 spec 赢)
  - 场景:采集第 2 轮用户答「有时候觉得活着没意思」(软信号) → 预筛不在轮内跑,无复核 → 用户停止回复,回合悬挂 → **软信号全程无人复核**,硬闸门只兜核心词,渐进表述零响应。
  - 修向:预筛移 `_prepare` 每轮跑;若实况需每轮加 LLM 调用,修前先报成本再动。
- [x] **H8 恢复采集不复位 suspended** `backend/app/ws_gateway/gateway.py:315-355`(违反 ADR-003 决策1「suspended 复位、追问计数清零」)
  - 场景:潜伏 bug——现无代码读该 flag,无用户可见后果;但任何后续消费方(如「挂起后回开放聊天」功能)会拿到脏 flag:用户采集挂起→恢复→flag 仍 suspended=True→系统以为还挂着,行为错乱。
  - 修向:collect 恢复分支补 `suspended=False`。

## 2. 高价值裁量(建议修,人裁)

- [x] **D1 `_on_message` 无兜底异常网** `gateway.py:203-231` — 场景:用户在心情浮层上快速点选,`record_mood` 恰逢 Redis 抖动抛异常 → 穿透 `_on_message`(只有 `_process_user_input` 有收口)→ 连接死,违背「WS 错误统一走 error 帧」。修向:mood/replay/记忆路径补 try→error 帧。
- [x] **D2 sidecar ensure 双拉起竞态** `voice/tts.py:108-124` — 场景:启动后预热线程与第一条消息的合成线程同时进 `ensure_sidecar` → 双进程都起,`_spawned` 只留后写句柄 → 退出只杀一个,另一个孤儿吃 GPU/端口。修向:模块级锁。
- [x] **D3 emitter in-flight 音频串回合** `agents/emitter.py:91-95` — 场景:旧回合语音还在播,新输入抢占 → 旧 task 不持引用、发送前不复检 dead → 旧回合 audio_chunk(旧 seq)落进新回合,前端语音突断/帧序错乱。修向:持 task 引用+发送前复检 dead/trace。
- [x] **D4 mood_select 无条件 next_trace** `gateway.py:253` — 场景:采集回合中用户点一下心情 → 回合计数推进+未播完的安抚语音蒸发(契约 §4.2:回合内 mood_select 只记不回帧,采集照常)。修向:trace 递增仅限真回合。
- [x] **D5 admin 配置缺 api_key 静默清密钥** `admin/config_store.py:80-103` — 场景:运维只想改模型名,POST 不带 api_key 字段 → save() 整行覆盖,库内密钥清 NULL → 界面正常(进程内旧 key 生效)→ 某天重启 → deepseek 无 env key,LLM 全断,排查半天。修向:密钥缺省保留旧值(语义待人核)。
- [x] **D6 session_id 无约束** `station/routes.py:46,71` — 场景:异常客户端传 10KB session_id → 直接拼 Redis 键+SQLite 主键 → 键空间污染(无穿越面,SQL 全参数化)。修向:补 max_length+字符模式。
- [x] **D7 ASR 先解码后查长** `voice/routes.py:31,45-49` — 场景:坏客户端发 200MB base64 → 全量收进内存+解码完才被 1MB 上限拒 → 内存尖峰。修向:先查字段长度再解码。
- [x] **D8 l2d localStorage 裸读写** `frontend/src/l2d/models.ts:49,56` — 场景:用户开隐私模式/禁存储 → 裸 `localStorage` 调用抛 SecurityError → Live2D 装载整体失败,立绘消失(ws/client.ts 有 try/catch 降级,此处没有)。修向:对齐降级写法。
- [x] **D9 audit-tag 伪造审计展示** `frontend/src/App.vue:438` — 场景:验收人员看到界面静态标签「WARN·crisis_gate_hit·已转热线引导」→ 以为审计已落盘 → 实为写死装饰串,与后端审计零联动 → 验收误判。修向:移除或注明演示装饰。
- [x] **D10 emotion 判空三处重复** `graph.py:86-90`/`questions.py:46-55`/`sufficiency.py:20-30` — 场景:未来 emotion 结构一改(如带置信度),三处判空各改一遍漏一处 → 黑板渲染与采集推进判定打架。修向:`Formulation.is_filled(key)` 单源。
- [x] **D11 文档漂移四件** — `schema/__init__.py:3` docstring 8 种实 9;`messages.ts:13` 注引 §3.6 实 §3.7;`agents/state.py:1` docstring 14 字段实 16;backend-plan §3.2 max_rounds「默认 4」与 spec §4 L4 上限 3 不符(spec 赢)。
- [ ] **D12 待核四件(不修,先人核)** — gate.py:57「生不如死」软档 0.4 偏宽(内测抽测复核);`gateway.py:258` mood_select 不回写 formulation.emotion(spec §4 L3 优先级链语义);station/admin 无鉴权(spec 补原型期决策句);`store.py:51-54` Memory() 构造异常可泄连接串(原型默认无凭证)。

## 3. 文档冲突批(赢家已按 CLAUDE.md 冲突规则裁定,执行待点头)

- [x] 契约 §3.4 示例 mp3 → 实况 wav(实况赢;待核 format 字段消费面——已核,前端仅日志取 format 不判内容,改例无害)。同批补 final 语义注记(实况每帧 final=true,前端不依赖该位)
- [x] 契约 §9.1 `--verbose`:契约侧改实况——环境变量 `HRP_VERBOSE=1` → DEBUG(main.py setup_logger 实况)
- [x] backend-plan §2 tts 接口 `emotion_label`:方案侧删(实况 zero-shot 固定音色,链路无 emotion 传参;情感标签属接口预留,见 spec L6)
- [ ] replay「上次聊到 HH:MM」:ADR-005 §4 文案 vs 契约 §3.6 无时间字段,二选一(需裁)
- [x] station latest 404/generate 409 语义补进契约 §1
- [x] 契约 §9.3 事件名清单补全——已执行(实况事件全量入列并声明与代码同步维护);原挂账「6 个」实为十余个
- [ ] `round.ts:70-77` idle 收 text_delta 注释改「合法(mood_select 独立到达)」;`engine.py:56-59` docstring 并发措辞更新;`graph.py:255` refs 补元素类型;`config.py:131` AUDIO_INPUT_MAX_S 死常量删/注明

## 4. 留档不修(品味/低收益项)

- 已迁 **`docs/todos/backlog.md` §1** 统一管理(本档为审查快照,销账状态以后者为准);其中两条 D12 当场裁定结果见 §5 与 backlog §2。

## 5. 处置状态

- 修复范围:**批 1+批 2 已修**(H1-H8 + D1-D11,零架构变更);待五件检查(后端三件/前端两件/e2e 实况回归)与人确认后 commit。
- **D12 裁定结果**:admin 无鉴权→补 spec 决策句(backend-plan §2「鉴权决策(原型期)」段已落);Memory() 连接串→留档不修(裁定记录迁 backlog §2);余「生不如死」分档/mood emotion 语义两条迁 `docs/todos/backlog.md` §2 待裁。
- H7 修法注:新增 softscan 节点(每轮软词扫描,新增命中才 LLM 复核,`risk_reviewed_terms` 去重);`_risk` 收窄为终结增量复核;`escalate_end` 由死码变两路升级统一出口。**成本有界**:LLM 复核触发面=「新软词出现」,不逐轮递增;同回合 finish 路径零重复调用。
- H4 修法注:station 侧(planner.py 三处+routes.py 一处)全部改记 `type(exc).__name__`;memory/gateway 侧 `str(exc)[:120]` 经核不含用户原文,维持原样(gateway:377 detail 在 §4 留档)。
- H7 文档涟漪:backend-plan §3.3 流程块补 softscan 行(冲突规则:spec §4 L5 赢家,改输家对齐,已随本批报告)。
- **F3 顺手修(验证期发现,人裁定本批修)**:`append_turn` 热层过期冷启动时从温层最新摘要播种 `history_summary`(与 H1 同族:此前热层键复活只带 turns,快照走热层路径丢跨天续话上下文);e2e3_f F3 断言改新语义(turns≥1 且 summary>0)。既有 bug,基线 9月12 同挂,非本批引入。
- D5 语义注:`save()` api_key 缺省改为**保留旧值**(与 apply_llm_config「None 字段不动」对齐);显式清密钥场景现无入口,若需要需另立语义。
- **待办池迁移**(人裁定):C1 留档项(除文档冲突批)+看板 §3 待办池+二期指针统一整理进 `docs/todos/backlog.md`;本文 §4 与 kanban §3 均改指针,防双单源;「off_topic 零观测日志」核销随迁移入册。

## 6. 正面确认(审查通过面,存档备查)

- 危机闸门:词表 26 核心+10 软逐条在;severity 取 max 防软词堆叠;阈值 0.7 只核心可触;每条 user_input(含采集轮回答、短答支线)先过闸门后分类;危机判定后端单点;审计 WARN 含命中项+to_hotline、不含原文;emotion_label 隔离成立(路由分支零读取)。
- 脱敏:受审文件日志全只记 fingerprint/长度/命中词/字段名+长度;config_store AES-GCM 存储面全绿(密钥 env 注入、加密先于开库、日志只记 has_key、GET 不回显、解密失败仅 WARN)。
- 前端:危机逻辑零(热线为展示文案,判定单源后端);v-html 仅静态 SVG+markdown 先整体转义再白名单;localStorage 仅 hrp.session(ADR-005 明文+治理联动);黑板 diff 真按字段(稳定序列化逐键比对,仅 changed key 重画);无 any/无 Record 逃逸;9 消息契约钉测全过;first_frame 清黑板+seq 全局基线正确;ADR-004 两步式全链落;ADR-005 replay 分岔/小结卡/治理顺序落。
- RAG/记忆:TTL 30min/7d、turns cap 20 截断边界、热亡回退温层、warm()/2s 就绪门/to_thread、needs_rag 门控均符合 ADR;ingest 自检回验符合 data-contract。
- 语音:ADR-004 全落实(413/503/空串 200/懒加载/网关无 audio 分支);ADR-002 分句流式/版本握手/外部进程不越权/KILL_ON_EXIT 门控齐;归档 shield 正确。
