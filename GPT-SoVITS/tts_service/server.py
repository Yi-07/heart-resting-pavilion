"""GPT-SoVITS TTS 远程服务 —— FastAPI 层。

与 backend/app/voice/tts_service 线格式完全一致(端口 9001、同一套环境变量、
同一组端点与错误码),因此主服务无需任何配置改动,切换 = 停旧起新。

端点
    GET  /live              进程存活
    GET  /ready             模型就绪(200 / 503)
    GET  /v1/health         详细状态
    POST /v1/tts/stream     NDJSON 流式合成,每行 {"wav": "<base64 完整 wav>"}
    POST /v1/tts/cancel     打断回合 {"round_id": "...", "cascade": true}
    GET  /metrics           Prometheus

线格式要点(来自 tts_client.py,改动会破坏主服务):
    - 请求体 {"text": "..."} / 响应每行 JSON,wav 字段是 base64 的**完整 wav 文件**
    - 出错时同一行给 {"error": "...", "code": "..."},HTTP 状态码仍是 200
    - 请求标识走 X-Request-ID 头,打断用它当 round_id
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import subprocess
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from . import MODEL_NAME, PROTOCOL_VERSION, SERVICE_NAME, SERVICE_VERSION
from .engine import EngineBusy, GuardError, TTSEngine
from .settings import get_settings

logger = logging.getLogger("tts_service")

# ---- Prometheus ----
# 指标名与后端 tts_service 保持同名同标签,便于两边一起看同一块面板。
ACTIVE_REQUESTS = Gauge(
    "tts_active_requests", "正在处理的请求数", ["endpoint"]
)
REQUEST_COUNT = Counter(
    "tts_requests_total", "请求总数", ["endpoint", "method", "status"]
)
REQUEST_LATENCY = Histogram(
    "tts_request_latency_seconds", "端点延迟", ["endpoint"]
)
SENTENCE_LATENCY = Histogram(
    "tts_sentence_latency_seconds", "单句合成耗时", ["stage"],
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 5.0, 10.0),
)
SENTENCES_TOTAL = Counter("tts_sentences_total", "产出句数")
AUDIO_BYTES_TOTAL = Counter("tts_audio_bytes_total", "产出音频字节数")
CANCEL_TOTAL = Counter("tts_cancel_total", "打断次数", ["scope"])
ERROR_TOTAL = Counter("tts_errors_total", "错误数", ["kind"])
GPU_MEMORY_USED = Gauge("tts_gpu_memory_used_bytes", "显存占用", ["device"])
GPU_UTILIZATION = Gauge("tts_gpu_utilization_percent", "GPU 利用率", ["device"])
SERVICE_UPTIME = Gauge("tts_service_uptime_seconds", "服务运行时长")

_START_TIME = time.time()
_cfg = get_settings()
logging.basicConfig(
    level=getattr(logging, _cfg.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

engine = TTSEngine(_cfg)


# ---- GPU 监控 ----
def _collect_gpu_stats() -> None:
    while True:
        try:
            r = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            for i, line in enumerate(r.stdout.strip().splitlines()):
                if "," in line:
                    mem, util = line.split(",", 1)
                    GPU_MEMORY_USED.labels(device=i).set(float(mem.strip()) * 1024 * 1024)
                    GPU_UTILIZATION.labels(device=i).set(float(util.strip()))
        except Exception:  # noqa: BLE001, S110 — GPU 不可用时静默
            pass
        time.sleep(10)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("startup_begin · GPT-SoVITS TTS Service 启动中")
    threading.Thread(target=engine.load, name="model-load", daemon=True).start()
    threading.Thread(target=_collect_gpu_stats, name="gpu-poll", daemon=True).start()
    yield
    logger.info("shutdown · TTS Service 关停")


app = FastAPI(title="hrp-tts-gpt-sovits", version=SERVICE_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- 中间件:认证 + request_id + metrics + 日志 ----
@app.middleware("http")
async def _observability(request: Request, call_next):
    path = request.url.path
    if path in ("/metrics", "/live"):
        return await call_next(request)

    if _cfg.auth_token and path != "/ready":
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {_cfg.auth_token}":
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized", "code": "auth_failed"},
            )

    # X-Request-ID 同时充当 round_id:主程序打断时用同一个值取消。
    request_id = request.headers.get("x-request-id", "").strip() or f"r{int(time.time() * 1000)}"
    request.state.request_id = request_id

    t0 = time.perf_counter()
    ACTIVE_REQUESTS.labels(endpoint=path).inc()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 — 中间件收口
        ACTIVE_REQUESTS.labels(endpoint=path).dec()
        REQUEST_COUNT.labels(endpoint=path, method=request.method, status="500").inc()
        ERROR_TOTAL.labels(kind="unhandled").inc()
        logger.error("unhandled_error request_id=%s %s", request_id, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)[:200], "code": "internal_error"},
        )
    finally:
        ACTIVE_REQUESTS.labels(endpoint=path).dec()

    elapsed = time.perf_counter() - t0
    REQUEST_COUNT.labels(
        endpoint=path, method=request.method, status=str(response.status_code)
    ).inc()
    REQUEST_LATENCY.labels(endpoint=path).observe(elapsed)
    logger.info(
        "request request_id=%s %s %s status=%s latency_ms=%.1f",
        request_id, request.method, path, response.status_code, elapsed * 1000,
    )
    return response


# ---- 端点 ----
@app.get("/live")
async def live():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
async def ready():
    if not engine.ready:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "error": engine.error, "version": PROTOCOL_VERSION},
        )
    return {"ready": True, "error": None, "version": PROTOCOL_VERSION}


@app.get("/v1/health")
async def health():
    gpu_available = False
    try:
        r = subprocess.run(  # noqa: ASYNC221 — nvidia-smi 快速查询,5s 超时可接受
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        gpu_available = bool(r.stdout.strip())
    except Exception:  # noqa: BLE001, S110
        pass
    snap = engine.snapshot()
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "model": MODEL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "ready": snap["ready"],
        "error": snap["error"],
        "gpu": gpu_available,
        "uptime_s": snap["uptime_s"],
        "engine": snap,
    }


class TTSRequest(BaseModel):
    """合成请求。

    `voice` 刻意声明成 `str = ""` 而不是 `str | None`:
    可选字符串会生成 OpenAPI 的 anyOf,Apifox 会把它渲染成 `"voice": {}`,
    用户只能填对象进去。空串语义等价于"不指定",schema 却是干净的 string。
    """

    text: str = Field(
        ...,
        description="要合成的文本(仅中文;含 ASCII 英文字母会返回 400)",
        examples=["我们先不急着解决什么，就从今晚开始，选一件最小的事做一做。"],
    )
    voice: str = Field(
        default="",
        description="临时指定音色名(对应 reference/<name>.wav);留空用默认音色",
        examples=["", "yilai", "normal"],
    )


class CancelRequest(BaseModel):
    round_id: str = Field(
        ...,
        description="要打断的回合 id(= 合成请求的 X-Request-ID 头)",
        examples=["r-001"],
    )
    cascade: bool = Field(
        default=True,
        description="同时清空尚未开始的排队回合",
        examples=[True],
    )


@app.post("/v1/tts/stream")
async def tts_stream(req: TTSRequest, request: Request):
    """NDJSON 流式合成:每行 {"wav": "<base64>"},每行一个完整 wav 文件。"""
    round_id = getattr(request.state, "request_id", "")

    if not req.text.strip():
        return JSONResponse(
            status_code=400, content={"error": "text 不能为空", "code": "empty_text"}
        )
    if not engine.ready:
        return JSONResponse(
            status_code=503,
            content={"error": engine.error or "模型未就绪", "code": "tts_unavailable"},
        )

    try:
        engine.guard(req.text)          # 同步守卫生效,失败直接 400,不必开流
    except GuardError as exc:
        ERROR_TOTAL.labels(kind="guard").inc()
        return JSONResponse(
            status_code=400, content={"error": str(exc), "code": exc.code}
        )

    voice = req.voice.strip() or None

    t0 = time.perf_counter()

    async def _stream() -> AsyncIterator[str]:
        """把同步推理放进专用生产者线程,event loop 只做 queue.get()。

        这样 /ready、/v1/health、/v1/tts/cancel 在合成期间依然能即时响应 ——
        api_v2.py 是在 handler 里直接迭代生成器,合成期间整个服务是僵的。
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        cancelled = False
        n_sent = 0
        bytes_out = 0

        def _produce() -> None:
            try:
                for item in engine.synthesize(
                    req.text, round_id=round_id, voice=voice
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, item)
            except Exception as exc:  # noqa: BLE001 — 交给消费端输出错误行
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        threading.Thread(target=_produce, name=f"synth-{round_id}", daemon=True).start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                ERROR_TOTAL.labels(kind="synth").inc()
                logger.error("synth_error round_id=%s %s", round_id, item)
                yield json.dumps(
                    {"error": str(item)[:200], "code": "synth_failed",
                     "round_id": round_id},
                    ensure_ascii=False,
                ) + "\n"
                break
            SENTENCE_LATENCY.labels(stage="generate").observe(item.gen_s)
            SENTENCE_LATENCY.labels(stage="ttfb").observe(item.ttfb_s)
            SENTENCES_TOTAL.inc()
            bytes_out += len(item.wav)
            AUDIO_BYTES_TOTAL.inc(len(item.wav))
            n_sent += 1
            yield json.dumps(
                {"wav": base64.b64encode(item.wav).decode("ascii"),
                 "round_id": round_id},
                ensure_ascii=False,
            ) + "\n"

        if n_sent == 0 and not cancelled:
            # 一句都没产出:只可能是被打断。显式告诉客户端,别让它当成空回复。
            yield json.dumps(
                {"cancelled": True, "round_id": round_id}, ensure_ascii=False
            ) + "\n"

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"X-Request-ID": round_id},
    )


@app.post("/v1/tts/cancel")
async def tts_cancel(req: CancelRequest, request: Request):
    """打断一个回合;cascade=true 同时清空尚未开始的排队回合。

    幂等:回合已结束或从未存在也返回 200,主程序不必关心顺序。
    """
    result = engine.cancel(req.round_id, cascade=req.cascade)
    if result["cancelled"]:
        CANCEL_TOTAL.labels(scope="round").inc()
    if result["cascaded"]:
        CANCEL_TOTAL.labels(scope="cascade").inc(len(result["cascaded"]))
    requester = getattr(request.state, "request_id", "")
    logger.info(
        "cancel from=%s round_id=%s state=%s cascaded=%s",
        requester, req.round_id, result["state"], result["cascaded"],
    )
    return result


@app.get("/metrics")
async def metrics():
    SERVICE_UPTIME.set(time.time() - _START_TIME)
    return StreamingResponse(
        iter([generate_latest()]),
        media_type=CONTENT_TYPE_LATEST,
    )
