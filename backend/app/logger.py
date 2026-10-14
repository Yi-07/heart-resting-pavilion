"""日志与审计(ws-contract §9 / backend-plan §9)。

双输出:
- 控制台:彩色可读(Loguru 风格),INFO 默认,HRP_VERBOSE=1 → DEBUG
- 文件:{HRP_LOG_DIR:-logs}/debug_{date}.log 结构化 JSON(serialize),DEBUG 全量,
  轮转 10MB / 保留 30 天。HRP_LOG_DIR 可重定向目录(默认 logs;测试/CI 用它把
  日志集中到临时目录,不改代码)
标准字段:ts/level/service/session_id/trace_id/event/route/message。
WARN 为注册的自定义级别(契约 §9.2 用 WARN 而非 WARNING,数值=30 同档)。
脱敏(硬约束):用户文本只记长度/哈希(audio 用户原文同理);音频/凭证绝不落。
"""

import inspect
import logging
import os
import sys
from collections.abc import Callable
from hashlib import sha1
from typing import Any

from loguru import logger

SERVICE = "hrp-backend"


class InterceptHandler(logging.Handler):
    """标准 logging → loguru(uvicorn/fastapi 记录并入双输出)"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logger(verbose: bool = False) -> None:
    """装配双输出;幂等(重复调用重置 sinks)。"""
    logger.remove()
    try:
        logger.level("WARN", no=30)
    except ValueError:
        pass  # 已注册
    logger.add(
        sys.stderr,
        level="DEBUG" if verbose else "INFO",
        format=(
            "<green>{time:MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | "
            "<cyan>{name}:{function}:{line}</cyan> - {message}"
        ),
    )
    logger.add(
        os.path.join(os.getenv("HRP_LOG_DIR", "logs"), "debug_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        serialize=True,
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
    )
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


def text_fingerprint(text: str) -> str:
    """脱敏指纹:长度 + sha1 前 8 位,不落原文(§9.4)。"""
    digest = sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"len={len(text)} sha1:{digest}"


def event_log(event: str, level: str = "INFO", **fields: Any) -> None:
    """标准事件日志:标准字段(service/event)+ 业务字段(bind 进结构化输出)。"""
    logger.bind(service=SERVICE, event=event, **fields).log(level, event)


def capture_events(sink: Callable[[Any], None]) -> int:
    """测试辅助:挂内存 sink 收结构化记录(record.extra 即字段);返回句柄供 remove。"""
    return logger.add(lambda message: sink(message.record), level="DEBUG")


__all__ = [
    "InterceptHandler",
    "capture_events",
    "event_log",
    "logger",
    "setup_logger",
    "text_fingerprint",
]
