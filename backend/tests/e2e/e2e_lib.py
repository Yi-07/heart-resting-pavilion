"""E2E 回归·公共库:WS 客户端 + 帧时间线打印 + 音频时长解析。

所有 e2e_*.py 复用;帧到达时刻统一相对脚本启动的 t0(monotonic)。
跑法:本机在跑 `uv run hrp`(lifespan 自动拉 sidecar+RAG 预热),然后
`uv run python tests/e2e/e2e2_a_gate_concept.py`(Windows 直接 python,
不经 pytest;ping_interval=None 防长任务下 20s keepalive 误断)。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import time
import wave
from collections.abc import Callable
from typing import Any

import websockets
from typing_extensions import Self
from websockets.asyncio.client import ClientConnection

URI = "ws://127.0.0.1:8000/ws"
T0 = time.monotonic()


def now() -> float:
    return time.monotonic() - T0


def stamp() -> str:
    return f"+{now():7.3f}s"


def wav_seconds(b64: str) -> float:
    """base64 wav → 秒(RIFF 头解析);解析失败返 0。"""
    try:
        with wave.open(io.BytesIO(base64.b64decode(b64))) as w:
            return w.getnframes() / w.getframerate()
    except Exception:  # noqa: BLE001 — 打印摘要用,非音频帧解析失败返 0 即可
        return 0.0


def describe(msg: dict[str, Any]) -> str:
    """单帧一行摘要(不打印 base64 正文)。"""
    t = msg.get("type")
    if t == "audio_chunk":
        sec = wav_seconds(msg.get("data", ""))
        return (f"audio_chunk seq={msg.get('seq')} final={msg.get('final')} "
                f"fmt={msg.get('format')} dur={sec:.2f}s b64len={len(msg.get('data', ''))}")
    if t == "text_delta":
        text = (msg.get("text") or "").replace("\n", "\\n")
        return f"text_delta seq={msg.get('seq')} final={msg.get('final')} text={text[:60]!r}"
    if t == "draw":
        data = msg.get("data") or {}
        filled = [k for k, v in data.items() if v not in (None, "", [], {})]
        return f"draw seq={msg.get('seq')} tpl={msg.get('template')} filled={filled}"
    if t == "first_frame":
        return (f"first_frame route={msg.get('route')} tpl={msg.get('template')} "
                f"mood={msg.get('mood_select')} emotion={msg.get('emotion_label')!r} "
                f"text={(msg.get('text') or '')[:30]!r}")
    if t == "done":
        return f"done session={msg.get('session_id')} seq={msg.get('seq')}"
    if t == "error":
        return f"error code={msg.get('code')} msg={msg.get('message')!r}"
    return json.dumps(msg, ensure_ascii=False)[:120]


class WsClient:
    """后台收帧入队;wait_for 断言 + drain_idle 静默收尾。"""

    def __init__(self) -> None:
        self.ws: ClientConnection | None = None
        self.frames: list[tuple[float, dict[str, Any]]] = []
        self.queue: asyncio.Queue[tuple[float, dict[str, Any]]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        self.ws = await websockets.connect(URI, max_size=32 * 2**20, ping_interval=None)
        self._task = asyncio.create_task(self._recv_loop())
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._task:
            self._task.cancel()
        if self.ws:
            await self.ws.close()

    async def _recv_loop(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                t = now()
                self.frames.append((t, msg))
                print(f"  {stamp()}  <- {describe(msg)}", flush=True)
                await self.queue.put((t, msg))
        except Exception:  # noqa: BLE001, S110 — 连接关闭/对端断开即收帧结束,静默退出收帧循环
            pass

    async def send(self, msg: dict[str, Any]) -> float:
        assert self.ws is not None
        t = now()
        print(f"  {stamp()}  -> {json.dumps(msg, ensure_ascii=False)[:90]}", flush=True)
        await self.ws.send(json.dumps(msg, ensure_ascii=False))
        return t

    async def wait_for(
        self,
        pred: Callable[[dict[str, Any]], bool],
        timeout: float,
        label: str = "",
    ) -> tuple[float, dict[str, Any]] | None:
        """从队列取帧直到 pred 命中或超时;命中帧已记入 self.frames。"""
        deadline = now() + timeout
        while True:
            remain = deadline - now()
            if remain <= 0:
                print(f"  !! wait_for 超时: {label}", flush=True)
                return None
            try:
                _, msg = await asyncio.wait_for(self.queue.get(), timeout=remain)
            except asyncio.TimeoutError:
                print(f"  !! wait_for 超时: {label}", flush=True)
                return None
            if pred(msg):
                return (now(), msg)

    def frames_since(self, t: float, typ: str | None = None) -> list[tuple[float, dict[str, Any]]]:
        return [(ft, m) for ft, m in self.frames if ft >= t and (typ is None or m.get("type") == typ)]

    async def drain_idle(self, idle_s: float = 10.0, hard_cap: float = 120.0) -> None:
        """持续收帧直到 idle_s 秒无新帧(或 hard_cap 兜底)。"""
        now()
        cap = now() + hard_cap
        while now() < cap:
            try:
                await asyncio.wait_for(self.queue.get(), timeout=idle_s)
                now()
            except asyncio.TimeoutError:
                break
        print(f"  {stamp()}  ~~ 静默 {idle_s}s,收帧结束(共 {len(self.frames)} 帧)", flush=True)


def user_text(text: str, session_id: str | None = None) -> dict[str, Any]:
    return {"type": "user_input", "text": text, "ts": int(time.time() * 1000),
            **({"session_id": session_id} if session_id else {})}


def result(name: str, ok: bool, detail: str) -> None:
    print(f"\n[{name}] {'PASS' if ok else 'FAIL'} — {detail}", flush=True)
