"""RAG Remote Service — Chroma+BM25+reranker 独立 FastAPI 服务。

端点:
  GET  /live            — 进程存活(200 = 活着)
  GET  /ready           — 模型就绪(200 = ready, 503 = 未就绪)
  GET  /v1/health       — 详细健康状态
  POST /v1/retrieve     — 混合检索+重排
  GET  /metrics         — Prometheus 指标

启动:
  python -m app.rag_service
  uvicorn app.rag_service.server:app --host 0.0.0.0 --port 9003

环境变量:
  RAG_SERVICE_PORT       — 监听端口 (默认 9003)
  RAG_SERVICE_HOST       — 监听地址 (默认 0.0.0.0)
  SERVICE_AUTH_TOKEN     — Bearer 认证 token (空=跳过验证)
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

# ---- 配置 ----

PORT = int(os.environ.get("RAG_SERVICE_PORT", "9003"))
HOST = os.environ.get("RAG_SERVICE_HOST", "0.0.0.0")
SERVICE_AUTH_TOKEN = os.environ.get("SERVICE_AUTH_TOKEN", "")
SERVICE_VERSION = "1.0.0"
MODEL_NAME = "bge-m3 + bge-reranker-v2-m3"
PROTOCOL_VERSION = 1

# ---- 结构化日志 ----

logger.remove()
logger.add(
    sys.stderr,
    level=os.environ.get("RAG_LOG_LEVEL", "INFO"),
    format=(
        "<green>{time:MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}:{function}:{line}</cyan> - {message}"
    ),
)
logger.add(
    "logs/rag_debug_{time:YYYY-MM-DD}.log",
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

# ---- 引擎状态 ----

_engine: Any = None
_engine_lock = threading.Lock()
_engine_loaded = False
_engine_error: str | None = None


def _load_engine_background():
    """后台线程预加载 RAG 引擎(Chroma+BM25+reranker)。"""
    global _engine, _engine_loaded, _engine_error
    try:
        from app.rag.corpus import RagLibrary
        from app.rag.engine import RagEngine

        logger.info("rag_engine_begin · 正在加载 RAG 引擎(Chroma+BM25+reranker)")
        t0 = time.perf_counter()
        engine = RagEngine()
        # 触发懒加载:embedder + 两库 BM25
        engine.retrieve("启动预热", k=1, library=RagLibrary.KNOWLEDGE)
        engine.retrieve("启动预热", k=1, library=RagLibrary.CASE)
        with _engine_lock:
            _engine = engine
            _engine_loaded = True
            MODEL_READY.set(1)
        elapsed = time.perf_counter() - t0
        logger.info(f"rag_engine_ready · RAG 引擎已加载({elapsed:.1f}s)")
    except Exception as exc:  # noqa: BLE001
        import traceback
        with _engine_lock:
            _engine_error = str(exc)
        MODEL_READY.set(0)
        logger.error(f"rag_engine_failed · {exc}\n{traceback.format_exc()}")


def _get_engine():
    """获取 RAG 引擎(同步)。"""
    with _engine_lock:
        if _engine is None:
            raise RuntimeError("RAG 引擎未就绪")
        return _engine


# ---- FastAPI App ----


@asynccontextmanager
async def lifespan(_application: FastAPI):
    logger.info("startup_begin · RAG Service 启动中")
    threading.Thread(target=_load_engine_background, daemon=True).start()
    yield
    logger.info("shutdown · RAG Service 关停")


app = FastAPI(title="hrp-rag", version=SERVICE_VERSION, lifespan=lifespan)

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
    return {"status": "ok", "service": "hrp-rag"}


@app.get("/ready")
async def ready():
    with _engine_lock:
        is_ready = _engine_loaded
        error = _engine_error
    if not is_ready:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "error": error, "version": PROTOCOL_VERSION},
        )
    return {"ready": True, "error": None, "version": PROTOCOL_VERSION}


@app.get("/v1/health")
async def health():
    with _engine_lock:
        is_ready = _engine_loaded
        error = _engine_error
    return {
        "status": "ok",
        "service": "hrp-rag",
        "version": SERVICE_VERSION,
        "model": MODEL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "ready": is_ready,
        "error": error,
        "gpu": False,
        "uptime_s": round(time.time() - _start_time),
    }


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="检索查询文本")
    k: int | None = Field(None, ge=1, le=20, description="返回条数(None=使用默认配置)")
    library: str = Field("case", description="检索库: knowledge / case")


class RefDict(BaseModel):
    id: str
    question: str
    answer: str
    score: float = 0.0
    category: str | None = None


class RetrieveResponse(BaseModel):
    refs: list[RefDict]


@app.post("/v1/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest, request: Request):
    request_id = getattr(request.state, "request_id", "unknown")

    with _engine_lock:
        is_ready = _engine_loaded
    if not is_ready:
        return JSONResponse(status_code=503, content={"error": "RAG 引擎未就绪", "code": "rag_unavailable"})

    # 校验 library 参数
    from app.rag.corpus import RagLibrary

    try:
        lib = RagLibrary(req.library)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"无效的 library: {req.library}", "code": "invalid_library"},
        )

    t0 = time.perf_counter()
    try:
        engine = _get_engine()
        refs = engine.retrieve(req.query, req.k, library=lib)
    except Exception as exc:  # noqa: BLE001
        logger.bind(request_id=request_id, event="retrieve_error", detail=str(exc)[:200]).error("retrieve_error")
        return JSONResponse(status_code=500, content={"error": str(exc)[:200], "code": "retrieve_failed"})

    elapsed = time.perf_counter() - t0
    INFERENCE_LATENCY.labels(model=MODEL_NAME).observe(elapsed)

    logger.bind(
        request_id=request_id,
        event="retrieve",
        latency_ms=round(elapsed * 1000, 1),
        query_length=len(req.query),
        k=req.k,
        library=req.library,
        result_count=len(refs),
    ).info("retrieve")

    return RetrieveResponse(
        refs=[
            RefDict(
                id=r.id,
                question=r.question,
                answer=r.answer,
                score=r.score,
                category=r.category,
            )
            for r in refs
        ]
    )


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

    logger.info(f"starting · RAG Service on {HOST}:{PORT}")
    uvicorn.run(
        "app.rag_service.server:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
