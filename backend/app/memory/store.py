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
from datetime import datetime
from typing import Any, cast

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


def _station_key(session_id: str) -> str:
    return f"{_PREFIX}:station:input:{session_id}"


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
        """治理一键清除(admin/clear_memory):Redis 全部 hrp:v1 键 + 冷层心情表
        + 语义记忆库(spec L7「语义」层;治理不降级例外覆盖语义层)。

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
        # 语义层由调用方汇入(admin 路由持 get_semantic);本方法保持 Redis/SQLite 职责
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
        self, session_id: str, formulation_json: str, summary: str
    ) -> None:
        """station:input 懒生成素材(回合末写;步骤 9 补给站消费)。"""

        payload = json.dumps({"formulation": formulation_json, "summary": summary}, ensure_ascii=False)
        try:
            await self._redis.set(
                _station_key(session_id), payload, ex=config.MEMORY_WARM_TTL_S
            )
        except Exception as exc:  # noqa: BLE001 — 记忆降级:写失败不杀回合
            logger.warning("memory_degraded", layer="station", reason=str(exc)[:120])

    async def load_station_input(self, session_id: str) -> dict[str, Any] | None:
        """读 station:input(步骤 9 用;先立读口防重复设计)。"""

        try:
            raw = await self._redis.get(_station_key(session_id))
            return json.loads(raw) if raw is not None else None
        except Exception as exc:  # noqa: BLE001 — 记忆降级:读失败当无素材
            logger.warning("memory_degraded", layer="station_read", reason=str(exc)[:120])
            return None

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
