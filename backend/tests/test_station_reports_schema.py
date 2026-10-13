"""station reports 旧库自检重建钉测(任务线 collect-smooth-flow T0)。

回归现场:434867c 把 reports 表主键改 (session_id, round_id),CREATE TABLE
IF NOT EXISTS 对已存在的旧表(session_id 单列主键)不做迁移,真环境 SELECT
round_id 撞 no such column → /station/report/latest 500。测试库全新不暴露,
需以旧 schema 预建表再初始化来钉住。
"""

import sqlite3

from app.station.reports import StationReports

_OLD_DDL = """
CREATE TABLE station_reports (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    report_md TEXT,
    updated_at TEXT NOT NULL
)
"""


def test_legacy_schema_is_dropped_and_rebuilt(tmp_path):
    db = str(tmp_path / "station.db")
    with sqlite3.connect(db) as conn:
        conn.execute(_OLD_DDL)  # 预置 434867c 之前的旧 schema

    reports = StationReports(db)

    # 列集与现行一致,旧行为 drop(0 行无保留价值;方案书可再生成)
    with sqlite3.connect(db) as conn:
        cols = tuple(row[1] for row in conn.execute("PRAGMA table_info(station_reports)"))
    assert "round_id" in cols
    assert "emotion_label" in cols

    # 重建后的表可正常读写(回归现场 = get_latest SELECT round_id 崩)
    reports.upsert("sess_x", "pending", round_id="r1", emotion_label="低落")
    row = reports.get_latest("sess_x")
    assert row is not None
    assert row["round_id"] == "r1"


def test_current_schema_survives_reinit(tmp_path):
    db = str(tmp_path / "station.db")
    reports = StationReports(db)
    reports.upsert("sess_y", "ready", "md", round_id="r2")
    StationReports(db)  # 二次初始化(同 schema)不得 drop 已有数据
    row = reports.get_latest("sess_y")
    assert row is not None
    assert row["report_md"] == "md"
