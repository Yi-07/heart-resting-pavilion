---
title: GPT-SoVITS 源码理解笔记
section: internal
last_updated: 2026-10-08
---

# GPT-SoVITS 源码理解笔记

> 注意：这份文档是我在理解代码时随手记的，不是给外层项目用的。主服务用的启动、请求、错误码说明在 `D:\aic-project\heart-resting-pavilion\docs\guides\gpt-sovits-guide.md`。

---

## 1. 一句话总结

这段代码的设计思路是：把复杂的 TTS 模型推理包成了 4 个核心接口——`load`、`synthesize`、`cancel`、`snapshot`。
主程序只管收请求、起线程；Python 线程里调用 `engine.synthesize()`，它再去 `TTS_infer_pack/TTS.py` 里走完整链路。

---

## 2. 最核心的几个文件

| 文件 | 作用 |
|---|---|
| `tts_service/__main__.py` | 命令行入口，启动 uvicorn |
| `tts_service/server.py` | FastAPI 层，做端点、中间件、metrics |
| `tts_service/engine.py` | **真正的推理引擎**，串行+守卫+打断 |
| `tts_service/settings.py` | 配置加载（环境变量、默认路径） |
| `GPT_SoVITS/TTS_infer_pack/TTS.py` | 真正加载模型和跑推理的地方 |
| `GPT_SoVITS/module/models.py` | VITS / SynthesizerTrn / Generator 模型定义 |
| `GPT_SoVITS/process_ckpt.py` | 读写权重 checkpoint、判断版本 |
| `text/` | 文本清洗、切分、音素提取 |
| `AR/models/t2s_model.py` | 文本到语义 token 的 AR 模型 |
| `BigVGAN/bigvgan.py` | v3/v4 的波形声码器 |

---

## 3. 启动链路

```text
python -m tts_service
  → tts_service/__main__.py
      →  get_settings()     # 读环境变量、yaml、配置
      →  uvicorn.run("tts_service.server:app")
           → tts_service/server.py
               → engine = TTSEngine(_cfg)
               → lifespan() 中启动后台线程
                   → threading.Thread(target=engine.load)
                     → TTS_infer_pack.TTS.TTS_Config()   # 等效写法
                     → TTS(configs)                      # 加载所有模型
```

---

## 4. 请求链路（核心）

```text
POST /v1/tts/stream
  ↓
server.py 先校验文本非空、engine 已 ready
  ↓
engine.guard(text)  -> syntactic check + ASCII 拦截 + 分句
  ↓
在后台线程里跑 engine.synthesize(...)
  ↓
engine._build_req()     # 为每句组装请求 dict
  ↓
engine.synthesize() 里逐句:
    for sentence in sentences:
        req = self._build_req(sentence, voice)
        for chunk_sr, chunk in tts.run(req):
            yield SentenceAudio(...)
  ↓
TTS_infer_pack/TTS.py.TTS.run(req)
  ↓
TextPreprocessor:
    text -> split into sentences
    each sentence -> segment_and_extract_feature_for_text()
        -> clean_text_inf()
        -> get_bert_inf()
  ↓
AR 模型: TTS_T2SModel.infer_panel(...)
    -> semantic tokens
  ↓
VITS/声码器: self.vits_model.decode() 或 using_vocoder_synthesis()
    -> 波形 float32 [-1,1]
  ↓
engine.py 把多段拼接、转 wav、apply guard（字节数上限）
  ↓
server.py 返回 NDJSON 每行 {"wav": "..."}
```

---

## 5. 为什么必须串行

`TTS` 里有 `prompt_cache`，缓存的是参考音频的语义特征、频谱特征，以及 BERT/cnhubert 需要的数据。
如果同时有两个请求同时往里写，会互相覆盖，导致风格错乱或模型状态爆炸。
所以 `engine.synthesize` 用 `_infer_lock` 做严格串行，每个回合还要注册 CancelToken。

---

## 6. 打断机制

不使用 kill thread，直接设置 `CancelToken.cancel()`。
`engine.synthesize()` 的循环里每处理一小段就检查 `token.cancelled`。
如果被打断，丢弃已生成的半句，`server.py` 端会返回 `{"cancelled": true}`。

---

## 7. 文本预处理的具体流程

```text
engine.guard(text)
  ↓
server.py 接收请求
  ↓
engine.synthesize() -> TextPreprocessor.preprocess()
  ↓
text/cleaner.py 里的 clean_text()
  ↓
chinese.py / english.py / japanese.py 等按语言清洗
  ↓
cleaned_text_to_sequence() -> phones, word2ph, norm_text
  ↓
get_bert_inf() -> bert_features (1024, phone_len)
  ↓
returns {phones, bert_features, norm_text}
```

---

## 8. 不同模型版本的差异

- v1/v2：输出 24k/32k，用 `vits_model.decode()`
- v3：加入 BigVGAN 声码器，输出 24k
- v4：修复 v3 的金属音，输出 48k
- v2Pro / v2ProPlus：v2 的强化版，需要 sv_model 配合

---

## 9. 已知坑

1. 任何英文字符都不行（`ascii_unsupported`）
2. v3/v4 不支持流式，会自动退化成 return_fragment
3. `SynthesizerTrn` 必须串行
4. 超过 510 字符的长句会被智能切分，但还是建议在源 text 已经切句
5. 若后面换语音，记得把 `reference/<voice>.wav` 放好并写进 `reference/voice_list.json`
