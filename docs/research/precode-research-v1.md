# 编码前研究 v1 · 待办与执行顺序

> **日期**:2026-08-28 · **性质**:决策记录(日志文档);新窗口按本文档执行编码前三阶段
> **上游**:仓库状况卡核实 + `doc-framework-research-v1.md` §7(议程原型) + CLAUDE.md §8(构建顺序·验收用例)
> **本文档角色**:编码前待办的唯一执行依据;执行完成后由 PROGRESS §二地图接管状态。

---

## 0. 真实性核对结论(状况卡 vs 实库)

- 提交链 6 笔属实(卡漏列 33b78f3"references 路径修补",在 911e15f 与 989c3fc 之间);HEAD=77daf9a,工作树干净。
- 结构属实:architecture/(小写)/docs 重组(research/×3+tasks-arrangement)/backend 骨架/backup/;地图 18 行、型录 11 型、CLAUDE.md 命令块新形态均核验通过。
- 卡片小误差:skill 实为 **13 件**(非 12,989c3fc 加 contributing 骨架);docs/adr/ 未实体存在,首篇 ADR 时建;根下空 workspace/ 未跟踪未使用。
- **排期关键事实**(tasks-arrangement):第一阶段交付日 08-23 **已过 5 天**;第一阶段交付物含**数据接口文档**(=地图 ⚠ data-contract,兼内部工件与交付物);数据集处理归蒋磊、刘俊江(=全量灌库主体)。

## 1. 阶段 0 · 环境(人做,option.md 承载操作细节)

| # | 事项 | 说明 |
|---|---|---|
| 0.1 | **venv 重建(最先行)** | 仓库目录改名(Mental-Health-Assistant→heart-resting-pavilion)致 `backend/.venv` 脚本 shebang 全指旧绝对路径,venv 已损坏;`rm -rf backend/.venv && uv sync` 重建 |
| 0.2 | Redis 容器 | option.md 步骤 2 |
| 0.3 | 前端 Node 升级+骨架+依赖 | option.md 步骤 3;**构建顺序的前提**(每步为前后端联动切片) |
| 0.4 | RAG 重排模型下载 | 可延至 answer 步前(answer 先向量检索跑通即够) |
| 0.5 | 检查点 0:git 提交 | option.md 收尾 |

## 2. 阶段 1 · 接缝定义会话(agent 做,一次会话;agenda v2)

| # | 事项 | 产出落点 |
|---|---|---|
| 1 | 后端接缝定义:RAG `refs` 形状 · gate GateResult 类型 · provider 抽象 · 采集事件联合 | backend-plan §2 接口列 + schema |
| 2 | 前端接缝核对:frontend-plan §4 关键签名逐个过(小而完整+错误模式) | frontend-plan §4 |
| 3 | 前端两缺口裁断:音频队列所有者 · 当前情绪所有者 | frontend-plan §2 表尾 [TODO] 转正 |
| 4 | 目录树规则落地核查 + ingest.py 归属 + **data-contract.md 转写**(接口约定会上已定缺转写;兼第一阶段交付物) | docs/data-contract.md |
| 5 | 类型单源:Formulation/FormulationKey 在 messages.ts 与 Pydantic 的对齐机制 | schema + messages.ts |
| 6 | 灰盒测试策略:接缝上钉测试(gate/sufficiency/retrieve/render/diff),不测内部——Pocock 闭环;**含分步冒烟:每步构建完成即跑 CLAUDE.md §8 对应用例,可 grep 判据过才算步完成** | 测试布局 |
| 7 | 深模块词汇约定(mattpocock:module/seam/depth/删除测试) | 协作词汇 |

**硬时序**:样本回验必须在队友(蒋磊/刘俊江)**全量灌库之前**——第一阶段已延期,数据集处理可能已在进行,本会话宜尽快开设。

## 3. 阶段 2 · 编码起步

**构建顺序**(前提=阶段 0+1 全部完成;走完=第一版软件功能,交付物另需交付前批文档):

契约类型(schema+messages.ts)→ WS 网关最小版+危机闸门 → answer(占位 refs 先跑通,不等全量灌库)→ collect(逻辑层先验)→ 黑板(补视觉判据)→ 记忆(Redis 前置)→ Live2D → 语音 → 工具(station 懒生成·admin)

- 验收=CLAUDE.md §8 三用例(crisis/answer/collect,可 grep 判据);分端细化=backend-plan §10(4 用例)/frontend-plan §7(3 用例)。
- 首个架构级决策发生 → 开 `docs/adr/0001-标题.md`(Nygard 五节+落选方案)。
- 编码纪律:改动面选跑验证(CLAUDE.md §4)· 文档同步挂件(§3.5)· **C1**(实现细节随骨架入 docstring 同 commit 出 plan §2 表)。
- README/CONTRIBUTING 编码完成后建(按职能维护)。

## 4. 名称统一记录(2026-08-28 裁定)

- 三形态:**心栖阁**(唯一中文名,文档/界面/图示统一全称,不用简称"心栖")· **heart-resting-pavilion**(仓库名)· **hrp**(服务标识缩写:service 字段 `hrp-backend`/`hrp-frontend`,pyproject name=`hrp-backend`)。
- 本轮清扫:三文档标题+option 提示词+preview 6 html(旧名 9 处+简称 12 处)+ws-contract service 值+pyproject name+CONTEXT 词条。
- 版本零残留(判据 1 演进):spec 标题与文件名的 v3 均去除(`architecture-spec.md`),版本完全归 git;全库引用同 commit 同步;研究记录历史引文保留(当时标题快照,保真)。
- 附加清扫:Redis 容器名 `mha-redis`→`hrp-redis`(mha=旧名缩写,容器未建零成本);option.md 提示词内复述的构建顺序改为指 CLAUDE.md §8(消双写)。

---

**新窗口执行顺序**:阶段 0(人做 0.1-0.5)→ 阶段 1(接缝会话,7 项)→ 阶段 2(按构建顺序,每步跑对应用例)。卡住→CLAUDE.md 护栏停下问人。
