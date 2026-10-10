"""TTS Remote Service — CosyVoice2 独立 FastAPI 服务。

端点:
  GET  /live          — 进程存活(200 = 活着)
  GET  /ready         — 模型就绪(200 = ready, 503 = 未就绪)
  GET  /v1/health     — 详细健康状态
  POST /v1/tts/stream — NDJSON 流式合成
  GET  /metrics       — Prometheus 指标

启动:
  python -m app.voice.tts_service
  uvicorn app.voice.tts_service.server:app --host 0.0.0.0 --port 9001

环境变量:
  TTS_SERVICE_PORT         — 监听端口 (默认 9001)
  TTS_SERVICE_HOST         — 监听地址 (默认 0.0.0.0)
  SERVICE_AUTH_TOKEN       — Bearer 认证 token (空=跳过验证)
  TTS_SERVICE_WORKERS      — uvicorn worker 数 (默认 1, CosyVoice 单卡串行)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import struct
import subprocess
import sys
import threading
import time
import wave
from collections.abc import Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

# ---- 路径设置:确保 CosyVoice 仓库可导入 ----

_SERVICE_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SERVICE_DIR.parents[2]
_COSYVOICE_REPO = _BACKEND_DIR.parent / "models" / "voices" / "CosyVoice"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# CosyVoice 仓库路径(tts_sidecar.py 同逻辑)
MODEL_DIR = _COSYVOICE_REPO / "pretrained_models" / "CosyVoice2-0.5B"
PROMPT_WAV = _COSYVOICE_REPO / "asset" / "zero_shot_prompt.wav"
PROMPT_TEXT = "希望你以后能够做的比我还好呦。"

# ---- 配置 ----

PORT = int(os.environ.get("TTS_SERVICE_PORT", "9001"))
HOST = os.environ.get("TTS_SERVICE_HOST", "0.0.0.0")
SERVICE_AUTH_TOKEN = os.environ.get("SERVICE_AUTH_TOKEN", "")
PROTOCOL_VERSION = 2  # 与 SIDECAR_VERSION 保持一致
SERVICE_VERSION = "1.0.0"
MODEL_NAME = "CosyVoice2-0.5B"

# ---- 结构化日志 ----

logger.remove()
logger.add(
    sys.stderr,
    level=os.environ.get("TTS_LOG_LEVEL", "INFO"),
    format=(
        "<green>{time:MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}:{function}:{line}</cyan> - {message}"
    ),
)
logger.add(
    "logs/tts_debug_{time:YYYY-MM-DD}.log",
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
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)
INFERENCE_LATENCY = Histogram(
    "service_inference_duration_seconds",
    "Model inference latency",
    ["model"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10],
)
ACTIVE_REQUESTS = Gauge("service_active_requests", "Currently active requests")
MODEL_READY = Gauge("service_model_ready", "Model ready (0/1)")
SERVICE_UPTIME = Gauge("service_uptime_seconds", "Service uptime")
GPU_MEMORY_USED = Gauge("gpu_memory_used_bytes", "GPU memory used in bytes")
GPU_UTILIZATION = Gauge("gpu_utilization_percent", "GPU utilization percent")

_start_time = time.time()

# ---- 模型状态 ----

_state_lock = threading.Lock()
_model_state: dict[str, Any] = {"ready": False, "error": None, "model": None, "prompt": None}


# ---- 模型加载(移植自 tts_sidecar.py) ----


def _tensor_from_wav_path(path: str | Path, target_sr: int) -> Any:
    """任意 wav → ffmpeg 16k/mono/s16 → (1,T) float 张量。"""
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(target_sr),
            "-sample_fmt", "s16", "-f", "wav", "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    import torch

    with wave.open(io.BytesIO(proc.stdout), "rb") as w:
        frames = w.readframes(w.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    return torch.tensor(samples, dtype=torch.float32).unsqueeze(0) / 32768.0


def _wav_bytes(t: Any, sr: int) -> bytes:
    """(1,T) float 张量 → 16bit PCM wav 字节。"""
    import torch

    data = (t.squeeze(0).clamp(-1.0, 1.0) * 32767.0).to(torch.int16).cpu().numpy().tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data)
    return buf.getvalue()


def _patch_load_wav() -> None:
    """替换 cosyvoice 的 load_wav(同 tts_sidecar.py)。"""
    import cosyvoice.utils.file_utils as fu
    import torch
    import torchaudio.transforms

    def load_wav(wav: object, target_sr: int, min_sr: int = 16000) -> Any:
        if isinstance(wav, torch.Tensor):
            speech = wav if wav.dim() == 2 else wav.unsqueeze(0)
            sr = 16000
        else:
            speech = _tensor_from_wav_path(str(wav), target_sr)
            sr = target_sr
        if sr != target_sr:
            speech = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)(speech)
        return speech

    fu.load_wav = load_wav
    import cosyvoice.cli.frontend as frontend_mod

    frontend_mod.load_wav = load_wav


def _load_model() -> None:
    """后台线程加载 CosyVoice2 模型。"""
    try:
        sys.path.insert(0, str(_COSYVOICE_REPO))
        # matcha lives in CosyVoice/third_party/Matcha-TTS, not at repo root
        sys.path.insert(0, str(_COSYVOICE_REPO / "third_party" / "Matcha-TTS"))
        _patch_load_wav()
        from cosyvoice.cli.cosyvoice import CosyVoice2

        prompt = _tensor_from_wav_path(PROMPT_WAV, 16000)
        cosyvoice = CosyVoice2(str(MODEL_DIR), load_jit=False, load_trt=False,)
        with _state_lock:
            _model_state["model"] = cosyvoice
            _model_state["prompt"] = prompt
            _model_state["ready"] = True
            MODEL_READY.set(1)
        logger.info(f"model_ready · CosyVoice2 已加载 ({MODEL_DIR})")
    except Exception as exc:  # noqa: BLE001 — 启动失败写进 /health 供诊断
        with _state_lock:
            _model_state["error"] = str(exc)
        MODEL_READY.set(0)
        logger.error(f"model_load_failed · {exc}")


def _synth_sentences(text: str) -> Generator[bytes]:
    """文本 → 逐句 wav 字节生成器(24k)。"""
    from app.voice.tts_service.protocol import split_for_tts

    with _state_lock:
        model = _model_state.get("model")
        prompt = _model_state.get("prompt")
    if model is None or prompt is None:
        raise RuntimeError("模型未就绪")
    for sent in split_for_tts(text):
        t0 = time.perf_counter()
        for result in model.inference_zero_shot(sent, PROMPT_TEXT, prompt, stream=False):
            INFERENCE_LATENCY.labels(model=MODEL_NAME).observe(time.perf_counter() - t0)
            yield _wav_bytes(result["tts_speech"], 24000)


# ---- GPU 监控 ----


def _collect_gpu_stats() -> None:
    """后台定期采集 GPU 指标(每 10s)。"""
    while True:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            for i, line in enumerate(result.stdout.strip().split("\n")):
                if "," in line:
                    mem, util = line.split(",", 1)
                    GPU_MEMORY_USED.labels(device=i).set(float(mem.strip()) * 1024 * 1024)
                    GPU_UTILIZATION.labels(device=i).set(float(util.strip()))
        except Exception:  # noqa: BLE001, S110 — GPU 不可用时静默
            pass
        time.sleep(10)


# ---- FastAPI App ----


@asynccontextmanager
async def lifespan(_application: FastAPI):
    """startup: 后台加载模型 + GPU 监控。"""
    logger.info("startup_begin · TTS Service 启动中")
    threading.Thread(target=_load_model, daemon=True).start()
    threading.Thread(target=_collect_gpu_stats, daemon=True).start()
    yield
    logger.info("shutdown · TTS Service 关停")


app = FastAPI(title="hrp-tts", version=SERVICE_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- 中间件:日志 + metrics + 认证 + request_id ----


@app.middleware("http")
async def _observability_middleware(request: Request, call_next):
    """统一中间件:结构化日志 + Prometheus metrics + Bearer 认证 + X-Request-ID。"""
    path = request.url.path

    # /metrics 和 /live 不记日志、不认证、不计 metrics(基础设施探针)
    if path in ("/metrics", "/live"):
        return await call_next(request)

    # 认证
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
    except Exception as exc:  # noqa: BLE001 — 中间件收口:任何异常不崩服务
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
    """进程存活探针。"""
    return {"status": "ok", "service": "hrp-tts"}


@app.get("/ready")
async def ready():
    """模型就绪探针:200=ready, 503=未就绪。"""
    with _state_lock:
        is_ready = bool(_model_state["ready"])
        error = _model_state["error"]
    if not is_ready:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "error": error, "version": PROTOCOL_VERSION},
        )
    return {"ready": True, "error": None, "version": PROTOCOL_VERSION}


@app.get("/v1/health")
async def health():
    """详细健康状态。"""
    with _state_lock:
        is_ready = bool(_model_state["ready"])
        error = _model_state["error"]
    gpu_available = False
    try:
        result = subprocess.run(  # noqa: ASYNC221 — nvidia-smi 快速查询,5s 超时可接受
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        gpu_available = bool(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 — GPU 不可用时静默
        pass
    return {
        "status": "ok",
        "service": "hrp-tts",
        "version": SERVICE_VERSION,
        "model": MODEL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "ready": is_ready,
        "error": error,
        "gpu": gpu_available,
        "uptime_s": round(time.time() - _start_time),
    }


class TTSRequest(BaseModel):
    text: str = Field(..., max_length=10000, description="要合成的文本")


@app.post("/v1/tts/stream")
async def tts_stream(req: TTSRequest, request: Request):
    """NDJSON 流式合成:每行 {"wav": "<base64>"}。"""
    request_id = getattr(request.state, "request_id", "unknown")

    if not req.text.strip():
        return JSONResponse(status_code=400, content={"error": "text 不能为空", "code": "empty_text"})

    with _state_lock:
        is_ready = bool(_model_state["ready"])
    if not is_ready:
        return JSONResponse(status_code=503, content={"error": "模型未就绪", "code": "tts_unavailable"})

    t0 = time.perf_counter()
    chunks = 0

    async def _stream():
        """将同步 CosyVoice 推理移出 event loop,保持 NDJSON 流式输出。

        使用 asyncio.Queue + 专用生产者线程:推理线程持续运行不阻塞 event loop,
        消费端只做 queue.get(),health 探针可即时响应。
        """
        nonlocal chunks
        queue: asyncio.Queue[bytes | None | Exception] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _producer():
            """在专用线程中逐句推理,结果放入 Queue。"""
            try:
                for wav in _synth_sentences(req.text):
                    loop.call_soon_threadsafe(queue.put_nowait, wav)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        producer = threading.Thread(target=_producer, daemon=True)
        producer.start()

        try:
            while True:
                item = await queue.get()
                if item is None:  # sentinel = done
                    break
                if isinstance(item, Exception):
                    raise item
                chunks += 1
                yield json.dumps({"wav": base64.b64encode(item).decode("ascii")}) + "\n"
        except Exception as exc:  # noqa: BLE001 — 合成失败:返回错误行
            logger.bind(request_id=request_id, event="synth_error", detail=str(exc)[:200]).error("synth_error")
            yield json.dumps({"error": str(exc)[:200], "code": "synth_failed"}) + "\n"

    async def _tracked_stream():
        nonlocal chunks
        async for chunk in _stream():
            yield chunk
        elapsed = time.perf_counter() - t0
        logger.bind(
            request_id=request_id,
            event="tts_stream",
            latency_ms=round(elapsed * 1000, 1),
            text_length=len(req.text),
            chunks=chunks,
        ).info("tts_stream")

    return StreamingResponse(
        _tracked_stream(),
        media_type="application/x-ndjson",
    )


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible 指标。"""
    SERVICE_UPTIME.set(time.time() - _start_time)
    return StreamingResponse(
        iter([generate_latest()]),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---- 入口 ----


def main():
    import uvicorn

    workers = int(os.environ.get("TTS_SERVICE_WORKERS", "1"))
    logger.info(f"starting · TTS Service on {HOST}:{PORT} (workers={workers})")
    uvicorn.run(
        "app.voice.tts_service.server:app",
        host=HOST,
        port=PORT,
        workers=workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()
