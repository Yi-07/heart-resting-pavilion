"""TTS 客户端:懒拉起 CosyVoice sidecar 并经 HTTP 合成。

- ensure_sidecar:探活 → 不在则用 CosyVoice venv python 起 tts_sidecar.py → 等 ready
- synthesize(text) → wav bytes | None(任何失败 WARN 降级返回 None,调用方跳过音频、
  文字链路照常——契约原则:失败跳过音频不阻塞回合)
- 同步阻塞(网关用 asyncio.to_thread 调);urllib stdlib 零新依赖
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from app import config
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="tts")

def _base() -> str:
    # 调用时读 config(测试 monkeypatch 端口可生效;import 时绑定会打死)
    return f"http://127.0.0.1:{config.TTS_SIDECAR_PORT}"


def _health(ready_required: bool) -> bool:
    try:
        with urllib.request.urlopen(f"{_base()}/health", timeout=3) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return False
    if ready_required:
        return bool(data.get("ready"))
    return data.get("error") is None or bool(data.get("ready"))


def ensure_sidecar(timeout_s: float | None = None) -> bool:
    """sidecar 就绪(必要时拉起);False=不可用,本轮全部跳过音频。"""
    if timeout_s is None:
        timeout_s = config.TTS_SIDECAR_READY_TIMEOUT_S
    if _health(ready_required=True):
        return True
    if _health(ready_required=False):
        pass  # 进程在但模型加载中 → 直接进入等待
    else:
        python = Path(config.TTS_SIDECAR_PYTHON)
        if not python.exists():
            logger.warning("tts_sidecar_missing_python", path=str(python))
            return False
        script = Path(__file__).parent / "tts_sidecar.py"
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        subprocess.Popen(
            [str(python), str(script)],
            cwd=str(script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        logger.info("tts_sidecar_spawned", port=config.TTS_SIDECAR_PORT)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _health(ready_required=True):
            return True
        time.sleep(1.0)
    logger.warning("tts_sidecar_not_ready", timeout_s=timeout_s)
    return False


def synthesize(text: str) -> bytes | None:
    """文本 → wav bytes;失败 None(降级跳过音频)。同步阻塞。"""
    if not text.strip():
        return None
    try:
        if not ensure_sidecar():
            return None
        req = urllib.request.Request(
            f"{_base()}/tts",
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001 — TTS 任何失败都降级,不杀回合
        logger.warning("tts_degraded", reason=str(exc)[:160])
        return None
