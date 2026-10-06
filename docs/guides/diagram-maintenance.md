# 图表维护指南

> **职能**：docs/diagrams/ 图表产物何时更新、怎么更新。架构事实本身见根目录 ARCHITECTURE.md。

## 存什么

docs/diagrams/ 下每张图两个文件成对：`<名称>.html`（交互源，浏览器打开可缩放）与 `<名称>.svg`（导出版，被 ARCHITECTURE.md 内联引用）。生产环境 `workspace/`（uv＋playwright）不入库。

## 何时更新

- 组件关系、链路流向、交互次序发生改动：同批次更新对应图表。
- 仅参数、数值、提示词类改动：不触图（图中本就不含参数）。
- 图与代码冲突：以代码为准，当场修图。

## 怎么更新

1. 改 HTML 源（diagram-design skill 产物，节点边预算与样式判据以 skill 为准，skill 在 `.claude/skills/diagram-design/`）。
2. 跑导出：在 `docs/diagrams/workspace/` 下 `uv run python export_svgs.py`，成对刷新 SVG。
3. 自检：`uv run python .claude/skills/diagram-design/scripts/self_check.py <文件>`，两份都过再交付。
4. 视觉验证：浏览器打开改后 HTML，核对连线不穿节点、标签不压线、节点无重叠。

## 改动面速查

| 改了什么 | 触碰哪张图 |
|---|---|
| 网关/闸门/链路分流/危机升级 | architecture-overview |
| 新增 WS 消息或交互环节 | session-lifecycle（消息字段不画，指 ws-contract） |
| 组件增删（如新支撑服务） | architecture-overview |
| 契约字段、TTL、提示词 | 都不触 |
