# 心栖阁 · AGENTS.md

> **职能**:coding agent 开工前必读——开发规范单源,细则按指针按需加载。改代码前先读完本文;改架构先讨论,不直接改 spec。
> **护栏**:命令失败 / 依赖装不上 / 实现与契约冲突 / 需改架构 → **停下问人**,不静默换依赖或改架构。

**冲突解决**:消息/字段矛盾 → 以 ws-contract 为准;机制/参数矛盾 → 以 spec 为准;历史与现行并存 → 以 spec 正文为准。矛盾 = 文档 bug:属上列三类 → 改输家文档对齐赢家后继续编码,并报告改动;三类之外 / 同文自相矛盾 / 赢家本身存疑 → 停下问人。

**文档同步**:改公共行为/接口 → 检查 ws-contract/spec 对应节;改工具链/依赖 → 查 §3 命令块是否失真。

## 1. 文档与边界

- 文档全索引 = `docs/README.md`;新文档落点规则在彼处尾部
- 只读权威 `docs/architecture/`:spec(机制/参数)· ws-contract(消息格式)· 双 plan(实施方案)· CONTEXT(术语)· PROGRESS(决策历史);改先讨论
- 判据与状态:验收判据=docs/tests/acceptance-v1.md · 执行状态=docs/task-kanbans/kanban-v1.md(+handoff)· 决策记录=docs/adr/ · 数据契约=docs/architecture/data-contract.md
- 新代码只落 `backend/` 与 `frontend/`;契约改动先改 ws-contract,backend/app/schema/ 与 frontend/src/ws/messages.ts 跟随
- 原型/探查/中间产物 → 项目根 `prototypes/`(整目录 gitignored,不入库),不散落项目各处

## 2. 核心架构约定

1. **三路路由**:每条 user_input 先过 `crisis` 危机闸门(规则硬判,确定性,贯穿每条输入)→ `answer`(直接答,知识走 RAG)/ `collect`(多轮采集)
2. **隔离约束**:`crisis/route` 只走规则;`emotion_label` 只喂黑板/Live2D,绝不进路由
3. **模板模型**:一个会话一个模板,粗稿/精稿同一张图逐步深化(表层→深层)

契约速览 = ARCHITECTURE.md §3 · 格式 = ws-contract §2 · 机制参数 = spec §3-§8

## 3. 开发命令

**后端**(`backend/` 目录下,uv 管依赖):
```bash
uv sync
uv run hrp                # 启动(默认 127.0.0.1:8000;--reload 热载开发,配 TTS_SIDECAR_KILL_ON_EXIT=0)
                          # 自动拉起并版本握手 TTS sidecar,退出有序关停;手动起 sidecar 可选
uv run ruff check app
uv run mypy app
uv run pytest
uv run python -m app.rag.ingest   # 语料 jsonl 变更后重灌 Chroma;--reset 清空重建
```

**前端**(`frontend/` 目录下):
```bash
npm install
npm run dev
npm run test:unit
npm run type-check
npm run lint
```

**模型配置**:环境变量,单源=`backend/.env.example`(provider 切换/密钥/Redis)。
**收录判据**:只收启动/验证入口与带约定语义的命令;业务 script 单源=package.json/pyproject,不复制;新约定命令随引入同 commit 收录。
改动后验证清单单源 = CONTRIBUTING.md「改动后验证」。

## 4. 代码风格

1. **类型对齐契约**:前端 TS / 后端 Pydantic 与 ws-contract 一致;类型只定义一份,复用
2. **TS**:永不 `any`;不用 `Record<string, unknown>` 逃逸
3. **函数式优先**:纯函数、不可变数据;复杂操作拆具名辅助函数
4. **Python**:Pydantic 校验;类型标注齐全
5. **错误集中处理**:WS 错误统一走 error 帧;日志用统一 logger
6. **深模块**:设计基准单源 = `docs/guides/deep-module.md`,新模块开工必读;新增重依赖(chroma·sentence-transformers·语音模型)用函数内懒加载,勿在模块顶部 import 拖慢启动

## 5. 性能热点

1. **黑板渲染**:按字段 diff,不做整树重建;动画按 seq 增量
2. **WS 消息**:批量/采样,不逐字转发;避免消息风暴
3. **RAG/LLM**:动态门控——普通/简单不走 RAG,知识查询才检索;预置问题库优先于 LLM 生成

## 6. 日志与安全红线(硬约束)

1. **日志双输出**:控制台彩色可读(INFO)/文件结构化(DEBUG);loguru
2. **脱敏**:用户文本不落原文(记长度/哈希)· 音频绝不落库 · 凭证(AES-GCM 密钥/API key)绝不落
3. **危机审计**:危机命中必落审计日志(WARN,含命中项+是否转热线,不含原文),不可省略
4. **安全**:危机判定只在后端;前端零危机逻辑;音频转写后即弃

## 7. 验收冒烟(3 条)

改链路后快速验证;单条话术、可 grep。话术与判据单源 = docs/tests/acceptance-v1.md。

1. **answer**:`什么是正念` → 无 first_frame、无 draw 帧,直接流式答
2. **collect**:`最近很焦虑睡不着` → first_frame → 心情选择器 → 黑板粗稿 → 逐轮增量 → 精稿 → 总结+补给站邀请语
3. **crisis**:`我不想活了` → 热线+支持画面+审计日志(WARN),无心情选择器

**构建顺序**(每步=前后端联动切片):契约类型(schema+messages.ts)→ WS 网关最小版+危机闸门 → answer → collect → 黑板 → 记忆 → Live2D → 语音 → 工具(station 懒生成·admin)

## 8. 工具与 Skill 提示

- 核心:ctx7(查库/框架文档拿最新信息数据)· chrome-devtools/playwright(验证 HTML 预览)。完整清单见 `.claude/rules/tools.md`(@引用)。
