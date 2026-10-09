"""rag:检索三件套(职责表见 backend-plan §2;数据对接见 docs/architecture/data-contract.md)。

深模块:对外接口小(Ref/load_corpus/get_engine/retrieve_async/warm),复杂藏在
engine 内。两库(科普知识库/案例库)由 RagLibrary 标识,调用方只传库种类,
不接触 Chroma/BM25/重排。

进程编排(ADR-003):模型加载 ~18s 级,禁止请求路径同步加载——lifespan 后台
warm() 预热;请求侧 retrieve_async 等就绪(上限 2s,超时 RagNotReady 由调用方
降级直答),检索本体走 to_thread(encode/query/rerank 数百 ms 同样不进事件循环)。
BM25 索引按库持久化缓存(.rag_store/bm25/),启动预热直接读缓存免回建。
"""

import asyncio
import threading
import time

from .corpus import RagLibrary, Ref, load_corpus
from .engine import RagEngine, get_engine

__all__ = [
    "RagEngine",
    "RagLibrary",
    "Ref",
    "get_engine",
    "load_corpus",
    "retrieve_async",
    "warm",
]


class RagNotReady(RuntimeError):
    """预热未完成(或失败):调用方按 rag_failed 降级直答,不重试不等待。"""


_ready = threading.Event()
"""预热完成旗标(threading.Event 与事件循环解耦,避免跨 loop 绑定问题)"""

_RAG_READY_WAIT_S = 2.0


def warm() -> None:
    """同步预热(放 to_thread 跑):触发全部懒加载件——client/embedder/reranker/
    两库 BM25 索引。任意失败不 set 旗标,请求侧降级;异常上抛由 lifespan 记日志。"""
    engine = get_engine()
    engine.retrieve("启动预热", k=1, library=RagLibrary.KNOWLEDGE)
    engine.retrieve("启动预热", k=1, library=RagLibrary.CASE)
    _ready.set()


async def retrieve_async(
    query: str, k: int | None = None, *, library: RagLibrary = RagLibrary.CASE
) -> list[Ref]:
    """请求侧检索入口:等就绪(上限 2s)→ to_thread 检索。未就绪抛 RagNotReady。"""
    if not _ready.is_set():
        deadline = time.monotonic() + _RAG_READY_WAIT_S
        while not _ready.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        if not _ready.is_set():
            raise RagNotReady("rag 预热未完成")
    engine = get_engine()
    return await asyncio.to_thread(engine.retrieve, query, k, library=library)
