"""ASR 远程客户端:通过 HTTP 调用远程 ASR Service。

接口与 asr.py 完全兼容(transcribe / ASRError),
routes.py 通过 asr.py 路由层透明切换,无需修改。

超时策略:
- transcribe: 整体超时 30s
- health/ready: 3s 快速探活
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

from app import config
from app import logger as app_logger
from app.voice.asr_errors import ASRError

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="asr_client")

__all__ = ["ASRError", "health", "ready", "transcribe"]


def _base() -> str:
    return config.ASR_SERVICE_URL.rstrip("/")


def _headers(request_id: str | None = None) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if config.SERVICE_AUTH_TOKEN:
        h["Authorization"] = f"Bearer {config.SERVICE_AUTH_TOKEN}"
    if request_id:
        h["X-Request-ID"] = request_id
    return h


def health() -> dict | None:
    """探活 /v1/health;None=不可达。"""
    try:
        with urllib.request.urlopen(f"{_base()}/v1/health", timeout=3) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def ready() -> bool:
    """就绪探针 /ready;True=模型可推理。"""
    try:
        with urllib.request.urlopen(f"{_base()}/ready", timeout=3) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except (urllib.error.URLError, OSError):
        return False


def transcribe(audio: bytes, *, request_id: str | None = None) -> str:
    """音频字节 → 文本;空串=无语音内容。同步阻塞。

    发送 base64 编码音频到远程 ASR Service,返回转写文本。
    失败抛 ASRError。
    """
    if not audio:
        return ""
    req_id = request_id or f"req_{int(time.time() * 1000)}"
    body = json.dumps({"audio": base64.b64encode(audio).decode("ascii")}).encode()
    req = urllib.request.Request(
        f"{_base()}/v1/transcribe",
        data=body,
        headers=_headers(req_id),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.ASR_SERVICE_TIMEOUT_S) as resp:
            result = json.loads(resp.read().decode())
            return result.get("text", "")
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode()[:200]
        except Exception:  # noqa: BLE001, S110
            pass
        if exc.code == 503:
            raise ASRError(f"ASR 服务不可用: {err_body}") from exc
        raise ASRError(f"HTTP {exc.code}: {err_body}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ASRError(f"连接失败: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise ASRError(f"响应解析失败: {exc}") from exc
