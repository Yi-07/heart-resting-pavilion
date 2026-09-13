# 工具与 Skill 参考(扩展)

> CLAUDE.md 只留核心,完整清单在此,由 CLAUDE.md `@` 引用。
> 来源:**内置**=随 `.claude/skills/` 入库,clone 即得;**部署**=本机拉起后可用,指令见「拉起指令」。

| 工具/Skill | 用途 | 何时用 | 来源 |
|---|---|---|---|
| ctx7 | 查库/框架/CLI 官方文档 | API 语法/配置/版本迁移/CLI 用法拿不准 | 部署 |
| chrome-devtools | 浏览器实况检查(DOM/CSS/性能) | 改预览后、调样式/查渲染 | 部署 |
| playwright | 浏览器自动化(快照/点击/E2E) | 交互流验证、E2E 脚本 | 部署 |
| grilling | 决策压力测试盘问 | 改架构/大方向前 | 内置 |
| grill-with-docs | 盘问连招(grilling+domain-modeling),决策落 ADR/术语 | 架构级决策盘问 | 内置 |
| domain-modeling | 领域建模/术语挑战 | 改领域模型、术语歧义 | 内置 |
| prototype | 一次性原型回答设计问题 | 状态模型/逻辑拿不准、UI 探索时 | 内置 |
| writing-for-agents | agent 文档写法 | 写/改 agent 读的文档 | 内置 |
| emil-design-eng | 动效/设计品味 | 动效审查 | 内置 |
| apple-design | Apple 风界面设计与物理动效(手势/弹簧/拖拽) | 做或审手势驱动 UI、sheet 交互时 | 内置 |
| doc-standards | 文档十判据(删留/单源裁定) | 写/改/审交付文档 | 内置 |

第三方技能全集两处:`.claude/skills/mattpocock/`(tdd/diagnosing-bugs/codebase-design/implement 等)与 `.claude/skills/emilkowalski/`(animate/review-animations 等),工程开发规范参考按需取用,不逐条入表。

## 文档编写规范(三套,按读者选用)

- **doc-standards**:十判据,管删留/单源/避用词;任何交付文档写改审先用它
- **doc-style-human**(`.claude/rules/`):句法文风铁律;给人看的交付文档与 doc-standards 叠加
- **writing-for-agents**:结构与写法;给 agent 看的文档(AGENTS.md/SKILL.md)与 doc-standards 叠加

## 拉起指令(部署类,命令单源=本节)

```
claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
claude mcp add playwright -- npx -y @playwright/mcp@latest
claude mcp add context7 -- npx -y @upstash/context7-mcp
```

- ctx7 免装即用:`npx ctx7@latest library "库名" "问题"` → `npx ctx7@latest docs /org/project "问题"`;配额报错→`npx ctx7@latest login` 或设 `CONTEXT7_API_KEY`
- 命令以 D1-d 临时 clone 实测为准,实测日修正本节
- 人读完整步骤=CONTRIBUTING.md 环境节(D1-b 落地,指向本节)
