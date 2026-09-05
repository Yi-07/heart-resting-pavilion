"""方案书存取(backend-plan §2 station 行):SQLite reports 表,每会话只留最新一份。

- session_id 主键 upsert,重复生成覆盖旧稿(最新胜)
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

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS station_reports (
                    session_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    report_md TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert(self, session_id: str, status: str, report_md: str | None = None) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO station_reports (session_id, status, report_md, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    status = excluded.status,
                    report_md = excluded.report_md,
                    updated_at = excluded.updated_at
                """,
                (session_id, status, report_md, _now_iso()),
            )

    def get(self, session_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT session_id, status, report_md, updated_at "
                "FROM station_reports WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {"session_id": row[0], "status": row[1], "report_md": row[2], "updated_at": row[3]}

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
