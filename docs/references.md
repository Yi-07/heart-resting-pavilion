# 研究参考 · 溯源(人看)

> 开发文档只留规范与采纳成果;本文档统一存放来源、溯源。

## 1. 开源参考(四条件筛选)

| 项目 | star | 用途 |
|---|---|---|
| Project AIRI | 47.4k | L1 Live2D 核心参考 |
| 心语 emotional_chat | 160 | 心理健康应用主参考(Agent Runtime+Skills) |
| HF speech-to-speech | 10k+ | 语音延迟工程(级联队列) |
| Qwen-Audio-Agent | 1.8k | 执行链路/前后台并行分析 |
| Open-LLM-VTuber · BongoCat · live2d-widget | — | 对照基准/桌宠/看板娘 |

## 2. 理论背书

Beck 认知概念化(formulation)· CBT(共情前置)· PsyChat(充分度不足强制深入)。

## 3. 工程溯源

- 日志双输出/轮转:Open-LLM-VTuber(`run_server.py` init_logger)· AIRI(可读日志)
- 结构化字段:OpenTelemetry 关联字段 · 脱敏:Pino redactPaths
- 插件化思想:deepseek-harness(Cordis:接口+注册表+配置拼装)

