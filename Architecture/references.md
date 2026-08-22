# 研究参考 · 溯源(答辩/人看)

> 开发文档只留规范与采纳成果;本文档统一存放来源、溯源与答辩叙事。

## 1. 开源参考(四条件筛选)

| 项目 | star | 用途 |
|---|---|---|
| Project AIRI | 47.4k | L1 Live2D 核心参考 |
| 心语 emotional_chat | 160 | 心理健康应用主参考(Agent Runtime+Skills) |
| HF speech-to-speech | 10k+ | 语音延迟工程(级联队列) |
| Qwen-Audio-Agent | 1.8k | 执行链路/边采边算(前后台并行) |
| Open-LLM-VTuber · BongoCat · live2d-widget | — | 对照基准/桌宠/看板娘 |

## 2. 理论背书

Beck 认知概念化(formulation)· CBT(共情前置)· PsyChat(充分度不足强制深入)。

## 3. 工程溯源

- 日志双输出/轮转:Open-LLM-VTuber(`run_server.py` init_logger)· AIRI(可读日志)
- 结构化字段:OpenTelemetry 关联字段 · 脱敏:Pino redactPaths
- 插件化思想:deepseek-harness(Cordis:接口+注册表+配置拼装)

## 4. 答辩叙事点

1. **危机闸门贯穿每轮 + 软信号预筛→复核**：安全是架构第一优先，且分层控成本
2. **多轮采集 = 共情式对话（L4 管状态、L5 管话术）**：把"理解"翻译成"被看见"，黑板上每轮生长一格
3. **两级标签 + 边采边算**：空窗期有图可画，最后一轮到精稿的空窗由后台分析填充（MVP 为停采后同步分析，并行化属二期）
4. **情绪一源三用**：一个 JSON 驱动立绘/黑板/语音，接口稳定
5. **记忆治理层 + 模型配置 AES-GCM**：隐私与工程完整性
