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

### 第一版生产级制程(主线已完成,以下为到达「第一版软件应用」的分步)

> MVP 完整词表(单源)=`architecture/architecture-spec.md` §10;此处只列「未完成项 + 可交付性」,不复制词表。二期(spec §10)由用户新开 PRD,不排第一版,本看板不追踪。

#### A. 生产级验收前置(功能可用 + 可复现)

- [x] 1. **answer 链路语义定位定论→混合知识库分流**:案例语料(case=来访者问题/治疗思路)与 seed(科普=知识问/科普答)语义类型不同。定论=answer 直答查「科普知识库」(当前 15 条种子垫底,内容后续 PRD 扩),collect/station 查「案例库」(14944 条)。engine 拆 `hrp_kb_knowledge`+`hrp_kb_case` 两 Chroma 集合,retrieve/ingest 加 `library` 参数(深模块);answer 链打通。test_gateway 15/15 + test_retrieve 8/8 + ruff/mypy 过;store 两库齐全(14944+15)。
- [x] 2. **前端设置面板(模型配置 + 记忆治理)**:GET /admin/config 读口(契约 §1 同步)+ 设置面板(预填/分段药丸/保存 + 趋势/一键清除两步确认)。附带完成 UI 范式定稿与正式化(状态 chip/液芽输入条/薄玻璃材质,范式=`preview/l1-ui-taste.html`,规格与冲突裁定见 frontend-plan)。test_admin 9 + 前端 69 用例全绿;E2E 设置面板判据+三路链路回归通过。
- [ ] 3. **模型下载脚本入库**:新克隆需 curl 重建 bge-m3/reranker(`backend/models/` gitignore);下载脚本未入库(见 PRD Further Notes)。
- [ ] 4. **RAG 启动 warm-up 预热**:bge-m3 冷启动重,超 answer 60s 预算;涉后端启动行为,做前打招呼。
- [ ] 5. **`npm run l2d:fetch` 命令可见性**:业务 script 单源=package.json 已收录;CLAUDE.md §4 命令块是否补,重审。

#### A.5 架构改造·记忆分层(ADR 001 `MemoryTiering`,已审定通过)

- [ ] **记忆分层落地(近期原始轮次/长期摘要)**:ADR 001 定案——热层改存 `recent_turns` 原始轮次(短TTL 30min)+精修「原始文本只短留」隐私边界;重连读 recent_turns 重建 `CollectState.turns`。涟漪=spec §4 L7 + §9.4 · `state.py`(`SessionContext` 加字段)· `memory/store.py`(热层结构)· `gateway.py`(重连重建)· 测试补重连一致用例。**与 A#2 解耦,独立落地**。

#### B. 生产级验收

- [ ] 6. **后端 §8 三用例 E2E 完整验收**:answer/collect/crisis 真链路(含 collect 完整链 + 心灵补给站触发),作生产级最终验收。

#### C. 交付产物(验收通过后)

- [ ] 7. **README / CONTRIBUTING 建立**:PROGRESS 文档地图标「编码后建立」,当前缺——验收通过后补,交付阶段产出。
- [ ] 8. **人看架构文档 + AGENT.md 副本**:PROGRESS 标「交付前批」,验收通过后、交付前补。

## 3. 接力规程

1. 收尾窗口(达成交接点):更新本文勾选与 §2 → 重写 `handoff.md` 为最新现状 → 一并 commit → 告知人可开新窗。
2. 新窗口开工:读 CLAUDE.md → 本文 → handoff.md → 按本文 §0 工作方式继续当前步骤。
3. 任何窗口发现本文与代码实况不符:以代码+git 为准,当场修正本文(文档 bug 处理同 CLAUDE.md 冲突解决)。
