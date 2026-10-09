"""Emitter 协议(backend-plan §8):图内发帧的唯一通道,config 传递不进 state。

三方法:draw(formulation) · text(s) · audio(chunk);ConnEmitter 包 Connection,
dead 标记后发帧蒸发(抢占时旧 emitter 标 dead,未发帧丢弃)。
audio 为同步门面(协议如此),内部调度异步发帧,图节点无需 await。
攒批工具(≥30 字/100ms 窗)单源在此,answer/collect 两路共用。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Protocol

from app.schema import Formulation, TemplateId

if TYPE_CHECKING:
    from app.ws_gateway.gateway import Connection

BATCH_CHARS = 30
BATCH_WINDOW_S = 0.1


class Emitter(Protocol):
    async def draw(self, formulation: Formulation) -> None: ...

    async def text(self, s: str, *, final: bool = False) -> None: ...

    def audio(self, chunk: bytes) -> None: ...


async def batched_chunks(
    chunks: AsyncIterator[str],
    *,
    min_chars: int = BATCH_CHARS,
    window_s: float = BATCH_WINDOW_S,
) -> AsyncIterator[str]:
    """攒批:≥min_chars 字或距上次出批 ≥window_s 秒出一批(尾批收尾)。"""
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


async def stream_final(emitter: Emitter, chunks: AsyncIterator[str]) -> bool:
    """流式出帧,hold-one 保证末帧 final=True;返回是否发出过帧(空流由调用方兜底)。"""
    pending: str | None = None
    async for batch in batched_chunks(chunks):
        if pending is not None:
            await emitter.text(pending)
        pending = batch
    if pending is not None:
        await emitter.text(pending, final=True)
        return True
    return False


class ConnEmitter:
    """Connection 适配 + dead 蒸发;log 透传网关标准事件日志。

    template 支持 callable:collect 板式接力时图内改 CollectState.template,
    emitter 每次 draw 现取——构造期快照会错过中途切换。
    """

    def __init__(self, conn: Connection, template: TemplateId | Callable[[], TemplateId]) -> None:
        self._conn = conn
        self._template = template
        self.dead = False
        self._audio_task: asyncio.Task[None] | None = None

    def mark_dead(self) -> None:
        self.dead = True

    def log(self, event: str, level: str = "INFO", **fields: object) -> None:
        if not self.dead:
            self._conn.log(event, level=level, **fields)

    def _current_template(self) -> TemplateId:
        return self._template() if callable(self._template) else self._template

    async def draw(self, formulation: Formulation) -> None:
        if self.dead:
            return
        await self._conn.send_draw(self._current_template(), formulation)

    async def text(self, s: str, *, final: bool = False) -> None:
        if self.dead:
            return
        await self._conn.send_text(s, final=final)

    def audio(self, chunk: bytes) -> None:
        """TTS 直发(wav 字节):同步门面,内部调度异步发帧;dead 或空块蒸发。
        持 task 引用(D3):防 GC 吞异常;发送前复检 dead,抢占后旧帧不落新回合。"""
        if self.dead or not chunk:
            return
        self._audio_task = asyncio.create_task(self._send_audio(chunk))

    async def _send_audio(self, chunk: bytes) -> None:
        if self.dead:
            return
        try:
            await self._conn.send_audio(chunk)
        except Exception:  # noqa: BLE001 — 音频缺席无副作用(WS 断开等)
            self.log("degraded", level="WARN", reason="audio_send_failed")
