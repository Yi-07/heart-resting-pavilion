"""WS 网关(backend-plan §8;帧映射=发射侧唯一事实)。

- 连接即建 session_id;user_input / mood_select 入口;JSON 文本帧
- 每条 user_input 先过危机闸门:命中 → 危机序列(first_frame → draw(stage_map)
  → text_delta(热线) → done)+ WARN 审计(§9.4,不含原文)
- 未命中 → 分层判定:answer → RAG(门控)→ LLM 流式直答(攒批 text_delta);
  collect → 步骤 4 接图,现占位安抚;answer 无 first_frame/draw(契约 §6.1)
- LLM 失败 → 话术库降级;处理满 LLM_TIMEOUT_S → error(timeout) 兜底
- 发号:仅 draw/text_delta/audio_chunk/done 盖章(seq 预增,首帧=1);
  first_frame/error 不带不消耗;计数器=连接内存(会话内全局递增)
- 非法消息 → error(invalid_message),不崩连接
- mode=audio:语音链路步骤 8 接入,现回 error(server_error)
- 抢占/Emitter 注入:随 collect 图接入(步骤 4)
- 重连:消息带原 session_id 时记忆恢复随步骤 6 接入,现仅留档
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import config
from app import logger as app_logger
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
    """单连接状态:session_id、seq/trace 计数、S→C 帧统一盖章即发。"""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.session_id = _session_id()
        self._seq = 0
        self._trace = -1

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
            await _dispatch(conn, raw)
    except WebSocketDisconnect:
        conn.log("session_close")


async def _dispatch(conn: Connection, raw: str) -> None:
    try:
        msg = _cs_adapter.validate_python(json.loads(raw))
    except json.JSONDecodeError:
        await conn.send_error("invalid_message", "非 JSON 文本")
        return
    except ValidationError as exc:
        await conn.send_error("invalid_message", _validation_brief(exc))
        return

    if isinstance(msg, UserInput):
        await _on_user_input(conn, msg)
    elif isinstance(msg, MoodSelect):
        await _on_mood_select(conn, msg)


async def _on_user_input(conn: Connection, msg: UserInput) -> None:
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

    result = gate.check(msg.text or "")
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
        conn.log("route_decided", trace_id=trace, route="crisis")
        await _crisis_sequence(conn)
        return

    cls = await classifier.classify(msg.text or "")
    conn.log(
        "route_decided",
        trace_id=trace,
        route=cls.route,
        source=cls.source,
        confidence=cls.confidence,
        needs_rag=cls.needs_rag,
    )
    if cls.route == "answer":
        await _answer_sequence(conn, trace, msg.text or "", cls)
    else:
        # TODO(步骤4):collect 图(first_frame→粗稿→轮次→精稿);现占位安抚
        await conn.send_text(phrases.PENDING_COLLECT_REPLY, final=True)
        await conn.send_done()


async def _crisis_sequence(conn: Connection) -> None:
    await conn.send_first_frame(
        route="crisis", text=phrases.CRISIS_SOOTHE, mood_select=False
    )
    await conn.send_draw("stage_map", phrases.CRISIS_STAGE)
    await conn.send_text(phrases.CRISIS_HOTLINE, final=True)
    await conn.send_done()


# ---- answer 直答(契约 §6.1:user_input → text_delta ×N → done,无黑板) ----

_BATCH_CHARS = 30
_BATCH_WINDOW_S = 0.1


async def _batched_chunks(
    chunks: AsyncIterator[str],
    *,
    min_chars: int = _BATCH_CHARS,
    window_s: float = _BATCH_WINDOW_S,
) -> AsyncIterator[str]:
    """攒批(backend-plan §8):≥30 字或距上次 ≥100ms 出一批。"""
    buf = ""
    last_flush = time.monotonic()
    async for chunk in chunks:
        buf += chunk
        now = time.monotonic()
        if len(buf) >= min_chars or (buf and now - last_flush >= window_s):
            yield buf
            buf = ""
            last_flush = now
    if buf:
        yield buf


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


async def _answer_sequence(
    conn: Connection, trace: int, text: str, cls: Classification
) -> None:
    refs: list[Ref] = []
    if cls.needs_rag:
        try:
            from app.rag import get_engine  # 懒加载:chroma/模型首次 answer 才进内存

            refs = get_engine().retrieve(text, k=config.RAG_TOP_K)
            conn.log("rag_retrieved", trace_id=trace, refs=[r.id for r in refs])
        except Exception as exc:  # noqa: BLE001 — RAG 任意失败都降级直答,不杀回合
            conn.log("degraded", level="WARN", reason="rag_failed", detail=str(exc)[:120])
            refs = []

    async def stream_out() -> None:
        pending: str | None = None
        async for batch in _batched_chunks(get_provider().stream(_answer_messages(text, refs))):
            if pending is not None:
                await conn.send_text(pending)
            pending = batch
        if pending is not None:
            await conn.send_text(pending, final=True)
        else:  # 空流 → 降级话术,不让回合无输出收场
            conn.log("degraded", level="WARN", reason="empty_stream")
            await conn.send_text(phrases.ANSWER_FALLBACK, final=True)

    try:
        await asyncio.wait_for(stream_out(), timeout=config.LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        conn.log("degraded", level="WARN", reason="timeout")
        await conn.send_error("timeout", "这次回应太慢了,先给你一句兜底")
        await conn.send_text(phrases.ANSWER_FALLBACK, final=True)
    except LLMError as exc:
        conn.log("degraded", level="WARN", reason="llm_error", detail=str(exc)[:120])
        await conn.send_text(phrases.ANSWER_FALLBACK, final=True)
    await conn.send_done()


async def _on_mood_select(conn: Connection, msg: MoodSelect) -> None:
    trace = conn.next_trace()
    conn.log("mood_select_received", trace_id=trace, mood=msg.mood)
    # TODO(步骤6):record_mood 更新 L7 profile;独立到达当前直接短安抚
    await conn.send_text(phrases.MOOD_ACK[msg.mood], final=True)
    await conn.send_done()


__all__ = ["Connection", "handle_connection"]
