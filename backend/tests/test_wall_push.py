"""wall_reply WS 推送钉测(契约 §3.7):worker 落回复后按 session_id 推在线连接。

链路:WS 连接注册(register_connection)→ wall store 落回复 → push_wall_reply
→ 连接收到 wall_reply 帧。worker._handle 直调(同 test_wall_worker),不等 30s 巡检。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.admin.config_store import reset_config_store
from app.main import app
from app.wall import worker
from app.wall.store import WallStore, reset_store

client = TestClient(app)


@pytest.fixture()
def wall_store(tmp_path: Any):
    store = WallStore(str(tmp_path / "wall.db"))
    reset_store(store)
    yield store
    reset_store(None)


@pytest.fixture(autouse=True)
def _no_active_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    from app.admin.config_store import ConfigStore

    reset_config_store(ConfigStore(str(tmp_path / "config.db")))
    monkeypatch.setattr("app.config.ACTIVE_PROVIDER_ID", "")
    yield
    reset_config_store(None)


@pytest.fixture(autouse=True)
def _clean_registry():
    """连接注册表跨测试残留隔离:gateway 前序测试的连接不走正常断连路径。"""

    from app.ws_gateway.gateway import _connections

    _connections.clear()
    yield
    _connections.clear()


def test_wall_reply_pushed_to_online_session(wall_store: WallStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """在线会话:worker 落回复 → 同 session 连接收到 wall_reply 帧。"""

    class _FakeProvider:
        async def chat(self, messages: list[Any]) -> str:
            return "一个小步骤:先喝口水。"

    monkeypatch.setattr(worker, "get_provider", lambda: _FakeProvider())

    with client.websocket_connect("/ws") as ws:
        # 裸连接无回合不发帧(契约:session_id 随 first_frame/done 带回);
        # session_id 从注册表取(连接即注册,handle_connection 侧写)
        from app.ws_gateway.gateway import _connections

        session_id = next(iter(_connections))

        item = wall_store.add(session_id, "今天有点累,但还行")
        import asyncio

        asyncio.run(worker._handle(item))

        pushed = json.loads(ws.receive_text())
        assert pushed["type"] == "wall_reply"
        assert pushed["session_id"] == session_id


def test_wall_reply_offline_session_is_silent(wall_store: WallStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """离线会话:无注册连接 → push 返回 False,不抛(未读态兜底)。"""

    class _FakeProvider:
        async def chat(self, messages: list[Any]) -> str:
            return "一个小步骤。"

    monkeypatch.setattr(worker, "get_provider", lambda: _FakeProvider())
    item = wall_store.add("offline-session-x", "今天有点累")

    import asyncio

    from app.ws_gateway import push_wall_reply

    assert asyncio.run(push_wall_reply("no-such-session")) is False
    asyncio.run(worker._handle(item))  # 不抛即通过
    rows = wall_store.list_messages("offline-session-x")
    assert rows[0]["reply"] == "一个小步骤。"
