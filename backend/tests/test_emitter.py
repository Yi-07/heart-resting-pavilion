"""Emitter 接缝钉测试(backend-plan §11):dead 标记后发帧蒸发;攒批/hold-one。"""

from collections.abc import AsyncIterator

from app.agents.emitter import ConnEmitter, batched_chunks, stream_final
from app.schema import Formulation


class _FakeConn:
    def __init__(self) -> None:
        self.frames: list[tuple[str, str, bool]] = []  # (kind, text, final)
        self.logs: list[str] = []

    def log(self, event: str, level: str = "INFO", **fields: object) -> None:
        self.logs.append(event)

    async def send_text(self, text: str, *, final: bool = False) -> None:
        self.frames.append(("text", text, final))

    async def send_draw(self, template: str, data: Formulation) -> None:
        self.frames.append(("draw", template, False))


async def _chunks(*parts: str, delay: float = 0.0) -> AsyncIterator[str]:
    import asyncio

    for p in parts:
        if delay:
            await asyncio.sleep(delay)
        yield p


async def test_dead_emitter_evaporates_frames():
    conn = _FakeConn()
    em = ConnEmitter(conn, "beck_formulation")  # type: ignore[arg-type]
    em.mark_dead()
    await em.text("蒸发")
    await em.draw(Formulation())
    em.audio(b"x")
    assert conn.frames == []  # 未发帧全部蒸发
    em.log("some_event")
    assert conn.logs == []


async def test_live_emitter_passes_through():
    conn = _FakeConn()
    em = ConnEmitter(conn, "beck_formulation")  # type: ignore[arg-type]
    await em.text("可见", final=True)
    await em.draw(Formulation())
    assert conn.frames == [("text", "可见", True), ("draw", "beck_formulation", False)]


async def test_stream_final_marks_last_batch():
    conn = _FakeConn()
    em = ConnEmitter(conn, "beck_formulation")  # type: ignore[arg-type]
    sent = await stream_final(em, _chunks("A" * 20, "B" * 20, "C" * 5))
    assert sent is True
    texts = [f for f in conn.frames if f[0] == "text"]
    assert "".join(t[1] for t in texts) == "A" * 20 + "B" * 20 + "C" * 5
    assert texts[-1][2] is True  # 末帧 final
    assert all(t[2] is False for t in texts[:-1])


async def test_stream_final_empty_stream_returns_false():
    conn = _FakeConn()
    em = ConnEmitter(conn, "beck_formulation")  # type: ignore[arg-type]
    assert await stream_final(em, _chunks()) is False
    assert conn.frames == []


async def test_batched_chunks_char_cap():
    batches = [b async for b in batched_chunks(_chunks("A" * 20, "B" * 20, "C"))]
    assert batches == ["A" * 20 + "B" * 20, "C"]  # ≥30 字出批


async def test_batched_chunks_time_window():
    batches = [b async for b in batched_chunks(_chunks("短", "短", delay=0.15))]
    assert len(batches) >= 2  # 100ms 窗口到期也出批
