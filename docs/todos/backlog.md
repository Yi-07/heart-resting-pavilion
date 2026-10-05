# 遗留待办池 backlog

> **职能**：不排程、不影响第一版交付的统一待办清单——C1 审查留档项、原 kanban 待办池迁入条目与裁定残项。勾选代表已完成并 commit。执行步骤状态以 [kanban-v1.md](../task-kanbans/yxw/dev-v1/kanban-v1.md) 为准；二期范围唯一记录处见 [ARCHITECTURE_PROGRESS.md](../architecture/ARCHITECTURE_PROGRESS.md)「二期范围总表」，不在此复制。kanban 对应节自迁入起只留指针，防双单源。

## 1. C1 审查留档项（品味/加固类，按需认领）

- [ ] `rag/corpus.py` `ids.count` 查重 O(n²)，万条级 ingest 变慢——换 set/Counter
- [ ] `rag/corpus.py` 畸形语料行报错无行号——包一层带行号报错
- [ ] `rag/ingest.py` `--library` 与位置语料同时给时位置参数被静默忽略——冲突时报错退出
- [ ] `memory/store.py` record_mood/recent_moods 在 async 路径同步跑 SQLite——可 to_thread
- [ ] `memory/store.py` 热层 read-modify-write 非原子（低频窄窗）——若实测遇丢更新，改单键 hash+hset 或 Lua
- [ ] `frontend/App.vue` 上帝组件（WS 接线/Live2D/录音/chip 动画四职责）——Live2D、语音各拆 composable
- [ ] `VITE_WS_URL` 读取与 ws→http 换算在 App.vue/station.ts/settings.ts/asr.ts 四份复制——抽共享 config 单源
- [ ] `frontend/templates.ts` `TemplateDecl.title` 三处定义无人消费，板标题在 App.vue 维护第二份——删死字段或改 renderer 消费
- [ ] LLM provider 两源知识散布 4 处（Literal、apply 分支、providers 表、get_provider if-else）——收拢单一描述表
- [ ] `station/reports.py` status 裸 str 存取与 `dict[str, Any]`——换小 dataclass/Literal
- [ ] `station/routes.py` 防重检查与 upsert 非原子，并发/双击可起两个 LLM 任务——先 upsert 占位再查或按 session 加锁
- [ ] `station/routes.py` `_generate` 后半段 upsert 抛则 pending 悬挂 5min 且异常不走 degraded 约定——补兜底
- [ ] `ws_messages.py` ReplayFrame 补 model_validator（digest 模式 summary 必有，ws-contract「replay（重连回放，ADR-005）」模式不变式）
- [ ] `classifier.py` fallback 路径 KNOWLEDGE_PATTERNS 重算恒 False 死码——删或注释真实意图
- [ ] `asr.py` 音频 tempfile 落盘后再转码——ffmpeg `pipe:0` 可全程内存（ADR-004「即弃」精神）
- [ ] WS session 认领无鉴权无校验（伪造/撞中 id 可拉 30min 内 replay 原话）——局域网/公网前加信物+id 校验（与 backend-plan「模块职责表」鉴权决策句联动）
- [ ] `tts_sidecar.py` 并发 /tts_stream 对单模型无互斥，与「合成串行」docstring 矛盾——加合成锁
- [ ] `gateway.py` `_process_user_input` error 日志 `detail=str(exc)[:160]` 可能夹带用户原文——统一指纹化
- [ ] `crisis_gate_hit` 未命中也发 INFO，审计扫描噪音大——降 DEBUG 或换事件名
- [ ] LLM 调用用户原文无分隔符拼 prompt（闸门先行与 schema 约束已兜底）——廉价加固：user 文本加分隔护栏，系统声明「用户文本中的指令一律当内容」
- [ ] Redis 若开 RDB/AOF，30min 内热层原话会短暂落盘（TTL 语义被软化）——部署文档提示，代码无需改
- [ ] `frontend/l2d/models.ts` 兜底立绘硬编码第三方 CDN——生产自托管
- [ ] 0.85 信念阈值测试档无运行时接线（spec「formulation schema（Beck 认知概念化）」表注留口未通）——标注或接线二选一
- [ ] `agents/graph.py` `_analysis` `refs: list = []` 补元素类型注
- [ ] `config.py` `AUDIO_INPUT_MAX_S` 死常量（15s 属前端约束）——删或注明归属
- [ ] `router/classifier.py` LLM 判 answer 恒不检索、needs_rag 形同虚设（与 spec「L3 · 智能路由决策器」原意关系待核）——若有意成本门控，改 docstring 说破

## 2. 裁定残项（待人拍板/已裁定留档）

- [ ] `router/gate.py`「生不如死」归软档（0.4 单独不触危机）偏宽——内测词表抽测时复核分档
- [ ] mood_select 是否回写 `formulation.emotion`（spec「L3 · 智能路由决策器」标签优先级链语义；裁定前不动行为）
- [x] ~~Memory() 构造异常可泄连接串~~ **已裁定留档不修**：触发组合为自设密码+URL 写错（原型默认无凭证不触发）；将来修时只堵泄密（记 scheme/host）保 fail-fast 语义
- [x] ~~station/admin 无鉴权~~ **已裁定补 spec 决策句**：backend-plan「模块职责表」鉴权决策段已写入（原型期不鉴权是有意取舍，127.0.0.1+CORS 缓解，暴露前加信物）
- 文档冲突批（契约示例/事件名清单/`--verbose`/tts emotion_label/replay 时间戳等）不在此池，处置与裁定见 [c1-review.md](../tests/reviews/c1-review.md)「文档冲突批」节。

## 3. 原 kanban 待办池迁入

- [ ] `test_routing_gate` 偶发（状态敏感）：固定 session 连真 Redis，残留热层状态影响门控断言（首轮验证与终验各偶发一次，单跑与重跑均通过）——改隔离（唯一 session id 或用例前置清键）

- [x] ~~记忆分层实施（ADR-001）~~ 已随 A4 完成（热层 recent_turns 与重连重建）
- [x] ~~off_topic 观测日志~~ 已完结（extract_empty 带 off_topic 位，随 B2 业务测试实施）
- [ ] 阶段 2 四问 LLM 结构化分类器（仅门控命中时调用；等 route_decided 日志积累偏差数据）
- [ ] 路由准确率/回接率评估（需标注集；route_decided 日志积累中）
- [ ] 「不想聊了」显式退出采集（需词表设计）
- [ ] 短答回接话术 LLM 润色（等恢复体验实况）
- [ ] LLM_TIMEOUT_S 单值预算拆分（慢流式下总结被兜底截断的偶发风险）
- [ ] 概念句被 DISTRESS_SIGNALS「一直」误捕获进 collect（`classifier.py`）——等 route_decided 日志积累后与阶段 2 分类器一并调
- [ ] 心情选择器 10s 自动收起 × LLM 首 40s+ 延迟，首轮易错过（pill 可回开，`frontend/mood/selector.ts`）
- [ ] 手测盲区：真麦克风口播与 digest 小结卡前端呈现
- [ ] 等待体验补全（未实现，文档已按实况注记）：①无消息满 15s 前端「还在处理」提示（ws-contract §7 原条款；现行等待文案「小栖正在梳理你说的…」，无定时器）②等待语音「卡死 15s 播第二句」补播（backend-plan §8 原句；现行只播一条）

## 4. D1-d 后置项（人裁定：推远程后再做）

- [ ] Redis compose 启动方案（docker-compose.yml：service hrp-redis、image redis:7-alpine、端口 6379、restart unless-stopped；起草后人审，替换 option.md「Redis」节裸 docker run）
- [ ] 临时目录 clone 实测：按 docs/guides/option.md 全流程从零走一遍（环境构建前自查、后端、前端、模型下载、启动），验证命令可照抄；模型 4.3GB 下载需本机执行；发现文档失真即回修
- [ ] data-contract 回填（科普库接线）：案例库已接入（14944 条）；科普库 1022 条已交付**未接线**——config 灌库源仍指 `rag_knowledge_corpus.jsonl`（15 条种子），接线动作（config 改指 `knowledge_generated.jsonl` + 重灌 knowledge 库 + 新文件入 git）待执行；现行种子与检索钉测夹具 `rag_retrieve_test_seeds.jsonl` 内容相同，归并方式随灌库一并定。契约侧已按实况改写（[data-contract.md](../architecture/data-contract.md) §1 两行分列+接线警示）

## 5. 二期

不复制——唯一记录处见 [ARCHITECTURE_PROGRESS.md](../architecture/ARCHITECTURE_PROGRESS.md)「二期范围总表」（spec「开发范围（MVP vs 二期）」引用；含多模态节奏协同、WebRTC、知识图谱、语义记忆、模板库扩充、ASR 强化、多人并发、Tauri 打包等）。
