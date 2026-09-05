"""入口装配(backend-plan §2):挂 /ws·/station·/admin;启动应用持久模型配置;
CORS 白名单放行前端 dev 跨源访问 REST(WS 无同源约束)。"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app import admin, config
from app.logger import setup_logger
from app.station import router as station_router
from app.ws_gateway import handle_connection

setup_logger(verbose=os.getenv("HRP_VERBOSE") == "1")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    admin.load_and_apply()  # 持久配置读回应用;无配置/失败 WARN 走 env
    yield


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
