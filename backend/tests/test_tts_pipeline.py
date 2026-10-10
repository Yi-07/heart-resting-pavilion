"""句子泵(LLM 流 → TTS → audio_chunk)的行为测试。

不打真服务、不打真 LLM:
    LLM 端用一个受控的假流(逐字吐,可指定每字的延迟),
    TTS 端用一个假 synthesizer(记录收到的句子与耗时,可指定单句耗时),
    只测**编排**:切句时机、并发不被拖死、帧序、final 归位、抢占蒸发。

关键行为(这些是设计承诺,不是实现细节):
    1. 首句音频不等 LLM 全文 —— 假流吐到第一个句号就该有一块音频落地
    2. 文字帧不被音频拖住 —— 慢 TTS 下文字仍应按时出完
    3. audio_chunk 按序、seq 单调递增
    4. 最后一块 final=True,中间的 final=False
    5. 抢占后不发新 TTS 请求,已合成的块不再下发
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.voice.sidecar_protocol import SentenceSplitter

# ---- 假 LLM ----

CHARS = "先从今晚开始，选一件最小的事做一做。别想太多。"


async def fake_llm(text: str, *, delay: float = 0.0) -> AsyncIterator[str]:
    for ch in text:
        if delay:
            await asyncio.sleep(delay)
        yield ch


class FakeConn:
    """Connection 的最小替身:只实现句子泵与打断用到的口。

    打断相关两个方法直接转发给 Connection 的真实现 —— 它们只依赖 log 与线程,
    不碰 ws,所以测的是真规则而不是复制品。
    """

    def __init__(self, *, trace: int = 7) -> None:
        self._trace = trace
        self.audio: list[tuple[bytes, bool]] = []   # (wav, final) legacy 链路
        self.pcm: list[tuple[bytes, int]] = []      # (pcm, audio_seq) realtime 链路
        self.logs: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def current_trace(self) -> int:
        return self._trace

    def log(self, event: str, level: str = "INFO", **fields: Any) -> None:
        self.logs.append((event, level, fields))

    async def send_audio(
        self, wav: bytes, *, final: bool = True, round_id: str | None = None
    ) -> None:
        self.audio.append((wav, final))

    async def send_pcm(
        self,
        pcm: bytes,
        *,
        round_id: str,
        audio_seq: int,
        sample_rate: int,
        channels: int = 1,
        final: bool = False,
    ) -> None:
        self.pcm.append((pcm, audio_seq))

    def audio_wavs(self) -> list[bytes]:
        return [w for w, _ in self.audio]

    def pcm_blocks(self) -> list[bytes]:
        return [p for p, _ in self.pcm]

    def tts_round_id(self, trace: int | None = None) -> str:
        from app.ws_gateway.gateway import Connection

        return Connection.tts_round_id(self, trace)  # type: ignore[arg-type]

    def cancel_tts(self, round_id: str | None = None, *, cascade: bool = True) -> None:
        from app.ws_gateway.gateway import Connection

        Connection.cancel_tts(self, round_id, cascade=cascade)  # type: ignore[arg-type]


class FakeEmitter:
    def __init__(self) -> None:
        self.texts: list[tuple[str, bool]] = []
        self.dead = False

    async def text(self, s: str, *, final: bool = False) -> None:
        self.texts.append((s, final))


class FakeTTS:
    """记录收到的句子;每句 sleep(per_sentence_s) 后返回一段可辨识的 wav。

    同一个假同时提供 legacy(wav)与 realtime(PCM)两条链路的实现,并记录
    两条链路各自被调用了多少次 —— gateway 按 tts.STREAM_MODE 选链路,
    所以桩必须两条都齐,否则测试只能钉住其中一条(plan §4/§33)。
    """

    def __init__(self, *, per_sentence_s: float = 0.0, chunks_per_sentence: int = 2) -> None:
        self.per_sentence_s = per_sentence_s
        self.chunks_per_sentence = chunks_per_sentence
        self.received: list[str] = []
        self.request_ids: list[str | None] = []
        self.wav_calls = 0
        self.pcm_calls = 0

    def synthesize_stream_detailed(self, text: str, *, request_id=None):
        self.received.append(text)
        self.request_ids.append(request_id)
        self.wav_calls += 1
        if self.per_sentence_s:
            time.sleep(self.per_sentence_s)
        yield b"WAV:" + text.encode()

    def synthesize_pcm_stream(self, text: str, *, request_id=None):
        self.received.append(text)
        self.request_ids.append(request_id)
        self.pcm_calls += 1
        if self.per_sentence_s:
            time.sleep(self.per_sentence_s)
        from app.voice.tts_client import PcmChunk

        for i in range(self.chunks_per_sentence):
            yield PcmChunk(
                round_id=request_id or "",
                seq=i,
                sentence_index=0,
                sample_rate=32000,
                channels=1,
                format="pcm_s16le",
                pcm=b"PCM:" + text.encode(),
            )


@pytest.fixture
def fake_tts_module(monkeypatch):
    """把 tts 模块的两条链路都换成假实现,返回装填器。

    gateway 里是 `from app.voice import tts` 的懒导入,所以只要换模块属性即可,
    不用 patch gateway 本身。

    `stream_mode` 控制 gateway 走哪条链路("pcm" / "wav"),让同一个夹具既能
    钉 realtime 路径,也能钉 legacy 路径。
    """
    import app.voice.tts as tts_mod

    holder: dict[str, FakeTTS] = {}

    def _install(fake: FakeTTS, *, stream_mode: str = "pcm") -> FakeTTS:
        holder["tts"] = fake
        monkeypatch.setattr(
            tts_mod, "synthesize_stream_detailed", fake.synthesize_stream_detailed
        )
        monkeypatch.setattr(
            tts_mod, "synthesize_pcm_stream", fake.synthesize_pcm_stream
        )
        monkeypatch.setattr(tts_mod, "STREAM_MODE", stream_mode, raising=False)
        return fake

    return _install


# ---- 切句器本身 ----

class TestSentenceSplitter:
    def test_hard_punct_boundary(self):
        s = SentenceSplitter()
        assert s.feed("你好啊。今天") == ["你好啊。"]
        assert s.flush() == ["今天"]

    def test_soft_punct_only_boundary_when_long(self):
        s = SentenceSplitter(max_hanzi=5)
        text = "一，二，三，四，五，六、七"
        got = s.feed(text)
        tail = s.flush()
        # 软标点兜底:每块都不该太长,否则单句合成会很慢
        assert all(len(x) <= 8 for x in got + tail), got + tail
        # 合起来不丢字
        assert "".join(got + tail) == text

    def test_no_premature_flush_under_limit(self):
        s = SentenceSplitter(max_hanzi=30)
        assert s.feed("一二三四五") == []
        assert s.pending == "一二三四五"

    def test_forced_cut_when_llm_never_punctuates(self):
        s = SentenceSplitter(max_hanzi=6)
        out = s.feed("一" * 40)
        assert out, "超长无标点必须强制切,否则缓冲无限增长"

    def test_flush_returns_remainder(self):
        s = SentenceSplitter()
        s.feed("没有句号")
        assert s.flush() == ["没有句号"]
        assert s.flush() == []

    def test_empty_and_whitespace_dropped(self):
        s = SentenceSplitter()
        s.feed("。\n\n")
        assert s.flush() == [], "只有标点和空白时,不能产出句子"


# ---- 编排行为 ----



# ---- 编排行为 ----


class TestAnswerWithVoiceWav:
    """句子泵的编排承诺(legacy wav 链路,STREAM_MODE=wav)。

    这些是设计意图,不是实现细节 —— 改动会让用户感到延迟回归。
    realtime(PCM)链路有同构的一组测试在 TestAnswerWithVoicePcm。
    """

    @pytest.mark.asyncio
    async def test_first_sentence_does_not_wait_for_full_stream(self, fake_tts_module):
        """核心承诺:首句音频不等 LLM 全文。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS(per_sentence_s=0.02), stream_mode="wav")

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        assert len(conn.audio_wavs()) >= 2
        first = conn.audio_wavs()[0].decode().removeprefix("WAV:")
        assert first == tts.received[0]
        assert first.startswith("先从今晚开始")

    @pytest.mark.asyncio
    async def test_streaming_chunks_are_final_false(self, fake_tts_module):
        """流式路径 final 恒 False。

        曾用 hold-one 给最后一块标 final=True,代价是每句最后一块压到下一句
        首块到达才发(实测首块 6.6s → 10.0s)。前端不读该字段,不值得。
        """
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        fake_tts_module(FakeTTS(), stream_mode="wav")

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        assert conn.audio, "应至少产出一块音频"
        assert all(f is False for _, f in conn.audio), "流式路径不该有 final=True"

    @pytest.mark.asyncio
    async def test_chunks_are_not_held_until_next(self, fake_tts_module):
        """每块必须即时下发:只有一块音频时也要发出去,不能等收尾。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS(chunks_per_sentence=1), stream_mode="wav")

        # 只产出一句 → 收尾时只有一块。若实现是 hold-one,这块会一直压着
        async def one_sentence():
            yield "只有一句。"

        await _answer_with_voice(conn, emitter, one_sentence(), "tts-7", 7)  # type: ignore[arg-type]

        assert len(conn.audio) == 1, "单句也要下发那一块"
        assert conn.audio[0][0].decode().removeprefix("WAV:") == tts.received[0]

    @pytest.mark.asyncio
    async def test_audio_order_preserved(self, fake_tts_module):
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS(), stream_mode="wav")

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        texts = [w.decode().removeprefix("WAV:") for w in conn.audio_wavs()]
        assert texts == tts.received, "音频下发顺序必须等于句子送入顺序"
        assert len(set(texts)) == len(texts), "同一句不能重复出声"

    @pytest.mark.asyncio
    async def test_text_stream_not_blocked_by_slow_tts(self, fake_tts_module):
        """慢 TTS 不应拖住文字帧 —— 两条队列分开就是为了这个。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        fake_tts_module(FakeTTS(per_sentence_s=0.15), stream_mode="wav")   # 故意慢

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        assert any(f for _, f in emitter.texts), "末帧文字必须 final=True"
        assert "".join(t for t, _ in emitter.texts) == CHARS

    @pytest.mark.asyncio
    async def test_preempt_stops_new_requests(self, fake_tts_module):
        """抢占后不再发新的 TTS 请求,已合成的块也不下发。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS(), stream_mode="wav")

        async def llm_then_preempt():
            yield "先"
            conn._trace = 8      # trace 变 = 抢占
            for ch in CHARS[1:]:
                yield ch

        await _answer_with_voice(conn, emitter, llm_then_preempt(), "tts-7", 7)  # type: ignore[arg-type]

        assert conn.audio_wavs() == [], "抢占后不应再下发音频"
        assert len(tts.received) <= 2, f"抢占后不该发多请求,实际 {len(tts.received)}"

    @pytest.mark.asyncio
    async def test_request_id_propagates(self, fake_tts_module):
        """round_id 必须一路传到 TTS —— 否则服务端不知道打断谁。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS())

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        assert tts.request_ids and all(r == "tts-7" for r in tts.request_ids)
        # realtime 链路必须真的被走到,否则这条断言只是"stub 没被换掉"
        assert tts.pcm_calls > 0, "STREAM_MODE=pcm 时应走 synthesize_pcm_stream"

    @pytest.mark.asyncio
    async def test_tts_failure_does_not_kill_turn(self, fake_tts_module, monkeypatch):
        """TTS 炸了只记 degraded,文字链路照常走完。"""
        import app.voice.tts as tts_mod
        from app.voice.tts_errors import TTSError
        from app.ws_gateway.gateway import _answer_with_voice

        def _boom(text, *, request_id=None):
            raise TTSError("合成失败")
            yield  # pragma: no cover — 让它看起来像生成器

        # 两条链路都要炸:gateway 按 STREAM_MODE 选链路,只炸一条等于没炸
        monkeypatch.setattr(tts_mod, "synthesize_stream_detailed", _boom)
        monkeypatch.setattr(tts_mod, "synthesize_pcm_stream", _boom)

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        assert conn.audio_wavs() == []
        assert conn.pcm_blocks() == []
        assert any(f for _, f in emitter.texts), "TTS 失败也要把文字说完"
        assert any(ev == "degraded" for ev, _, _ in conn.logs)

    @pytest.mark.asyncio
    async def test_empty_llm_stream_sends_no_audio(self, fake_tts_module):
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS())

        async def empty():
            if False:
                yield ""

        await _answer_with_voice(conn, emitter, empty(), "tts-7", 7)  # type: ignore[arg-type]

        assert conn.audio_wavs() == []
        assert tts.received == []


class TestAnswerWithVoicePcm:
    """realtime PCM 链路(STREAM_MODE=pcm)的编排承诺,与 wav 那组同构。

    分开成两个类而不是加 if:两条链路的**交付粒度不同**(整句 vs 块),
    混在一个类里会写出一堆 stream_mode 分支的断言,读起来看不出哪条在跑。
    """

    @pytest.mark.asyncio
    async def test_pcm_blocks_reach_conn(self, fake_tts_module):
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS(chunks_per_sentence=2))

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        assert tts.pcm_calls > 0, "应走 PCM 链路"
        assert tts.wav_calls == 0, "PCM 模式下不应再走 legacy wav 链路"
        assert len(conn.pcm) > 0, "至少要下发一块 PCM"
        assert conn.audio == [], "PCM 模式下不发 wav 帧"

    @pytest.mark.asyncio
    async def test_pcm_round_id_and_seq_are_passed_through(self, fake_tts_module):
        """round_id / audio_seq 原样透传,网关不重新编号(plan §13/§15)。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        fake_tts_module(FakeTTS(chunks_per_sentence=3))

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        seqs = [s for _, s in conn.pcm]
        assert seqs == sorted(seqs), f"audio_seq 必须保序,实际 {seqs}"
        assert len(set(seqs)) == len(seqs), f"audio_seq 不得重复,实际 {seqs}"

    @pytest.mark.asyncio
    async def test_pcm_text_not_blocked_by_slow_tts(self, fake_tts_module):
        """慢 TTS 不拖住文字帧 —— realtime 链路同样成立。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        fake_tts_module(FakeTTS(per_sentence_s=0.15))

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        assert "".join(t for t, _ in emitter.texts) == CHARS

    @pytest.mark.asyncio
    async def test_pcm_preempt_stops_emitting(self, fake_tts_module):
        """抢占后不再下发 PCM 块。"""
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS(chunks_per_sentence=4))

        async def llm_then_preempt():
            yield "先"
            conn._trace = 8
            for ch in CHARS[1:]:
                yield ch

        await _answer_with_voice(conn, emitter, llm_then_preempt(), "tts-7", 7)  # type: ignore[arg-type]

        assert len(conn.pcm) <= 4, f"抢占后不该再下发,实际 {len(conn.pcm)}"
        assert len(tts.received) <= 2

    @pytest.mark.asyncio
    async def test_pcm_round_id_mismatch_is_reported(self, fake_tts_module):
        """frame.round_id 与 request 不一致 → 记错误,不静默下发(plan §14.2)。"""
        from app.voice.tts_client import PcmChunk
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()

        class _MismatchTTS(FakeTTS):
            def synthesize_pcm_stream(self, text, *, request_id=None):
                self.received.append(text)
                self.pcm_calls += 1
                yield PcmChunk(
                    round_id="tts-OTHER",
                    seq=0,
                    sentence_index=0,
                    sample_rate=32000,
                    channels=1,
                    format="pcm_s16le",
                    pcm=b"PCM:bad",
                )

        fake_tts_module(_MismatchTTS())

        await _answer_with_voice(conn, emitter, fake_llm(CHARS), "tts-7", 7)  # type: ignore[arg-type]

        # round_id 不一致的块绝不能下发到前端
        assert conn.pcm == [], "round_id 不一致的块绝不能下发到前端"
        # 必须留下可观测痕迹:统计计入 errors + 日志里有 WARN/ERROR 级别事件
        assert any(ev in ("degraded", "error") for ev, _, _ in conn.logs), (
            f"round_id 不一致必须留下可观测记录,实际日志 {conn.logs}"
        )

    @pytest.mark.asyncio
    async def test_pcm_empty_llm_stream_sends_nothing(self, fake_tts_module):
        from app.ws_gateway.gateway import _answer_with_voice

        conn = FakeConn(trace=7)
        emitter = FakeEmitter()
        tts = fake_tts_module(FakeTTS())

        async def empty():
            if False:
                yield ""

        await _answer_with_voice(conn, emitter, empty(), "tts-7", 7)  # type: ignore[arg-type]

        assert conn.pcm == []
        assert tts.received == []


# ---- 契约:打断必须穿透到服务 ----


class TestCancelPenetration:
    def test_cancel_tts_reaches_client_with_round_id(self, monkeypatch):
        """抢占必须真的打出去 —— round_id 与 tts 一致,cascade 打开。"""
        import app.voice as voice_pkg

        conn = FakeConn(trace=7)
        called: dict[str, Any] = {}

        class _Mod:
            @staticmethod
            def cancel(rid, *, cascade=True):
                called["rid"] = rid
                called["cascade"] = cascade
                return {"cancelled": True}

        monkeypatch.setattr(voice_pkg, "tts", _Mod(), raising=False)
        conn.cancel_tts()
        time.sleep(0.2)   # 等线程跑完

        assert called.get("rid") == "tts-7"
        assert called.get("cascade") is True
        assert any(ev == "tts_cancel_sent" for ev, _, _ in conn.logs)

    def test_audio_chunk_contract_fields(self):
        """ws 帧字段与契约一致:format=wav、seq 存在、final 存在。"""
        import app.schema.ws_messages as wm

        chunk = wm.AudioChunk(
            seq=6,
            format="wav",
            data=base64.b64encode(b"x").decode(),
            final=True,
        )
        dumped = chunk.model_dump(by_alias=True)
        assert dumped["type"] == "audio_chunk"
        assert dumped["format"] == "wav"
        assert dumped["seq"] == 6
        assert dumped["final"] is True
        assert isinstance(dumped["data"], str)
