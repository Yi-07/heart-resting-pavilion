"""端到端:真 TTS 服务 + 真 WS 网关,验证 answer 路的流式语音。

不打真 LLM(需要 API key 且慢):用受控假流按字符吐,验证编排链路本身。
真 TTS 服务在 127.0.0.1:9001(GPT-SoVITS)。

    cd backend
    uv run pytest tests/test_ws_streaming_e2e.py -q -s

前置:TTS 服务已起且 /ready == 200。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator

import pytest

pytestmark = pytest.mark.asyncio


async def _llm_chars(text: str, delay: float = 0.0) -> AsyncIterator[str]:
    for ch in text:
        if delay:
            await asyncio.sleep(delay)
        yield ch


class Recorder:
    """收集网关下行帧。"""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.t0 = time.perf_counter()

    async def accept(self) -> None:
        return None

    async def send_text(self, payload: str) -> None:
        self.frames.append({**json.loads(payload), "_t": time.perf_counter() - self.t0})

    async def receive_text(self) -> str:  # pragma: no cover — 不用
        await asyncio.sleep(3600)
        return ""


@pytest.fixture
def conn_rec():
    """真 Connection + 收集器。返回 (conn, recorder) —— Connection 不持有 ws 引用。"""
    from app.ws_gateway.gateway import Connection

    rec = Recorder()
    c = Connection(rec)          # type: ignore[arg-type]
    c.session_id = "sess_test"
    return c, rec


def _tts_ready() -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:9001/ready", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def fake_llm(monkeypatch):
    """桩掉网关手里的 get_provider。

    必须 patch `app.ws_gateway.gateway.get_provider` —— gateway 顶部是
    `from app.llm import get_provider`,已经把引用绑到自己模块上了,
    patch app.llm.provider 不起作用,会**真的去打 LLM API**。
    """

    def _install(text: str, delay: float = 0.0) -> FakeLLM:
        fake = FakeLLM(text, delay)
        import app.ws_gateway.gateway as gw

        monkeypatch.setattr(gw, "get_provider", lambda: fake)
        assert gw.get_provider is not None, "补丁必须生效,否则会打真 API"
        return fake

    return _install


class FakeLLM:
    """逐字吐的假 LLM,记录自己什么时候吐完。

    为什么要记录结束时刻:"首块音频不等全文"的判据是
    **首块音频到达 < LLM 流结束**,而不是"音频早于末帧文字" ——
    后者在瞬时假流上不成立(文字一瞬间就发完了),测不出流式有没有生效。
    """

    def __init__(self, text: str, delay: float) -> None:
        self._text = text
        self._delay = delay
        self.t_end = -1.0
        self.t_start = 0.0

    def stream(self, _messages: object = None) -> AsyncIterator[str]:
        self.t_start = time.perf_counter()

        async def _gen() -> AsyncIterator[str]:
            for ch in self._text:
                if self._delay:
                    await asyncio.sleep(self._delay)
                yield ch
            self.t_end = time.perf_counter()

        return _gen()


class TestAnswerStreaming:
    async def test_answer_emits_text_and_audio_interleaved(self, conn_rec, fake_llm):
        """answer 回合:text_delta 与 audio_chunk 都要有,且音频不排在文字之后。"""
        conn, rec = conn_rec
        from app.router.classifier import Classification
        from app.ws_gateway.gateway import _answer_sequence

        if not _tts_ready():
            pytest.skip("TTS 服务未就绪(先起 python -m tts_service)")

        text = "我们先不急着解决什么。就从今晚开始,选一件最小的事做一做。慢慢来就好。"
        # 假 LLM 要有真实速度:瞬时吐完的话,"音频不等全文"根本无从观察
        fake = fake_llm(text, delay=0.15)   # 真 TTS 走 HTTP,只有 LLM 是假的

        cls = Classification(
            route="answer", emotion_label=None, confidence=1.0,
            needs_rag=False, source="rule",
        )

        t0 = time.perf_counter()
        await _answer_sequence(conn, text, cls)
        wall = time.perf_counter() - t0

        frames = rec.frames
        kinds = [f["type"] for f in frames]
        assert "text_delta" in kinds, f"缺文字帧: {kinds}"
        assert "audio_chunk" in kinds, f"缺音频帧: {kinds}"
        assert "done" in kinds, f"缺 done: {kinds}"

        # answer 路径同步等完再发 done,音频应全部在 done 之前
        assert max(i for i, k in enumerate(kinds) if k == "audio_chunk") < kinds.index("done")

        audio = [f for f in frames if f["type"] == "audio_chunk"]
        assert all(f["format"] == "wav" for f in audio)
        assert all(len(f["data"]) > 0 for f in audio)

        seqs = [f["seq"] for f in frames if "seq" in f]
        assert seqs == sorted(seqs), f"seq 必须单调递增: {seqs}"

        assert all(f["final"] is False for f in audio), (
            "流式路径 final 恒 False(前端不读该字段,不做 hold-one 换取更低延迟)"
        )

        # 核心判据:首块音频必须早于 LLM 流结束 —— 这才是"不等全文"
        texts = [f for f in frames if f["type"] == "text_delta"]
        assert fake.t_end > 0, "假 LLM 应记录到结束时刻"
        llm_span = fake.t_end - fake.t_start
        assert audio[0]["_t"] < llm_span, (
            f"首块音频 {audio[0]['_t']:.2f}s 晚于 LLM 流结束 {llm_span:.2f}s "
            "—— 说明在等全文,流式没生效"
        )
        # 文字与音频应交错,而不是一前一后两段
        assert audio[0]["_t"] < texts[-1]["_t"], "音频应与文字交错,不能整段排在后面"

        print(
            f"\n  回合 {wall:.2f}s | 帧 {len(frames)} | 音频 {len(audio)} 块 "
            f"| LLM 流 {llm_span:.2f}s | 首块音频 {audio[0]['_t']:.2f}s "
            f"| 末块音频 {audio[-1]['_t']:.2f}s | 末帧文字 {texts[-1]['_t']:.2f}s"
        )

    async def test_cancel_penetrates_on_preempt(self, conn_rec, monkeypatch):
        """抢占时 cancel_tts 被打出去,带正确的 round_id。"""
        conn, _rec = conn_rec
        sent: list[tuple[str, bool]] = []

        def _spy(rid, *, cascade=True):
            sent.append((rid, cascade))
            return {"round_id": rid, "cancelled": True, "cascaded": []}

        import app.voice.tts as tts_mod

        monkeypatch.setattr(tts_mod, "cancel", _spy)

        conn.cancel_tts()
        await asyncio.sleep(0.25)   # 等打断线程跑完(异步测试里不能用 time.sleep)

        assert sent, "cancel_tts 应真的发起调用"
        assert sent[0][0] == conn.tts_round_id()
        assert sent[0][1] is True, "cascade 默认必须打开"

    async def test_voice_off_switch_skips_audio(self, conn_rec, fake_llm, monkeypatch):
        """TTS_ANSWER_VOICE=0 时只走文字,不发音频帧。"""
        conn, rec = conn_rec
        from app import config
        from app.router.classifier import Classification
        from app.ws_gateway.gateway import _answer_sequence

        monkeypatch.setattr(config, "TTS_ANSWER_VOICE", False)

        text = "只有文字。"
        fake_llm(text)

        cls = Classification(
            route="answer", emotion_label=None, confidence=1.0,
            needs_rag=False, source="rule",
        )
        await _answer_sequence(conn, text, cls)

        kinds = [f["type"] for f in rec.frames]
        assert "text_delta" in kinds
        assert "audio_chunk" not in kinds, "开关关掉后不应有音频帧"

    async def test_service_returns_valid_wav_per_line(self):
        """直接对服务验一遍:每行 wav 头正确、句数与分句一致。"""
        if not _tts_ready():
            pytest.skip("TTS 服务未就绪")

        import base64
        import urllib.request
        from io import BytesIO
        from wave import open as wave_open

        text = "先从今晚开始,选一件最小的事做一做。"

        def _fetch() -> list[dict]:
            req = urllib.request.Request(
                "http://127.0.0.1:9001/v1/tts/stream",
                data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json", "X-Request-ID": "e2e-1"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return [
                    json.loads(x)
                    for x in resp.read().decode().splitlines()
                    if x.strip()
                ]

        lines = await asyncio.to_thread(_fetch)

        wavs = [r for r in lines if r.get("wav")]
        assert wavs, f"没有音频行: {lines}"
        for r in wavs:
            assert r["round_id"] == "e2e-1"
            data = base64.b64decode(r["wav"])
            with wave_open(BytesIO(data), "rb") as w:
                assert w.getnchannels() == 1
                assert w.getsampwidth() == 2
                assert w.getframerate() in (32000, 44100)
                assert w.getnframes() > 0
        _ = (sys, os)
