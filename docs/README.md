# docs · 文档总索引

> **职能**:全部文档的索引与入树规则,找文档先查本文。

## 架构权威(docs/architecture/)

| 文档 | 职能 |
|---|---|
| architecture/architecture-spec.md | 架构权威源(三路路由/容器/DrawProtocol) |
| architecture/ws-contract.md | WS 消息契约权威源(9 种消息格式) |
| architecture/frontend-plan.md | 前端实施方案(模块/状态机/接口) |
| architecture/backend-plan.md | 后端实施方案(模块/图/网关) |
| architecture/CONTEXT.md | 术语表(正词/避用) |
| architecture/ARCHITECTURE_PROGRESS.md | 决策台账 + 二期总表 + 会话恢复锚点 |
| architecture/data-contract.md | 队友数据集对接契约 |
| architecture/preview/ | 前端 UI 参考:布局=l1-ui-mockup-v7.html,组件范式=l1-ui-taste.html |

## 决策记录(docs/adr/)

001-005 共 5 篇;各篇一句话索引与链接 = ARCHITECTURE.md §4(单源)。

## 测试验收(docs/tests/)

| 文档 | 职能 |
|---|---|
| tests/acceptance-v1.md | 第一版交付验收判据单源 |

## 项目执行(docs/task-kanbans/ · docs/todos/)

| 文档 | 职能 |
|---|---|
| task-kanbans/kanban-v1.md | 跨会话执行看板(步骤状态单源) |
| task-kanbans/handoff.md | 交接现场快照 |
| todos/backlog.md | 遗留待办池单源 |
| todos/tasks-arrangement.md | 里程碑/阶段排期(人看) |

## 审查快照(docs/reviews/)

| 文档 | 职能 |
|---|---|
| reviews/c1-review.md | C1 全库代码审查快照与销账 |
| reviews/d1a-survey.md | D1-a 文档摸查问题清单 |
| reviews/d1b-pointer-survey.md | D1-b 重复叙述与指针规范搜查 |

## 操作指南与设计基准(docs/guides/)

| 文档 | 职能 |
|---|---|
| guides/option.md | 环境搭建操作手册(人做 0-5 步) |
| guides/deep-module.md | 代码库设计基准(深模块) |

## 需求(docs/prds/)

| 文档 | 职能 |
|---|---|
| prds/rag-full-corpus-bge-m3.md | RAG 全量语料+bge-m3 换模型 PRD(已完结) |

## 参考(docs/)

| 文档 | 职能 |
|---|---|
| references.md | 开源参考溯源 |
| Inspiration.md | 灵感随手档(人看) |

## 新文档入树规则

仓库根只留 4 个入口(README / CONTRIBUTING / AGENTS / ARCHITECTURE)+ CLAUDE.md 薄壳;原型/探查/中间产物=项目根 `prototypes/`(整目录 gitignored)。其余按类型:

| 内容类型 | 落点 |
|---|---|
| 架构权威(六件套+preview) | docs/architecture/ |
| 架构决策 | docs/adr/ |
| 操作指南与设计基准 | docs/guides/ |
| 验收判据 | docs/tests/ |
| 执行状态 | docs/task-kanbans/ · docs/todos/ |
| 审查快照 | docs/reviews/ |
| 其余人看文档 | docs/ 根 |
