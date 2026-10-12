"""station 接缝钉测试:reports 表最新胜 / REST 端点形状(409/404/pending/ready,
契约 §1)/ 防重受理与陈旧重收 / planner 降级模板与非医疗声明硬保证。
planner 与 RAG 全 stub;后台任务经 TestClient portal 落地,轮询行断言。"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.llm import LLMError
from app.main import app
from app.schema import Emotion, Formulation, StationReportResponse, StationReportStatus
from app.station.planner import DISCLAIMER, generate_report
from app.station.reports import get_reports

client = TestClient(app)


def _material(summary: str = "焦虑睡不着的总结") -> dict[str, Any]:
    f = Formulation(situation="加班到很晚", thought="我做得不够好")
    f.emotion = Emotion(label="疲惫", intensity=0.6)
    return {
        "formulation": f.model_dump_json(by_alias=True),
        "summary": summary,
        "round_id": "r2",
    }


class _RagStub:
    def retrieve(self, query: str, k: int | None = None) -> list[Any]:
        return []


def _patch_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub())


# ---- 契约形状 ----


def test_contract_shape():
    assert set(StationReportResponse.model_fields) == {"status", "report_md"}
    assert {e.value for e in StationReportStatus} == {"pending", "ready"}


def test_cors_preflight_allowed():
    """dev 前端(5173)跨源访问 REST:预检放行;白名单外来源不放行。"""

    res = client.options(
        "/station/report/latest",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = client.options(
        "/station/report/latest",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert bad.headers.get("access-control-allow-origin") != "http://evil.example"


# ---- reports 表 ----


def test_reports_upsert_latest_wins(tmp_reports: Any):
    get_reports().upsert("s", "pending", round_id="r0")
    assert get_reports().get_latest("s") is not None
    get_reports().upsert("s", "ready", "第一稿", round_id="r0")
    row = get_reports().get_latest("s")
    assert row is not None and row["status"] == "ready" and row["report_md"] == "第一稿"
    get_reports().upsert("s", "ready", "第二稿", round_id="r0")  # 同回合重新生成=覆盖
    row = get_reports().get_latest("s")
    assert row is not None and row["report_md"] == "第二稿"
    assert get_reports().clear_all() == 1
    assert get_reports().get_latest("s") is None


def test_reports_history_by_round(tmp_reports: Any):
    """(session_id, round_id) 主键历史保留:新回合新增行,get_latest 取最新回合。"""
    get_reports().upsert("s", "ready", "第 0 回合稿", round_id="r0", emotion_label="焦虑")
    get_reports().upsert("s", "pending", round_id="r1", emotion_label="低落")
    row = get_reports().get_latest("s")
    assert row is not None and row["round_id"] == "r1" and row["status"] == "pending"
    assert row["emotion_label"] == "低落"
    get_reports().upsert("s", "ready", "第 1 回合稿", round_id="r1", emotion_label="低落")
    row = get_reports().get_latest("s")
    assert row is not None and row["status"] == "ready" and row["report_md"] == "第 1 回合稿"
    # 旧回合行还在(历史保留)
    with sqlite3.connect(tmp_reports._db_path) as conn:
        rows = conn.execute(
            "SELECT round_id, status FROM station_reports WHERE session_id='s' ORDER BY round_id"
        ).fetchall()
    assert rows == [("r0", "ready"), ("r1", "ready")]
    assert get_reports().clear_all() == 2


# ---- REST 端点 ----


def test_generate_no_material_409(fake_memory: Any, tmp_reports: Any):
    res = client.post("/station/report/generate", params={"session_id": "s1"})
    assert res.status_code == 409
    assert "素材" in res.json()["detail"]


def test_latest_404_when_never_generated(tmp_reports: Any):
    res = client.get("/station/report/latest", params={"session_id": "s_none"})
    assert res.status_code == 404


def test_latest_pending_and_ready_shapes(tmp_reports: Any):
    get_reports().upsert("s2", "pending")
    res = client.get("/station/report/latest", params={"session_id": "s2"})
    assert res.status_code == 200
    assert res.json() == {"status": "pending"}  # report_md 不带(exclude_none)
    get_reports().upsert("s2", "ready", "# 心理成长方案\n\n稿")
    res = client.get("/station/report/latest", params={"session_id": "s2"})
    assert res.json() == {"status": "ready", "report_md": "# 心理成长方案\n\n稿"}


def test_generate_flow_pending_to_ready(
    fake_memory: Any, tmp_reports: Any, monkeypatch: pytest.MonkeyPatch
):
    fake_memory.station_input = _material()
    got: list[str] = []

    async def _stub(f: Formulation, summary: str) -> str:
        got.append(summary)
        return "# 心理成长方案\n\n生成稿"

    monkeypatch.setattr("app.station.planner.generate_report", _stub)
    from app.admin import reset_config_store
    from app.admin.config_store import ConfigStore

    reset_config_store(ConfigStore(":memory:"))  # lifespan 读空配置,不触真库
    with TestClient(app) as c:
        res = c.post("/station/report/generate", params={"session_id": "s1"})
        assert res.status_code == 200
        assert res.json() == {"status": "pending"}
        row = None
        for _ in range(200):  # 后台任务在 portal loop 落地,轮询行
            row = get_reports().get_latest("s1")
            if row is not None and row["status"] == "ready":
                break
            time.sleep(0.02)
        assert row is not None and row["status"] == "ready"
        assert row["report_md"] == "# 心理成长方案\n\n生成稿"
        assert row["round_id"] == "r2"  # 素材 round_id 落账(手动重生成同键)
        assert row["emotion_label"] == "疲惫"  # 素材研判标签落账
        latest = c.get("/station/report/latest", params={"session_id": "s1"})
        assert latest.json() == {"status": "ready", "report_md": "# 心理成长方案\n\n生成稿"}
    assert got == ["焦虑睡不着的总结"]


def test_generate_dedup_while_pending(
    fake_memory: Any, tmp_reports: Any, monkeypatch: pytest.MonkeyPatch
):
    fake_memory.station_input = _material()
    started = 0

    async def _slow(f: Formulation, summary: str) -> str:
        nonlocal started
        started += 1
        await asyncio.sleep(30)  # 拖住在途;portal 退出时取消
        return "# 稿"

    monkeypatch.setattr("app.station.planner.generate_report", _slow)
    from app.admin import reset_config_store
    from app.admin.config_store import ConfigStore

    reset_config_store(ConfigStore(":memory:"))
    with TestClient(app) as c:
        assert c.post("/station/report/generate", params={"session_id": "s1"}).json() == {
            "status": "pending"
        }
        assert c.post("/station/report/generate", params={"session_id": "s1"}).json() == {
            "status": "pending"
        }
    assert started == 1  # 鲜 pending 不重复起任务


def test_generate_stale_pending_reaccepted(
    fake_memory: Any, tmp_reports: Any, monkeypatch: pytest.MonkeyPatch
):
    fake_memory.station_input = _material()
    started = 0

    async def _slow(f: Formulation, summary: str) -> str:
        nonlocal started
        started += 1
        await asyncio.sleep(30)
        return "# 稿"

    monkeypatch.setattr("app.station.planner.generate_report", _slow)
    from app.admin import reset_config_store
    from app.admin.config_store import ConfigStore

    reset_config_store(ConfigStore(":memory:"))
    with TestClient(app) as c:
        c.post("/station/report/generate", params={"session_id": "s1"})
        with sqlite3.connect(tmp_reports._db_path) as conn:
            conn.execute(
                "UPDATE station_reports SET updated_at = '2020-01-01T00:00:00' "
                "WHERE session_id = 's1'"
            )
        res = c.post("/station/report/generate", params={"session_id": "s1"})
        assert res.status_code == 200
    assert started == 2  # 陈旧 pending(任务已死)重新受理


def test_auto_generate_round_end(
    fake_memory: Any, tmp_reports: Any, monkeypatch: pytest.MonkeyPatch
):
    """回合末自动生成(方案书裁定):start_auto_generate 按回合键落 pending 后台起任务;
    同回合重复触发(重连/收尾重放)在鲜 pending 窗内不重复起任务。"""
    started = 0

    async def _stub(f: Formulation, summary: str) -> str:
        nonlocal started
        started += 1
        return "# 自动稿"

    monkeypatch.setattr("app.station.planner.generate_report", _stub)
    from app.station.routes import start_auto_generate

    async def _drive() -> None:
        await start_auto_generate("s9", "r0", _material())
        await start_auto_generate("s9", "r0", _material())  # 鲜 pending:防重
        for _ in range(200):
            row = get_reports().get_latest("s9")
            if row is not None and row["status"] == "ready":
                break
            await asyncio.sleep(0.02)

    asyncio.run(_drive())
    row = get_reports().get_latest("s9")
    assert row is not None and row["status"] == "ready" and row["report_md"] == "# 自动稿"
    assert row["round_id"] == "r0"
    assert started == 1


def test_auto_generate_new_round_appends(
    fake_memory: Any, tmp_reports: Any, monkeypatch: pytest.MonkeyPatch
):
    """第二回合 Finish:新 round_id 行新增,latest 指向新回合(历史保留)。"""
    from app.station.routes import start_auto_generate

    async def _drive() -> None:
        await start_auto_generate("s8", "r0", _material("第一回合小结"))
        for _ in range(200):
            row = get_reports().get_latest("s8")
            if row is not None and row["status"] == "ready":
                break
            await asyncio.sleep(0.02)
        await start_auto_generate("s8", "r1", _material("第二回合小结"))
        for _ in range(200):
            row = get_reports().get_latest("s8")
            if row is not None and row["round_id"] == "r1" and row["status"] == "ready":
                break
            await asyncio.sleep(0.02)

    asyncio.run(_drive())
    row = get_reports().get_latest("s8")
    assert row is not None and row["round_id"] == "r1"
    with sqlite3.connect(tmp_reports._db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM station_reports WHERE session_id='s8'").fetchone()[0]
    assert n == 2  # 两回合各一行(历史保留)


# ---- planner ----


class _ErrProvider:
    async def chat(self, messages: Any) -> str:
        raise LLMError("provider down")


class _OkProvider:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.messages: list[Any] = []

    async def chat(self, messages: Any) -> str:
        self.messages = messages
        return self.reply


async def test_planner_fallback_on_llm_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.station.planner.get_provider", lambda: _ErrProvider())
    _patch_rag(monkeypatch)
    md = await generate_report(Formulation(situation="被否定", thought="我不行"), "总结")
    assert "# 心理成长方案" in md
    assert "被否定" in md  # 素材进降级模板
    assert "不构成医疗诊断" in md  # 非医疗声明硬保证
    assert "1. " in md  # 练习列表


async def test_planner_llm_ok_appends_disclaimer_when_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    provider = _OkProvider("# 心理成长方案\n\n正文内容")
    monkeypatch.setattr("app.station.planner.get_provider", lambda: provider)
    _patch_rag(monkeypatch)
    md = await generate_report(Formulation(), "")
    assert md.endswith(DISCLAIMER)
    assert md.count(DISCLAIMER) == 1


async def test_planner_llm_disclaimer_kept(monkeypatch: pytest.MonkeyPatch):
    body = "# 心理成长方案\n\n正文\n\n> 不构成医疗诊断或治疗建议,请寻求专业帮助。"
    provider = _OkProvider(body)
    monkeypatch.setattr("app.station.planner.get_provider", lambda: provider)
    _patch_rag(monkeypatch)
    md = await generate_report(Formulation(), "")
    assert md == body  # 已有声明不重复拼


async def test_planner_timeout_falls_back(monkeypatch: pytest.MonkeyPatch):
    class _Slow:
        async def chat(self, messages: Any) -> str:
            await asyncio.sleep(1)
            return "# 稿"

    monkeypatch.setattr("app.station.planner.get_provider", lambda: _Slow())
    monkeypatch.setattr("app.station.planner.PLANNER_TIMEOUT_S", 0.05)
    _patch_rag(monkeypatch)
    md = await generate_report(Formulation(), "")
    assert "# 心理成长方案" in md  # 超时走降级模板


async def test_planner_rag_failure_degrades(monkeypatch: pytest.MonkeyPatch):
    def _raise() -> Any:
        raise RuntimeError("rag down")

    monkeypatch.setattr("app.rag.get_engine", _raise)
    provider = _OkProvider("# 心理成长方案\n\n正文")
    monkeypatch.setattr("app.station.planner.get_provider", lambda: provider)
    md = await generate_report(Formulation(), "小结")
    assert md  # RAG 挂→refs 空照常出稿
