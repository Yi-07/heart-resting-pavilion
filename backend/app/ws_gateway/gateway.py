"""WS 网关(backend-plan §8;帧映射=发射侧唯一事实)。

- 连接即建 session_id;user_input / mood_select 入口;JSON 文本帧
- user_input 处理跑独立任务、不阻塞收包:新 user_input 即抢占——取消当前任务
  + 旧 emitter 标 dead(未发帧蒸发)→ 新回合 entry(安抚语承接变体)
- 每条 user_input 先过危机闸门:命中 → 危机序列 + WARN 审计 + 销毁采集态
- 未命中 → 分层判定(规则速判保 first_frame ≤300ms;模糊按 collect 走,
  LLM 仅异步精化 emotion_label,不撤回,spec §4 L4):
  answer → RAG 门控 → LLM 流式直答;collect → first_frame → collect 图
- collect:AskNext/EmpathChat 后保留状态等下一条;Finish → done + 销毁;
  Escalate → 危机序列 + 销毁。回合结束三动作的温层/station 落盘随步骤 6/9 接入
- LLM 失败 → 话术库降级;处理满 LLM_TIMEOUT_S → error(timeout) 兜底
- 发号:仅 draw/text_delta/audio_chunk/done 盖章(seq 预增,首帧=1);
  first_frame/error 不带不消耗;计数器=连接内存(会话内全局递增)
- 非法消息 → error(invalid_message),不崩连接;mode=audio 步骤 8 前显式拒绝
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import config
from app import logger as app_logger
from app.agents import CollectState, ConnEmitter, Escalate, Finish, Turn, stream_final
from app.agents.state import CollectEvent
from app.llm import LLMError, Message, get_provider
from app.router import classifier, gate, phrases
from app.router.classifier import Classification
from app.schema import (
    CSMsg,
    Done,
    Draw,
    ErrorCode,
    ErrorFrame,
    FirstFrame,
    MoodSelect,
    TemplateData,
    TemplateId,
    TextDelta,
    UserInput,
)

if TYPE_CHECKING:
    from app.rag.corpus import Ref

_cs_adapter: TypeAdapter[CSMsg] = TypeAdapter(CSMsg)


def _session_id() -> str:
    return f"sess_{uuid4().hex[:12]}"


def _validation_brief(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(part) for part in err["loc"])
    msg = str(err["msg"]).removeprefix("Value error, ")
    return f"{loc}: {msg}"


class Connection:
    """单连接状态:session_id、seq/trace 计数、当前任务与采集态、盖章发帧。"""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.session_id = _session_id()
        self._seq = 0
        self._trace = -1
        self.current: asyncio.Task[None] | None = None
        self.current_emitter: ConnEmitter | None = None
        self.collect_state: CollectState | None = None

    # ---- 计数 ----

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def next_trace(self) -> int:
        """回合自增 ID(会话内从 0 递增,契约 §9.2)。"""
        self._trace += 1
        return self._trace

    # ---- 日志(标准字段 bind,业务字段随 event) ----

    def log(self, event: str, level: str = "INFO", **fields: Any) -> None:
        app_logger.logger.bind(
            service=app_logger.SERVICE,
            session_id=self.session_id,
            event=event,
            **fields,
        ).log(level, event)

    # ---- 发帧(发射侧唯一路径;by_alias 序列化,stage_map.from 别名正确) ----

    async def _send(self, msg: BaseModel) -> None:
        await self.ws.send_text(msg.model_dump_json(by_alias=True))

    async def send_first_frame(
        self,
        *,
        route: Literal["collect", "crisis"],
        text: str,
        mood_select: bool,
        template: TemplateId | None = None,
        emotion_label: str | None = None,
    ) -> None:
        await self._send(
            FirstFrame(
                session_id=self.session_id,
                route=route,
                template=template,
                emotion_label=emotion_label,
                mood_select=mood_select,
                text=text,
            )
        )
        self.log("first_frame_sent", route=route)

    async def send_draw(self, template: TemplateId, data: TemplateData) -> None:
        await self._send(Draw(seq=self._next_seq(), template=template, data=data))
        self.log("draw_sent", template=template)

    async def send_text(self, text: str, *, final: bool = False) -> None:
        await self._send(TextDelta(seq=self._next_seq(), text=text, final=final))

    async def send_done(self) -> None:
        await self._send(Done(session_id=self.session_id, seq=self._next_seq()))
        self.log("done")

    async def send_error(self, code: ErrorCode, message: str) -> None:
        await self._send(ErrorFrame(code=code, message=message))
        self.log("error", level="ERROR", code=code, detail=message)


# ---- 入口 ----


async def handle_connection(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws)
    conn.log("session_open")
    try:
        while True:
            raw = await ws.receive_text()
            await _on_message(conn, raw)
    except WebSocketDisconnect:
        if conn.current is not None and not conn.current.done():
            conn.current.cancel()
        conn.log("session_close")


async def _on_message(conn: Connection, raw: str) -> None:
    try:
        msg = _cs_adapter.validate_python(json.loads(raw))
    except json.JSONDecodeError:
        await conn.send_error("invalid_message", "非 JSON 文本")
        return
    except ValidationError as exc:
        await conn.send_error("invalid_message", _validation_brief(exc))
        return

    if isinstance(msg, MoodSelect):
        await _on_mood_select(conn, msg)
        return

    # user_input:抢占当前处理(分析中 cancel + 弃 state + 旧 emitter 标 dead
    # → 未发帧蒸发),新任务接管;轮次回答不经过此处销毁(state 仅在处理中被弃)
    preempted = False
    if conn.current is not None and not conn.current.done():
        conn.current.cancel()
        preempted = True
    if conn.current_emitter is not None:
        conn.current_emitter.mark_dead()
        conn.current_emitter = None
    if preempted and conn.collect_state is not None:
        conn.collect_state = None
    conn.current = asyncio.create_task(_process_user_input(conn, msg, carried=preempted))
    # 不 await:立刻回收下一条,保持抢占窗口


async def _on_mood_select(conn: Connection, msg: MoodSelect) -> None:
    trace = conn.next_trace()
    if conn.collect_state is not None:
        # 回合内到达:仅更新 profile,不回帧,采集照常(契约 §4.2)
        conn.log("mood_select_received", trace_id=trace, mood=msg.mood, in_round=True)
        return
    conn.log("mood_select_received", trace_id=trace, mood=msg.mood)
    # TODO(步骤6):record_mood 更新 L7 profile;独立到达当前直接短安抚
    await conn.send_text(phrases.MOOD_ACK[msg.mood], final=True)
    await conn.send_done()


async def _process_user_input(conn: Connection, msg: UserInput, *, carried: bool) -> None:
    trace = conn.next_trace()
    if msg.session_id and msg.session_id != conn.session_id:
        conn.log("reconnect_claim", trace_id=trace, id_len=len(msg.session_id))
    conn.log(
        "user_input_received",
        trace_id=trace,
        mode=msg.mode,
        fingerprint=app_logger.text_fingerprint(msg.text or msg.audio or ""),
    )

    if msg.mode == "audio":
        # 语音链路步骤 8 接入;当前显式拒绝,避免静默丢字
        await conn.send_error("server_error", "语音链路未接入(步骤 8)")
        return

    text = msg.text or ""
    result = gate.check(text)
    conn.log(
        "crisis_gate_hit",
        level="WARN" if result.hit else "INFO",
        trace_id=trace,
        hit=result.hit,
        severity=result.severity,
        matched=result.matched,
        to_hotline=result.hit,
    )
    if result.hit:
        conn.collect_state = None
        conn.log("route_decided", trace_id=trace, route="crisis")
        await _crisis_sequence(conn)
        return

    try:
        cls = classifier.classify_rules(text)
        if cls.route == "answer":
            if conn.collect_state is not None:
                # 等待期抢占:输入判 answer → 弃采集态,直接直答(§8 抢占)
                conn.log("preempted", trace_id=trace, reason="answer_route")
                conn.collect_state = None
            conn.log(
                "route_decided",
                trace_id=trace,
                route="answer",
                source=cls.source,
                needs_rag=cls.needs_rag,
            )
            await asyncio.wait_for(
                _answer_sequence(conn, text, cls), timeout=config.LLM_TIMEOUT_S
            )
        else:
            conn.log(
                "route_decided",
                trace_id=trace,
                route="collect",
                source=cls.source,
                confidence=cls.confidence,
                in_round=conn.collect_state is not None,
            )
            await asyncio.wait_for(
                _collect_sequence(conn, trace, text, cls, carried=carried),
                timeout=config.LLM_TIMEOUT_S,
            )
    except asyncio.TimeoutError:
        conn.collect_state = None
        conn.log("degraded", level="WARN", trace_id=trace, reason="timeout")
        await conn.send_error("timeout", "这次回应太慢了,先给你一句兜底")
        await conn.send_text(phrases.ANSWER_FALLBACK, final=True)
        await conn.send_done()
    except Exception as exc:  # noqa: BLE001 — 网关收口:任何异常 error 帧 + 不崩连接
        conn.collect_state = None
        conn.log(
            "error", level="ERROR", trace_id=trace, code="server_error", detail=str(exc)[:160]
        )
        await conn.send_error("server_error", "我这边卡了一下,先陪你坐一会儿")
        await conn.send_done()


async def _crisis_sequence(conn: Connection) -> None:
    await conn.send_first_frame(
        route="crisis", text=phrases.CRISIS_SOOTHE, mood_select=False
    )
    await conn.send_draw("stage_map", phrases.CRISIS_STAGE)
    await conn.send_text(phrases.CRISIS_HOTLINE, final=True)
    await conn.send_done()


# ---- collect(每条 user_input=一次短图调用,backend-plan §3) ----


async def _collect_sequence(
    conn: Connection, trace: int, text: str, cls: Classification, *, carried: bool
) -> None:
    state = conn.collect_state
    if state is None:
        # entry:first_frame(≤300ms 语义,规则速判)+ 建态;承接变体=抢占后重开
        state = CollectState(
            session_id=conn.session_id,
            route="collect",
            template="beck_formulation",
            emotion_label=cls.emotion_label,
            confidence=cls.confidence,
            max_rounds=config.COLLECT_MAX_ROUNDS,
        )
        conn.collect_state = state
        await conn.send_first_frame(
            route="collect",
            template="beck_formulation",
            emotion_label=cls.emotion_label,
            mood_select=True,
            text=phrases.collect_soothe(cls.emotion_label, carried=carried),
        )
        conn.log("collection_start", trace_id=trace, carried=carried)
    # 轮次回答:同回合继续,无 first_frame(契约 §6.2)
    state.turns.append(Turn(role="user", text=text))

    emitter = ConnEmitter(conn, "beck_formulation")
    conn.current_emitter = emitter
    try:
        from app.agents import run_collect  # 懒加载:LangGraph 只进 collect 路径

        event = await run_collect(state, emitter)
    finally:
        if conn.current_emitter is emitter:
            conn.current_emitter = None
    await _settle_collect_event(conn, trace, event)


async def _settle_collect_event(
    conn: Connection, trace: int, event: CollectEvent
) -> None:
    if isinstance(event, Finish):
        # 回合结束三动作:温层摘要+station:input 随步骤 6/9 接入;销毁状态
        conn.collect_state = None
        await conn.send_done()
    elif isinstance(event, Escalate):
        conn.collect_state = None
        conn.log("route_decided", trace_id=trace, route="crisis", via="escalate")
        await _crisis_sequence(conn)
    # AskNext / EmpathChat:保留状态等待下一条输入(帧已由图内 emitter 发出)


# ---- answer 直答(契约 §6.1:user_input → text_delta ×N → done,无黑板) ----


def _answer_messages(query: str, refs: list[Ref]) -> list[Message]:
    if refs:
        context = "\n\n".join(f"【{r.question}】\n{r.answer}" for r in refs)
        system = (
            "你是心栖阁的心理知识科普助手。优先依据下面的资料回答,科普口吻、简洁"
            f"(150 字内);资料没有的内容不编造;不做医疗诊断。参考资料:\n{context}"
        )
    else:
        system = (
            "你是心栖阁的陪伴助手。温暖、简洁地回应(80 字内),不做医疗诊断,"
            "不连续追问。"
        )
    return [Message("system", system), Message("user", query)]


async def _answer_sequence(conn: Connection, text: str, cls: Classification) -> None:
    refs: list[Ref] = []
    if cls.needs_rag:
        try:
            from app.rag import get_engine  # 懒加载:chroma/模型首次 answer 才进内存

            refs = get_engine().retrieve(text, k=config.RAG_TOP_K)
            conn.log("rag_retrieved", refs=[r.id for r in refs])
        except Exception as exc:  # noqa: BLE001 — RAG 任意失败都降级直答,不杀回合
            conn.log("degraded", level="WARN", reason="rag_failed", detail=str(exc)[:120])
            refs = []

    emitter = ConnEmitter(conn, "beck_formulation")  # answer 不画黑板,draw 不触达
    conn.current_emitter = emitter
    try:
        sent = False
        try:
            sent = await stream_final(emitter, get_provider().stream(_answer_messages(text, refs)))
        except LLMError as exc:
            conn.log("degraded", level="WARN", reason="llm_error", detail=str(exc)[:120])
        if not sent:
            conn.log("degraded", level="WARN", reason="empty_stream")
            await emitter.text(phrases.ANSWER_FALLBACK, final=True)
    finally:
        if conn.current_emitter is emitter:
            conn.current_emitter = None
    await conn.send_done()


__all__ = ["Connection", "handle_connection"]
