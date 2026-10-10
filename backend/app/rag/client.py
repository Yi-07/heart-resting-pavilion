"""RAG 远程客户端:通过 HTTP 调用远程 RAG Service。

接口与 rag/__init__.py 完全兼容(retrieve_async / warm / RagNotReady),
agents/graph.py · station/planner.py · gateway.py 通过 rag/__init__.py
路由层透明切换,无需修改。

超时策略:
- retrieve: 10s (检索+重排 通常 <2s)
- health/ready: 3s 快速探活
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from app import config, diag
from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="rag_client")


class RagError(RuntimeError):
    """远程 RAG 不可用/检索失败;调用方降级直答。"""


def _base() -> str:
    return config.RAG_SERVICE_URL.rstrip("/")


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
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(f"{_base()}/ready", timeout=3) as resp:
            ok = resp.status == 200
            diag.mark("rag_ready_http", ok=ok,
                      ms=round((time.perf_counter() - t0) * 1000))
            return ok
    except urllib.error.HTTPError as e:
        diag.mark("rag_ready_http", ok=e.code == 200, http=e.code,
                  ms=round((time.perf_counter() - t0) * 1000))
        return e.code == 200
    except (urllib.error.URLError, OSError) as exc:
        diag.mark("rag_ready_http", ok=False, err=type(exc).__name__,
                  ms=round((time.perf_counter() - t0) * 1000))
        return False


def retrieve(
    query: str,
    k: int | None = None,
    *,
    library: str = "case",
    request_id: str | None = None,
) -> list[dict]:
    """检索远程 RAG Service;返回 Ref dict 列表。失败抛 RagError。"""
    req_id = request_id or f"req_{int(time.time() * 1000)}"
    body = json.dumps({
        "query": query,
        "k": k,
        "library": library,
    }).encode()
    req = urllib.request.Request(
        f"{_base()}/v1/retrieve",
        data=body,
        headers=_headers(req_id),
        method="POST",
    )
    t0 = time.perf_counter()
    diag.mark("rag_retr_open_begin", base=_base(), query_len=len(query))
    try:
        with urllib.request.urlopen(req, timeout=config.RAG_SERVICE_TIMEOUT_S) as resp:
            diag.mark("rag_retr_headers", status=resp.status,
                      ms=round((time.perf_counter() - t0) * 1000))
            raw = resp.read()
            result = json.loads(raw.decode())
            refs = result.get("refs", [])
            diag.mark("rag_retr_done", refs=len(refs), nbytes=len(raw),
                      ms=round((time.perf_counter() - t0) * 1000))
            return refs
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode()[:200]
        except Exception:  # noqa: BLE001, S110
            pass
        if exc.code == 503:
            raise RagError(f"RAG 服务不可用: {err_body}") from exc
        raise RagError(f"HTTP {exc.code}: {err_body}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RagError(f"连接失败: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise RagError(f"响应解析失败: {exc}") from exc
