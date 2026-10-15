"""wall worker 钉测试:危机命中必落审计 WARN(红线,同网关 crisis_gate_hit 字段口径)
+ 危机回复接 phrases.py 单源 + 普通留言走 LLM 回复。worker._handle 直调,LLM 注入替身。"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

import pytest

from app.admin.config_store import ConfigStore, reset_config_store
from app.logger import capture_events
from app.router import phrases
from app.wall import worker
from app.wall.store import WallStore, get_store, reset_store


@pytest.fixture()
def wall_store(tmp_path: Any):
    store = WallStore(str(tmp_path / "wall.db"))
    reset_store(store)
    yield store
    reset_store(None)


@pytest.fixture(autouse=True)
def _no_llm_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """worker LLM 走激活配置解析;测试指到空库+无激活,替身从 get_provider 注入。"""

    store = ConfigStore(str(tmp_path / "config.db"))
    reset_config_store(store)
    monkeypatch.setattr("app.config.ACTIVE_PROVIDER_ID", "")
    yield
    reset_config_store(None)


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    async def chat(self, messages: list[Any]) -> str:
        self.calls.append(messages)
        return "一个小步骤:先喝口水。"


def test_crisis_hit_audits_warn_and_replies_hotline(wall_store: WallStore) -> None:
    """红线:危机命中必落审计 WARN(matched/severity/to_hotline,不含原文)+话术单源。"""

    events: list[dict[str, Any]] = []
    handle = capture_events(events.append)
    try:
        item = wall_store.add("s" * 8, "我不想活了")
        fake = _FakeProvider()
        original = worker.get_provider
        worker.get_provider = lambda: fake  # type: ignore[method-assign]
        try:
            asyncio.run(worker._handle(item))
        finally:
            worker.get_provider = original  # type: ignore[method-assign]
    finally:
        from loguru import logger

        logger.remove(handle)

    audits = [e for e in events if e["extra"].get("event") == "wall_crisis_hit"]
    assert any(
        e["level"].name == "WARN"
        and e["extra"].get("hit") is True
        and "不想活" in e["extra"]["matched"]
        and e["extra"].get("to_hotline") is True
        for e in audits
    ), "wall 危机审计未落 WARN"

    rows = wall_store.list_messages("s" * 8)
    assert len(rows) == 1 and rows[0]["reply"] is not None
    # 话术接 phrases 单源(不是 worker 内硬编码)
    assert phrases.CRISIS_SOOTHE in rows[0]["reply"]
    assert phrases.CRISIS_HOTLINE in rows[0]["reply"]
    # 危机路径不进 LLM
    assert fake.calls == []
    # 审计不含留言原文
    assert all("我不想活了" not in str(e["extra"]) for e in audits)


def test_normal_message_goes_to_llm(wall_store: WallStore) -> None:
    item = wall_store.add("t" * 8, "今天有点累,但还行")
    fake = _FakeProvider()
    original = worker.get_provider
    worker.get_provider = lambda: fake  # type: ignore[method-assign]
    try:
        asyncio.run(worker._handle(item))
    finally:
        worker.get_provider = original  # type: ignore[method-assign]

    rows = wall_store.list_messages("t" * 8)
    assert rows[0]["reply"] == "一个小步骤:先喝口水。"
    assert len(fake.calls) == 1
    assert "今天有点累" in fake.calls[0][0].content


def test_worker_cleans_expired_messages(wall_store: WallStore) -> None:
    """七日生命周期:过期留言由 cleanup 清除(直接验 store 层)。"""

    item = wall_store.add("u" * 8, "旧留言")
    with sqlite3.connect(wall_store._db_path) as conn:
        conn.execute(
            "UPDATE wall_messages SET created_at = datetime('now', '-8 days') WHERE id = ?",
            (item["id"],),
        )
    removed = wall_store.cleanup()
    assert removed == 1
    assert wall_store.list_messages("u" * 8) == []
    assert get_store() is wall_store
