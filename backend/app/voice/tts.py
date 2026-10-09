"""TTS 路由层:按 TTS_MODE 选择 local (sidecar 子进程) 或 remote (HTTP 远程服务)。

gateway.py / fillers.py 的 import 路径不变(app.voice.tts),
本模块透明切换底层实现。

本地模式:原有 sidecar 逻辑不变。
远程模式:HTTP 调用 TTS Service,不加载 CosyVoice 模型。
"""

from __future__ import annotations

from app import config

# 异常类模块级导入:两个模式共用同一组类,且对 gateway 始终是模块属性。
# 放在各分支内部的话,gateway 里的 tts.TTSCancelled 会被 mypy 判为无此属性。
# TTSCancelled 在本模块内没有引用点 —— 它是给 gateway 用的再导出,
# ruff 的 F401 会把"本文件没用到"误判成死代码,所以显式 noqa。
from app.voice.tts_errors import TTSCancelled, TTSError  # noqa: F401

if config.TTS_MODE == "remote":
    from app.voice.tts_client import (
        cancel,
        synthesize,
        synthesize_stream,
        synthesize_stream_detailed,
    )
else:
    # ---- local mode:原有 sidecar 实现(内联,避免循环导入) ----

    import base64
    import json
    import subprocess
    import threading
    import time
    import urllib.error
    import urllib.request
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Any

    from app import logger as app_logger
    from app.voice.sidecar_protocol import SIDECAR_VERSION

    logger = app_logger.logger.bind(service=app_logger.SERVICE, module="tts")

    _spawned: subprocess.Popen[bytes] | None = None
    """自己拉起的 sidecar 句柄(有序关停用;外部手动启动的进程不持有)"""

    _stopping = False
    """关停旗标:shutdown 后 warmup 线程不可取消(to_thread),靠旗标阻止其拉起孤儿进程"""

    _spawn_lock = threading.Lock()
    """拉起互斥(D2):warmup 与首次合成的并发窗口防双 spawn——句柄被覆盖会漏杀孤儿进程"""

    def _base() -> str:
        return f"http://127.0.0.1:{config.TTS_SIDECAR_PORT}"

    def _probe() -> dict[str, Any] | None:
        """探活 /health;None=进程不可达。"""
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
        """lifespan 关停:terminate 自己拉起的 sidecar。"""
        global _stopping
        _stopping = True
        if not config.TTS_SIDECAR_KILL_ON_EXIT:
            return
        _terminate_spawned()

    def ensure_sidecar(timeout_s: float | None = None) -> bool:
        """sidecar 就绪(必要时拉起);False=不可用。"""
        if timeout_s is None:
            timeout_s = config.TTS_SIDECAR_READY_TIMEOUT_S

        global _spawned
        if _stopping:
            return False
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

        if _spawned is None or _spawned.poll() is not None:
            with _spawn_lock:
                if _spawned is not None and _spawned.poll() is None:
                    pass
                elif _stopping:
                    return False
                else:
                    python = Path(config.TTS_SIDECAR_PYTHON)
                    if not python.exists():
                        logger.warning("tts_sidecar_missing_python", path=str(python))
                        return False
                    script = Path(__file__).parent / "tts_sidecar.py"
                    creationflags = (
                        subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
                    )
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

    def synthesize_stream_detailed(
        text: str, *, request_id: str | None = None
    ) -> Iterator[bytes]:
        """与 remote 模式同签名。sidecar 不支持打断,request_id 被忽略。"""
        if not text.strip():
            return
        yield from synthesize_stream(text, request_id=request_id)

    def cancel(request_id: str, *, cascade: bool = True) -> dict:
        """sidecar 无打断能力,恒返回未打断。

        保留这个函数是为了让 gateway 不必关心当前跑的是哪种模式;
        local 模式下"打断"退化为只停发帧(_speak_stream 的 dead 判定),
        服务端那一层本来也已经在算了。
        """
        return {"round_id": request_id, "cancelled": False, "reason": "sidecar_no_cancel"}

    def synthesize_stream(
        text: str, *, request_id: str | None = None
    ) -> Iterator[bytes]:
        """文本 → 逐句 wav 字节流(POST /tts_stream NDJSON);失败抛 TTSError。
        sidecar 不支持打断,request_id 被忽略(签名与 remote 模式对齐)。"""
        if not text.strip():
            return
        if not ensure_sidecar():
            raise TTSError("sidecar 不可用")
        req = urllib.request.Request(
            f"{_base()}/tts_stream",
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for line in resp:
                    piece = json.loads(line.decode())["wav"]
                    yield base64.b64decode(piece)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            raise TTSError(str(exc)[:160]) from exc

    def synthesize(text: str, *, request_id: str | None = None) -> bytes | None:
        """文本 → 拼接整段 wav bytes;失败 WARN 降级 None。"""
        if not text.strip():
            return None
        try:
            return b"".join(synthesize_stream(text, request_id=request_id))
        except TTSError as exc:
            logger.warning("tts_degraded", reason=str(exc)[:160])
            return None
