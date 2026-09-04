"""SenseVoice ASR(backend-plan §2 voice 行):webm/opus → ffmpeg wav16k → 只取转写文本。

- rich 转写的情感/事件标签丢弃(spec:只取文本);音频字节即弃,不落任何存储(红线)
- 懒加载:首次 transcribe 才载模型;funasr 自动从 modelscope 缓存解析
- 转写失败抛 ASRError,由网关降级(温和话术),不杀连接
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from functools import lru_cache

from app import config
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="asr")

_TAG_RE = re.compile(r"<\|[^|]*\|>")


class ASRError(RuntimeError):
    """转写失败(转码/模型异常);网关捕获后降级"""


@lru_cache(maxsize=1)
def _model():
    from funasr import AutoModel

    return AutoModel(model=config.ASR_MODEL_ID, disable_update=True)


def _to_wav16k(audio: bytes) -> bytes:
    """ffmpeg 转码任意容器(webm/opus 为主)→ wav 16k 单声道。"""
    fd, path = tempfile.mkstemp(suffix=".webm")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    finally:
        os.unlink(path)
    if proc.returncode != 0 or not proc.stdout:
        raise ASRError(f"ffmpeg 转码失败: rc={proc.returncode}")
    return proc.stdout


def transcribe(audio: bytes) -> str:
    """音频字节 → 文本;空串=无语音内容。同步阻塞(网关用 to_thread 调)。"""
    wav = _to_wav16k(audio)
    try:
        result = _model().generate(input=wav, language="zh", use_itn=True, batch_size_s=60)
        raw = result[0]["text"]
    except Exception as exc:
        raise ASRError(f"SenseVoice 推理失败: {exc}") from exc
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        text = rich_transcription_postprocess(raw)
    except Exception:  # noqa: BLE001 — 后处理缺位时手工剥标签
        text = _TAG_RE.sub("", raw)
    return text.strip()
