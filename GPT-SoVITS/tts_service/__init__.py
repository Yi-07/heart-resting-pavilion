"""GPT-SoVITS 远程 TTS 服务。

与 api_v2.py 同级(仓库根目录),作为 backend `tts_service` 的可替换实现:
线格式、端点、环境变量全部对齐,切换只需停旧起新,主服务零配置改动。

启动(工作目录必须是 GPT-SoVITS 根,服务内部也会自行 chdir):

    python -m tts_service
    python -m tts_service --port 9001
    python -m tts_service --check      # 只做输入守卫自检,不加载模型
"""

from __future__ import annotations

from typing import Any

SERVICE_NAME = "hrp-tts"
SERVICE_VERSION = "1.0.0"
PROTOCOL_VERSION = 2
"""线协议版本,与 backend/app/voice/tts_service/protocol.py 的 SIDECAR_VERSION 对齐。"""

MODEL_NAME = "GPT-SoVITS-v2"

__all__ = [
    "MODEL_NAME",
    "PROTOCOL_VERSION",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "app",
    "main",
]


def __getattr__(name: str) -> Any:
    """延迟暴露 app / main,避免 `import tts_service` 就拖起 FastAPI 与模型依赖。"""
    if name == "app":
        from .server import app as _app

        return _app
    if name == "main":
        from .__main__ import main as _main

        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
