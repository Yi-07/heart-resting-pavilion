# WS 前后端契约 · ws-contract

> **权威源**:`architecture-spec-v3.md`(本文件为其工程落地补充,不覆盖)
> **范围**:前后端 WebSocket 单连接的**完整消息契约**。前端内部(模板声明/渲染器)不在此文档。

---

## 1. 连接与会话

| 项 | 值 |
|---|---|
| 端点 | `ws://<host>/ws` |
| 会话 | 连接即建 `session_id`(服务端生成,随 `first_frame`/`done` 带回)|
| 生命周期 | 单连接承载多回合;断线重连用原 `session_id` 恢复上下文 |
| 编码 | JSON,UTF-8,文本帧 |
| 管理通道 | 记忆清除/趋势/模型配置走 HTTP REST(`POST /admin/clear_memory`·`GET /admin/trends`·`POST /admin/config`)，不进 WS；WS 仅对话 8 消息 |
| 补给站通道 | 心灵补给站方案书走 HTTP REST:`POST /station/report/generate`(点击触发懒生成) · `GET /station/report/latest`(轮询,等待态"正在为你整理…")；不进 WS |

---

## 2. 消息总览(8)

| 方向 | 类型 | 触发方 | 说明 |
|---|---|---|---|
| S→C | first_frame | 后端 | 新回合起点;告知 route / 模板 / 安抚语 |
| S→C | draw | 后端 | 黑板绘制数据(粗稿/逐轮/精稿统一)|
| S→C | text_delta | 后端 | 流式回复文本 |
| S→C | audio_chunk | 后端 | TTS 音频块(base64)|
| S→C | done | 后端 | 回合结束 |
| C→S | user_input | 前端 | 用户文字/音频;采集轮次回答也用它 |
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

**前端语义**:收到 first_frame = **新回合起点 → 清空黑板、重置 seq、收起心情选择器计时**。

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

### 3.5 done

```json
{ "type": "done", "seq": 7 }
```

- 前端:收起全部等待态(心情选择器、黑板"收尾中"提示)

### 3.6 error

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
  "mode": "text",
  "text": "最近总失眠",
  "audio": null,
  "ts": 1723456789
}
```

- `mode: text` → text 必填;`mode: audio` → audio 必填(base64, 编码 webm/opus, 单段 ≤15s)
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
     C→S  mood_select (可选,用户点了才发)
     C→S  user_input (第 1 轮回答)
S→C  draw (seq=2, +situation+emotion)
     C→S  user_input (第 2 轮回答)
S→C  draw (seq=3, +thought+behavior)
     [充分度 ≥0.7 或轮数上限 → 停采集 → 停采后同步分析]
S→C  draw (seq=4, 精稿: 完整 formulation)
S→C  text_delta ×N (人话总结/方案)
S→C  audio_chunk ×N (可选)
S→C  done
```

- **降级**(答案过短/话题漂移/负面词):后端跳过剩余轮次,直接发精稿 draw + 转共情陪聊/已采字段收尾;情绪变差命中软预筛 → 改发危机序列(§6.3)
- **分析等待**:停采后同步分析,精稿 draw 前有分析耗时(前端显示"收尾中");后台并行属二期

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
| 超时 | 前端 15s(可调常量)无 S→C 消息 → 显示"还在处理";60s(可调常量)后端 `error(code=timeout)` 兜底 |

---

## 8. 错误处理

1. 后端收到非法 C→S 消息 → 回 `error(code=invalid_message)`,**不崩连接**
2. 采集/分析超时 → `error(code=timeout)` + 转降级回复
3. 后端异常 → `error(code=server_error)`,前端显示温和兜底话术(非医疗、不恐慌)
4. 重连:前端带 `session_id` 重连,后端恢复热层上下文

---

## 9. 日志范式(双输出:控制台给人读,文件给机器查)

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
| service | `mental-health-backend` / `mental-health-frontend` |
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

事件: `session_open` · `user_input_received` · `crisis_gate_hit` · `route_decided` · `first_frame_sent` · `collection_round` · `sufficiency_scored` · `degraded` · `analysis_start` · `analysis_end` · `draw_sent` · `done` · `error`

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
