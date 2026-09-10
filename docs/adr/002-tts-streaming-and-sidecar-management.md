# ADR-002 · TTS 分句流式与 sidecar 进程统一管理

## 状态

已定案（实施记录见 git log 与 ARCHITECTURE_PROGRESS）

## 背景

collect 全链路实测暴露三个问题：

1. **总结语音必超时**：`_process_user_input` 的 `wait_for(LLM_TIMEOUT_S=60s)` 罩住整个 collect 序列含总结 TTS；CosyVoice CPU 合成 0.7s/字，305 字总结必撞线，触发 `error(timeout)` 兜底帧、总结语音永远播不出。
2. **存量截断 bug**：`inference_zero_shot` 对 `stream=False` 也按块 yield，sidecar 用 `next()` 只取第一块，长文本丢约 3/4 音频。
3. **进程版本漂移**：sidecar 支持手动启动，backend 探活只看进程存活不看版本，旧代码进程被静默复用；改码后忘重启 sidecar 表现为"无声音且难排查"。

归因（实测）：两 venv torch 均为 CPU 版（RTX 4050 6GB 闲置）是延迟根因；整段合成是链路放大因素。一次性原型验证：GPU torch 快 ~4x、峰值显存 2.9GB；分句合成首包 16.9s→1.5s。参考 Open-LLM-VTuber（分句+并行合成+seq 重排）与 AIRI（首包 boost 切短）。

## 决策

1. **分句流式取代整段合成**：sidecar 新端点 `POST /tts_stream`（NDJSON 逐句出料，`split_for_tts` 分句：硬标点切句、首句软标点提前切、超 30 字软切），取代 `/tts`（唯一调用方，直接切换不留兼容层）；网关 `_speak_stream` 逐句直发，每句一个 `audio_chunk`（seq 单调），合成线程经 `run_coroutine_threadsafe` 回事件循环保序。不采用 CosyVoice2 模型内流式（chunk 递增变长，结构性缺陷）。
2. **总结语音移出处理窗口**：`_settle_collect_event` 中总结 TTS 改 `create_task` 异步流出，`done` 紧随文本收尾；蒸发条件与安抚语区分——总结语音**仅抢占（trace 变）才蒸发**（要在回合收尾后播完），安抚语回合收尾即蒸发。
3. **sidecar 进程统一管理**：backend lifespan 启动后台拉起 sidecar（模型加载分钟级，不阻塞文字链路），退出有序关停自己拉起的子进程（`TTS_SIDECAR_KILL_ON_EXIT` 门控，`--reload` 开发置 0）；`/health` 携带 `version` 握手，不匹配=自己拉起的杀掉重拉、外部的 ERROR 降级，杜绝旧进程静默复用。启动入口收敛为 `uv run hrp`（pyproject scripts）。
4. **算力分配**：ASR（SenseVoice）留 CPU；6GB 显存只给 TTS 一个常驻模型。ASR GPU 化收益 4-6x 但非必需，二期再议。

## 后果

- **契约变更**（ws-contract §3.4/§6.2 已同步）：audio_chunk 可多帧（分句）；总结语音可在 done 之后到达，抢占即蒸发。前端 AudioQueue 独立于回合状态、first_frame 清队，行为兼容。
- **运维约束**：改 sidecar 代码后 backend 会经版本握手拒绝旧进程并 ERROR 提示重启（自动杀重拉仅限自己拉起的）。
- **测试卫生**：sidecar 编排在 conftest 隔断（TestClient 的 lifespan 不得真拉进程）；语音用例显式 stub `ensure_sidecar=False`，禁走真拉起路径。
- **遗留**：分句合成的 per-call prompt 重编码固定开销（~0.5-1s/句）使总耗时不降，收益全部在首包；onnx 部分（campplus/speech_tokenizer）win32 无 CUDA provider 留 CPU。真·LLM 流式逐句合成（边生成边播）留二期。

## 影响

backend: `ws_gateway/gateway.py`、`voice/tts.py`、`voice/tts_sidecar.py`、`voice/sidecar_protocol.py`、`main.py`、`cli.py`、`config.py`、`pyproject.toml`；架构: `ws-contract.md`；环境: `models/voices/CosyVoice/.venv`（CUDA torch）。
