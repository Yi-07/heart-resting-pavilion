"""测试公共桩:网关用假记忆(autouse)——网关测试不依赖真 Redis/SQLite,
真链路由 tests/test_memory.py 直测 Memory(前置=本机 Redis 可用)。"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.state import SessionContext
from app.station.reports import StationReports, reset_reports


class FakeMemory:
    """调用记录型替身;snapshot 恒空档(需要历史语境的用例自行改写 history_summary)。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._snapshot = SessionContext()
        self.station_input: dict[str, Any] | None = None  # load_station_input 返回口
        self.moods: list[dict[str, Any]] = []  # recent_moods 返回口

    async def ping(self) -> bool:
        return True

    def set_snapshot(self, ctx: SessionContext) -> None:
        self._snapshot = ctx

    async def snapshot(self, session_id: str) -> SessionContext:
        self.calls.append(("snapshot", {"session_id": session_id}))
        return SessionContext(
            history_summary=self._snapshot.history_summary,
            mood_recent=list(self._snapshot.mood_recent),
            recent_turns=list(self._snapshot.recent_turns),
        )

    async def append_turn(self, session_id: str, role: str, text: str) -> None:
        self.calls.append(
            ("append_turn", {"session_id": session_id, "role": role, "text": text})
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

    async def load_station_input(self, session_id: str) -> dict[str, Any] | None:
        self.calls.append(("load_station_input", {"session_id": session_id}))
        return self.station_input

    def recent_moods(self, days: int = 7) -> list[dict[str, Any]]:
        self.calls.append(("recent_moods", {"days": days}))
        return [dict(m) for m in self.moods]

    async def clear_all(self) -> dict[str, int]:
        self.calls.append(("clear_all", {}))
        return {"redis_keys": 2, "mood_rows": 3}

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
    monkeypatch.setattr("app.station.routes.get_memory", lambda: mem)
    monkeypatch.setattr("app.admin.routes.get_memory", lambda: mem)
    monkeypatch.setattr("app.main.get_memory", lambda: mem)
    # 语音默认静音:TTS 流式合成不出块(跳过音频帧)、fillers 取不到——防测试
    # 拉起真 sidecar 或多出 audio_chunk 破坏既有帧序断言;语音用例自行覆盖
    monkeypatch.setattr("app.voice.tts.synthesize_stream", lambda text: iter(()))
    monkeypatch.setattr("app.voice.fillers.pick", lambda: None)
    # sidecar 进程编排不进测试:TestClient 触发 lifespan 时不得真拉 sidecar,
    # 也不得留下 _stopping=True 污染同进程的后续语音用例;语音用例自行还原
    # remote 模式下 ensure_sidecar/shutdown_spawned 不存在,跳过
    from app.voice import tts as _tts_mod

    if hasattr(_tts_mod, "ensure_sidecar"):
        monkeypatch.setattr("app.voice.tts.ensure_sidecar", lambda timeout_s=None: False)
    if hasattr(_tts_mod, "shutdown_spawned"):
        monkeypatch.setattr("app.voice.tts.shutdown_spawned", lambda: None)
    # RAG 预热旗标置位:单测不跑真预热(真实加载 ~18s),retrieve_async 直通
    import threading

    import app.rag as _rag

    ready = threading.Event()
    ready.set()
    monkeypatch.setattr(_rag, "_ready", ready)
    return mem


@pytest.fixture()
def tmp_reports(tmp_path: pytest.TempPathFactory) -> StationReports:
    """station/admin 路由测试共用:临时 reports 库替身,收尾还原单例。"""

    store = StationReports(str(tmp_path / "station.db"))
    reset_reports(store)
    yield store
    reset_reports()
