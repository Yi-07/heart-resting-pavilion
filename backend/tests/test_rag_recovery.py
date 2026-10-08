"""RAG remote 模式恢复测试。

验证:
1. warm() 失败后 _ready 永远 False (当前 bug — regression guard)
2. warm() 成功后 _ready 变 True
3. warm() 先失败后成功 → 第二次调用能恢复
4. retrieve_async() 在 _ready=False 时正确抛出 RagNotReady
"""

from __future__ import annotations

import asyncio

import pytest

from app import config
import app.rag as rag_mod

# 本文件所有测试仅适用于 remote 模式 (需要 asyncio-based _ready + HTTP client)
pytestmark = pytest.mark.skipif(
    config.RAG_MODE == "local",
    reason="RAG recovery tests require RAG_MODE=remote",
)


@pytest.fixture()
def _force_remote_ready_false(monkeypatch: pytest.MonkeyPatch):
    """conftest autouse 会把 _ready 设为 truthy threading.Event;
    此 fixture 在其之后运行,把 _ready 还原为 remote 模式期望的 bool=False,
    使 rag/__init__.py 中 if not _ready 分支可触达。

    同时重置 asyncio 对象,避免跨测试 event loop 绑定冲突。
    """
    monkeypatch.setattr(rag_mod, "_ready", False)
    # 重置 asyncio 对象:新测试的 event loop 不同,旧 Event/Lock 无法复用
    if hasattr(rag_mod, "_ready_event"):
        rag_mod._ready_event = None
    if hasattr(rag_mod, "_recovery_lock"):
        rag_mod._recovery_lock = None
    if hasattr(rag_mod, "_last_check_time"):
        rag_mod._last_check_time = 0.0


class TestRagRemoteDegradation:
    """warm() 失败后永久降级 — 当前已知 bug 的 regression guard。"""

    def test_warm_failure_leaves_ready_false(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """warm() 失败 → _ready 保持 False。"""
        assert rag_mod._ready is False
        monkeypatch.setattr("app.rag.client.ready", lambda: False)

        with pytest.raises(rag_mod.RagNotReady, match="未就绪"):
            rag_mod.warm()

        assert rag_mod._ready is False

    @pytest.mark.asyncio
    async def test_retrieve_async_fails_when_not_ready(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """_ready=False 时 retrieve_async() 直接抛 RagNotReady。"""
        assert rag_mod._ready is False
        # Mock client.ready to prevent auto-recovery hitting real service
        monkeypatch.setattr("app.rag.client.ready", lambda: False)

        with pytest.raises(rag_mod.RagNotReady, match="未就绪"):
            await rag_mod.retrieve_async("test query")

    def test_warm_failure_then_success_still_degraded(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """warm() 先失败后成功 → _ready 恢复为 True。

        这是当前 bug 的精确复现:第一次 warm() 失败后,
        即使后来 RAG Service 可用,warm() 再次成功,
        _ready 应该恢复为 True。
        """
        # 第一次:失败
        monkeypatch.setattr("app.rag.client.ready", lambda: False)
        with pytest.raises(rag_mod.RagNotReady):
            rag_mod.warm()
        assert rag_mod._ready is False

        # 第二次:成功 (RAG Service 启动完成)
        monkeypatch.setattr("app.rag.client.ready", lambda: True)
        rag_mod.warm()

        # 断言:当前 bug — warm() 成功但 _ready 仍为 False
        # 如果修复后此断言应改为 assert rag_mod._ready is True
        # 当前行为(warm 成功但不设 _ready)就是 bug 的根因
        assert rag_mod._ready is True, (
            "warm() 成功后 _ready 应为 True; "
            "如果仍为 False,说明 warm() 成功路径未正确设置 _ready"
        )

    @pytest.mark.asyncio
    async def test_retrieve_after_warm_recovery(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """warm() 失败 → 后来成功 → retrieve_async() 应可用。"""
        # warm 失败
        monkeypatch.setattr("app.rag.client.ready", lambda: False)
        with pytest.raises(rag_mod.RagNotReady):
            rag_mod.warm()

        # RAG Service 恢复
        monkeypatch.setattr("app.rag.client.ready", lambda: True)
        rag_mod.warm()

        # retrieve 应该成功 (mock 掉 HTTP client)
        fake_refs = [{"id": "1", "question": "q", "answer": "a", "score": 0.9}]
        monkeypatch.setattr("app.rag.client.retrieve", lambda *a, **kw: fake_refs)

        result = await rag_mod.retrieve_async("test query")
        assert len(result) == 1
        assert result[0].id == "1"

    @pytest.mark.asyncio
    async def test_retrieve_async_recovers_after_warm_failure(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """核心 bug 修复验证:startup warm 失败后,RAG Service 恢复,
        retrieve_async() 应自动恢复连接并成功检索。

        修复前:retrieve_async() 永远抛 RagNotReady (永久降级)。
        修复后:retrieve_async() 通过 _try_recover() 检测恢复。
        """
        # 模拟 startup: warm 失败
        monkeypatch.setattr("app.rag.client.ready", lambda: False)
        with pytest.raises(rag_mod.RagNotReady):
            rag_mod.warm()
        assert rag_mod._ready is False

        # 模拟 RAG Service 30s 后恢复就绪
        monkeypatch.setattr("app.rag.client.ready", lambda: True)

        # mock HTTP 检索
        fake_refs = [{"id": "1", "question": "q", "answer": "a", "score": 0.9}]
        monkeypatch.setattr("app.rag.client.retrieve", lambda *a, **kw: fake_refs)

        # 修复后:retrieve_async 应该自动恢复并成功返回
        result = await rag_mod.retrieve_async("test query")
        assert len(result) == 1
        assert result[0].id == "1"
        assert rag_mod._ready is True


class TestRagRemoteRuntimeDegradation:
    """RAG Service 运行中掉线 → 恢复。"""

    @pytest.mark.asyncio
    async def test_http_failure_resets_ready(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """retrieve_async() HTTP 失败 → _ready 重置为 False。"""
        # 先设为 ready
        monkeypatch.setattr(rag_mod, "_ready", True)

        # HTTP 检索失败
        def _fail(*a, **kw):
            raise RuntimeError("connection lost")

        monkeypatch.setattr("app.rag.client.retrieve", _fail)

        with pytest.raises(RuntimeError, match="connection lost"):
            await rag_mod.retrieve_async("test query")

        assert rag_mod._ready is False

    @pytest.mark.asyncio
    async def test_recovery_after_runtime_failure(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """HTTP 失败 → _ready=False → 下次请求自动恢复。"""
        # 先设为 ready,然后 HTTP 失败
        monkeypatch.setattr(rag_mod, "_ready", True)

        call_count = 0

        def _fail_then_ok(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("connection lost")
            return [{"id": "1", "question": "q", "answer": "a", "score": 0.9}]

        monkeypatch.setattr("app.rag.client.retrieve", _fail_then_ok)
        monkeypatch.setattr("app.rag.client.ready", lambda: True)

        # 第一次:失败
        with pytest.raises(RuntimeError, match="connection lost"):
            await rag_mod.retrieve_async("test query")
        assert rag_mod._ready is False

        # 第二次:自动恢复
        result = await rag_mod.retrieve_async("test query")
        assert len(result) == 1
        assert rag_mod._ready is True


class TestRagRemoteSingleFlight:
    """多个并发请求同时触发 recovery 时,只有一个执行实际检查。"""

    @pytest.mark.asyncio
    async def test_concurrent_recovery_single_flight(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """多个协程同时调用 retrieve_async(),只有第一个触发 HTTP 检查。"""
        check_count = 0

        def _counting_ready():
            nonlocal check_count
            check_count += 1
            return True

        monkeypatch.setattr("app.rag.client.ready", _counting_ready)
        fake_refs = [{"id": "1", "question": "q", "answer": "a", "score": 0.9}]
        monkeypatch.setattr("app.rag.client.retrieve", lambda *a, **kw: fake_refs)

        # 并发 5 个请求
        results = await asyncio.gather(
            *[rag_mod.retrieve_async(f"query {i}") for i in range(5)]
        )

        assert all(len(r) == 1 for r in results)
        # single-flight: 只有 1 次 HTTP ready 检查
        assert check_count == 1
        assert rag_mod._ready is True


class TestRagRemoteCooldown:
    """recovery cooldown:短时间内不重复检查。"""

    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_rechecks(
        self, monkeypatch: pytest.MonkeyPatch, _force_remote_ready_false
    ):
        """第一次 recovery 失败后,第二次在 cooldown 内不重新检查。"""
        check_count = 0

        def _fail_then_ok():
            nonlocal check_count
            check_count += 1
            return check_count >= 2  # 第一次失败,第二次成功

        monkeypatch.setattr("app.rag.client.ready", _fail_then_ok)
        fake_refs = [{"id": "1", "question": "q", "answer": "a", "score": 0.9}]
        monkeypatch.setattr("app.rag.client.retrieve", lambda *a, **kw: fake_refs)

        # 第一次:recovery 失败
        with pytest.raises(rag_mod.RagNotReady):
            await rag_mod.retrieve_async("query 1")
        assert check_count == 1

        # 第二次(立刻):cooldown 内,不应该重新检查
        with pytest.raises(rag_mod.RagNotReady):
            await rag_mod.retrieve_async("query 2")
        # check_count 仍为 1:cooldown 内没有重新检查
        assert check_count == 1
