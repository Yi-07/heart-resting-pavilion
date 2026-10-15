"""留言墙存储。

留言墙与普通会话记忆使用不同的表和清理入口；正文只用于用户再次查看，
日志中不记录正文。七日清理通过 created_at 巡检实现，不依赖时区数据库包。
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app import config

RETENTION = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WallStore:
    def __init__(self, db_path: str = config.WALL_DB_PATH) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS wall_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    reply TEXT,
                    status TEXT NOT NULL,
                    unread INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_wall_session ON wall_messages(session_id, created_at)")

    def add(self, session_id: str, text: str) -> dict[str, Any]:
        message_id = f"wall_{uuid.uuid4().hex[:12]}"
        now = _now().isoformat(timespec="seconds")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO wall_messages (id, session_id, text, status, unread, created_at, updated_at) VALUES (?, ?, ?, 'pending', 0, ?, ?)",
                (message_id, session_id, text, now, now),
            )
        return {"id": message_id, "session_id": session_id, "text": text, "reply": None, "status": "pending", "unread": False, "created_at": now}

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, text, reply, status, unread, created_at FROM wall_messages WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def unread_count(self, session_id: str) -> int:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM wall_messages WHERE session_id = ? AND unread = 1", (session_id,)).fetchone()
        return int(row[0] if row else 0)

    def mark_read(self, session_id: str) -> int:
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("UPDATE wall_messages SET unread = 0 WHERE session_id = ? AND unread = 1", (session_id,))
            return cur.rowcount

    def pending(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT id, session_id, text, created_at FROM wall_messages WHERE status = 'pending' ORDER BY created_at ASC").fetchall()
        return [{"id": r[0], "session_id": r[1], "text": r[2], "created_at": r[3]} for r in rows]

    def reply(self, message_id: str, text: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("UPDATE wall_messages SET reply = ?, status = 'replied', unread = 1, updated_at = ? WHERE id = ?", (text, _now().isoformat(timespec="seconds"), message_id))

    def fail(self, message_id: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("UPDATE wall_messages SET status = 'failed', updated_at = ? WHERE id = ?", (_now().isoformat(timespec="seconds"), message_id))

    def clear(self, session_id: str) -> int:
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM wall_messages WHERE session_id = ?", (session_id,))
            return cur.rowcount

    def cleanup(self) -> int:
        cutoff = (_now() - RETENTION).isoformat(timespec="seconds")
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM wall_messages WHERE created_at < ?", (cutoff,))
            return cur.rowcount

    @staticmethod
    def _row(row: tuple[Any, ...]) -> dict[str, Any]:
        return {"id": row[0], "text": row[1], "reply": row[2], "status": row[3], "unread": bool(row[4]), "created_at": row[5]}


_store: WallStore | None = None


def get_store() -> WallStore:
    global _store
    if _store is None:
        _store = WallStore()
    return _store


def reset_store(store: WallStore | None = None) -> None:
    global _store
    _store = store
