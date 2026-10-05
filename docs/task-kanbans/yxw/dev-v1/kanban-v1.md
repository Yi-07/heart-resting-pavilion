# 心栖阁 · 跨会话执行看板 kanban-v1

> **职能**:多对话窗口接力的共享执行清单——步骤执行状态唯一记录处;勾选代表已完成并 commit。
> **优先级**:新会话开工必读顺序:CLAUDE.md(即 AGENTS.md)→ 本文 → 同目录 `handoff.md`;步骤状态与本文冲突时以本文为准(优于任何会话记忆)。
> **单源边界**:构建顺序/命令/构建验收判据见 `AGENTS.md`,业务测试判据唯一记录处见 `docs/tests/acceptance-v1.md`(B1 产出),本文只记执行状态与分派,不复制判据;完成一步的前提:跑过对应用例并停下汇报获人确认。
> **路径**:本看板在 yxw/dev-v1/(人名/任务两级结构);全库指针已同步。

## 0. 工作方式(本看板的执行模式)

- 主会话只做:决策、编码(Edit/Write)、commit、看板与交接快照更新、向人汇报。
- 高噪音步骤派子 agent(Agent 工具)黑盒执行,主会话只回收结论,不进中间输出:
  - 跑后端三件套/前端检查 → 回收「过/挂 + 失败摘要(文件:行)」
  - 浏览器 E2E 验证(playwright 对真实前后端) → 回收「验收判据逐条命中/未中」
  - 大文件蒸馏(如 preview mockup 结构) → 回收结构化要点
  - 全库检索/多文件摸底 → 回收结论 + 文件:行号
- 汇报纪律不变:每步完成停下汇报 → 人确认 → commit(勾选+handoff 同步)→ 继续。

## 1. 主线构建(全部完成)

步骤1-9(契约类型→WS 网关→answer→collect→黑板→记忆→Live2D→语音→工具)+ 排后·全量语料接入(bge-m3,14944 条)全部完成。逐项实现/验证细节见 git log 的详细 commit message(git show <hash>);决策背景见 `docs/architecture/ARCHITECTURE_PROGRESS.md`。

## 2. 第一版交付待办

### A. 遗留问题完善

- [x] **A1 危机核心词表扩充**:核心 9→23、软 5→10,词表逐条入 `gate.CORE_TERMS/SOFT_TERMS` 并配测试。(B2 批补 3 条消失族核心词,现行 26+10)
- [x] **A2 prototypes/tts-latency 归档**:e2e_lib+两轮 E2E 脚本迁 `backend/tests/e2e/`;freeze 两文件留 `backend/scripts/`;bench/FINDINGS/运行日志删。
- 注:~~RAG 启动 warm-up 预热~~ 已随 ADR-003 落地;~~模型下载脚本~~ 并入 D1。
- [x] **A3 语音输入两步式(ADR-004)**:录音→转写→确认后按文本发送;`user_input` 删 audio 字段,语音故障与 WS 解耦。
- [x] **A4 对话回放与小结卡片(ADR-001 落地与 ADR-005)**:热层 recent_turns+重连重建;契约新增 `replay` 帧;前端身份持久化+幕布/小结卡组件。

### B. 业务测试(新窗口执行)

- [x] **B1 验收清单建立**:清单文档见 `docs/tests/acceptance-v1.md`(判据载体),看板只挂状态;双用例原则(三链路+门控场景各配简单+复杂两条话术)。
- [x] **B2 完整三链路业务测试**:answer/collect/crisis 全链实况过 acceptance 全节;既有 8 脚本回归+新写 7 个 e2e3 脚本+浏览器交互两段;遗留待办见 backlog。

### C. code review

- [x] **C1 全库代码审查**:审查快照与逐条处置见 `docs/tests/reviews/c1-review.md`;留档/待裁项见 `docs/todos/backlog.md`。

### D. 交付文档(部署配置并入此处)

- [x] **D1-a 全库文档摸查**:18 项问题清单+.env 逐键核对,报告见 `docs/tests/reviews/d1a-survey.md`。
  - [x] **D1-b 文档体系定稿**:单根 `docs/` 树状递归分类;渐进式披露链:根 4 入口+CLAUDE.md 薄壳+docs 树;逐份流程:大纲→人审砍多余→正文→人审精修→交付。
  - [x] **D1-c 写作规范(两套)**:人看文档走 doc-style-human+doc-standards 十判据叠加;agent 看文档走 writing-for-agents 方法学。
  - [x] **D1-d 一键就绪**:option.md 全量安装单路径;模型 --local-dir 落到 `backend/models/`;freeze 两参照入 `backend/scripts/`;剩余两项(Redis compose/临时 clone 实测)迁 backlog §4。
  - **验收标准**:文档分类规整(单根树+渐进式披露链成立);内容逐份过人审精修;配置与散落环境配置收集完善;按文档从零操作能正常部署并使用本项目。
- [x] **D2 交付批核对**:PROGRESS 头注/文档地图/二期表刷新;backend-plan 数值复写压缩为指针;spec/双 plan 头注补「不管面」声明;.env.example 补缺失 2 键。ADR 状态核对 5 篇与 git 实况一致。

- [ ] **推远程后第一批(详情见 `docs/todos/backlog.md` §4)**:①Redis compose 一次拉起(替换 option §2.1)②临时目录 clone 按 option.md 全流程实测。git remote 已配置(origin=github.com/Yi-07/heart-resting-pavilion),推增量即可。

## 3. 待办池(已迁出,防双单源)

待办内容唯一记录处见 `docs/todos/backlog.md`(C1 审查留档项+裁定残项+原待办池统一管理;二期范围见 `docs/architecture/ARCHITECTURE_PROGRESS.md` §四)。本节不再维护条目。

## 4. 接力规程

1. 收尾窗口(达成交接点):更新本文勾选与 §2 → 重写 `handoff.md` 为最新现状 → 一并 commit → 告知人可开新窗。
2. 新窗口开工:读 CLAUDE.md(即 AGENTS.md)→ 本文 → handoff.md → 按本文 §0 工作方式继续当前步骤。
3. 任何窗口发现本文与代码实况不符:以代码+git 为准,当场修正本文(文档 bug 处理同 AGENTS.md 冲突解决)。
