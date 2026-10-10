"""TTS benchmark 埋点收口(plan §25/§27/§30)。

浏览器侧观测到的三样东西只在浏览器里存在:
    AudioContext.sampleRate · AudioBuffer.sampleRate · first source scheduled
所以前端把事件 POST 上来,由本端点代为落进与 TTS 服务同一个 JSONL ——
聚合脚本于是能在一条时间线上同时看到 :9001 / :8000 / 浏览器三段。

**只收事件,不收音频。** 请求体只允许 event 名与数值字段,PCM 一律不经过这里
(音频绝不落盘是硬红线,这条端点是它最容易被绕过的地方)。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import logger as app_logger
from app.voice import tts_bench

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="tts_bench")

router = APIRouter(prefix="/v1/tts/bench", tags=["tts-bench"])

_MAX_BATCH = 500
"""单批上限。攒批间隔 500ms,正常远到不了;上限是防刷,不是业务限制。"""


class BenchEventIn(BaseModel):
    ts_ms: float = Field(description="浏览器侧 wall-clock 毫秒")
    ev: str = Field(description="事件名,须与冻结字典一致")
    round_id: str | None = None


class BenchBatch(BaseModel):
    events: list[BenchEventIn] = Field(max_length=_MAX_BATCH)


@router.post("/events")
async def post_events(batch: BenchBatch) -> dict[str, object]:
    """收一批前端事件,原样落盘。返回 accepted 条数与埋点是否开启。

    关着时返回 accepted=0 而不是报错:前端是否开埋点不该影响正常对话。
    """
    if not tts_bench.enabled():
        return {"accepted": 0, "enabled": False, "sink": str(tts_bench.sink_path())}

    payload = [e.model_dump() for e in batch.events]
    n = tts_bench.record_frontend(payload)
    if n:
        logger.bind(event="bench_events", count=n).log("DEBUG", "bench_events")
    return {"accepted": n, "enabled": True, "sink": str(tts_bench.sink_path())}