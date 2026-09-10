"""入口装配(backend-plan §2):挂 /ws·/station·/admin;启动应用持久模型配置;
CORS 白名单放行前端 dev 跨源访问 REST(WS 无同源约束)。
进程编排:startup 后台拉起 TTS sidecar(模型加载分钟级,不阻塞文字链路),
shutdown 有序关停自己拉起的子进程(外部启动的不越权,版本握手防旧进程静默复用)。"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app import admin, config
from app import logger as app_logger
from app.logger import setup_logger
from app.station import router as station_router
from app.ws_gateway import handle_connection

setup_logger(verbose=os.getenv("HRP_VERBOSE") == "1")
_logger = app_logger.logger.bind(service=app_logger.SERVICE, module="main")


async def _warm_sidecar() -> None:
    """后台拉起 sidecar 并等 ready(超时=配置上限);失败只 WARN,TTS 降级、回合照常。
    懒导入:语音模块只在 warmup 路径进内存,网关/REST 启动零成本。"""
    from app.voice import tts

    try:
        ok = await asyncio.to_thread(tts.ensure_sidecar)
    except Exception as exc:  # noqa: BLE001 — 拉起链路任何意外都不挡主进程
        _logger.warning("tts_sidecar_warm_error", detail=str(exc)[:160])
        return
    if ok:
        _logger.info("tts_sidecar_warm_ready", port=config.TTS_SIDECAR_PORT)
    else:
        _logger.warning(
            "tts_sidecar_warm_failed",
            port=config.TTS_SIDECAR_PORT,
            hint="TTS 将降级跳过;文字链路不受影响,详见上方 sidecar 日志",
        )


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    admin.load_and_apply()  # 持久配置读回应用;无配置/失败 WARN 走 env
    warm = asyncio.create_task(_warm_sidecar())
    yield
    warm.cancel()  # 没就绪就退了:不再等
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


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await handle_connection(websocket)
