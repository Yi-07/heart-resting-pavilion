# WS 前后端契约 · ws-contract

> **权威源**：[architecture-spec.md](architecture-spec.md)（本文件为其工程实施补充，不覆盖）
> **范围**：前后端 WebSocket 单连接的**完整消息契约**。前端内部（模板声明/渲染器）不在此文档。

---

## 1. 连接与会话

| 项 | 值 |
|---|---|
| 端点 | `ws://<host>/ws` |
| 会话 | 连接即建 `session_id`（服务端生成，随 `first_frame`/`done` 带回）|
| 生命周期 | 单连接承载多回合；断线重连用原 `session_id` 恢复上下文 |
| 编码 | JSON，UTF-8，文本帧 |
| 管理通道 | 记忆清除/趋势走 HTTP REST（`POST /admin/clear_memory`·`GET /admin/trends?days=7`，趋势只回 mood_select 源）；不进 WS；WS 对话 10 消息（见「消息总览（10）」） |
| 模型服务通道 | 模型配置走 HTTP REST `/admin/llm/*`（多服务商 profiles+单激活）：`GET /admin/llm/catalog`（服务商+离线候选目录）· `POST /admin/llm/models`（实时模型发现，探测失败仍回候选+live_error）· `GET /admin/llm/profiles`（列表+active_id）· `POST /admin/llm/profiles`（保存待启动）· `PUT /admin/llm/profiles/{id}`（编辑；api_key 留空即保留旧密钥）· `POST /admin/llm/profiles/{id}/verify`（真实最小调用验证，不激活）· `POST /admin/llm/profiles/{id}/activate`（验证通过才切换）· `DELETE /admin/llm/profiles/{id}`（运行中不可删）；同一服务商仅一条配置（409）；**任何响应零密钥回显**；不进 WS |
| 留言墙通道 | 留言墙走 HTTP REST `/wall/*`（本地单用户，七日生命周期）：`GET /wall?session_id=`（列表+unread 计数）· `POST /wall`（创建，≤2000 字）· `POST /wall/read?session_id=`（打开后清未读）· `GET /wall/unread?session_id=`· `DELETE /wall?session_id=`（清空）；回复由后台 worker 30s 巡检异步生成——留言先过危机闸门，命中落审计 WARN（`wall_crisis_hit`）+热线话术单源回复，普通留言交当前激活 LLM；不进 WS |
| 语义记忆治理通道 | 语义记忆查看/单条删除走 HTTP REST：`GET /admin/memories`（列表） · `DELETE /admin/memories/{id}`（单条删除，成功 200）；不进 WS |
| 补给站通道 | 心灵补给站方案书走 HTTP REST，按回合寻址（`round_id` 必填查询参数，缺 → 422）：回合末自动触发生成（Finish 归档时后台启动，无需点击）；`POST /station/report/generate`（兜底受理 + 手动重生成）· `GET /station/report/latest`（按轮取稿/轮询，等待态「正在为你整理…」）· `GET /station/report/list`（报告列表，只含有效期内报告）；不进 WS |
| 语音转写通道 | 语音输入两步式（ADR-004）：`POST /asr/transcribe`（base64 webm/opus → 转写文本）供前端回填文本框，用户确认后按文本输入发送；不进 WS |

**补给站 REST 响应**（HTTP 200，generate/latest 两端点同形）：

```json
{ "status": "ready", "report_md": "# 心理成长方案\n## 睡眠与焦虑的梳理",
  "title": "考试没有考好 · 焦虑", "updated_at": "2026-10-16T21:27:05" }
```

| 字段 | 值 | 说明 |
|---|---|---|
| status | `pending` \| `ready` | pending 表示已受理/生成中 |
| report_md | string | 仅 ready 返回；md 正文，前端预览/导出 |
| title | string | 仅 ready 返回；取自报告自身数据（`formulation.situation` + `emotion.label`，情境超 16 字截断，缺失各有兜底），**不用轮次序号或自增 ID** |
| updated_at | iso 本地时间 | 仅 ready 返回；最近一次**成功**生成/重新生成时刻（重生成不改 `created_at`，前端据此显示「更新于」） |

- **轮次维度**：generate/latest 均按 `(session_id, round_id)` 存取，**一回合一份逻辑报告**（主键即幂等：重复受理/重复点击/并发更新同一行，不新增条目；并发由受理层锁 + pending 鲜度窗 + `gen_token` 条件写入去重）
- **round_id 不是「第 N 次对话」**：round_id 由 round_seq 高水位在 collect 入场时分配（持久，重连/重启不复位，治理清除不复位——防残留旧链接指向同号新报告）；被抢占作废的入场也消耗一个 id，故标题与列表都不按它编号
- **有效期**：报告自该回合素材归档时刻起 7 天（`expires_at`，与 station:input 素材 Redis TTL 同锚点同期限；重新生成**不延长**）；到期后 latest 视为无记录返 404，generate 拒绝，后台物理清理
- generate 受理即返；latest 轮询——生成中 `pending`，完成 `ready`+`report_md`。回合末自动生成已受理时点击链接直接进入轮询，不重复起任务
- 错误码：`POST /station/report/generate` 无素材或素材已过期 → 409；素材有效期暂时无法确认（Redis 异常/键无 TTL）→ 503（不臆测可重新生成）；`GET /station/report/latest` 无（有效）记录 → 404

**报告列表**（`GET /station/report/list?session_id=`，HTTP 200；只返回有效期内的报告，按生成时间降序）：

```json
{
  "reports": [
    { "round_id": "3", "title": "把对方拉黑了 · 愤怒", "status": "ready",
      "created_at": "2026-10-12T16:40:00", "updated_at": "2026-10-12T16:52:10",
      "expires_at": "2026-10-19T16:40:00", "can_regenerate": "yes" }
  ]
}
```

| 字段 | 值 | 说明 |
|---|---|---|
| round_id | string | 轮次标识（`first_frame`/`done` 带回，见「3.1 first_frame」/「3.5 done」）；`legacy` = 升级前旧报告，轮次未知 |
| title | string | 展示标题（如「考试没有考好 · 焦虑」）；与 latest 的 `title` 同源同值 |
| status | `pending` \| `ready` | 生成中 / 可查看 |
| created_at · updated_at · expires_at | iso 本地时间 | 首次生成 / 最近一次成功生成（含重新生成）/ 到期时刻（素材归档 + 7 天） |
| can_regenerate | `yes` \| `no` \| `unknown` | 素材是否可用：`no`=已过期或已被治理清除；`unknown`=Redis 暂不可用，不承诺 |

**语音转写请求/响应**（ADR-004）——请求 `POST /asr/transcribe`：

```json
{ "audio": "<base64 webm/opus>" }
```

响应（HTTP 200）：

```json
{ "text": "最近总失眠" }
```

- 请求 `audio` 必填，单段 ≤15s（前端 MediaRecorder 侧约束），后端字节护栏 1MB 超限 413
- 转写成功（空串表示「没听到」）→ 200 + `text`；转写不可用（模型未加载/异常）→ 503
- 音频转写后即弃不落存储；日志 `asr_transcribed`/`asr_empty`（脱敏：只记长度+指纹）

---

## 2. 消息总览（10）

| 方向 | 类型 | 触发方 | 说明 |
|---|---|---|---|
| S→C | first_frame | 后端 | 新回合起点；告知 route / 模板 / 开场文案（collect 可空）|
| S→C | draw | 后端 | 黑板绘制数据（粗稿/逐轮/精稿统一）|
| S→C | text_delta | 后端 | 流式回复文本 |
| S→C | audio_chunk | 后端 | TTS 音频块（base64）|
| S→C | done | 后端 | 回合结束 |
| S→C | replay | 后端 | 重连回放（历史气泡/小结卡，ADR-005；无 seq）|
| S→C | wall_reply | 后端 | 留言墙回复就绪通知（不占 seq、不进回放；收到后拉取 `/wall` 刷新）|
| C→S | user_input | 前端 | 用户文本输入（ADR-004 输入单源）；采集轮次回答也用它 |
| C→S | mood_select | 前端 | 心情选择上报 |
| S→C | error | 后端 | 错误帧（见 §8）|

---

## 3. 消息定义（S→C）

### 3.1 first_frame

```json
{
  "type": "first_frame",
  "session_id": "sess_abc",
  "route": "collect",
  "round_id": "3",
  "template": "scene_default",
  "emotion_label": "疲惫",
  "mood_select": false,
  "text": ""
}
```

| 字段 | 值 | 说明 |
|---|---|---|
| round_id | string | **collect 才有（crisis/answer 不带）**；本轮采集的稳定标识（round_seq 高水位分配，持久不复用），报告按 `(session_id, round_id)` 寻址（见「连接与会话」节补给站通道） |
| route | `collect` \| `crisis` \| `answer` | **采集期打岔（ADR-003）不发 first_frame**（黑板保活，增量续画）；纯 answer 回合发（route=answer，chip 立即切换） |
| template | 模板 id | collect 才有，预告粗稿模板 |
| emotion_label | 快速研判标签 | 喂 Live2D + 粗稿；answer 携研判标签（表情不回落） |
| mood_select | bool | 恒 false（心情选择器自动浮出废弃，心情上报由用户主动点「今日心情」按钮，见「mood_select」节；字段保留作协议兼容预留） |
| text | 开场文案（可空） | collect 现行恒空串（开场不设安抚语，第一句话由问话 LLM 生成后随 text_delta 到达）；crisis 携郑重安抚文案；answer 恒空串 |

**前端语义**：收到 first_frame 即**新回合起点 → 清空黑板、重置 seq 基线、收起心情选择器计时**（基线是旧帧判定起点；后端计数不重置，见 §3.2）。`text` 为空串时前端直接开空 bot 消息等待 text_delta，不渲染任何占位语。

### 3.2 draw

```json
{
  "type": "draw",
  "seq": 3,
  "template": "scene_focus",
  "data": {
    "situation": "被 leader 当众否定",
    "emotion": { "label": "焦虑", "intensity": 0.85 },
    "thought": "我不行",
    "behavior": "逃避会议",
    "intermediate_belief": null,
    "core_belief": null,
    "assets": { "situation": "desk.cluttered", "emotion": "state.storm-cloud", "subject": "desk.overwhelmed" }
  }
}
```

- **data 携完整 formulation**（不是增量），前端按 seq 差动画新字段（已画的保留，新的淡入）
- scene_* 板式的 data 为 **scene_formulation** 型（§5.1）：六字段同 formulation + `assets` 展示选材
- `assets`：字段 key → 图标 id，仅选中字段携带；`subject` 为画面主体选材，与字段键平等——选材与模板声明都在才画，无默认兜底
- assets 不进 formulation 域对象（归档不含选材）；assets 变更不触发前端重画（选材与字段文本同轮由提取产出）
- seq：**会话内全局递增**（不随回合重置）；前端忽略 `seq <= 已处理` 的旧帧；跨回合陈旧帧天然被丢弃

### 3.3 text_delta

```json
{ "type": "text_delta", "seq": 5, "text": "我们把它拆开看看——", "final": false }
```

- `final: true` 标记最后一块（可不依赖）

### 3.4 audio_chunk

```json
{ "type": "audio_chunk", "seq": 6, "format": "wav", "data": "<base64>", "final": false }
```

```json
{
  "type": "audio_chunk", "seq": 6, "format": "pcm_s16le", "data": "<base64>",
  "final": false, "round_id": "tts-7", "audio_seq": 3,
  "sample_rate": 32000, "channels": 1
}
```

- **format 二选一**：`wav` 携带整句 wav（base64 的完整文件）；`pcm_s16le` 携带一块裸 PCM16（base64，小端，交错，无文件头）。前端按 `format` 分派两条播放链路（`AudioHub`：`wav` 走 `AudioQueue`，`pcm_s16le` 走 `PcmPlayer`）
- **PCM 四字段**：`format=pcm_s16le` 时 `round_id`/`audio_seq`/`sample_rate`/`channels` **必填**；`format=wav` 时只有 `round_id` 可能出现，其余省略
- **可多帧**：TTS 分块合成，一段语音拆成多个 audio_chunk（seq 单调递增），前端按序连播
- **round_id 一致性**：同一回合的所有帧 `round_id` 相同，由后端从 TTS 服务原样透传。前端只接受 `round_id == currentRoundId` 的帧；旧回合的迟到帧直接丢（可观测）
- **预置 wav 组号**：预置语音的 wav 帧由网关赋**逻辑组号**（`preset-*` 前缀，非 TTS 透传），仅覆盖**回合外路径**：`preset-mood-{trace}`（心情回执）、`preset-crisis-{trace}`（危机话术；安抚+热线两句**同组**，保顺播）。前端对 wav 帧按组路由，与 PCM 共用同一套回合状态：同组排队续播，未见过的新组**双链 flush 后接管**（旧回合余音淡出让位），见过的旧组迟到帧丢弃；wav 缺组号按 legacy 队列现状入队（可观测降级）。**回合内预置语音（分析期等待话术）不携组号**——它是回合内过客，抢组号会把同回合总结 PCM（`tts-{trace}`，与问话同组）判成旧组迟到帧整段丢弃
- **audio_seq**：回合内单调递增的音频块序号，**跨句连续、不重置**。它与外层 `seq` 是两套号：`seq` 是本连接全局发帧序号，`audio_seq` 是回合内音频块序
- **final 语义**：`true` 标记本回合最后一块（单发路径如危机热线/等待语音/心情回执恒 true；流式路径恒 false，最后一块不补发）。前端当前不读该字段，不依赖它也能播
- **时序例外**：总结语音异步流出，可在 `done` 之后到达（见「6.2 collect」）；前端播放队列独立于回合状态，旧回合余音由新回合音频首块自认领时 flush、用户发送新输入（user_sent）时即 flush（音频打断由 AudioHub/PcmPlayer 承担）

### 3.5 done

```json
{ "type": "done", "session_id": "sess_abc", "seq": 7, "round_id": "3", "station_ready": true }
```

- `round_id`：collect 回合结束时带回本轮标识（answer/crisis 不带）；前端据此把该轮的「心灵补给站」邀请语链接绑定到这一轮
- `station_ready`：**仅 collect 正常收尾（Finish）携带**——本轮素材是否已成功归档；false 时前端不得启用该轮报告入口（归档失败需显式提示，不得静默进入生成）；字段缺省按旧行为处理（旧后端兼容）
- 前端：收起全部等待态（心情选择器、黑板"收尾中"提示）

### 3.6 replay（重连回放，ADR-005）

```json
{ "type": "replay", "mode": "bubbles", "turns": [ {"role": "user", "text": "最近很焦虑睡不着"}, {"role": "assistant", "text": "那种睡不着的时候,脑子里在想什么?"} ], "summary": "上次梳理围绕入睡困难展开,聊到工作中被批评的委屈。", "session_id": "sess_abc" }
```

- **触发**：重连认领（`user_input` 带原 session_id）后、本回合 first_frame 之前，主动推一次；新连接（不带 id）不推
- `mode: "bubbles"`（30min 内，热层 recent_turns 还在）：`turns` 携带最近轮次原话（≤20 轮，`role: user|assistant`）+ `summary`（温层最新摘要，可为 null）；前端幕布折叠式回放（历史收横幅，展开降饱和气泡）
- `mode: "digest"`（热层已过期）：无 `turns`，`summary` 必有；前端小结卡片+提示"原话已按隐私设定抹去"
- 热层温层均无内容 → 不推帧（全新会话）
- 无 `seq`，不进回合计数（同 first_frame/error 语义）
- 治理联动：`POST /admin/clear_memory` 由前端先清浏览器存的身份，再调本端点

### 3.7 wall_reply（留言墙回复通知）

```json
{ "type": "wall_reply", "session_id": "sess_abc" }
```

- **触发**：留言墙 worker 写入回复后按 `session_id` 查在线连接推送；无在线连接则静默跳过（留言保留未读态，用户下次打开留言墙拉取）
- 前端收到后调 `GET /wall?session_id=` 刷新列表与未读小红点；本帧不携留言内容（内容单源在 REST 列表）
- 无 `seq`，不进回合计数、不进重连回放（同 replay 语义）
- 身份约定：wall 的 REST `session_id` 与 WS 会话 id 同源（前端统一取 WS 身份，不再自造 `wall_*`）

### 3.8 error

```json
{ "type": "error", "code": "invalid_message", "message": "字段缺失: text" }
```

| code | 含义 |
|---|---|
| invalid_message | 请求消息不合法（缺字段/类型错）|
| timeout | 采集/分析超时 |
| server_error | 后端异常，已降级 |
| ask_llm_failed | 问话 LLM 失败；采集态挂起待重试，前端走辐条提示 |

---

## 4. 消息定义（C→S）

### 4.1 user_input

```json
{
  "type": "user_input",
  "session_id": "sess_abc",
  "text": "最近总失眠",
  "ts": 1723456789
}
```

- `text` 必填；语音输入经 `POST /asr/transcribe` 转写回填文本框、用户确认后同此发送（ADR-004，输入单源文本）
- **采集轮次的回答也用此消息**（后端按会话状态识别第几轮）

### 4.2 mood_select

```json
{
  "type": "mood_select",
  "session_id": "sess_abc",
  "mood": "低落",
  "ts": 1723456789
}
```

- mood 取值（6 档）：`难过 / 低落 / 平静 / 还好 / 开心 / 很好`
- **来源**：用户点工具栏「今日心情」在表情组中主动选择；首帧自动浮出已废弃
- **独立到达**（无活跃回合）：后端仅更新 L7 profile，回 `text_delta`（预置回执） + `audio_chunk`（预置回执语音，预置 wav 直发，失败跳过） + `done`（**不发 first_frame**，与 answer 一致）；Live2D 表情由前端 mood_select 本地触发；前端点选即置灰按钮组，done 解除（连接异常约 8s 兜底解除）
- **回合内到达**（采集期）：仅更新 L7 profile，不回帧，采集照常等待轮次回答（按钮组回合内置灰，此路径为兜底语义）

---

## 5. 数据对象

### 5.1 formulation（collect 专用，后端填 / 前端渲染）

```json
{
  "situation": "string|null",
  "emotion": { "label": "string|null", "intensity": "number|null" },
  "thought": "string|null",
  "behavior": "string|null",
  "intermediate_belief": "string|null",
  "core_belief": "string|null"
}
```

- 未采字段为 null（前端不画该格；belief 字段允许留白，后端不硬填）

**scene_* 板式 data 扩展（scene_formulation）**：六字段同 formulation + `assets`（定义与语义见 §3.2）；后端实现为 formulation 子型，Draw 判别校验按 TEMPLATE_DATA 映射取型

**scene_answer / scene_crisis 固定场景 data（scene_note）**：`{ "note": "string|null" }`——图标全预绑定无 LLM，data 只携底部注释行文字（crisis 恒携预置注文案，正文由后端话术库单源；answer 恒 `note: null`）

**测试模板 data**：
- `emotion_wheel`：`{ emotions: [{ label: string, intensity: 0~1, color: string }] }`
- `stage_map`：`{ nodes: [string], current: int, from: string }`

### 5.2 枚举

| 枚举 | 值 |
|---|---|
| route | `answer` / `collect` / `crisis` |
| template | `scene_default`（兜底暖场景，兼 collect 开场）· `scene_focus`（正题聚焦板，接力后用）· `scene_answer`（answer 固定场景）· `scene_crisis`（危机固定场景）· `emotion_wheel` · `stage_map`（测试模板）|
| mood_select.mood | 见 §4.2 六档 |
| emotion.intensity | 0~1 或 null（研判无强度可缺省） |

- `beck_formulation` 从 collect 链路退役，枚举保留作几何测试模板；后续板式按 `scene_<处境族>` 扩展

---

## 6. 时序

### 6.1 answer（直接答，场景帧先行）

```
C→S  user_input
S→C  first_frame (route=answer, text="", emotion_label=研判标签)
S→C  draw (template:"scene_answer", data:{note:null})   ← 回合起点发,读书场景淡入
S→C  text_delta ×N   (流式;知识型走 RAG 后同)
     S→C  audio_chunk ×N (逐句语音,与 text_delta 交错,可选)
S→C  done
```

- 模板切换触发前端转场管线（空板→场景淡入）；重复 answer 回合同模板不转场、同 data 不重画
- **打岔例外**（ADR-003）：采集期打岔不发 first_frame（无清板，黑板保活），仅发 `draw (scene_answer)` 接管；恢复采集时模板切回触发转场（§6.2）
- **语音与文字交错**：句子泵把 LLM 流增量切句，凑够一句就送 TTS，出声不等全文生成完。两者共用 seq 计数（§3.2），顺序以到达为准
- **文字不被音频拖住**：LLM 出字比合成快一个量级，两条队列分开走
- **语音缺席不杀回合**：TTS 失败只记 degraded，文字链路照常；`TTS_ANSWER_VOICE=0` 可整体关停 answer 语音（调试用）

### 6.2 collect（多轮采集，问话 LLM 流式 + 逐句 TTS）

```
C→S  user_input (第 1 条)
S→C  first_frame (route=collect, template=scene_default, text="", mood_select=false)
S→C  draw (scene_default|scene_focus, entry 提取结果: 首条输入即提取,带选材)
S→C  text_delta ×N (问话 LLM 流式,攒批)
S→C  audio_chunk ×N (问话逐句 TTS,句子泵,pcm_s16le 带 round_id)
     C→S  mood_select (可选,用户点了才发)
     C→S  user_input (第 1 轮回答)
S→C  draw (增量,+新字段,板式接力可能在此切 scene_focus)
S→C  text_delta ×N + audio_chunk ×N (确认+下一问,流式+逐句 TTS,与第 1 问同构)
     ...循环至充分度 ≥0.7 或轮数上限...
S→C  text_delta ×1 (等待话术单帧 final=true,预置文本)
S→C  audio_chunk ×1 (等待语音,预置 wav 直发,与文本同文)
S→C  draw (精稿: 复核后全量 formulation,选材不重发)
S→C  text_delta ×N (人话总结,流式攒批,末尾拼心灵补给站邀请语)
S→C  done
S→C  audio_chunk ×N (总结语音,异步流出,可选;done 后到达,抢占即蒸发)
```

- **问话生成**：LLM 按采集信息需求流式生成（系统提示词规范共情陪伴者风格），文字攒批与逐句 TTS 与 answer 同构（SentenceSplitter 复用）；确认语不再独立预置——由问话 LLM 按采集进展自然带出（含进度感知：已采字段/剩余轮数进 prompt）
- **entry 即提取**：首条输入过路由即跑字段提取+选材，粗稿带实质字段出图；板式接力条件不变（situation/thought/behavior 首次入格且选材图标有效），时点提前至 entry 即可发生；选材熔断 → 永久暖场景（`asset_fuse_trip` WARN）
- **打岔挂起/恢复**（ADR-003）：采集期命中 answer 的输入 → `draw (template:"scene_answer")` 接管黑板 + 短答 + done，采集态挂起不清；下一输入恢复采集，恢复轮照常发全量 draw（模板切回触发转场）
- **降级**（答案过短/话题漂移/负面词）：后端跳过剩余轮次，直接发精稿 draw + 转共情陪聊/已采字段收尾；情绪变差命中软预筛 → 改发危机序列（§6.3）
- **问话 LLM 失败**：`error(code=ask_llm_failed)` + 前端辐条提示（不入对话气泡）；采集态挂起，下一条输入重试；不发预置问句兜底
- **分析等待**：停采后同步分析，精稿 draw 前有分析耗时（前端显示"收尾中"）；等待话术预置文本+预置 wav 声文同发（与危机/心情回执同构，正文单源 phrases.py 不入契约）；前端 analysis 相对单帧 `final=true` 的 text_delta 不推进回合相（后随精稿 draw）；后台并行属二期
- **seq 示例**：时序图仅示意；text/audio 交错消耗号，递增规则见 §3.2

### 6.3 crisis（危机）

```
C→S  user_input
S→C  first_frame (route=crisis, 郑重安抚, mood_select=false)
S→C  draw (seq=1, template:"scene_crisis", data:{note:"加油！你能行的"})
S→C  text_delta (热线 12356 引导)
S→C  audio_chunk (热线话术语音,预置 wav,与文本同步)
S→C  done
```

- 图标预绑定，无 LLM 选材（危机链路不走选材）；热线引导仍走 text_delta
- 危机话术（安抚文案/热线引导/黑板注）全部预置文本+预生成 wav：文本照常发帧，语音直发预置文件，不占运行时 TTS；固定文案由后端话术库单源，契约不记正文

---

## 7. 回合与中断

| 规则 | 值 |
|---|---|
| 回合起点 | 收到 first_frame → 前端清黑板、重置动画基线（seq 会话内全局，不重置） |
| 旧帧处理 | 收到 `seq <= 已处理` 的 draw 忽略 |
| 新回合抢占 | 采集/分析未完成时用户发新 user_input → 后端取消当前处理（旧 emitter 标 dead，未发帧蒸发）；**采集态保留**，新输入按轮次回答消费（无 first_frame，黑板增量续画，已采字段与轮次计数不丢）；仅危机命中、收尾后销毁采集态。answer 支线（含采集期打岔）被抢占则支线结束，采集态不受影响 |
| 抢占时序边界 | 新输入取消处理时，旧问话/陪聊流可能已流出半截文本：前端发送即封口旧流式消息（另起新消息），后端已发帧不撤回（seq 语义不变） |
| 超时 | 后端处理任一 user_input 满 60s（可调常量，自该消息到达起算）→ `error(code=timeout)` 兜底；采集态保留（同抢占语义，下一条输入继续）。（原「无 S→C 消息满 15s → 前端显示『还在处理』」条款未实现，前端等待文案为「小栖正在梳理你说的…」，补播与定时提示未实现，见 backlog） |

---

## 8. 错误处理

1. 后端收到非法 C→S 消息 → 回 `error(code=invalid_message)`，**不崩连接**
2. 采集/分析超时 → `error(code=timeout)` + 转降级回复
3. 后端异常 → `error(code=server_error)`，前端显示温和兜底话术（非医疗、不恐慌）
4. 问话 LLM 失败 → `error(code=ask_llm_failed)`，前端辐条提示（不入对话气泡）；采集态挂起，下一条输入重试，不发预置问句兜底
5. 重连：前端带 `session_id` 重连，后端恢复热层上下文（ADR-001：重建 turns；ADR-005：先推 `replay` 帧回放）

---

## 9. 日志范式（双输出）

### 9.1 双输出

| 输出 | 形态 | 级别 | 用途 |
|---|---|---|---|
| 控制台 | **彩色可读**（Loguru 风格：绿时间 + 级别 + 青`模块:行号` + 短消息）| INFO 默认；环境变量 `HRP_VERBOSE=1` → DEBUG | 开发/演示，评审看得懂 |
| 文件 | **结构化 JSON**（全部字段）| DEBUG | 排查/审计，`logs/debug_{date}.log` |

### 9.2 标准字段（两条输出共用）

| 字段 | 说明 |
|---|---|
| ts | ISO 8601（含时区）|
| level | DEBUG / INFO / WARN / ERROR / FATAL |
| service | `hrp-backend` / `hrp-frontend` |
| session_id | 会话关联键 |
| trace_id | 回合自增 ID（会话内从 0 递增）|
| event | 事件名（§9.3）|
| route | answer / collect / crisis（有则带）|
| message | 简短描述 |

### 9.3 级别与事件

| 级别 | 用在哪 |
|---|---|
| DEBUG | WS 消息收发明细（默认关闭）|
| INFO | 回合开始/结束、路由判定、done |
| WARN | 危机审计、降级触发、超时降级 |
| ERROR | 消息非法、后端异常、error 帧发出 |
| FATAL | 进程级故障 |

事件（连接与回合）： `session_open` · `user_input_received` · `reconnect_adopted` · `memory_restored` · `memory_degraded` · `route_decided` · `first_frame_sent` · `preempt_collect_retained`（INFO，抢占保留采集态） · `mood_select_received` · `round_archived`（Finish 归档完成） · `done` · `error` · `session_close` · `event_loop_lag` · `diag_dumped`
事件（危机与风险）： `crisis_gate_hit` · `risk_review_failed`（WARN，软信号复核失败不升级） · `wall_crisis_hit`（WARN，留言墙危机审计，见「留言墙通道」）
事件（采集与分析）： `collection_start` · `collection_round` · `sufficiency_scored` · `degraded`（WARN，横切降级，按 reason 字段分型，见尾注） · `ask_llm_failed`（WARN，问话 LLM 失败采集挂起；亦作 `degraded` 的 reason 值） · `analysis_start` · `analysis_end` · `extract_filled` · `extract_empty`
事件（黑板与选材）： `draw_sent` · `asset_fallback`（WARN，选材校验拒绝落默认） · `asset_fuse_trip`（WARN，选材熔断全默认） · `asset_catalog_missing`（WARN，选材目录缺文件）
事件（音频与回放）： `replay_sent`（ADR-005） · `audio_sent` · `pcm_sent`（realtime PCM 块发出） · `tts_answer_done`（句子泵收尾） · `tts_absent` · `tts_cancel_sent`（打断穿透到 TTS 服务）
事件（TTS 服务）： `tts_degraded` · `tts_remote_degraded` · `tts_cancel_failed` · `tts_round_id_mismatch` · `tts_v2_round_id_mismatch` · `tts_v2_seq_gap` · `tts_sidecar_spawned` · `tts_sidecar_not_ready` · `tts_sidecar_missing_python` · `tts_sidecar_version_mismatch` · `tts_sidecar_version_respawn`
事件（记忆与检索）： `memory_cleared` · `memory_clear_failed`（ERROR） · `semantic_recalled` · `semantic_saved` · `semantic_degraded` · `semantic_deleted` · `semantic_list_failed` · `semantic_delete_failed` · `semantic_clear_client_failed` · `semantic_clear_delete_failed` · `rag_retrieved` · `rag_bm25_cache_invalid` · `rag_bm25_cache_write_failed` · `rag_bm25_rebuild_failed` · `rag_ingest_state_update_failed`
事件（模型配置）： `config_applied` · `config_aes_key_loaded` · `config_aes_key_generated`（WARN，密钥自举生成） · `config_aes_key_write_failed` · `llm_profile_created` · `llm_profile_deleted` · `llm_activated` · `llm_activate_rejected`（WARN，激活验证未过） · `llm_connection_verified` · `llm_persist_failed`（ERROR，落库失败） · `llm_config_key_unavailable`（WARN）
事件（留言墙）： `wall_reply_pushed` · `wall_reply_failed`（WARN） · `wall_worker_degraded`（WARN，巡检异常不退出）
事件（补给站）： `planner_llm_ok` · `station_report_accepted` · `station_report_ready` · `station_report_superseded`（WARN，旧任务令牌失配拒绝覆盖） · `station_reports_schema_mismatch`（WARN，旧库自检重建） · `station_legacy_migrated`（WARN，旧表结构迁移） · `round_id_alloc_failed`（WARN，round_seq 分配失败该轮不产素材） · `station_legacy_refined` · `station_titles_backfilled`（启动遗留核价/旧式标题回填） · `station_reports_gc` · `station_report_gc_error`（WARN，清理失败不影响服务）
REST 侧： `asr_transcribed` · `asr_empty`（归属 `/asr/transcribe`，ADR-004）。本清单为全量运行时事件名，与代码 `logger` 调用同步维护；启动生命周期与压测台日志（`startup_*`/`*_warm_*`/`memory_ready`/`memory_ping_failed`/`asr_model_*`/`rag_warm_*`/`watchdog_on`/`bench_events`，message 落点）不入本表。`preset_wav_missing`/`preset_wav_failed`/`station_auto_material_missing`/`station_auto_generate_failed`/`finish_archival_interrupted`/`semantic_note_llm_failed`/`empty_stream`/`llm_error`/`summary_llm_error`/`rag_failed`/`timeout`/`tts_failed`/`tts_send_failed`/`tts_sentence_failed`/`audio_send_failed`/`asr_failed`/`config_decrypt`/`config_load` 均为 `degraded` 事件的 reason 字段值而非独立事件名

### 9.4 脱敏（硬约束）

1. 用户文本：不落日志；需要时记**长度或哈希**，不记原文
2. 音频：绝不落库、绝不落日志
3. 凭证（AES-GCM 密钥 / API key）：绝不落
4. **危机命中必须落审计日志**（WARN，event=crisis_gate_hit，含命中项 + 是否转热线，不含原文）——安全合规要求，不可省略

### 9.5 轮转与健壮

- 文件轮转 10MB、保留 30 天（`rotation=10MB, retention=30 days`）
- uncaught 异常用 `logger.catch` 兜底，避免进程崩溃静默
- 二期接 ELK / Datadog 聚合

---

## 10. 前后端各自实现清单（开工检查）

**前端**
1. WS 客户端（10 种消息解析、seq 校验、断线重连）
2. first_frame → 清黑板/重置/收起选择器
3. draw → 增量渲染（新字段动画；scene 模板 asset 渲染——未知 id 跳过兜底，subject 与 zones 声明都在才画）
4. mood_select 上报（含独立到达）
5. error → 温和兜底（ask_llm_failed 走辐条提示，不入对话气泡）
6. replay → 幕布回放/小结卡（ADR-005；session_id 经 localStorage 持久化）

**后端**
1. WS 网关（session_id、消息路由、seq 管理）
2. first_frame 生成（route/template/开场文案；collect 置空，crisis 携安抚）
3. draw 下发（粗稿/逐轮/精稿；collect 板式接力 scene_default→scene_focus）
4. mood_select 处理（profile 更新 / 独立到达）
5. error 帧 + 超时兜底
6. replay 推送（重连认领后，ADR-005）+ `/asr/transcribe` 转写端点（ADR-004）
7. asset_catalog 加载 + 选材白名单校验 + 熔断与日志（extract 同调用顺带选材，不加 LLM 次数）
