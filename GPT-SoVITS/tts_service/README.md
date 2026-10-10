# tts_service —— GPT-SoVITS 远程 TTS 服务

与 `api_v2.py` 同级。作为 `backend/app/voice/tts_service`（CosyVoice 实现）的**可替换件**：
端口、端点、线格式、环境变量全部一致，主服务零配置改动，切换 = 停旧起新。

## 启动

```bash
cd <仓库根>/GPT-SoVITS

python -m tts_service                  # 127.0.0.1:9001
python -m tts_service --port 9880      # 换端口
python -m tts_service --host 0.0.0.0   # 对外
python -m tts_service --voice yilai    # 换音色
python -m tts_service --check          # 只跑输入守卫自检，不加载模型、不占显存
```

模型在后台线程加载，约 30~45 s；加载完 `/ready` 才返回 200。**不要开多 worker**——
单实例独占约 3.9~4.4 GiB 显存，8GB 卡装不下两份，且会破坏引擎内的串行保证。

用到的解释器：`D:\miniconda3\envs\digitai_man\python.exe`（GPT-SoVITS 自己的 conda 环境）。

## 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/live` | 进程存活，恒 200 |
| GET | `/ready` | 模型就绪；200 就绪 / 503 未就绪 |
| GET | `/v1/health` | 详细状态（含引擎快照：在跑哪些回合、计数器） |
| POST | `/v1/tts/stream` | NDJSON 流式合成 |
| POST | `/v1/tts/cancel` | 打断回合 |
| GET | `/metrics` | Prometheus |

认证：`SERVICE_AUTH_TOKEN` 非空时，除 `/live` `/metrics` `/ready` 外都要
`Authorization: Bearer <token>`，否则 401。

### POST /v1/tts/stream

请求体：

```json
{ "text": "我们先不急着解决什么，就从今晚开始，选一件最小的事做一做。", "voice": null }
```

- `text` 必填，**仅中文**（见下方"已知限制"）
- `voice` 可选，临时指定音色名（对应 `reference/<name>.wav`），不传用默认音色

响应 `application/x-ndjson`，**每行一个完整 wav 文件**：

```
{"wav":"<base64 的完整 RIFF/PCM wav>","round_id":"r1712..."}
{"wav":"<base64>","round_id":"r1712..."}
```

出错时同一行给（HTTP 状态码仍是 200）：

```
{"error":"...","code":"synth_failed","round_id":"r1712..."}
```

请求标识走 `X-Request-ID` 头，**同时充当 `round_id`**，打断时用同一个值：

```bash
curl -N -X POST http://127.0.0.1:9001/v1/tts/stream \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: r-001' \
  -d '{"text":"我在的。"}'
```

### POST /v1/tts/cancel

```json
{ "round_id": "r-001", "cascade": true }
```

- `cascade: true`（默认）**同时清空所有尚未开始的排队回合**
- 幂等：回合已结束或从未存在也返回 200

```json
{"round_id":"r-001","cancelled":true,"state":"cancelled","cascaded":["r-002"]}
```

`state` ∈ `running` / `queued` / `cancelled` / `finished` / `not_found`。

打断语义：正在合成的那一句**直接丢弃半句**，不把旧音频漏出去；排队中的回合不启动。

### 错误码

| code | HTTP | 含义 |
| --- | --- | --- |
| `empty_text` | 400 | text 为空或纯空白 |
| `ascii_unsupported` | 400 | text 含 ASCII 英文字母 |
| `text_too_long` | 400 | 超长（默认 2000 字符） |
| `too_many_sentences` | 400 | 分句数超限（默认 60 句） |
| `auth_failed` | 401 | token 不对 |
| `tts_unavailable` | 503 | 模型未就绪 |
| `synth_failed` | 200（流内） | 合成异常 |

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TTS_SERVICE_HOST` | `127.0.0.1` | 绑定地址 |
| `TTS_SERVICE_PORT` | `9001` | 端口 |
| `SERVICE_AUTH_TOKEN` | 空 | 非空则启用 Bearer 认证 |
| `TTS_LOG_LEVEL` | `INFO` | 日志级别 |
| `GPT_SOVITS_CONFIG` | `GPT_SoVITS/configs/tts_infer.yaml` | 模型配置 |
| `GPT_SOVITS_VERSION` | `v2` | 用 yaml 里哪个版本段 |
| `GPT_SOVITS_VOICE` | 读 `reference/my_voice.txt` | 音色名 |
| `GPT_SOVITS_REF_AUDIO` | 由音色名推导 | 参考音频绝对/相对路径 |
| `GPT_SOVITS_PROMPT_TEXT` | 由音色名查 `voice_list.json` | 参考音频对应文本 |
| `GPT_SOVITS_PROMPT_LANG` | `zh` | 参考音频语言 |
| `GPT_SOVITS_TEXT_LANG` | `zh` | 合成文本语言 |
| `GPT_SOVITS_SPLIT_METHOD` | `cut5` | 句内再切分方式 |
| `GPT_SOVITS_MIN_CHUNK` | `16` | 流式最小块长 |
| `GPT_SOVITS_OVERLAP` | `2` | 语义 token 重叠 |
| `GPT_SOVITS_SEED` | `42` | 固定种子（可复现） |
| `GPT_SOVITS_MAX_TEXT` | `2000` | 文本长度上限 |
| `GPT_SOVITS_MAX_SENTENCES` | `60` | 分句数上限 |
| `GPT_SOVITS_MAX_AUDIO_BYTES` | `8388608` | 单次响应音频字节上限 |
| `GPT_SOVITS_QUEUE_WAIT_S` | `120` | 排队等推理锁的超时 |

上面这套推理参数取自本机实测最优组合（`cut5` + `min_chunk_length=16` +
`overlap_length=2` + `streaming_mode=True` + `seed=42`）。

## 实测（本机 RTX 4060 Laptop，智能模式）

24 轮 HTTP 端到端，中位数：

| 指标 | 服务口径 | 裸库口径 |
| --- | --- | --- |
| **RTF** | **0.288**（min 0.255 / p90 0.388） | 0.21 ~ 0.26 |
| **TTFB** | **0.626 s**（min 0.381 / p90 0.703） | 0.25 ~ 0.30 s（首块） |
| 断流 | 0 | 0 |

**两个口径的 TTFB 不是一回事，别混用**：

- 裸库的 0.25~0.30 s 是"**首个音频块**"到达时间
- 服务因为线格式要求每行是**完整 wav 文件**（`tts_client.py` 直接
  `b64decode` 就拿去播），首行必然等**整句**合成完
- 0.626 s ≈ 一句 15 字 ≈ 4 s 音频 × RTF 0.21，账对得上

要压 TTFB 只有一条路：改线格式，让首行也允许裸 PCM 增量。那要动
`ws-contract` 与 `tts_client.py`，本轮没做。

RTF 服务比裸库高约 0.03~0.05，来源是 HTTP + NDJSON + base64 + 事件循环跳转 + 逐句分句。

## 已知限制

1. **不支持英文。** 上游 `g2p_en` 依赖 nltk 的 `cmudict`，本机缺该语料，
   任何含 ASCII 字母的文本（**含单个 `A`**）都会抛 `LookupError` 且首次触发卡 12 s。
   服务在进模型前挡掉，返回 400 `ascii_unsupported`。数字和中文标点不受影响。
2. **TTFB 是整句口径**，见上。
3. **严格串行。** 同时只跑一个推理；其余在锁上排队（默认 120 s 超时）。
4. **不切模型。** 权重在启动时定死；要换模型重启服务。

## 相比 `api_v2.py` 修掉的问题

| `api_v2.py` | 本服务 |
| --- | --- |
| 读不存在的 `../config/config.yaml`，直接崩 | 只读 `tts_infer.yaml`，不存在就报明确错误 |
| 无条件用 `my_voice.txt` 覆盖请求里的音色 | 音色来自配置/环境变量，请求可临时指定 |
| `text` 不 `.strip()`，静音也当成功 | 守卫挡掉空文本，并有静音兜底 |
| 在 async handler 里直接迭代生成器 → **阻塞整个 event loop**，合成期间服务僵死 | 合成在专用生产者线程，event loop 只做 `queue.get()`；合成期间 `/ready` `/v1/health` `/cancel` 依然即时响应 |
| 无打断能力 | `/v1/tts/cancel`，句中生效 + 队列级联清空 |
| 文本长度、音频字节数无任何限制 | 三道护栏 + 排队超时 |
| 每块都过一遍 `pack_audio`（ogg 路径还起线程改栈大小） | 直接 `wave` 写 int16 PCM，无中间层 |
| 强制 `media_type=wav` 且每块重写 wav 头 | 每句一个完整 wav，只写一次头 |
