# 环境搭建操作手册

> **职能**:队友 clone 后本地部署的唯一操作文档,按节顺序执行到项目启动。
> 护栏:命令失败/依赖装不上 → 停下问人(AGENTS.md),不静默换依赖。
> 单步失败先查 §5 故障排查;查不到停下问人。

## 1. 版本锚定

装好下列工具并验证:

| 工具 | 要求 | 验证 | 参考版本 |
|---|---|---|---|
| Python | 3.10(pyproject 已锁) | `python --version` | 3.10.11 |
| uv | ≥0.11 | `uv --version` | 0.11.31 |
| Node.js | ≥22.18 或 ≥24.12 | `node -v` | 24 LTS |
| Docker Desktop | WSL2 后端,鲸鱼图标稳定 | — | 29.1.5 |
| ffmpeg | 含 libopus | `ffmpeg -version` | 8.0-full |
| git | 近期版本 | `git --version` | 2.52 |

另备 DeepSeek API key(§2 填入 `.env`)。

## 2. 后端构建

### 2.1 Redis

```bash
docker run -d --name hrp-redis -p 6379:6379 --restart unless-stopped redis:7-alpine
docker exec hrp-redis redis-cli ping        # 应答 PONG
```

### 2.2 依赖与配置

```bash
cd backend
uv sync
cp .env.example .env
```

编辑 `.env`:填 `DEEPSEEK_API_KEY`(必填);其余键有默认,改前读注释(provider 切换/Redis 地址/TTS sidecar 端口)。

就绪判据:

```bash
uv run python -V                                            # 3.10.x
uv run python -c "import fastapi, langgraph, chromadb, funasr; print('deps ok')"
```

## 3. 前端构建

```bash
cd frontend
npm install
node scripts/fetch-l2d.mjs        # Live2D 素材本地化(幂等;产出 public/vendor/live2d/)
```

自定义数字人模型:`public/vendor/live2d/models/` 同名目录丢入模型,在 `models.json` 手工加一行。

## 4. 模型下载

### 4.1 RAG 检索模型与灌库

```bash
cd backend
uv run hf download BAAI/bge-m3 BAAI/bge-reranker-v2-m3    # 共约 4.3GB
uv run python -m app.rag.ingest                            # 语料 → Chroma
# 语料结构变更后重灌:加 --reset
```

下载失败/超时 → 切镜像:

```bash
HF_ENDPOINT=https://hf-mirror.com uv run hf download BAAI/bge-m3 BAAI/bge-reranker-v2-m3
```

缓存默认落 `C:\Users\<用户名>\.cache\huggingface\hub`。挪盘:设系统环境变量 `HF_HOME`(如 `D:\hf_cache`),重开终端验证:

```bash
uv run python -c "from huggingface_hub import constants; print(constants.HF_HUB_CACHE)"
```

输出以所设路径开头即成。中文用户名曾有 sentencepiece 坑,推荐系统级 `HF_HOME`。

### 4.2 ASR · SenseVoice

引擎 `funasr` 已随 §2 依赖装好;权重 `iic/SenseVoiceSmall` 首次调用自动下载,约 900MB。落盘位:系统环境变量 `MODELSCOPE_CACHE`(如 `D:\modelscope_cache`),不设落 C 盘。

### 4.3 TTS · CosyVoice 2

独立 venv + 权重 5.3GB(落 `models/voices/`,gitignored):

```bash
git clone https://github.com/QwenAudio/CosyVoice.git models/voices/CosyVoice
cd models/voices/CosyVoice
uv venv --python 3.10
"setuptools<81" | Out-File -Encoding ascii build-constraints.txt
uv pip install --python .venv/Scripts/python.exe --index-strategy unsafe-best-match --build-constraints build-constraints.txt -r requirements.txt
```

三个硬约束:独立 venv(与应用 venv 混装必炸);`--index-strategy unsafe-best-match`(双 extra-index 跨源解析);`--build-constraints`(setuptools≥81 已删 `pkg_resources`,构建必崩)。版本核对蓝本 = `backend/scripts/freeze_gpu_blueprint.txt`(重建)与 `freeze_sidecar_rollback.txt`(回滚参照)。requirements 含 GPU 向依赖,装不动停下问人。模型权重(`CosyVoice2-0.5B`,ModelScope/HF)按官方 README 现行命令下载,先核对再跑。

## 5. 故障排查

| 症状 | 处置 |
|---|---|
| hf/ModelScope 下载超时 | 挂 `HF_ENDPOINT=https://hf-mirror.com`(§4.1);ModelScope 同理查 `MODELSCOPE_CACHE` |
| 6379 端口被占 | `docker ps` 查旧容器;只动 `hrp-redis`,无关容器勿删 |
| 8000/9880 残留进程 | `taskkill //F /PID <pid>`(后端与 sidecar 都要清) |
| node 版本不对 | 系统环境变量 PATH 删旧 Node 条目,重开终端 |
| 脚本中文乱码 | 配 `PYTHONIOENCODING=utf-8` |
| 模型路径找不到 | `HF_HOME`/`MODELSCOPE_CACHE` 须系统级生效,重开终端再验 |
| CosyVoice 构建崩 | 查 `build-constraints.txt` 在位;详见 `freeze_gpu_blueprint.txt` 头注 |

## 6. 项目启动

```bash
cd backend && uv run hrp        # 默认 127.0.0.1:8000;lifespan 自动拉 TTS sidecar 并版本握手,RAG 预热
cd frontend && npm run dev      # http://localhost:5173
```

后端启动即校验 §1-§4 全部就位:sidecar 拉起失败查 §4.3,Redis 连不上查 §2.1。开发热载:`uv run hrp --reload`,配 `TTS_SIDECAR_KILL_ON_EXIT=0`。

启动后跑三链路冒烟,话术与判据 = AGENTS.md §7。

## 7. coding agent 接力提示词

编码期每次开新窗口,整块粘贴:

```
你在心栖阁仓库工作,接续跨会话开发。开工顺序:CLAUDE.md → docs/task-kanbans/kanban-v1.md
→ docs/task-kanbans/handoff.md;按看板§0工作方式执行(高噪音步骤派子agent黑盒只收结论,
主会话只做决策/编码/commit),继续看板当前未完成步骤;每步完成跑 AGENTS.md §7 对应用例,
停下汇报→人确认→commit(看板勾选+handoff 同步)→继续;护栏照 AGENTS.md(命令失败/依赖
装不上/契约冲突/需改架构→停下问人,不静默改)。
```

快照纪律:交接点收尾必须更新看板勾选 + 重写 handoff.md 并一并 commit,再开新窗。
