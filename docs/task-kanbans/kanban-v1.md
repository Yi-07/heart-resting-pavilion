# 心栖阁 · 跨会话执行看板 kanban-v1

> **职能**:多对话窗口接力的共享执行清单——步骤执行状态单源;勾选=已完成并 commit。
> **优先级**:新会话开工必读顺序 = CLAUDE.md → 本文 → 同目录 `handoff.md`;步骤状态与本文冲突时以本文为准(优于任何会话记忆)。
> **单源边界**:构建顺序/验收判据/命令单源 = CLAUDE.md §4/§8,本文只记执行状态与分派,不复制判据;完成一步的前提=跑过 §8 对应用例并停下汇报获人确认。

## 0. 工作方式(本看板的执行模式)

- 主会话只做:决策、编码(Edit/Write)、commit、看板与交接快照更新、向人汇报。
- 高噪音步骤派子 agent(Agent 工具)黑盒执行,主会话只回收结论,不进中间输出:
  - 跑后端三件套/前端检查 → 回收「过/挂 + 失败摘要(文件:行)」
  - 浏览器 E2E 验证(playwright 对真实前后端) → 回收「验收判据逐条命中/未中」
  - 大文件蒸馏(如 preview mockup 结构) → 回收结构化要点
  - 全库检索/多文件摸底 → 回收结论 + 文件:行号
- 依据:单窗口实测,工具中间输出(测试日志/浏览器快照/检索面)会快速吃掉主上下文并污染推理现场。
- 汇报纪律不变:每步完成停下汇报 → 人确认 → commit(勾选+handoff 同步)→ 继续。

## 1. 构建顺序(CLAUDE.md §8;每步=前后端联动切片)

- [x] 步骤1 契约类型(schema+messages.ts)· `6c58aae`
- [x] 步骤2 WS 网关最小版+危机闸门 · `f226fbb`
- [x] 步骤3 answer(种子语料真检索) · `324bf0a`
- [x] 步骤4 collect 多轮采集(逻辑层先验) · `07cc917`
- [x] 步骤5 黑板(SVG 渲染+视觉判据) · `089165e`
- [x] 步骤6 记忆(Redis 前置) · `c82a343`
- [x] 步骤7 Live2D · `fdeaa46`(附带 `1db9e72` 修 ws 重连链断裂,步骤2 遗留)
- [x] 步骤8 语音(ASR+TTS) · `e1251d6`
- [x] 步骤9 工具(station 懒生成·admin) · `0b5435e`
- [x] 排后·全量语料接入(队友 `dataset/` 已到位不入库;步骤9 后单做,走 `docs/data-contract.md` §4 回验替换 15 条种子——本项为看板级排程追加,非 CLAUDE.md §8 构建顺序成员)· 翻译层+bge-m3(见 PRD `docs/prds/rag-full-corpus-bge-m3.md`)

## 2. 步骤状态(排后·全量语料接入 已完成)

**完成情况**:排后·全量语料接入 已落地——翻译层(`dataset/all_base.md` → `backend/data/rag_corpus.jsonl` 14944 条四条字段)+ embedding 换 **bge-m3**(本地 `backend/models/bge-m3/`)+ reranker 本地化 + 分批 upsert。全量已 `ingest --reset` 灌入生产 `.rag_store`(`hrp_kb count=14944`)。方案详见 `docs/prds/rag-full-corpus-bge-m3.md`;测试口径见 `backend/tests/test_retrieve.py`(改 bge-m3 + 测试种子 `rag_retrieve_test_seeds.jsonl`)。

**验证**:test_retrieve 7/7、半量(均衡一半 7472 条)检索合并命中率 98.5%、ruff/mypy 全过。`test_memory` 需本机 Redis 6379(环境前提,非代码)。

### 待议(记录于此,不阻塞,后期再定)

- **answer 链路语义定位**:案例语料(`question=来访者问题 / answer=治疗思路`)与 seed(`question=知识问题 / answer=科普答案`)语义类型不同。受影响=`gateway.py:457`(answer 直答,科普口吻);`analysis.py:58`(collect 总结,case 适配良好);`planner.py:93`(station,case 适配良好)。当前 mock 掉 answer 直答,留后期再议。
- **RAG 冷启动预热**:bge-m3 冷启动重,over answer 60s 预算(遗留)。

## 3. 接力规程

1. 收尾窗口(达成交接点):更新本文勾选与 §2 → 重写 `handoff.md` 为最新现状 → 一并 commit → 告知人可开新窗。
2. 新窗口开工:读 CLAUDE.md → 本文 → handoff.md → 按本文 §0 工作方式继续当前步骤。
3. 任何窗口发现本文与代码实况不符:以代码+git 为准,当场修正本文(文档 bug 处理同 CLAUDE.md 冲突解决)。
