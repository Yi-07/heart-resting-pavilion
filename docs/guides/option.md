# 环境搭建操作手册

> **职能**:队友 clone 后从零到可用的唯一操作手册,全步骤人工执行;README 环境构建节只留本文指针。
> **分档**:§1-§3+§7=最小启动(文字三链路);§4-§6 可选增强(RAG/立绘/语音),不做则对应能力缺省降级。
> 护栏:命令失败/依赖装不上 → 停下问人(AGENTS.md),不静默换依赖。
> 排查统一见 §8;本文不记进度,执行状态归看板。

## 0. 前置检查

| 工具 | 版本要求 | 验证命令 | 参考版本 |
|---|---|---|---|
| git | 任意近期 | `git --version` | 2.52 |
| uv | ≥0.11 | `uv --version` | 0.11.31 |
| Node.js | ≥22.18 或 ≥24.12 | `node -v` | 24 LTS |
| Docker Desktop | WSL2 后端 | 鲸鱼图标稳定 | 29.1.5 |
| ffmpeg | 含 libopus(ASR 转码用) | `ffmpeg -version` | 8.0-full |

另备:DeepSeek API key(§2 填入 `.env`)。

## 1. Redis(记忆层前提)

启动 Docker Desktop,拉起容器:

```bash
docker run -d --name hrp-redis -p 6379:6379 --restart unless-stopped redis:7-alpine
docker exec hrp-redis redis-cli ping
```

第二条应答 `PONG`。`--restart unless-stopped` 使容器随 Docker 自启,日常开机只需开 Docker Desktop。compose 一次拉起方案落地后替换本节。

## 2. 后端:依赖 + .env

```bash
cd backend
uv sync
cp .env.example .env
```

编辑 `.env`:

| 键 | 必填 | 默认 | 说明 |
|---|---|---|---|
| DEEPSEEK_API_KEY | 是 | — | LLM 直答/采集/总结全部依赖 |
| LLM_PROVIDER | 否 | deepseek | ollama=本地兜底 |
| REDIS_URL | 否 | 127.0.0.1:6379 | 与 §1 容器一致 |
| 其余键 | 否 | 见注释 | provider 切换/TTS sidecar/危机阈值 |

就绪判据:

```bash
uv run python -V        # 3.10.x
uv run python -c "import fastapi, langgraph, chromadb, funasr; print('deps ok')"
```

## 3. 前端:依赖

```bash
cd frontend
npm install
npm run dev             # 浏览器开 http://localhost:5173 见页面即真
```

node 版本不满足 → 升级 LTS 后重开终端;旧 PATH 条目残留见 §8。

## 4. RAG 知识库(完整档)

不做本节 = answer 知识查询降级,文字链路不受影响。

### 4.1 模型下载

```bash
cd backend
uv run hf download BAAI/bge-m3 BAAI/bge-reranker-v2-m3
```

两模型共约 4.3GB。下载失败/超时 → 切镜像:

```bash
HF_ENDPOINT=https://hf-mirror.com uv run hf download BAAI/bge-m3 BAAI/bge-reranker-v2-m3
```

缓存默认落 `C:\Users\<用户名>\.cache\huggingface\hub`。挪盘:设系统环境变量 `HF_HOME`(如 `D:\hf_cache`)后重开终端,验证:

```bash
uv run python -c "from huggingface_hub import constants; print(constants.HF_HUB_CACHE)"
```

输出以所设路径开头即成。中文用户名曾有 sentencepiece 坑,推荐系统级 `HF_HOME`。

### 4.2 语料灌库

```bash
cd backend
uv run python -m app.rag.ingest          # 语料 jsonl → Chroma
# 语料结构变更后重建:加 --reset 清空两库重灌
```

## 5. Live2D 素材(可选)

不做本节 = 立绘空白,功能不受影响。素材授权禁止再分发,目录不入库,clone 后为空:

```bash
cd frontend
node scripts/fetch-l2d.mjs    # 幂等;jsdelivr 镜像;产出 public/vendor/live2d/
```

自定义模型:同格式目录丢入 `public/vendor/live2d/models/`,在 `models.json` 手工加一行。

## 6. 语音栈(可选,人做)

不做本节 = 语音无声,文字链路不受影响。

### 6.1 TTS · CosyVoice 2

独立 venv,权重 5.3GB 落 `models/voices/`(gitignored)。重建蓝本(GPU torch 钉版/setuptools<81 坑/extra-index 说明)= `backend/scripts/freeze_gpu_blueprint.txt`,按蓝本逐步执行;requirements 含 GPU 向依赖,装不动停下问人。

### 6.2 ASR · SenseVoice

引擎 `funasr` 已随 §2 依赖装好;权重 `iic/SenseVoiceSmall` 首次调用自动下载,约 900MB。落盘位:系统环境变量 `MODELSCOPE_CACHE`(如 `D:\modelscope_cache`),不设则落 C 盘用户缓存。音频链路:前端 webm/opus → ffmpeg 转码 wav 16k → SenseVoice;转写即弃(红线)。

### 6.3 测试语音素材

回归用音频自备,放 `backend/tests/voices/`(红线:音频不入库,目录已 gitignore)。

## 7. 启动与冒烟

```bash
cd backend && uv run hrp      # 默认 127.0.0.1:8000;lifespan 自动拉 TTS sidecar + RAG 预热
```

开发热载:`uv run hrp --reload`,配 `TTS_SIDECAR_KILL_ON_EXIT=0`。前端 `npm run dev` 后跑三链路冒烟,话术与判据 = AGENTS.md §7。

## 8. 故障排查

| 症状 | 处置 |
|---|---|
| hf 下载超时 | 挂 `HF_ENDPOINT=https://hf-mirror.com`(§4.1) |
| 6379 端口被占 | `docker ps` 查旧容器;无关容器勿动,只管 `hrp-redis` |
| 8000/9880 残留进程 | `taskkill //F /PID <pid>`(后端/ sidecar 都要清) |
| node 版本不对 | 系统环境变量 PATH 删旧 Node 条目,重开终端 |
| e2e/脚本中文乱码 | 配 `PYTHONIOENCODING=utf-8` |
| 模型加载找不到路径 | 检查 `HF_HOME`/`MODELSCOPE_CACHE` 是否系统级生效(重开终端) |

## 9. coding agent 接力提示词

编码期每次开新窗口,整块粘贴:

```
你在心栖阁仓库工作,接续跨会话开发。开工顺序:CLAUDE.md → docs/task-kanbans/kanban-v1.md
→ docs/task-kanbans/handoff.md;按看板§0工作方式执行(高噪音步骤派子agent黑盒只收结论,
主会话只做决策/编码/commit),继续看板当前未完成步骤;每步完成跑 AGENTS.md §7 对应用例,
停下汇报→人确认→commit(看板勾选+handoff 同步)→继续;护栏照 AGENTS.md(命令失败/依赖
装不上/契约冲突/需改架构→停下问人,不静默改)。
```

快照纪律:交接点收尾必须更新看板勾选+重写 handoff.md 并一并 commit,再开新窗。
