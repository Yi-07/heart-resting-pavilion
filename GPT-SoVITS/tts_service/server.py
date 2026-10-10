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

from . import MODEL_NAME, PROTOCOL_VERSION, SERVICE_NAME, SERVICE_VERSION, bench
from .engine import EngineBusy, GuardError, TTSEngine
from .logger import event, setup_logging
from .settings import get_settings

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
CHUNKS_TOTAL = Counter("tts_chunks_total", "产出 PCM chunk 数")
AUDIO_BYTES_TOTAL = Counter("tts_audio_bytes_total", "产出音频字节数")
CANCEL_TOTAL = Counter("tts_cancel_total", "打断次数", ["scope"])
ERROR_TOTAL = Counter("tts_errors_total", "错误数", ["kind"])
TTFB = Histogram(
    "tts_ttfb_seconds", "请求开始 → 第一块 PCM 发出", ["stage"],
    buckets=(0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 5.0, 8.0, 12.0),
)
"""plan §36:stage=ttfb 与 stage=total **分离记录**。

混在一个 histogram 里没法回答「是首包慢还是整体慢」——而这两者的修法完全不同。
"""
STREAM_LATENCY = Histogram(
    "tts_request_latency_seconds_total", "请求开始 → 整条流结束",
    buckets=(0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 60.0, 120.0),
)
CHUNK_INTERVAL = Histogram(
    "tts_chunk_interval_seconds", "相邻 chunk 的到达间隔",
    buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6),
)
CHUNK_DURATION = Histogram(
    "tts_chunk_duration_seconds", "单块 PCM 的音频时长",
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 4.0),
)
HEALTH_LATENCY = Histogram(
    "tts_health_handler_seconds", "/v1/health handler 内部耗时",
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
"""health 的服务端内部耗时(plan §36 F3)。

分桶下探到 0.5ms:这个 handler 现在只读内存,正常应在 1ms 以内;
一旦上到几十毫秒,说明 GPU 轮询缓存或 snapshot 被什么东西拖住了。
"""
GPU_MEMORY_USED = Gauge("tts_gpu_memory_used_bytes", "显存占用", ["device"])
GPU_UTILIZATION = Gauge("tts_gpu_utilization_percent", "GPU 利用率", ["device"])
SERVICE_UPTIME = Gauge("tts_service_uptime_seconds", "服务运行时长")

_START_TIME = time.time()
_cfg = get_settings()

# 日志唯一初始化点。放这里而不是 __main__.py:两条启动路径都会导入本模块
# (`python -m tts_service` 与 `uvicorn tts_service.server:app`),放这里才都覆盖得到;
# 放两处会在启动过程中反复 remove/re-add sink。
# base_dir 传 _cfg.root:log_dir 的相对路径锚定仓库根,不依赖进程 cwd。
setup_logging(
    level=_cfg.log_level,
    log_dir=_cfg.log_dir,
    rotation=_cfg.log_rotation,
    retention=_cfg.log_retention,
    file_level=_cfg.log_file_level,
    base_dir=_cfg.root,
)

engine = TTSEngine(_cfg)


# ---- GPU 监控 ----
_gpu_state: dict[str, Any] = {
    "available": False,
    "checked_at": 0.0,
    "samples": 0,
    "last_error": None,
}
"""GPU 状态的**轮询缓存**(plan §36)。

/v1/health 之前在请求内同步跑一次 nvidia-smi(5s 超时),于是:
    - health 延迟被 nvidia-smi 的冷启动拖到秒级;
    - nvidia-smi 卡住 = health 跟着卡住,探活失去意义。
改成后台线程轮询 + 请求只读缓存后,health 的成本是一次 dict 读取。
"""


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
            _gpu_state["available"] = True
            _gpu_state["samples"] = int(_gpu_state["samples"]) + 1
            _gpu_state["last_error"] = None
        except Exception as exc:  # noqa: BLE001 — GPU 不可用时静默,只留状态
            _gpu_state["last_error"] = f"{type(exc).__name__}: {exc}"[:120]
        _gpu_state["checked_at"] = time.time()
        time.sleep(10)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    event("startup_begin", stage="lifespan")
    threading.Thread(target=engine.load, name="model-load", daemon=True).start()
    if _cfg.gpu_poll_enabled:
        threading.Thread(target=_collect_gpu_stats, name="gpu-poll", daemon=True).start()
    else:
        # off 档(plan §36 F1):完全不执行 nvidia-smi。health 仍可应答,
        # 只是 gpu 字段永远为 False —— 那是"没采",不是"没卡"。
        _gpu_state["last_error"] = "gpu poll disabled by config"
        event("gpu_poll_disabled", stage="lifespan")
    yield
    event("shutdown", stage="lifespan")


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
        event("unhandled_error", level="ERROR", request_id=request_id,
              exc=exc, detail=str(exc)[:200])
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
    event(
        "request_done",
        request_id=request_id,
        method=request.method,
        path=path,
        status=response.status_code,
        latency_ms=round(elapsed * 1000, 1),
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
    """详细状态。**不再在请求内同步调用 nvidia-smi**(plan §36 F2),只读轮询缓存。

    latency_ms 报的是**本 handler 内部**耗时(plan §36 F3)。它与客户端实测的
    端到端延迟不同 —— 后者还含 HTTP 栈与事件循环调度。两者的差值本身就是有用的
    信号:差值大说明瓶颈在服务外(连接、GC、事件循环被推理线程挤占)。
    """
    t0 = time.perf_counter()
    snap = engine.snapshot()
    latency_ms = round((time.perf_counter() - t0) * 1000, 3)
    HEALTH_LATENCY.observe(latency_ms / 1000)
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "model": MODEL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "ready": snap["ready"],
        "error": snap["error"],
        # 兼容旧字段名 gpu;值来自缓存,不再是「此刻现查一次」
        "gpu": bool(_gpu_state["available"]),
        "gpu_samples": _gpu_state["samples"],
        "gpu_checked_at": _gpu_state["checked_at"],
        "gpu_last_error": _gpu_state["last_error"],
        "latency_ms": latency_ms,
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


class TTSRequestV2(TTSRequest):
    """/v2 请求体:在 /v1 的 text + voice 之上**必须**带 round_id(plan §10.2)。

    强制 `X-Request-ID == Body.round_id`。理由不是形式主义:打断是按 round_id
    命中的,请求头与请求体给两个不同的值时,打断要么打不中(排队继续出声),
    要么打中别人(跨 round 误伤)。所以不一致直接拒绝,连推理都不进。
    """

    round_id: str = Field(
        ...,
        description="回合 id,必须与 X-Request-ID 头一致",
        examples=["tts-7"],
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
        # 守一次,把切好的句交给 engine(plan §36 H3)。engine 内部不再重复守。
        guarded = engine.prepare(req.text)
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
                    req.text,
                    round_id=round_id,
                    voice=voice,
                    guarded=guarded,
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
                event("synth_error", level="ERROR", round_id=round_id,
                      exc=item, detail=str(item)[:200])
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


@app.post("/v2/tts/stream")
async def tts_stream_v2(req: TTSRequestV2, request: Request):
    """NDJSON 实时 PCM16 流(plan §10.2 / §11)。

    与 /v1 的差别只有「交付时机」:/v1 等整句齐了给一个完整 wav,
    /v2 一块 PCM16 给一块,前端据此边合成边播。音色/语速由同一段推理保证一致。

    帧类型:
        {"type":"audio",         round_id, seq, sentence_index, sample_rate,
                                channels, format, pcm}   一块 PCM16(base64)
        {"type":"sentence_end",  round_id, sentence_index} 一句结束
        {"type":"end",           round_id}                正常收尾
        {"type":"error",         round_id, code, message}
        {"type":"cancelled",     round_id}                被打断且未产出任何块
    `end` 与 `cancelled` 互斥。
    """
    header_round = getattr(request.state, "request_id", "")
    body_round = req.round_id.strip()

    # plan §14.1:Header/Body 不一致 → 立即拒绝,不创建推理执行
    if header_round != body_round:
        bench.mark(
            bench.PROTOCOL_MISMATCH,
            round_id=body_round,
            stage="v2_request",
            header=header_round,
            body=body_round,
        )
        event("round_id_mismatch", level="ERROR", round_id=body_round,
              header=header_round, body=body_round)
        ERROR_TOTAL.labels(kind="round_id_mismatch").inc()
        return JSONResponse(
            status_code=400,
            content={
                "error": "X-Request-ID 与 body.round_id 不一致",
                "code": "round_id_mismatch",
                "header_round_id": header_round,
                "body_round_id": body_round,
            },
        )

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
        # 守一次,句交给 engine(plan §36 H3)
        guarded = engine.prepare(req.text)
    except GuardError as exc:
        ERROR_TOTAL.labels(kind="guard").inc()
        return JSONResponse(
            status_code=400, content={"error": str(exc), "code": exc.code}
        )

    round_id = body_round
    voice = req.voice.strip() or None
    # P2 = server 收到 v2 请求(与 P1 client send 配对)
    bench.mark(bench.P2, round_id=round_id, endpoint="v2", hanzi=len(req.text))

    _t_req = time.perf_counter()

    async def _stream() -> AsyncIterator[str]:
        """同步推理进专用生产者线程,event loop 只做 queue.get()。

        /ready、/v1/health、/v1/tts/cancel 在合成期间仍能即时响应。
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        n_sent = 0
        bytes_out = 0
        last_seq = -1
        last_sentence = -1
        prev_emit: float | None = None

        def _produce() -> None:
            try:
                for item in engine.synthesize_pcm(
                    req.text,
                    round_id=round_id,
                    voice=voice,
                    guarded=guarded,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, item)
            except Exception as exc:  # noqa: BLE001 — 交给消费端输出错误行
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_produce, name=f"pcm-{round_id}", daemon=True).start()

        cancelled = False
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                ERROR_TOTAL.labels(kind="synth").inc()
                event("pcm_synth_error", level="ERROR", round_id=round_id,
                      exc=item, detail=str(item)[:200])
                yield json.dumps(
                    {"type": "error", "code": "synth_failed",
                     "message": str(item)[:200], "round_id": round_id},
                    ensure_ascii=False,
                ) + "\n"
                return

            # plan §14.2:同一 request 内 frame.round_id 与 request 不一致 = 协议错误,
            # 不是可静默丢弃的 stale frame。必须显式报错并终止该 stream。
            if item.round_id != round_id:  # pragma: no cover — 引擎侧保证不发生
                bench.mark(
                    bench.PROTOCOL_MISMATCH, round_id=round_id,
                    stage="v2_frame", frame_round_id=item.round_id,
                )
                ERROR_TOTAL.labels(kind="round_id_mismatch").inc()
                yield json.dumps(
                    {"type": "error", "code": "round_id_mismatch",
                     "message": f"frame round_id={item.round_id} != {round_id}",
                     "round_id": round_id},
                    ensure_ascii=False,
                ) + "\n"
                return

            # seq 单调递增、不重置(plan §15)
            assert item.seq == last_seq + 1, f"seq gap: {last_seq} → {item.seq}"
            last_seq = item.seq

            if item.is_first:
                # P6 = server 第一次把 PCM 发出去(P5 engine yield 之后的下一步)
                bench.mark(bench.P6, round_id=round_id, seq=item.seq)
                TTFB.labels(stage="ttfb").observe(time.perf_counter() - _t_req)

            frame = {
                "type": "audio",
                "round_id": round_id,
                "seq": item.seq,
                "sentence_index": item.sentence_index,
                "sample_rate": item.sample_rate,
                "channels": item.channels,
                "format": item.format,
                "pcm": base64.b64encode(item.pcm).decode("ascii"),
            }
            n_sent += 1
            bytes_out += len(item.pcm)
            AUDIO_BYTES_TOTAL.inc(len(item.pcm))
            CHUNK_DURATION.observe(item.duration_s)
            if prev_emit is not None:
                CHUNK_INTERVAL.observe(time.perf_counter() - prev_emit)
            prev_emit = time.perf_counter()

            yield json.dumps(frame, ensure_ascii=False) + "\n"
            bench.mark(bench.T5C, round_id=round_id, seq=item.seq)

            if item.sentence_index != last_sentence:
                # 上一句收尾(sentence_index 只会前进,故这里补的是"上一句的 end")
                if last_sentence >= 0:
                    yield json.dumps(
                        {"type": "sentence_end", "round_id": round_id,
                         "sentence_index": last_sentence},
                        ensure_ascii=False,
                    ) + "\n"
                last_sentence = item.sentence_index

        if n_sent == 0:
            cancelled = True
            yield json.dumps(
                {"type": "cancelled", "round_id": round_id}, ensure_ascii=False
            ) + "\n"
            CANCEL_TOTAL.labels(scope="round").inc()
        else:
            if last_sentence >= 0:
                yield json.dumps(
                    {"type": "sentence_end", "round_id": round_id,
                     "sentence_index": last_sentence},
                    ensure_ascii=False,
                ) + "\n"
            yield json.dumps(
                {"type": "end", "round_id": round_id}, ensure_ascii=False
            ) + "\n"

        CHUNKS_TOTAL.inc(n_sent)
        STREAM_LATENCY.observe(time.perf_counter() - _t_req)
        event(
            "v2_stream_done",
            round_id=round_id,
            chunks=n_sent,
            bytes=bytes_out,
            cancelled=cancelled,
            duration_ms=round((time.perf_counter() - _t_req) * 1000, 1),
        )

    _t_req = time.perf_counter()
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
    event(
        "cancel",
        round_id=req.round_id,
        state=result["state"],
        cascaded=len(result["cascaded"]),
        requester=requester,
    )
    return result


@app.get("/metrics")
async def metrics():
    SERVICE_UPTIME.set(time.time() - _START_TIME)
    return StreamingResponse(
        iter([generate_latest()]),
        media_type=CONTENT_TYPE_LATEST,
    )
