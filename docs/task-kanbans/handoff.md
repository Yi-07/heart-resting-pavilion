# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `architecture/*`、`CLAUDE.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| 业务测试执行(B2;脚本见 §2 e2e 现场) | 常规编码+`webapp-testing`;测试派子 agent 黑盒跑(见 kanban §0) |
| UI 定稿前 | `design-taste-frontend`;动效 `emil-design-eng` |
| 改架构/大方向前 | `mattpocock-skills:grilling`;决策定案落 `docs/adr/` |
| 写/改交付文档、清扫避用词 | `doc-standards`(十判据) |
| code review(C1) | 按 kanban C1 自定义两轴子 agent 方案(三个现成 review skill 均 diff 型,不适配全库) |
| 默认生效 | `i-have-adhd`(输出友好;会话技能清单未收录时以此清单为准) |

## 2. 环境现场(命令与判据单源=CLAUDE.md §4/§8,此处只记坑)

- **服务入口已换短命令**:`cd backend && uv run hrp`(=pyproject scripts→`app/cli.py`,默认 127.0.0.1:8000)。lifespan 自动完成三件事:sidecar 拉起(版本握手,SIDECAR_VERSION=2)· RAG 预热(日志 `rag_warm_ready`,~30s)· 事件循环看门狗——**不再需要手动拉 sidecar 或"演示前先打一条知识问题预热"**。`--reload` 开发配 `TTS_SIDECAR_KILL_ON_EXIT=0`(免得热载陪杀模型)。
- **CosyVoice venv 已重建为 GPU torch**(torch 2.3.1+cu121,本机 RTX 4050 6GB):蓝本=`prototypes/tts-latency/freeze_gpu_blueprint.txt`(回滚锚=同目录 freeze_sidecar_rollback.txt);坑=setuptools 必须 <81(pyworld 依赖 pkg_resources)、cosyvoice.dataset.processor 连带 pyarrow/pyworld。**仍别随手往该 venv pip 装东西**(历史版本地狱,重装成本高)。
- **改 sidecar 代码必须重启 sidecar**:backend 版本握手会拒绝旧进程(日志 `tts_sidecar_version_mismatch` ERROR + TTS 降级),自己拉起的会自动杀掉重拉,外部手动拉起的只报错。
- **RAG 模型本地化**:bge-m3 `backend/models/bge-m3/`(2.2G)+ reranker(2.1G),**gitignore 不入库;新克隆需重建**(下载脚本待补=看板 D1,下载命令已内联看板;本机走 hf-mirror `curl -sL`,huggingface_hub Xet 分片在本机报 FileMetadataError,底层 HTTP 通)。缺件不炸:answer 走降级直答(日志 `rag_warm_failed`/`degraded rag_failed`)。
- **Chroma**=`backend/.rag_store/`:`hrp_kb_knowledge`(15 条科普库/answer 用)· `hrp_kb_case`(14944 条案例库/collect·station 用)。重建=`uv run python -m app.rag.ingest --reset`;**全量编码纯 CPU 易被 OOM 杀,限线程 `OMP_NUM_THREADS=8` 可稳**(本机 15.8G 内存)。检索已异步化(`rag.retrieve_async`,未就绪 2s 超时降级),不阻塞事件循环。
- **内存压力**:系统内存不足时后端/后台进程会被系统结束(非代码问题,重启即恢复)——9880/8000 端口被占时先 `netstat -ano | grep 端口`+`taskkill //F //PID`。
- **E2E 脚本现场**:已迁 `backend/tests/e2e/`(e2e_lib + 两轮共 10 脚本,ruff/mypy 干净);跑法=e2e_lib 头注(`uv run python tests/e2e/e2e2_a_gate_concept.py`,Windows 直接 python);e2e_b_asr 需命令行传真实语音 wav(样本不入库);日志路径=backend/tests/e2e 相对 backend/logs。`prototypes/tts-latency/` 仅剩 freeze 两文件(venv 重建锚,gitignore 不入库,**随 D1 迁 backend/scripts/ 入库**)。
- **WS 测试脚本**:`websockets` 库建议传 `ping_interval=None`(长任务/冷启下 20s 默认 keepalive 会误断;e2e_lib 已带该参,自写脚本记得加);前端浏览器原生 WS 不受影响。
- **Windows 坑**:仓库文本 CRLF(前端读 `architecture/*.md` 正则要 `\r?\n`+`s`);git-bash 管道下 Python print 中文 GBK 乱码(仅显示,断言在脚本内做);TestClient 的 WS 测试是同步函数不能 `await`。
- **Live2D 素材**:`frontend/public/vendor/` 整体 gitignore(授权禁再分发);新克隆跑 `npm run l2d:fetch` 重建,缺失自动回退 CDN→SVG 手绘兜底。目录单源=`src/l2d/models.ts`。
- **CORS**:白名单=`config.CORS_ALLOW_ORIGINS`(默认 5173 两址)——队友内测若跨机访问需扩。

## 3. 已定案的架构裁定(勿重开;详见 ADR-002/003 与各模块 docstring)

- **ADR-001 已落地(随 ADR-005 批)**:热层存 recent_turns(≤20 轮原话,30min TTL)+重连重建 state.turns;formulation/round_index 不持久(黑板重画=已知局限,二期)。
- **ADR-005(对话回放与小结卡片)**:契约新增 `replay` 帧(S→C 共 9 种;重连认领后、本回合帧前主动推一次;bubbles=30min 内原话回放,digest=隔天仅温层摘要;热温均无不发)。前端 localStorage 存 session_id(`hrp.session`,刷新后仍认领+回放);呈现=幕布折叠(bubbles)/小结卡+隐私横幅(digest);**治理联动=clear_memory 前端先清 localStorage**。assistant 回复(问句/陪聊/总结)入热层轮次——graph 轮答消费点已改按 role 倒查(不能再取 turns[-1])。UI 形态单源=prototypes/replay-ui(定稿:30min 内幕布/隔天混流)。聊天窗打开立绘左移让位(chat-open,v7 同款)。

- **ADR-004(语音输入两步式)**:录音 → REST `POST /asr/transcribe`(base64 webm/opus → {text};空串=没听到 200,不可用 503,字节护栏 1MB=413)→ 前端追加式回填文本框 → 用户确认按文本发送;**输入单源文本**——`user_input` 无 mode/audio 字段,网关无 audio 分支,e2e_b_asr 已删;危机判定吃用户确认文本,ASR 质量不直入安全链路;转写日志 asr_transcribed/asr_empty 归属 REST 端点(事件名不变)。

- done 帧**带** session_id;user_input/mood_select 的 session_id **可空**;重连带原 id → 网关认领+热层 snapshot 恢复(仅 history_summary;turns 重建属 ADR-001 待办)。
- **轮次回答=同回合连续不发 first_frame**;分析中抢占=cancel+旧 emitter 标 dead(未发帧蒸发)。
- **ADR-002(TTS 分句流式+进程统一)**:sidecar `POST /tts_stream` NDJSON 逐句出料(消费完整生成器——旧版 next() 截断 bug 已修);网关逐句直发,每句一个 audio_chunk(seq 单调);**总结语音 done 之后异步流出,仅抢占(trace 变)蒸发**——60s 回合超时不再罩 TTS;sidecar `/health` 带 version 握手,旧进程拒绝静默复用;协议常量单源=`app/voice/sidecar_protocol.py`(backend 与 CosyVoice venv 共享的零依赖模块)。
- **ADR-003(采集态门控+防阻塞)**:采集态中 answer 命中不弃态——纯概念问句/连续追问满 2/显式要求回答→短答支线(`suspended` 挂起,无 first_frame 黑板保活,下一输入自动恢复);求助句(怎么办/建议类)留 collect 由提取/陪聊轻回应。RAG=lifespan 预热+`retrieve_async`(未就绪 2s 降级);事件循环看门狗 lag>2s WARN;前端 WS 断线横幅。
- 模糊输入规则速判按 collect 兜底(first_frame ≤300ms);LLM 异步精化 emotion_label 未接(非必须)。
- StageMapData `from_` 序列化必须 `model_dump_json(by_alias=True)`。
- 增量/精稿 draw 前端不可实时区分→「轮答提交→analysis→draw→final」纯前端推断;emotionLabel 写序=first_frame→draw(未手点锁)→mood_select(手点锁,first_frame 解锁)。
- **语音裁定**:ASR=SenseVoice 本地(funasr[knf],CPU 不上 GPU);TTS=CosyVoice2-0.5B 经 sidecar HTTP 进程隔离(两套 venv torch 互不兼容);音频 IO 全 ffmpeg+stdlib;fillers 预生成同音色;**6GB 显存只给 TTS 常驻**。
- **station/admin**:方案书=独立 REST(REST 基址由 `VITE_WS_URL` 换算);危机回合不产素材;`clear_memory` 治理不降级(失败 503,与记忆层默认吞异常相反,有意例外);config 端点 api_key 用 `HRP_CONFIG_AES_KEY` 加密落库,响应零密钥回显。

## 4. 工程约定与陷阱(ruff/mypy/框架)

### 后端

- ruff 0.16 默认规则集已扩:pydantic ValueError→`# noqa: TRY004`;降级盲捕→`# noqa: BLE001`;本地日聚合→`# noqa: DTZ005`。
- `from __future__ import annotations` 防 TYPE_CHECKING 前向引用炸;LangGraph 节点签名 `(state, config)`,emitter 走 config;图模块级编译一次。
- pytest-asyncio `asyncio_mode=auto`;loguru 内存 sink record:`extra` 是 dict、`level` 用 `.name`。
- **conftest 桩矩阵(新用例默认零真依赖)**:假记忆+`synthesize_stream` 空流+fillers None+`ensure_sidecar=False`(防 TestClient lifespan 真拉 sidecar/留 `_stopping` 污染)+`app.rag._ready` 置位(防 2s 等待)——真链路用例(test_voice/test_memory/test_retrieve)自行还原,模式=**模块导入期捕获原函数**,fixture 里现取会拿到桩。历史教训:语音降级用例若走真拉起路径,每轮全量测试遗留一个 sidecar 僵尸进程(曾积 12 个压崩 torch 模型加载)。
- mypy overrides:funasr/torchaudio/cosyvoice/jieba/rank_bm25 无 stub + `sidecar_protocol`(脚本目录顶层导入,无包上下文)。
- **RAG**:`_QUERY_PREFIX=""`(bge-m3 无检索前缀);`_UPSERT_BATCH=1000`(分批安全值,chroma 硬上限 ~5461);换 embedding 模型=维度变化**必 `ingest --reset`**;`test_memory` 真链路需本机 Redis 6379。语料源=`backend/data/rag_corpus.jsonl`(14944)+`rag_knowledge_corpus.jsonl`(15)。
- **TaskStop 结束不了 python 子进程**(杀的是 bash 壳):sidecar/uvicorn 重启前先按端口找 PID `taskkill //F`。

### 前端

- 运行时创建的 SVG 吃不到 scoped CSS——黑板动画类在 `main.css` 全局;组件测试 DOM 断言 `await nextTick()`。
- pixi-live2d-display 必须走 `/cubism4` 子路径;**切换=renderer 单例换模型**(pixi Application.destroy 会杀 WebGL context,同 canvas 重建必炸 shader 编译)。
- Pinia store 跨「setup 构造的控制器类↔组件」同实例直接赋值;E2E 观察存疑先页内轮询打点(工具往返时延会造成误判)。
- tsconfig `noUncheckedIndexedAccess` 已开——数组下标读取退化 `| undefined`,需收窄。
- 截图视觉复核:子 agent Read 图逐项判基准(文本判据外的溢出/遮挡它抓得准)。

## 5. 现状

- 主线步骤 1-9 全落(见 kanban §1);**ADR-002 批次已落地**:TTS 分句流式(修长文本丢 3/4 音频的截断 bug)+总结语音出窗+`uv run hrp` 统一进程管理+版本握手;**ADR-003 批次已落地**:采集态门控(修采集中被 answer 抢占丢黑板)+RAG 预热(修 ~18s 冷启动冻结→WS 静默断连)+看门狗+断线横幅。两批均 E2E 5 用例实况 PASS(脚本在 prototypes/tts-latency/)。
- **A1 已完成**:危机词表扩充(核心 9→23/软 5→10,"吃安眠药"归软档防医疗正用误伤)+词表逐条钉测试,三件套全绿(pytest 123)。
- 测试:后端 119(pytest)+前端 69+type-check/lint 干净;后端三件套与前端检查全绿。
- **prototypes/=临时区**(gitignore 不入库):本轮挂 TTS 延迟原型(FINDINGS.md)+两轮 E2E 脚本,归档处置=看板 A2;勿在交付文档加指针。
- 第一版交付冲刺(遗留问题→业务测试→code review→交付文档)=看板 §2,当前停在 A 段待开工。

## 6. 二期语音项(不阻塞,单源=kanban §3 待办池)

- 口型=播放态点头,音频幅值真口型二期;真口型 model.speak 与 AudioQueue 双通道播放冲突,接前先设计单一播放源。
- answer 链路无语音(契约设计);是否补=产品决策。
