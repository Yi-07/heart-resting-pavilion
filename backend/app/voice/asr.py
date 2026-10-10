"""ASR 路由层:按 ASR_MODE 选择 local (funasr 本地推理) 或 remote (HTTP 远程服务)。

routes.py 的 import 路径不变(app.voice.asr),
本模块透明切换底层实现。

本地模式:原有 funasr SenseVoice 实现不变。
远程模式:HTTP 调用 ASR Service,不加载 funasr 模型。
"""

from __future__ import annotations

from app import config

if config.ASR_MODE == "remote":
    from app.voice.asr_client import ASRError, transcribe
else:
    # ---- local mode:原有 funasr 实现(内联,避免循环导入) ----

    import io
    import os
    import re
    import struct
    import subprocess
    import tempfile
    import time
    import wave
    from functools import lru_cache

    from app import logger as app_logger

    logger = app_logger.logger.bind(service=app_logger.SERVICE, module="asr")

    _TAG_RE = re.compile(r"<\|[^|]*\|>")

    _SILENCE_GATE = 100
    """近静音门限(16bit PCM 平均绝对幅值,32768 满幅;≈-50dBFS)。"""

    from app.voice.asr_errors import ASRError

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
        """wav PCM16 平均绝对幅值(0~32768);解析失败返 None。"""
        try:
            with wave.open(io.BytesIO(wav)) as w:
                if w.getsampwidth() != 2:
                    return None
                frames = w.readframes(w.getnframes())
        except Exception:  # noqa: BLE001
            return None
        n = len(frames) // 2
        if n == 0:
            return None
        samples = struct.unpack(f"<{n}h", frames)
        return sum(abs(s) for s in samples) / n

    def transcribe(audio: bytes, *, request_id: str | None = None) -> str:
        """音频字节 → 文本;空串=无语音内容。同步阻塞(网关用 to_thread 调)。"""
        wav = _to_wav16k(audio)
        level = _mean_abs_amplitude(wav)
        if level is not None and level < _SILENCE_GATE:
            return ""
        try:
            result = _model().generate(input=wav, language="zh", use_itn=True, batch_size_s=60)
            raw = result[0]["text"]
        except Exception as exc:
            raise ASRError(f"SenseVoice 推理失败: {exc}") from exc
        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess

            text = rich_transcription_postprocess(raw)
        except Exception:  # noqa: BLE001
            text = _TAG_RE.sub("", raw)
        return text.strip()
