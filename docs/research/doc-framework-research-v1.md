# 文档框架研究 v1 · 生成侧补全与项目实践定案

> **日期**:2026-08-25~26(grilling 会话) · **性质**:决策记录(ADR,日志文档,日期叙事合法)
> **状态**:**全部定案,待执行**——新窗口直接按 §8 执行顺序动工,无需重议。
> **上游**:`docs/research/doc-standards-research-v1.md`(十判据来历)· `.claude/skills/doc-standards/SKILL.md`(现行审查侧)
> **本文档角色**:本会话 grilling 的完整产出存档 = skill 重构与项目实践的**唯一执行依据**。

---

## 1. 问题对齐(两轮修正的最终形态)

进场表述"skill 效果和文档规范化效果不好"经质询证伪。真问题:

| 缺失 | 含义 | 解法归属 |
|---|---|---|
| **基线缺失** | 未学过软件工程,不知道业内文档标配,缺了什么无从对照 | 核心型录(业内正型) |
| **工艺缺失** | 内容在脑中,但编排(给谁看/怎么分层)、每份骨架怎么搭,无工程经验 | 文档地图模板+类型骨架 |

**目标**:①skill 升级为个人可移植的文档规范工作流(生成相位从无到有+审查相位保留)②用它实践当前项目。skill 定位=**个人/小团队域**,不做企业全景。

---

## 2. 一手调研(九源,全部原文抓取)

| 来源 | 关键收获 | 去向 |
|---|---|---|
| [Diátaxis](https://diataxis.fr/) 官网 | 四象限+判别罗盘:**行动/认知 × 学技能/用技能**;官方用法="拿真实文档问题套用" | 地图格子·人向语气卡 |
| [C4 model](https://c4model.com/) | 层级抽象+补充图(dynamic/landscape/deployment);notation 无关 | 人看架构文档范式;spec §3≈dynamic 图 |
| [Nygard ADR 原文](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)+[adr.github.io](https://adr.github.io/) | 五节结构;superseded 保留不复用编号;"**Large documents are never kept up to date. Small, modular documents have at least a chance**" | Q7 向前采用 |
| [arc42](https://arc42.org/) | 12 章模板确认;对本项目过重 | **不采用**(裁定记录) |
| Pocock 视频字幕("Your codebase is NOT ready for AI",2026-02-26,webReader 抓) | 反模式=**浅模块网**(非"没用深模块");深模块=杠杆率;接缝=品味施加点;灰盒=测试锁行为交实现给AI;渐进式披露=深模块**读起来的样子**,非本质 | Q9α′·代码会话议程 |
| [sandcastle](https://github.com/mattpocock/sandcastle)(AGENTS/CLAUDE/CONTEXT 原文) | 验证命令第一行;changesets 版本硬机制;CONTEXT.md 与我们同构(独立发明互相验证);极简指针派(~20行) | 三源对照·版本裁定 |
| [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)(AGENTS.md 31KB 全读) | **Repository layout=包级一行职责,非文件树**(Q9 外部实证);conventions 每条带理由链接;"**Wire mechanically checkable invariants into an executed top-level gate**"(机械可查进闸门,语义留规则);验证 evidence-matching;CLAUDE.md symlink AGENTS.md | Q9α′·挂件1-3·版本硬机制 |
| Anthropic 官方([best practices](https://code.claude.com/docs/en/best-practices)) | <200 行;排除清单(**changelog/历史/常变信息/逐文件描述**不进);IMPORTANT 全文一处 | 挂件合法性·CLAUDE.md 型骨架 |
| [shuorenhua](https://github.com/MrGeDiao/shuorenhua)(README 全读) | **保真合同**:数字连修饰对象保留·关系不改写("展示潜力"≠"采用了")·范围/条件/否定/情态即事实·抽象不擅自具体化·缺口指出不补;**句式段落模式优先,词表只兜底**;场景包;bounded 档=整句空话进待确认清单 | 人向风格节主源 |
| [blader/humanizer](https://github.com/blader/humanizer)(README 全读) | 上游=Wikipedia《Signs of AI writing》(WikiProject AI Cleanup 维护);35 模式中可迁移中文技术文的子集;"写旧版本史"模式与墓志铭判据同源 | 负面模式清单补充 |

**明确不采纳**(防复议):OUBIGFA 硬禁词路线(禁"而是"伤技术文精确性,且 shuorenhua 自己反对词表硬洗)· rnskill 整包安装(与 doc-standards 双入口冲突,只提取思想)· voice 风格复现 · PowerShell/Node 审计脚本(grep 完成判据已够,过度工程,同 pre-commit hook 裁定逻辑)。

---

## 3. 定案总表(17 项,审核通过)

### A 线 · skill 设计

| # | 定案 |
|---|---|
| A1 | **单 skill 双相位**:入口判"这份文档存在吗"→不存在走生成流程/已存在要改走十判据审查;名不改 |
| A2 | **生成侧三层**:核心型录(~10 型,**双来源**=业内正型∪本项目验证过的工作集;每型三栏:是什么·触发器·骨架指针)+触发器制文档地图模板(状态列可机械核验,触发列=文本判断)+骨架库收 `references/` |
| A3 | **生成流程**:扫触发器(问:项目什么状态?谁要用?)→呈缺项清单→用户点头→照骨架逐份生成→十判据自查收尾 |
| A4 | **人向文档风格节**(见 §6)——补掉"人看文档写作无裁定"空白 |
| A5 | **soft dependency 声明**:无 CONTEXT.md 的项目跳过避用词 grep,其余判据照常(dsh ADR-0001 hard/soft 分拆工艺) |
| A6 | **先不搬家**:skill 留项目级,当前项目行为验证成功后再决定迁用户级;届时 cases.md 留项目,增长环改双出口(泛化→判据表;项目特有→案例库) |

### B 线 · 当前项目实践

| # | 定案 |
|---|---|
| B1 | **文档地图落 PROGRESS §二**(全量行集见 §5.1);CLAUDE.md 保持纯指针 |
| B2 | **README 缓建**:触发器=推仓共享那一刻;定位=团队枢纽四块(项目状态/开发文档指路=地图的人侧导览/代码库概览/团队协作规则 PR·review);CONTRIBUTING 拆分触发器=协作节挤压其他块 |
| B3 | **数据契约 ⚠**:接口已在会上定了,缺转写不缺约定;移交代码会话(见 §7);本会话只在地图留格 |
| B4 | **ADR 向前采用**:存量 PROGRESS §六不拆转只读台账;新架构级决策起走 `docs/adr/NNN-标题.md`(Nygard 五节+**落选方案节**[Pocock 实例]);判别线=动了机制/参数/契约才算架构级(纯实现细节不需要);决策发生当下记,agent 起草用户过目 |
| B5 | **人看架构文档**:交付前批;形态=C4 Context+Container(mermaid)+可选 dynamic(三路路由图示化)+设计叙事(references.md 展开);硬规则=**派生不复制**,数值一律指向 spec |
| B6 | **目录树单源 α′**:`backend-plan §2`/`frontend-plan §2` 的文件级树**立即**变形为语义化模块职责表(规格见 §5.3);此后文件增删改不回 plan,职责变化才改行;风格法则不死("一职能一深模块目录·删除测试·文件不散放 app 根");命名按各语言社区惯例,文档只写偏离默认的约定(no-op 检验) |
| B7 | **CLAUDE.md 三挂件**(diff 见 §5.2):验证路由行·文档同步两行·ADR 指针行 |
| B8 | **AGENT.md**:复制+头部注"真源=CLAUDE.md",交付时才做(交付清单含 Agent.md) |
| B9 | **版本硬机制零新增**:git 真源(tag=log 入口)/判据1/grep 闸三层已齐备;pre-commit hook 不做(单人项目过度工程) |

### C 线 · 执行中的关键修正(审核轮发现)

| # | 修正 |
|---|---|
| C1 | **载重事实过渡期安置**(α′ diff 自查发现的一步搬家隐患):原树注释里的细节分拣两类——**接口相关事实**(调用方须知,如 asr 的 `ffmpeg 转码 webm/opus→wav16k`、转写即弃)=**永久留在职责表接口列**;纯实现细节=代码落地那天随骨架写入该模块 docstring、同 commit 出表(一步搬家排期到那时,不是现在)。禁止"现在删旧家、docstring 新家还没出生"的半步迁移 |

---

## 4. 涟漪扫描(α′ 环境真源原则确立后,既有裁定的免疫确认)

| 对象 | 判定 | 理由 |
|---|---|---|
| spec / ws-contract | ✓ 免疫 | 它们**先于代码存在**,是实现的设计源;方向相反(环境是产物),不属于复述环境 |
| CLAUDE.md §4 命令块 | ✓ 已合规 | 此前已立纪律:环境可查的删(package.json scripts agent 自己能读),约定不说的留(端口/env/uv 用法) |
| C4 人看架构图(B5) | ✓ 免疫 | 画容器关系与数据流(部署拓扑),`ls` 查不出关系图 |
| PROGRESS §二地图 | ✓ 同构 | 状态列本来就是存在性检查 |
| 泛化候选 | ➕ 入 skill | "文档不复述环境可自查的事实"=判据5(数值路径单源)的推广,进判据表或 cases 先例 |

---

## 5. 待落地工件的具体形态(执行时照抄)

### 5.1 文档地图行集(落 PROGRESS §二,替换现"增量清单")

| 文档型 | 触发器 | 状态 |
|---|---|---|
| CLAUDE.md | 用 coding agent | ✓ |
| spec(HLD,`architecture-spec-v3`) | 架构想清楚 | ✓ |
| 实施方案(LLD,frontend/backend-plan) | 对应端开工 | ✓ |
| 接口契约(ws-contract) | 两端分离协作 | ✓ |
| 术语表(CONTEXT.md) | 命名分歧出现 | ✓ |
| 环境/操作手册(option.md) | 有人要跑起来 | ✓ |
| 进度/恢复台账(PROGRESS) | agent 跨会话工作 | ✓ |
| 答辩溯源(references.md) | 评审场景 | ✓ |
| 决策记录(`docs/adr/NNN`,B4) | 架构级决策发生 | ✓机制就绪,首篇待首个编码期决策 |
| 数据契约(`docs/data-contract.md`) | 数据生产者≠消费者 | ⚠ 移交代码会话(§7) |
| README | 推仓共享 | △ 交付前批(B2) |
| 人看架构文档 | 交付演示 | △ 交付前批(B5) |
| AGENT.md 副本 | 交付要求含 Agent.md | △ 交付前批(B8) |
| 研究记录(`docs/research/` 下 *-research-*.md) | 专题调研发生 | ✓ |
| UI 参考(`preview/l1-ui-mockup-v7.html`) | 前端 UI 实现 | ✓ |
| 备忘录(`docs/Inspiration.txt`) | 随手记 | ✓ 人看 |

**域外脚注触发表**(一行一型,何时才需要):LICENSE/SECURITY=开源或公开产品期 · CHANGELOG=对外发版(git tag 即内部替代)· runbook=多环境部署 · tutorial=产品有外部学习者 · PRD=多干系人需求谈判 · 正式 RFC=团队扩大需评审流程 · CONTRIBUTING=README 协作节挤压。

### 5.2 CLAUDE.md 三挂件 diff

```diff
(§4 bash 块之后追加)
+ **验证路由**:改后端→`uv run ruff check app`·`uv run mypy app`·`uv run pytest`
+ (测试建立前空跑即绿);改前端→`npm run typecheck`·`npm run lint`(前端骨架后生效);
+ 改文档→doc-standards 十判据+收尾 grep

(§3 核心架构约定追加第 5 条)
+ 5. **文档同步**:改公共行为/接口→检查 ws-contract/spec 对应节是否需同步;
+    改工具链/依赖→查 §4 命令块是否失真

(§1 表格末尾追加行)
+ | 决策记录(向前) | `docs/adr/NNN-标题.md` | 架构级决策定案时新建一篇;存量查 PROGRESS §六(只读) |
```

净增 ~4 行(<200 红线富余)。AGENT.md 本会话不动。

### 5.3 plan §2 变形规格(两端同型)

**表头两行**(法则保留+新声明):

> 目录风格(原样保留):一个职能一个深模块目录——小接口藏大行为,通过删除测试;文件不散放 app 根。
> **文件真源=文件系统**:本表只记职责与接口;文件增删改不回本表,**职责变化才改行**;接口相关事实留接口列(C1),纯实现细节由代码落地时入 docstring。

**backend 行集**(14 行):

| 模块 | 职责 | 关键接口 |
|---|---|---|
| app/main | 入口装配 | 挂 /ws·/station·/admin |
| ws_gateway | 连接/发号/抢占 | 每条 user_input 先过闸门;S→C 帧统一盖章即发(发号与帧映射=§8) |
| admin | 管理通道 REST | — |
| config | 模型配置 | LLM/ASR/TTS 读环境变量;config 传递 emitter |
| logger | 日志与审计 | 双输出+危机审计(§9) |
| router | 闸门+分类+话术 | gate.check(text)→GateResult · classifier→{route,label,conf} · phrases=预设话术库(安抚/承接/邀请/危机,不经 LLM);隔离约束=spec §4 L3 |
| collect | 采集三件 | 预置问题库/充分度(sufficiency(f)→float)/三降级检测;管状态不管话术=spec §4 L4 |
| agents | 图编排+共享黑板 | CollectState 14 字段(§3,answer/collect 共用)·确定性条件边分派;Agent 名单=spec §4 L5 |
| rag | 检索三件套 | retrieve(query)→refs;Chroma+bge-small-zh·BM25+jieba·bge-reranker;灌库策略=§7(**归属待代码会话裁**,唯一悬空行) |
| llm | LLM 双源 | OpenAI 兼容统一入口(config 切换) |
| memory | 热/温/冷记忆+治理 | 层介质与 TTL 单源=spec §4 L7(数值不复制) |
| voice | 语音引擎 | ASR(SenseVoice;ffmpeg 转码 webm/opus→wav16k,只取文本,音频即弃)·TTS(念=开场安抚/总结+邀请/危机;失败跳过音频文字照常收尾)·fillers=预生成等待语音(同音色切块直发) |
| station | 补给站 REST+方案书存取 | 端点单源=ws-contract §1;懒生成素材 station:input(§3.3) |
| schema | 契约类型单源 | Pydantic 对齐 ws-contract |

**frontend 行集**(8 行+占位):ws(connect/on/send;messages 对齐 ws-contract)· board(render(templateId,data,seq)·diff·registry;粉笔效果=实现细节;声明类型见 §5.1)· mood · l2d(pixi 钉子在 §1,不重复)· chat · station · state(transition(event),§3)· logger。**原样保留**(§2 非文件清单的段落):工具栏范围·UI 参考·交互模式·插件化四段。

> [TODO] 前端表尾占位两行(代码会话议程③裁完后入表):音频队列所有者 · 当前情绪所有者。

### 5.4 skill 重构清单(doc-standards)

```
SKILL.md 结构(重构后):
  description(更新:补"新建项目/新文档生成"触发词)
  适用分叉(保留:交付/日志)
  相位分叉(新增,A1/A3):文档不存在→生成流程;否则→审查流程
  生成流程(新增,A2/A3):扫触发器→呈缺项清单→点头→照 references/ 骨架生成→十判据自查
  受众分叉(新增,A4,~10行内联):谁读?agent→十判据全量;人→通用子集(判据5/6 照用,
    防漂移不管文风)+human-style.md
  执行流程(保留5步+补完成判据:步骤1-4 各加一句 done 条件,writing-for-agents)
  soft dependency(新增,A5):无 CONTEXT.md→跳过避用词 grep 并注明,其余照常
  十判据(保留;判据6 首句改写=旧欠)
  增长环(改双出口:A6 预埋)
references/(披露层):
  human-style.md(§6)· type-skeletons/(每核心型一份:adr.md 五节+落选方案/
  readme.md 四块+第一屏三问/claude-md.md 三源对照要点+hld-lld.md+contract.md+
  data-contract.md 占位 glossary.md CONTEXT 式+progress.md+env-howto.md)
cases.md:先 grep 核对库再补——**判据 6 首句已是新句,跳过不改**;旧欠实为 3 行
  (代码标识符不进 spec·轻量分类器入避用列·AGENTS.md 单工具不建);追加本次 5 项:
  命名no-op注脚·环境真源判例(目录树)·版本硬机制三层确认·数据契约[TODO]格·接口事实vs实现细节分拣(C1)
补研三件(执行中做):agents.md 标准(agentsmd.net 一手)· README 规范择一
  (standard-readme vs makeareadme)· mattpocock SKILL-MECHANICS.md
  (路径:plugins/cache/claude-plugins-official/mattpocock-skills/*/skills/productivity/writing-for-agents/)
```

### 5.5 人向风格节(human-style.md 最终结构)

```
0. 保真合同(最高律,先于一切风格)[源:shuorenhua]
   数字连修饰对象一起留 · 关系不改写(潜力≠采用)· 范围/条件/否定/情态即事实 ·
   抽象不擅自具体化 · 缺信息指出缺口不补
   ※ 与十判据同 DNA 的人类侧镜像(数字↔判据5·渲染词↔判据3)——节首注明,
     防被误当作另一套标准
1. 四型语气卡(Diátaxis)+场景包要点
   Tutorial:第二人称·开头承诺结果·每步可验证·原理不提前讲
   How-to:标题=任务名·假设已上手·步骤编号·前置一行
   Reference:零叙事零人称·条目同构·可扫读;API/reference 场景护端点字段
     状态码(与 ws-contract 纪律同构)
   Explanation:回答为什么·允许取舍观点·标题写成论点·不夹操作
   README 第一屏三问:是什么/给谁用/解决什么 [源:shuorenhua scene pack]
2. 负面模式清单 [源:自拟7条+Wikipedia Signs of AI writing 经 humanizer]
   空洞总结段(综上/总之+复述)· 强制三连排比 · "值得注意的是"起手 ·
   不可证伪赞美词(强大/完善/优雅)· 散文段强行分点 · 元叙述(本文将介绍)·
   不是X而是Y壳 · 标题下复读 · 写旧版本史(墓志铭判据人类侧)· 伪深刻总结 ·
   没人问的辩解 · 万能正面结尾
3. 执行顺序:句式段落模式先行,负面词 grep 只兜底 [源:shuorenhua 方法论]
4. 完成判据:可 grep 负面词零命中;整句空话不直删→进"待确认清单"呈人
   (=存疑停下问护栏的人向版,bounded 档思想)
```

---

## 6. 版本硬机制确认(B9,调研结论存档)

三方一致:官方排除清单明文(changelog/历史不进 CLAUDE.md)· dsh 元规则(机械可查进闸门)· sandcastle changesets(工具接管版本职责)。本项目三层已齐备:

```
真源层 git 自动记版本/changelog ——模型无从插手
规则层 判据1 版本=文件名自带,修订叙事归 git(正向表述)
执行层 skill 收尾 grep 版本/日期/墓志铭零残留
```

---

## 7. 移交挂账

### 代码库会话议程(7 项;开在队友全量灌库之前——样本回验护栏的载体)

1. 后端接缝定义:RAG `refs` 形状·gate GateResult 类型·provider 抽象·采集事件联合(一次定完,接缝=品味施加点)
2. 前端接缝核对:plan §4 关键签名逐个过(小而完整?错误模式写了没?)
3. 前端两缺口:音频队列所有者(src 树无家但 §6 有行为:入队顺序播放+淡出~100ms+口型)· 当前情绪所有者(一源三用的源头)
4. 目录树规则落地核查+ingest.py 归属(灌库归队友后的去留;data-contract.md 转写+**样本回验须在全量灌库前**)
5. 类型单源:Formulation/FormulationKey 在 messages.ts 与 Pydantic schema 的对齐机制
6. 灰盒测试策略:接缝上钉测试(gate/sufficiency/retrieve/render/diff),不测内部——Pocock 闭环;agent 浅模块倾向的对策=法则+review 接缝
7. 深模块词汇沿用 mattpocock-skills:codebase-design(module/interface/seam/depth/删除测试)

### 交付前批

README(B2 四块)· 人看架构文档(B5)· AGENT.md 副本(B8)。

---

## 8. 新窗口执行顺序

```
0. 必读:本文档 + .claude/skills/doc-standards/SKILL.md + ARCHITECTURE_PROGRESS.md
1. skill 清欠:判据 6 跳过(已是新句);cases.md 先核对再补 3 旧欠+5 新裁定(§5.4)
2. skill 重构:先读 SKILL-MECHANICS.md → 双相位+生成三层+受众分叉+soft dependency
   → references/(human-style.md+type-skeletons/)→ 补研三件
3. 实践:PROGRESS §二地图(§5.1)→ CLAUDE.md 三挂件(§5.2)→ 两端 plan §2 变形(§5.3+C1 分拣)
4. 收尾:grep 验证(避用词零命中+版本日期零残留+悬空引用零)→ 一次 commit
验收判据(可 grep):判据6 保持现句未被重改 · cases 新行在 · 地图 16 行齐 ·
  CLAUDE.md 净增~4行 · 两端 §2 零文件级枚举 · human-style.md 存在且五节齐
```

**commit 参考链**:本文件为 grilling 会话终点;执行会话起点=读完 §8 第 0 步。
