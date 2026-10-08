"""ws_gateway 接缝钉测试(backend-plan §11):危机序列 E2E、发号、error 收口、mood 独立到达。

即 CLAUDE.md §8 验收用例 3(crisis)的后端链路判据:
日志 event=crisis_gate_hit(WARN)+ 危机帧序(first_frame→draw→text_delta→done)
+ mood_select=false(不弹心情选择器由前端判,协议层以 first_frame.mood_select 钉)。
"""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.agents.state import SessionContext
from app.llm import LLMError
from app.logger import capture_events
from app.main import app
from app.rag.corpus import RagLibrary, Ref

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_answer_voice(monkeypatch):
    """本文件的用例测的是帧序/黑板/seq/危机,不是语音。

    两件事都要钉死,否则测试结果取决于"这台机器上 TTS 服务开没开":
      1. 关掉 answer 语音 —— 它并发跑 TTS,给事件循环加负载;
         batched_chunks 的攒批窗口是 100ms 墙钟,负载一变批次切分就变,
         而这些用例断言精确帧数,会变成时序脆弱的测试。
      2. TTS 桩成"不产出任何音频" —— 危机路径本来就会调 TTS,
         真服务在跑时会多出 audio_chunk 帧,把帧序断言打乱。

    语音链路本身由 tests/test_ws_streaming_e2e.py 覆盖(真服务 + 真 HTTP),
    需要音频帧的用例自己覆写这个桩(见 test_crisis_speaks_hotline)。
    """
    monkeypatch.setattr(config, "TTS_ANSWER_VOICE", False)
    monkeypatch.setattr(
        "app.voice.tts.synthesize_stream",
        lambda text, **kw: iter(()),
    )


def _silent_stream(text: str, **kw: Any) -> Iterator[bytes]:
    return iter((b"WAVSTUB",))


def _recv(ws: Any) -> dict:
    return json.loads(ws.receive_text())


def _send_input(ws: Any, text: str) -> None:
    ws.send_text(json.dumps({"type": "user_input", "text": text, "ts": 1}))


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
        ws.send_text(json.dumps({"type": "user_input", "text": None, "ts": 3}))
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


# ---- 语音转写预览(ADR-004;/asr/transcribe REST,真 ASR 见 tests/test_voice.py) ----


def test_asr_transcribe_rest_ok_and_audited(monkeypatch):
    """转写成功:200+text;日志 asr_transcribed 只记长度+指纹(脱敏,不含原文)。"""
    monkeypatch.setattr("app.voice.asr.transcribe", lambda audio: "最近很焦虑睡不着")
    events: list[dict[str, Any]] = []
    handle = capture_events(events.append)
    try:
        res = client.post("/asr/transcribe", json={"audio": "ZmFrZS13ZWJt"})  # b"fake-webm"
    finally:
        from loguru import logger

        logger.remove(handle)
    assert res.status_code == 200
    assert res.json() == {"text": "最近很焦虑睡不着"}
    hits = [e for e in events if e["extra"].get("event") == "asr_transcribed"]  # record.extra 即字段
    assert len(hits) == 1
    assert hits[0]["extra"]["length"] == len("最近很焦虑睡不着")
    assert "最近很焦虑睡不着" not in json.dumps(events, default=str)  # 原文不落日志


def test_asr_transcribe_rest_empty_ok(monkeypatch):
    """空转写(="没听到")→ 200+空串+asr_empty,不算错误。"""
    monkeypatch.setattr("app.voice.asr.transcribe", lambda audio: "")
    res = client.post("/asr/transcribe", json={"audio": "eg=="})
    assert res.status_code == 200
    assert res.json() == {"text": ""}


def test_asr_transcribe_rest_unavailable(monkeypatch):
    """转写不可用(模型未加载/异常)→ 503,前端引导转打字。"""
    from app.voice.asr import ASRError

    def _boom(audio: bytes) -> str:
        raise ASRError("model not loaded")

    monkeypatch.setattr("app.voice.asr.transcribe", _boom)
    res = client.post("/asr/transcribe", json={"audio": "eg=="})
    assert res.status_code == 503


def test_asr_transcribe_rest_bad_base64():
    res = client.post("/asr/transcribe", json={"audio": "not-base64!!!"})
    assert res.status_code == 422


def test_asr_transcribe_rest_oversize(monkeypatch):
    monkeypatch.setattr("app.voice.routes._MAX_AUDIO_BYTES", 8)  # 护栏分支,不必造 1MB 载荷
    res = client.post("/asr/transcribe", json={"audio": "ZmFrZS13ZWJtLW92ZXItbGltaXQ="})
    assert res.status_code == 413


def test_legacy_audio_input_rejected():
    """旧 mode=audio 形状(ADR-004 前)→ invalid_message:输入单源文本,音频不进 WS。"""
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "user_input",
                    "mode": "audio",
                    "text": None,
                    "audio": "ZmFrZS13ZWJt",
                    "ts": 5,
                }
            )
        )
        reply = _recv(ws)
        assert reply["type"] == "error"
        assert reply["code"] == "invalid_message"


def test_crisis_speaks_hotline(monkeypatch):
    """危机热线 TTS:text → audio_chunk(wav·final·seq 递增)→ done。"""
    import base64 as b64mod

    monkeypatch.setattr(
        # 收 request_id:_speak_stream 现在会带上回合 id(为了能穿透打断到服务)
        "app.voice.tts.synthesize_stream",
        lambda text, **kw: iter((b"WAVDATA",)),
    )
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
        self.calls: list[tuple[str, int | None, RagLibrary | None]] = []

    def retrieve(
        self, query: str, k: int | None = None, *, library: RagLibrary | None = None
    ) -> list[Any]:
        self.calls.append((query, k, library))
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

    assert rag.calls == [("什么是正念", 3, RagLibrary.KNOWLEDGE)]  # answer 查科普库,默认 k=3
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
                    "text": "什么是正念",
                    "ts": 6,
                }
            )
        )
        assert _recv(ws)["type"] == "text_delta"
        done = _recv(ws)
        assert done["type"] == "done"
        assert done["session_id"] == "sess_previous_round"


# ---- 重连回放(ADR-005):认领后 replay 帧 + assistant 轮次入热层 ----


def test_reconnect_pushes_replay_bubbles(fake_memory, monkeypatch):
    """带原 session_id 认领 + 热层 recent_turns 在 → 先推 replay(bubbles) 再走回合。"""
    from app.agents.state import Turn

    fake_memory.set_snapshot(
        SessionContext(
            history_summary="上次聊了失眠",
            recent_turns=[Turn(role="user", text="最近睡不着"), Turn(role="assistant", text="在想什么?")],
        )
    )
    stub = _StreamStub(["好" * 20])
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub([]))
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps({"type": "user_input", "session_id": "sess_old", "text": "晚上又睡不着", "ts": 7})
        )
        rp = _recv(ws)
        assert rp["type"] == "replay"  # 先于 first_frame/text_delta
        assert rp["mode"] == "bubbles"
        assert [t["role"] for t in rp["turns"]] == ["user", "assistant"]
        assert rp["turns"][0]["text"] == "最近睡不着"
        assert rp["summary"] == "上次聊了失眠"
        assert rp["session_id"] == "sess_old"
        assert "seq" not in rp  # 不带号不消耗(同 first_frame 语义)
        nxt = _recv(ws)
        assert nxt["type"] in ("first_frame", "text_delta")  # 回放后本回合正常走


def test_reconnect_pushes_replay_digest_when_hot_expired(fake_memory, monkeypatch):
    """热层无 turns(30min 过)但温层摘要在 → replay(digest),无 turns 字段内容。"""
    fake_memory.set_snapshot(SessionContext(history_summary="前天梳理过考试焦虑"))
    stub = _StreamStub(["好" * 20])
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub([]))
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps({"type": "user_input", "session_id": "sess_old2", "text": "最近还好", "ts": 8})
        )
        rp = _recv(ws)
        assert rp["type"] == "replay"
        assert rp["mode"] == "digest"
        assert rp["turns"] == []
        assert rp["summary"] == "前天梳理过考试焦虑"


def test_new_connection_no_replay(fake_memory, monkeypatch):
    """新连接(不带 id)不推 replay(全新会话语义;§3.6)。"""
    stub = _StreamStub(["好" * 20])
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub([]))
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "user_input", "text": "什么是正念", "ts": 9}))
        first = _recv(ws)
        assert first["type"] != "replay"


def test_assistant_turns_logged_for_replay(fake_memory, monkeypatch):
    """ADR-005:用户输入与 assistant 问句 → append_turn 落账。

    collect 首轮(单条输入)无 done 帧——回合开放等下一轮;首问 text_delta
    (图内发出)到达即退,settle 的 append_turn 在事件落定时执行、晚于帧,
    退帧后小睡等落账(纯内存桩 0.5s 足够)。
    """
    import time

    stub = _StreamStub(["好" * 20])
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub([]))
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "user_input", "text": "最近很焦虑睡不着", "ts": 10}))
        while True:
            frame = _recv(ws)
            if frame.get("type") == "text_delta":
                break
        time.sleep(0.5)
    calls = fake_memory.calls
    roles = [c[1]["role"] for c in calls if c[0] == "append_turn"]
    user_texts = [
        c[1]["text"] for c in calls if c[0] == "append_turn" and c[1]["role"] == "user"
    ]
    assert "user" in roles
    assert "最近很焦虑睡不着" in user_texts
    assert "assistant" in roles  # AskNext 首问入轮次(回放含小栖一侧)
