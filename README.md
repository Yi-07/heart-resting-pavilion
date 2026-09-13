# 心栖阁

> **职能**:项目入口——项目是什么、怎么跑起来、去哪深入。环境细节=[docs/guides/option.md](docs/guides/option.md) · 协作=[CONTRIBUTING.md](CONTRIBUTING.md) · agent 规范=[AGENTS.md](AGENTS.md) · 架构=[ARCHITECTURE.md](ARCHITECTURE.md) · 文档索引=[docs/README.md](docs/README.md)

## 项目定位

面向轻中度情绪困扰人群的情感陪伴 + 心理知识科普工具。

> **非医疗声明**:本工具不提供医疗诊断与治疗建议,不能替代专业帮助。出现危机信号时转心理援助热线 12356。

## 三链路一览

每条用户输入先过危机闸门,再进路由:

| 链路 | 触发 | 行为 |
|---|---|---|
| crisis | 危机闸门命中(规则硬判) | 热线 12356 + 支持性画面 + 审计日志 |
| answer | 知识问答、简单问候 | RAG 检索后流式直答,无黑板 |
| collect | 情绪梳理需求 | 多轮采集,黑板粗稿→逐轮增量→精稿→总结 |

## 技术栈

| 端 | 选型 |
|---|---|
| 后端 | FastAPI + LangGraph(uv 管依赖) |
| 前端 | Vue3 + Vite + TypeScript |
| 存储 | Redis(热/温层)· Chroma(知识库)· SQLite(冷层) |

## 环境构建

从零到可用统一走 [docs/guides/option.md](docs/guides/option.md):前置检查 → Redis → 后端依赖与 .env → 前端 → 可选增强(RAG 知识库/Live2D 素材/语音栈)→ 启动与冒烟。

不做可选增强 = 文字三链路(crisis/answer/collect)可用,RAG 知识检索/语音/立绘缺省降级。日常开发命令=[AGENTS.md](AGENTS.md) §3。
