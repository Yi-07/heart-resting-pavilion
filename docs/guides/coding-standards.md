# 代码规范

> **职能**：跨文件的代码写法约定与性能约束单源，AGENTS.md「按任务先读·改码」指向此文档。约束所有或多个模块的写法（类型、结构、错误处理、性能）；单文件内部的实现细节以代码现状为准，不在此过多叙述。
> **术语**：深模块/浅模块网/接缝等术语定义见 [CONTEXT.md](../architecture/CONTEXT.md)「架构方法」。

## 类型

- 前端 TS 与后端 Pydantic 的类型对齐 [ws-contract](../architecture/ws-contract.md)；类型只定义一份，复用。
- TS 永不 `any`；不用 `Record<string, unknown>` 逃逸。
- Python 全量类型标注；入参出参过 Pydantic 校验。

## 结构

- 函数式优先：纯函数、不可变数据；复杂操作拆具名辅助函数。
- 深模块：新模块设计与重构按 [deep-module.md](deep-module.md) 判据执行，新模块开工必读。
- 重依赖（chroma、sentence-transformers、语音模型）函数内懒加载，不在模块顶部 import。

## 错误与日志

- WS 错误统一走 error 帧，不散落各 handler。
- 日志用统一 logger，不直接调 print/标准 logging。

## 性能热点

- 黑板渲染按字段 diff，不做整树重建；动画按 seq 增量。
- WS 消息批量/采样，不逐字转发，避免消息风暴。
- RAG/LLM 动态门控：普通/简单问题不走 RAG，知识查询才检索；预置问题库优先于 LLM 生成。
