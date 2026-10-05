# 环境搭建操作手册

> **职能**：队友 clone 后本地部署的唯一操作文档，按节顺序执行到项目启动。

## 1. 环境构建前自查

系统与硬件（本文命令均按 Windows/PowerShell 编写）：

| 项 | 要求 | 验证 | 参考环境 |
|---|---|---|---|
| 操作系统 | Windows 11 | `winver` | — |
| WSL2 | Docker Desktop 的后端，默认版本 2 | `wsl --status` | Ubuntu |
| GPU 与驱动 | NVIDIA GPU，TTS 合成用 | `nvidia-smi` | RTX 4050 Laptop 6GB · 驱动 566.24 |

工具版本：

| 工具 | 要求 | 验证 | 参考版本 |
|---|---|---|---|
| Python | 3.10（pyproject 已锁） | `python --version` | 3.10.11 |
| uv | ≥0.11 | `uv --version` | 0.11.31 |
| Node.js | ≥22.18 或 ≥24.12 | `node -v` | 24.20 |
| Docker Desktop | WSL2 后端（或 Hyper-V 后端）运行中 | `docker version` | 29.7.2 |
| ffmpeg | 含 libopus | `ffmpeg -version` | 8.0-full |
| git | 近期版本 | `git --version` | 2.52 |

另自备 DeepSeek API key（后端构建时填入 `.env`）。

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

编辑 `.env`：填 `DEEPSEEK_API_KEY`（必填）；其余键有默认，改前读注释（provider 切换、Redis 地址、TTS sidecar 端口）。

就绪判据（验证）：

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

自定义数字人模型：把模型目录按原名放入 `public/vendor/live2d/models/`，在 `models.json` 手工加一行。

## 4. 模型下载

模型有两类落点：RAG 检索模型落 `backend/models/`，TTS 权重落仓库根 `models/voices/`。两类落点不同，下载前先看对应节说明。

### 4.1 RAG 检索模型与灌库

**模型下载前需要注意**：代码按本地路径读模型（`backend/app/config.py`：`RAG_EMBED_MODEL`/`RAG_RERANK_MODEL` = `backend/models/<模型名>`），下载时必须用 `--local-dir` 落到 `backend/models/`。不加 `--local-dir` 的下载命令会把模型下载到 C 盘默认缓存（`C:\Users\<用户名>\.cache\huggingface\`）：

```bash
cd backend
uv run hf download BAAI/bge-m3 --local-dir models/bge-m3
uv run hf download BAAI/bge-reranker-v2-m3 --local-dir models/bge-reranker-v2-m3
```

> [!note]
> 说明：模型权重共约 4.3GB，`backend/models/` 已 gitignore 不入库。下载失败、超时、报 Xet 元数据错时挂镜像重试（命令同上，前面加 `HF_ENDPOINT=https://hf-mirror.com`）。

---

**灌库前需要注意**：向量库 `backend/.rag_store/` 是运行时产物，不入 git——**clone 后首次必跑一次**；已灌过的环境重跑无害但费时（全量重新 embed），勿重复执行；语料 jsonl（`backend/data/`）变更后才需重跑，结构变更加 `--reset` 清空两库重建：

```bash
uv run python -m app.rag.ingest
```

### 4.2 ASR · SenseVoice

**模型下载前需要注意**：引擎 `funasr` 已随「后端构建」节的依赖装好，只有权重需要下载。权重 `iic/SenseVoiceSmall` 首次调用自动下载，约 900MB，落到系统环境变量 `MODELSCOPE_CACHE` 指定的目录（如 `D:\modelscope_cache`）。不设该变量会默认存到 C 盘（`C:\Users\<用户名>\.cache\modelscope\`）。

### 4.3 TTS · CosyVoice 2

**模型下载前需要注意**：本节命令在**仓库根目录**执行（不是`backend/`）。CosyVoice 独立 venv 与权重共约 5.3GB，落仓库根 `models/voices/`（gitignored）。RAG 模型落的是 `backend/models/`，两者落点不同，勿混：

```bash
git clone https://github.com/QwenAudio/CosyVoice.git models/voices/CosyVoice
cd models/voices/CosyVoice
uv venv --python 3.10
"setuptools<81" | Out-File -Encoding ascii build-constraints.txt
uv pip install --python .venv/Scripts/python.exe --index-strategy unsafe-best-match --build-constraints build-constraints.txt -r requirements.txt
```

> [!note]
> 说明：独立 venv（与 `backend/.venv` 混装会失败）；`--index-strategy unsafe-best-match`（双 extra-index 跨源解析）；`--build-constraints`（setuptools≥81 已删 `pkg_resources`，不加会构建失败）。版本核对参照 `backend/scripts/freeze_gpu_blueprint.txt`（重建用）与 `freeze_sidecar_rollback.txt`（回滚用）。模型权重（`CosyVoice2-0.5B`，ModelScope/HF）以官方 README 现行命令为准（下载命令随上游更新，先核对再执行）。requirements 含 GPU 相关依赖，装不上时查「故障排查」节。

## 5. 故障排查

| 症状 | 处置 |
|---|---|
| hf/ModelScope 下载超时 | 挂 `HF_ENDPOINT=https://hf-mirror.com`（见「模型下载」节）；ModelScope 同理查 `MODELSCOPE_CACHE` |
| 6379 端口被占 | `docker ps` 查旧容器；只动 `hrp-redis`，无关容器勿删 |
| 8000/9880 残留进程 | `taskkill //F /PID <pid>`（后端与 sidecar 都要清） |
| node 版本不对 | 系统环境变量 PATH 删旧 Node 条目，重开终端 |
| 脚本中文乱码 | 配 `PYTHONIOENCODING=utf-8` |
| RAG 模型路径找不到 | `backend/models/bge-m3`、`backend/models/bge-reranker-v2-m3` 两目录须有模型文件；重跑「模型下载」节的下载命令（带 `--local-dir`） |
| 模型装错位置 | RAG 模型须在 `backend/models/`，TTS 权重与 venv 须在仓库根 `models/voices/`。装到别处就整个目录移动过去，勿重下 |
| SenseVoice 权重找不到 | `MODELSCOPE_CACHE` 须系统级生效，重开终端再验 |
| CosyVoice 构建崩 | 查 `build-constraints.txt` 在位；详见 `freeze_gpu_blueprint.txt` 头注 |

## 6. 项目启动

```bash
cd backend && uv run hrp        # 默认 127.0.0.1:8000;lifespan 自动拉 TTS sidecar 并版本握手,RAG 预热
cd frontend && npm run dev      # http://localhost:5173
```

> [!tip]
> 后端启动后，可查看终端日志情况校验前四节是否全部就位：sidecar 拉起失败查「TTS · CosyVoice 2」节，Redis 连不上查「Redis」节。开发热载：`uv run hrp --reload`，配 `TTS_SIDECAR_KILL_ON_EXIT=0`。
