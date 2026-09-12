# WS 前后端契约 · ws-contract

> **权威源**:`architecture-spec.md`(本文件为其工程落地补充,不覆盖)
> **范围**:前后端 WebSocket 单连接的**完整消息契约**。前端内部(模板声明/渲染器)不在此文档。

---

## 1. 连接与会话

| 项 | 值 |
|---|---|
| 端点 | `ws://<host>/ws` |
| 会话 | 连接即建 `session_id`(服务端生成,随 `first_frame`/`done` 带回)|
| 生命周期 | 单连接承载多回合;断线重连用原 `session_id` 恢复上下文 |
| 编码 | JSON,UTF-8,文本帧 |
| 管理通道 | 记忆清除/趋势/模型配置走 HTTP REST(`POST /admin/clear_memory`·`GET /admin/trends`·`GET /admin/config`·`POST /admin/config`)，不进 WS；WS 仅对话 8 消息 |
| 补给站通道 | 心灵补给站方案书走 HTTP REST:`POST /station/report/generate`(点击触发懒生成) · `GET /station/report/latest`(轮询,等待态"正在为你整理…")；不进 WS |
| 语音转写通道 | 语音输入两步式(ADR-004):`POST /asr/transcribe`(base64 webm/opus → 转写文本)供前端回填文本框,用户确认后按文本输入发送;不进 WS |

**补给站 REST 响应**(HTTP 200,两端点同形):

```json
{ "status": "ready", "report_md": "# 心理成长方案\n## 睡眠与焦虑的梳理" }
```

| 字段 | 值 | 说明 |
|---|---|---|
| status | `pending` \| `ready` | pending=已受理/生成中 |
| report_md | string | 仅 ready 返回;md 正文,前端预览/导出 |

- generate 受理即返;latest 轮询——生成中 `pending`,完成 `ready`+`report_md`

**语音转写请求/响应**(ADR-004)——请求 `POST /asr/transcribe`:

```json
{ "audio": "<base64 webm/opus>" }
```

响应(HTTP 200):

```json
{ "text": "最近总失眠" }
```

- 请求 `audio` 必填,单段 ≤15s(前端 MediaRecorder 侧约束),后端字节护栏 1MB 超限 413
- 转写成功(含空串="没听到")→ 200 + `text`;转写不可用(模型未加载/异常)→ 503
- 音频转写后即弃不落存储;日志 `asr_transcribed`/`asr_empty`(脱敏:只记长度+指纹)

---

## 2. 消息总览(9)

| 方向 | 类型 | 触发方 | 说明 |
|---|---|---|---|
| S→C | first_frame | 后端 | 新回合起点;告知 route / 模板 / 安抚语 |
| S→C | draw | 后端 | 黑板绘制数据(粗稿/逐轮/精稿统一)|
| S→C | text_delta | 后端 | 流式回复文本 |
| S→C | audio_chunk | 后端 | TTS 音频块(base64)|
| S→C | done | 后端 | 回合结束 |
| S→C | replay | 后端 | 重连回放(历史气泡/小结卡,ADR-005;无 seq)|
| C→S | user_input | 前端 | 用户文本输入(ADR-004 输入单源);采集轮次回答也用它 |
| C→S | mood_select | 前端 | 心情选择上报 |
| S→C | error | 后端 | 错误帧(见 §8)|

---

## 3. 消息定义(S→C)

### 3.1 first_frame

```json
{
  "type": "first_frame",
  "session_id": "sess_abc",
  "route": "collect",
  "template": "beck_formulation",
  "emotion_label": "疲惫",
  "mood_select": true,
  "text": "嗯，我在听。这个累不是矫情。"
}
```

| 字段 | 值 | 说明 |
|---|---|---|
| route | `collect` \| `crisis` | **answer 型不发 first_frame**,直接 text_delta |
| template | 模板 id | collect 才有,预告粗稿模板 |
| emotion_label | 快速研判标签 | 喂 Live2D + 粗稿 |
| mood_select | bool | crisis 恒 false;collect true |
| text | 安抚语 | 按情绪标签选文案 |

**前端语义**:收到 first_frame = **新回合起点 → 清空黑板、重置 seq 基线、收起心情选择器计时**(基线=旧帧判定起点;后端计数不重置,见 §3.2)。

### 3.2 draw

```json
{
  "type": "draw",
  "seq": 3,
  "template": "beck_formulation",
  "data": {
    "situation": "被 leader 当众否定",
    "emotion": { "label": "焦虑", "intensity": 0.85 },
    "thought": "我不行",
    "behavior": "逃避会议",
    "intermediate_belief": null,
    "core_belief": null
  }
}
```

- **data = 完整 formulation**(不是增量),前端按 seq 差动画新字段(已画的保留,新的淡入)
- seq:**会话内全局递增**(不随回合重置);前端忽略 `seq <= 已处理` 的旧帧;跨回合陈旧帧天然被丢弃

### 3.3 text_delta

```json
{ "type": "text_delta", "seq": 5, "text": "我们把它拆开看看——", "final": false }
```

- `final: true` 标记最后一块(可不依赖)

### 3.4 audio_chunk

```json
{ "type": "audio_chunk", "seq": 6, "format": "mp3", "data": "<base64>", "final": false }
```

- **可多帧**:TTS 按句合成,一段语音 = 多个 audio_chunk(seq 单调递增),前端按序连播
- **时序例外**:总结语音与安抚语异步流出,可在 `done` 之后到达(见 §6.2);前端播放队列独立于回合状态,下一回合 `first_frame` 清队(音频打断由 AudioQueue 承担)

### 3.5 done

```json
{ "type": "done", "session_id": "sess_abc", "seq": 7 }
```

- 前端:收起全部等待态(心情选择器、黑板"收尾中"提示)

### 3.6 replay(重连回放,ADR-005)

```json
{ "type": "replay", "mode": "bubbles", "turns": [ {"role": "user", "text": "最近很焦虑睡不着"}, {"role": "assistant", "text": "那种睡不着的时候,脑子里在想什么?"} ], "summary": "上次梳理围绕入睡困难展开,聊到工作中被批评的委屈。", "session_id": "sess_abc" }
```

- **触发**:重连认领(`user_input` 带原 session_id)后、本回合 first_frame 之前,主动推一次;新连接(不带 id)不推
- `mode: "bubbles"`(30min 内,热层 recent_turns 还在):`turns` 携带最近轮次原话(≤20 轮,`role: user|assistant`)+ `summary`(温层最新摘要,可为 null);前端幕布折叠式回放(历史收横幅,展开降饱和气泡)
- `mode: "digest"`(热层已过期):无 `turns`,`summary` 必有;前端小结卡片+提示"原话已按隐私设定抹去"
- 热层温层均无内容 → 不推帧(全新会话)
- 无 `seq`,不进回合计数(同 first_frame/error 语义)
- 治理联动:`POST /admin/clear_memory` 由前端先清浏览器存的身份,再调本端点

### 3.7 error

```json
{ "type": "error", "code": "invalid_message", "message": "字段缺失: text" }
```

| code | 含义 |
|---|---|
| invalid_message | 请求消息不合法(缺字段/类型错)|
| timeout | 采集/分析超时 |
| server_error | 后端异常,已降级 |

---

## 4. 消息定义(C→S)

### 4.1 user_input

```json
{
  "type": "user_input",
  "session_id": "sess_abc",
  "text": "最近总失眠",
  "ts": 1723456789
}
```

- `text` 必填;语音输入经 `POST /asr/transcribe` 转写回填文本框、用户确认后同此发送(ADR-004,输入单源文本)
- **采集轮次的回答也用此消息**(后端按会话状态识别第几轮)

### 4.2 mood_select

```json
{
  "type": "mood_select",
  "session_id": "sess_abc",
  "mood": "低落",
  "ts": 1723456789
}
```

- mood 取值(6 档):`难过 / 低落 / 平静 / 还好 / 开心 / 很好`
- **独立到达**(无活跃回合):后端仅更新 L7 profile,回 `text_delta`(短安抚) + `done`(**不发 first_frame**,与 §3.1 answer 一致);Live2D 表情由前端 mood_select 本地触发
- **回合内到达**(§6.2 采集期):仅更新 L7 profile,不回帧,采集照常等待轮次回答

---

## 5. 数据对象

### 5.1 formulation(collect 专用,后端填 / 前端渲染)

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

- 未采字段 = null(前端不画该格;belief 字段允许留白,后端不硬填)

**测试模板 data**：
- `emotion_wheel`：`{ emotions: [{ label: string, intensity: 0~1, color: string }] }`
- `stage_map`：`{ nodes: [string], current: int, from: string }`

### 5.2 枚举

| 枚举 | 值 |
|---|---|
| route | `answer` / `collect` / `crisis` |
| template | `beck_formulation`(默认,MVP 采集)· `emotion_wheel` · `stage_map`(测试模板,危机用)|
| mood_select.mood | 见 §4.2 六档 |
| emotion.intensity | 0~1 或 null(研判无强度可缺省) |

---

## 6. 时序

### 6.1 answer(直接答,无黑板)

```
C→S  user_input
S→C  text_delta ×N   (流式;知识型走 RAG 后同)
S→C  done
```

### 6.2 collect(多轮采集)

```
C→S  user_input
S→C  first_frame (route=collect, template, 安抚语, mood_select=true)
S→C  draw (seq=1, 粗稿: emotion + 占位)
S→C  audio_chunk ×N (安抚语语音,可选)
S→C  text_delta (确认情绪 + 第 1 问)
     C→S  mood_select (可选,用户点了才发)
     C→S  user_input (第 1 轮回答)
S→C  draw (全量,+situation+emotion)
S→C  text_delta (确认 + 第 2 问)
     C→S  user_input (第 2 轮回答)
S→C  draw (全量,+thought+behavior)
S→C  text_delta (确认 + 第 3 问)
     [充分度 ≥0.7 或轮数上限 → 停采 → 停采后同步分析]
S→C  audio_chunk ×N (等待语音,可选)
S→C  draw (精稿: 完整 formulation)
S→C  text_delta ×N (人话总结,末尾拼心灵补给站邀请语)
S→C  done
S→C  audio_chunk ×N (总结语音,异步流出,可选;done 后到达,抢占即蒸发)
```

- **降级**(答案过短/话题漂移/负面词):后端跳过剩余轮次,直接发精稿 draw + 转共情陪聊/已采字段收尾;情绪变差命中软预筛 → 改发危机序列(§6.3)
- **分析等待**:停采后同步分析,精稿 draw 前有分析耗时(前端显示"收尾中");后台并行属二期
- **seq 示例**:时序图仅粗稿标 seq=1;text/audio 交错消耗号,后续帧不标数值(递增规则见 §3.2)

### 6.3 crisis(危机)

```
C→S  user_input
S→C  first_frame (route=crisis, 郑重安抚, mood_select=false)
S→C  draw (seq=1, template:"stage_map", data:{nodes:["现在","拨打热线","专业支持"], current:0, from:"你不是一个人"})
S→C  text_delta (热线 12356 引导)
S→C  done
```

---

## 7. 回合与中断

| 规则 | 值 |
|---|---|
| 回合起点 | 收到 first_frame → 前端清黑板、重置动画基线(seq 会话内全局,不重置) |
| 旧帧处理 | 收到 `seq <= 已处理` 的 draw 忽略 |
| 新回合抢占 | 采集/分析未完成时用户发新 user_input → 后端中止当前回合,发新 first_frame(前端自动清黑板)|
| 超时 | 无 S→C 消息满 15s(可调常量)→ 前端显示"还在处理";后端处理任一 user_input 满 60s(可调常量,自该消息到达起算)→ `error(code=timeout)` 兜底 |

---

## 8. 错误处理

1. 后端收到非法 C→S 消息 → 回 `error(code=invalid_message)`,**不崩连接**
2. 采集/分析超时 → `error(code=timeout)` + 转降级回复
3. 后端异常 → `error(code=server_error)`,前端显示温和兜底话术(非医疗、不恐慌)
4. 重连:前端带 `session_id` 重连,后端恢复热层上下文(ADR-001:重建 turns;ADR-005:先推 `replay` 帧回放)

---

## 9. 日志范式(双输出)

### 9.1 双输出

| 输出 | 形态 | 级别 | 用途 |
|---|---|---|---|
| 控制台 | **彩色可读**(Loguru 风格:绿时间 + 级别 + 青`模块:行号` + 短消息)| INFO 默认;`--verbose` → DEBUG | 开发/演示,评审看得懂 |
| 文件 | **结构化 JSON**(全部字段)| DEBUG | 排查/审计,`logs/debug_{date}.log` |

### 9.2 标准字段(两条输出共用)

| 字段 | 说明 |
|---|---|
| ts | ISO 8601(含时区)|
| level | DEBUG / INFO / WARN / ERROR / FATAL |
| service | `hrp-backend` / `hrp-frontend` |
| session_id | 会话关联键 |
| trace_id | 回合自增 ID(会话内从 0 递增)|
| event | 事件名(§9.3)|
| route | answer / collect / crisis(有则带)|
| message | 简短描述 |

### 9.3 级别与事件

| 级别 | 用在哪 |
|---|---|
| DEBUG | WS 消息收发明细(默认关闭)|
| INFO | 回合开始/结束、路由判定、done |
| WARN | 危机审计、降级触发、超时降级 |
| ERROR | 消息非法、后端异常、error 帧发出 |
| FATAL | 进程级故障 |

事件: `session_open` · `user_input_received` · `crisis_gate_hit` · `route_decided` · `first_frame_sent` · `collection_round` · `sufficiency_scored` · `degraded` · `analysis_start` · `analysis_end` · `draw_sent` · `done` · `error`;REST 侧: `asr_transcribed` · `asr_empty`(归属 `/asr/transcribe`,ADR-004)

### 9.4 脱敏(硬约束)

1. 用户文本:不落日志;需要时记**长度或哈希**,不记原文
2. 音频:绝不落库、绝不落日志
3. 凭证(AES-GCM 密钥 / API key):绝不落
4. **危机命中必须落审计日志**(WARN,event=crisis_gate_hit,含命中项 + 是否转热线,不含原文)——安全合规要求,不可省略

### 9.5 轮转与健壮

- 文件轮转 10MB、保留 30 天(`rotation=10MB, retention=30 days`)
- uncaught 异常用 `logger.catch` 兜底,避免进程崩溃静默
- 二期接 ELK / Datadog 聚合

---

## 10. 前后端各自实现清单(开工检查)

**前端**
1. WS 客户端(7+1 消息解析、seq 校验、断线重连)
2. first_frame → 清黑板/重置/收起选择器
3. draw → 增量渲染(新字段动画)
4. mood_select 上报(含独立到达)
5. error → 温和兜底

**后端**
1. WS 网关(session_id、消息路由、seq 管理)
2. first_frame 生成(route/template/安抚语)
3. draw 下发(粗稿/逐轮/精稿)
4. mood_select 处理(profile 更新 / 独立到达)
5. error 帧 + 超时兜底
