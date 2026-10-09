"""collect 图(backend-plan §5;LangGraph StateGraph,确定性条件边)。

每次 user_input = 一次短图调用,跑到「等待下一条输入」(AskNext/EmpathChat)
或「回合终结」(Finish/Escalate)即返回;CollectState 挂连接对象,节点只读写;
相位不落 state——去向由 where_next 纯函数从 escalate/degrade/sufficiency/
round_index 算出。emitter 经 config 注入,不进 state。

节点:prepare(entry 粗稿 / 轮次填格+打分+降级)→ softscan → cond(where_next)
  ask(确认+下一问,预置问题库) / chat(共情陪聊,off_topic) / risk+analysis
softscan:每轮软预筛(gate.SOFT_TERMS 过全部 user 轮,spec §4 L5)→ 新增命中
  (risk_reviewed_terms 去重)才 LLM 复核;risk=终结路径增量复核(同一去重)。
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
from app.agents.extract import extract_fields
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
from app.board import asset_system
from app.llm import LLMError, Message, get_provider
from app.router import gate, phrases
from app.schema import Emotion, Formulation, SceneFormulation


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


_NO_EXTRACT_FIELDS: tuple[FieldKey, ...] = ("intermediate_belief", "core_belief")
"""信念字段永不进提取(spec 信念留白:后端不硬填,分析阶段也不产)。"""


def _field_filled(cs: CollectState, field: FieldKey) -> bool:
    return cs.formulation.is_filled(field)


def _open_fields(cs: CollectState, target_field: FieldKey) -> list[FieldKey]:
    """本轮可提取字段:所问字段优先,其余按问序;信念字段排除(留白)。"""
    fields = [f for f in collect.ASK_ORDER
              if f not in _NO_EXTRACT_FIELDS and not _field_filled(cs, f)]
    if target_field in fields:
        fields.remove(target_field)
        fields.insert(0, target_field)
    return fields


def _emitter(config: RunnableConfig) -> ConnEmitter:
    # 测试注入假 emitter(同协议),cast 不做运行时强校验
    return cast(ConnEmitter, config["configurable"]["emitter"])


def _scene_draw_data(cs: CollectState, assets: dict[str, str] | None) -> SceneFormulation:
    """黑板 draw 数据:formulation 快照 + 选材 assets(域对象不混选材,归档干净)。

    assets 由调用方先经 selector.apply 得出(单次调用,熔断计数不双计);
    None=selector 未挂/熔断/无选材,前端全落槽位默认图标。
    """
    data = SceneFormulation(**cs.formulation.model_dump())
    if assets:
        data.assets = assets
    return data


_TRIGGER_FIELDS: tuple[str, ...] = ("situation", "thought", "behavior")
"""板式接力触发集:非情绪三字段任一首次入格且本轮选材含其图标
→ scene_default 切 scene_focus;emotion 不在内(开场由研判种子占位,算入会让
暖场景只活一帧)。无有效图标(如目录无对应素材)维持暖场景候着。"""


def _maybe_switch_template(cs: CollectState, assets: dict[str, str] | None) -> None:
    """板式接力单源:scene_default → scene_focus 单向一次。"""
    if cs.template != "scene_default":
        return
    if not any(f in (assets or {}) for f in _TRIGGER_FIELDS):
        return
    cs.template = "scene_focus"


def _applied_assets(cs: CollectState) -> dict[str, str] | None:
    """本轮选材经白名单/熔断的唯一入口(selector.apply 有状态,只许调一次)。"""
    selector = cs.asset_selector
    if selector is None or not cs.pending_assets:
        return None
    return selector.apply(cs.pending_assets)


# ---- 节点 ----


async def _prepare(state: GraphState, config: RunnableConfig) -> dict:
    cs = state["cs"]
    em = _emitter(config)

    if cs.round_index == 0 and cs.pending_question is None:
        # entry:粗稿(快速研判标签入 emotion,intensity 缺省)
        if cs.emotion_label and cs.formulation.emotion.label is None:
            cs.formulation.emotion = Emotion(label=cs.emotion_label)
        cs.sufficiency = collect.sufficiency(cs.formulation)
        await em.draw(_scene_draw_data(cs, _applied_assets(cs)))
        em.log("collection_round", round_index=0, sufficiency=cs.sufficiency, phase="draft")
        return {}

    # 轮次:消费最近一条 user 轮为本轮回答(ADR-005:assistant 轮也入 turns,
    # turns[-1] 可能是上一问——按 role 倒查,不能只取末条)
    answer = next((t.text for t in reversed(cs.turns) if t.role == "user"), "")
    cs.round_index += 1
    pending = cs.pending_question

    if pending is None:
        # 陪聊轮回答:不填格、无 draw;清降级位避免 off_topic 死循环
        cs.degrade_reason = None
        return {}

    reason = collect.detect(answer)
    values: dict[FieldKey, str] = {}
    cs.pending_assets = None
    if reason is None:
        selector = cs.asset_selector
        asset_hint = asset_system(selector.catalog) if selector is not None else None
        values, raw_assets = await extract_fields(
            pending.text, pending.target_field, answer, _open_fields(cs, pending.target_field),
            asset_hint=asset_hint,
        )
        cs.pending_assets = raw_assets or None
        if not values:
            reason = "off_topic"

    if reason is None:
        for field, value in values.items():
            _fill(cs, field, value)
        if pending.target_field in values:
            cs.pending_question = None  # 本题已答;未答则保留挂起,防下一条被吞
        cs.degrade_reason = None
        cs.sufficiency = collect.sufficiency(cs.formulation)
        assets = _applied_assets(cs)
        _maybe_switch_template(cs, assets)
        await em.draw(_scene_draw_data(cs, assets))
        em.log(
            "sufficiency_scored",
            round_index=cs.round_index,
            score=cs.sufficiency,
            filled=",".join(values),
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
    await em.text(f"{confirm}{question}", final=True)
    return {"event": AskNext(confirm=confirm, next_question=question, target_field=field)}


async def _chat(state: GraphState, config: RunnableConfig) -> dict:
    em = _emitter(config)
    reply = phrases.EMPATH_CHAT_REPLY
    await em.text(reply, final=True)
    return {"event": EmpathChat(reply=reply)}


class _RiskOut(BaseModel):
    risky: bool


_RISK_SYSTEM = (
    "你是心理安全风险评估器。用户在倾诉过程中出现了低档位风险信号。"
    '判断其近期表述是否构成需要立即转危机干预的自伤/自杀风险。只输出 JSON:{"risky":true|false}。'
    "标准:出现明确自伤意图/计划/工具才 risky;单纯情绪痛苦为 false。"
)


def _soft_matched(cs: CollectState) -> set[str]:
    """软预筛(纯规则):SOFT_TERMS 子串过全部 user 轮(spec §4 L5 每轮)。"""
    user_texts = [t.text for t in cs.turns if t.role == "user"]
    return {term for term in gate.SOFT_TERMS if any(term in t for t in user_texts)}


async def _soft_review(cs: CollectState, em: ConnEmitter, new_terms: set[str]) -> None:
    """软信号 LLM 复核(唯一升级验收点):risky → escalated 置位,由条件边统一
    走 escalate_end 出 Escalate 事件;复核失败不升级(WARN 留痕,硬闸门已每条过)。"""
    user_texts = [t.text for t in cs.turns if t.role == "user"]
    recent = "\n".join(user_texts[-6:])
    try:
        out = await get_provider().chat_json(
            [Message("system", _RISK_SYSTEM), Message("user", recent)], _RiskOut
        )
    except LLMError:
        em.log("risk_review_failed", level="WARN", matched=sorted(new_terms))
        return
    if out.risky:
        cs.escalated = True
        em.log(
            "crisis_gate_hit",
            level="WARN",
            hit=True,
            matched=sorted(new_terms),
            to_hotline=True,
            via="risk_review",
        )


async def _softscan(state: GraphState, config: RunnableConfig) -> dict:
    """每轮软预筛+命中复核(spec §4 L5):新增命中才复核;risk_reviewed_terms
    去重——同一软词整会话只复核一次,新表述出现再复核(成本有界)。"""
    cs = state["cs"]
    em = _emitter(config)
    matched = _soft_matched(cs)
    new = matched - cs.risk_reviewed_terms
    if not new:
        return {}
    cs.risk_reviewed_terms |= matched
    await _soft_review(cs, em, new)
    return {}


async def _risk(state: GraphState, config: RunnableConfig) -> dict:
    """终结路径软复核:只补 softscan 未覆盖的新增命中(已复核零 LLM 成本)。"""
    cs = state["cs"]
    em = _emitter(config)
    matched = _soft_matched(cs)
    new = matched - cs.risk_reviewed_terms
    if not new:
        return {}
    cs.risk_reviewed_terms |= matched
    await _soft_review(cs, em, new)
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
    await em.draw(_scene_draw_data(cs, None))  # 精稿(emotion 复核后全量;选材不重发)

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
    graph.add_node("softscan", _softscan)
    graph.add_node("ask", _ask)
    graph.add_node("chat", _chat)
    graph.add_node("risk", _risk)
    graph.add_node("analysis", _analysis)
    graph.add_node("escalate_end", _escalate_end)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "softscan")
    graph.add_conditional_edges(
        "softscan",
        lambda s: where_next(s["cs"]),
        {"ask": "ask", "chat": "chat", "finish": "risk", "escalate": "escalate_end"},
    )
    graph.add_conditional_edges(
        "risk",
        lambda s: "end" if s["cs"].escalated else "proceed",
        {"end": "escalate_end", "proceed": "analysis"},
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
