"""入口装配(backend-plan §2):挂 /ws·/station·/admin·/asr;启动应用持久模型配置;
CORS 白名单放行前端 dev 跨源访问 REST(WS 无同源约束)。
进程编排:startup 后台拉起 TTS sidecar(模型加载分钟级,不阻塞文字链路),
shutdown 有序关停自己拉起的子进程(外部启动的不越权,版本握手防旧进程静默复用)。"""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app import admin, config
from app import logger as app_logger
from app.logger import setup_logger
from app.memory import get_memory
from app.station import router as station_router
from app.station.reports import get_reports
from app.voice.routes import router as asr_router
from app.ws_gateway import handle_connection

setup_logger(verbose=os.getenv("HRP_VERBOSE") == "1")
_logger = app_logger.logger.bind(service=app_logger.SERVICE, module="main")


async def _warm_sidecar() -> None:
    """后台拉起 sidecar 并等 ready(超时=配置上限);失败只 WARN,TTS 降级、回合照常。
    懒导入:语音模块只在 warmup 路径进内存,网关/REST 启动零成本。"""
    from app.voice import tts

    _logger.info("tts_sidecar_warm_begin · 正在拉起 TTS sidecar")
    t0 = time.perf_counter()
    try:
        ok = await asyncio.to_thread(tts.ensure_sidecar)
    except Exception as exc:  # noqa: BLE001 — 拉起链路任何意外都不挡主进程
        _logger.warning("tts_sidecar_warm_error · TTS sidecar 拉起异常",
                        detail=str(exc)[:160])
        return
    elapsed = round(time.perf_counter() - t0, 1)
    if ok:
        _logger.info(f"tts_sidecar_warm_ready · TTS sidecar 已就绪(port {config.TTS_SIDECAR_PORT},"
                     f"{elapsed}s)")
    else:
        _logger.warning(
            "tts_sidecar_warm_failed · TTS sidecar 未就绪",
            port=config.TTS_SIDECAR_PORT,
            elapsed_s=elapsed,
        )


async def _check_tts_ready() -> None:
    """远程 TTS 就绪检查:等待远程服务模型加载完成;失败只 WARN,TTS 降级。"""
    from app.voice import tts_client

    _logger.info(f"tts_remote_warm_begin · 正在检查远程 TTS ({config.TTS_SERVICE_URL})")
    t0 = time.perf_counter()
    try:
        ok = await asyncio.to_thread(tts_client.wait_ready, 60.0)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("tts_remote_warm_error · 远程 TTS 检查异常",
                        detail=str(exc)[:160])
        return
    elapsed = round(time.perf_counter() - t0, 1)
    if ok:
        _logger.info(f"tts_remote_warm_ready · 远程 TTS 已就绪({config.TTS_SERVICE_URL}, {elapsed}s)")
    else:
        _logger.warning(
            "tts_remote_warm_failed · 远程 TTS 未就绪",
            url=config.TTS_SERVICE_URL,
            elapsed_s=elapsed,
        )


async def _warm_rag() -> None:
    """后台预热 RAG(模型/索引加载 ~18s 级,ADR-003:禁止请求路径同步加载)。
    失败只 WARN:检索请求 2s 等不到就绪即降级直答,文字链路不受影响。"""
    from app.rag import warm

    _logger.info("rag_warm_begin · 正在预热 RAG 检索库")
    t0 = time.perf_counter()
    try:
        await asyncio.to_thread(warm)
    except Exception as exc:  # noqa: BLE001 — 预热失败不挡主进程
        _logger.warning("rag_warm_failed · RAG 预热失败",
                        detail=str(exc)[:160])
        return
    _logger.info(f"rag_warm_ready · RAG 检索库预热完成({time.perf_counter() - t0:.1f}s)")


async def _loop_watchdog() -> None:
    """事件循环阻塞看门狗(ADR-003):lag>2s 记 WARN。RAG 冷启动静默断连的
    教训——同步调用堵 loop 时超时/降级机制全部失灵,唯一可靠信号是时钟漂移。"""
    _logger.info("watchdog_on · 事件循环监控已启动")
    while True:
        t0 = time.perf_counter()
        await asyncio.sleep(1)
        lag = time.perf_counter() - t0 - 1
        if lag > 2:
            _logger.warning(
                "event_loop_lag", lag_s=round(lag, 2),
                hint="某处同步调用阻塞了事件循环,按时间戳查同时刻调用栈",
            )


_REPORT_GC_INTERVAL_S = 6 * 3600
"""报告过期清理周期;启动时另扫一次(含遗留核价)。"""


async def _report_gc_once(*, refine: bool) -> None:
    """方案书过期清理：先查拦截(get_active/list_by_session 已过滤)，这里做物理删除。

    refine=True(仅启动时)：给升级遗留行(expires_at IS NULL)核价——旧素材 Redis TTL
    可复原原始到期时刻；不可核验且 Redis 不可达则保持未定价(不猜不删，下次启动重试)。
    任何失败只 WARN，不挡启动/服务。"""

    try:
        reports = get_reports()
        if refine:
            counts = await reports.refine_legacy_expiry(get_memory().legacy_station_deadline)
            if counts["priced"] or counts["expired"]:
                _logger.info("station_legacy_refined", **counts)
            # 旧式标题(「第 N 次梳理」)重算为数据驱动标题(情境 · 情绪):
            # 素材可得→用其 formulation 推导;不可得→中性备用标题。只改 title,不动正文、不删行。
            titles = await reports.backfill_legacy_titles(get_memory().load_station_input)
            if titles["retitled"] or titles["fallback"]:
                _logger.info("station_titles_backfilled", **titles)
        removed = reports.delete_expired()
        if removed:
            _logger.info("station_reports_gc", removed=removed)
    except Exception as exc:  # noqa: BLE001 — 清理失败不影响服务
        _logger.warning("station_report_gc_error", reason=type(exc).__name__)


async def _report_gc_loop() -> None:
    while True:
        await asyncio.sleep(_REPORT_GC_INTERVAL_S)
        await _report_gc_once(refine=False)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    _logger.info("startup_begin · 心栖阁 backend 启动中")
    admin.load_and_apply()  # 持久配置读回应用;无配置/失败 WARN 走 env
    if await get_memory().ping():
        _logger.info("memory_ready · Redis 连接正常")
    else:
        _logger.warning("memory_ping_failed · Redis 连接失败")
    # TTS: remote 模式检查远程服务就绪;local 模式拉起 sidecar
    if config.TTS_MODE == "remote":
        warm = asyncio.create_task(_check_tts_ready())
    else:
        warm = asyncio.create_task(_warm_sidecar())
    rag_warm = asyncio.create_task(_warm_rag())
    watchdog = asyncio.create_task(_loop_watchdog())
    # 方案书过期清理：先核价+扫一遍(先于服务)，再挂周期任务
    await _report_gc_once(refine=True)
    report_gc = asyncio.create_task(_report_gc_loop())
    _logger.info("startup_ready · 文字链路已就绪")
    yield
    warm.cancel()  # 没就绪就退了:不再等
    rag_warm.cancel()
    watchdog.cancel()
    report_gc.cancel()
    # local 模式才关停 sidecar;remote 模式不持有子进程
    if config.TTS_MODE != "remote":
        from app.voice import tts  # 懒加载(同 warmup)

        tts.shutdown_spawned()


app = FastAPI(title="心栖阁 backend", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(station_router)
app.include_router(admin.router)
app.include_router(asr_router)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await handle_connection(websocket)
