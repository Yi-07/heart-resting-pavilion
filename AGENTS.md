# AGENTS.md

心栖阁（heart-resting-pavilion）：面向轻中度情绪困扰人群的情感陪伴与心理知识科普工具（非医疗）。危机闸门贯穿每条输入，分 crisis / answer / collect 三链路。技术栈与模块职责见 `ARCHITECTURE.md`。

## 规则约定

- 职能：coding agent 常驻开发规范，细则按指针按需加载。
- 读写闸门：只读支线（检索、扫库、分析）自由；凡变更本库内容的写操作，先按「文档索引」取规则，再沿 `CONTRIBUTING.md` 流程推进。
- 护栏：命令失败、依赖装不上、实现与契约冲突、需改架构时，中止操作并向维护者确认。
- 行为约束：每次改动聚焦单一主题；理解并验证全部生成代码；多步任务先记入看板再开工，每步完成停下汇报、人确认后 commit，当轮小修做完补记；提交前按 `CONTRIBUTING.md`「改动后验证」跑对应检查。
- 冲突解决：消息或字段矛盾，以 `docs/architecture/ws-contract.md` 为准；机制或参数矛盾，以 `docs/architecture/architecture-spec.md` 为准；新旧描述并存，以 spec 正文为准。
- 不一致即文档缺陷：属上述三类，先修正文档再编码并报告改动；三类之外、同文自相矛盾或权威本身存疑，向维护者确认。

## 文档索引

- 全库文档索引与入树规则见 `docs/README.md`；工程流程见 `CONTRIBUTING.md`（人与 agent 同遵；agent 执行细则以本文件为准）。

- 按任务先读：
  - 改码：编码规范见 `docs/guides/coding-standards.md`；新模块开工先读 `docs/guides/deep-module.md`
  - 改契约：先读 `docs/architecture/ws-contract.md` 与 `docs/architecture/architecture-spec.md` 相关节
  - 新需求：复杂任务可走 `CONTRIBUTING.md`「复杂任务的开发流程」节（自选不强求）
  - 验收：话术与判据见 `docs/tests/acceptance-v1.md`
  - 写文档：调用 doc-standards skill
  - 续接：先读任务看板（现 `docs/task-kanbans/yxw/dev-v1/kanban-v1.md`）与同文件夹 `handoff.md`

## 架构要点

- 三路路由：每条 `user_input` 先过危机闸门（规则硬判，确定性，贯穿每条输入）；细则见 `docs/architecture/architecture-spec.md`「三路路由」节。
- 闸门未命中时进 answer（直接答，知识走 RAG）或 collect（多轮采集）。
- 职责隔离：`crisis` 与 `route` 只走规则；`emotion_label` 只喂黑板与 Live2D，不进路由。
- 依赖方向：契约以 `docs/architecture/ws-contract.md` 为准，`backend/app/schema/` 与 `frontend/src/ws/messages.ts` 跟随契约实现；改动核验通过后同步契约文档，与代码同一提交批次。
- 新代码只写 `backend/` 与 `frontend/`。

## 命令

- 命令单源是 `backend/pyproject.toml` 与 `frontend/package.json`，本节只收启动与验证摘要；模型与环境变量单源是 `backend/.env.example`，版本要求与模型下载见 `docs/guides/option.md`。

```bash
uv run hrp    # 后端启动(backend/ 目录,uv):默认 127.0.0.1:8000,--host/--port 可覆盖;--reload 热重载开发,配 TTS_SIDECAR_KILL_ON_EXIT=0;自动拉起 sidecar 并版本握手,模型加载不阻塞文字链路,退出有序关停
uv run ruff check app && uv run mypy app && uv run pytest    # 检查、类型检查、测试
uv run python -m app.rag.ingest    # 语料 jsonl 变更后重新导入 Chroma;--reset 清空重建,换模型或维度必须;--library 只导入单个库
uv run python -m app.voice.fillers    # 预生成等待语音,幂等,已存在跳过;换音色后删 data/fillers/ 重跑
npm run dev    # 前端开发(frontend/ 目录)
npm run type-check && npm run lint && npm run test:unit    # 验证三连;lint 带 --fix,自动改源文件
```

## 安全红线

- 脱敏：用户文本**不落原文**，记长度与哈希；音频不落库；凭证（AES-GCM 密钥、API key）不落。
- 危机审计：危机命中**必落审计日志**，WARN 级，含命中项与是否转热线，不含原文。
- 判定边界：危机判定**只在后端**；前端零危机逻辑；音频转写后即弃。

## 工具

- MCP 工具按 harness 各自配置：Claude Code 用项目根 `.mcp.json`（本仓已配）；Codex/Cursor 若使用，各建 `.codex/config.toml`/`.cursor/mcp.json`（本仓未配，仓内示例=`.mcp.json`）。本仓推荐三件：chrome-devtools（页面实况检查）、playwright（浏览器自动化）、context7（库文档查询）。
- skill 清单见 `.claude/skills/`。
