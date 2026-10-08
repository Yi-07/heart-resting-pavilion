"""ASR Remote Service — SenseVoice 独立 FastAPI 服务。

端点:
  GET  /live            — 进程存活(200 = 活着)
  GET  /ready           — 模型就绪(200 = ready, 503 = 未就绪)
  GET  /v1/health       — 详细健康状态
  POST /v1/transcribe   — base64 音频 → 转写文本
  GET  /metrics         — Prometheus 指标

启动:
  python -m app.voice.asr_service
  uvicorn app.voice.asr_service.server:app --host 0.0.0.0 --port 9002

环境变量:
  ASR_SERVICE_PORT       — 监听端口 (默认 9002)
  ASR_SERVICE_HOST       — 监听地址 (默认 0.0.0.0)
  ASR_MODEL_ID           — funasr 模型 ID (默认 iic/SenseVoiceSmall)
  SERVICE_AUTH_TOKEN     — Bearer 认证 token (空=跳过验证)
"""

from __future__ import annotations

import base64
import io
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

# ---- 配置 ----

PORT = int(os.environ.get("ASR_SERVICE_PORT", "9002"))
HOST = os.environ.get("ASR_SERVICE_HOST", "0.0.0.0")
SERVICE_AUTH_TOKEN = os.environ.get("SERVICE_AUTH_TOKEN", "")
ASR_MODEL_ID = os.environ.get("ASR_MODEL_ID", "iic/SenseVoiceSmall")
SERVICE_VERSION = "1.0.0"
MODEL_NAME = "SenseVoiceSmall"
PROTOCOL_VERSION = 1

_MAX_AUDIO_BYTES = 1 * 1024 * 1024
"""base64 解码后字节护栏:与主服务保持一致。"""

_SILENCE_GATE = 100
"""近静音门限(与 asr.py 保持一致)。"""

_TAG_RE = re.compile(r"<\|[^|]*\|>")

# ---- 结构化日志 ----

logger.remove()
logger.add(
    sys.stderr,
    level=os.environ.get("ASR_LOG_LEVEL", "INFO"),
    format=(
        "<green>{time:MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}:{function}:{line}</cyan> - {message}"
    ),
)
logger.add(
    "logs/asr_debug_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    serialize=True,
    rotation="10 MB",
    retention="30 days",
    encoding="utf-8",
)

# ---- Prometheus 指标 ----

REQUEST_COUNT = Counter(
    "service_requests_total",
    "Total requests",
    ["endpoint", "method", "status"],
)
REQUEST_LATENCY = Histogram(
    "service_request_duration_seconds",
    "Request latency",
    ["endpoint"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)
INFERENCE_LATENCY = Histogram(
    "service_inference_duration_seconds",
    "Model inference latency",
    ["model"],
    buckets=[0.05, 0.1, 0.5, 1, 2, 5, 10],
)
ACTIVE_REQUESTS = Gauge("service_active_requests", "Currently active requests")
MODEL_READY = Gauge("service_model_ready", "Model ready (0/1)")
SERVICE_UPTIME = Gauge("service_uptime_seconds", "Service uptime")

_start_time = time.time()

# ---- 模型状态 ----

_model_loaded = False
_model_error: str | None = None
_model_lock = threading.Lock()


# ---- 音频处理(移植自 asr.py) ----


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
        raise RuntimeError(f"ffmpeg 转码失败: rc={proc.returncode}")
    return proc.stdout


def _mean_abs_amplitude(wav: bytes) -> float | None:
    """wav PCM16 平均绝对幅值。"""
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


def _transcribe_inner(audio: bytes) -> str:
    """音频转写核心逻辑(同步阻塞)。"""
    wav = _to_wav16k(audio)
    level = _mean_abs_amplitude(wav)
    if level is not None and level < _SILENCE_GATE:
        return ""
    try:
        result = _model().generate(input=wav, language="zh", use_itn=True, batch_size_s=60)
        raw = result[0]["text"]
    except Exception as exc:
        raise RuntimeError(f"SenseVoice 推理失败: {exc}") from exc
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        text = rich_transcription_postprocess(raw)
    except Exception:  # noqa: BLE001
        text = _TAG_RE.sub("", raw)
    return text.strip()


_model_instance = None


def _model():
    """懒加载 SenseVoice 模型(手动单例,支持模型 ID 回退)。"""
    global _model_loaded, _model_instance
    if _model_instance is not None:
        return _model_instance

    from funasr import AutoModel

    logger.info("asr_model_begin · 正在加载 SenseVoice 模型")
    t0 = time.perf_counter()

    # 尝试完整 ID,失败则尝试短 ID
    model_ids = [ASR_MODEL_ID]
    if "/" in ASR_MODEL_ID:
        model_ids.append(ASR_MODEL_ID.split("/", 1)[1])

    last_error = None
    for mid in model_ids:
        try:
            logger.info(f"asr_debug · trying model={mid!r}")
            model = AutoModel(model=mid, disable_update=True)
            _model_instance = model
            with _model_lock:
                _model_loaded = True
                MODEL_READY.set(1)
            logger.info(f"asr_model_ready · SenseVoice 模型已加载({time.perf_counter() - t0:.1f}s) model={mid}")
            return model
        except Exception as exc:  # noqa: BLE001 — 模型加载失败类型多样,记录后尝试下一个 id
            last_error = exc
            logger.warning(f"asr_debug · model={mid!r} failed: {exc}")
            continue

    raise last_error  # type: ignore[misc]


def _load_model_background():
    """后台线程预加载模型(含重试,应对 funasr 注册竞态)。"""
    global _model_error
    import traceback as _tb

    for attempt in range(1, 4):
        try:
            _model()
            return  # 成功
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"model_load_attempt_{attempt}_failed · {exc}")
            if attempt < 3:
                import time as _t
                _t.sleep(2)  # 等待 funasr 注册完成
            else:
                with _model_lock:
                    _model_error = str(exc)
                MODEL_READY.set(0)
                logger.error(f"model_load_failed · {exc}\n{_tb.format_exc()}")


# ---- FastAPI App ----


@asynccontextmanager
async def lifespan(_application: FastAPI):
    logger.info("startup_begin · ASR Service 启动中")
    threading.Thread(target=_load_model_background, daemon=True).start()
    yield
    logger.info("shutdown · ASR Service 关停")


app = FastAPI(title="hrp-asr", version=SERVICE_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- 中间件:日志 + metrics + 认证 + request_id ----


@app.middleware("http")
async def _observability_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/metrics", "/live"):
        return await call_next(request)

    if SERVICE_AUTH_TOKEN and path not in ("/ready",):
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {SERVICE_AUTH_TOKEN}":
            return JSONResponse(status_code=401, content={"error": "Unauthorized", "code": "auth_failed"})

    request_id = request.headers.get("x-request-id", "unknown")
    request.state.request_id = request_id

    t0 = time.perf_counter()
    ACTIVE_REQUESTS.inc()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        ACTIVE_REQUESTS.dec()
        REQUEST_COUNT.labels(endpoint=path, method=request.method, status="500").inc()
        logger.bind(request_id=request_id, event="unhandled_error", detail=str(exc)[:200]).error("unhandled_error")
        return JSONResponse(status_code=500, content={"error": str(exc)[:200], "code": "internal_error"})
    finally:
        ACTIVE_REQUESTS.dec()

    elapsed = time.perf_counter() - t0
    REQUEST_COUNT.labels(endpoint=path, method=request.method, status=str(response.status_code)).inc()
    REQUEST_LATENCY.labels(endpoint=path).observe(elapsed)

    logger.bind(
        request_id=request_id,
        event="request",
        endpoint=path,
        method=request.method,
        status=response.status_code,
        latency_ms=round(elapsed * 1000, 1),
    ).info("request")

    return response


# ---- 端点 ----


@app.get("/live")
async def live():
    return {"status": "ok", "service": "hrp-asr"}


@app.get("/ready")
async def ready():
    with _model_lock:
        is_ready = _model_loaded
        error = _model_error
    if not is_ready:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "error": error, "version": PROTOCOL_VERSION},
        )
    return {"ready": True, "error": None, "version": PROTOCOL_VERSION}


@app.get("/v1/health")
async def health():
    with _model_lock:
        is_ready = _model_loaded
        error = _model_error
    return {
        "status": "ok",
        "service": "hrp-asr",
        "version": SERVICE_VERSION,
        "model": MODEL_NAME,
        "model_id": ASR_MODEL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "ready": is_ready,
        "error": error,
        "gpu": False,
        "uptime_s": round(time.time() - _start_time),
    }


class TranscribeRequest(BaseModel):
    audio: str = Field(..., max_length=1_400_000, description="base64 编码的音频")


class TranscribeResponse(BaseModel):
    text: str


@app.post("/v1/transcribe", response_model=TranscribeResponse)
async def transcribe(req: TranscribeRequest, request: Request):
    request_id = getattr(request.state, "request_id", "unknown")

    with _model_lock:
        is_ready = _model_loaded
    if not is_ready:
        return JSONResponse(status_code=503, content={"error": "模型未就绪", "code": "asr_unavailable"})

    # 解码音频
    try:
        audio = base64.b64decode(req.audio, validate=True)
    except (ValueError, TypeError):  # base64 解码失败
        return JSONResponse(status_code=400, content={"error": "audio 不是合法 base64", "code": "invalid_audio"})

    if len(audio) > _MAX_AUDIO_BYTES:
        return JSONResponse(status_code=413, content={"error": "语音超过长度上限", "code": "audio_too_large"})

    if not audio:
        return TranscribeResponse(text="")

    t0 = time.perf_counter()
    try:
        text = _transcribe_inner(audio)
    except Exception as exc:  # noqa: BLE001
        logger.bind(request_id=request_id, event="transcribe_error", detail=str(exc)[:200]).error("transcribe_error")
        return JSONResponse(status_code=500, content={"error": str(exc)[:200], "code": "transcribe_failed"})

    elapsed = time.perf_counter() - t0
    INFERENCE_LATENCY.labels(model=MODEL_NAME).observe(elapsed)

    logger.bind(
        request_id=request_id,
        event="transcribe",
        latency_ms=round(elapsed * 1000, 1),
        audio_bytes=len(audio),
        text_length=len(text),
    ).info("transcribe")

    return TranscribeResponse(text=text)


@app.get("/metrics")
async def metrics():
    SERVICE_UPTIME.set(time.time() - _start_time)
    return JSONResponse(
        content=generate_latest().decode("utf-8"),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---- 入口 ----


def main():
    import uvicorn

    logger.info(f"starting · ASR Service on {HOST}:{PORT}")
    uvicorn.run(
        "app.voice.asr_service.server:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
