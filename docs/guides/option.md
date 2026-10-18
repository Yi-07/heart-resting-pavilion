# 环境搭建操作手册

> **职能**：队友 clone 后本地部署的唯一操作文档，按节顺序执行到项目启动。
> **路径**：TTS 走仓库内 vendored 的 GPT-SoVITS，后端自动拉起它的 tts_service 子进程。
> **深度与排障**：实测值、踩坑成因、日志对照表见 [jl-option.md](jl-option.md)（本文的实测与排障附录）。
> 命令均按 Windows PowerShell 编写，`<仓库>` 指本仓库根目录。

## 1. 准备工具

安装并确认以下工具：

| 工具 | 要求 | 检查命令 |
|---|---|---|
| Python | 后端 3.10；GPT-SoVITS 3.12.14 | `python --version` |
| uv | ≥0.11，已加入 PATH | `uv --version` |
| Node.js | `>=22.18.0` 或 `>=24.12.0` | `node -v` |
| ffmpeg | 含 libopus，已加入 PATH | `ffmpeg -version` |
| Redis | 本机监听 `6379` | `redis-cli PING` |
| NVIDIA GPU | TTS 合成与 RAG 检索用 | `nvidia-smi` |

后端需要 DeepSeek API key。准备好后，在第 8 节写入 `.env`。

Redis 未安装时，可以使用 Docker：

```powershell
docker run -d --name hrp-redis -p 6379:6379 --restart unless-stopped redis:7-alpine
docker exec hrp-redis redis-cli ping
```

检查结果应为 `PONG`。

## 2. 设置模型缓存目录

模型较大，建议把缓存放在空间充足且路径只含 ASCII 字符的磁盘。以下变量只对当前 PowerShell 窗口生效：

```powershell
$env:HF_HOME = 'D:\model-cache\huggingface'
$env:MODELSCOPE_CACHE = 'D:\model-cache\modelscope'
```

需要长期生效时，把这两个变量写入 `backend/.env`。
`HF_HOME` 用于 RAG 模型。
`MODELSCOPE_CACHE` 用于首次调用 SenseVoice 时下载的 ASR 模型。

## 3. 安装后端依赖

没有本地 CUDA wheel 时，从仓库根目录执行：

```powershell
cd <仓库>\backend
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

`uv sync` 会创建 `backend/.venv`。torch 和 torchaudio 按 `backend/pyproject.toml` 使用 PyTorch `cu126` 索引。
清华源只提供未指定其他索引的依赖，torch 仍从 PyTorch 官方索引下载。

有本地 CUDA wheel 时，先安装 torch，再安装其余依赖：

```powershell
cd <仓库>\backend
uv venv
uv pip install --python .venv `
  --default-index https://pypi.tuna.tsinghua.edu.cn/simple `
  --find-links <wheel目录> `
  "torch==2.12.1+cu126" "torchaudio==2.11.0+cu126"
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

`uv sync` 会保留已安装且满足锁定版本的 torch。

检查 CUDA 版 torch：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, '| cuda:', torch.cuda.is_available())"
```

结果应包含 `2.12.1+cu126` 和 `cuda: True`。
`+cuXXX` 后缀必须保留。无后缀的 torch 是 CPU 版，`torch.cuda.is_available()` 会返回 `False`。这是静默降级，不报错。

## 4. 安装 GPT-SoVITS 依赖

后端和 GPT-SoVITS 必须使用两个独立环境。没有本地 CUDA wheel 时，进入 TTS 目录执行：

```powershell
cd <仓库>\GPT-SoVITS
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

有本地 CUDA wheel 时，使用 Python 3.12 对应的三个 wheel：

```powershell
cd <仓库>\GPT-SoVITS
uv venv
uv pip install --python .venv `
  --default-index https://pypi.tuna.tsinghua.edu.cn/simple `
  --find-links <wheel目录> `
  "torch==2.6.0+cu124" "torchaudio==2.6.0+cu124" "torchvision==0.21.0+cu124"
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

wheel 文件必须与 Python 版本匹配：

```text
torch-2.12.1+cu126-cp310-cp310-win_amd64.whl
torchaudio-2.11.0+cu126-cp310-cp310-win_amd64.whl
torch-2.6.0+cu124-cp312-cp312-win_amd64.whl
torchaudio-2.6.0+cu124-cp312-cp312-win_amd64.whl
torchvision-0.21.0+cu124-cp312-cp312-win_amd64.whl
```

`cp310` 对应 Python 3.10，`cp312` 对应 Python 3.12。两个环境不能合并，torch、transformers 和 numpy 版本不同。

没有镜像访问条件时，分别在两个项目目录执行 `uv sync`：

```powershell
cd <仓库>\backend
uv sync
cd ..\GPT-SoVITS
uv sync
```

其余依赖会从 `pypi.org` 下载，torch 仍使用 PyTorch 官方索引。

检查 CUDA 版 torch：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, '| cuda:', torch.cuda.is_available())"
```

结果应包含 `2.6.0+cu124` 和 `cuda: True`。

## 5. 下载 TTS 模型

在 `GPT-SoVITS` 目录使用仓库内脚本：

```powershell
uv run python down-model.py
```

脚本会下载并放置以下资源（幂等，已存在的跳过）：

- `GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/`
- `GPT_SoVITS/pretrained_models/chinese-hubert-base/`
- `GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/`
- `GPT_SoVITS/pretrained_models/fast_langdetect/lid.176.bin`
- `GPT_SoVITS/text/G2PWModel/`

脚本默认使用 `https://hf-mirror.com`。

确认关键文件（以下命令在 `<仓库>` 根目录执行）：

```powershell
cd <仓库>
$base = 'GPT-SoVITS\GPT_SoVITS'
Test-Path "$base\pretrained_models\chinese-roberta-wwm-ext-large\pytorch_model.bin"
Test-Path "$base\pretrained_models\chinese-hubert-base\pytorch_model.bin"
Test-Path "$base\pretrained_models\gsv-v2final-pretrained\s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt"
Test-Path "$base\pretrained_models\gsv-v2final-pretrained\s2G2333k.pth"
Test-Path "$base\pretrained_models\fast_langdetect\lid.176.bin"
Test-Path "$base\text\G2PWModel\g2pW.onnx"
```

六条结果都应为 `True`。

> `lid.176.bin` 容易漏：`langsegmenter.py` 在 import 时把 fast_langdetect 的 detector 整个替换掉，`cache_dir` 写死在项目内那个路径，`FTLANG_CACHE` 对它无效。脚本不可用时的手工补法见 jl-option.md「手工补 `lid.176.bin`」节。

## 6. 下载 RAG 模型

进入后端目录，把模型直接下载到代码读取的目录：

```powershell
cd <仓库>\backend
$env:HF_ENDPOINT = 'https://hf-mirror.com'
uv run hf download BAAI/bge-m3 `
  --local-dir models\bge-m3 `
  --exclude 'onnx/*' 'imgs/*' 'README.md' '.gitattributes'
uv run hf download BAAI/bge-reranker-v2-m3 `
  --local-dir models\bge-reranker-v2-m3 `
  --exclude 'onnx/*' 'imgs/*' 'assets/*' 'README.md' '.gitattributes'
```

必须保留 `--local-dir`。应用从 `backend/models/` 读取模型，不会从 Hugging Face 缓存目录查找这两个模型。

SenseVoice 使用 `iic/SenseVoiceSmall`，首次执行语音转写时由 `funasr` 自动下载到 `MODELSCOPE_CACHE`，不需要手动下载。

## 7. 安装前端依赖和 Live2D 素材

```powershell
cd <仓库>\frontend
npm install
node scripts/fetch-l2d.mjs
```

素材会写入 `frontend/public/vendor/live2d/`。该目录已被 gitignore，每台机器都要执行素材下载。

抓不到 Cubism Core 时脚本会 `exit 1`，后面的模型一个都不下；兜底办法见 jl-option.md「Live2D 素材本地化」节。

## 8. 创建配置文件

在 `backend` 目录复制配置模板：

```powershell
cd <仓库>\backend
Copy-Item .env.example .env
```

编辑 `backend/.env`，至少填写：

```dotenv
DEEPSEEK_API_KEY=你的密钥
```

需要修改模型缓存目录时，在同一个文件中填写 `HF_HOME` 和 `MODELSCOPE_CACHE`。
默认配置会让后端自动启动 `GPT-SoVITS` 的 TTS 服务。
确认以下配置仍指向仓库内路径：

```dotenv
TTS_SERVICE_SPAWN=1
TTS_SERVICE_PYTHON=../GPT-SoVITS/.venv/Scripts/python.exe
TTS_SERVICE_CWD=../GPT-SoVITS
```

## 9. 初始化运行数据

先生成 RAG 向量库：

```powershell
uv run python -m app.rag.ingest
```

语料变更后重跑。需要清空并重建时使用 `--reset`。向量库 `backend/.rag_store/` 不入 git，clone 后首次必跑。

> [!tip]
> 固定话术音频依赖正在运行的 TTS 服务。先执行「启动项目」中的命令，确认 `http://127.0.0.1:9001/ready` 返回就绪，再回到这里执行下面的命令。

```powershell
uv run python -m app.voice.fillers
```

音频写入 `backend/data/fillers/`。该目录为空时，危机话术仍有文字，但没有预置语音。

## 常用检查

```powershell
# 后端目录
uv run ruff check app
uv run mypy app
uv run pytest

# 前端目录
cd ..\frontend
npm run type-check
npm run lint
npm run test:unit
```

## 10. 启动项目

后端会自动拉起 TTS 子进程。打开两个 PowerShell 窗口，分别执行：

```powershell
# 窗口一
cd <仓库>\backend
uv run hrp
```

```powershell
# 窗口二
cd <仓库>\frontend
npm run dev
```

前端默认地址为 `http://localhost:5173`，后端默认地址为 `http://127.0.0.1:8000`。

## 排障入口

只列上手后最常撞的四条，成因与完整排障见 [jl-option.md](jl-option.md)「排障」节。

| 现象 | 处置 |
|---|---|
| 后端起不来，不知道健康没有 | backend **没有** `/health` 路由，打它必然 404，与监听好坏无关。改打真路由：`curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/openapi.json`（期望 200）、`/admin/trends`（期望 200）、TTS 的 `http://127.0.0.1:9001/ready`（期望 200） |
| 聊天正常但所有 REST 接口打不开 | `netstat -ano | findstr :8000` 只看得到 `ESTABLISHED`、没有 `LISTENING`，就是监听套接字已失效，重启后端。成因见 jl-option.md「聊天正常但所有 REST 接口打不开」 |
| 危机路径只有文字没有声音 | `backend/data/fillers/` 是空的，回第 9 节跑 `app.voice.fillers` |
| TTS 日志里中文或符号变成 `?` / `�` | 子进程 stdio 跟本机 ANSI 代码页走了，确认 `.env` 里 `TTS_SERVICE_PYTHONIOENCODING=utf-8` 生效 |

排查 TTS 权重、依赖缺失时，看 `GPT-SoVITS/logs/tts_service_stdout.log`——`Loading … weights` 那几行只在它里面，日志对照表见 jl-option.md「日志分三处」。
