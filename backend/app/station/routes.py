"""补给站 REST(端点单源=ws-contract「连接与会话」节):回合末自动生成+按轮取稿。

- 生成触发=Finish 归档(网关 _archive_round 调 start_auto_generate 后台起任务,
  done 照发不等待);`POST /station/report/generate` 为兜底受理+手动重生成入口
  (素材=该轮 station:input;无素材/已过期→409;有效期不可确认→503);
  生成在后台任务,持 gen_token 落库(令牌不符=旧任务被顶掉,拒绝覆盖)
- GET /station/report/latest?session_id&round_id — pending(生成中)/ ready+report_md
  +title+updated_at;过期/无记录 404
- GET /station/report/list?session_id — 本会话有效期内的报告(列表页),按生成时间降序
- 防重:pending 且 <PENDING_FRESH_S 视为在途不重复起任务;陈旧 pending(任务被杀)重新受理
- 并发:进程内 asyncio.Lock[(sid, round)] 包住「防重检查→占位→建任务」,消除非原子窗口
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import logger as app_logger
from app.memory import get_memory
from app.schema import Formulation, StationReportResponse, StationReportStatus
from app.station import planner
from app.station.reports import PENDING_FRESH_S, derive_title, get_reports

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="station")

router = APIRouter(prefix="/station", tags=["station"])

_running: set[asyncio.Task[None]] = set()
"""持引用防 GC(裸 create_task 会被回收),完成即弃。"""

_gen_locks: dict[tuple[str, str], asyncio.Lock] = {}
"""按 (session_id, round_id) 的进程内生成锁;仅防同进程并发/双击,不覆盖跨进程。"""


def _lock_for(session_id: str, round_id: str) -> asyncio.Lock:
    key = (session_id, round_id)
    lock = _gen_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _gen_locks[key] = lock
    return lock


def _age_s(updated_at: str) -> float:
    try:
        delta = datetime.now() - datetime.fromisoformat(updated_at)  # noqa: DTZ005 — 与写入同用本地时区
        return delta.total_seconds()
    except ValueError:
        return 1e9


async def start_auto_generate(session_id: str, round_id: str, material: Any) -> None:
    """回合末自动生成入口(网关 _archive_round 调):按回合键落 pending 后台起任务。

    与手动受理共用 _generate 与鲜度窗防重;素材为 StationMaterial(dataclass)。
    永不抛——归档收尾不被自动生成触发失败打断,降级由 _generate 内纪律兜底。
    """
    token = secrets.token_hex(8)
    async with _lock_for(session_id, round_id):
        row = get_reports().get_active(session_id, round_id)
        if (
            row is not None
            and row["status"] == StationReportStatus.PENDING.value
            and _age_s(str(row["updated_at"])) < PENDING_FRESH_S
        ):
            return  # 同回合鲜 pending 在途:自动触发不重复起任务
        get_reports().begin_generation(
            session_id,
            round_id,
            token,
            collected_at=material.collected_at,
            expires_at=material.deadline,
            title=_material_title(material),
        )
        task = asyncio.create_task(_generate(session_id, round_id, token, material))
        _running.add(task)
        task.add_done_callback(_running.discard)
    logger.info("station_report_accepted", session_id=session_id, round_id=round_id)


@router.post(
    "/report/generate", response_model=StationReportResponse, response_model_exclude_none=True
)
async def generate(
    session_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    round_id: str = Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$"),
) -> StationReportResponse:
    state, material = await get_memory().load_station_input(session_id, round_id)
    if state == "absent":
        raise HTTPException(
            status_code=409,
            detail="这一轮还没有可整理的素材——先完成一次梳理,再来领取你的方案书。",
        )
    if state == "unknown" or material is None or material.deadline is None:
        # 素材有效期不可确认(Redis 异常/键无 TTL):不臆测可重新生成
        raise HTTPException(
            status_code=503,
            detail="暂时无法确认这一轮素材的有效期,稍后再点开试试。",
        )
    now = datetime.now()  # noqa: DTZ005 — 本地时区
    if material.deadline <= now:
        raise HTTPException(
            status_code=409,
            detail="这一轮梳理已过有效期(归档后 7 天),重新聊聊可以为你生成新的方案。",
        )

    await start_auto_generate(session_id, round_id, material)
    return StationReportResponse(status=StationReportStatus.PENDING)


def _material_title(material: Any) -> str:
    """标题取自本次报告的素材数据(情境 · 情绪)。

    不用轮次序号:round_id 数的是 collect 入场次数(含被抢占作废、从未生成报告的入场),
    拿它当显示序号会出现「第 5 次梳理」而用户只认两轮对话。
    素材损坏时落中性备用标题(不影响受理)。"""

    try:
        f = Formulation.model_validate_json(str(material.payload["formulation"]))
    except Exception:  # noqa: BLE001
        return derive_title(None, None)
    return derive_title(f.situation, f.emotion.label)


@router.get(
    "/report/latest", response_model=StationReportResponse, response_model_exclude_none=True
)
async def latest(
    session_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    round_id: str = Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$"),
) -> StationReportResponse:
    row = get_reports().get_active(session_id, round_id)
    if row is None:
        # 无记录或已过期(过期=不可查看,不得以 200-pending 悬挂)
        raise HTTPException(status_code=404, detail="这一轮还没有生成过方案书。")
    if row["status"] == StationReportStatus.READY.value and row["report_md"]:
        return StationReportResponse(
            status=StationReportStatus.READY,
            report_md=row["report_md"],
            title=row["title"],
            updated_at=row["updated_at"],
        )
    return StationReportResponse(status=StationReportStatus.PENDING)


@router.get("/report/list")
async def list_reports(
    session_id: str = Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
) -> dict[str, Any]:
    """有效期内的报告列表;can_regenerate 三态(unknown ≠ 可用)。"""

    rows = get_reports().list_by_session(session_id)
    out: list[dict[str, Any]] = []
    for row in rows:
        state = await get_memory().probe_station_input(session_id, str(row["round_id"]))
        out.append(
            {
                "round_id": row["round_id"],
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "expires_at": row["expires_at"],
                "can_regenerate": {"ok": "yes", "absent": "no", "unknown": "unknown"}[state],
            }
        )
    return {"reports": out}


async def _generate(session_id: str, round_id: str, token: str, material: Any) -> None:
    try:
        formulation = Formulation.model_validate_json(str(material.payload["formulation"]))
    except Exception as exc:  # noqa: BLE001 — 素材损坏不炸任务:降级模板
        # H4:只记类型——pydantic 报文含 input_value(用户原文片段),落日志破脱敏红线
        logger.warning("degraded", layer="station_material", reason=type(exc).__name__)
        formulation = Formulation()
    summary = str(material.payload.get("summary") or "")
    md = await planner.generate_report(formulation, summary)
    # 条件落库:令牌不符(旧任务被顶掉)/ 已过期 → 拒绝覆盖,记 superseded
    ok = get_reports().finish_generation(
        session_id,
        round_id,
        token,
        report_md=md,
        title=derive_title(formulation.situation, formulation.emotion.label),
    )
    if ok:
        logger.info("station_report_ready", session_id=session_id, round_id=round_id, length=len(md))
    else:
        logger.warning("station_report_superseded", session_id=session_id, round_id=round_id)
