# 环境搭建与部署手册（JL 版）

> 本文是 `option.md` 的并行版本，不覆盖它。两份的差异见末节「与 option.md 的差异」。
> 本文只写**在本机实测跑通**的做法；数字都是实测值，不是估计值。
> 编写日期：2026-10-17。

---

## 0. 目标环境

| 项 | 值 | 备注 |
|---|---|---|
| GPU | NVIDIA GeForce RTX 4060 Laptop，8188 MiB | 显存是本文所有取舍的硬约束，见 §7 |
| OS | Windows（PowerShell） | 见 §9.3 的 Windows 专有陷阱 |
| 后端解释器 | `backend/.venv`，CPython 3.10.21，torch 2.12.1+cu126 | 211 包 |
| TTS 解释器 | `GPT-SoVITS/.venv`，CPython 3.12.14，torch 2.6.0+cu124 | 143 包 |
| ffmpeg | 8.0.1，需在 PATH | ASR 音频转码硬依赖 |
| Redis | 本机 6379 | 记忆层硬依赖 |
| Node | ≥22.18.0 或 ≥24.12.0 | 前端构建 |

**两个 venv 不能合并**：torch 2.6 与 2.12、transformers 4.50 与 4.51、numpy 1.26 与 2.2 三处互斥；且 `GPT_SoVITS/configs/tts_infer.yaml` 的推理参数（`repetition_penalty=1.35` / `top_k=5` / `top_p=1.0` / `seed=42`）是按 torch 2.6.0+cu124 这套钉版标定的，换版本必须重标。

---

## 1. 依赖单源

| 环境 | 文件 | 说明 |
|---|---|---|
| backend | `backend/pyproject.toml` + `backend/uv.lock` + `backend/.python-version` | 29 个直接依赖全部 `==` 钉版 |
| TTS | `GPT-SoVITS/pyproject.toml` + `GPT-SoVITS/uv.lock` + `GPT-SoVITS/.python-version` | 版本照抄实测环境；含 16 个反查出来的间接必需项，见 §9.2 |

日常命令：

### 1.1 三条安装路线，先选一条

**先搞清一件事：`--default-index`（清华源）只管「没有被显式指去别的索引的包」。**

torch / torchaudio / torchvision 由各自 `pyproject.toml` 里的这两段锁死在 `download.pytorch.org`：

```toml
[[tool.uv.index]]
name = "pytorch-cu126"
url = "https://download.pytorch.org/whl/cu126"
explicit = true          # 只有 sources 指过来的包才从这里取

[tool.uv.sources]
torch = { index = "pytorch-cu126" }
```

**所以加清华源不会让 torch 变快**，torch 永远走 PyTorch 官方索引。其余 200 来个包才走清华。

---

#### 路线 A：有本地 CUDA wheel（推荐，约 2 分钟）

适合本机、或能拿到 wheel 的场景。torch 零下载。

下文 `<仓库>` 指本仓库根目录，`<wheel目录>` 指你放 CUDA wheel 的文件夹，换成你自己的路径。

```powershell
cd <仓库>\backend

uv venv                                                    # ① 必须先建
uv pip install --python .venv `
  --default-index https://pypi.tuna.tsinghua.edu.cn/simple `
  --find-links <wheel目录> `
  "torch==2.12.1+cu126" "torchaudio==2.11.0+cu126"         # ② torch 从本地 wheel
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple   # ③ 其余走清华
```

GPT-SoVITS 同理，换成三个包：

```powershell
cd ..\GPT-SoVITS
uv venv
uv pip install --python .venv `
  --default-index https://pypi.tuna.tsinghua.edu.cn/simple `
  --find-links <wheel目录> `
  "torch==2.6.0+cu124" "torchaudio==2.6.0+cu124" "torchvision==0.21.0+cu124"
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

**为什么第 ③ 步不会把第 ② 步的 torch 覆盖掉**：`uv sync` 按 lock 核对，已满足的版本不动。实测 `uv sync --dry-run` 的待装列表里不含 torch。

**wheel 目录需要什么文件**：

```
torch-2.12.1+cu126-cp310-cp310-win_amd64.whl        backend 用，2499 MB
torchaudio-2.11.0+cu126-cp310-cp310-win_amd64.whl   backend 用，1 MB
torch-2.6.0+cu124-cp312-cp312-win_amd64.whl         GPT-SoVITS 用，2415 MB
torchaudio-2.6.0+cu124-cp312-cp312-win_amd64.whl    GPT-SoVITS 用，4 MB
torchvision-0.21.0+cu124-cp312-cp312-win_amd64.whl  GPT-SoVITS 用，6 MB
```

cp310 = Python 3.10，cp312 = Python 3.12，别拿错。

---

#### 路线 B：没有 wheel，走官方索引（换机器的默认路径）

```powershell
cd <仓库>\backend
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple

cd ..\GPT-SoVITS
uv sync --default-index https://pypi.tuna.tsinghua.edu.cn/simple
```

`uv sync` 会自己建 venv，不需要先 `uv venv`。

耗时参考：torch 从 `download.pytorch.org` 持续 **2.02 MB/s**（五段 40 MB 实测，波动 1.31~3.91），2.4 GB → **约 20 分钟一个**，两个环境共约 40 分钟；其余包走清华约 5 分钟。这是一次性成本，之后 uv 按内容哈希缓存，再 `uv sync` 是秒级。

---

#### 路线 C：不指定源（能跑，但慢）

```powershell
uv sync
```

其余 200 来个包走 `pypi.org`（国内不稳定）。torch 仍然走 `download.pytorch.org`，因为它不受 `--default-index` 影响。网络特别差时可以试，但不推荐。

---

### 1.2 装完必须验这一条

```powershell
# backend
.\.venv\Scripts\python.exe -c "import torch;print(torch.__version__,'| cuda:',torch.cuda.is_available(),'|',torch.cuda.get_device_name(0))"

# GPT-SoVITS
.\.venv\Scripts\python.exe -c "import torch;print(torch.__version__,'| cuda:',torch.cuda.is_available())"
```

期望：

```
2.12.1+cu126 | cuda: True | NVIDIA GeForce RTX 4060 Laptop GPU
2.6.0+cu124  | cuda: True
```

**`+cuXXX` 后缀必须在。** 装成无后缀的 `2.12.1` 就是 CPU 版——这是**静默降级，不报错**，只有 `torch.cuda.is_available()` 会露馅。Windows 上 PyPI 的 torch 就是 CPU 版（195 MB vs CUDA 版 2499 MB），详见 §8.3。

### 1.3 日常命令

装完之后，日常只有这四条：

```powershell
cd backend;    uv run hrp                        # 起 backend（自动拉起 TTS 子进程）
cd backend;    uv run python -m app.rag.ingest   # 重灌 RAG 库
cd backend;    uv run python -m app.voice.fillers # 重生成预置语音
cd frontend;   npm run dev                       # 起前端
```

验证：

```powershell
cd backend
uv run ruff check app
uv run mypy app
uv run pytest
```

`uv run` 会用项目 `.venv`，不需要 activate，也不会串到 conda 环境。

---

## 2. 前置依赖

### 2.1 Redis

```powershell
redis-cli PING        # 期望 PONG
```

backend 启动日志里出现 `memory_ready · Redis 连接正常` 即通。不通时记忆层降级，回合仍能走。

### 2.2 ffmpeg

```powershell
ffmpeg -version
```

`backend/app/voice/asr.py:53` 用 `subprocess.run(["ffmpeg", ...])` 做 webm/opus → wav16k 转码，靠 PATH 查找。不装则语音输入整体失效。

### 2.3 Node

```powershell
node -v               # 需满足 frontend/package.json 的 engines
```

---

## 3. Live2D 素材本地化

先安装 Node 依赖，再执行抓取脚本构建前端与下载 Live2D：

```powershell
cd frontend
npm install
node scripts/fetch-l2d.mjs        # Live2D 素材本地化(幂等;产出 public/vendor/live2d/)
```

脚本零第三方依赖（只用 `node:fs/promises` / `node:path` / `node:url`），所以 `npm install` 与它的执行顺序可以颠倒。`npm install` 是起 dev server 才需要的。

产出：

```
frontend/public/vendor/live2d/
├── core/live2dcubismcore.min.js          Cubism Core 运行时，207 KB
├── models/haru/                          默认模型（default: true）
├── models/wanko/                         第二尊
└── models.json                           目录清单，前端切换器读
```

**唯一硬失败点**是 Core：源地址写死在 `scripts/fetch-l2d.mjs:19`（`https://cubism.live2d.com/sdk-web/cubismcore/live2dcubishcore.min.js`），抓不到会 `exit 1`，**后面的模型一个都不下**。模型走 jsdelivr 双镜像，失败只 warn 跳过。

抓不到时的兜底（不动代码）：`index.html:16-17` 的 script 标签已带 `onerror` 自动回退官方 CDN，运行时本来就不致命；要让脚本跑完，手动把 core 放进目标路径再重跑即可——`download()` 会先判 `exists(dest)`，文件已在就直接跳过、根本不发请求：

```powershell
$dst = 'frontend/public/vendor/live2d/core'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
curl.exe -4 -L -o "$dst/live2dcubismcore.min.js" https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js
node scripts/fetch-l2d.mjs
```

自定义模型：整目录丢进 `public/vendor/live2d/models/<id>/`，再在 `models.json` 手工加一行。**加之前先把文件补齐**，否则运行时加载必失败。

> `frontend/public/vendor/` 已在 `.gitignore` 第 27 行（素材授权禁止再分发），每台机器都要跑一次。

---

## 4. GPT-SoVITS

### 4.1 安装（来自 GPT-SoVITS 官网）

仓库内已 vendored `GPT-SoVITS/`，源码与推理配置入库。官网 README 的模型下载指引原文如下：

> 若成功运行 install.sh 可跳过 No.1,2,3
>
> 中国地区的用户可以在此处下载这些模型。
>
> 从 GPT-SoVITS Models 下载预训练模型，并将其放置在 `GPT_SoVITS/pretrained_models` 目录中。
>
> 从 G2PWModel.zip(HF) \| G2PWModel.zip(ModelScope) 下载模型，解压并重命名为 G2PWModel，然后将其放置在 `GPT_SoVITS/text` 目录中。(仅限中文 TTS)

本项目**不使用** UVR5（人声分离）、Faster-Whisper ASR、nltk 语料、ja_userdic 等官网列出的附加项——`tts_service` 的推理链不经过它们。

环境：

```powershell
cd GPT-SoVITS
uv sync
```

### 4.2 TTS 预训练模型

用 TTS 的环境运行下载脚本：

```powershell
# 在 GPT-SoVITS 目录下,用 TTS venv 的解释器
python down-model.py
```

脚本做三件事（均走 `HF_ENDPOINT=https://hf-mirror.com`，幂等，已存在的跳过）：

**① v2 四件**，从 `lj1995/GPT-SoVITS` 拉到 `GPT_SoVITS/pretrained_models/`：

```
chinese-roberta-wwm-ext-large/                                      621 MB
chinese-hubert-base/                                                180 MB
gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt   148 MB
gsv-v2final-pretrained/s2G2333k.pth                                     101 MB
```

**② G2PWModel**，从 `XXXXRT/GPT-SoVITS-Pretrained` 拉 `G2PWModel.zip`，解压重命名到 `GPT_SoVITS/text/G2PWModel/`（含 `g2pW.onnx` 606 MB）。

**③ fast_langdetect 语种模型**，125 MB，放到：

```
GPT-SoVITS/GPT_SoVITS/pretrained_models/fast_langdetect/lid.176.bin
```

跑完的输出应该长这样：

```
Downloading v2 and shared models into: ...\GPT-SoVITS\GPT_SoVITS\pretrained_models
v2 weights, HuBERT and RoBERTa download finished.
G2PWModel already exists; skipping: ...\GPT_SoVITS\text\G2PWModel
Downloading fast_langdetect lid.176.bin ...
fast_langdetect 模型已安装: ...\pretrained_models\fast_langdetect\lid.176.bin
All requested model downloads finished.
```

**三件事一个脚本跑完，不需要手动补任何一项。**

### 4.3 核验（三份权重 + 语种模型）

```powershell
$base = 'GPT-SoVITS\GPT_SoVITS'

Test-Path "$base\pretrained_models\chinese-roberta-wwm-ext-large\pytorch_model.bin"   # 621 MB
Test-Path "$base\pretrained_models\chinese-hubert-base\pytorch_model.bin"             # 180 MB
Test-Path "$base\pretrained_models\gsv-v2final-pretrained\s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt"
Test-Path "$base\pretrained_models\gsv-v2final-pretrained\s2G2333k.pth"
Test-Path "$base\text\G2PWModel\g2pW.onnx"                                          # 606 MB
Get-FileHash "$base\pretrained_models\fast_langdetect\lid.176.bin" -Algorithm MD5     # 01810BC59C6A3D2B79C79E6336612F65
```

六条全过。

### 4.4 手工补 `lid.176.bin`（脚本不可用时）

`lid.176.bin` 这一项以前容易漏——`GPT_SoVITS/text/LangSegmenter/langsegmenter.py:16` 在 import 时把 fast_langdetect 的 detector 整个替换掉，`cache_dir` 写死为项目内那个路径：

```python
fast_langdetect.infer._default_detector = fast_langdetect.infer.LangDetector(
    fast_langdetect.infer.LangDetectConfig(
        cache_dir=Path(__file__).parent.parent.parent / "pretrained_models" / "fast_langdetect"))
```

配上下游两个后果：

- `split_lang/detect_lang/detector.py:15` 硬编码 `model="full"`，**不会**用 fast_langdetect 包内自带的 `lid.176.ftz`，非这个文件不可
- 文件不在时它会自己从 `dl.fbaipublicfiles.com` 现下，而那是在**请求路径里**发生的，国内下不动就每次合成都失败，日志表现为 `pcm_synth_error`
- `FTLANG_CACHE` 环境变量对它**无效**：`infer.py:366` 显示只有显式传 config 才用别的 detector，而 `split_lang` 不传

所以脚本里那一项不是多余的。真的要用不了脚本时（例如换了机器、`down-model.py` 丢了），手工补：

```powershell
$dst = 'GPT-SoVITS\GPT_SoVITS\pretrained_models\fast_langdetect'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
curl.exe -L --retry 5 -o "$dst\lid.176.bin" https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main/pretrained_models/fast_langdetect/lid.176.bin
Get-FileHash "$dst\lid.176.bin" -Algorithm MD5    # 01810BC59C6A3D2B79C79E6336612F65
```

MD5 是 `fast_langdetect/infer.py:215` 的 `VERIFY_FASTTEXT_LARGE_MODEL`，对不上它照样报错。

### 4.5 自检

```powershell
cd GPT-SoVITS
uv run python -m tts_service --port 9002      # 换端口,不与正式服务冲突
```

```powershell
curl.exe -s http://127.0.0.1:9002/ready       # 期望 {"ready":true,...}
```

起得来日志会依次出现（缺任一权重或依赖都会在这里失败）：

```
Loading Text2Semantic weights from GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt
Loading VITS weights from .../s2G2333k.pth. <All keys matched successfully>
Loading BERT weights from .../chinese-roberta-wwm-ext-large
Loading CNHuBERT weights from .../chinese-hubert-base
```

---

## 5. RAG 与检索模型

### 5.1 bge 两个

代码读本地绝对路径（`app/config.py:65` / `:68`），不走 hub，所以 `--local-dir` 必须落到位：

```powershell
cd backend
conda activate test                       # 或任意装了 huggingface_hub 的环境
$env:HF_ENDPOINT = 'https://hf-mirror.com'
hf download BAAI/bge-m3 --local-dir models\bge-m3 --exclude "onnx/*" "imgs/*" "README.md" ".gitattributes"
hf download BAAI/bge-reranker-v2-m3 --local-dir models\bge-reranker-v2-m3 --exclude "onnx/*" "imgs/*" "assets/*" "README.md" ".gitattributes"
```

`--exclude` 去掉 `onnx/` 后每个模型省 2.3 GB（推理走 PyTorch，用不到 ONNX 导出）。

| 模型 | 磁盘 | 显存 | 权重文件 |
|---|---|---|---|
| bge-m3 | 2.2 GB | 2166 MB | `pytorch_model.bin`（**不是** safetensors） |
| bge-reranker-v2-m3 | 2.2 GB | 2166 MB | `model.safetensors` |

`sentence-transformers` 要的 `modules.json`、`1_Pooling/config.json`、`sentence_bert_config.json` 两个仓里都有。

### 5.2 SenseVoice（懒加载，不用手动下）

`app/config.py:148` 是 `ASR_MODEL_ID = "iic/SenseVoiceSmall"`，funasr 首次调 ASR 时自动从 ModelScope 拉 893 MB，落盘位置由 `MODELSCOPE_CACHE` 决定（默认 `C:\Users\<用户>\.cache\modelscope`）。

### 5.3 灌库

```powershell
cd backend
uv run python -m app.rag.ingest
```

本机实测：

```
ingest 完成: case ← data/rag_case_corpus.jsonl → 14944 条(.rag_store/)
自检 [case|...] → conv_01452(1.00), conv_02827(1.00), conv_01355(1.00)
ingest 完成: knowledge ← data/rag_knowledge_corpus.jsonl → 1022 条(.rag_store/)
自检 [knowledge|什么是冥想？] → knowledge_1(1.00), knowledge_4(0.95), knowledge_3(0.34)
```

自检那两行是脚本自带的回验判据（`rag/ingest.py:60-64`）：拿语料首条检索自己，case 命中自身 1.00 说明嵌入与写入链路通。

`.rag_store/` 约 200 MB，`ingest` 重建，不入库。

### 5.4 预生成音频

TTS 服务 `/ready` 返回 200 **之后**才跑（早跑会对着还没加载完的引擎生成）：

```powershell
cd backend
uv run python -m app.voice.fillers
```

生成等待语音、情绪回执、危机话术等固定话术的 wav，落在 `data/fillers/`（幂等，删目录重跑即可）。不入库，每台机器都要跑。

危机话术（P10/P11）走的就是这批预置 wav：`ws_gateway/gateway.py:655` 的注释写明「缺文件/发送失败记 degraded 跳过——音频缺席不影响文字链路」。所以**没跑 fillers 时，危机路径只有文字没有声音**。

---

## 6. 启动

### 6.1 单命令启动（当前实现）

```powershell
cd backend
uv run hrp
```

`TTS_SERVICE_SPAWN=1`（默认）时，backend 的 lifespan 会自己拉起 `GPT-SoVITS` 的 tts_service 子进程。**不用另开终端手工起 TTS。**

另开一个终端起前端：

```powershell
cd frontend
npm run dev
```

### 6.2 启动时间线

下面是 `uv run hrp` 实测的一条完整时间线（冷机、无其他负载）：

```
02:10:24  startup_begin → startup_ready · 文字链路已就绪        < 1s,服务此刻已可接请求
02:10:24  tts_spawned        pid=<壳进程>  cwd=…\GPT-SoVITS
02:10:24  rag_warm_begin / llm_catalog_warm_begin / tts_remote_warm_begin
02:10:42  llm_catalog_warm_ready                              18s
02:11:10  tts_remote_warm_ready                               46s   < TTS 模型加载完
02:11:14  rag_warm_ready                                      50s
```

期间**零 WARN、零 ERROR、零 `event_loop_lag`**。

**TTS 那 46 秒里发消息是可以的**，只是没有声音（走 TTS 降级），文字链路不受影响。超时 60 秒只记 `tts_remote_warm_failed` WARN，backend 不退出；子进程在自己那边继续加载，下一回合自动恢复语音。

权重已进系统页缓存后，同一条命令的 `tts_remote_warm_ready` 实测 **13.2 秒**。

### 6.3 日志分三处

```
backend/logs/debug_YYYY-MM-DD.log          backend 自己的,结构化 JSON(轮转 10MB / 30 天)
GPT-SoVITS/logs/tts_service_YYYY-MM-DD.log tts_service 的 logger(同上)
GPT-SoVITS/logs/tts_service_stdout.log     子进程 stdout/stderr 原始流 ← 出错看这个
```

**为什么需要第三个文件**：`tts_service` 自己的 logger 已经是双输出（终端 + 它的 log 文件），但**上游 GPT-SoVITS 的 `print` 不走 loguru**——这些内容只在进程输出流里。实测（`uv run hrp` 拉起 + 真合成一次）的对照：

| 内容 | 来源 | 在 `tts_service_*.log`？ | 在 `tts_service_stdout.log`？ |
|---|---|---|---|
| `starting · hrp-tts-gpt-sovits …` | tts_service loguru | ✅ | ✅ |
| `request_done` / `pcm_synth_error` / `v2_stream_done` | tts_service loguru | ✅ | ✅ |
| `Loading CNHuBERT weights from …` | 上游 `print` | ❌ | ✅ |
| `Loading Text2Semantic weights from …` | 上游 `print` | ❌ | ✅ |
| `Loading VITS weights from … <All keys matched successfully>` | 上游 `print` | ❌ | ✅ |
| `ModuleNotFoundError` / `ImportError` traceback | stderr | ❌ | ✅ |
| `fast-langdetect: Downloading model…` | 第三方 logger → stderr | ❌ | ✅ |
| huggingface_hub / jieba / onnxruntime 的 warning | stderr | ❌ | ✅ |
| `ConnectionResetError: [WinError 10054]`（`proactor_events.py`） | asyncio 默认异常处理器 | ❌ | ✅ |

排查权重缺失、依赖缺失时最想看的那三行 `Loading … weights`，全在第三个文件里——**没有它就只能看 backend 终端，而默认配置下 backend 终端里根本不会出现这些行**。

> 曾经误以为推理期的进度条输出（`curr_ptr` / `infrq` / `rps`）也会落在这里。**实测真合成后这几个关键字 0 命中**，本机这套配置下它们不打印，所以不写进上表。

实时跟：

```powershell
Get-Content GPT-SoVITS\logs\tts_service_stdout.log -Wait -Tail 20
```

不缓冲追加写（handler 每行 flush），重启追加不覆盖。**超 10 MB 轮转**，留 3 份：

```
GPT-SoVITS/logs/tts_service_stdout.log       当前
GPT-SoVITS/logs/tts_service_stdout.log.1     ← 上一份
GPT-SoVITS/logs/tts_service_stdout.log.2
GPT-SoVITS/logs/tts_service_stdout.log.3
```

调 `.env` 的 `TTS_SERVICE_STDOUT_MAX_BYTES` / `TTS_SERVICE_STDOUT_BACKUP_COUNT`。

> **为什么不是「子进程直接写文件」**：那样最省事，但轮转做不到。
> `logging.handlers.RotatingFileHandler` **没有 `fileno()`**，`Popen(stdout=handler)` 直接
> `AttributeError`；就算传它内部的 stream，轮转判定只写在 `emit()` 里，而子进程是
> **直接往 fd 写字节**、不经过 `emit()`，永远不会触发轮转。
> 所以实现是：子进程写 `PIPE` → 父进程后台线程抽水 → 经 `RotatingFileHandler` 落盘。
> 实测把上限压到 4 KB：主文件 2156 B、切出 `.1` 3989 B（刚好卡在上限下），内容跨切点完整。

**默认子进程输出不进 backend 终端**（`TTS_SERVICE_STDOUT_TO_CONSOLE=0`）。调试时想实时看：

```powershell
# .env
TTS_SERVICE_STDOUT_TO_CONSOLE=1
```

### 6.3.1 日志编码：必须钉死 UTF-8

`backend` 通过 `PYTHONIOENCODING` 把子进程 stdio 的编码**钉成 utf-8**，父进程抽水时按**同一个值**解码——两边绑在 `TTS_SERVICE_PYTHONIOENCODING` 一个配置项上，不会漂移。

不定死会怎样：Windows 上子进程 stdout 默认跟本机 ANSI 代码页走（本机 `ACP=936` → `gbk`），而父进程按 UTF-8 解码，`·` 的 GBK 字节 `A1 A4` 会解成**两个 U+FFFD**，中文全废。实测修前：

```
修前  starting <FFFD><FFFD> hrp-tts-gpt-sovits      U+FFFD ×2
修后  starting · hrp-tts-gpt-sovits                  U+FFFD ×0
字节  73 74 61 72 74 69 6E 67 20 C2 B7 20 ...      ← C2 B7 正确还原
```

这一条同时让日志**与机器语言/代码页无关**，换机器也一致。

### 6.4 backend 终端看得见的日志

```
startup_ready · 文字链路已就绪                      ← 0.3s,服务可用
tts_spawned · pid=… cwd=…\GPT-SoVITS url=http://127.0.0.1:9001 stdout_log=logs/tts_service_stdout.log
llm_catalog_warm_begin → llm_catalog_warm_ready
rag_warm_begin → rag_warm_ready
tts_remote_warm_ready · 远程 TTS 已就绪(http://127.0.0.1:9001, 35.2s)
```

### 6.5 健康判据

**看监听，不要看进程在不在**：

```powershell
netstat -ano | findstr :8000
```

要看到 `LISTENING`。如果只有 `ESTABLISHED` 没有 `LISTENING`，见 §9.1。

REST 探活打真路由，不要打 `/health`——**这个项目没有 `/health` 路由**，打它必然 404，跟监听好坏无关：

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/openapi.json      # 期望 200
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/admin/trends        # 期望 200
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:9001/ready               # 期望 200
```

实测健康态下 18 条路由的响应分布正确：`200`（GET 可用）/ `405`（GET 打 POST-only 路由，方法不符）/ `422`（缺必填查询参数）。**只有「全部 404」才是监听死了**，见 §9.1。

### 6.6 关停：为什么必须 `taskkill /T`

uv 建的 venv 里，`.venv\Scripts\python.exe` **不是解释器本体，是一个 262 KB 的重定向启动器**。所以 `spawn()` 拿到的那一层 pid 是个空壳，真干活的是它的子进程。实测一次 `spawn()` 的完整子树是**三层**：

```
46520  GPT-SoVITS\.venv\Scripts\python.exe -m tts_service   ← spawn() 拉起的,4 MB
  └─ 24580   真解释器 uv\python\cpython-3.12.14\python.exe   2600+ MB,持有 :9001 与全部显存
      └─ 29928  ……还有一层
```

**如果 `stop()` 只对 `46520` 调 `terminate()`**，`24580` 会变成孤儿继续跑：占着 2.6 GB 显存、占着 `:9001`、`_proc.poll()` 却报告「已退出」。所以 `tts_service_process.stop()` 走的是 `taskkill /T /F /PID <pid>`（杀整棵树），非 Windows 才退回 `terminate → wait → kill`。

实测（`stop()` 完整跑通）：

```
spawn: 壳=46520 后代=[24580, 29928]   /ready OK 13.2s   :9001 LISTENING=True
stop(): 0.19s
  日志句柄已关闭 = True          句柄随 stop() 显式关闭,不是等 GC
  taskkill /T 干掉 = [24580, 29928, 46520]   漏网 = 无
  :9001 LISTENING = False
```

### 6.7 手工起 TTS（不自动拉起时）

```powershell
# .env 里设 TTS_SERVICE_SPAWN=0，然后：
cd GPT-SoVITS
uv run python -m tts_service
```

---

## 7. 显存预算

本机实测（`nvidia-smi`，总计 8188 MiB）：

| 组件 | 显存 | 何时加载 |
|---|---|---|
| bge-m3 | 2166 MB | 启动预热（RAG） |
| bge-reranker-v2-m3 | 2166 MB | 启动预热（RAG） |
| GPT-SoVITS tts_service | ~1.6 GB | 启动即加载 |
| SenseVoiceSmall | 893 MB | **首次发语音时** |
| **合计** | **~6.8 GB** | 余量约 1.2 GB |

设备日志实证：

```
sentence_transformers.SentenceTransformer:__init__:211 - Use pytorch device_name: cuda:0
sentence_transformers.cross_encoder.CrossEncoder:__init__:224 - Use pytorch device: cuda:0
```

ASR 走 CUDA 的依据：`asr.py:42` 的 `AutoModel(model=…, disable_update=True)` 不传 `device`，funasr 在 `auto/auto_model.py:564` 取默认 `"cuda"`，仅当 `torch.cuda.is_available()` 为假才回落 CPU。

CPU 侧的部分：Chroma 的 HNSW 检索与 BM25+jieba 分词、LiteLLM 调用（纯网络）、ffmpeg 转码、tokenize 与 numpy 后处理。

### 处置

余量只剩 1 GB 时，按性价比排：

| 手段 | 收益 | 代价 |
|---|---|---|
| reranker 挪 CPU（`app/rag/engine.py:353` 加 `device="cpu"`） | 省 2166 MB | 重排慢百来毫秒，排序质量不变 |
| bge 两个转 fp16 | 省约 2.1 GB | 余弦相似度变化，需 `--reset` 重灌并重验检索质量 |
| 灌库时限制 batch（`engine.py:414` 补 `batch_size=8`） | 压低灌库瞬时峰值 | 只影响灌库，日常对话用不到 |

**CUDA 没有按需分页机制。** 显存不足的表现是 `torch.OutOfMemoryError` 直接抛，以及分配器为腾挪缓存块做设备同步产生的卡顿尖峰——后者常被误认为"换页"。要确认是否真在共享内存，看任务管理器 GPU 行的「CUDA」引擎下「共享 GPU 内存」是否为 0。

---

## 8. 换机器重建

入库的是两个文本文件对：`pyproject.toml` + `uv.lock` + `.python-version`。`.venv` 不入库（`.gitignore`），每台机器各自构建。

### 8.1 常规路径

见 §1.1 路线 B（无 wheel）与路线 A（有 wheel）。此处不重复，只补一点：`uv.lock` 入库后，别人 clone 下来跑 `uv sync` 装出来的版本与你逐字节一致，包括 `torch==2.6.0+cu124` 这个 CUDA 变体——这是 `requirements.txt` 给不了的（它不钉传递依赖，也不记 CUDA 变体）。

### 8.2 uv 环境与原 conda 环境的差异（重要，别误读）

`uv.lock` **不等于**原来的 conda 环境，两者逐包比对结果：

| | 完全一致 | 仅补丁/微版不同 | ★ 次版本不同 | ★★ 跨大版本 |
|---|---|---|---|---|
| backend | 131 | 17 | 20 | **3** |
| GPT-SoVITS | 109 | 1 | 8 | **3** |

跨大版本的六处：

```
backend     kubernetes    37.0.1 ← 36.0.3      oauthlib     4.0.0 ← 3.3.1
            pycryptodome   4.0.0 ← 3.23.0
GPT-SoVITS  markupsafe     3.0.4 ← 2.1.5      setuptools  84.0.0 ← 83.0.0
            multidict      7.1.0 ← 6.9.1
```

**原因**：`pyproject.toml` 里 26 条（backend）/ 55 条（GPT-SoVITS）**直接依赖全部 `==` 钉死，与 conda 基线零漂移**；但**传递依赖由 uv 重新解析成「当时最新兼容版」**，不是 conda 里那些旧补丁号。

**这不等于环境不可用**——实测两套都通过：

```
uv run pytest           241 passed, 25 skipped        （与 conda 环境完全相同的数字）
torch CUDA              backend 2.12.1+cu126 / TTS 2.6.0+cu124，均 cuda:True
TTS 真合成              POST /v1/tts/stream → 200，32kHz/mono，RMS 9.1%，非静音 53.9%
```

要精确复刻某个历史环境，得把传递依赖也钉进 `pyproject.toml`；本项目选择只钉直接依赖 + 提交 lock，理由是 lock 已经保证了「往后每次 `uv sync` 结果一致」。

### 8.3 torch 必须走 PyTorch 索引

Windows 上 **PyPI 的 torch 是 CPU 版**：

| | 大小 |
|---|---|
| `torch==2.6.0` win_amd64（PyPI） | 195 MB |
| `torch==2.6.0+cu124` win_amd64（pytorch 索引） | 2415 MB |

且 torch 的 `nvidia-*` 依赖全部带 `platform_system == "Linux"` 条件，Windows 上一个都装不上。所以 `pyproject.toml` 里必须声明：

```toml
[[tool.uv.index]]
name = "pytorch-cu126"
url = "https://download.pytorch.org/whl/cu126"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cu126" }
torchaudio = { index = "pytorch-cu126" }
```

装成无后缀的 `2.6.0`（而不是 `2.6.0+cu124`）就说明拿到的是 CPU 版。**静默降级，不报错**，`torch.cuda.is_available()` 才会露馅。

### 8.4 网络差时的兜底

实测 `download.pytorch.org` 持续速度约 **2.02 MB/s**（五段 40 MB，波动 1.31~3.91），torch 一个 2.4 GB → 约 20 分钟。网络更差时先从本地 wheel 装，`uv sync` 不会覆盖已满足 lock 的版本：

```powershell
uv pip install --python .venv `
  --default-index https://pypi.tuna.tsinghua.edu.cn/simple `
  --find-links <wheel目录> "torch==2.12.1+cu126" "torchaudio==2.11.0+cu126"
uv sync
```

注意：**不要加 `--no-index`**——那会把传递依赖（sympy 等）一起断掉，报 `no version of sympy==1.13.1`。只加 `--find-links` 即可；`+cuXXX` 这个版本号 PyPI 上不存在，不存在误取 CPU 版的风险。

`uv.lock` 里 torch 的 `source` 记的是官方索引，所以这个兜底只影响本机安装方式，不影响 lock 的可移植性。

### 8.5 完整 fresh-clone 清单

| 需要什么 | 怎么来 | 耗时 |
|---|---|---|
| Python 环境 | `uv sync` ×2 | torch 各约 20 分钟（一次性，之后 uv 缓存命中） |
| 前端 | `npm ci` + `npm run l2d:fetch` | 约 2 分钟 |
| 系统依赖 | ffmpeg、Redis 自行安装 | — |
| 配置 | `copy .env.example .env` → 填 `DEEPSEEK_API_KEY` | — |
| TTS 权重 | `python down-model.py` + 补 `lid.176.bin` | 约 10 分钟 |
| bge 两个 | `hf download --local-dir` | 约 20 分钟 |
| SenseVoice | 首次发语音自动下 | — |
| RAG 库 | `uv run python -m app.rag.ingest` | 约 5 分钟 |
| fillers | TTS ready 后 `uv run python -m app.voice.fillers` | 约 1 分钟 |

---

## 9. 排障

### 9.1 聊天正常但所有 REST 接口打不开

**最隐蔽的一个故障。** 进程活着、日志在写、WebSocket 对话完全正常，但新建 HTTP 连接一律被拒。

```
netstat LISTENING 命中 :800*   →  0 条      监听套接字消失
netstat ESTABLISHED            →  有        旧 WebSocket 仍存活
curl 连接耗时                  →  0.000000s 立即 RST,不是超时
```

成因链：

```
首次 LLM 调用在事件循环上做约 20 秒的同步工作
  → Windows asyncio 的 IOCP 待 accept 操作作废
  → CPython asyncio/proactor_events.py:849 执行 sock.close()
     且该回调链不重新 arm、无重试
  → 监听能力永久失效,直到进程重启
```

已建立连接与监听套接字是两个独立对象，TCP 四元组建立后即持有引用，所以关掉监听不影响已建立的 WebSocket——这正是"对话正常但接口全废"这一反常现象的成因。

**现在已规避**：`app/main.py` 的 `_warm_llm_catalog()` 在 lifespan 里用 `asyncio.create_task` + `asyncio.to_thread` 把 litellm 的首次导入挪出事件循环（实测 13~19 秒完成，全程 `event_loop_lag` 不报警）。

复发判据：日志出现 `event_loop_lag` 且 `lag_s` 很大。阈值是 `main.py:133` 的 `lag > 2`，故意设得敏感。**`lag_s` 与是否崩不是硬阈值关系**——实测 23.49 秒那次没崩（发生在 RAG 预热，纯计算），20.43 秒那次崩了（发生在 aiohttp 建连接的路径上）。长阻塞是危险信号，尤其当它发生在碰 socket 的代码路径上。

兜底处置：`netstat -ano | findstr :8000` 确认，然后重启 backend。

### 9.2 TTS 依赖缺失（本机踩过的全部）

推理链上有几个"看着像训练专用、实际跑不掉"的依赖，漏一个就是 import 时炸：

| 缺什么 | 谁 import 它 | 报错形态 |
|---|---|---|
| `matplotlib` | `AR/modules/lr_schedulers.py:6` ← `AR/models/t2s_lightning_module.py:14` | `ModuleNotFoundError: No module named 'matplotlib'` |
| `x-transformers` | `f5_tts/model/backbones/dit.py:16` | `ModuleNotFoundError: No module named 'x_transformers'` |
| `pillow` `pandas` `chardet` `jieba` `einx` `frozendict` `torch-einops-utils` `fasttext-predict` `defusedxml` `coloredlogs` `wordsegment` `orjson` `pytz` `rich` | 各自模块顶层 | 同上 |

定位方法（比逐个试快）：在两个环境里 import 同一条推理链，再 diff 各自 `sys.modules` 的第三方模块集合。

```python
import os, sys
ROOT = r"...\GPT-SoVITS"
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "GPT_SoVITS"))
from tools.i18n.i18n import I18nAuto; I18nAuto()
import GPT_SoVITS.TTS_infer_pack.TTS   # 成功即链路通
```

### 9.3 误判清单（曾经浪费时间的方向）

| 现象 | 当时的猜测 | 实际 |
|---|---|---|
| `ModuleNotFoundError: No module named 'litellm'` | — | 环境里装的是 `litellm` 不是 `litellm-core`，而 `provider.py:3` 注释写的是 core |
| onnxruntime 1.20.2 没有 `preload_dlls()` | 会 AttributeError | `text/g2pw/onnx_api.py:23-26` 是 `try/except: pass`，包着的 |
| `_BACKEND_DIR/..` 到不了项目根 | 层级错 | `_BACKEND_DIR = backend/`，一层 `..` 正好到仓库根 |
| 父进程 `PYTHONPATH` 会污染子进程 torch | 版本冲突 | 子进程解释器是绝对路径，`sys.path` 不跨进程传染；真风险在 PATH 顺序 |
| TTS 日志里 `ConnectionResetError: [WinError 10054]`，栈底是 `asyncio/proactor_events.py` 的 `_call_connection_lost` → `self._sock.shutdown()` | 监听又死了 | **不是**。backend 的 `wait_ready` 每秒探一次 `/ready` 后粗暴断连，服务端 proactor 对已重置的套接字再 `shutdown()` 就报它。它以 `ERROR` 级别打到日志，但服务随后照常加载完并返回 200。一次实测只出现 1 次。判断依据是同文件里 `/ready` 的响应码从 `503` 翻到 `200` |
| `uv run pytest` 报 6 个 warning | 我们代码有问题 | 全是第三方的：jieba 的 `re.compile("([a-zA-Z0-9]+(?:\.\d+)?%?)")` 转义告警 + `pkg_resources is deprecated` |

### 9.4 其他

| 现象 | 原因 | 处置 |
|---|---|---|
| `GET /health → 404` | backend 无此路由（该端点在 TTS 服务上是 `/v1/health`） | 无害，外部探针在轮询。判健康请用 §6.5 的真路由 |
| 前端立绘不出来 | `l2d:fetch` 没跑，或 Core 没抓到 | 见 §3 |
| 危机路径只有文字没声音 | `data/fillers/` 空 | 见 §5.4 |
| `uv sync` 报 `拒绝访问(os error 5)` | 有进程占着 venv 的 `.pyd`（多半是残留的 TTS） | 停掉占用进程后重跑；必要时删 `site-packages` 下对应目录 |
| 显存不足 | 见 §7 | 按表处置 |
| 日志里中文/符号变成 `?` 或 `�` | 子进程 stdio 跟本机 ANSI 代码页走（cp936 → gbk），父进程按 UTF-8 解码 | 确认 `TTS_SERVICE_PYTHONIOENCODING=utf-8` 生效，见 §6.3.1 |
| `GPT-SoVITS\logs\tts_service_stdout.log` 一直涨 | 超过 `TTS_SERVICE_STDOUT_MAX_BYTES` 会轮转，只留 `BACKUP_COUNT` 份 | 调大上限，或调小份数；旧文件手工清 |

---

## 10. 与 option.md 的差异

本文不替代 `option.md`，两者定位不同：

| | option.md | 本文 |
|---|---|---|
| 定位 | 原手册 | 并行版本，不覆盖 |
| TTS | 写的是另一套 TTS sidecar 的安装配置 | 已移除该部分，全文只讲 GPT-SoVITS |
| 进程模型 | backend 与 TTS 分开起 | backend 自动拉起 TTS 子进程 |
| 环境管理 | 无 | 两个 uv venv + lock |
| matplotlib | — | `==3.11.2`，取自 conda 基线（3.11.2 要求 numpy>=1.25，本环境 1.26.4 满足） |
| 数字 | — | 全部为本机实测值 |

后续若确认本文为唯一有效路径，再决定 `option.md` 的去留。
