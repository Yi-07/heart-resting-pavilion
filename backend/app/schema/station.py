"""契约类型——补给站 REST 响应(ws-contract §1)。

generate 受理即返 pending;latest 轮询,ready 携 report_md(md 正文,前端预览/导出)。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class StationReportStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"


class StationReportResponse(BaseModel):
    status: StationReportStatus
    report_md: str | None = None  # 仅 ready 返回
