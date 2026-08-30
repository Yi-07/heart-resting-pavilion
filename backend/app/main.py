"""入口装配(backend-plan §2):挂 /ws;admin/station 随步骤 9 接入。"""

import os

from fastapi import FastAPI, WebSocket

from app.logger import setup_logger
from app.ws_gateway import handle_connection

setup_logger(verbose=os.getenv("HRP_VERBOSE") == "1")

app = FastAPI(title="心栖阁 backend", version="0.1.0")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await handle_connection(websocket)
