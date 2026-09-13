# 贡献指南

> **职能**:人类队友的协作规范——节奏、验证、文档、任务、红线。agent 规范单源=AGENTS.md · 环境手册=docs/guides/option.md · 文档索引=docs/README.md

## 协作节奏

每步完成 → 停下汇报 → 人确认 → commit。未获确认不开下一步。

commit 风格:`类型(范围): 中文描述`。类型 = feat / fix / docs / chore,范围 = 看板步骤号或模块名。示例:`feat(b2): 完整三链路业务测试落地`。

coding agent 协作方式(派发/回收/汇报纪律)=docs/task-kanbans/kanban-v1.md §0。

## 环境搭建

操作手册=docs/guides/option.md(Redis、模型下载、`.env`、语音栈,0-5 步)。agent 工具(ctx7 / chrome-devtools / playwright)拉起指令单源=.claude/rules/tools.md「拉起指令」节。

## 改动后验证

按改动面选跑对应检查。不全套跑,不重复跑已过的检查。

| 改动面 | 检查(运行目录) |
|---|---|
| 后端 | `uv run ruff check app` · `uv run mypy app` · `uv run pytest`(backend/) |
| 前端 | `npm run type-check` · `npm run lint` · `npm run test:unit`(frontend/) |
| 文档 | doc-standards 十判据自查 + 避用词收尾 grep |

## 文档贡献

三套写作规范按读者选用,清单单源=.claude/rules/tools.md「文档编写规范」节:

- 给人看 → doc-style-human(句法铁律)+ doc-standards(删留判据)
- 给 agent 看 → writing-for-agents(结构与写法)+ doc-standards

新文档落哪个目录=docs/README.md「新文档入树规则」。

## 任务清单索引

- 团队任务与系统发现待裁决问题回放 = docs/todos/backlog.md
- 排程执行状态单源 = docs/task-kanbans/kanban-v1.md(勾选=已完成并 commit)

## 红线

危机判定只在后端 · 用户文本不落原文 · 音频不落库。细则=AGENTS.md §6。
