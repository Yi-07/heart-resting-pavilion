"""collect 图(backend-plan §5;LangGraph StateGraph,确定性条件边)。

每次 user_input = 一次短图调用,跑到「等待下一条输入」(AskNext/EmpathChat)
或「回合终结」(Finish/Escalate)即返回;CollectState 挂连接对象,节点只读写;
相位不落 state——去向由 where_next 纯函数从 escalate/degrade/sufficiency/
round_index 算出。emitter 经 config 注入,不进 state。

节点:prepare(entry 粗稿 / 轮次填格+打分+降级)→ cond(where_next)
  ask(确认+下一问,预置问题库) / chat(共情陪聊,off_topic) / risk+analysis
risk:软预筛(gate.SOFT_TERMS 过全部 user 轮)→ 命中才 LLM 复核(唯一验收点);
  复核失败不升级(WARN 记录,硬闸门已每条过)。情绪强度环比上升检测二期。
analysis:emotion 复核(两级标签第二级)→ 精稿 draw → RAG 引用 → 流式总结
  → 邀请语(phrases,不走 LLM);LLM 失败话术兜底,精稿照发。
MVP 润色跳过:问话骨架全预置(性能热点 §6:预置优先于 LLM 生成)。
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Literal, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app import collect
from app.agents import analysis
from app.agents.emitter import ConnEmitter, stream_final
from app.agents.extract import extract_field
from app.agents.state import (
    AskNext,
    CollectEvent,
    CollectState,
    EmpathChat,
    Escalate,
    FieldKey,
    Finish,
    FinishCause,
    PendingQuestion,
)
from app.llm import LLMError, Message, get_provider
from app.router import gate, phrases
from app.schema import Emotion, Formulation


class GraphState(TypedDict, total=False):
    cs: CollectState
    event: CollectEvent


Step = Literal["ask", "chat", "finish", "escalate"]


def where_next(cs: CollectState) -> Step:
    """条件边纯函数(backend-plan §3.1):四去向,读字段不落相位。"""
    if cs.escalated:
        return "escalate"
    if cs.degrade_reason == "negative":
        return "finish"
    if cs.degrade_reason == "off_topic":
        return "chat"
    if collect.should_stop(cs.sufficiency) or cs.round_index >= cs.max_rounds:
        return "finish"
    return "ask"


def _finish_cause(cs: CollectState) -> FinishCause:
    """终结三因:降级 > 充分度 > 轮数(从字段现算,不落相位)。"""
    if cs.degrade_reason is not None:
        return cs.degrade_reason
    if collect.should_stop(cs.sufficiency):
        return "sufficient"
    return "max_rounds"


def _fill(cs: CollectState, field: FieldKey, value: str) -> None:
    if field == "emotion":
        cs.formulation.emotion = Emotion(label=value)
    else:
        setattr(cs.formulation, field, value)


def _emitter(config: RunnableConfig) -> ConnEmitter:
    # 测试注入假 emitter(同协议),cast 不做运行时强校验
    return cast(ConnEmitter, config["configurable"]["emitter"])


# ---- 节点 ----


async def _prepare(state: GraphState, config: RunnableConfig) -> dict:
    cs = state["cs"]
    em = _emitter(config)

    if cs.round_index == 0 and cs.pending_question is None:
        # entry:粗稿(快速研判标签入 emotion,intensity 缺省)
        if cs.emotion_label and cs.formulation.emotion.label is None:
            cs.formulation.emotion = Emotion(label=cs.emotion_label)
        cs.sufficiency = collect.sufficiency(cs.formulation)
        await em.draw(cs.formulation)
        em.log("collection_round", round_index=0, sufficiency=cs.sufficiency, phase="draft")
        return {}

    # 轮次:消费最近一条 user 轮为本轮回答(ADR-005:assistant 轮也入 turns,
    # turns[-1] 可能是上一问——按 role 倒查,不能只取末条)
    answer = next((t.text for t in reversed(cs.turns) if t.role == "user"), "")
    cs.round_index += 1
    pending = cs.pending_question
    cs.pending_question = None

    if pending is None:
        # 陪聊轮回答:不填格、无 draw;清降级位避免 off_topic 死循环
        cs.degrade_reason = None
        return {}

    reason = collect.detect(answer)
    value: str | None = None
    if reason is None:
        value = await extract_field(pending.target_field, pending.text, answer)
        if value is None:
            reason = "off_topic"

    if reason is None and value is not None:
        _fill(cs, pending.target_field, value)
        cs.degrade_reason = None
        cs.sufficiency = collect.sufficiency(cs.formulation)
        await em.draw(cs.formulation)
        em.log(
            "sufficiency_scored",
            round_index=cs.round_index,
            score=cs.sufficiency,
            filled=pending.target_field,
        )
    else:
        cs.degrade_reason = reason
        em.log(
            "degraded",
            level="WARN" if reason == "negative" else "INFO",
            reason=reason,
            round_index=cs.round_index,
        )
    return {}


async def _ask(state: GraphState, config: RunnableConfig) -> dict:
    cs = state["cs"]
    em = _emitter(config)
    field = collect.next_field(cs)
    if field is None:  # 全满兜底(正常应被充分度拦截)
        return {"event": Finish(cause="sufficient")}
    retry = cs.degrade_reason == "too_short"
    question = collect.question_for(field, retry=retry)
    if cs.round_index == 0:
        confirm = ""  # entry 首问:尚无内容可确认,不带"记下了"式确认语
    elif retry:
        confirm = phrases.RETRY_ACK
    else:
        confirm = phrases.CONFIRM_BY_FIELD[field]
    cs.pending_question = PendingQuestion(text=question, target_field=field)
    cs.degrade_reason = None
    await em.text(f"{confirm}{question}")
    return {"event": AskNext(confirm=confirm, next_question=question, target_field=field)}


async def _chat(state: GraphState, config: RunnableConfig) -> dict:
    em = _emitter(config)
    reply = phrases.EMPATH_CHAT_REPLY
    await em.text(reply)
    return {"event": EmpathChat(reply=reply)}


class _RiskOut(BaseModel):
    risky: bool


_RISK_SYSTEM = (
    "你是心理安全风险评估器。用户在倾诉过程中出现了低档位风险信号。"
    '判断其近期表述是否构成需要立即转危机干预的自伤/自杀风险。只输出 JSON:{"risky":true|false}。'
    "标准:出现明确自伤意图/计划/工具才 risky;单纯情绪痛苦为 false。"
)


async def _risk(state: GraphState, config: RunnableConfig) -> dict:
    cs = state["cs"]
    em = _emitter(config)
    user_texts = [t.text for t in cs.turns if t.role == "user"]
    matched = [term for term in gate.SOFT_TERMS if any(term in t for t in user_texts)]
    if not matched:
        return {}
    recent = "\n".join(user_texts[-6:])
    risky = False
    try:
        out = await get_provider().chat_json(
            [Message("system", _RISK_SYSTEM), Message("user", recent)], _RiskOut
        )
        risky = out.risky
    except LLMError:
        # 复核失败不升级:硬闸门已每条过,软信号缺确认按陪聊收尾(WARN 留痕)
        em.log("risk_review_failed", level="WARN", matched=matched)
        return {}
    if risky:
        cs.escalated = True
        em.log(
            "crisis_gate_hit",
            level="WARN",
            hit=True,
            matched=matched,
            to_hotline=True,
            via="risk_review",
        )
        return {"event": Escalate()}
    return {}


async def _analysis(state: GraphState, config: RunnableConfig) -> dict:
    cs = state["cs"]
    em = _emitter(config)
    em.log("analysis_start")

    # 等待语音:停采→精稿之间的分析耗时,直发预生成 filler(契约 §6.2;缺文件跳过)
    from app.voice import fillers

    wav = await asyncio.to_thread(fillers.pick)
    if wav is not None:
        em.audio(wav)

    cs.formulation.emotion = await analysis.review_emotion(cs)
    cs.sufficiency = collect.sufficiency(cs.formulation)
    await em.draw(cs.formulation)  # 精稿(emotion 复核后全量)

    refs: list = []
    try:
        from app.rag import retrieve_async  # 懒加载

        query = " ".join(
            part
            for part in (
                cs.formulation.situation,
                cs.formulation.emotion.label,
                cs.formulation.thought,
            )
            if part
        )
        refs = await retrieve_async(query or "情绪", k=2)
    except Exception:  # noqa: BLE001 — RAG 失败/未就绪降级无引用总结
        em.log("degraded", level="WARN", reason="rag_failed")

    # 蒸馏总结文本:随流攒全量,Finish 带给网关落温层(降级用话术兜底文本)
    summary_parts: list[str] = []

    async def _tapped() -> AsyncIterator[str]:
        async for chunk in analysis.summary_stream(cs, refs):
            summary_parts.append(chunk)
            yield chunk

    try:
        sent = await stream_final(em, _tapped())
    except LLMError:
        em.log("degraded", level="WARN", reason="summary_llm_error")
        sent = False
    summary = "".join(summary_parts) if sent else phrases.SUMMARY_FALLBACK
    if not sent:
        await em.text(summary, final=True)
    await em.text(phrases.STATION_INVITE, final=True)

    em.log("analysis_end", summary_len=len(summary))
    return {"event": Finish(cause=_finish_cause(cs), summary=summary)}


async def _escalate_end(state: GraphState, config: RunnableConfig) -> dict:
    return {"event": Escalate()}


# ---- 装配 ----


def _build():
    graph = StateGraph(GraphState)
    graph.add_node("prepare", _prepare)
    graph.add_node("ask", _ask)
    graph.add_node("chat", _chat)
    graph.add_node("risk", _risk)
    graph.add_node("analysis", _analysis)
    graph.add_node("escalate_end", _escalate_end)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare",
        lambda s: where_next(s["cs"]),
        {"ask": "ask", "chat": "chat", "finish": "risk", "escalate": "escalate_end"},
    )
    graph.add_conditional_edges(
        "risk",
        lambda s: "end" if isinstance(s.get("event"), Escalate) else "proceed",
        {"end": END, "proceed": "analysis"},
    )
    graph.add_edge("ask", END)
    graph.add_edge("chat", END)
    graph.add_edge("escalate_end", END)
    graph.add_edge("analysis", END)
    return graph.compile()


_graph = _build()


async def run_collect(cs: CollectState, emitter: ConnEmitter) -> CollectEvent:
    """一次短图调用;返回四变体事件之一(网关按事件收尾)。"""
    result = await _graph.ainvoke({"cs": cs}, config={"configurable": {"emitter": emitter}})
    event = result.get("event")
    if event is None:
        raise RuntimeError("collect 图未产出事件")
    return event


__all__ = ["Formulation", "run_collect", "where_next"]
