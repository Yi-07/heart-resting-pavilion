# 后端实施方案 · 技术原型

> **版本**:v1 · **日期**:2026-08-12
> **权威源**:`architecture-spec-v3.md`(架构)· `ws-contract.md`(契约)
> **目标**:技术原型后端——跑通三路路由全链路(危机闸门 / 分类器 / 多轮采集 / Agent / 记忆 / 语音),日志与审计齐备。

---

## 1. 技术栈

| 项 | 选型 |
|---|---|
| 框架 | FastAPI + WebSocket |
| Agent | LangGraph 1.x(确定性 StateGraph,条件边编排,research-v1 Q2) |
| 环境 | uv(python)|
| 日志 | loguru(双输出:控制台彩色 + 文件结构化)|
| 存储 | SQLite(冷层)+ Redis(热/温层)|
| 语音 | CosyVoice 2(TTS,情感标签)+ SenseVoice(ASR,含情感识别)|
| LLM | DeepSeek(OpenAI 兼容)+ Ollama 本地,双源抽象 |

---

## 2. 目录结构

```
backend/
  app/
    main.py                # FastAPI 入口,挂 /ws
    ws_gateway.py          # WS 网关:session/seq/消息路由/error 帧
    config.py              # 模型配置(LLM/ASR/TTS,读环境变量)
    logger.py              # loguru 双输出 + 审计
    router/
      gate.py              # 危机闸门(词典 + 严重度打分)
      classifier.py        # 轻量分类器(route + emotion_label + conf)
    collect/
      state.py             # 采集器状态机
      questions.py         # 预置问题库(按空缺字段组织)
      sufficiency.py       # 充分度打分(权重表)
      degrade.py           # 三降级触发检测
    agents/
      graph.py             # LangGraph 图定义(supervisor)
      empath.py            # 共情:采集话术(确认+下一问)/人话总结
      knowledge.py         # 知识分析师(动态 RAG)
      risk.py              # 风险评估(软预筛 → LLM 复核)
      planner.py           # 计划制定者(方案生成 + 安全边界)
    llm/
      provider.py          # DeepSeek/Ollama 统一抽象(OpenAI 兼容)
    memory/
      hot.py               # Redis:会话上下文
      warm.py              # Redis:会话摘要
      cold.py              # SQLite:profile + 情绪趋势
    asr.py  tts.py         # SenseVoice / CosyVoice 封装
    schema/
      formulation.py       # Pydantic:formulation
      ws_messages.py       # 消息模型(对齐 ws-contract)
```

---

## 3. 采集器状态机(核心)

```
(route=collect 进入)
IDLE → FRAME_SENT:发 first_frame(安抚语 + 粗稿 draw)
FRAME_SENT → ROUND(i):共情 Agent 出"确认情绪 + 第 i 问"
ROUND(i):
  等 user_input → gate 再查 → 填 formulation → draw 增量
  充分度 ≥0.4 → ANALYSIS_RUNNING(二期接口位;MVP 不启动,停采后同步分析,research-v1 Q4)
  充分度 ≥0.7 或 i≥上限 → STOP
  降级触发 → DEGRADE
STOP → FINAL:精稿 draw + 分析总结(text_delta,末尾拼心灵补给站邀请语)+ done
DEGRADE: ①转共情陪聊 ②已采字段收尾 ③情绪变差→gate(危机转热线)
任意轮 gate 命中 → CRISIS:热线 + 支持画面 + 审计日志
```

**每轮输出(共情 Agent 结构化)**:
```json
{ "confirm": "被否定不等于你不配。", "next_question": "当时脑子里闪过了什么念头？", "target_field": "thought" }
```

---

## 4. 充分度打分

```python
WEIGHTS = {"situation": .20, "emotion": .20, "thought": .20,
           "behavior": .15, "intermediate_belief": .15, "core_belief": .10}

def sufficiency(f: Formulation) -> float:
    return sum(w for k, w in WEIGHTS.items() if getattr(f, k) is not None)
# 高阈值 0.7(可调常量);测试档 0.85 → 常态 3 轮挖信念
```

---

## 5. LangGraph 图定义(骨架)

```
nodes: empath · knowledge · risk · planner(监督职能=确定性条件边,无 LLM 派活,research-v1 Q2)
gate/classifier 已定 route,条件边分派:
    answer → (需 RAG ?) knowledge → 直答流式
    collect → empath(采集循环,状态=formulation)
            → risk(软预筛→复核,命中升级)
            → 停采 → analysis(同步:emotion 复核 + 总结 + RAG 引用,research-v1 Q4)
            → empath 总结(末尾拼心灵补给站邀请语)
            → planner = 心灵补给站方案书(用户点击触发,异步,REST 通道,research-v1 Q3)
            安全边界:非医疗声明 · 危机绕过 · 方案基于 RAG 知识
```

---

## 6. 危机与审计

- **gate.py**:危机词典 + 严重度打分(硬判,个位数 ms),与 L6 规则引擎**共享单一词典来源**
- 词典/降级阈值 = 配置数据,MVP 最小占位(危机核心词先跑),内容运行时补
- 每轮输入过 gate;命中 → CRISIS,落**审计日志**(WARN:命中项 + 是否转热线,不含原文)
- **risk.py**:软信号关键词预筛(低档位)→ 命中才 LLM 复核,控成本

---

## 7. LLM 双源抽象

```python
# llm/provider.py —— OpenAI 兼容统一入口
# DeepSeek: base_url=https://api.deepseek.com, model=deepseek-chat
# Ollama:   base_url=http://localhost:11434/v1, model=qwen2.5:7b(示例)
# 由 config.py 切换;R3 配置 UI 后续接管
```

> **provider 策略(mock 边界)**：
> - 真 provider：LLM(DeepSeek/Ollama) · ASR(SenseVoice/FunASR) · TTS(CosyVoice 2) · Live2D 真模型打包 · 记忆 SQLite 真存
> - **RAG = 预置问答对灌入 Chroma 跑真检索**(种子语料)；数据集就绪 = 往 Chroma 加数据，代码不变
> - 配置占位：危机/软信号词典、降级阈值(结构定、内容后补)
> - 收尾优化：本地兜底，单机离线演示
> - 不 mock 边界：契约(ws-contract)/WS 网关/采集状态机/充分度/黑板渲染 全真实现；provider 抽象接口保留，真实现与兜底同接口

---

## 8. WS 网关

- 每连接:建 session_id;`user_input/mood_select` 入口;`seq` 会话内全局递增(不随回合重置,对齐 ws-contract §3.2)
- 消息路由:按 `type` 分发到对应处理通道
- 非法消息 → `error(invalid_message)`;超时 → `error(timeout)` + 降级;异常 → `error(server_error)`
- 新 user_input 抢占旧回合 → 发新 first_frame

---

## 9. 日志(双输出,对齐 ws-contract §9)

- **控制台**:loguru 彩色可读(时间/级别/`模块:行号`/短消息),INFO 默认,`--verbose`→DEBUG
- **文件**:`logs/debug_{date}.log`,轮转 10MB / 保留 30 天
- **审计**:危机命中必落(WARN);用户文本只记长度/哈希;音频/凭证绝不落

---

## 10. 验收(后端视角,3 用例)

用 WS 客户端或脚本各跑一遍,查链路消息顺序 + 日志:

1. **answer**:`user_input("什么是正念")` → text_delta 流式 → done;无 draw
2. **collect**:`user_input("最近很焦虑睡不着")` → first_frame → 2 轮 draw 增量 → 精稿 → 分析总结+心灵补给站邀请语 → done(方案书由用户点击补给站触发,不在回合内);日志含 `crisis_gate_hit(hit:false)`、`route_decided(collect)`、`sufficiency_scored`
3. **crisis**:`user_input("我不想活了")` → first_frame(crisis) → 热线内容;日志含 **crisis_gate_hit(hit:true, audit)** 审计
