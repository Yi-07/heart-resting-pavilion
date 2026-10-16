"""方案书存取 + 轮次序号(backend-plan「station」行;端点单源=ws-contract「连接与会话」节)。

- station_reports:每 (session_id, round_id) 一行——主键含轮次,一轮一份互不覆盖
- 有效期:expires_at = collected_at + config.STATION_RETENTION_S(自 collect 归档起算,
  重新生成不刷新);expires_at IS NULL = 升级遗留行尚未定价(查询一律按不可用处理,
  待启动时核价,GC 不物理删除——不猜、不误删)
- round_seq:轮次高水位(session 级);无 TTL、GC 不删、治理清除不重置(D8:
  防残留内存态旧链接指向同号新报告)
- 清理:delete_expired 物理删除;查询侧 get_active/list_by_session 同步过滤(双保险)
- clear_all 挂 admin/clear_memory(方案书=用户数据衍生物,治理与记忆同清;不动 round_seq)
- 单行小表,同步 SQLite 读写即可,无并发热点;next_round_id 用 BEGIN IMMEDIATE 保证原子
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from app import config
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="station")

PENDING_FRESH_S = 300.0
"""pending 鲜度窗:窗内在途不重复受理、GC 不删;超窗视为任务已死。"""

LegacyProbe = Callable[[str], Awaitable["tuple[str, datetime | None]"]]
"""遗留行核价探针(async):session_id → ("ok", deadline) | ("absent", None) | ("unknown", None)。"""

MaterialLoader = Callable[[str, str], Awaitable["tuple[str, Any]"]]
"""素材加载器(async):(session_id, round_id) → (state, StationMaterial | None)。"""

_LEGACY_TITLE_MARK = "次梳理"

# 现行 schema 列集(换 schema 改这里,自检据此判旧库;列序与 CREATE TABLE 一致)
_COLUMNS = (
    "session_id", "round_id", "status", "report_md", "title",
    "collected_at", "created_at", "updated_at", "expires_at", "gen_token",
)


def derive_title(situation: str | None, emotion_label: str | None) -> str:
    """报告标题：取自报告自身数据（情境 + 情绪），不用轮次序号/自增 ID。

    - 情境截到 16 字（列表行宽），去首尾标点
    - 情绪缺失 → 不出分隔符；情境也缺失 → 中性备用标题
    """

    sit = (situation or "").strip()
    sit = sit.strip("。").strip(".").strip("!").strip("！").strip("？").strip("?").strip("，")
    sit = sit.strip("、").strip(";").strip("；").strip(":").strip("：").strip(" ")
    if len(sit) > 16:
        sit = f"{sit[:16]}…"
    emo = (emotion_label or "").strip()
    if sit and emo:
        return f"{sit} · {emo}"
    if sit:
        return sit
    if emo:
        return emo
    return "这一次的梳理"


def _is_legacy_title(title: str | None) -> bool:
    """旧式标题「第 N 次梳理 · 情绪」（按轮次序号命名，需重算）。"""

    return isinstance(title, str) and title.startswith("第 ") and _LEGACY_TITLE_MARK in title

_LEGACY_ROUND_ID = "legacy"
_LEGACY_TITLE = "早期方案 · 轮次未知"


def _now() -> datetime:
    return datetime.now()  # noqa: DTZ005 — 单机原型,本地时区(与 _age_s 同基准)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class StationReports:
    """reports/round_seq 两表读写;方法不自吞异常(调用方=REST 路由/GC,失败如实上报)，
    唯二例外:next_round_id 与 refine_legacy_expiry——它们必须降级(分配失败/Redis
    不可达时由调用方按显式失败态处理，不能拖死启动链路)。"""

    def __init__(self, db_path: str = config.STATION_DB_PATH) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            # 原型无迁移框架:旧库列集不符即 drop 重建(方案书可再生成,drop 安全)。
            # 不自检的话 CREATE TABLE IF NOT EXISTS 会保留旧表,新代码 SELECT 撞
            # no such column(434867c 主键改 (session_id, round_id) 时的真实回归;
            # PR4 换 title/expires_at/gen_token 列集同理,本地旧 emotion_label 表也判旧)。
            existing = tuple(str(r[1]) for r in conn.execute("PRAGMA table_info(station_reports)"))
            if existing and existing != _COLUMNS:
                logger.warning("station_reports_schema_mismatch", found=len(existing))
                conn.execute("DROP TABLE station_reports")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS station_reports (
                    session_id   TEXT NOT NULL,
                    round_id     TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    report_md    TEXT,
                    title        TEXT,
                    collected_at TEXT,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    expires_at   TEXT,
                    gen_token    TEXT,
                    PRIMARY KEY (session_id, round_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_expiry "
                "ON station_reports (expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_session "
                "ON station_reports (session_id, expires_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS round_seq (
                    session_id TEXT PRIMARY KEY,
                    next       INTEGER NOT NULL
                )
                """
            )
            if self._is_legacy(conn):
                self._rebuild_legacy(conn)

    @staticmethod
    def _is_legacy(conn: sqlite3.Connection) -> bool:
        """旧表判定:存在 station_reports 但无 round_id 列(旧主键=session_id 单列)。"""

        cols = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(station_reports)").fetchall()
        }
        return bool(cols) and "round_id" not in cols

    def _rebuild_legacy(self, conn: sqlite3.Connection) -> None:
        """旧表升 v2:旧行以 round_id='legacy' 迁入(不伪造轮次)；
        collected_at/created_at/updated_at 取旧 updated_at(唯一可得时间)，
        expires_at 置 NULL(未定价)——由 refine_legacy_expiry 启动时核价。"""

        conn.execute("DROP TABLE IF EXISTS station_reports_v2")
        conn.execute(
            """
            CREATE TABLE station_reports_v2 (
                session_id   TEXT NOT NULL,
                round_id     TEXT NOT NULL,
                status       TEXT NOT NULL,
                report_md    TEXT,
                title        TEXT,
                collected_at TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                expires_at   TEXT,
                gen_token    TEXT,
                PRIMARY KEY (session_id, round_id)
            )
            """
        )
        conn.execute(
            f"""
            INSERT OR IGNORE INTO station_reports_v2
                (session_id, round_id, status, report_md, title,
                 collected_at, created_at, updated_at, expires_at, gen_token)
            SELECT session_id, '{_LEGACY_ROUND_ID}', status, report_md, '{_LEGACY_TITLE}',
                   updated_at, updated_at, updated_at, NULL, NULL
            FROM station_reports
            """
        )
        conn.execute("DROP TABLE station_reports")
        conn.execute("ALTER TABLE station_reports_v2 RENAME TO station_reports")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_expiry ON station_reports (expires_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_session "
            "ON station_reports (session_id, expires_at DESC)"
        )
        logger.warning("station_legacy_migrated", title=_LEGACY_TITLE)

    # ---- 轮次高水位 ----

    def next_round_id(self, session_id: str) -> str | None:
        """分配本轮 round_id(session 级单调)。SQLite 不可用返 None(调用方不得伪造编号)。"""

        conn = sqlite3.connect(self._db_path, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT next FROM round_seq WHERE session_id = ?", (session_id,)
            ).fetchone()
            nxt = (int(row[0]) if row is not None else 0) + 1
            conn.execute(
                "INSERT INTO round_seq (session_id, next) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET next = excluded.next",
                (session_id, nxt),
            )
            conn.execute("COMMIT")
            return str(nxt)
        except Exception as exc:  # noqa: BLE001 — 分配失败必须降级:整轮不产素材,不猜编号
            logger.warning("round_id_alloc_failed", reason=type(exc).__name__)
            return None
        finally:
            conn.close()

    # ---- 生成生命周期 ----

    def begin_generation(
        self,
        session_id: str,
        round_id: str,
        token: str,
        *,
        collected_at: datetime,
        expires_at: datetime,
        title: str,
    ) -> None:
        """受理即占位:新行插 pending;已有行(ready)转 pending 且**保留 report_md**，
        collected_at/expires_at 沿用旧值(绝不以本次受理重新起算有效期)。"""

        now = _now_iso()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO station_reports
                    (session_id, round_id, status, report_md, title,
                     collected_at, created_at, updated_at, expires_at, gen_token)
                VALUES (?, ?, 'pending', NULL, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, round_id) DO UPDATE SET
                    status = 'pending',
                    title = excluded.title,
                    updated_at = excluded.updated_at,
                    gen_token = excluded.gen_token,
                    collected_at = COALESCE(station_reports.collected_at, excluded.collected_at),
                    expires_at = COALESCE(station_reports.expires_at, excluded.expires_at)
                """,
                (
                    session_id,
                    round_id,
                    title,
                    _iso(collected_at),
                    now,
                    now,
                    _iso(expires_at),
                    token,
                ),
            )

    def finish_generation(
        self,
        session_id: str,
        round_id: str,
        token: str,
        *,
        report_md: str,
        title: str,
    ) -> bool:
        """条件落库:令牌不符(旧任务被顶掉)或已过期 → 拒绝写入。

        返回是否写入;调用方据此记 station_report_superseded。"""

        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                """
                UPDATE station_reports
                   SET status = 'ready', report_md = ?, title = ?, updated_at = ?,
                       gen_token = NULL
                 WHERE session_id = ? AND round_id = ? AND gen_token = ?
                   AND expires_at IS NOT NULL AND expires_at > ?
                """,
                (report_md, title, _now_iso(), session_id, round_id, token, _now_iso()),
            )
            return (cur.rowcount or 0) == 1

    # ---- 查询(过期拦截=第一道清理) ----

    def get_active(self, session_id: str, round_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT session_id, round_id, status, report_md, title, "
                "collected_at, created_at, updated_at, expires_at, gen_token "
                "FROM station_reports "
                "WHERE session_id = ? AND round_id = ? "
                "AND expires_at IS NOT NULL AND expires_at > ?",
                (session_id, round_id, _now_iso()),
            ).fetchone()
        return self._row(row)

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """有效报告(未过期),生成时间降序;列表页与历史链接寻址共用。"""

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT session_id, round_id, status, report_md, title, "
                "collected_at, created_at, updated_at, expires_at, gen_token "
                "FROM station_reports "
                "WHERE session_id = ? "
                "AND expires_at IS NOT NULL AND expires_at > ? "
                "ORDER BY created_at DESC",
                (session_id, _now_iso()),
            ).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]

    @staticmethod
    def _row(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "session_id": row[0],
            "round_id": row[1],
            "status": row[2],
            "report_md": row[3],
            "title": row[4],
            "collected_at": row[5],
            "created_at": row[6],
            "updated_at": row[7],
            "expires_at": row[8],
            "gen_token": row[9],
        }

    # ---- 清理 ----

    def delete_expired(self) -> int:
        """物理删除已过期行;鲜 pending(生成在途)不删。返回删除行数。

        expires_at IS NULL(遗留未定价)不删——等下次启动 refine_legacy_expiry 核价。"""

        cutoff = _iso(_now() - timedelta(seconds=PENDING_FRESH_S))
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "DELETE FROM station_reports "
                "WHERE expires_at IS NOT NULL AND expires_at <= ? "
                "AND (status = 'ready' OR updated_at < ?)",
                (_now_iso(), cutoff),
            )
            return cur.rowcount or 0

    async def refine_legacy_expiry(self, probe: LegacyProbe) -> dict[str, int]:
        """启动核价:给 expires_at IS NULL 的遗留行定有效期。

        - probe → ("ok", deadline):写原始到期时刻(旧素材 Redis TTL 复原 archive+7d)
        - probe → ("absent", None):无法核验 → 置为当前时刻(保守,随即被清理)
        - probe → ("unknown", None):Redis 不可达 → 保持 NULL,不猜不删,下次启动重试
        """

        counts = {"priced": 0, "expired": 0, "unknown": 0}
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT session_id FROM station_reports WHERE expires_at IS NULL"
            ).fetchall()
            for (sid,) in rows:
                state, deadline = await probe(str(sid))
                if state == "ok" and deadline is not None:
                    value, bucket = _iso(deadline), "priced"
                elif state == "absent":
                    value, bucket = _now_iso(), "expired"
                else:
                    counts["unknown"] += 1
                    continue
                conn.execute(
                    "UPDATE station_reports SET expires_at = ? "
                    "WHERE session_id = ? AND round_id = ?",
                    (value, str(sid), _LEGACY_ROUND_ID),
                )
                counts[bucket] += 1
        return counts

    async def backfill_legacy_titles(self, load_material: MaterialLoader) -> dict[str, int]:
        """启动时把旧式标题（「第 N 次梳理」）重算为数据驱动标题。

        素材可得 → 用其 formulation 推导；不可得 → 中性备用标题。
        更改只查 `_is_legacy_title` 命中的行，不动正文、不删行。"""

        counts = {"retitled": 0, "fallback": 0}
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT session_id, round_id, title FROM station_reports"
            ).fetchall()
            for sid, rid, title in rows:
                if not _is_legacy_title(str(title)):
                    continue
                new_title: str | None = None
                try:
                    state, material = await load_material(str(sid), str(rid))
                    if state == "ok" and material is not None:
                        from app.schema import Formulation

                        f = Formulation.model_validate_json(str(material.payload["formulation"]))
                        new_title = derive_title(f.situation, f.emotion.label)
                except Exception:  # noqa: BLE001 — 推导失败随备用标题
                    new_title = None
                bucket = "retitled"
                if new_title is None:
                    new_title, bucket = "这一次的梳理", "fallback"
                conn.execute(
                    "UPDATE station_reports SET title = ? WHERE session_id = ? AND round_id = ?",
                    (new_title, str(sid), str(rid)),
                )
                counts[bucket] += 1
        return counts

    def clear_all(self) -> int:
        """治理清除(admin/clear_memory);返回删除行数。

        刻意**不清 round_seq**(D8):治理清除不重置轮次高水位——否则残留的旧聊天
        链接(活在前端内存 chat.msgs)会指向同号新报告。刷新后身份由服务端重发，
        新 session 自然从 1 计。"""

        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM station_reports")
            return cur.rowcount or 0


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
