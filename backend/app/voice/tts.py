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
from typing import Any

from app import config
from app import logger as app_logger
from app.voice.sidecar_protocol import SIDECAR_VERSION

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="tts")

_spawned: subprocess.Popen[bytes] | None = None
"""自己拉起的 sidecar 句柄(有序关停用;外部手动启动的进程不持有)"""

_stopping = False
"""关停旗标:shutdown 后 warmup 线程不可取消(to_thread),靠旗标阻止其拉起孤儿进程"""


def _base() -> str:
    # 调用时读 config(测试 monkeypatch 端口可生效;import 时绑定会打死)
    return f"http://127.0.0.1:{config.TTS_SIDECAR_PORT}"


def _probe() -> dict[str, Any] | None:
    """探活 /health;None=进程不可达。响应含 ready/error/version 三字段。"""
    try:
        with urllib.request.urlopen(f"{_base()}/health", timeout=3) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def spawned_process() -> subprocess.Popen[bytes] | None:
    return _spawned


def _terminate_spawned() -> None:
    global _spawned
    if _spawned is None or _spawned.poll() is not None:
        _spawned = None
        return
    _spawned.terminate()
    try:
        _spawned.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _spawned.kill()
    _spawned = None


def shutdown_spawned() -> None:
    """lifespan 关停:terminate 自己拉起的 sidecar;受 KILL_ON_EXIT 门控
    (--reload 开发置 0,免得热载陪杀模型);外部启动的进程不越权。
    先立旗标再杀:warmup 线程可能在 shutdown 落地后才走到 spawn 点。"""
    global _stopping
    _stopping = True
    if not config.TTS_SIDECAR_KILL_ON_EXIT:
        return
    _terminate_spawned()


def ensure_sidecar(timeout_s: float | None = None) -> bool:
    """sidecar 就绪(必要时拉起);False=不可用,本轮全部跳过音频。
    版本不匹配:自己拉起的杀掉重拉;外部进程只报错降级——不静默复用旧代码。"""
    if timeout_s is None:
        timeout_s = config.TTS_SIDECAR_READY_TIMEOUT_S

    global _spawned
    if _stopping:
        return False  # 已关停:warmup 线程赛跑输给 shutdown,不再拉起
    payload = _probe()
    if payload is not None:
        if payload.get("version") != SIDECAR_VERSION:
            if _spawned is not None and _spawned.poll() is None:
                logger.warning(
                    "tts_sidecar_version_respawn",
                    expected=SIDECAR_VERSION,
                    running=payload.get("version"),
                )
                _terminate_spawned()
            else:
                logger.error(
                    "tts_sidecar_version_mismatch",
                    expected=SIDECAR_VERSION,
                    running=payload.get("version"),
                    hint="9880 被旧版 sidecar 占用:重启它,或用当前代码手动拉起",
                )
                return False
        if payload.get("ready"):
            return True
        # 进程在但模型加载中 → 落到下方等待循环

    if _spawned is None or _spawned.poll() is not None:
        if _stopping:
            return False
        python = Path(config.TTS_SIDECAR_PYTHON)
        if not python.exists():
            logger.warning("tts_sidecar_missing_python", path=str(python))
            return False
        script = Path(__file__).parent / "tts_sidecar.py"
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        _spawned = subprocess.Popen(
            [str(python), str(script)],
            cwd=str(script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        logger.info("tts_sidecar_spawned", port=config.TTS_SIDECAR_PORT)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _stopping:
            return False
        payload = _probe()
        if (
            payload is not None
            and payload.get("ready")
            and payload.get("version") == SIDECAR_VERSION
        ):
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
