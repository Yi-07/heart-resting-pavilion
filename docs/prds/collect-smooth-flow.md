# PRD · collect 链路顺滑化

> 产品需求文档。描述 collect 链路「抢占保留采集态 + 陪聊不占轮次 + prompt 注入对话历史 + 等待期气泡统一 + 心情按钮组改造」的改动面。机制权威源见 [architecture-spec.md](../../architecture/architecture-spec.md)「三路路由」「L4 · 空窗期策略」;消息契约见 [ws-contract.md](../../architecture/ws-contract.md)「3.1 first_frame」「4.2 mood_select」「6.2 collect」;本 PRD 不复制其内容。

## Problem Statement

collect 链路体验五处断点(2026-10-13 检查会话逐项取证):

1. **抢占清空采集态**:轮次回答处理期间用户再发一条 → 网关 preempt 分支把 `collect_state` 整体置 None(formulation/round_index/pending_question 全丢),下条输入重新走 entry。timeout(60s)与 exception 路径同样清空。用户在问话流式期间补话(倾诉常见行为)导致梳理进度蒸发。
2. **陪聊轮占提问轮次**:`_prepare` 对每条非重试输入 `round_index += 1`,`where_next` 以 `round_index >= max_rounds` 收尾。连续两轮 off_topic 陪聊后第三条输入即 finish(max_rounds),可能一问未答就收尾,analysis 对空表格总结。`ask_messages` 的 rounds_left 被蚕食,问话 prompt 提前进入催促态。
3. **问话/陪聊 LLM 无对话历史**:九个 LLM 调用点全部单发 `[system, user]` 双消息,上下文靠字符串拼接(提炼值截 24 字),turns 原话(回合内 + 热层重连重建)从不进 prompt。问话「接住上文」只有本轮回答可用,跨轮连贯性差。answer 路 `_answer_messages` 同病。
4. **首轮等待文案闪跳**:气泡 `bubbleText` 双分支——awaiting/analysis 显示「小栖正在梳理你说的…」,collecting+无文本显示「我在听。」;首条输入后 ~300ms first_frame 到达相位切 collecting,文案瞬切 + 0.4s 淡出动画 → 「我在听」一闪而过。该分支实为死文案(bubbleOn 在 collecting+无文本时为 false)。
5. **心情按钮组缺位 + 自动弹出打扰**:mood_select 浮层 first_frame 即弹(10s 超时),此时系统对用户一无所知选出多为噪声;emotion entry 已由研判标签预填,自报通道与采集时刻脱节;预置语音(心情回执/总结 PCM)跨路径播放无仲裁——总结播放中点按钮两路同时出声;连续点按回执排队顺播,文本即时替换造成声文错位。

## User Stories

1. 作为用户,我在小栖提问时补充一句话,希望接着聊下去,而不是黑板清空从头再来。
2. 作为用户,我跑题闲聊几轮后回来,希望小栖接着问没问完的,而不是突然开始总结。
3. 作为用户,我希望小栖记得几分钟前我说过的话,不要每问都像第一次见面。
4. 作为用户,我发送消息后希望气泡稳定告诉我「正在梳理」,而不是文案闪烁跳变。
5. 作为用户,我想点「今日心情」表情告诉小栖我的状态,听到温暖的回应引导我开始对话;连续点按不应声音叠在一起。

## Solution

按六面分票(机制细节以权威文档为准,此处记改动面与验收口径):

### 1. 抢占保留采集态(T1,后端)

- 网关 `_on_message` preempt 分支:取消当前任务后**保留** `conn.collect_state`(新输入由 prepare 当本轮回答消费,pending_question 语义天然衔接;ADR-005 turns 倒查已为此设计)。
- 同批收敛 timeout/exception 两路径:非挂起态不再清 state(与 AskFailed 的 `ask_retry` 挂起范式看齐)。
- 危机闸门销毁采集态**不变**(安全红线)。
- 已知边界随修:preempt 后 state 保留但 emitter 必须换新(旧 emitter 已 mark_dead,由 `_collect_sequence` 每回合新建,现状已满足)。
- 注意 task.done() 调度窗口误判问题(gateway 注释 backlog)与本次同源,一并评估。

### 2. 陪聊轮不占提问轮次(T2,后端)

- 轮次语义改「提问轮」:`round_index` 只在真正发出问话(AskNext)时递增;陪聊轮(EmpathChat)不计数。
- 实现落点:`_prepare` 轮次分支的 `round_index += 1` 移除,改由 `_ask` 成功路径计数;`ask_retry` 失败轮不计数语义不变。
- 文档先行:spec §4 L4「多轮采集(上限 3 轮)」的「轮」定义补一句「提问轮;陪聊/降级轮不计」。
- **陪聊驻留不设上限(裁定 2026-10-13)**:off_topic 陪聊轮数不限,但每轮陪聊回应后须带出一句与**当前挂起提问所需信息**相关的语句,引导用户回到采集:
  - 该语句必须与陪聊回应正文衔接自然(陪聊话题与当前回合的采集多少相关;实在无关时,以「前面你提到的…」式回指点一下本回合挂起的提问)。
  - prompt 侧:`chat_messages` 注入当前挂起提问的 target_field 与其 info_need(`FIELD_INFO_NEED`/`next_field` 现有单源,零新机制),system 段约束「回应后自然衔接一句指向挂起提问信息需求的语句;话题实在无关时用『前面你提到的…』回指点题」。
  - 引导后是否回题由用户主导(提取阶段判定),不强拉、不重发完整问句。

### 3. prompt 注入 turns 历史(T3,后端)

- 注入分层:turns 在(回合内 + 热层 30min 重连重建)→ 注入最近 6~8 轮原话(role 标注,含 assistant 问句);turns 清(热层过期)→ 降级注入 history_summary(回合级);都无 → 现状(filled 提炼值)。
- 落点:`ask_messages` / `chat_messages`(问话与陪聊);answer 路 `_answer_messages` 同批注入(热层 recent_turns 查询已有)。
- 截断预算对齐 `_soft_review` 的 6 轮先例;prompt 不落日志,原话进 prompt 不碰脱敏红线(§7)。
- `ask.py` filled 三字段拼接保留(结构化提炼与原话语境不互补);`extract.py` docstring 40 字 vs 常量 24 的陈旧注释顺带修。

### 4. 等待期气泡统一(T4,前端)

- `ChatPanel.vue` bubbleText:有旧文本显示旧文本;无旧文本且回合活跃(awaiting/collecting/analysis)→ 一律「小栖正在梳理你说的…」;删「我在听。」分支。
- bubbleOn:collecting+无文本期间保持可见。
- 链路效果:首条输入 → 「正在梳理」持续到第一问文字到达;中间轮等待显示上一问;总结等待由 P7 等待话术声文同发(bd98fb7 已落地)。

### 5. 心情按钮组改造(T5,前端+后端)

- **形态**:toolbar「今日心情」点击 → 表情按钮组浮层(六档,复用 MOODS 常量);点表情 → `audio.flush()` → 发 mood_select → 按钮组置灰冷却。
- **回执**:走现有独立到达路径(`gateway.py` `_on_mood_select` 无回合分支:MOOD_ACK 预置文本 + mood_ack 预置 wav + done),文案不改(裁定 2026-10-13:现有六档文案已含对话诱导,「引导开场」是定位描述非改写要求)。
- **冷却**:done 帧驱动解除置灰(App.vue 已 track done;独立到达路径回执完必发 done),~8s 兜底计时器防连接异常卡死。
- **回合内置灰**:采集/回答进行中按钮组置灰(disabled + title 提示,心灵练习模式),不做 v-if 真隐藏(工具栏不跳动);定位「开场专用」。
- **废弃自动弹出**:first_frame.mood_select 驱动浮出的链路移除;前端清 moodVisible 驱动 + 10s 超时逻辑(`selector.ts` show/hide 简化);契约 §3.1 mood_select 字段语义改「恒 false(预留)」,前端 round.ts 的 enterCollect 相应简化。
- **手点锁联动废弃**:`selector.select()` 的 `setManualMood`(锁 draw emotion 覆盖)随自动弹出一起移除;回合外点按不碰回合状态。
- in_round mood_select 记 profile 不回帧行为保留(契约 §4.2),按钮组回合内置灰后自然不可达,兜底语义不变。

### 6. 音频衔接仲裁(T6,前端,可选进批)

- **第一层(并入 T5 必做)**:按钮点击即 flush(已述)。
- **第二层(已裁定进批,2026-10-13)**:预置语音 wav 帧补 round_id 语义——`send_audio` 已有 `round_id` 参数,预置路径按逻辑组传(如 `preset-mood-{ts}`、`preset-crisis-{trace}`,危机两句同组);AudioHub 对 wav 帧按 round_id 路由:同组排队(保 crisis_soothe→hotline 顺播),新组 → 双链 flush 后接管(与 PCM 自认领对称)。
- 契约先行:ws-contract §3.4 wav 帧的 round_id 语义(现注「可不依赖」)先改再编码。

## Non-Goals

- emotion 字段改「真问」(研判标签只作候选)——动问序行为,联动充分度/板式,另立任务线。
- 分析期 mood_select 弹出 + 自报融合进 review_emotion——上一轮讨论的落点 (b),被「按钮组开场专用」裁定替代;若后续要做,接口已留(mood_select 消息不变)。
- 后端「思考中」状态帧(等待期提示的契约信号方案)——前端推断已满足,不加契约面。
- 对话历史进 classifier/风险复核 prompt——只做问话/陪聊/answer 三处,其余调用点上下文现状够用。

## Acceptance Criteria

1. collect 轮次处理中再发一条输入:formulation 已采字段保留,round_index 不重置,黑板不清板(新 draw 增量)。
2. 连续两轮 off_topic 后再发实质输入:进入提问而非 finish;rounds_left 反映提问轮而非总轮次。
3. 问话 prompt 包含最近对话原话(测试桩断言 messages 内容);热层过期场景降级注入 summary。
4. 全新会话首条输入:气泡从发送起持续显示「正在梳理」,无「我在听」闪跳。
5. 「今日心情」点表情:回执声文同发,冷却期按钮不可点,done 后恢复;collect 进行中按钮组置灰。
6. 总结 PCM 播放中点表情:总结淡出,回执独播,无叠声。
7. 回归:后端 ruff/mypy/pytest 全过;前端 type-check/lint/test:unit 全过。

## 开放问题(裁定台账,2026-10-13 全部关闭)

| # | 问题 | 裁定 |
|---|---|---|
| Q1 | T6 第二层 wav round_id 进不进本批 | **进批**(Solution 6 已同步) |
| Q2 | T2 off_topic 陪聊是否设驻留上限 | **不设上限**;但每轮陪聊回应须自然衔接下一个待采字段信息需求,引导回采集(Solution 2 已同步) |
| Q3 | T5 心情回执文案是否改写 | **不改**;现有文案已含对话诱导(Solution 5 已同步) |
| Q4 | T1 连发多条输入的行为 | **确认:最后一条胜出**(现状语义,无需新机制) |
