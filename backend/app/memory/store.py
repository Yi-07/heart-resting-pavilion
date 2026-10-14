"""热/温/冷记忆存储(backend-plan §2 memory 行;层介质与生命周期单源=spec §4 L7)。

- 热:当前会话上下文 {history_summary, mood_recent} → Redis TTL 30min(snapshot 优先读)
- 温:会话摘要列表(粗摘要,LLM 生成文本,非用户原文)→ Redis TTL 7 天;热亡时 snapshot 回退取最新一条
- station:input:{formulation, summary} → Redis TTL 7 天(回合末写,步骤 9 补给站懒生成素材)
- 冷:每日心情 {date, mood_label, intensity, source} → SQLite 无 TTL,同日同源 upsert 最新胜
- 治理:键 `hrp:v1:` 前缀隔离+版本号(spec §4 L7);用户查看/一键清除随 admin 通道(步骤 9)
- 降级:所有操作异常吞掉记 WARN——记忆不可用绝不杀回合;redis-py 断连自动重试下次操作
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast

import redis.asyncio as aioredis

from app import config
from app import logger as app_logger
from app.agents.state import SessionContext, Turn

_PREFIX = "hrp:v1"

_RECENT_TURNS_CAP = 20
"""热层 recent_turns 上限(ADR-005):最近 20 轮原话,30min TTL,隔天只剩摘要。"""

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="memory")


def _now_local() -> datetime:
    return datetime.now()  # noqa: DTZ005 — 每日心情按机器本地日聚合(原型单机,时区即用户时区)


def _hot_key(session_id: str) -> str:
    return f"{_PREFIX}:hot:{session_id}"


def _warm_key(session_id: str) -> str:
    return f"{_PREFIX}:warm:{session_id}"


def _station_key(session_id: str, round_id: str | None = None) -> str:
    """station:input 键。round_id=None = 旧键(升级前写入,只读用于遗留核价)；
    新键带轮次后缀:每轮 collect 一份素材,互不覆盖。"""

    if round_id is None:
        return f"{_PREFIX}:station:input:{session_id}"
    return f"{_PREFIX}:station:input:{session_id}:{round_id}"


MaterialState = Literal["ok", "absent", "unknown"]
"""素材三态:ok=可读且有效期可确定；absent=键不存在(无可整理素材/已过期)；
unknown=Redis 异常或键无 TTL(非本代码写入格式)——有效期不可确认,不得放行生成。"""


@dataclass(frozen=True)
class StationMaterial:
    """素材 + 可靠原始到期时刻 + 归档时刻。

    deadline/collected_at 由素材自身证据得出(payload collected_at、Redis 剩余 TTL),
    绝不以当前时间重新起算有效期。"""

    payload: dict[str, Any]
    deadline: datetime
    collected_at: datetime


def material_times(
    payload: dict[str, Any], pttl_s: int | None, *, now: datetime
) -> tuple[datetime, datetime] | None:
    """(deadline, collected_at)——到期时刻唯一定价处;None=不可确认。

    - payload 有 collected_at:归档时刻取它,deadline = 归档 + RETENTION;
      若 Redis PTTL 也可得,deadline 取两者较早者(绝不延长原始有效期)
    - 仅 PTTL 可得(旧格式素材):deadline = now + pttl(精确复原原始到期),
      归档时刻按 deadline - RETENTION 回推(Redis 写入即 ex=RETENTION,同锚点)
    """

    retention = timedelta(seconds=config.STATION_RETENTION_S)
    collected: datetime | None = None
    raw = payload.get("collected_at")
    if isinstance(raw, str):
        try:
            collected = datetime.fromisoformat(raw)
        except ValueError:
            collected = None
    ttl_deadline: datetime | None = None
    if pttl_s is not None and pttl_s >= 0:
        ttl_deadline = now + timedelta(seconds=pttl_s)
    if collected is not None:
        payload_deadline = collected + retention
        deadline = min(payload_deadline, ttl_deadline) if ttl_deadline else payload_deadline
        return deadline, collected
    if ttl_deadline is not None:
        return ttl_deadline, ttl_deadline - retention
    return None


class Memory:
    """Redis(热/温/station)+ SQLite(冷)三落点;每方法自带降级。"""

    def __init__(self, url: str = config.REDIS_URL, db_path: str = config.MEMORY_DB_PATH) -> None:
        self._redis = aioredis.from_url(url, decode_responses=True)
        self._db_path = db_path
        self._init_db()

    async def ping(self) -> bool:
        """Redis 连通性检查(启动提示用);失败不抛,由调用方落降级提示。"""
        try:
            return bool(await self._redis.ping())
        except Exception:  # noqa: BLE001 — 启动检查,连接失败返回 False 即可
            return False

    # ---- 冷层:每日心情(同日同源 upsert,最新胜) ----

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mood_daily (
                    date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    mood_label TEXT NOT NULL,
                    intensity REAL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (date, source)
                )
                """
            )

    async def record_mood(
        self,
        mood_label: str,
        *,
        source: str,
        intensity: float | None = None,
        session_id: str | None = None,
    ) -> None:
        """冷层 upsert,同日同源最新胜(spec §7 上报→L7 情绪趋势;研判复核 source=研判)。
        带 session_id 时顺带刷热层 mood_recent(喂 snapshot/Live2D 语境)。"""

        def _cold_write() -> None:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO mood_daily (date, source, mood_label, intensity, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (date, source) DO UPDATE SET
                        mood_label = excluded.mood_label,
                        intensity = excluded.intensity,
                        updated_at = excluded.updated_at
                    """,
                    (
                        _now_local().date().isoformat(),
                        source,
                        mood_label,
                        intensity,
                        _now_local().isoformat(timespec="seconds"),
                    ),
                )

        try:
            _cold_write()
        except Exception as exc:  # noqa: BLE001 — 记忆降级:冷层失败不杀回合
            logger.warning("memory_degraded", layer="cold", reason=str(exc)[:120])
        if session_id is not None:
            await self._push_mood_recent(session_id, mood_label)

    def recent_moods(self, days: int = 7) -> list[dict[str, Any]]:
        """冷层情绪趋势查看(治理/后续 admin 用;date 降序)。"""

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT date, source, mood_label, intensity FROM mood_daily "
                "ORDER BY date DESC, updated_at DESC LIMIT ?",
                (days,),
            ).fetchall()
        return [
            {"date": r[0], "source": r[1], "mood_label": r[2], "intensity": r[3]}
            for r in rows
        ]

    async def clear_all(self) -> dict[str, int]:
        """治理一键清除(admin/clear_memory):Redis 全部 hrp:v1 键 + 冷层心情表。

        刻意**不降级**——治理失败必须让用户知道(路由层 503 上报),
        与其余记忆方法「异常吞掉、保证回合进行」的默认行为相反,属有意例外。
        """

        cleared = {"redis_keys": 0, "mood_rows": 0}
        keys = [key async for key in self._redis.scan_iter(f"{_PREFIX}:*")]
        if keys:
            cleared["redis_keys"] = int(await self._redis.delete(*keys))
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM mood_daily")
            cleared["mood_rows"] = cur.rowcount or 0
        return cleared

    # ---- 热/温层 ----

    async def snapshot(self, session_id: str) -> SessionContext:
        """读 SessionContext:优先热层;热亡回退温层最新摘要(spec §4 L7)。"""

        try:
            raw = await self._redis.get(_hot_key(session_id))
            if raw is not None:
                data = json.loads(raw)
                return SessionContext(
                    history_summary=data.get("history_summary"),
                    mood_recent=list(data.get("mood_recent", [])),
                    recent_turns=[
                        Turn(role=t["role"], text=t["text"])
                        for t in data.get("recent_turns", [])
                        if isinstance(t, dict) and t.get("role") in ("user", "assistant")
                    ],
                )
            warm = await self._redis.lrange(_warm_key(session_id), -1, -1)
            if warm:
                # decode_responses=True 运行时为 str;client 泛型标 bytes|str,收窄
                return SessionContext(history_summary=cast(str, warm[0]), mood_recent=[])
        except Exception as exc:  # noqa: BLE001 — 记忆降级:读失败返回空档
            logger.warning("memory_degraded", layer="snapshot", reason=str(exc)[:120])
        return SessionContext()

    async def append_turn(self, session_id: str, role: str, text: str) -> None:
        """热层追加一轮原话(ADR-001/005:重连重建 turns + 回放帧数据源)。

        user 轮=user_input 即追加;assistant 轮=图事件落定后追加(拼合全文)。
        原话只活热层 30min(隐私线 §9.4);失败不杀回合。
        """

        try:
            raw = await self._redis.get(_hot_key(session_id))
            if raw is not None:
                data = json.loads(raw)
            else:
                # 热层过期冷启动(F3,与 H1 同族):温层最新摘要播种进新热层键——
                # 否则键里只有 turns,快照走热层路径丢 history_summary,跨天续话上下文断裂
                warm = await self._redis.lrange(_warm_key(session_id), -1, -1)
                data = {"history_summary": cast(str | None, warm[0]) if warm else None}
            turns = list(data.get("recent_turns", []))
            turns.append({"role": role, "text": text})
            data["recent_turns"] = turns[-_RECENT_TURNS_CAP:]
            await self._write_hot(session_id, data)
        except Exception as exc:  # noqa: BLE001 — 记忆降级:轮次存储失败不影响对话
            logger.warning("memory_degraded", layer="hot_turn", reason=str(exc)[:120])

    async def save_round_summary(self, session_id: str, summary: str) -> None:
        """温层追加本回合摘要 + 热层 history_summary 刷新(回合末,backend-plan §3.3)。"""

        if not summary:
            return
        try:
            await self._redis.rpush(_warm_key(session_id), summary)
            await self._redis.expire(_warm_key(session_id), config.MEMORY_WARM_TTL_S)
            await self._refresh_hot(session_id, history_summary=summary)
        except Exception as exc:  # noqa: BLE001 — 记忆降级:写失败不杀回合
            logger.warning("memory_degraded", layer="warm", reason=str(exc)[:120])

    async def save_station_input(
        self,
        session_id: str,
        round_id: str,
        formulation_json: str,
        summary: str,
        collected_at: str | None = None,
    ) -> bool:
        """station:input 懒生成素材(回合末写;步骤 9 补给站消费)。

        带轮次键 + collected_at(归档时刻,报告有效期锚点)。返回写成功与否
        (供 Done.station_ready;Redis 失败记 memory_degraded 并回 false,不谎报)。"""

        payload = json.dumps(
            {
                "formulation": formulation_json,
                "summary": summary,
                "collected_at": collected_at or _now_local().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        )
        try:
            await self._redis.set(
                _station_key(session_id, round_id), payload, ex=config.MEMORY_WARM_TTL_S
            )
            return True
        except Exception as exc:  # noqa: BLE001 — 记忆降级:写失败不杀回合
            logger.warning("memory_degraded", layer="station", reason=str(exc)[:120])
            return False

    async def load_station_input(
        self, session_id: str, round_id: str
    ) -> tuple[MaterialState, StationMaterial | None]:
        """读本轮素材 + 可靠原始到期时刻(GET+PTTL 一次完成)。

        - ok:payload 可解析且到期时刻可由素材自身证据确定
        - absent:键不存在(无可整理素材或已过期)
        - unknown:Redis 异常,或键无 TTL(非本代码写入格式)——不得放行生成
        """

        try:
            key = _station_key(session_id, round_id)
            raw = await self._redis.get(key)
            pttl = await self._redis.pttl(key)
            if raw is None:
                return "absent", None
            payload = json.loads(str(raw))
            if not isinstance(payload, dict):
                return "absent", None
            if not isinstance(pttl, int) or pttl < 0:
                # -1 = 键无过期时间:非本代码写入格式,有效期不可确认
                return "unknown", None
            times = material_times(payload, pttl // 1000, now=_now_local())
            if times is None:
                return "unknown", None
            deadline, collected_at = times
            return "ok", StationMaterial(payload=payload, deadline=deadline, collected_at=collected_at)
        except Exception as exc:  # noqa: BLE001 — 记忆降级:读失败按不可确认处理
            logger.warning("memory_degraded", layer="station_read", reason=type(exc).__name__)
            return "unknown", None

    async def probe_station_input(self, session_id: str, round_id: str) -> MaterialState:
        """素材存在性三态(列表页 can_regenerate 用;unknown ≠ 可用)。"""

        try:
            raw = await self._redis.get(_station_key(session_id, round_id))
            if raw is None:
                return "absent"
            pttl = await self._redis.pttl(_station_key(session_id, round_id))
            if not isinstance(pttl, int) or pttl < 0:
                return "unknown"
            return "ok"
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_degraded", layer="station_probe", reason=type(exc).__name__)
            return "unknown"

    async def legacy_station_deadline(self, session_id: str) -> tuple[MaterialState, datetime | None]:
        """遗留核价:旧键(无轮次后缀)的原始到期时刻。

        ("ok", now+pttl)=旧素材仍在,精确复原 archive+7d；
        ("absent", None)=键已消亡或无 TTL,无法核验；
        ("unknown", None)=Redis 不可达(调用方应保持未定价,不猜不删)。"""

        try:
            raw = await self._redis.get(_station_key(session_id))
            if raw is None:
                return "absent", None
            pttl = await self._redis.pttl(_station_key(session_id))
            if not isinstance(pttl, int) or pttl < 0:
                return "absent", None
            return "ok", _now_local() + timedelta(seconds=pttl // 1000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_degraded", layer="station_legacy", reason=type(exc).__name__)
            return "unknown", None

    # ---- 内部 ----

    async def _push_mood_recent(self, session_id: str, mood_label: str) -> None:
        try:
            data = await self._read_hot(session_id)
            moods = list(data.get("mood_recent", []))
            moods.append(mood_label)
            await self._write_hot(
                session_id,
                {
                    "history_summary": data.get("history_summary"),
                    "mood_recent": moods[-config.MOOD_RECENT_CAP :],
                    # 整键覆写必须带全热层其余字段(H1):丢 recent_turns 会清空
                    # 回放/重建数据源(ADR-001/005),第二回合起形同虚设
                    "recent_turns": data.get("recent_turns", []),
                },
            )
        except Exception as exc:  # noqa: BLE001 — 记忆降级:热层失败不影响冷层已写
            logger.warning("memory_degraded", layer="hot_mood", reason=str(exc)[:120])

    async def _refresh_hot(self, session_id: str, *, history_summary: str) -> None:
        data = await self._read_hot(session_id)
        await self._write_hot(
            session_id,
            {
                "history_summary": history_summary,
                "mood_recent": data.get("mood_recent", []),
                "recent_turns": data.get("recent_turns", []),  # H1:覆写须带全热层
            },
        )

    async def _read_hot(self, session_id: str) -> dict[str, Any]:
        raw = await self._redis.get(_hot_key(session_id))
        return json.loads(raw) if raw is not None else {}

    async def _write_hot(self, session_id: str, data: dict[str, Any]) -> None:
        await self._redis.set(
            _hot_key(session_id), json.dumps(data, ensure_ascii=False), ex=config.MEMORY_HOT_TTL_S
        )
