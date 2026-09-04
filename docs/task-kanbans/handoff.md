# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `architecture/*`、`CLAUDE.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| 步骤9 station/admin · 后续 UI | `design-taste-frontend`(定稿前);动效 `emil-design-eng` |
| E2E 验证(真实前后端) | `webapp-testing`(playwright);截图**视觉复核**派多模态子 agent(见 §4 末条) |
| 改架构/大方向前 | `grilling`;决策定案落 `docs/adr/` |
| 写/改交付文档、清扫避用词 | `doc-standards`(十判据) |
| 默认生效 | `i-have-adhd`(输出友好) |

## 2. 环境现场(命令与判据单源=CLAUDE.md §4/§8,此处只记坑)

- **模型缓存单源=`backend/.env.example` 模型缓存节**(HF_HOME + MODELSCOPE_CACHE,本地 .env 已配):**必须指向 ASCII 盘符路径**——默认 `C:\Users\<中文用户名>\.cache\` 会让 sentencepiece 直接 NOT_FOUND(SenseVoice 实测)。本机:HF_HOME=D:\MetaverseStudy\hf_cache(bge 系列),MODELSCOPE_CACHE=D:\MetaverseStudy\modelscope_cache(SenseVoice ~900MB 已就位);CosyVoice2-0.5B 权重 5.3GB 在 `models/voices/CosyVoice/pretrained_models/`。dotenv 进程级生效且不覆盖已存在的系统变量。
- **Chroma** 持久化 `backend/.rag_store/`(15 条种子已灌);**RAG 冷启动实测 ~1-2min** 超 answer 60s 预算触发设计内降级——演示/验收前先打一条知识问题预热(遗留优化 §6)。
- **服务现场**:5173 vite 常驻;8000 后端在跑(步骤8 代码);**TTS sidecar 不留守**(系统内存紧张会被 OOM 杀)——`app/voice/tts.py` 按需懒拉起,首次 TTS 等模型 ~40s 就绪;手动起=`models/voices/CosyVoice/.venv/Scripts/python.exe backend/app/voice/tts_sidecar.py`(先清 9880 旧监听,见 §4 孤儿进程条)。**开工先探活**两端;后端不用 --reload;脚本直连用 `127.0.0.1`(uvicorn 只绑 IPv4,localhost 解析 ::1 会拒)。
- **WS 测试脚本坑**:`websockets` 库默认 keepalive ping 20s,RAG 冷加载会断——传 `ping_interval=None`;前端浏览器原生 WebSocket 不受影响。
- **Windows 坑**:仓库文本 CRLF——前端读 `architecture/*.md` 正则要 `\r?\n`+`s` 标志;git-bash 管道下 Python print 中文 GBK 乱码(仅显示,断言在脚本内做);TestClient 的 WS 测试是同步函数不能 `await`;reload 断 WS 时 Proactor ERROR 是已知噪音。

## 3. 已定案的架构裁定(勿重开,详见 git log 与各模块 docstring)

- done 帧**带** session_id;user_input/mood_select 的 session_id **可空**;重连带原 id → 网关认领(`reconnect_adopted`)+热层 snapshot 恢复。
- **轮次回答=同回合连续不发 first_frame**;等待期抢占落 answer/危机;分析中抢占=cancel+弃 state+emitter dead 蒸发→entry 承接。
- 模糊输入规则速判按 collect 兜底(first_frame ≤300ms);LLM 异步精化 emotion_label 未接(非必须)。
- 种子语料 15 条人审定稿;全量语料=队友 `dataset/` **排后单做**(看板「排后」项,走 data-contract §4)。
- StageMapData `from_` 序列化必须 `model_dump_json(by_alias=True)`。
- 增量/精稿 draw 前端不可实时区分→「轮答提交→analysis→draw→final」纯前端推断;emotionLabel 写序=first_frame→draw(未手点锁)→mood_select(手点锁,first_frame 解锁)。
- **语音裁定(步骤8)**:ASR=SenseVoice 本地(funasr[knf]);TTS=CosyVoice2-0.5B 经 sidecar HTTP 进程隔离(两套 venv torch 不兼容);音频 IO 全 ffmpeg+stdlib 免疫版本漂移;fillers 预生成同音色。

## 4. 工程约定与陷阱(ruff/mypy/框架)

### 后端

- **ruff 0.16 默认规则集已扩**(I/RUF/TRY/BLE):`--fix` 可修 import/`__all__`/空 spread 等;pydantic ValueError→`# noqa: TRY004`;降级盲捕→`# noqa: BLE001`;本地日聚合→`# noqa: DTZ005` 单点 helper。
- `from __future__ import annotations` 防 TYPE_CHECKING 前向引用炸;LangGraph 节点签名 `(state, config)`,emitter 走 config;图模块级编译一次。
- pytest-asyncio `asyncio_mode=auto`;loguru 内存 sink record:`extra` 是 dict、`level` 用 `.name`。
- 懒加载分层:chroma/sentence-transformers/langgraph/语音模型全部函数内 import;mypy overrides:funasr/torchaudio/cosyvoice/jieba/rank_bm25 无 stub 已配。
- **记忆(步骤6)**:单例 `get_memory()`;conftest autouse 假记忆+静音 TTS/fillers(新用例默认不触 Redis/sidecar,真链路 test_memory 需 6379);test_voice 的真客户端用例要在**模块导入期捕获原函数**再恢复(fixture 里现取会拿到 conftest 桩)。
- **语音(步骤8)**:tts 客户端端口/超时调用时读 config(import 期绑定会让 monkeypatch 失效);sidecar 对 `cosyvoice.utils.file_utils.load_wav` 打补丁且须在 frontend 导入**前**(from-import 绑定,双保险重绑 frontend 模块属性);该 venv 曾被 pip 装 matcha-tts 连锁顶到 torch 2.14——别再往里 pip 装东西,要装先想连锁。
- **TaskStop 杀不透 python 子进程**(杀的是 bash 壳):sidecar/uvicorn 重启前先 `netstat -ano | grep 9880`+`taskkill //F //PID`,SO_REUSEADDR 会多实例叠监听;系统内存紧张会 OOM 杀后台任务(勿依赖长留守)。

### 前端

- **运行时创建的 SVG 吃不到 scoped CSS**——黑板动画类在 `main.css` 全局;组件测试 DOM 断言 `await nextTick()`。
- **pixi-live2d-display 必须走 `/cubism4` 子路径**(主入口顶层硬要求 Cubism2 runtime 必炸);cubism core 走 index.html defer,`window.Live2DCubismCore` 轮询等待。
- 黑板排版单源:`board/templates.ts`(zones)/`renderer.ts`(wrapChalk 词边界折行≤3行,单测钉住)。
- Pinia store 跨「setup 构造的控制器类↔组件」同实例直接赋值;E2E 观察存疑先页内轮询打点(工具往返时延会造假象)。
- **截图视觉复核**:子 agent `model: "sonnet"`(环境映射 glm-5.3-flash[1M] 多模态)Read 图逐项判基准——文本判据外的溢出/遮挡它抓得准(步骤5/7 均立功)。

## 5. 现状(§1 未完成项=步骤9 工具)

- **前端(步骤5/7/8 落)**:`board/`·`state/round.ts`·`mood/`·`chat/`·`audio/queue.ts`(wav 真播放)·`l2d/live2d.ts`(真立绘+SVG 兜底)·mic 录音;设计变量单源 `main.css`。测试 34。
- **后端(步骤1-6/8 落)**:契约/网关/三路路由/RAG/采集/记忆三层/语音四件(`voice/asr·tts·tts_sidecar·fillers`);fillers 已产 2 条(`data/fillers/`,gitignored);`station:input` 回合末写入,`memory.load_station_input` 读口已备待步骤9 消费。测试 87(voice 含真模型转写)。
- **v7 mockup 仍有用行段**:工具面板 tool-panel L57-69/L328(心灵练习/留言墙/补给站入口——步骤9 接);模型配置 cfg L234-242/L348。

## 6. 遗留小事(不阻塞,顺手可做)

- **RAG 冷启动预热**:启动后台 warm-up 一次(涉后端启动行为,做前打招呼)。
- 口型=播放态点头,音频幅值真口型二期;audio_chunk=整段一帧,流式分块二期。
- mood pill 已显回合 emotionLabel;持久 profile 视图随 admin(步骤9)。
- Live2D 真口型 model.speak 与 AudioQueue 双通道播放冲突,接前先设计单一播放源。
