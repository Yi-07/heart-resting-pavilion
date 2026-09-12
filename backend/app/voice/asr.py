"""SenseVoice ASR(backend-plan §2 voice 行):webm/opus → ffmpeg wav16k → 只取转写文本。

- rich 转写的情感/事件标签丢弃(spec:只取文本);音频字节即弃,不落任何存储(红线)
- 懒加载:首次 transcribe 才载模型;funasr 自动从 modelscope 缓存解析
- 转写失败抛 ASRError,由网关降级(温和话术),不杀连接
"""

from __future__ import annotations

import io
import os
import re
import struct
import subprocess
import tempfile
import time
import wave
from functools import lru_cache

from app import config
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="asr")

_TAG_RE = re.compile(r"<\|[^|]*\|>")

_SILENCE_GATE = 100
"""近静音门限(16bit PCM 平均绝对幅值,32768 满幅;≈-50dBFS)。只吃数字静音/纯底噪,
防 SenseVoice 对静音段幻听出语气词(B2 §2 实测);正常小声说话远高于此,不误吃。"""


class ASRError(RuntimeError):
    """转写失败(转码/模型异常);网关捕获后降级"""


@lru_cache(maxsize=1)
def _model():
    from funasr import AutoModel

    logger.info("asr_model_begin · 正在加载 SenseVoice 模型")
    t0 = time.perf_counter()
    model = AutoModel(model=config.ASR_MODEL_ID, disable_update=True)
    logger.info(f"asr_model_ready · SenseVoice 模型已加载({time.perf_counter() - t0:.1f}s)")
    return model


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


def _mean_abs_amplitude(wav: bytes) -> float | None:
    """wav PCM16 平均绝对幅值(0~32768);解析失败返 None(不拦截,走模型)。"""
    try:
        with wave.open(io.BytesIO(wav)) as w:
            if w.getsampwidth() != 2:
                return None
            frames = w.readframes(w.getnframes())
    except Exception:  # noqa: BLE001 — 非常规 wav 交模型处理
        return None
    n = len(frames) // 2
    if n == 0:
        return None
    samples = struct.unpack(f"<{n}h", frames)
    return sum(abs(s) for s in samples) / n


def transcribe(audio: bytes) -> str:
    """音频字节 → 文本;空串=无语音内容。同步阻塞(网关用 to_thread 调)。"""
    wav = _to_wav16k(audio)
    level = _mean_abs_amplitude(wav)
    if level is not None and level < _SILENCE_GATE:
        return ""  # 近静音直接判空:不进模型,防静音幻听(空串走 asr_empty 语义)
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
