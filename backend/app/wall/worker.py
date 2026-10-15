"""留言墙异步回复 worker。

危机路径与网关同红线(AGENTS.md 安全红线):命中必落审计 WARN
(event=wall_crisis_hit,含 matched/severity/to_hotline,不含留言原文),
回复话术接 router/phrases.py 单源(CRISIS_SOOTHE+CRISIS_HOTLINE)。
"""

from __future__ import annotations

import asyncio

from app import logger as app_logger
from app.llm import LLMError, Message, get_provider
from app.router import phrases
from app.router.gate import check
from app.ws_gateway import push_wall_reply

from .store import get_store

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="wall")
_task: asyncio.Task[None] | None = None


async def _handle(item: dict[str, str]) -> None:
    store = get_store()
    gate = check(item["text"])
    if gate.hit:
        # 危机命中必落审计(红线):同网关 crisis_gate_hit 字段口径,不含原文
        app_logger.event_log(
            "wall_crisis_hit",
            level="WARN",
            message_id=item["id"],
            hit=True,
            severity=gate.severity,
            matched=gate.matched,
            to_hotline=True,
        )
        reply = f"{phrases.CRISIS_SOOTHE}{phrases.CRISIS_HOTLINE}"
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
    # 回复就绪推 wall_reply(§3.7):在线则前端即时刷新,离线静默(未读态兜底)
    if await push_wall_reply(item["session_id"]):
        logger.info("wall_reply_pushed", message_id=item["id"])


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
