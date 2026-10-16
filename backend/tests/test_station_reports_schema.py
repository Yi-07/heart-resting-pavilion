"""station reports 旧库自检重建钉测(任务线 collect-smooth-flow T0;PR4 融合后随新列集更新)。

回归现场:434867c 把 reports 表主键改 (session_id, round_id),CREATE TABLE
IF NOT EXISTS 对已存在的旧表(session_id 单列主键)不做迁移,真环境 SELECT
round_id 撞 no such column → /station/report/latest 500。测试库全新不暴露,
需以旧 schema 预建表再初始化来钉住。PR4 融合后列集再换(title/expires_at/
gen_token 取代 emotion_label),本地过渡表(有 emotion_label 无 expires_at)
同属旧库——自检判列集不符即 drop 重建,旧行不迁(报告可再生成)。
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from app.station.reports import _COLUMNS, StationReports

_OLD_DDL = """
CREATE TABLE station_reports (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    report_md TEXT,
    updated_at TEXT NOT NULL
)
"""

_MID_DDL = """
CREATE TABLE station_reports (
    session_id TEXT NOT NULL,
    round_id TEXT NOT NULL,
    status TEXT NOT NULL,
    report_md TEXT,
    emotion_label TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, round_id)
)
"""


@pytest.fixture()
def raw_db(tmp_path, tmp_reports):
    """独立 db 路径(避开 autouse tmp_reports 已建的 station.db,那里表已被现行
    schema 初始化,预置旧 DDL 会撞 already exists);tmp_reports 挂着只为占住单例,
    本文件直接实例化 StationReports(raw_db) 自管,不依赖全局单例。"""

    return str(tmp_path / "legacy.db")


def test_legacy_schema_is_dropped_and_rebuilt(raw_db):
    db = raw_db
    with sqlite3.connect(db) as conn:
        conn.execute(_OLD_DDL)  # 预置 434867c 之前的旧 schema

    reports = StationReports(db)

    # 列集与现行一致
    with sqlite3.connect(db) as conn:
        cols = tuple(row[1] for row in conn.execute("PRAGMA table_info(station_reports)"))
    assert "round_id" in cols
    assert "expires_at" in cols
    assert "gen_token" in cols

    # 重建后的表可正常读写(回归现场 = get_active SELECT round_id 崩)
    now = datetime.now()  # noqa: DTZ005
    reports.begin_generation(
        "sess_x", "1", "t", collected_at=now,
        expires_at=now + timedelta(days=7), title="t",
    )
    assert reports.get_active("sess_x", "1") is not None


def test_mid_schema_is_dropped_and_rebuilt(raw_db):
    """本地过渡表(有 emotion_label 无 expires_at,PRD 批产物)同判旧库。"""

    db = raw_db
    with sqlite3.connect(db) as conn:
        conn.execute(_MID_DDL)
        conn.execute(
            "INSERT INTO station_reports VALUES ('s', 'r1', 'ready', 'md', '焦虑', '2026-10-15T10:00:00')"
        )

    StationReports(db)  # 初始化即触发自检换列集(返回值无用,行为在 _init_db)

    with sqlite3.connect(db) as conn:
        cols = tuple(row[1] for row in conn.execute("PRAGMA table_info(station_reports)"))
    assert cols == _COLUMNS  # 换到现行列集


def test_current_schema_survives_reinit(raw_db):
    db = raw_db
    reports = StationReports(db)
    now = datetime.now()  # noqa: DTZ005
    reports.begin_generation(
        "sess_y", "2", "t", collected_at=now,
        expires_at=now + timedelta(days=7), title="t",
    )
    reports.finish_generation("sess_y", "2", "t", report_md="md", title="t")
    StationReports(db)  # 二次初始化(同 schema)不得 drop 已有数据
    row = reports.get_active("sess_y", "2")
    assert row is not None
    assert row["report_md"] == "md"
