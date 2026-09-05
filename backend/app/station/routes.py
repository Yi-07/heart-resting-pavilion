"""补给站 REST(端点单源=ws-contract §1):点击触发懒生成,轮询取稿。

- POST /station/report/generate?session_id= — 受理即返 pending;素材=回合末
  station:input(Redis;危机回合不写→409 引导先完成一次梳理);生成在后台任务
- GET /station/report/latest?session_id= — pending(生成中)/ ready+report_md;
  无记录 404。响应两端点同形(ws-contract §1)
- 防重:pending 且 <5min 视为在途不重复起任务;陈旧 pending(任务被杀)重新受理
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import logger as app_logger
from app.memory import get_memory
from app.schema import Formulation, StationReportResponse, StationReportStatus
from app.station import planner
from app.station.reports import get_reports

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="station")

router = APIRouter(prefix="/station", tags=["station"])

_running: set[asyncio.Task[None]] = set()
"""持引用防 GC(裸 create_task 会被回收),完成即弃。"""

_PENDING_FRESH_S = 300.0
"""pending 鲜度窗:窗内在途不重复受理;超窗视为任务已死,重新生成。"""


def _age_s(updated_at: str) -> float:
    try:
        delta = datetime.now() - datetime.fromisoformat(updated_at)  # noqa: DTZ005 — 与写入同用本地时区
        return delta.total_seconds()
    except ValueError:
        return 1e9


@router.post(
    "/report/generate", response_model=StationReportResponse, response_model_exclude_none=True
)
async def generate(session_id: str = Query(min_length=1)) -> StationReportResponse:
    material = await get_memory().load_station_input(session_id)
    if material is None:
        raise HTTPException(
            status_code=409,
            detail="这次对话还没有可整理的素材——先完成一次梳理,再来领取你的方案书。",
        )
    row = get_reports().get(session_id)
    if (
        row is not None
        and row["status"] == StationReportStatus.PENDING.value
        and _age_s(str(row["updated_at"])) < _PENDING_FRESH_S
    ):
        return StationReportResponse(status=StationReportStatus.PENDING)
    get_reports().upsert(session_id, StationReportStatus.PENDING.value)
    task = asyncio.create_task(_generate(session_id, material))
    _running.add(task)
    task.add_done_callback(_running.discard)
    logger.info("station_report_accepted", session_id=session_id)
    return StationReportResponse(status=StationReportStatus.PENDING)


@router.get(
    "/report/latest", response_model=StationReportResponse, response_model_exclude_none=True
)
async def latest(session_id: str = Query(min_length=1)) -> StationReportResponse:
    row = get_reports().get(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="本会话还没有生成过方案书。")
    if row["status"] == StationReportStatus.READY.value:
        return StationReportResponse(status=StationReportStatus.READY, report_md=row["report_md"])
    return StationReportResponse(status=StationReportStatus.PENDING)


async def _generate(session_id: str, material: dict[str, Any]) -> None:
    try:
        formulation = Formulation.model_validate_json(str(material["formulation"]))
    except Exception as exc:  # noqa: BLE001 — 素材损坏不炸任务:降级模板
        logger.warning("degraded", layer="station_material", reason=str(exc)[:120])
        formulation = Formulation()
    summary = str(material.get("summary") or "")
    md = await planner.generate_report(formulation, summary)
    get_reports().upsert(session_id, StationReportStatus.READY.value, md)
    logger.info("station_report_ready", session_id=session_id, length=len(md))
