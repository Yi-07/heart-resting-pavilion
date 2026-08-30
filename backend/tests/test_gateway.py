"""ws_gateway 接缝钉测试(backend-plan §11):危机序列 E2E、发号、error 收口、mood 独立到达。

即 CLAUDE.md §8 验收用例 3(crisis)的后端链路判据:
日志 event=crisis_gate_hit(WARN)+ 危机帧序(first_frame→draw→text_delta→done)
+ mood_select=false(不弹心情选择器由前端判,协议层以 first_frame.mood_select 钉)。
"""

import json
from typing import Any

from fastapi.testclient import TestClient

from app.logger import capture_events
from app.main import app

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


def test_pending_route_placeholder_and_seq_global():
    with client.websocket_connect("/ws") as ws:
        _send_input(ws, "最近很焦虑睡不着")  # 未命中 → 占位回复(步骤3/4 前)
        text1 = _recv(ws)
        assert text1["type"] == "text_delta"
        assert _recv(ws)["type"] == "done"

        _send_input(ws, "今天天气怎么样")
        text2 = _recv(ws)
        assert text2["seq"] > text1["seq"]  # seq 会话内全局递增,不随回合重置
        _recv(ws)


def test_audio_mode_rejected_until_step8():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps({"type": "user_input", "mode": "audio", "audio": "aGk=", "ts": 5})
        )
        err = _recv(ws)
        assert err["type"] == "error"
        assert err["code"] == "server_error"
