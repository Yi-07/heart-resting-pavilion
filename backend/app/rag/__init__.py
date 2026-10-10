"""rag:检索三件套(职责表见 backend-plan §2;数据对接见 docs/data-contract.md)。

路由层:按 RAG_MODE 切换 local/remote。
- local: 直接调用本地 engine(Chroma+BM25+reranker),原路径不变
- remote: 通过 HTTP client 调用远程 RAG Service,主服务零 ML 依赖

对外接口不变:retrieve_async / warm / RagNotReady / Ref / RagLibrary / load_corpus
gateway.py · agents/graph.py · station/planner.py 无需修改。
"""

import asyncio
import time

from app import diag

from .corpus import RagLibrary, Ref, load_corpus

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


from app import config

if config.RAG_MODE == "remote":
    # ---- Remote 模式:通过 HTTP 调用远程 RAG Service ----

    import logging

    from . import client as _client

    _ready = False
    _ready_event: asyncio.Event | None = None
    _recovery_lock: asyncio.Lock | None = None
    _last_check_time: float = 0.0
    _RECOVERY_COOLDOWN_S = 30.0
    _RECOVERY_WAIT_S = 2.0

    logger = logging.getLogger("app.rag")

    def _init_async_state() -> tuple[asyncio.Event, asyncio.Lock]:
        """延迟初始化 asyncio 对象(必须在 running loop 内调用)。"""
        global _ready_event, _recovery_lock
        if _ready_event is None:
            _ready_event = asyncio.Event()
        if _recovery_lock is None:
            _recovery_lock = asyncio.Lock()
        return _ready_event, _recovery_lock

    class _RemoteEngine:
        """轻量包装器:对外接口与 RagEngine.retrieve 兼容,内部走 HTTP client。

        目的:让 gateway.py / test monkeypatch.get_engine() 路径在两种模式下一致。
        """

        def retrieve(
            self, query: str, k: int | None = None, *, library: RagLibrary = RagLibrary.CASE
        ) -> list[Ref]:
            refs_dict = _client.retrieve(query, k, library=library.value)
            return [
                Ref(
                    id=r["id"],
                    question=r["question"],
                    answer=r["answer"],
                    score=r.get("score", 0.0),
                    category=r.get("category"),
                )
                for r in refs_dict
            ]

    _engine = _RemoteEngine()

    def get_engine() -> _RemoteEngine:
        """进程级单例(测试可通过 monkeypatch 替换)。"""
        return _engine

    async def _try_recover() -> bool:
        """尝试恢复连接: single-flight + cooldown。

        返回 True 表示恢复成功,_ready 已设为 True。
        同一时刻只有一个 coroutine 执行实际检查;其他调用者等待结果。
        """
        global _ready, _last_check_time
        event, lock = _init_async_state()

        diag.mark("rag_recover_enter", ready=_ready,
                  since_check=round(time.monotonic() - _last_check_time, 2))
        if _ready:
            return True

        now = time.monotonic()
        if now - _last_check_time < _RECOVERY_COOLDOWN_S:
            # cooldown 内:不检查,等现有结果
            if _ready:
                return True
            diag.mark("rag_recover_cooldown_wait", wait_s=_RECOVERY_WAIT_S)
            try:
                await asyncio.wait_for(event.wait(), timeout=_RECOVERY_WAIT_S)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            diag.mark("rag_recover_cooldown_done", ready=_ready)
            return _ready

        async with lock:
            # double-check:可能其他 coroutine 已完成恢复
            if _ready:
                return True
            now = time.monotonic()
            if now - _last_check_time < _RECOVERY_COOLDOWN_S:
                try:
                    await asyncio.wait_for(event.wait(), timeout=_RECOVERY_WAIT_S)
                except (asyncio.TimeoutError, TimeoutError):
                    pass
                return _ready

            # 执行实际检查(同步 HTTP 放到 to_thread)
            _last_check_time = now
            diag.mark("rag_recover_probe_begin")
            try:
                is_ready = await asyncio.to_thread(_client.ready)
            except Exception:  # noqa: BLE001
                is_ready = False
            diag.mark("rag_recover_probe_done", is_ready=is_ready)

            if is_ready:
                _ready = True
                event.set()
                logger.info("rag_recovery_success · 远程 RAG Service 恢复就绪")
            else:
                event.clear()
                logger.debug("rag_recovery_failed · 远程 RAG Service 仍未就绪")
            return _ready

    def warm() -> None:
        """远程模式预热:检查 RAG Service 就绪状态。startup + 后续重试共用。"""
        global _ready
        if _client.ready():
            _ready = True
        else:
            raise RagNotReady("远程 RAG Service 未就绪")

    async def retrieve_async(
        query: str, k: int | None = None, *, library: RagLibrary = RagLibrary.CASE
    ) -> list[Ref]:
        """远程检索:不就绪时尝试恢复 → 成功则检索,失败则降级。

        async-safe:所有等待通过 asyncio.sleep / asyncio.Event,不阻塞 event loop。
        """
        global _ready
        diag.mark("rag_async_enter", ready=_ready, query_len=len(query))
        if not _ready:
            recovered = await _try_recover()
            if not recovered:
                raise RagNotReady("远程 RAG Service 未就绪")
        engine = get_engine()
        try:
            diag.mark("rag_thread_begin")
            refs = await asyncio.to_thread(engine.retrieve, query, k, library=library)
            diag.mark("rag_thread_done", refs=len(refs))
            return refs
        except Exception:
            # HTTP 检索失败:可能 RAG Service 掉线,标记不就绪
            _ready = False
            if _ready_event is not None:
                _ready_event.clear()
            raise

    RagEngine = _RemoteEngine  # type: ignore[assignment,misc]

else:
    # ---- Local 模式:直接调用本地 engine ----

    import threading

    from .engine import RagEngine, get_engine  # type: ignore[assignment,misc]

    _ready = threading.Event()  # type: ignore[assignment]
    _RAG_READY_WAIT_S = 2.0

    def warm() -> None:
        """同步预热(放 to_thread 跑):触发全部懒加载件。"""
        engine = get_engine()
        engine.retrieve("启动预热", k=1, library=RagLibrary.KNOWLEDGE)
        engine.retrieve("启动预热", k=1, library=RagLibrary.CASE)
        _ready.set()  # type: ignore[attr-defined]

    async def retrieve_async(
        query: str, k: int | None = None, *, library: RagLibrary = RagLibrary.CASE
    ) -> list[Ref]:
        """请求侧检索入口:等就绪(上限 2s) → to_thread 检索。"""
        if not _ready.is_set():  # type: ignore[attr-defined]
            deadline = time.monotonic() + _RAG_READY_WAIT_S
            while not _ready.is_set() and time.monotonic() < deadline:  # type: ignore[attr-defined]
                await asyncio.sleep(0.1)
            if not _ready.is_set():  # type: ignore[attr-defined]
                raise RagNotReady("rag 预热未完成")
        engine = get_engine()
        return await asyncio.to_thread(engine.retrieve, query, k, library=library)
