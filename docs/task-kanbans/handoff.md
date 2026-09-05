# 交接快照 handoff

> **职能**:当前编码会话向下一个会话交接「项目现状 + 推理现场」;每次接力前由收尾窗口整篇重写(描述现状,不写流水账/日期)。开工读取顺序见 kanban-v1 头注。
> **不复制原则**:架构/契约/方案/判据/命令已载于 `architecture/*`、`CLAUDE.md`、git log——本文只写「别处查不到的现场状态」并给出路径引用。无任何密钥类内容。

## 1. 建议技能(下一会话按需调用)

| 场景 | 技能 |
|---|---|
| 排后·全量语料接入(纯数据/检索回验) | 常规编码;检索结果复核可 `doc-standards` |
| 后续 UI 定稿前 | `design-taste-frontend`;动效 `emil-design-eng` |
| E2E 验证(真实前后端) | `webapp-testing`(playwright);截图**视觉复核**派多模态子agent(见 §4 末) |
| 改架构/大方向前 | `grilling`;决策定案落 `docs/adr/` |
| 写/改交付文档、清扫避用词 | `doc-standards`(十判据) |
| 默认生效 | `i-have-adhd`(输出友好) |

## 2. 环境现场(命令与判据单源=CLAUDE.md §4/§8,此处只记坑)

- **模型缓存单源=`backend/.env.example` 模型缓存节**(HF_HOME + MODELSCOPE_CACHE,本地 .env 已配):**必须指向 ASCII 盘符路径**——默认 `C:\Users\<中文用户名>\.cache\` 会让 sentencepiece 直接 NOT_FOUND(SenseVoice 实测)。本机:HF_HOME=D:\MetaverseStudy\hf_cache(bge 系列),MODELSCOPE_CACHE=D:\MetaverseStudy\modelscope_cache(SenseVoice ~900MB 已就位);CosyVoice2-0.5B 权重 5.3GB 在 `models/voices/CosyVoice/pretrained_models/`。dotenv 进程级生效且不覆盖已存在的系统变量。
- **Chroma** 持久化 `backend/.rag_store/`(15 条种子已灌);**RAG 冷启动实测 ~1-2min** 超 answer 60s 预算触发设计内降级——演示/验收前先打一条知识问题预热(遗留 §6)。排后项将替换为队友 `dataset/` 全量。
- **服务现场**:5173 vite 常驻;**8000 后端视内存可起**(系统内存不足时会被内存管理机制结束进程,非代码问题——本会话后端曾被结束 2 次,重启即恢复,与 E2E 无关)。起后端=`uv run uvicorn app.main:app --port 8000`(不用 --reload;脚本直连用 `127.0.0.1`,uvicorn 只绑 IPv4)。**TTS sidecar 不常驻**(内存不足时后台进程会被结束)——`app/voice/tts.py` 按需懒拉起,首次 TTS 等模型 ~40s 就绪;优先先把 sidecar 预热到就绪再跑 collect 完整链,可避开「总结 TTS 冷启 vs 60s 回合超时上限」的预算冲突(§6 遗留)。手动起=`models/voices/CosyVoice/.venv/Scripts/python.exe backend/app/voice/tts_sidecar.py`(先清 9880 旧监听:`netstat -ano | grep 9880`+`taskkill //F //PID`)。
- **WS 测试脚本坑**:`websockets` 库默认 keepalive ping 20s,RAG 冷加载会断——传 `ping_interval=None`;前端浏览器原生 WebSocket 不受影响。
- **Windows 坑**:仓库文本 CRLF——前端读 `architecture/*.md` 正则要 `\r?\n`+`s` 标志;git-bash 管道下 Python print 中文 GBK 乱码(仅显示,断言在脚本内做);TestClient 的 WS 测试是同步函数不能 `await`;reload 断 WS 时 Proactor ERROR 是已知噪音。
- **Live2D 素材本地化(步骤7 追加)**:素材=运行时产物 `frontend/public/vendor/`(core+4 模型+models.json),**整体 gitignore**(授权禁止再分发);新克隆跑 `npm run l2d:fetch` 重建(需网络,fetch 脚本对可达镜像 404 权威跳过;本地 vendor 缺失自动回退 CDN)。l2d 目录单源=`src/l2d/models.ts`。
- **CORS(步骤9)**:后端已挂 `CORSMiddleware`,白名单=`config.CORS_ALLOW_ORIGINS`(默认 5173 两址,env 可调)。浏览器内 REST(station/admin)受同源策略约束,WS 不受——改前端或新增 REST 端点时留意。

## 3. 已定案的架构裁定(勿重开,详见 git log 与各模块 docstring)

- done 帧**带** session_id;user_input/mood_select 的 session_id **可空**;重连带原 id → 网关认领(`reconnect_adopted`)+热层 snapshot 恢复。
- **轮次回答=同回合连续不发 first_frame**;等待期抢占落 answer/危机;分析中抢占=cancel+弃 state+emitter 标记失效(未发帧不再发出)→entry 承接。
- 模糊输入规则速判按 collect 兜底(first_frame ≤300ms);LLM 异步精化 emotion_label 未接(非必须)。
- 种子语料 15 条人审定稿;全量语料=队友 `dataset/` **排后单做**(看板「排后」项,走 data-contract §4)。
- StageMapData `from_` 序列化必须 `model_dump_json(by_alias=True)`。
- 增量/精稿 draw 前端不可实时区分→「轮答提交→analysis→draw→final」纯前端推断;emotionLabel 写序=first_frame→draw(未手点锁)→mood_select(手点锁,first_frame 解锁)。
- **语音裁定(步骤8)**:ASR=SenseVoice 本地(funasr[knf]);TTS=CosyVoice2-0.5B 经 sidecar HTTP 进程隔离(两套 venv torch 不兼容);音频 IO 全 ffmpeg+stdlib 免疫版本漂移;fillers 预生成同音色。
- **station/admin(步骤9)**:方案书=独立 REST(REST 基址由 `VITE_WS_URL` 换算,单源);危机回合不产素材(网关序列不写 station:input);`clear_memory` = Redis 全键+冷层心情+reports 三清,**治理不降级**(失败 503,与记忆层「异常吞掉、保证回合进行」的默认行为相反,有意例外);config 端点 api_key 用 `HRP_CONFIG_AES_KEY` 加密落库(缺密钥拒存),响应零密钥回显。

## 4. 工程约定与陷阱(ruff/mypy/框架)

### 后端

- **ruff 0.16 默认规则集已扩**(I/RUF/TRY/BLE):`--fix` 可修 import/`__all__`/空 spread 等;pydantic ValueError→`# noqa: TRY004`;降级盲捕→`# noqa: BLE001`;本地日聚合→`# noqa: DTZ005` 单点 helper。
- `from __future__ import annotations` 防 TYPE_CHECKING 前向引用炸;LangGraph 节点签名 `(state, config)`,emitter 走 config;图模块级编译一次。
- pytest-asyncio `asyncio_mode=auto`;loguru 内存 sink record:`extra` 是 dict、`level` 用 `.name`。
- 懒加载分层:chroma/sentence-transformers/langgraph/语音模型全部函数内 import;mypy overrides:funasr/torchaudio/cosyvoice/jieba/rank_bm25 无 stub 已配。
- **记忆(步骤6)**:单例 `get_memory()`;conftest autouse 假记忆+静音 TTS/fillers(新用例默认不触 Redis/sidecar,真链路 test_memory 需 6379);test_voice 的真客户端用例要在**模块导入期捕获原函数**再恢复(fixture 里现取会拿到 conftest 桩)。**conftest 已扩** FakeMemory 补 load_station_input/recent_moods/clear_all+monkeypatch station.routes/admin.routes 的 get_memory+tmp_reports 夹具。
- **语音(步骤8)**:tts 客户端端口/超时调用时读 config(import 期绑定会让 monkeypatch 失效);sidecar 需在导入前覆写 `cosyvoice.utils.file_utils.load_wav`(from-import 绑定,双保险重绑 frontend 模块属性);该 venv 曾被 pip 装 matcha-tts 连锁升级到 torch 2.14——别再往里 pip 装东西,要装先想连锁。
- **步骤9 模块**:`get_reports()`/`get_config_store()` 单例+`reset_*` 测试口;planner RAG/LLM 懒加载+永不抛(降级模板保 latest 终态 ready);pydantic str-Enum 字段传参**必须用枚举成员**(`StationReportStatus.READY`)而非裸字符串,mypy 不全收窄。cryptography 已显式加依赖。
- **TaskStop 结束不了 python 子进程**(结束的是 bash 壳):sidecar/uvicorn 重启前先 `netstat -ano | grep 端口`+`taskkill //F //PID`,SO_REUSEADDR 会多实例占用同一端口;勿依赖长时驻留进程。

### 前端

- **运行时创建的 SVG 吃不到 scoped CSS**——黑板动画类在 `main.css` 全局;组件测试 DOM 断言 `await nextTick()`。
- **pixi-live2d-display 必须走 `/cubism4` 子路径**(主入口顶层硬要求 Cubism2 runtime 必炸);cubism core 走 index.html 本地 vendor+onerror 回退,`window.Live2DCubismCore` 轮询等待。
- **Live2D 目录单源=`l2d/models.ts`**(本地 vendor 优先→source CDN 回退,localStorage 选中,`nextModel` 轮换);`createLive2D` 现接候选数组逐候选试载;切换器=l2d-name 内联⇄按钮。载入候选要传 `modelUrls(entry)`。
- 黑板排版单源:`board/templates.ts`(zones)/`renderer.ts`(wrapChalk 词边界折行≤3行,单测钉住)。
- Pinia store 跨「setup 构造的控制器类↔组件」同实例直接赋值;E2E 观察存疑先页内轮询打点(工具往返时延会造成误判)。
- **tsconfig `noUncheckedIndexedAccess` 已开**——数组下标读取退化 `| undefined`,测试/纯函数传参需收窄(mymodels.spec 曾踩)。
- **截图视觉复核**:子agent `model: "sonnet"`(环境映射 ANTHROPIC_DEFAULT_SONNET_MODEL 视觉模型)Read 图逐项判基准——文本判据外的溢出/遮挡它抓得准(步骤5/7/9 均立功)。

## 5. 现状

- **步骤1-9 全落**:契约/网关/三路路由/RAG/采集/记忆三层/Live2D/语音/工具(station+admin)。测试后端 110(station 15 含 CORS 预检/防重/陈旧重收/planner 降级+非医疗声明硬保证/admin 12 含明文不落库+AES roundtrip)+前端 63(含 l2d models 单源/回退/轮换)。
- **步骤9 相关**:
  - 后端 station(planner/reports/routes)+admin(config_store/routes)为深模块;schema/station.py 对齐 ws-contract §1;main 挂路由+CORS+启动 lifespan 读 config。
  - 前端 `src/station/`(station.ts 控制器+REST/markdown.ts 迷你渲染器/StationPanel.vue 面板,操作钮钉面板底)+邀请语「心灵补给站」分段可点(ChatPanel)+工具栏入口;WSClient 增 `sessionId` getter。
- **v7 mockup 仍有值行段**:工具面板 tool-panel L57-69/L328(心灵练习/留言墙/补给站——补给站已做,心灵练习/留言墙二期);模型配置 cfg L234-242/L348(步骤9 admin/config 已接,前端设置入口未点亮,二期)。
- **排后·全量语料**:队友 `dataset/` 在仓库根(git 未跟踪),走 data-contract §4 回验替换 15 条种子。

## 6. 遗留小事(不阻塞,按排程)

- **RAG 冷启动预热**:启动后台 warm-up 一次(涉后端启动行为,做前打招呼);排后接全量语料顺带处理。
- **总结 TTS vs 60s 回合超时上限的预算冲突**(步骤8 遗留,步骤9 重验再证):sidecar 冷启/DeepSeek 慢流超出回合时长上限,`error(timeout)` 在 `round_archived`(station:input 落库)之后出现,station 链不受影响——建议二期把总结 TTS 移出回合上限、或超时上限不计 TTS 段。演示/验收前先预热 sidecar 规避。
- 口型=播放态点头,音频幅值真口型二期;audio_chunk=整段一帧,流式分块二期。
- mood pill 已显回合 emotionLabel;持久 profile 视图随 admin(步骤9)已接,前端设置入口(含模型配置 UI)未点亮=二期。
- Live2D 真口型 model.speak 与 AudioQueue 双通道播放冲突,接前先设计单一播放源。
- 新增约定命令未入 CLAUDE.md §4(`npm run l2d:fetch`):业务 script 单源=package.json 已收录,CLAUDE.md §4 命令块是否需要补可见性,随排后项重审。
