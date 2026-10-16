"""测试公共桩:网关用假记忆(autouse)——网关测试不依赖真 Redis/SQLite,
真链路由 tests/test_memory.py 直测 Memory(前置=本机 Redis 可用)。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from app import config
from app.agents.state import SessionContext
from app.memory import MaterialState
from app.memory.store import StationMaterial
from app.station.reports import StationReports, reset_reports


def _now() -> datetime:
    return datetime.now()  # noqa: DTZ005 — 与 app 侧本地时区同基准


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


class FakeMemory:
    """调用记录型替身;snapshot 恒空档(需要历史语境的用例自行改写 history_summary)。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._snapshot = SessionContext()
        self.station_input: dict[str, Any] | None = None  # load_station_input 返回口
        self.station_state: MaterialState = "ok"  # load/probe_station_input 状态口(unknown=有效期不可确认)
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
        self,
        session_id: str,
        round_id: str,
        formulation_json: str,
        summary: str,
        collected_at: str | None = None,
    ) -> bool:
        self.calls.append(
            (
                "save_station_input",
                {
                    "session_id": session_id,
                    "round_id": round_id,
                    "formulation_json": formulation_json,
                    "summary": summary,
                    "collected_at": collected_at,
                },
            )
        )
        # 写回返回口:回合末自动生成(R1 裁定)归档后立即 load 素材,
        # 不写回会话内 save→load 断流,触发被静默跳过
        if self.station_input is None:
            self.station_input = {
                "formulation": formulation_json,
                "summary": summary,
                "collected_at": collected_at or _now_iso(),
            }
        return True

    async def load_station_input(
        self, session_id: str, round_id: str
    ) -> tuple[MaterialState, StationMaterial | None]:
        self.calls.append(
            ("load_station_input", {"session_id": session_id, "round_id": round_id})
        )
        if self.station_input is None:
            return "absent", None
        payload = dict(self.station_input)
        payload.setdefault("collected_at", _now_iso())
        return self.station_state, StationMaterial(
            payload=payload, deadline=_now() + timedelta(days=7), collected_at=_now()
        )

    async def probe_station_input(self, session_id: str, round_id: str) -> MaterialState:
        self.calls.append(
            ("probe_station_input", {"session_id": session_id, "round_id": round_id})
        )
        return self.station_state if self.station_input is not None else "absent"

    async def legacy_station_deadline(
        self, session_id: str
    ) -> tuple[MaterialState, datetime | None]:
        self.calls.append(("legacy_station_deadline", {"session_id": session_id}))
        return "absent", None

    def recent_moods(self, days: int = 7, *, source: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("recent_moods", {"days": days, "source": source}))
        rows = [dict(m) for m in self.moods]
        return rows if source is None else [m for m in rows if m["source"] == source]

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


class FakeSemantic:
    """语义记忆替身:调用记录型;网关/admin 测试零模型成本。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.items: list[dict[str, Any]] = []

    async def recall(self, query: str, recent_topics: str = "", k: int | None = None) -> list[dict[str, Any]]:
        self.calls.append(("recall", {"query": query, "recent_topics": recent_topics}))
        return []

    async def save_notes(
        self,
        session_id: str,
        turn_index: int,
        notes_raw: str,
        *,
        mood_label: str | None = None,
        intensity: float | None = None,
    ) -> None:
        self.calls.append(
            (
                "save_notes",
                {
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "raw": notes_raw,
                    "mood_label": mood_label,
                    "intensity": intensity,
                },
            )
        )

    def list_items(self, limit: int = 50) -> list[dict[str, Any]]:
        self.calls.append(("list_items", {"limit": limit}))
        return list(self.items)

    def delete_items(self, ids: list[str]) -> None:
        self.calls.append(("delete_items", {"ids": ids}))

    def clear_all(self) -> int:
        self.calls.append(("clear_all", {}))
        n = len(self.items)
        self.items.clear()
        return n


class _DefaultCollectLLM:
    """collect 图 LLM 默认替身(问话 LLM 化后的测试隔离桩)。

    问话从预置库改 LLM 流式后,任何触发 collect 而未打桩的测试都会真调 LLM API
    ——网络抖动(LLMError→AskFailed)让收帧测试死等文本帧。默认桩堵这个洞;
    需要特定行为的用例自行 monkeypatch 覆盖(函数级 setattr 晚于本 fixture 生效)。
    """

    async def chat(self, messages: Any) -> str:
        return "这次梳理的笔记。"

    async def stream(self, messages: Any):
        yield "嗯,先从最具体的一幕说起吧,当时发生了什么?"

    async def chat_json(self, messages: Any, schema: type) -> Any:
        name = getattr(schema, "__name__", "")
        if name == "_ExtractOut":
            asked = ""
            for m in messages:
                content = getattr(m, "content", "") or ""
                for line in content.splitlines():
                    if line.startswith("所问字段:"):
                        asked = line.split(":", 1)[1].strip()
            return schema(fields={asked: "提炼值"} if asked else {}, off_topic=False)
        if name == "RouteLabel":
            return schema(route="collect", emotion_label=None, confidence=0.9)
        if name == "_ReviewOut":
            return schema(label="焦虑", intensity=0.8)
        if name == "_RiskOut":
            return schema(risky=False)
        raise AssertionError(f"未预期 schema: {name}")


@pytest.fixture(autouse=True)
def fake_memory(monkeypatch: pytest.MonkeyPatch, tmp_path_factory) -> FakeMemory:
    mem = FakeMemory()
    monkeypatch.setattr("app.ws_gateway.gateway.get_memory", lambda: mem)
    monkeypatch.setattr("app.station.routes.get_memory", lambda: mem)
    monkeypatch.setattr("app.admin.routes.get_memory", lambda: mem)
    monkeypatch.setattr("app.main.get_memory", lambda: mem)
    sem = FakeSemantic()
    monkeypatch.setattr("app.ws_gateway.gateway.get_semantic", lambda: sem)
    monkeypatch.setattr("app.admin.routes.get_semantic", lambda: sem)
    # 语音默认静音:TTS 流式合成不出块(跳过音频帧)、fillers 取不到——防测试
    # 拉起真 sidecar 或多出 audio_chunk 破坏既有帧序断言;语音用例自行覆盖。
    # **两条链路都要静音**:默认 STREAM_MODE=pcm,只静音 wav 那条等于没静音
    # ——真去打 TTS 服务既给事件循环加负载(负载一变,batched_chunks 的 100ms
    # 攒批窗口切分就变,精确帧数断言会飘),又会多出 audio_chunk 打乱帧序断言。
    # 要真服务的那一组(test_ws_streaming_e2e.py)自己恢复。
    # 签名带 **kw:realtime 链路会用 request_id= 关键字调用。
    monkeypatch.setattr("app.voice.tts.synthesize_stream", lambda text, **kw: iter(()))
    monkeypatch.setattr("app.voice.tts.synthesize_pcm_stream", lambda text, **kw: iter(()))
    # 预置语音静音:FILLERS_DIR 指空目录=pick_named 缺文件路径(返回 None),
    # 防真 data/fillers 泄进帧序断言;要用真 wav 的用例自行 monkeypatch
    # FILLERS_DIR 到 tmp_path 并写文件(见 test_gateway 危机/回执用例)
    monkeypatch.setattr(config, "FILLERS_DIR", str(tmp_path_factory.mktemp("fillers")))
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
    # collect 图 LLM 默认桩(问话 LLM 化的测试隔离;extract/analysis/classifier
    # 三处同打,classifier 桩保持 fallback=collect 语义不扰路由测试)
    _default_llm = _DefaultCollectLLM()
    for target in (
        "app.agents.extract.get_provider",
        "app.agents.analysis.get_provider",
        "app.agents.graph.get_provider",
        "app.router.classifier.get_provider",
    ):
        monkeypatch.setattr(target, lambda _p=_default_llm: _p)
    # sem 挂在 mem 上供用例取用(避免改 fixture 签名破坏既有用例)
    mem.semantic = sem  # type: ignore[attr-defined] — 动态挂载,仅测试便利
    return mem


@pytest.fixture(autouse=True)
def tmp_reports(tmp_path: pytest.TempPathFactory) -> StationReports:
    """station 路由/网关测试共用:临时 reports 库替身,收尾还原单例。

    autouse:轮次高水位 round_seq 也在这个库里——不隔离会让测试污染真实
    station.db(数据/运行时产物),且轮次编号跨测试串号。"""

    store = StationReports(str(tmp_path / "station.db"))
    reset_reports(store)
    yield store
    reset_reports()
