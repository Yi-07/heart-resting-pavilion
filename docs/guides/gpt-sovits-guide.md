---
title: GPT-SoVITS TTS 服务说明
section: guides
last_updated: 2026-10-08
---

# GPT-SoVITS TTS 服务说明

> **读者**:本项目开发者。说明这套 GPT-SoVITS 与主服务之间的接口、启动方式、核心链路与故障排查。

---

## 1. 这是个什么东西

它是一个**独立的 FastAPI TTS 微服务**，把 GPT-SoVITS 的推理能力包成了标准的 HTTP 接口。
主服务通过 HTTP 调它合成语音，而不是自己加载 AI 模型。

**它不在本仓库源码里**，源码在：

```text
E:\aic-project\GPT-SoVITS
```

---

## 2. 启动方式

```powershell
# 在源码仓库根目录下
cd E:\aic-project\GPT-SoVITS

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
| POST | `/v1/tts/stream` | 流式合成语音 |
| POST | `/v1/tts/cancel` | 打断当前合成 |

---

## 4. 请求/响应格式

### 4.1 合成请求

```http
POST /v1/tts/stream
Content-Type: application/json
X-Request-ID: r-123

{"text": "你好，今天天气不错。", "voice": "yilai"}
```

- `text`：**必须纯中文**，含英文字母会直接返回 400
- `voice`：可选，对应 `reference/<name>.wav`

### 4.2 响应（NDJSON）

每行一个 JSON，每行是一个完整的 wav 文件（base64 编码）：

```json
{"wav": "xxxx...", "round_id": "r-123"}
```

如果出错：

```json
{"error": "text contains ASCII characters", "code": "ascii_unsupported"}
```

---

## 5. 核心链路（调用顺序）

```
POST /v1/tts/stream
  ↓
server.py 读取请求、做基础校验
  ↓
engine.py.guard()  —— 输入守卫（长度、空文本、ASCII 禁用、句数上限）
  ↓
engine.py.synthesize()  —— 逐句合成
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

---

## 9. 排查清单

| 症状 | 可能原因 |
|---|---|
| `/ready` 不通 | 模型加载失败，查看后台日志 |
| 合成很慢 | GPU 被占满或串行队列过长 |
| 音频有金属音 | v3 已知问题，建议换 v4 |
| 收到 400 ASCII 错误 | 文本里有英文字母，去掉或替换成中文 |

---

## 10. 如何在主服务里关闭/切换

如果你想暂停这个 TTS 服务：

```powershell
# 停掉正在跑的 python -m tts_service 进程即可
```

如果你的主服务要换回内置模式，把 `TTS_MODE` 环境变量改成 `local`。
