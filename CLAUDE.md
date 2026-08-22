# 心理健康助手 · 项目规则(coding agent 共同查看维护)

> 本文件是 coding agent 的**开工前必读**。改代码前先读它;改架构先讨论,不直接改 spec。
> **护栏**:命令失败 / 依赖装不上 / 与契约冲突 / 需改架构 → **停下问人**,不静默换依赖或改架构。

---

## 1. 项目一句话 + 文档指针

面向轻中度情绪困扰人群的情感陪伴 + 心理知识科普工具(非医疗诊断)。技术原型阶段:跑通三路路由(危机/直接答/多轮采集)全链路。

| 文档 | 位置 | 性质 |
|---|---|---|
| 架构权威源 | `Architecture/architecture-spec-v3.md` | **只读**,改架构先讨论 |
| 前后端契约 | `Architecture/ws-contract.md` | **只读**,消息格式以此为准 |
| 前端方案 | `Architecture/frontend-plan.md` | 前端按此实现 |
| 后端方案 | `Architecture/backend-plan.md` | 后端按此实现 |
| 前端 UI/布局参考 | `Architecture/preview/l1-ui-mockup-v7.html` | 默认实现;接口固定、视觉可替换 |

## 2. 边界表(新代码写哪,旧代码别碰)

| 路径 | 职责 | 能否改 |
|---|---|---|
| `Architecture/` | 架构/契约/方案文档 | **只读**,改架构先讨论 |
| `backend/` | 后端(FastAPI+LangGraph) | 新代码落点 |
| `frontend/` | 前端(Vue3+Vite+TS) | 新代码落点 |
| `backend/app/schema/` | Pydantic 模型 | 与 ws-contract 对齐,改契约先改 ws-contract |
| `frontend/src/ws/messages.ts` | 消息类型 | 同上 |

## 3. 核心架构约定

1. **三路路由**:`crisis`(危机闸门,规则硬判,贯穿每轮)→ `answer`(直接答,知识走 RAG)/ `collect`(多轮采集)
2. **隔离约束**:`crisis/route` 只走规则,确定性;`emotion_label` 只喂黑板/Live2D,绝不进路由
3. **模板模型**:一个会话一个模板,粗稿/精稿**同一张图逐步深化**(表层→深层),数据填充;测试模板 3 个(`emotion_wheel`/`beck_formulation`/`stage_map`)
4. **契约要点**:8 种消息;`first_frame`=回合起点(前端清黑板);`draw` 传**全量 formulation** + `seq`(前端 diff);危机判定**只在后端**

## 4. 开发命令

```bash
# 后端（以下命令在 backend/ 目录下执行）
uv sync                                    # 装依赖
uv run uvicorn app.main:app --port 8000    # 启动
# 前端
cd frontend && npm install && npm run dev  # 启动
# 模型配置(环境变量)
LLM_PROVIDER=deepseek|ollama  DEEPSEEK_API_KEY=...  OLLAMA_URL=http://localhost:11434/v1
```

## 5. 代码风格(可执行规则)

1. **类型对齐契约**:前端 TS 类型 / 后端 Pydantic **必须**与 `ws-contract.md` 一致,禁止各定义一套;类型只定义一份,复用
2. **TS**:永不 `any`;不用 `Record<string, unknown>` 逃逸
3. **函数式优先**:纯函数、不可变数据;复杂操作拆具名辅助函数
4. **Python**:Pydantic 做数据校验;类型标注齐全
5. **错误集中处理**:WS 错误统一走 error 帧;日志用统一 logger

## 6. 性能热点(针对本项目)

1. **黑板渲染**:前端 diff 按字段,不做整树重建;动画按 seq 增量
2. **WS 消息**:不逐字转发,批量/采样;避免消息风暴
3. **RAG/LLM**:动态门控——普通/简单不走 RAG;知识查询才检索;LLM 每轮调用是成本热点,预置问题库优先于 LLM 生成

## 7. 日志与安全红线(硬约束)

1. **日志双输出**:控制台彩色可读(INFO)/文件结构化(DEBUG);loguru
2. **脱敏**:用户文本不落原文(记长度/哈希)· 音频绝不落库 · 凭证(AES-GCM 密钥/API key)绝不落
3. **危机审计**:危机命中必须落审计日志(WARN,含命中项+是否转热线,不含原文),不可省略
4. **安全**:危机判定只在后端;前端零危机逻辑;音频转写后即弃

## 8. 验收用例(技术原型,3 条)

**判据(可 grep)**：
1. **answer**:`什么是正念` → 直接答。判据:无 first_frame、无 draw 帧
2. **collect**:`最近很焦虑睡不着` → 第一帧 → 心情选择器 → 黑板粗稿 → 逐轮增量 → 精稿 → 分析总结 + 心灵补给站邀请语(方案书=用户点击心灵补给站触发生成)。判据:seq 单调递增;draw=粗稿+每轮增量+精稿;充分度≥0.7 停采;信念字段留白
3. **crisis**:`我不想活了` → 热线 + 支持画面 + 审计日志;不弹心情选择器。判据:日志 event=crisis_gate_hit(WARN) + 热线横幅 + 无心情选择器

**构建顺序**:危机闸门 → answer → collect(核心路由) → 黑板 → 记忆 → Live2D → 语音 → 工具

## 9. 工具与 Skill 提示

核心:ctx7(查库/框架文档,先 library 后 docs)· chrome-devtools/playwright(验证 HTML 预览)· emil-design-eng(动效)。完整清单见 `.claude/rules/tools.md`(@引用)。
