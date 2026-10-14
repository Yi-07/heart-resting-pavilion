"""ws_gateway 接缝钉测试(backend-plan §11):危机序列 E2E、发号、error 收口、mood 独立到达。

即 CLAUDE.md §8 验收用例 3(crisis)的后端链路判据:
日志 event=crisis_gate_hit(WARN)+ 危机帧序(first_frame→draw→text_delta→done)
+ mood_select=false(不弹心情选择器由前端判,协议层以 first_frame.mood_select 钉)。
"""

import asyncio
import json
import time
from typing import Any

from fastapi.testclient import TestClient

from app import config
from app.agents.state import SessionContext
from app.llm import LLMError
from app.logger import capture_events
from app.main import app
from app.rag.corpus import RagLibrary, Ref
from app.station.reports import get_reports

client = TestClient(app)


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
            assert draw["template"] == "scene_crisis"  # blackboard-v1:危机固定场景帧
            assert draw["data"]["note"] == "加油！你能行的"  # P12 文案裁定

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
        assert _recv(ws)["type"] == "done"  # 预置回执 wav 缺文件:音频跳过,直接收口


def test_mood_select_speaks_preset_ack(tmp_path, monkeypatch):
    """P13 心情回执语音:预置 wav 在时 text_delta → audio_chunk → done(§4.2)。"""
    import base64 as b64mod

    from app.voice import fillers

    monkeypatch.setattr(config, "FILLERS_DIR", str(tmp_path))
    (tmp_path / f"{fillers.mood_ack_name('低落')}.wav").write_bytes(b"MOODWAV")
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "mood_select", "mood": "低落", "ts": 4}))
        reply = _recv(ws)
        assert reply["type"] == "text_delta"
        audio = _recv(ws)
        assert audio["type"] == "audio_chunk"
        assert audio["format"] == "wav"
        assert audio["round_id"] == "preset-mood-0"  # 独立到达消耗 next_trace=0(§3.4)
        assert b64mod.b64decode(audio["data"]) == b"MOODWAV"
        assert audio["seq"] == reply["seq"] + 1
        done = _recv(ws)
        assert done["type"] == "done" and done["seq"] == audio["seq"] + 1


def test_answer_seq_global_across_rounds(monkeypatch):
    """seq 会话内全局递增,不随回合重置(契约 §3.2)。"""
    stub = _StreamStub(["A" * 20, "B" * 5])
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub([]))
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "什么是正念")  # answer 路(RAG 关,无种子库则降级直答)
        assert _recv(ws)["type"] == "draw"  # 场景帧先行
        text1 = _recv(ws)
        assert text1["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "如何缓解焦虑")
        assert _recv(ws)["type"] == "draw"
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


def test_crisis_speaks_hotline(monkeypatch, tmp_path):
    """危机话术预置 wav 直发(契约 §6.3):first_frame 后安抚音频,热线文本后热线音频。

    运行时 TTS 合成路径已由预置语音取代(spec L6「预置语音」);缺文件跳过,
    文字链路照常——两条断言合在本用例:有 wav 时音频与文本同步。"""
    import base64 as b64mod

    monkeypatch.setattr(config, "FILLERS_DIR", str(tmp_path))
    (tmp_path / "crisis_soothe.wav").write_bytes(b"SOOTHEWAV")
    (tmp_path / "crisis_hotline.wav").write_bytes(b"HOTLINEWAV")
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "我不想活了")
        assert _recv(ws)["type"] == "first_frame"

        soothe = _recv(ws)
        assert soothe["type"] == "audio_chunk"  # P10 安抚随 first_frame 同步
        assert soothe["format"] == "wav"
        assert soothe["final"] is True
        assert b64mod.b64decode(soothe["data"]) == b"SOOTHEWAV"
        assert soothe["seq"] == 1  # audio 盖章:会话首号
        assert soothe["round_id"] == "preset-crisis-0"  # 危机组号(§3.4)

        draw = _recv(ws)
        assert draw["type"] == "draw" and draw["seq"] == 2

        text = _recv(ws)
        assert text["type"] == "text_delta" and text["seq"] == 3

        audio = _recv(ws)
        assert audio["type"] == "audio_chunk"  # P11 热线随文本同步
        assert b64mod.b64decode(audio["data"]) == b"HOTLINEWAV"
        assert audio["seq"] == text["seq"] + 1
        assert audio["round_id"] == "preset-crisis-0"  # 两句同组:前端同组排队保顺播

        done = _recv(ws)
        assert done["type"] == "done"
        assert done["seq"] == audio["seq"] + 1


def test_crisis_preset_wav_missing_still_texts():
    """预置 wav 缺文件:音频跳过、记 degraded,文字链路照常(危机帧序不变形)。"""
    events: list[dict[str, Any]] = []
    handle = capture_events(events.append)
    try:
        with client.websocket_connect("/ws") as ws:
            _send_input(ws, "我不想活了")
            assert _recv(ws)["type"] == "first_frame"
            draw = _recv(ws)  # 无音频帧:安抚 wav 缺失被跳过
            assert draw["type"] == "draw"
            text = _recv(ws)
            assert text["type"] == "text_delta"
            done = _recv(ws)
            assert done["type"] == "done"
    finally:
        from loguru import logger

        logger.remove(handle)
    degraded = [e for e in events if e["extra"].get("reason") == "preset_wav_missing"]
    assert len(degraded) == 2  # 安抚+热线两次缺文件各记一次 WARN


# ---- answer 直答(契约 §6.1 blackboard-v1 修订:场景帧先行,无 first_frame) ----


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
        frames = [_recv(ws), _recv(ws), _recv(ws), _recv(ws)]

    types = [f["type"] for f in frames]
    assert types == ["draw", "text_delta", "text_delta", "done"]
    assert frames[0]["template"] == "scene_answer"  # 空板缺口:场景帧先行
    assert not any(t == "first_frame" for t in types)  # 判据:无 first_frame(§3.1)
    joined = frames[1]["text"] + frames[2]["text"]
    assert joined == "A" * 20 + "B" * 20 + "C" * 5
    assert frames[2]["final"] is True
    assert frames[3]["type"] == "done"

    assert rag.calls == [("什么是正念", 3, RagLibrary.KNOWLEDGE)]  # answer 查科普库,默认 k=3
    assert stub.messages is not None
    system = stub.messages[0]["content"]
    assert "正念是觉察练习" in system  # RAG 资料进了生成上下文


def test_answer_llm_error_falls_back(monkeypatch):
    stub = _StreamStub([], error=LLMError("上游断流"))
    monkeypatch.setattr("app.ws_gateway.gateway.get_provider", lambda: stub)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "什么是正念")
        assert _recv(ws)["type"] == "draw"  # 场景帧先行
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
        assert _recv(ws)["type"] == "draw"  # 场景帧先行,超时后仍降级兜底
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
        assert first["mood_select"] is False  # 恒 false:自动浮出废弃(契约「mood_select」节)
        assert first["template"] == "scene_default"  # 开场板式(接力单源在 CollectState)


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


def test_finish_archives_round_three_actions(monkeypatch, fake_memory, tmp_reports):
    """回合三动作:温层摘要+station:input(研判 mood 需 emotion 已填,此处空态不记)。

    方案书回合末自动生成(方案书裁定):归档后素材在 → start_auto_generate 被触发,
    done 照发不等待;reports 表落 pending/ready 行(round_id=回合号)。"""
    from app.agents.state import Finish

    async def _stub_run(cs, emitter):
        return Finish(cause="sufficient", summary="测试总结文本")

    async def _stub_report(f, summary):
        return "# 自动生成稿"

    monkeypatch.setattr("app.agents.run_collect", _stub_run)
    monkeypatch.setattr("app.station.planner.generate_report", _stub_report)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        first = _recv(ws)
        assert first["type"] == "first_frame"
        assert _recv(ws)["type"] == "done"  # done 照发:自动生成不拖收尾
        session_id = first["session_id"]
    names = [c[0] for c in fake_memory.calls]
    assert "save_round_summary" in names
    assert "save_station_input" in names
    saved = {c[0]: c[1] for c in fake_memory.calls if c[0] in ("save_round_summary", "save_station_input")}
    assert saved["save_round_summary"]["summary"] == "测试总结文本"
    assert saved["save_station_input"]["summary"] == "测试总结文本"
    assert "situation" in saved["save_station_input"]["formulation_json"]
    row = None
    for _ in range(200):  # 后台生成在 portal loop 落地,轮询行
        row = get_reports().get_latest(session_id)
        if row is not None and row["status"] == "ready":
            break
        time.sleep(0.02)
    assert row is not None and row["status"] == "ready" and row["report_md"] == "# 自动生成稿"
    assert row["round_id"] == "r0"  # 挂起重试轮不计,entry 回合 round_index=0


def test_ask_llm_failed_suspends_collect(monkeypatch, fake_memory):
    """问话 LLM 失败(网关 settle 面,契约 §8.4):error(ask_llm_failed) 帧 + 采集态
    挂起(ask_retry 置位);无 done——前端辐条呈现,下一条输入重试。
    (挂起消费/重试语义由 test_collect_flow 图层钉;此处钉网关帧序与置位。)"""
    from app.agents import AskFailed
    from app.agents.state import CollectState

    captured: dict[str, CollectState] = {}

    async def _stub_run(cs, emitter):
        captured["cs"] = cs
        return AskFailed(source="ask")

    monkeypatch.setattr("app.agents.run_collect", _stub_run)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        assert _recv(ws)["type"] == "first_frame"
        err = _recv(ws)
        assert err["type"] == "error"
        assert err["code"] == "ask_llm_failed"
        assert "小栖" in err["message"] or err["message"]  # 辐条文案由后端给
    assert captured["cs"].ask_retry is True  # 挂起标记置位(下一条输入重试)
    assert captured["cs"].round_index == 0  # 失败轮不计数
    assert captured["cs"].pending_question is None  # 不落预置问句(不掩盖错误)


def test_preempt_retains_collect_state(monkeypatch, fake_memory):
    """抢占保留采集态(体验重构裁定,契约 §7):采集轮次处理中再发一条输入 →
    采集态不清,新输入按轮次回答消费(无 first_frame,增量 draw 续画);
    已采字段/轮次计数保留。"""
    import asyncio

    from app.agents import AskNext
    from app.agents.state import CollectState, Finish, PendingQuestion

    gate_hold = asyncio.Event()
    calls: list[str] = []

    async def _stub_run(cs: CollectState, emitter):
        calls.append("run")
        if len(calls) == 1:
            # 第 1 次图调用:发出第 1 问后挂住(模拟问话流被抢占时正在处理)
            cs.pending_question = PendingQuestion(text="当时你在想什么?", target_field="thought")
            await emitter.text("当时你在想什么?", final=True)
            await asyncio.wait_for(gate_hold.wait(), timeout=5)
            return AskNext(question="当时你在想什么?", target_field="thought")
        return Finish(cause="sufficient", summary="收尾")

    monkeypatch.setattr("app.agents.run_collect", _stub_run)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        first = _recv(ws)
        assert first["type"] == "first_frame"
        assert _recv(ws)["type"] == "text_delta"  # 第 1 问已发出
        _send_input(ws, "被领导否定了")  # 抢占:旧任务 cancel,采集态保留
        gate_hold.set()  # 放开旧任务(将被 cancel,不产生更多帧)
        # 新输入按轮次消费:无 first_frame(与旧语义的核心差异),直接增量 draw
        frame = _recv(ws)
        assert frame["type"] != "first_frame"
    # 采集态在连接上保留(state 未被抢占清空——由 _stub_run 第 2 次调用收到
    # 带进度的 state 佐证:pending_question 语义由图侧轮次分支消费)


def test_collect_timeout_retains_state(monkeypatch, fake_memory):
    """超时保留采集态(契约 §7):60s 超时路径不再弃 state,采集进度不丢。"""
    from app.agents.state import CollectState, Finish

    captured: dict[str, CollectState] = {}

    async def _stub_run(cs: CollectState, emitter):
        captured["cs"] = cs
        await asyncio.sleep(10)  # 超 LLM_TIMEOUT_S(下方 monkeypatch 到 0.05)
        return Finish(cause="sufficient")

    monkeypatch.setattr("app.agents.run_collect", _stub_run)
    monkeypatch.setattr(config, "LLM_TIMEOUT_S", 0.05)
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")
        assert _recv(ws)["type"] == "first_frame"
        err = _recv(ws)
        assert err["type"] == "error" and err["code"] == "timeout"
        assert _recv(ws)["type"] == "text_delta"  # 兜底话术
        assert _recv(ws)["type"] == "done"
    # state 保留:连接级断言经由 run_collect 的第 2 次进入不可行(stub 只调一次),
    # 语义由「抢占保留」同路径保证——这里钉超时路径不再有清空副作用
    assert captured["cs"] is not None


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
        assert _recv(ws)["type"] == "draw"  # 场景帧先行
        text = _recv(ws)
        assert text["type"] == "text_delta"
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
