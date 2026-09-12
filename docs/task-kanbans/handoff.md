# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `architecture/*`、`CLAUDE.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 0. 当前停点(下一窗口从这里接)

- **已完成并 commit**:A1-A4 / B1 / **B2(本窗口)**。B2 落定=acceptance-v1 全节实况过+顺手修 7 项真发现(危机词表+3 消失族·跨字段提取·挂起填到才清·final 收尾·Finish 归档 shield·ASR 静音判空·启动提示),详见 kanban B2 行与 commit message。
- **下一窗口=C1 全库代码审查**(人已裁定新开窗口执行)。方案=kanban C1 原文(两轴+独立安全轴,5 片子 agent 并行);注意 B2 刚改过 `gate.py`/`extract.py`/`graph.py`/`gateway.py`/`main.py`/`asr.py`/`memory/store.py` 与前端 `App.vue`/`mood/selector.ts`,审查以改后代码为准。
- **C1 之后**=D1(一键就绪+README/文档大盘点)/ D2(交付批核对)。
- **环境**:Redis=Docker 容器 `hrp-redis`(6379;另有无关容器 `docker-redis-1` 勿动);后端 `cd backend && uv run hrp`;破坏性 e2e3_g 会 stop/start 该容器。
- **已知陷阱**(沿用):全量 pytest 按 deselect 三真链路文件跑;e2e 脚本串行(日志按时间窗断言);破坏性用例(g 与 `e2e3_f_replay.py --clear`)压轴;Windows GBK 下跑 e2e 脚本若见 UnicodeEncodeError,e2e_lib 已带 stdout UTF-8 兜底(仍崩就配 `PYTHONIOENCODING=utf-8`)。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| C1 代码审查 | 按 kanban C1 两轴子 agent 方案(三个现成 review skill 均 diff 型,不适配全库) |
| UI 定稿前 | `design-taste-frontend`;动效 `emil-design-eng` |
| 改架构/大方向前 | `mattpocock-skills:grilling`;决策定案落 `docs/adr/` |
| 写/改交付文档、清扫避用词 | `doc-standards`(十判据) |
| 默认生效 | `i-have-adhd` |

## 2. 环境现场(命令与判据单源=CLAUDE.md §4/§8,此处只记坑)

- **启动提示已标志化**(B2 顺手改):启动日志含 `startup_begin`/`memory_ready`(Redis ping 失败=`memory_ping_failed` WARN)/`rag_warm_begin→rag_warm_ready(耗时)`/`tts_sidecar_warm_begin→warm_ready(端口,耗时)`/`watchdog_on`/`startup_ready`;ASR 模型加载=`asr_model_begin→asr_model_ready`。判事件名 grep 这些。
- **跨字段提取已落地**(B2 核心机制改动):`extract.py` 一次调用返回多字段 dict(`{fields:{...},off_topic}`),`graph.py::_open_fields` 按问序给可填清单(信念字段永不进提取);挂起问题**填到才清**;提取日志=`extract_filled`(只记字段名+长度,不落原文)/`extract_empty`。e2e stub 契约同步(test_collect_flow/test_collect_e2e 的 `_ExtractOut` 分支)。
- **危机词表 26 核心+10 软**(B2 +3 消失族:从这个世界上消失/从这个世上消失/想从这个世界消失);e2e3_a 词表抽测 42 句 126 断言自检词表一致性,词表再改先过该脚本自检。
- **CosyVoice venv/RAG 模型/Chroma/Live2D 素材/CORS/WS ping_interval=None/Windows 坑**:同前(bge-m3/reranker 在 `backend/models/`,Chroma=`backend/.rag_store/`,Live2D 走 `npm run l2d:fetch`;详见 git log 历史 handoff 与 kanban)。
- **语音素材**:`backend/tests/voices/`(collect_test.wav 4.0s/crisis_test.wav 2.3s,gitignore);**合成静音会幻听出「嗯。」已由 asr.py 近静音门限(-50dBFS)判空拦住**——真实麦底噪场景留手测。
- **E2E 脚本现场**:`backend/tests/e2e/` = e2e_lib(WS 客户端+log_records 日志扫描+REST 辅助)+ 两轮 8 脚本 + e2e3 七脚本(e2e3_a 词表/b 复杂双用例/c 门控变体/d ASR/e station+admin/f 记忆回放[--clear 独立入口]/g Redis 宕机)。跑法=e2e_lib 头注;日志路径已修为 backend/logs(此前 parents[1] 找错目录的坑勿复发)。
- **采集回合无 done/final 语义**:AskNext/EmpathChat 分支设计上无 done;文本流末帧 final=True(B2 已补);e2e 脚本轮间用 sleep 留白(4s,防踩抢占弃态)不等 done。
- **回放幕布呈现位置=设计行为**:幕布只在对话记录面板内、主区干净(replay-ui 原型+ADR-005 明文),勿当 bug 修。
- **心情浮层**:无门控 bug;first_frame.mood_select 直接触发,10s 自动收起(selector.ts:7),show/hide 已带 debug 日志;刷新重连"未弹"=瞬态窗口观察问题。

## 3. 已定案的架构裁定(勿重开;详见 ADR-002/003/005 与各模块 docstring)

- **跨字段提取(B2 定案)**:每轮一次 LLM 调用填所有可填字段;off_topic=整段无关才判;LLMError 降级=所问字段填原文截断。单字段时代(返回 value|off_topic)已废。
- **Finish 归档 shield**:三动作(温层摘要/station:input/mood 冷层)包 `asyncio.shield`,断连取消不再吞归档;取消落 `degraded reason=finish_archival_interrupted` WARN。
- **词表分档**:危机闸门纯子串 26 核心+10 软;"吃安眠药"归软档;消失族表述入核心。否定/语境消歧仍无(二期)。
- **ADR-001/005(回放)**:热层 recent_turns ≤20 轮 30min;replay 帧 bubbles/digest 分岔看 snapshot 有无 turns;clear_memory 前端清 localStorage;幕布=对话面板内。
- **ADR-004(语音两步式)**:输入单源文本;ASR 静音门限判空返回空串(asr_empty 语义)。
- **mood_select 采集态内=静默**(只记 in_round 日志);独立到达(无 collect_state)才 ack+done。
- 其余裁定(TTS 分句流式/采集态门控/RAG 预热/station·admin/单源短命令等)同 git log 详细 message 与 ADR,此处不复制。

## 4. 工程约定与陷阱(ruff/mypy/框架)

- **后端**:ruff 0.16(noqa 惯例 TRY004/BLE001/DTZ005/S112);mypy 64 文件干净;pytest 110 passed(deselect test_voice/test_memory/test_retrieve 真链路三件)。loguru 内存 sink:`extra` 是 dict、`level` 用 `.name`;**station/admin 路由日志事件名只在 message 文本不在 extra**(e2e_lib.log_records 已兼容两种)。
- **conftest**:FakeMemory 需随 Memory 接口同步(ping 已加);app.main.get_memory 也 monkeypatch(lifespan Redis ping 用)。
- **前端**:type-check/lint 干净;scoped CSS 全局类在 main.css;`noUncheckedIndexedAccess` 收窄;运行时 SVG 吃不到 scoped CSS。
- **TaskStop 杀不掉 python 子进程**:按端口 taskkill //F;改后端代码必须重启 hrp(无 --reload 常驻)。
- **e2e 断言口径**:危机断言看 crisis_gate_hit 的 hit/severity/level(WARN=hit);软词命中=同事件 INFO;降级=memory_degraded;ASR 指纹格式 `len={n} sha1:{8hex}`;stage_map wire 字段是 `from` 非 `from_`。

## 5. 现状

- 主线 1-9 + 冲刺 A 段(A1-A4)+ B 段(B1/B2)全落;测试盘=后端 pytest 110 + e2e 脚本 16 个(含词表 42 句)+ 前端 69。
- **当前=看板 §2 C 段(C1 全库代码审查)待新窗口开工**;之后 D1/D2。
- B2 遗留(看板 §3 待办池):概念句"一直"误捕获、extract off_topic 观测日志、心情选择器 10s UX、真麦口播/digest 小结卡手测。
