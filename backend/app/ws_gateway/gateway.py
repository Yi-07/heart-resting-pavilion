"""WS 网关最小版(backend-plan §8;帧映射=发射侧唯一事实)。

- 连接即建 session_id;user_input / mood_select 入口;JSON 文本帧
- 每条 user_input 先过危机闸门:命中 → 危机序列(first_frame → draw(stage_map)
  → text_delta(热线) → done)+ WARN 审计(§9.4,不含原文)
- 发号:仅 draw/text_delta/audio_chunk/done 盖章(seq 预增,首帧=1);
  first_frame/error 不带不消耗;计数器=连接内存(会话内全局递增)
- 非法消息 → error(invalid_message),不崩连接
- mode=audio:语音链路步骤 8 接入,现回 error(server_error)
- 未命中:分层判定(answer/collect)随步骤 3/4 接入,现回占位安抚 + done
- 抢占/超时兜底/Emitter 注入:随 collect 图与 LLM 长任务接入(步骤 3+)
- 重连:消息带原 session_id 时记忆恢复随步骤 6 接入,现仅留档
"""

import json
from typing import Any, Literal
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import logger as app_logger
from app.router import gate, phrases
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
    else:
        # TODO(步骤3/4):分层判定 → answer(RAG 直答)/ collect(多轮采集)
        conn.log("route_decided", trace_id=trace, route="pending")
        await conn.send_text(phrases.PENDING_ROUTE_REPLY, final=True)
        await conn.send_done()


async def _crisis_sequence(conn: Connection) -> None:
    await conn.send_first_frame(
        route="crisis", text=phrases.CRISIS_SOOTHE, mood_select=False
    )
    await conn.send_draw("stage_map", phrases.CRISIS_STAGE)
    await conn.send_text(phrases.CRISIS_HOTLINE, final=True)
    await conn.send_done()


async def _on_mood_select(conn: Connection, msg: MoodSelect) -> None:
    trace = conn.next_trace()
    conn.log("mood_select_received", trace_id=trace, mood=msg.mood)
    # TODO(步骤6):record_mood 更新 L7 profile;独立到达当前直接短安抚
    await conn.send_text(phrases.MOOD_ACK[msg.mood], final=True)
    await conn.send_done()


__all__ = ["Connection", "handle_connection"]
