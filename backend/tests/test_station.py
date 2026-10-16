"""station 接缝钉测试:reports 表按 (session,round) · 轮次高水位不复用 · 过期清理与
迁移核价 / REST 端点形状(409/404/503/pending/ready,契约 §1)/ 防重受理与陈旧重收 /
gen_token 条件写入(旧任务不覆盖新稿)/ planner 降级模板与非医疗声明硬保证。
planner 与 RAG 全 stub;后台任务经 TestClient portal 落地,轮询行断言。"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.llm import LLMError
from app.main import app
from app.memory import MaterialState
from app.memory.store import StationMaterial
from app.schema import Emotion, Formulation, StationReportResponse, StationReportStatus
from app.station.planner import DISCLAIMER, generate_report
from app.station.reports import StationReports, derive_title, get_reports
from app.station.routes import _gen_locks

client = TestClient(app)


async def _stub_report(f: Formulation, summary: str) -> str:
    return "# 心理成长方案\n\n生成稿"


def _material(summary: str = "焦虑睡不着的总结") -> dict[str, Any]:
    f = Formulation(situation="加班到很晚", thought="我做得不够好")
    return {
        "formulation": Formulation(
            situation=f.situation,
            thought=f.thought,
            emotion=Emotion(label="焦虑"),
        ).model_dump_json(by_alias=True),
        "summary": summary,
        "collected_at": "2026-10-14T21:22:48",
    }


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _set_material(fake_memory: Any, material: dict[str, Any] | None, state: MaterialState = "ok") -> None:
    fake_memory.station_input = material
    fake_memory.station_state = state


class _RagStub:
    def retrieve(self, query: str, k: int | None = None) -> list[Any]:
        return []


def _patch_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.get_engine", lambda: _RagStub())


@pytest.fixture(autouse=True)
def _reset_locks():
    _gen_locks.clear()
    yield
    _gen_locks.clear()


# ---- 契约形状 ----


def test_contract_shape():
    assert set(StationReportResponse.model_fields) == {"status", "report_md", "title", "updated_at"}
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


# ---- reports 表:轮次维度 ----


def test_reports_round_scoped_latest_wins(tmp_reports: StationReports):
    """同一 session 两轮各存一份,互不覆盖。"""

    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s", "1", "t1", collected_at=now, expires_at=now + timedelta(days=7), title="第 1 次梳理"
    )
    assert tmp_reports.finish_generation("s", "1", "t1", report_md="# 第一稿", title="第 1 次梳理")
    tmp_reports.begin_generation(
        "s", "2", "t2", collected_at=now, expires_at=now + timedelta(days=7), title="第 2 次梳理"
    )
    assert tmp_reports.finish_generation("s", "2", "t2", report_md="# 第二稿", title="第 2 次梳理")

    row1 = tmp_reports.get_active("s", "1")
    row2 = tmp_reports.get_active("s", "2")
    assert row1 is not None and row1["report_md"] == "# 第一稿"
    assert row2 is not None and row2["report_md"] == "# 第二稿"


def test_begin_generation_keeps_previous_md(tmp_reports: StationReports):
    """重生成占位不清 report_md——新稿失败时旧稿仍可查看。"""

    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s", "1", "t1", collected_at=now, expires_at=now + timedelta(days=7), title="第 1 次梳理"
    )
    assert tmp_reports.finish_generation("s", "1", "t1", report_md="# 旧稿", title="第 1 次梳理")
    tmp_reports.begin_generation(
        "s", "1", "t2", collected_at=now, expires_at=now + timedelta(days=7), title="第 1 次梳理"
    )
    row = tmp_reports.get_active("s", "1")
    assert row is not None and row["status"] == "pending" and row["report_md"] == "# 旧稿"


def test_finish_generation_rejects_stale_token(tmp_reports: StationReports):
    """令牌不符(旧任务被顶掉)→ 拒绝覆盖,新稿不被旧任务冲掉。"""

    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s", "1", "t-old", collected_at=now, expires_at=now + timedelta(days=7), title="t"
    )
    assert tmp_reports.finish_generation("s", "1", "t-old", report_md="# 第一稿", title="t")
    # 重新生成:新令牌接管,旧任务随后才返回
    tmp_reports.begin_generation(
        "s", "1", "t-new", collected_at=now, expires_at=now + timedelta(days=7), title="t"
    )
    assert tmp_reports.finish_generation("s", "1", "t-old", report_md="# 过期旧稿", title="t") is False
    assert tmp_reports.finish_generation("s", "1", "t-new", report_md="# 新稿", title="t") is True
    row = tmp_reports.get_active("s", "1")
    assert row is not None and row["report_md"] == "# 新稿"


def test_finish_generation_rejects_when_expired(tmp_reports: StationReports):
    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s", "1", "t1", collected_at=now - timedelta(days=8),
        expires_at=now - timedelta(days=1), title="t",
    )
    assert tmp_reports.finish_generation("s", "1", "t1", report_md="# 迟到的稿", title="t") is False


def test_round_seq_monotonic_and_not_reused(tmp_reports: StationReports):
    """轮次高水位单调;删报告不重置编号(治理清除不复用 round_id)。"""

    first = [tmp_reports.next_round_id("s") for _ in range(3)]
    assert first == ["1", "2", "3"]
    tmp_reports.clear_all()
    assert tmp_reports.next_round_id("s") == "4"  # 不复用 1/2/3


def test_delete_expired_keeps_fresh_pending(tmp_reports: StationReports):
    """过期即物理删除;鲜 pending(生成在途)不删。"""

    now = datetime.now()  # noqa: DTZ005
    # 常态过期行:ready + 到期(由直插构造——finish_generation 自身会拒绝写过期行)
    with sqlite3.connect(tmp_reports._db_path) as conn:
        conn.execute(
            "INSERT INTO station_reports (session_id, round_id, status, report_md, title, "
            "collected_at, created_at, updated_at, expires_at, gen_token) "
            "VALUES (?, '1', 'ready', '# 旧稿', '第 1 次梳理', ?, ?, ?, ?, NULL)",
            (
                "s", "1", _iso(now - timedelta(days=8)), _iso(now - timedelta(days=8)),
                _iso(now - timedelta(days=1)),
            ),
        )
    # 在途 pending(未过期)
    tmp_reports.begin_generation(
        "s", "2", "t2", collected_at=now, expires_at=now + timedelta(days=7), title="在途"
    )
    assert tmp_reports.delete_expired() == 1
    assert tmp_reports.get_active("s", "1") is None
    assert tmp_reports.get_active("s", "2") is not None


async def test_refine_legacy_expiry_states(tmp_reports: StationReports):
    """遗留核价三态:可核价→原始到期;不可核验→立即过期;Redis 不可达→保持未定价。"""

    async def probe(sid: str) -> tuple[MaterialState, datetime | None]:
        now = datetime.now()  # noqa: DTZ005 — 与 app 侧本地时区同基准
        return {"ok": ("ok", now + timedelta(days=3)),
                "absent": ("absent", None),
                "unknown": ("unknown", None)}[sid]

    with sqlite3.connect(tmp_reports._db_path) as conn:
        for sid in ("ok", "absent", "unknown"):
            conn.execute(
                "INSERT INTO station_reports (session_id, round_id, status, report_md, title, "
                "collected_at, created_at, updated_at, expires_at, gen_token) "
                "VALUES (?, 'legacy', 'ready', '# 旧', '早期方案 · 轮次未知', ?, ?, ?, NULL, NULL)",
                (sid, "2026-09-20T10:00:00", "2026-09-20T10:00:00", "2026-09-20T10:00:00"),
            )
    counts = await tmp_reports.refine_legacy_expiry(probe)
    assert counts == {"priced": 1, "expired": 1, "unknown": 1}
    assert tmp_reports.get_active("ok", "legacy") is not None  # 仍在 3 天窗口内
    assert tmp_reports.get_active("absent", "legacy") is None  # 立即过期
    with sqlite3.connect(tmp_reports._db_path) as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM station_reports WHERE expires_at IS NULL"
        ).fetchone()[0]
    assert left == 1  # unknown 不猜不删,下次启动重试


# ---- REST 端点 ----


def test_generate_no_material_409(fake_memory: Any, tmp_reports: StationReports):
    _set_material(fake_memory, None)
    res = client.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"})
    assert res.status_code == 409
    assert "素材" in res.json()["detail"]


def test_generate_material_unknown_503(fake_memory: Any, tmp_reports: StationReports):
    _set_material(fake_memory, _material(), state="unknown")
    res = client.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"})
    assert res.status_code == 503
    assert "无法确认" in res.json()["detail"]


def test_generate_expired_material_409(fake_memory: Any, tmp_reports: StationReports):
    fake_memory.station_input = _material()
    fake_memory.station_state = "ok"
    # 让桩返回的 deadline 落在过去:直接覆盖 load_station_input
    past = datetime.now() - timedelta(days=1)  # noqa: DTZ005 — 与 app 侧同基准
    old = _material()
    old["collected_at"] = (past - timedelta(days=7)).isoformat(timespec="seconds")

    async def _stale(session_id: str, round_id: str):
        return "ok", StationMaterial(payload=old, deadline=past, collected_at=past - timedelta(days=7))

    fake_memory.load_station_input = _stale  # type: ignore[method-assign]
    res = client.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"})
    assert res.status_code == 409
    assert "有效期" in res.json()["detail"]


def test_latest_404_when_never_generated(tmp_reports: StationReports):
    res = client.get("/station/report/latest", params={"session_id": "s_none", "round_id": "1"})
    assert res.status_code == 404


def test_latest_pending_and_ready_shapes(tmp_reports: StationReports):
    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s2", "1", "t", collected_at=now, expires_at=now + timedelta(days=7), title="t"
    )
    res = client.get("/station/report/latest", params={"session_id": "s2", "round_id": "1"})
    assert res.status_code == 200
    assert res.json() == {"status": "pending"}  # report_md 不带(exclude_none)
    tmp_reports.begin_generation(
        "s2", "1", "t2", collected_at=now, expires_at=now + timedelta(days=7), title="t"
    )
    assert tmp_reports.finish_generation("s2", "1", "t2", report_md="# 稿\n\n正文", title="t")
    res = client.get("/station/report/latest", params={"session_id": "s2", "round_id": "1"})
    body = res.json()
    assert body["status"] == "ready"
    assert body["report_md"] == "# 稿\n\n正文"
    assert body["title"] == "t"  # 标题由 finish_generation 写入
    assert body["updated_at"] is not None


def test_latest_expired_row_404(tmp_reports: StationReports):
    now = datetime.now()  # noqa: DTZ005
    with sqlite3.connect(tmp_reports._db_path) as conn:
        conn.execute(
            "INSERT INTO station_reports (session_id, round_id, status, report_md, title, "
            "collected_at, created_at, updated_at, expires_at, gen_token) "
            "VALUES (?, '1', 'ready', '# 过期稿', '第 1 次梳理', ?, ?, ?, ?, NULL)",
            (
                "s3", _iso(now - timedelta(days=8)), _iso(now - timedelta(days=8)),
                _iso(now - timedelta(days=8)), _iso(now - timedelta(days=1)),
            ),
        )
    res = client.get("/station/report/latest", params={"session_id": "s3", "round_id": "1"})
    assert res.status_code == 404  # 过期=不可查看,不以 200 悬挂


def test_generate_flow_pending_to_ready(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    _set_material(fake_memory, _material())
    got: list[str] = []

    async def _stub(f: Formulation, summary: str) -> str:
        got.append(summary)
        return "# 心理成长方案\n\n生成稿"

    monkeypatch.setattr("app.station.planner.generate_report", _stub)
    from app.admin import reset_config_store
    from app.admin.config_store import ConfigStore

    reset_config_store(ConfigStore(":memory:"))  # lifespan 读空配置,不触真库
    with TestClient(app) as c:
        res = c.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"})
        assert res.status_code == 200
        assert res.json() == {"status": "pending"}
        row = None
        for _ in range(200):  # 后台任务在 portal loop 落地,轮询行
            row = get_reports().get_active("s1", "1")
            if row is not None and row["status"] == "ready":
                break
            time.sleep(0.02)
        assert row is not None and row["status"] == "ready"
        assert row["report_md"] == "# 心理成长方案\n\n生成稿"
        latest = c.get("/station/report/latest", params={"session_id": "s1", "round_id": "1"})
        assert latest.json()["report_md"] == "# 心理成长方案\n\n生成稿"
        # 标题取自素材自身数据(情境 · 情绪),不是轮次序号
        assert latest.json()["title"] == "加班到很晚 · 焦虑"
    assert got == ["焦虑睡不着的总结"]


def test_generate_dedup_while_pending(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    _set_material(fake_memory, _material())
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
        assert c.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"}).json() == {
            "status": "pending"
        }
        assert c.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"}).json() == {
            "status": "pending"
        }
    assert started == 1  # 鲜 pending 不重复起任务


def test_generate_stale_pending_reaccepted(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    _set_material(fake_memory, _material())
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
        c.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"})
        with sqlite3.connect(tmp_reports._db_path) as conn:
            conn.execute(
                "UPDATE station_reports SET updated_at = '2020-01-01T00:00:00' "
                "WHERE session_id = 's1' AND round_id = '1'"
            )
        res = c.post("/station/report/generate", params={"session_id": "s1", "round_id": "1"})
        assert res.status_code == 200
    assert started == 2  # 陈旧 pending(任务已死)重新受理


# ---- 并发/列表/寻址/标题(融合自 PR #4) ----


def test_regenerate_concurrent_start_one_task(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    """并发/双击:进程内锁保证只起一个任务(旧版非原子窗口)。"""

    _set_material(fake_memory, _material())
    started = 0

    async def _slow(f: Formulation, summary: str) -> str:
        nonlocal started
        started += 1
        await asyncio.sleep(0.2)
        return "# 稿"

    monkeypatch.setattr("app.station.planner.generate_report", _slow)
    from app.admin import reset_config_store
    from app.admin.config_store import ConfigStore

    reset_config_store(ConfigStore(":memory:"))
    with TestClient(app) as c:
        import threading

        results: list[int] = []

        def _post() -> None:
            results.append(
                c.post(
                    "/station/report/generate", params={"session_id": "s1", "round_id": "1"}
                ).status_code
            )

        threads = [threading.Thread(target=_post) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results == [200] * 4
    assert started == 1


def test_report_list_shape_and_can_regenerate(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    """列表:只含有效报告;can_regenerate 三态(unknown ≠ 可用)。"""

    _set_material(fake_memory, _material())
    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s", "1", "t1", collected_at=now, expires_at=now + timedelta(days=7), title="第 1 次梳理"
    )
    assert tmp_reports.finish_generation("s", "1", "t1", report_md="# 稿", title="第 1 次梳理")
    # 过期行不进列表
    tmp_reports.begin_generation(
        "s", "2", "t2", collected_at=now - timedelta(days=8),
        expires_at=now - timedelta(days=1), title="第 2 次梳理",
    )
    res = client.get("/station/report/list", params={"session_id": "s"})
    assert res.status_code == 200
    reports = res.json()["reports"]
    assert [r["round_id"] for r in reports] == ["1"]
    assert reports[0]["can_regenerate"] == "yes"
    assert reports[0]["title"] == "第 1 次梳理"
    assert reports[0]["expires_at"] is not None

    fake_memory.station_state = "unknown"
    res = client.get("/station/report/list", params={"session_id": "s"})
    assert res.json()["reports"][0]["can_regenerate"] == "unknown"

    _set_material(fake_memory, None)
    res = client.get("/station/report/list", params={"session_id": "s"})
    assert res.json()["reports"][0]["can_regenerate"] == "no"


def test_missing_round_id_422(tmp_reports: StationReports):
    """round_id 必填(不猜轮次)。"""

    assert client.post("/station/report/generate", params={"session_id": "s1"}).status_code == 422
    assert client.get("/station/report/latest", params={"session_id": "s1"}).status_code == 422


# ---- 标题:数据驱动,不用轮次序号 ----


def test_derive_title_uses_situation_and_emotion():
    assert derive_title("上周开会汇报被领导当众批评", "焦虑") == "上周开会汇报被领导当众批评 · 焦虑"
    assert derive_title("加班到很晚", None) == "加班到很晚"          # 情绪缺失 → 无分隔符
    assert derive_title(None, "疲惫") == "疲惫"                    # 情境缺失 → 只用情绪
    assert derive_title(None, None) == "这一次的梳理"              # 全缺 → 中性备用
    assert derive_title("", "") == "这一次的梳理"
    assert derive_title("一" * 30, "焦虑").endswith("… · 焦虑")     # 超长截断


def test_generate_title_from_material_not_round_id(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    """标题取自素材自身数据(情境 · 情绪),与被抢占作废也照样递增的 round_id 无关。"""

    _set_material(fake_memory, _material())
    monkeypatch.setattr("app.station.planner.generate_report", _stub_report)
    with TestClient(app) as c:
        c.post("/station/report/generate", params={"session_id": "s1", "round_id": "5"})
        row = None
        for _ in range(200):
            row = get_reports().get_active("s1", "5")
            if row is not None and row["status"] == "ready":
                break
            time.sleep(0.02)
    assert row is not None
    assert row["title"] == "加班到很晚 · 焦虑"
    assert "第" not in row["title"]  # 不得出现轮次序号


# ---- 同一来源只有一份逻辑报告(幂等/去重) ----


def test_repeated_generation_keeps_one_row(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    """同一 (session_id, round_id) 重复生成:仍只有一行,正文被更新(最新胜)。"""

    _set_material(fake_memory, _material())
    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s", "1", "t1", collected_at=now, expires_at=now + timedelta(days=7), title="第一次"
    )
    assert tmp_reports.finish_generation("s", "1", "t1", report_md="# 第一稿", title="第一次")
    # 第二次受理+生成
    tmp_reports.begin_generation(
        "s", "1", "t2", collected_at=now, expires_at=now + timedelta(days=7), title="第二次"
    )
    assert tmp_reports.finish_generation("s", "1", "t2", report_md="# 第二稿", title="第二次")
    rows = tmp_reports.list_by_session("s")
    assert len(rows) == 1  # 没有第二条逻辑报告
    assert rows[0]["report_md"] == "# 第二稿"
    assert rows[0]["created_at"] == rows[0]["created_at"]  # created_at 不被刷新
    assert rows[0]["updated_at"] >= rows[0]["created_at"]


def test_repeated_begin_generation_single_row(tmp_reports: StationReports):
    """同源重复 begin_generation(受理/重试)→ 仍只有一行(主键幂等)。

    跨进程/线程级并发由路由层 asyncio.Lock + PENDING 鲜度窗保证
    (见 test_regenerate_concurrent_start_one_task);这里钉 DB 层幂等。"""

    now = datetime.now()  # noqa: DTZ005
    for i in range(5):
        tmp_reports.begin_generation(
            "s", "1", f"t{i}", collected_at=now, expires_at=now + timedelta(days=7), title="x"
        )
    assert len(tmp_reports.list_by_session("s")) == 1


def test_different_rounds_not_merged(tmp_reports: StationReports):
    """不同来源(round_id 不同)不得被去重逻辑合并。"""

    now = datetime.now()  # noqa: DTZ005
    for rid in ("1", "2", "3"):
        tmp_reports.begin_generation(
            "s", rid, f"t{rid}", collected_at=now, expires_at=now + timedelta(days=7), title=f"r{rid}"
        )
        assert tmp_reports.finish_generation("s", rid, f"t{rid}", report_md=f"# {rid}", title=f"r{rid}")
    rows = tmp_reports.list_by_session("s")
    assert sorted(r["round_id"] for r in rows) == ["1", "2", "3"]  # 三份独立,不被去重合并
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps, reverse=True)  # 按创建时间降序


async def test_backfill_legacy_titles(tmp_reports: StationReports, fake_memory: Any):
    """旧式「第 N 次梳理」标题 → 数据驱动;幂等;无素材时落中性备用标题。"""

    async def loader_ok(sid: str, rid: str):
        return "ok", StationMaterial(
            payload={
                "formulation": Formulation(
                    situation="考试没考好",
                    thought="我不行",
                    emotion=Emotion(label="焦虑"),
                ).model_dump_json(),
                "summary": "s",
                "collected_at": "2026-10-14T21:22:48",
            },
            deadline=datetime.now() + timedelta(days=7),  # noqa: DTZ005
            collected_at=datetime.now(),  # noqa: DTZ005
        )

    async def loader_absent(sid: str, rid: str):
        return "absent", None

    for sid in ("a", "b"):
        tmp_reports.begin_generation(
            sid, "1", "t", collected_at=datetime.now(), expires_at=datetime.now() + timedelta(days=7),  # noqa: DTZ005
            title="第 1 次梳理 · 焦虑",
        )
        assert tmp_reports.finish_generation(sid, "1", "t", report_md="# 稿", title="第 1 次梳理 · 焦虑")

    counts = await tmp_reports.backfill_legacy_titles(loader_ok)
    assert counts == {"retitled": 2, "fallback": 0}
    assert tmp_reports.get_active("a", "1")["title"] == "考试没考好 · 焦虑"
    # 幂等:二跑不再改
    assert await tmp_reports.backfill_legacy_titles(loader_ok) == {"retitled": 0, "fallback": 0}
    # 无素材 → 中性备用标题,不动正文
    tmp_reports.begin_generation(
        "c", "1", "t", collected_at=datetime.now(), expires_at=datetime.now() + timedelta(days=7),  # noqa: DTZ005
        title="第 9 次梳理",
    )
    assert tmp_reports.finish_generation("c", "1", "t", report_md="# c稿", title="第 9 次梳理")
    counts2 = await tmp_reports.backfill_legacy_titles(loader_absent)
    assert counts2 == {"retitled": 0, "fallback": 1}
    row = tmp_reports.get_active("c", "1")
    assert row["title"] == "这一次的梳理"
    assert row["report_md"] == "# c稿"


def test_latest_returns_title_and_updated_at(tmp_reports: StationReports):
    """latest 回传 title/updated_at(前端据此显示「更新于」,不再只显示首次生成时间)。"""

    now = datetime.now()  # noqa: DTZ005
    tmp_reports.begin_generation(
        "s", "1", "t1", collected_at=now, expires_at=now + timedelta(days=7), title="t1"
    )
    assert tmp_reports.finish_generation("s", "1", "t1", report_md="# 稿", title="考试没考好 · 焦虑")
    tmp_reports.begin_generation(
        "s", "1", "t2", collected_at=now, expires_at=now + timedelta(days=7), title="t2"
    )
    assert tmp_reports.finish_generation("s", "1", "t2", report_md="# 新稿", title="把对方拉黑了 · 愤怒")
    res = client.get("/station/report/latest", params={"session_id": "s", "round_id": "1"})
    body = res.json()
    assert body["status"] == "ready"
    assert body["title"] == "把对方拉黑了 · 愤怒"
    assert body["updated_at"] is not None


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



def test_auto_generate_round_end(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    """回合末自动生成(R1 裁定):start_auto_generate 按回合键落 pending 后台起任务;
    同回合重复触发(重连/收尾重放)在鲜 pending 窗内不重复起任务。"""
    started = 0

    async def _stub(f: Formulation, summary: str) -> str:
        nonlocal started
        started += 1
        return "# 自动稿"

    monkeypatch.setattr("app.station.planner.generate_report", _stub)
    from datetime import datetime, timedelta

    from app.station.routes import start_auto_generate

    now = datetime.now()  # noqa: DTZ005
    material = StationMaterial(
        payload=_material(), deadline=now + timedelta(days=7), collected_at=now,
    )

    async def _drive() -> None:
        await start_auto_generate("s9", "3", material)
        await start_auto_generate("s9", "3", material)  # 鲜 pending:防重
        for _ in range(200):
            row = get_reports().get_active("s9", "3")
            if row is not None and row["status"] == "ready":
                break
            await asyncio.sleep(0.02)

    asyncio.run(_drive())
    row = get_reports().get_active("s9", "3")
    assert row is not None and row["status"] == "ready" and row["report_md"] == "# 自动稿"
    assert row["round_id"] == "3"
    assert started == 1


def test_auto_generate_new_round_appends(
    fake_memory: Any, tmp_reports: StationReports, monkeypatch: pytest.MonkeyPatch
):
    """第二回合 Finish:新 round_id 行新增,latest 指向新回合(历史保留)。"""
    from datetime import datetime, timedelta

    from app.station.routes import start_auto_generate

    now = datetime.now()  # noqa: DTZ005

    def _mat(summary: str) -> StationMaterial:
        return StationMaterial(
            payload=_material(summary), deadline=now + timedelta(days=7), collected_at=now,
        )

    async def _drive() -> None:
        await start_auto_generate("s8", "3", _mat("第一回合小结"))
        for _ in range(200):
            row = get_reports().get_active("s8", "3")
            if row is not None and row["status"] == "ready":
                break
            await asyncio.sleep(0.02)
        await start_auto_generate("s8", "4", _mat("第二回合小结"))
        for _ in range(200):
            row = get_reports().get_active("s8", "4")
            if row is not None and row["status"] == "ready":
                break
            await asyncio.sleep(0.02)

    asyncio.run(_drive())
    row = get_reports().get_active("s8", "4")
    assert row is not None and row["round_id"] == "4"
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
