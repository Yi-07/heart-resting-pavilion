# CONTRIBUTING

> **写给谁**：人类队友。agent 队友的规范单源是 [AGENTS.md](AGENTS.md)（[CLAUDE.md](CLAUDE.md) 是其入口薄壳），本文不重复叙述。
> **写什么**：从拿到仓库到改动合入 main，每一步做什么、按什么规范。
> **何时读**：第一次上手通读一遍；某一步不确定时回查对应节。
> 复杂任务（需求说不清、跨多模块、动契约）另有一条可选流程，见[「复杂任务的开发流程」](#5-复杂任务的开发流程可选)。

## 1. 环境搭建

安装、模型下载、启动、排障等细则见 [docs/guides/option.md](docs/guides/option.md)。跑通后端与前端开发服务，环境即就绪。

## 2. 开发改码

代码怎么写：跨文件约定见 [docs/guides/coding-standards.md](docs/guides/coding-standards.md)；术语正词见 [docs/architecture/CONTEXT.md](docs/architecture/CONTEXT.md)。

每次改动聚焦单一主题。文档与代码同一提交批次改完。

与 agent 协作的节奏：多步任务先记入看板再开工，当轮小修做完补记一笔；它每完成一步停下汇报，你确认后 commit。看板按人名、任务名两级文件夹组织，细则见 [docs/task-kanbans/yxw/dev-v1/kanban-v1.md](docs/task-kanbans/yxw/dev-v1/kanban-v1.md)「工作方式」节。

## 3. 改动后验证

提交前按改动面跑对应检查。检查不过，修复后重跑。

| 改动面 | 检查 | 通过标准 |
|---|---|---|
| 后端代码 | `uv run ruff check app`、`uv run mypy app`、`uv run pytest` | ruff 零输出；mypy 零错误；pytest 全过 |
| 前端代码 | `npm run type-check`、`npm run lint`、`npm run test:unit` | type-check 零错误；lint 零错误；test:unit 全过 |
| 文档 | doc-standards skill 十判据自查 | 避用词 grep 零命中 |

> [!tip]
>
> 验证命令明细以 [AGENTS.md](AGENTS.md)「命令」节与配置文件为单源，本表只记对应关系。

## 4. 提交与 PR

commit 风格：`类型(范围): 中文描述`。类型取 feat、fix、docs、chore、refactor、test；范围写模块名或任务号。

提交走 fork 工作流：

1. fork 本仓库，在 fork 内开分支，分支名 `类型/短描述`。
2. 验证全过后向 main 提 PR。PR 标题即合并用的 commit message，须符合同一风格。
3. 负责人审查，问题写在 review 意见里，改完再提审。
4. 审查通过后由负责人 squash 合并。

两条说明：本仓库不设 CI，验证靠本地按上表自跑；多个改动并行时用 git worktree 分开工作区。

改动合入后，在看板勾选对应条目并补一句执行纪要。

## 5. 复杂任务的开发流程（可选）

本章提供开发流程的思路，可按需采用，多数改动走默认路径即可：直接改码、跑验证、提 PR。

满足任一条，建议走本章流程：

- 需求说不清最终形态，或多方理解不一。
- 改动跨多个文件或多个模块。
- 可能触及契约或架构面（schema、ws-contract、architecture-spec 等）。

流程六环：

```text
grilling 需求清晰化 → prototype 原型验证 → PRD 写作 → 架构对齐 → 开发 → 审核提交
```

| 环节 | 做什么 | 库内 skill |
|---|---|---|
| 需求清晰化 | 盘问需求，产出设计共识 | grilling、grill-with-docs |
| 原型验证 | 写弃型原型回答设计问题，验证后再写真代码 | prototype |
| PRD 写作 | 写需求文档入 [docs/prds/](docs/prds/)，只写改动面 | to-spec |
| 架构对齐 | PRD 触及架构文档的，先改文档再开工；判定无影响要在 PRD 里写明 | — |
| 开发 | 按 PRD 实现，可测试先行 | to-tickets、implement、tdd |
| 审核提交 | 提 PR 前跑一轮代码审查 | code-review |

影响面判定：触及 [ws-contract](docs/architecture/ws-contract.md)、[data-contract](docs/architecture/data-contract.md)、[architecture-spec](docs/architecture/architecture-spec.md) 等架构文档的已定内容，即算影响。拿不准就按有影响处理，先对齐再开工。

## 6. 文档贡献

按读者选写作规范，写完按 doc-standards skill 十判据自查：

- 给人看的文档：先读 [.claude/rules/doc-style-human.md](.claude/rules/doc-style-human.md)。
- agent 看的文档：按 writing-for-agents skill 写。

新文档放哪、入树规则，见 [docs/README.md](docs/README.md)。

## 7. 任务与状态

- 执行状态（任务看板）：[docs/task-kanbans/yxw/dev-v1/kanban-v1.md](docs/task-kanbans/yxw/dev-v1/kanban-v1.md)，勾选即已完成并 commit。
- 任务待办池：[docs/todos/backlog.md](docs/todos/backlog.md)。
- 会话间交接：交接快照与看板同文件夹同名配对（如 [dev-v1/handoff.md](docs/task-kanbans/yxw/dev-v1/handoff.md)），按 kanban 交接规程整篇重写。
- agent 的派发与汇报纪律：见 [kanban-v1.md](docs/task-kanbans/yxw/dev-v1/kanban-v1.md)「工作方式」节。

## 8. 工程纪律

- 验证不过不允许提交。
- 每次改动要聚焦单一主题。
- 文档与代码不得分离提交。
- 严格监控 agent 的操作，不得轻易信任批准直接入库。注意保留人工检查点：验证自己跑、改动自己看、提交自己确认。

安全红线（脱敏、危机审计、判定边界）细则单源见 [AGENTS.md](AGENTS.md)「安全红线」节，本文不重复叙述。
