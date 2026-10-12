"""留言墙异步回复 worker。"""

from __future__ import annotations

import asyncio

from app import logger as app_logger
from app.llm import LLMError, Message, get_provider
from app.router.gate import check

from .store import get_store

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="wall")
_task: asyncio.Task[None] | None = None


async def _handle(item: dict[str, str]) -> None:
    store = get_store()
    gate = check(item["text"])
    if gate.hit:
        reply = "我听见你现在很辛苦。请先联系心理援助热线 12356，找一位现实中的人陪你一起待着。"
    else:
        prompt = (
            "你是心栖阁的温和陪伴者。请用简短、具体、不评判的中文回复这条留言；"
            "不要诊断，不要假装治疗师，只给一个现在能做的小步骤。留言：" + item["text"]
        )
        try:
            reply = await get_provider().chat([Message("user", prompt)])
        except LLMError as exc:
            logger.warning("wall_reply_failed", message_id=item["id"], reason=str(exc)[:120])
            return
    store.reply(item["id"], reply)


async def _run() -> None:
    while True:
        try:
            get_store().cleanup()
            for item in get_store().pending():
                await _handle(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("wall_worker_degraded", reason=str(exc)[:120])
        await asyncio.sleep(30)


def start_worker() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run(), name="hrp-wall-worker")


async def stop_worker() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
