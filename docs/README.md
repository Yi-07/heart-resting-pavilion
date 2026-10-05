# docs · 文档总索引

> **职能**：登记 docs/ 下每个目录收什么、新文档往哪放。
> 文件职能由各文件头注自述，本文不逐文件登记；目录内新增文件不改本文，新建目录才入树。

## 架构权威（docs/architecture/）

收录架构与契约的权威文档。架构怎么定、接口什么格式，以此目录为准。

- 契约与架构：[architecture-spec.md](architecture/architecture-spec.md)（架构）、[ws-contract.md](architecture/ws-contract.md)（WS 消息契约）、[data-contract.md](architecture/data-contract.md)（RAG 语料资产契约）。
- 实施计划：[frontend-plan.md](architecture/frontend-plan.md)、[backend-plan.md](architecture/backend-plan.md)。
- 配套：[CONTEXT.md](architecture/CONTEXT.md)（术语正词与避用词）、[ARCHITECTURE_PROGRESS.md](architecture/ARCHITECTURE_PROGRESS.md)（决策台账、二期总表与会话恢复锚点）、preview/（UI 参考静态原型）。

## 图表（docs/diagrams/）

收录架构图表，diagram-design skill 生成，HTML 源与 SVG 导出成对入库（生产环境 workspace/ 不入库）。

- [architecture-overview](diagrams/architecture-overview.html)：架构总览（组件与数据流走向），被 [ARCHITECTURE.md](../ARCHITECTURE.md) 引用。
- [session-lifecycle](diagrams/session-lifecycle.html)：一次会话生命周期时序。
- 维护边界与更新工序请参阅 [guides/diagram-maintenance.md](guides/diagram-maintenance.md)。

## 决策记录（docs/adr/）

收录架构决策记录。命名 `NNN-slug.md`，三位顺序编号接续现有最大号。

- 何时写：三条全占才写一篇——决策落地后难以调头；事后会追问当初为什么这么定；方案之间存在真实取舍。占不满的，记入 [ARCHITECTURE_PROGRESS.md](architecture/ARCHITECTURE_PROGRESS.md) 决策台账。
- 各篇一句话索引在根目录 [ARCHITECTURE.md](../ARCHITECTURE.md)，本文不重复。

## 指南与规范（docs/guides/）

收录各类指南与跨文件规范，供其他文档按需引用。

- [option.md](guides/option.md)：环境搭建操作手册。
- [coding-standards.md](guides/coding-standards.md)：跨文件代码写法约定。
- [deep-module.md](guides/deep-module.md)：代码库设计基准。
- [diagram-maintenance.md](guides/diagram-maintenance.md)：docs/diagrams/ 图表维护规程（何时更新、更新工序）。
- 命名：职能名，小写英文连字符。

## 测试与验收（docs/tests/）

收录验收判据与审查留档。

- [acceptance-v1.md](tests/acceptance-v1.md)：第一版交付验收判据，话术与判据以此为准。
- reviews/：代码审查与文档摸查的留档，一次审查留一份（如 [reviews/c1-review.md](tests/reviews/c1-review.md)）。
- 命名：验收判据用 `acceptance-v<版本号>.md`；审查留档用任务号加类型。

## 执行状态（docs/task-kanbans/ · docs/todos/）

收录任务执行现场：做到哪一步、还欠什么。

- task-kanbans/：跨会话执行看板与会话交接快照，按人名、任务名两级文件夹组织，每任务一份看板与一份交接快照，同名配对。现行任务：[yxw/dev-v1/kanban-v1.md](task-kanbans/yxw/dev-v1/kanban-v1.md)。
- todos/：待办与问题存放点，常驻文件用职能名（[backlog.md](todos/backlog.md)、[tasks-arrangement.md](todos/tasks-arrangement.md)），一次性记录用日期前缀（[20260917-questions.md](todos/20260917-questions.md)）。

## 需求（docs/prds/）

收录 PRD。PRD 描述新增或改动需求，随实现进展更新，完结后加完结注。

- 何时写：原型验证之后、开发之前；流程见 [CONTRIBUTING](../CONTRIBUTING.md)「复杂任务的开发流程」节（可选）。
- 命名：小写英文连字符，概述需求主题。
- 边界：PRD 只写本需求的改动面；数据契约字段以 [data-contract.md](architecture/data-contract.md) 为准。

## 参考（docs/ 根）

收录不属于以上任何目录的参考文件。

- [references.md](references.md)：开源参考溯源。
- [Inspiration.md](Inspiration.md)：灵感随手档。

## 新文档入树规则

仓库根不再新增文档，新文档一律按下表落入 docs/。原型、探查、中间产物不进 docs/，放项目根 `prototypes/`（整目录不进版本库）。

| 内容类型 | 落点 |
|---|---|
| 架构权威、契约、实施计划 | docs/architecture/ |
| 架构决策记录 | docs/adr/ |
| 架构图表 | docs/diagrams/ |
| 指南、操作手册、跨文件规范 | docs/guides/ |
| 验收判据、审查留档 | docs/tests/ |
| 任务看板、交接、待办、排期 | docs/task-kanbans/ · docs/todos/ |
| 需求文档 | docs/prds/ |
| 其余文档 | docs/ 根 |

新建目录：在本文加一节，写清目录职责与命名规范。
