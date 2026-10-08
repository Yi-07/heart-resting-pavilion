"""TTS 远程客户端:通过 HTTP 调用远程 TTS Service。

接口与 tts.py 完全兼容(synthesize_stream / synthesize / TTSError),
gateway.py 通过 tts.py 路由层透明切换,无需修改。

流式链路契约(与 GPT-SoVITS/tts_service 一一对应):
    请求  POST /v1/tts/stream  {"text": "..."},X-Request-ID = round_id
    响应  NDJSON,逐行:
        {"wav": "<base64 完整 wav>", "round_id": "..."}   正常,一句一块
        {"error": "...", "code": "...", "round_id": "..."}  合成失败
        {"cancelled": true, "round_id": "..."}              被打断且一句未产出
    打断  POST /v1/tts/cancel  {"round_id": "...", "cascade": true}

    未知字段必须忽略:服务侧可能在同一行加新字段(向后兼容),
    不能因为多一个键就抛 KeyError。

超时策略:
- synthesize_stream: 首包超时 30s, 整体超时 600s
- synthesize: 整体超时 600s
- health/ready: 3s 快速探活
- cancel: 3s(抢占路径必须快,不能拖累下一轮)
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

from app import config, diag
from app import logger as app_logger
from app.voice.tts_errors import TTSCancelled, TTSError

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="tts_client")

__all__ = [
    "TTSCancelled",
    "TTSError",
    "cancel",
    "health",
    "ready",
    "synthesize",
    "synthesize_stream",
    "synthesize_stream_detailed",
    "wait_ready",
]


def _base() -> str:
    return config.TTS_SERVICE_URL.rstrip("/")


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
    except (urllib.error.URLError, OSError):
        return False
    except urllib.error.HTTPError as e:
        return e.code == 200


def wait_ready(timeout_s: float = 30.0) -> bool:
    """等待远程 TTS 就绪;False=超时。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(1.0)
    return False


_READ_BLOCK = 65536
"""流式读取的块大小(纯流式优化,不是任何延迟问题的根因)。

这里用「分块读 + 自己切行」而不是 `for line in resp`,是因为服务端是
StreamingResponse(chunked 编码),而 `HTTPResponse` 的逐行迭代在 chunked 下
走小缓冲路径。用 `read1` 而不是 `read`:后者在块读底层 socket 文件对象上会
**阻塞到凑满 n 字节**,短句响应会白等;`read1` 有多少读多少。

行到即出的流式语义不变(凑够一行就 yield)。

注意:曾经把"逐行读慢 4.4 倍"当成本次 TTFB 延迟的根因,那是**误判** ——
那次 A/B 比较里一边用 127.0.0.1、另一边用 localhost,把主机名解析的
2.1s 差读成了读取方式的开销。真正的根因见 .env 里 TTS_SERVICE_URL 的注释。
"""


def _parse_line(raw: bytes, req_id: str) -> bytes | None:
    """一行 NDJSON → wav bytes;None = 该行不产出音频(未知字段/空行)。

    返回 None 而不是抛异常,是为了向后兼容:服务侧在同一行加新字段时,
    客户端不能因为多一个键就炸掉。
    """
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    piece = json.loads(text)
    if piece.get("cancelled"):
        raise TTSCancelled(f"round {req_id} 被打断")
    if piece.get("error"):
        raise TTSError(str(piece["error"])[:160])
    wav = piece.get("wav")
    if not wav:
        return None
    echoed = piece.get("round_id")
    if echoed and echoed != req_id:
        logger.warning("tts_round_id_mismatch", want=req_id, got=echoed)
    return base64.b64decode(wav)


def synthesize_stream_detailed(text: str, *, request_id: str | None = None) -> Iterator[bytes]:
    """文本 → 逐句 wav;失败抛 TTSError,被打断抛 TTSCancelled。

    句子泵用这个:打断在服务端是"停止产出"而不是报错,只有在这里把 cancelled
    行翻译成异常,调用方才能区分"抢占"与"故障"。

    分块读 + 自己切行(见 _READ_BLOCK 的说明):既避开 chunked 响应逐行读的
    4.4 倍开销,又保持"一行到就吐一块",流式语义不变。
    """
    if not text.strip():
        return
    req_id = request_id or f"req_{int(time.time() * 1000)}"
    req = urllib.request.Request(
        f"{_base()}/v1/tts/stream",
        data=json.dumps({"text": text}).encode(),
        headers=_headers(req_id),
        method="POST",
    )
    try:
        diag.mark("http_open_begin", req_id=req_id, hanzi=len(text))
        with urllib.request.urlopen(req, timeout=config.TTS_SERVICE_TIMEOUT_S) as resp:
            diag.mark(
                "http_headers", req_id=req_id,
                status=getattr(resp, "status", None),
            )
            # read1 = 有多少读多少;老解释器/无 read1 的实现退回 read
            read_chunk = getattr(resp, "read1", None) or resp.read
            buf = b""
            while True:
                chunk = read_chunk(_READ_BLOCK)
                if not chunk:
                    break
                buf += chunk
                if b"\n" not in buf:
                    continue
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    wav = _parse_line(line, req_id)
                    if wav is not None:
                        diag.mark("http_line_wav", req_id=req_id, nbytes=len(wav))
                        yield wav
            if buf.strip():
                wav = _parse_line(buf, req_id)
                if wav is not None:
                    diag.mark("http_line_wav", req_id=req_id, nbytes=len(wav))
                    yield wav
        diag.mark("http_done", req_id=req_id)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()[:200]
        except Exception:  # noqa: BLE001, S110 — 读取响应体失败时用空串
            pass
        raise TTSError(f"HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TTSError(f"连接失败: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise TTSError(f"响应解析失败: {exc}") from exc


def synthesize_stream(text: str, *, request_id: str | None = None) -> Iterator[bytes]:
    """文本 → 逐句 wav 字节流;失败抛 TTSError,被打断抛 TTSCancelled。

    与 synthesize_stream_detailed 同义,保留此名是因为 sidecar 模式的门面也是这个名字
    (调用方 tts.py 按 TTS_MODE 路由,两模式同名同签名才能互换)。
    """
    yield from synthesize_stream_detailed(text, request_id=request_id)


def cancel(request_id: str, *, cascade: bool = True) -> dict:
    """打断一个回合。返回服务侧的处置结果;不可达/失败不抛(抢占路径不能被它拖挂)。

    cascade=True 时服务侧会连带清掉所有"尚未开始"的排队回合 ——
    主程序取消后必须立刻把队列清空,不能让旧回合接着出声。
    """
    payload = json.dumps({"round_id": request_id, "cascade": cascade}).encode()
    try:
        req = urllib.request.Request(
            f"{_base()}/v1/tts/cancel",
            data=payload,
            headers=_headers(),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 — 打断失败只影响音频,不影响回合
        logger.warning("tts_cancel_failed", round_id=request_id, reason=str(exc)[:120])
        return {"round_id": request_id, "cancelled": False, "error": str(exc)[:120]}


def synthesize(text: str, *, request_id: str | None = None) -> bytes | None:
    """文本 → 拼接整段 wav bytes;失败 WARN 降级 None(离线生成用,如 fillers)。"""
    if not text.strip():
        return None
    try:
        return b"".join(synthesize_stream(text, request_id=request_id))
    except TTSError as exc:
        logger.warning("tts_remote_degraded", reason=str(exc)[:160])
        return None
    except TTSCancelled:
        return None
