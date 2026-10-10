"""TTS 服务日志模块:终端彩色可读 + 文件结构化 JSON Lines 双输出。

为什么不用标准库 logging 的 basicConfig:
    basicConfig 只能配终端,没有文件输出、没有结构化、没有轮转。
    本模块参照 backend/app/logger.py 的成熟模式,用 loguru 实现双输出。

终端格式(人类可读):
    10-09 12:34:56 | INFO  | tts_service | request_start · round_id=tts-0 text_len=42

文件格式(JSON Lines,便于检索):
    {"text":"...", "record":{...标准化字段..., "round_id":"tts-0", "duration_ms":123}}

标准字段:ts / level / service / event / round_id / message
业务字段(随 event 变化):duration_ms / bytes / seq / status / audio_seq / error 等。

轮转:按文件大小(默认 10 MB)+ 保留天数(默认 30 天),可经 YAML 配置。
"""

from __future__ import annotations

import inspect
import logging
import sys
import traceback
from pathlib import Path
from typing import Any

from loguru import logger

SERVICE = "hrp-tts-gpt-sovits"
"""服务名,所有日志记录的标准字段。"""

DEFAULT_LOG_DIR = "logs"
DEFAULT_ROTATION = "10 MB"
DEFAULT_RETENTION = "30 days"


class InterceptHandler(logging.Handler):
    """把标准 logging 的记录转给 loguru(uvicorn 的访问日志走这条路)。

    不装这个 handler,uvicorn 的 request 日志会走它自己的 StreamHandler,
    与 loguru 的双输出脱节:终端格式不统一、文件里也看不到访问日志。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        # traceback 对象无法被 JSON 序列化(serialize=True 时会崩),
        # 转成字符串附加到消息里,保留完整异常信息
        exc_info = record.exc_info
        if exc_info:
            exc_text = "".join(traceback.format_exception(*exc_info))
            logger.opt(depth=depth).log(level, f"{record.getMessage()}\n{exc_text}")
        else:
            logger.opt(depth=depth).log(level, record.getMessage())


def setup_logging(
    *,
    level: str = "INFO",
    log_dir: str = DEFAULT_LOG_DIR,
    rotation: str = DEFAULT_ROTATION,
    retention: str = DEFAULT_RETENTION,
    file_level: str = "INFO",
    base_dir: Path | None = None,
) -> None:
    """装配双输出:终端彩色可读 + 文件结构化 JSON Lines。

    幂等:重复调用先 remove 所有 sink 再重装,避免重复输出。
    日志目录不存在时自动创建;创建失败时只保留终端输出并给出明确错误,
    不会悄悄退化成"没有日志"的无法诊断状态。

    base_dir:相对 log_dir 的锚点。**必须传**仓库根(settings.ROOT),否则
    「相对路径」会跟着进程 cwd 走 —— 从别的目录启动就把 logs/ 写到别处去了,
    排查时根本想不到日志在别的地方。绝对路径 log_dir 不受影响。
    """
    logger.remove()

    # 终端:人类可读,时间 | 级别 | 服务 | 事件 · 关键字段
    logger.add(
        sys.stderr,
        level=level.upper(),
        format=(
            "<green>{time:MM-DD HH:mm:ss}</green> | "
            "<level>{level: <7}</level> | "
            "<cyan>{name}:{function}:{line}</cyan> - {message}"
        ),
    )

    # 桥接标准 logging(uvicorn 访问日志)到 loguru,否则它走自己的 handler
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 文件:结构化 JSON Lines,便于检索;轮转 + 保留策略
    path = Path(log_dir)
    if not path.is_absolute():
        # 锚定调用方给的仓库根,不跟 cwd 走
        path = (base_dir or Path.cwd()) / path
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # 目录建不了:保留终端输出,明确报错,不静默吞掉
        logger.error(
            f"log_dir_unavailable · dir={path} err={exc};仅终端输出,文件日志已禁用"
        )
        return

    logger.add(
        str(path / "tts_service_{time:YYYY-MM-DD}.log"),
        level=file_level.upper(),
        serialize=True,
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
    )


def format_exc(exc: BaseException) -> str:
    """异常 → 完整 traceback 字符串(含类型与消息)。

    为什么不直接交给 loguru 的 exception=:`serialize=True` 时 traceback 对象
    不可序列化,会抛 "Logging error in Loguru Handler"。转字符串是 JSON 安全的,
    信息一点不少(类型/消息/调用栈都在)。
    """
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def event(
    event_name: str,
    level: str = "INFO",
    *,
    exc: BaseException | None = None,
    **fields: Any,
) -> None:
    """记录一条结构化事件日志。

    标准字段(service/event)自动注入,业务字段(如 round_id/duration_ms/bytes)
    通过 bind 混入,序列化为 JSON 后写入文件。

    exc=传入被捕获的异常时,自动补 error_type 与 traceback 两个字段 ——
    捕获后只记一句 "失败" 的日志没有诊断价值,traceback 才是定位依据。
    """
    if exc is not None:
        fields.setdefault("error_type", type(exc).__name__)
        fields.setdefault("traceback", format_exc(exc))
    logger.bind(service=SERVICE, event=event_name, **fields).log(level.upper(), event_name)


__all__ = [
    "SERVICE",
    "InterceptHandler",
    "event",
    "format_exc",
    "logger",
    "setup_logging",
]
