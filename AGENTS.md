# AGENTS.md

心栖阁（heart-resting-pavilion）：面向轻中度情绪困扰人群的情感陪伴与心理知识科普工具（非医疗）。
危机闸门贯穿每条输入。全库文档索引与入树规则见 `docs/README.md`。在动手改动本项目前请先阅读`CONTRIBUTING.md`获取对应规范。

## 规则约定

- 读写闸门：只读支线（检索、扫库、分析）自由；写操作前先按 `docs/README.md` 索引读涉及的规范文档，再沿 `CONTRIBUTING.md` 流程推进。
- 护栏：命令失败、依赖装不上、实现与契约冲突、需改架构时，中止操作并向维护者确认。
- 行为约束：每次改动聚焦单一主题；理解并验证全部生成代码；多步任务先记入看板再开工（看板落点由人指定），每步完成停下汇报、人确认后 commit，当轮小修做完补记；提交前按 `CONTRIBUTING.md`「改动后验证」跑对应检查，检查并维护改动涉及的所有常驻文档的信息对齐状态，保持文档信息的时效性，改文档前必先看`CONTRIBUTING.md`的「文档贡献」；接续任务时，看板与交接材料路径由人指定，不默认读取任何固定位置；交付文档由当轮改动的 agent 起草、维护者确认后合入，执行状态文档由执行会话随步维护。
- 冲突解决：消息或字段矛盾，以 `docs/architecture/ws-contract.md` 为准；机制或参数矛盾，以 `docs/architecture/architecture-spec.md` 为准；新旧描述并存，以 spec 正文为准。
- 文档与实况脱节时的处置：消息或字段对不上、机制或参数对不上、新旧描述并存——这三类先修正输掉的文档再编码，并向维护者报告改动；其他矛盾（三类之外、同一文档前后打架、权威文档本身可疑），停下向维护者确认，不自行裁定。
- 本文档失真或误导时当场修正——本文是 agent 行为规则唯一住址，过时内容污染全局。

## 规则边界

- 危机闸门与路由机制是架构级决定，改动先停下确认；细则见 `docs/architecture/architecture-spec.md`「三路路由」节。
- 契约先行：改消息或字段先改 `docs/architecture/ws-contract.md`，再动 `backend/app/schema/` 与 `frontend/src/ws/messages.ts`，核验通过与代码同一提交批次。
- 职责隔离：`emotion_label` 只喂黑板与 Live2D，不进路由判定。
- 新代码只写 `backend/` 与 `frontend/`。

## 命令

命令单源是 `backend/pyproject.toml` 与 `frontend/package.json`；模型与环境变量单源是 `backend/.env.example`。

```bash
uv run hrp    # 后端启动（backend/ 目录，uv）：默认 127.0.0.1:8000；--reload 热重载开发须配 TTS_SIDECAR_KILL_ON_EXIT=0
uv run ruff check app && uv run mypy app && uv run pytest    # 检查、类型检查、测试
uv run python -m app.rag.ingest    # 语料 jsonl 变更后重灌；--reset 清空重建，换模型或维度必须
uv run python -m app.voice.fillers    # 预生成等待语音，幂等；换音色后删 data/fillers/ 重跑
npm run dev    # 前端开发（frontend/ 目录）
npm run type-check && npm run lint && npm run test:unit    # 前端验证；lint 带 --fix，自动改源文件
```

## 安全红线

- 脱敏：用户文本**不落原文**，记长度与哈希；音频不落库；凭证（AES-GCM 密钥、API key）不落。
- 危机审计：危机命中**必落审计日志**，WARN 级，含命中项与是否转热线，不含原文。
- 判定边界：危机判定**只在后端**；前端零危机逻辑；音频转写后即弃。

## 工具

MCP 与 skill 配置见项目根 `.mcp.json` 与 `.claude/skills/`。
