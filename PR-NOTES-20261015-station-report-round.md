# PR 说明 · 心灵补给站报告按回合寻址

> **本文件是什么**：本 PR 的审批说明入口，供**人工与 LLM 评审**提取本次改动。要回答三个问题——**改了哪些文件**、**做了什么**、**过程中遇到的 bug 是否解决了**——都在下面，且与 PR 的 diff 逐文件对齐。
> **权威指针**：消息与字段格式以 [docs/architecture/ws-contract.md](docs/architecture/ws-contract.md)「连接与会话」节为准；术语正词以 [docs/architecture/CONTEXT.md](docs/architecture/CONTEXT.md) 为准。本文件不定义契约，只描述本次改动。
> **本文件不替代 diff**：凡本文件与代码不一致，以代码与 `ws-contract.md` 为准，并视为本文件的缺陷。

## 0. 元信息

| 项 | 值 |
|---|---|
| 特性分支 | `yxw/station-report-round`（从 `yxw` 切出） |
| PR 目标分支 | `yxw`（不是 `main`） |
| 基线 | `yxw` @ `40f7b79` |
| 改动规模 | 36 个文件：33 个修改 + 3 个新增（其中 1 个是本文件）；不含任何删除 |
| 验证环境 | Windows · 后端 conda `test` · 前端 Node 26 / npm |
| 一句话摘要 | 心灵补给站的方案书从「每会话一份、点链接才生成、无法区分多次对话」改为「**按回合寻址、一回合一份、多份可列表查看、自素材归档起 7 天有效并后台物理清理**」，报告标题改用报告自身数据（情境 · 情绪）而非轮次序号 |

## 1. 我改了哪些文件

### 1.1 契约与常驻文档（5 个）

| 文件 | 状态 | 改了什么 | 为什么 |
|---|---|---|---|
| `docs/architecture/ws-contract.md` | 修改 +41/-10 | 补给站 REST 响应表新增 `title`、`updated_at` 两个字段及其取值与出现时机；`/report/list` 行新增 `updated_at`；补三条约束：轮次维度主键即幂等、`round_id` 不等于「第 N 次对话」、标题来源与旧式标题回填 | 本次改了响应字段，契约是字段权威（AGENTS.md 冲突裁定）；不写清楚评审无法判断兼容性 |
| `docs/architecture/backend-plan.md` | 修改 | station 行「SQLite reports 表（**每会话只留最新一份**）」→ 改为「**每回合一份**，主键 `(session_id, round_id)`，重复生成更新同一份；自素材归档起 7 天有效，过期后台物理清理」 | 原文与本次实现直接矛盾 |
| `docs/architecture/frontend-plan.md` | 修改 | station 职责行与「工具栏工具范围」补上报告列表、视图切换详情、「重新整理」、有效期提示 | 原文只写了触发/等待/预览/导出，缺本次新增的可见行为 |
| `docs/architecture/ARCHITECTURE_PROGRESS.md` | 修改 | 二期范围总表里「心灵补给站历史列表（MVP 只留最新一份）」整行移出，表下加一句脚注说明它已提前落地及指向 | 该表文档自述「改二期只改本表」；此项已不是二期 |
| `docs/architecture/CONTEXT.md` | 修改 | 术语表补「逻辑报告」「素材」两条正词；「回合 / 会话」条补一句：逐回合标识在协议与代码里叫 `round_id`，注释与口语里的「轮次」是同义说法 | 本次引入两个新概念，原表无对应词条 |

### 1.2 后端（12 个）

| 文件 | 状态 | 改了什么 | 为什么 |
|---|---|---|---|
| `backend/app/station/reports.py` | 修改 +390 | 报告表升到以 `(session_id, round_id)` 为主键的版本；新增 `round_seq` 高水位表与 `next_round_id()`；`begin_generation` 改为主键 upsert（重复生成更新同一行、`created_at` 不刷新）；新增 `gen_token` 条件写入（`finish_generation` 令牌不匹配则不落库，旧在途任务不会覆盖新一轮）；新增 `refine_legacy_expiry()`（升级遗留行按 Redis TTL 核价）、`backfill_legacy_titles()`（旧式标题幂等重算）、`delete_expired()`；新增 `derive_title()` 与 `PENDING_FRESH_S` | 本次改动的核心：一份回合一份逻辑报告、可重复生成不新增条目、有确定的到期与物理清理 |
| `backend/app/station/routes.py` | 修改 +163 | `generate`/`latest`/`list` 三端点改按 `round_id` 寻址；受理加锁与 pending 鲜度窗去重；删除按 `round_id` 拼「第 N 次梳理」的 `_title()`，改为从素材 formulation 推导标题的 `_material_title()`；`latest` 回传 `title`/`updated_at`，`list` 行补 `updated_at` | 寻址、幂等、标题来源、更新时间回传都在这一层 |
| `backend/app/ws_gateway/gateway.py` | 修改 +69 | collect 回合入场时分配 `round_id` 并写入状态；`first_frame` 与 `done` 带上 `round_id`，`done` 另带 `station_ready`（本轮素材是否归档成功）；归档时把素材与 `collected_at` 一起写入 | 前端需要稳定标识来绑定消息并按轮寻址；`collected_at` 是有效期锚点 |
| `backend/app/memory/store.py` | 修改 +158 | 素材三态（无 / 未归档 / 已归档）与 `material_times` 记录归档时刻；`clear_all` 治理清除不回退轮次高水位；`load_station_input` 支持按 `(session_id, round_id)` 取素材 | 归档窗口期需要能区分「还没归档」与「没有」；治理清除后旧链接不能指向同号新报告 |
| `backend/app/memory/__init__.py` | 修改 +2 | 导出新增的素材加载接口 | 供 station 层调用 |
| `backend/app/agents/state.py` | 修改 +5 | 回合状态新增 `round_id` 与 `collected_at` 两个字段（含字段说明） | 状态里要携带本轮标识与归档时刻 |
| `backend/app/main.py` | 修改 +40 | 新增 `_report_gc_once`/`_report_gc_loop`：启动时做遗留核价 + 旧式标题回填，运行期每 6 小时物理删除过期报告；失败只 WARN 不挡启动 | 「7 天有效」必须有后台物理清理，否则只是逻辑隐藏 |
| `backend/app/config.py` | 修改 | 新增 `STATION_RETENTION_S`（对齐温层 TTL，即 7 天）；模块注释由「每会话最新胜」改为「每会话每轮一份」 | 有效期天数要与素材 TTL 同锚点，不能各写一个数 |
| `backend/app/logger.py` | 修改 | 文件日志目录改为读 `HRP_LOG_DIR`（默认仍是 `logs`） | 测试/CI 需要把日志重定向到临时目录，避免写脏工作树 |
| `backend/app/schema/station.py` | 修改 +2 | `StationReportResponse` 新增 `title`、`updated_at` 两个可选字段 | 与契约一致 |
| `backend/app/schema/ws_messages.py` | 修改 +3 | `first_frame` 加 `round_id`；`done` 加 `round_id` 与 `station_ready` | 契约消息字段（与 `ws-contract.md` 同一批次） |
| `backend/.env.example` | 修改 | 新增 `HRP_LOG_DIR` 注释项；把 `DEEPSEEK_API_KEY=sk-你的真实key` 的 key 形态占位值清空 | 避免占位值被当成真实 key 复制走 |

### 1.3 前端（7 个修改 + 1 个新增）

| 文件 | 状态 | 改了什么 | 为什么 |
|---|---|---|---|
| `frontend/src/station/ReportList.vue` | **新增** | 报告列表视图：逐条显示标题、生成时间、状态标签，可点进对应回合 | 多回合可分别查看需要一个列表入口 |
| `frontend/src/station/station.ts` | 修改 +291 | 控制器重写为状态机（视图 list/detail × 阶段 loading/pending/ready/error、当前回合、当前标题、元信息、重生成中）；新增列表打开、按回合打开、返回列表、重新整理；标题改用接口回传的 `title`（不再用轮次序号拼）；元信息带 `updated_at`；导出文件名用报告标题并过滤文件系统非法字符 | 本次前端改动的主体 |
| `frontend/src/station/StationPanel.vue` | 修改 +161 | 外壳内做列表/详情视图切换（不新建详情组件）；详情头部元信息行改为「标题 · 生成 ·（重生成过才显示）更新 · 有效期至」；底部双按钮 + 重生成浮条 | 复用既有面板，避免两套详情实现 |
| `frontend/src/chat/messages.ts` | 修改 +48 | 每条消息绑定 `roundId`；模块级全局改为 `chat.activeRoundId`；`appendDelta`/`beginBot`/`markStationReady` 支持按回合绑定；邀请语链接据此寻址 | 修「点击邀请语进空列表/错轮次」；模块级全局会被多轮串味 |
| `frontend/src/state/round.ts` | 修改 +19 | 新增 `backendRoundId`（后端权威标识）、`lastCollectRoundId`、`stationReady`；`done` 不带 `round_id` 时（answer/crisis 支线）清空当前轮次，避免支流文本继承上一回合编号 | 报告寻址一律以 `backendRoundId` 为准，前端不自造编号 |
| `frontend/src/ws/messages.ts` | 修改 +5 | `first_frame`/`done` 类型加 `round_id`、`station_ready` | 与契约一致 |
| `frontend/src/App.vue` | 修改 +11 | 接线：`first_frame` 记后端轮次、`text_delta` 把当前轮次传进 `appendDelta`、`done` 处理归档信号与工具栏「心灵补给站」入口 | 把 WS 帧与状态机、面板入口连起来 |
| `frontend/src/chat/ChatPanel.vue` | 修改 +14 | 邀请语链接：素材未归档成功时置灰并给明确提示（不静默生成、不谎报可生成） | 归档失败不该让用户点进一个打不开的报告 |

### 1.4 测试（9 个修改 + 1 个新增）

| 文件 | 状态 | 改了什么 |
|---|---|---|
| `backend/tests/test_station.py` | 修改 +513 | 新增 8 项：标题推导六种输入、受理后标题来自素材而非 `round_id`、重复生成仍一行且正文最新胜且 `created_at` 不刷新、重复受理只一行、不同 `round_id` 不被去重合并、旧式标题回填（重算 + 幂等 + 无素材落中性标题且不动正文）、`latest` 回传 `title`/`updated_at`；既有断言适配新字段 |
| `backend/tests/conftest.py` | 修改 +58 | 报告库临时目录、素材桩等夹具 |
| `backend/tests/test_gateway.py` | 修改 +65 | 轮次分配与 `done` 携带字段的行为 |
| `backend/tests/test_memory.py` | 修改 +48 | 素材三态、归档时刻、治理清除不动高水位 |
| `backend/tests/test_admin.py` | 修改 +13 | 治理清除相关 |
| `backend/tests/e2e/e2e3_e_station_admin.py` | 修改 +152 | e2e 用例适配按回合寻址 |
| `backend/tests/e2e/e2e_lib.py` | 修改 +16 | e2e 工具读 `HRP_LOG_DIR` |
| `frontend/src/station/__tests__/station.spec.ts` | 修改 +379 | 控制器用例，新增：标题用接口 `title` 且不含「第 」、列表行标题即数据、导出文件名用标题（含非法字符过滤）、无标题才回落轮次、重生成后 `updated_at` 到位 |
| `frontend/src/station/__tests__/panel.spec.ts` | 修改 +77 | 元信息行用例改为断言显示标题、不显示轮次序号 |
| `frontend/src/chat/__tests__/station-link.spec.ts` | **新增** | 邀请语链路 + 4 项边界用例（含用户发言穿插、多条 bot 消息、显式 null 不继承） |

### 1.5 本说明（1 个新增）

| 文件 | 状态 | 说明 |
|---|---|---|
| `PR-NOTES-20261015-station-report-round.md` | **新增** | 本文件。放在仓库根是维护者的指定；未进 `docs/` 索引树，因为它是一次性交付说明而非项目文档 |

## 2. 我做了什么（用户与数据可见的语义变化）

1. **报告按回合寻址**：`generate`/`latest` 必须带 `round_id`（缺 → 422）；一次对话的邀请语链接只打开它自己那一回合的报告。
2. **一回合一份逻辑报告**：同一 `(session_id, round_id)` 重复点链接、重复请求、并发请求，都更新同一份，不新增列表条目；「重新整理」也更新同一份，旧稿在生成失败时仍可查看导出。
3. **多回合可分别存取**：工具栏「心灵补给站」进入列表，逐条列出各回合已生成/生成中的报告，可分别打开。
4. **7 天有效并真正清理**：自该回合素材归档时刻起 7 天（与素材 Redis TTL 同锚点同期限）。到期后列表不显示、`latest` 返回 404、`generate` 拒绝，后台每 6 小时物理删除。重新生成**不延长**有效期。
5. **标题改用报告自身数据**：标题取自素材的「情境 · 情绪」（情境超 16 字截断；情绪缺失不出分隔符；情境也缺失落中性标题「这一次的梳理」）。**不再使用「第 N 次梳理」**——`round_id` 计的是入场次数（含被抢占作废的），当显示序号必然与用户体感错位。
6. **重新生成有可见反馈**：`latest`/`list` 回传 `updated_at`；详情元信息在它与 `created_at` 不同时显示「更新于」。此前重生成虽然成功，但界面只显示首次生成时间，看不出变化。
7. **归档窗口期不再误报失败**：邀请语文本先于 `done`（携带归档信号）到达。素材尚未归档时点击链接给宽限重试，仍不可寻址才显示显式失败态；归档失败则链接置灰。
8. **日志目录可重定向**：新增 `HRP_LOG_DIR`，默认行为不变。

## 3. 契约字段变更（逐字段）

| 位置 | 字段 | 类型 | 何时出现 | 为什么 | 兼容性 |
|---|---|---|---|---|---|
| WS `first_frame` | `round_id` | `string \| null` | collect 回合才有；answer/crisis 为 null | 前端绑定消息并按回合寻址 | 可选；旧后端不发时前端按「不可寻址」处理 |
| WS `done` | `round_id` | `string \| null` | collect 回合结束带回 | 同上 | 可选 |
| WS `done` | `station_ready` | `boolean \| null` | collect `Finish` 携带 | 素材是否归档成功，决定邀请语链接能否启用 | 可选；缺失时前端按保守侧（置灰） |
| REST `report/latest`、`report/generate` 响应 | `title` | `string`（ready 时） | 生成成功才返回 | 列表与详情共用同一标题 | 新增可选字段 |
| REST `report/latest`、`report/generate` 响应 | `updated_at` | iso 本地时间（ready 时） | 生成成功才返回 | 重新生成的可见反馈 | 新增可选字段 |
| REST `report/list` 行 | `updated_at` | iso 本地时间 | 始终 | 同上 | 新增字段 |
| REST `report/generate`、`latest`、`list` 请求 | `round_id` | 查询参数，`^[A-Za-z0-9_-]+$` | 必填 | 按回合寻址 | **缺省视为不合法请求（422）**；旧前端调用会被拒 |

## 4. 过程中遇到的 bug 与处理

| # | 现象 | 根因 | 处置 | 状态 |
|---|---|---|---|---|
| 1 | 点邀请语链接进空列表或落到别的轮次 | 用户发言后 `appendDelta` 走 `beginBot(text)` 丢掉 roundId；且 roundId 曾存在模块级全局里，多轮会串味 | 改为 `chat.activeRoundId`（状态对象）；兜底仅在参数省略时生效，显式 null 不继承；`beginBot` 不继承 | 已解决（`station-link.spec.ts` 4 项边界用例） |
| 2 | 列表出现「第 5 次梳理」，但用户只聊了两轮 | `round_id` 由高水位在 collect **入场**时分配，计的是入场次数（含被抢占作废的、从未点链接的），界面却拿它当显示序号 | 标题改用素材的情境与情绪推导，不再编号；`round_id` 仍会跳号但不再面向用户 | 已解决 |
| 3 | 点「重新整理」看起来"还是这个" | 重生成**其实成功了**（该轮 `updated_at` 21:23:05→21:27:05、正文 1131→1156 字），但元信息只显示首次生成时间，且同素材重跑正文相近 | 回传 `updated_at`，元信息在其与 `created_at` 不同时显示「更新于」；导出文件名改用报告标题 | 已解决 |
| 4 | 归档窗口期点链接弹「这轮的整理没能存下来」 | 邀请语文本先于 `done`（携带归档信号）发出，素材尚未写入 | 不可寻址时给宽限重试（最多 3 次），仍失败才显式失败态；归档失败则链接置灰 | 已解决 |
| 5 | 升级前已生成的报告没有到期时间，无法判断能不能看 | 遗留行 `expires_at` 为空 | 启动时按素材 Redis TTL 核价；不可核验且 Redis 不可达则保持未定价（**不猜不删**），下次启动重试 | 已解决 |
| 6 | 重复点击/网络重试/并发请求可能产生多条报告 | 无幂等约束 | `(session_id, round_id)` 为主键 upsert + 受理层 `asyncio.Lock` + pending 鲜度窗（300 秒）+ `gen_token` 条件写入 | 已解决（HTTP 并发 1 项 + DB 幂等 2 项用例） |
| 7 | Live2D 不显示（本地环境） | `frontend/public/vendor/` 不存在且被 gitignore，需 `npm run l2d:fetch` 生成 | 从本机另一份检出**复制** 71 个文件（12.8 MB，不入库、不建 junction，避免以后 `l2d:fetch` 写进对方目录） | 已解决（本地环境项，**不在本 PR diff 内**） |
| 8 | TTS 服务起不来（本地环境） | GPT-SoVITS 缺 48 个源码文件与 `G2PWModel` | 从本机另一份检出补齐（junction/复制，不入库） | 已解决（本地环境项，**不在本 PR diff 内**） |
| 9 | 我误用 `uv run ruff`，导致 `backend/.venv` 被重建（约 1.2 GB） | 与维护者要求的 conda `test` 环境不符 | 已按指示用 `[System.IO.Directory]::Delete()` 删除；后续不再执行任何 uv 命令 | 已解决 |
| 10 | 旧标题回填恒不生效 | 我做批量替换时 `\uXXXX` 转义写错，把「梳理」写成「疆球」，匹配串恒不成立 | 用编辑工具直接写中文修正 | 已解决 |
| 11 | 回填测试全部落中性标题 | 我写的 noqa 批量脚本把测试里 loader 的一行注释坏了（`collected_at` 被注释吃掉，构造失败） | 手工修正该行 | 已解决 |

**未解决 / 遗留（不属本次范围，如实列出）**

| 项 | 说明 |
|---|---|
| `src/l2d/__tests__/models.spec.ts` 7 项失败 | Node 26 环境下 `localStorage is not available`；该文件本次零改动，属既有失败 |
| 重生成期间刷新页面 | 旧稿暂不可恢复（重生成期间接口不回正文），沿用原有产品语义 |
| 并发保护范围 | 仅单进程有效；多 worker 部署前需重新评估 |
| `ARCHITECTURE.md:34` | 仍写「TTS 走 CosyVoice sidecar」，与前几轮已改的 remote GPT-SoVITS 不符——**前几轮的既有失真，不在本次范围，未擅自改** |
| `CONTRIBUTING.md §4` | 仍写「向 main 提 PR」，与本次「只提 yxw」不符——**未擅自改** |
| ruff / mypy | 未运行（本机 conda `test` 环境无这两个工具，维护者决定不补）。前端 `npm run lint` 已运行且通过 |

## 5. 数据与隐私影响

- **用户文本仍不落原文**：本 PR 不新增任何落库的用户原文；报告表新增的只有标识、状态、时间与标题。
- **标题来源是提炼值**：`formulation.situation`（≤16 字截断）与 `emotion.label`，与报告正文里已有的内容同一数据类别，不引入新类别的数据。
- **留存期限**：素材与报告同为自归档起 7 天，到期后不可查看、不可重新生成，并被后台物理删除。
- **治理清除**：`POST /admin/clear_memory` 清除素材与报告，但**不回退轮次高水位**，避免旧链接指向同号的新报告。
- **无新增依赖**：未引入任何新的第三方库；未改危机判定位置（危机判定仍只在后端）。

## 6. 测试证据

| 检查 | 命令 | 结果 | 退出码 |
|---|---|---|---|
| 后端测试 | `python -m pytest tests` | **193 passed / 4 skipped / 0 failed** | 0 |
| 前端全量 | `npx vitest run` | **100 passed / 7 failed**（14 文件 / 107 用例；7 项失败全为既有 `src/l2d/__tests__/models.spec.ts`，本次零改动） | 1 |
| 前端类型 | `vue-tsc --noEmit -p tsconfig.app.json` | 干净 | 0 |
| 前端类型 | `vue-tsc --noEmit -p tsconfig.node.json` | 干净 | 0 |
| 前端类型 | `vue-tsc --noEmit -p tsconfig.vitest.json` | 干净 | 0 |
| 前端 lint | `npm run lint`（oxlint + eslint，`--fix`） | 0 warnings / 0 errors，**未改动任何文件** | 0 |
| 前端构建 | `npx vite build` | 通过 | 0 |
| e2e | `tests/e2e/e2e3_e_station_admin.py` | 20/20（**在本轮标题改动之前跑的**，标题改动后未重跑 e2e） | 0 |

**未运行**：后端 `ruff` / `mypy`（原因见第 4 节遗留表）。

## 7. 明确未做

- 未改架构：没有引入第二套报告系统、没有新建版本表、没有改危机闸门与三路路由。
- 未重置任何计数器：`round_seq` 高水位保持原值，旧链接不会指向同号新报告。
- 未删除任何历史报告数据：旧标题只被重算（只改 `title` 字段，不动正文、不删行），且该操作幂等、可重复执行。
- 未改 `.gitignore`，未新增依赖，未顺带重构无关模块。
- 未把「轮次」全库改名成「回合」：`轮次` 在本 PR 之前就存在于未涉及的模块（如 `agents/extract.py`、`schema/ws_messages.py`、`ws/messages.ts`），全库改名会把 40+ 个无关文件卷进本 PR。改为在 `CONTEXT.md` 里写明两者同义。

## 8. 可复现验证步骤

1. 起后端（conda `test` 环境）与前端（`npm run dev`）。
2. 第一轮情绪梳理 → 等回合归档 → 点聊天消息末尾的「心灵补给站」邀请语链接 → 出方案书。
3. 第二轮情绪梳理 → 同样点链接 → 出方案书。
4. 对其中一份点「重新整理」（可连点两次以制造重复请求）。
5. 打开工具栏「心灵补给站」：
   - 列表**恰好两条**，没有重复条目；
   - 标题是「情境 · 情绪」（如「考试没有考好 · 焦虑」），**不出现「第 N 次梳理」**；
   - 被重新整理过的那条，详情元信息里出现「更新于 HH:MM」，另一条不出现；
   - 两条的「有效期至」都是各自素材归档时刻 + 7 天。

## 9. 提交批次

| # | 范围 | 类型前缀 |
|---|---|---|
| 1 | 契约 + 后端（12 个）+ `ws-contract.md` | `feat(station)` |
| 2 | 前端（8 个） | `feat(station)` |
| 3 | 测试（10 个） | `test(station)` |
| 4 | 常驻文档失真修正（4 个）+ 本说明 | `docs(station)` |
