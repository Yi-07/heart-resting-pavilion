"""ws_gateway 接缝钉测试(backend-plan §11):危机序列 E2E、发号、error 收口、mood 独立到达。

即 CLAUDE.md §8 验收用例 3(crisis)的后端链路判据:
日志 event=crisis_gate_hit(WARN)+ 危机帧序(first_frame→draw→text_delta→done)
+ mood_select=false(不弹心情选择器由前端判,协议层以 first_frame.mood_select 钉)。
"""

import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient

from app import config
from app.llm import LLMError
from app.logger import capture_events
from app.main import app
from app.rag.corpus import Ref

client = TestClient(app)


def _recv(ws: Any) -> dict:
    return json.loads(ws.receive_text())


def _send_input(ws: Any, text: str) -> None:
    ws.send_text(json.dumps({"type": "user_input", "mode": "text", "text": text, "ts": 1}))


def test_crisis_sequence_and_audit():
    events: list[dict[str, Any]] = []
    handle = capture_events(events.append)
    try:
        with client.websocket_connect("/ws") as ws:
            _send_input(ws, "我不想活了")

            first = _recv(ws)
            assert first["type"] == "first_frame"
            assert first["route"] == "crisis"
            assert first["mood_select"] is False  # 不弹心情选择器
            assert first["template"] is None
            assert "seq" not in first  # first_frame 不带号不消耗
            session_id = first["session_id"]
            assert "12356" in first["text"] or first["text"]  # 郑重安抚文案存在

            draw = _recv(ws)
            assert draw["type"] == "draw"
            assert draw["seq"] == 1  # 首帧=1
            assert draw["template"] == "stage_map"
            assert draw["data"]["nodes"] == ["现在", "拨打热线", "专业支持"]
            assert draw["data"]["from"] == "你不是一个人"  # by_alias 序列化
            assert "from_" not in draw["data"]

            text = _recv(ws)
            assert text["type"] == "text_delta"
            assert text["seq"] == 2
            assert text["final"] is True
            assert "12356" in text["text"]  # 热线引导

            done = _recv(ws)
            assert done["type"] == "done"
            assert done["seq"] == 3
            assert done["session_id"] == session_id  # 随 done 带回(§1)
    finally:
        from loguru import logger

        logger.remove(handle)

    audits = [e for e in events if e["extra"].get("event") == "crisis_gate_hit"]
    assert any(
        e["level"].name == "WARN"
        and e["extra"].get("hit") is True
        and "不想活" in e["extra"]["matched"]
        and e["extra"].get("to_hotline") is True
        for e in audits
    ), "危机审计未落 WARN"


def test_invalid_json_error_then_connection_alive():
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not-json")
        err = _recv(ws)
        assert err["type"] == "error"
        assert err["code"] == "invalid_message"
        assert "seq" not in err  # error 不带号

        # 连接未崩:合法消息照常处理
        ws.send_text(json.dumps({"type": "mood_select", "mood": "平静", "ts": 2}))
        reply = _recv(ws)
        assert reply["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"


def test_invalid_user_input_payload():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "user_input", "mode": "text", "text": None, "ts": 3}))
        err = _recv(ws)
        assert err["code"] == "invalid_message"
        assert "text" in err["message"]


def test_mood_select_independent_no_first_frame():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "mood_select", "mood": "低落", "ts": 4}))
        reply = _recv(ws)
        assert reply["type"] == "text_delta"  # 短安抚,不发 first_frame(§4.2)
        assert _recv(ws)["type"] == "done"


def test_answer_seq_global_across_rounds(monkeypatch):
    """seq 会话内全局递增,不随回合重置(契约 §3.2)。"""
    stub = _StreamStub(["A" * 20, "B" * 5])
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub([]))
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "什么是正念")  # answer 路(RAG 关,无种子库则降级直答)
        text1 = _recv(ws)
        assert text1["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "如何缓解焦虑")
        text2 = _recv(ws)
        assert text2["seq"] > text1["seq"]
        _recv(ws)


# ---- 语音链路(步骤8;真 ASR/TTS 见 tests/test_voice.py,此处钉网关接线) ----


def test_audio_mode_transcribed_same_stream(monkeypatch):
    """mode=audio:转写文本走同 text 流(用例4 链路判据;音频即弃)。"""
    monkeypatch.setattr("app.voice.asr.transcribe", lambda audio: "最近很焦虑睡不着")
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "user_input",
                    "mode": "audio",
                    "text": None,
                    "audio": "ZmFrZS13ZWJt",  # b"fake-webm"
                    "ts": 5,
                }
            )
        )
        first = _recv(ws)
        assert first["type"] == "first_frame"
        assert first["route"] == "collect"
        assert first["mood_select"] is True


def test_audio_mode_empty_transcript_degrades(monkeypatch):
    monkeypatch.setattr("app.voice.asr.transcribe", lambda audio: "")
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps(
                {"type": "user_input", "mode": "audio", "text": None, "audio": "eg==", "ts": 6}
            )
        )
        reply = _recv(ws)
        assert reply["type"] == "text_delta"  # 温和降级,不发 first_frame
        assert _recv(ws)["type"] == "done"


def test_crisis_speaks_hotline(monkeypatch):
    """危机热线 TTS:text → audio_chunk(wav·final·seq 递增)→ done。"""
    import base64 as b64mod

    monkeypatch.setattr("app.voice.tts.synthesize", lambda text: b"WAVDATA")
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "我不想活了")
        assert _recv(ws)["type"] == "first_frame"
        assert _recv(ws)["type"] == "draw"
        text = _recv(ws)
        assert text["type"] == "text_delta"

        audio = _recv(ws)
        assert audio["type"] == "audio_chunk"
        assert audio["format"] == "wav"
        assert audio["final"] is True
        assert b64mod.b64decode(audio["data"]) == b"WAVDATA"
        assert audio["seq"] == text["seq"] + 1

        done = _recv(ws)
        assert done["type"] == "done"
        assert done["seq"] == audio["seq"] + 1


# ---- answer 直答(契约 §6.1;CLAUDE.md §8 用例 1 判据:无 first_frame、无 draw) ----


class _StreamStub:
    """get_provider 替身:stream 可编程,记录收到的 messages"""

    def __init__(self, chunks: list[str], error: Exception | None = None, delay: float = 0.0):
        self.chunks = chunks
        self.error = error
        self.delay = delay
        self.messages: list[dict[str, str]] | None = None

    async def stream(self, messages):
        self.messages = [{"role": m.role, "content": m.content} for m in messages]
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk


class _RagStub:
    def __init__(self, refs: list[Any]) -> None:
        self.refs = refs
        self.calls: list[tuple[str, int | None]] = []

    def retrieve(self, query: str, k: int | None = None) -> list[Any]:
        self.calls.append((query, k))
        return self.refs


def test_answer_streams_without_blackboard(monkeypatch):
    stub = _StreamStub(["A" * 20, "B" * 20, "C" * 5])
    rag = _RagStub(
        [Ref(id="mindfulness-01", question="什么是正念?", answer="正念是觉察练习")]
    )
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: rag)

    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "什么是正念")
        frames = [_recv(ws), _recv(ws), _recv(ws)]

    types = [f["type"] for f in frames]
    assert types == ["text_delta", "text_delta", "done"]
    assert not any(t in ("first_frame", "draw") for t in types)  # 判据:无黑板
    joined = frames[0]["text"] + frames[1]["text"]
    assert joined == "A" * 20 + "B" * 20 + "C" * 5
    assert frames[1]["final"] is True
    assert frames[2]["type"] == "done"

    assert rag.calls == [("什么是正念", 3)]  # RAG 门控开,默认 k=3
    assert stub.messages is not None
    system = stub.messages[0]["content"]
    assert "正念是觉察练习" in system  # RAG 资料进了生成上下文


def test_answer_llm_error_falls_back(monkeypatch):
    stub = _StreamStub([], error=LLMError("上游断流"))
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "什么是正念")
        text = _recv(ws)
        assert text["type"] == "text_delta"
        assert text["final"] is True
        assert _recv(ws)["type"] == "done"


def test_answer_timeout_bails_out(monkeypatch):
    monkeypatch.setattr(config, "LLM_TIMEOUT_S", 0.1)
    stub = _StreamStub(["很慢" * 30, "依然很慢"], delay=0.3)
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "什么是正念")
        err = _recv(ws)
        assert err == {**err, "type": "error", "code": "timeout"}
        text = _recv(ws)
        assert text["type"] == "text_delta"  # 降级话术兜底
        assert _recv(ws)["type"] == "done"


def test_collect_placeholder_route(monkeypatch):
    """collect 全链路 E2E 见 tests/test_collect_flow.py;此处钉网关侧帧序基线。"""
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        first = _recv(ws)
        assert first["type"] == "first_frame"
        assert first["route"] == "collect"
        assert first["mood_select"] is True
        assert first["template"] == "beck_formulation"


# ---- 记忆接线(步骤6;memory 真链路见 tests/test_memory.py) ----


def test_mood_select_recorded_to_cold_layer(fake_memory):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "mood_select", "mood": "低落", "ts": 4}))
        assert _recv(ws)["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"
    calls = [c for c in fake_memory.calls if c[0] == "record_mood"]
    assert len(calls) == 1
    assert calls[0][1]["mood_label"] == "低落"
    assert calls[0][1]["source"] == "mood_select"


def test_finish_archives_round_three_actions(monkeypatch, fake_memory):
    """回合三动作:温层摘要+station:input(研判 mood 需 emotion 已填,此处空态不记)。"""
    from app.agents.state import Finish

    async def _stub_run(cs, emitter):
        return Finish(cause="sufficient", summary="测试总结文本")

    monkeypatch.setattr("app.agents.run_collect", _stub_run)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        assert _recv(ws)["type"] == "first_frame"
        assert _recv(ws)["type"] == "done"
    names = [c[0] for c in fake_memory.calls]
    assert "save_round_summary" in names
    assert "save_station_input" in names
    saved = {c[0]: c[1] for c in fake_memory.calls if c[0] in ("save_round_summary", "save_station_input")}
    assert saved["save_round_summary"]["summary"] == "测试总结文本"
    assert saved["save_station_input"]["summary"] == "测试总结文本"
    assert "situation" in saved["save_station_input"]["formulation_json"]


def test_reconnect_adopts_session_id(monkeypatch):
    """契约 §8.4:带原 session_id 的 user_input → 后端认领(done 帧带回原 id)。"""
    stub = _StreamStub(["好" * 20])
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub([]))
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "user_input",
                    "session_id": "sess_previous_round",
                    "mode": "text",
                    "text": "什么是正念",
                    "ts": 6,
                }
            )
        )
        assert _recv(ws)["type"] == "text_delta"
        done = _recv(ws)
        assert done["type"] == "done"
        assert done["session_id"] == "sess_previous_round"
