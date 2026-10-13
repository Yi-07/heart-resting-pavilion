"""方案书存取(backend-plan §2 station 行):SQLite reports 表,(session_id, round_id)
主键,历史保留——同会话每回合一份(方案书裁定,collect 链路重构)。

- upsert 按回合键写入;同回合重复生成覆盖该回合旧稿(回合内最新胜)
- get_latest 取该会话 round_id 最大的一行(前端轮询语义不变:pending|ready)
- status:pending(生成中)| ready(携 report_md);陈旧 pending 由路由层按鲜度重受理
- clear_all 挂 admin/clear_memory(方案书=用户数据衍生物,治理与记忆同清)
- 单行小表,同步 SQLite 读写即可,无并发热点
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from app import config
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="station")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")  # noqa: DTZ005 — 单机原型,本地时区


class StationReports:
    """reports 表读写;方法不自吞异常(调用方=REST 路由,失败如实上报)。"""

    def __init__(self, db_path: str = config.STATION_DB_PATH) -> None:
        self._db_path = db_path
        self._init_db()

    # 现行 schema 列集(换 schema 改这里,自检据此判旧库)
    _COLUMNS = ("session_id", "round_id", "status", "report_md", "emotion_label", "updated_at")

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            # 原型无迁移框架:旧库列集不符即 drop 重建(方案书可再生成,drop 安全)。
            # 不自检的话 CREATE TABLE IF NOT EXISTS 会保留旧表,新代码 SELECT 撞
            # no such column(434867c 主键改 (session_id, round_id) 时的真实回归)。
            existing = tuple(row[1] for row in conn.execute("PRAGMA table_info(station_reports)"))
            if existing and existing != self._COLUMNS:
                logger.warning("station_reports_schema_mismatch", found=len(existing))
                conn.execute("DROP TABLE station_reports")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS station_reports (
                    session_id TEXT NOT NULL,
                    round_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    report_md TEXT,
                    emotion_label TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, round_id)
                )
                """
            )

    def upsert(
        self,
        session_id: str,
        status: str,
        report_md: str | None = None,
        *,
        round_id: str = "0",
        emotion_label: str | None = None,
    ) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO station_reports
                    (session_id, round_id, status, report_md, emotion_label, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, round_id) DO UPDATE SET
                    status = excluded.status,
                    report_md = excluded.report_md,
                    emotion_label = excluded.emotion_label,
                    updated_at = excluded.updated_at
                """,
                (session_id, round_id, status, report_md, emotion_label, _now_iso()),
            )

    def get_latest(self, session_id: str) -> dict[str, Any] | None:
        """该会话最新回合的方案书行;无记录返回 None。"""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT session_id, round_id, status, report_md, emotion_label, updated_at "
                "FROM station_reports WHERE session_id = ? "
                "ORDER BY round_id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "round_id": row[1],
            "status": row[2],
            "report_md": row[3],
            "emotion_label": row[4],
            "updated_at": row[5],
        }

    def clear_all(self) -> int:
        """治理清除(admin/clear_memory);返回删除行数。"""

        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM station_reports")
            return cur.rowcount


_reports: StationReports | None = None


def get_reports() -> StationReports:
    global _reports
    if _reports is None:
        _reports = StationReports()
    return _reports


def reset_reports(reports: StationReports | None = None) -> None:
    """测试隔离:换实例或清空。"""

    global _reports
    _reports = reports
