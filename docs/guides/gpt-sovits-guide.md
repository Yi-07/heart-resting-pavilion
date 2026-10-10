---
title: GPT-SoVITS TTS 服务说明
section: guides
last_updated: 2026-10-09
---

# GPT-SoVITS TTS 服务说明

> **读者**:本项目开发者。说明这套 GPT-SoVITS 与主服务之间的接口、启动方式、核心链路与故障排查。

---

## 1. 这是个什么东西

它是一个**独立的 FastAPI TTS 微服务**，把 GPT-SoVITS 的推理能力包成了标准的 HTTP 接口。
主服务通过 HTTP 调它合成语音，而不是自己加载 AI 模型。

---

## 2. 启动方式

```powershell
python -m tts_service
```

默认绑定 `127.0.0.1:9001`。

可选参数：

```powershell
python -m tts_service --host 0.0.0.0 --port 9880 --voice yilai
```

---

## 3. 端点列表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/live` | 进程存活，不动模型 |
| GET | `/ready` | 模型就绪才返回 200，否则 503 |
| GET | `/v1/health` | 详细健康：端口、模型名、GPU 状态 |
| GET | `/metrics` | Prometheus 指标 |
| POST | `/v1/tts/stream` | **legacy**：逐句产出整句 WAV |
| POST | `/v2/tts/stream` | **realtime**：逐块产出 PCM16 |
| POST | `/v1/tts/cancel` | round 级打断 |

---

## 4. 请求/响应格式

### 4.1 legacy 合成请求（`/v1`）

```http
POST /v1/tts/stream
Content-Type: application/json
X-Request-ID: r-123

{"text": "你好，今天天气不错。", "voice": "yilai"}
```

- `text`：**必须纯中文**，含英文字母会直接返回 400
- `voice`：可选，对应 `reference/<name>.wav`
- `X-Request-ID` 当作 `round_id` 用，打断时用同一个值

**legacy 契约不要求 body 里带 `round_id`** —— 那是 `/v2` 才引入的规则，
不要用 v2 的要求去校验 v1 的调用方。

### 4.2 legacy 响应（NDJSON）

每行一个 JSON，每行是一个完整的 wav 文件（base64 编码）：

```json
{"wav": "xxxx...", "round_id": "r-123"}
```

如果出错：

```json
{"error": "text contains ASCII characters", "code": "ascii_unsupported"}
```

### 4.3 realtime 合成请求（`/v2`）

```http
POST /v2/tts/stream
Content-Type: application/json
X-Request-ID: r-123

{"text": "你好，今天天气不错。", "voice": "", "round_id": "r-123"}
```

**强制 `X-Request-ID == body.round_id`**。不一致直接 400 `round_id_mismatch`，
**不进入推理**。理由不是形式主义：打断是按 `round_id` 命中的，两处给不同的值，
打断要么打不中（排队继续出声），要么打中别人（跨 round 误伤）。

### 4.4 realtime 响应（NDJSON）

音频块（裸 PCM16，无 WAV 头，base64 编码）：

```json
{"type": "audio", "round_id": "r-123", "seq": 0, "sentence_index": 0,
 "sample_rate": 32000, "channels": 1, "format": "pcm_s16le", "pcm": "xxxx..."}
```

控制帧：

```json
{"type": "sentence_end", "round_id": "r-123", "sentence_index": 0}
{"type": "end", "round_id": "r-123"}
{"type": "cancelled", "round_id": "r-123"}
{"type": "error", "round_id": "r-123", "code": "synth_failed", "message": "..."}
```

- `end` 与 `cancelled` **互斥**
- `seq` 从 0 开始，在**一个 round 内**单调递增、跨句连续、不跳号、不重号
- PCM 固定 `32000 Hz / 单声道 / pcm_s16le`（小端、交错）

---

## 5. 核心链路（调用顺序）

### 5.1 legacy（`/v1`，整句交付）

```
POST /v1/tts/stream
  ↓
server.py 读取请求、做基础校验
  ↓
engine.py.guard()  —— 输入守卫（长度、空文本、ASCII 禁用、句数上限）
  ↓
engine.py.synthesize()  —— 逐句合成，整句齐了才交
  ↓
engine.py._build_req()  —— 准备模型需要的参数
  ↓
TTS_infer_pack.TTS.run()  —— 真正推理
  ↓
TextPreprocessor  →  AR 文本到语义 token  →  vits/vocoder 生成音频
```

---

## 6. 关键类与文件

| 类/文件 | 职责 |
|---|---|
| `tts_service/server.py` | FastAPI 层，端点、中间件、指标 |
| `tts_service/engine.py` | 推理引擎：加载、守卫、串行、打断 |
| `GPT_SoVITS/TTS_infer_pack/TTS.py` | 实际的语义 token + vocoder 推理 |
| `GPT_SoVITS/module/models.py` | VITS/SynthesizerTrn 等模型定义 |
| `GPT_SoVITS/AR/models/t2s_model.py` | 文本到语义 token 的 AR 模型 |
| `GPT_SoVITS/BigVGAN/bigvgan.py` | v3/v4 的波形合成器 |
| `GPT_SoVITS/text/` | 文本清洗、切分、g2p 预处理 |

---

## 7. 版本差异（简单版）

| 版本 | 关键特征 | 输出采样率 |
|---|---|---|
| v1 | 最旧 | 24k |
| v2 | 稳定版 | 32k |
| v3 | 更高音色相似度 | 24k |
| v4 | 修复 v3 金属音 | 48k |
| v2Pro/v2ProPlus | v2 基础上加强 | 24k/48k |

---

## 8. 已知坑

1. **ASCII 英文字母会返回 400**  
   当前 `g2p_en` 缺 `nltk cmudict`，任何英文字符都会导致 `LookupError` 卡 12s，所以在入口就拦截。

2. **v3/v4 流式自动回退**  
   V3/V4 的 `TTS.py` 不支持流式，会自动改成 `return_fragment=True`（分片返回）。

3. **严格串行**  
   `SynthesizerTrn`/`SynthesizerTrnV3` 共享 prompt_cache，必须逐请求串行，不能多线程并行合成。

4. **打断靠 token，不杀线程**  
   如果直接杀线程，CUDA 同步会漏掉，显存可能无法释放。

5. **chunk 级打断不中断在跑的那一块**  
   `/v1` 与 `/v2` 都是 **chunk 级**：取消命中后不再开始新的 chunk，
   但已经在跑的那个 chunk 会跑完才停。最坏延迟约等于一个 chunk 的时长
   （实测 P50 2ms / P90 744ms）。这是设计选择，不是 bug。

6. **进程 cwd 必须是 GPT-SoVITS 根目录**  
   `tts_infer.yaml` 里的权重路径、参考音频路径全��相对路径。
   `python -m tts_service` 会在进程入口 chdir 到仓库根 —— 这不是 `engine.load()`
   在后台线程里做的（那种做法会让「哪个线程碰文件系统」变成不确定行为）。

---

## 9. 排查清单

| 症状 | 可能原因 |
|---|---|
| `/ready` 不通 | 模型加载失败，查看后台日志 |
| 合成很慢 | GPU 被占满或串行队列过长 |
| 音频有金属音 | v3 已知问题，建议换 v4 |
| 收到 400 ASCII 错误 | 文本里有英文字母，去掉或替换成中文 |
| 收到 400 `round_id_mismatch` | `/v2` 的 `X-Request-ID` 与 `body.round_id` 不一致 |
| 收到 503 `queue_wait_timeout` | 前一个回合还在跑；等它结束或先 cancel |

---

## 10. 如何在主服务里关闭/切换

如果你想暂停这个 TTS 服务：

```powershell
# 停掉正在跑的 python -m tts_service 进程即可
```

如果你的主服务要换回内置模式，把 `TTS_MODE` 环境变量改成 `local`
（此时主服务走 CosyVoice sidecar，不经过本文档这套接口）。

---

## 11. benchmark

埋点默认关闭。开启后事件落 `temp/bench/*.jsonl`：

```powershell
# 服务侧
$env:TTS_BENCH=1; python -m tts_service

# 打流并聚合
python temp/bench_tts.py --scenario multi --n 20 --rounds 3
python temp/bench_compare.py            # 拼时间线 + 出 bench_compare.md
```

事件名是冻结契约，两端（服务 / 主服务 / 浏览器）必须逐字相同，
否则拼不出跨进程时间线。最近一次完整结果见 `temp/BENCH_REPORT.md`。
