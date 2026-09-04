"""测试公共桩:网关用假记忆(autouse)——网关测试不依赖真 Redis/SQLite,
真链路由 tests/test_memory.py 直测 Memory(前置=本机 Redis 可用)。"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.state import SessionContext


class FakeMemory:
    """调用记录型替身;snapshot 恒空档(需要历史语境的用例自行改写 history_summary)。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._snapshot = SessionContext()

    def set_snapshot(self, ctx: SessionContext) -> None:
        self._snapshot = ctx

    async def snapshot(self, session_id: str) -> SessionContext:
        self.calls.append(("snapshot", {"session_id": session_id}))
        return SessionContext(
            history_summary=self._snapshot.history_summary,
            mood_recent=list(self._snapshot.mood_recent),
        )

    async def save_round_summary(self, session_id: str, summary: str) -> None:
        self.calls.append(("save_round_summary", {"session_id": session_id, "summary": summary}))

    async def save_station_input(
        self, session_id: str, formulation_json: str, summary: str
    ) -> None:
        self.calls.append(
            (
                "save_station_input",
                {
                    "session_id": session_id,
                    "formulation_json": formulation_json,
                    "summary": summary,
                },
            )
        )

    async def record_mood(
        self,
        mood_label: str,
        *,
        source: str,
        intensity: float | None = None,
        session_id: str | None = None,
    ) -> None:
        self.calls.append(
            (
                "record_mood",
                {
                    "mood_label": mood_label,
                    "source": source,
                    "intensity": intensity,
                    "session_id": session_id,
                },
            )
        )


@pytest.fixture(autouse=True)
def fake_memory(monkeypatch: pytest.MonkeyPatch) -> FakeMemory:
    mem = FakeMemory()
    monkeypatch.setattr("app.ws_gateway.gateway.get_memory", lambda: mem)
    return mem
