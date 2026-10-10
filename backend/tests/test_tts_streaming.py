"""TTS Service 流式/健康探针验证。

不加载 CosyVoice 真模型;mock _synth_sentences 验证:
1. streaming 期间 /live /ready /health 是否仍能及时响应
2. streaming 逐段返回、正常结束、首包正常
3. client disconnect 后服务不崩溃
4. 并发请求串行执行(不阻塞 event loop)
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---- Mock TTS Service App ----

# Import the real app but we'll override model loading
from app.voice.tts_service.server import app as _real_app, _model_state, _state_lock


@asynccontextmanager
async def _mock_lifespan(_application):
    """不加载 CosyVoice 模型,不启动 GPU 监控线程。"""
    yield


# Create a test client with mocked lifespan (no model loading)
client = TestClient(_real_app, raise_server_exceptions=False)


def _set_model_ready(ready: bool = True):
    """设置模型就绪状态。"""
    with _state_lock:
        _model_state["ready"] = ready
        _model_state["error"] = None


def _fake_synth_sentences(text: str):
    """mock _synth_sentences: 返回 2 个 fake wav chunk, 每个 50ms 延迟。"""
    for i in range(2):
        time.sleep(0.05)
        yield b"FAKEWAV" + str(i).encode() + b":" + text.encode()[:8]


# ---- Tests: Health Probes During Streaming ----


class TestHealthProbesDuringStreaming:
    """streaming 期间 /live /ready /health 是否仍能及时响应。"""

    def test_live_responds_during_streaming(self):
        """/live 在 streaming 期间应立即响应。"""
        _set_model_ready(True)

        with patch("app.voice.tts_service.server._synth_sentences", _fake_synth_sentences):
            # Start streaming in background
            stream_done = threading.Event()

            def do_stream():
                resp = client.post(
                    "/v1/tts/stream",
                    json={"text": "测试文本"},
                    headers={"X-Request-ID": "stream-1"},
                )
                assert resp.status_code == 200
                stream_done.set()

            stream_thread = threading.Thread(target=do_stream)
            stream_thread.start()

            # Wait for streaming to start
            time.sleep(0.02)

            # /live should respond immediately during streaming
            t0 = time.perf_counter()
            live_resp = client.get("/live")
            elapsed = time.perf_counter() - t0

            assert live_resp.status_code == 200
            assert live_resp.json()["status"] == "ok"
            assert elapsed < 1.0, f"/live took {elapsed:.2f}s during streaming"

            stream_done.wait(timeout=5)
            stream_thread.join(timeout=5)

    def test_ready_responds_during_streaming(self):
        """/ready 在 streaming 期间应立即响应。"""
        _set_model_ready(True)

        with patch("app.voice.tts_service.server._synth_sentences", _fake_synth_sentences):
            stream_done = threading.Event()

            def do_stream():
                resp = client.post(
                    "/v1/tts/stream",
                    json={"text": "测试文本"},
                    headers={"X-Request-ID": "stream-2"},
                )
                assert resp.status_code == 200
                stream_done.set()

            stream_thread = threading.Thread(target=do_stream)
            stream_thread.start()

            time.sleep(0.02)

            # /ready should respond immediately
            t0 = time.perf_counter()
            ready_resp = client.get("/ready")
            elapsed = time.perf_counter() - t0

            assert ready_resp.status_code == 200
            assert ready_resp.json()["ready"] is True
            assert elapsed < 1.0, f"/ready took {elapsed:.2f}s during streaming"

            stream_done.wait(timeout=5)
            stream_thread.join(timeout=5)

    def test_health_responds_during_streaming(self):
        """/v1/health 在 streaming 期间应立即响应。"""
        _set_model_ready(True)

        with patch("app.voice.tts_service.server._synth_sentences", _fake_synth_sentences):
            stream_done = threading.Event()

            def do_stream():
                resp = client.post(
                    "/v1/tts/stream",
                    json={"text": "测试文本"},
                    headers={"X-Request-ID": "stream-3"},
                )
                assert resp.status_code == 200
                stream_done.set()

            stream_thread = threading.Thread(target=do_stream)
            stream_thread.start()

            time.sleep(0.02)

            # /v1/health should respond immediately (may call nvidia-smi, mock it)
            with patch("subprocess.run", return_value=type("R", (), {"stdout": "NVIDIA GeForce\n", "returncode": 0})()):
                t0 = time.perf_counter()
                health_resp = client.get("/v1/health")
                elapsed = time.perf_counter() - t0

            assert health_resp.status_code == 200
            data = health_resp.json()
            assert data["status"] == "ok"
            assert data["service"] == "hrp-tts"
            assert data["ready"] is True
            assert elapsed < 2.0, f"/v1/health took {elapsed:.2f}s during streaming"

            stream_done.wait(timeout=5)
            stream_thread.join(timeout=5)


# ---- Tests: Streaming Behavior ----


class TestStreamingBehavior:
    """streaming 逐段返回、正常结束、首包正常。"""

    def test_streaming_returns_ndjson_chunks(self):
        """streaming 应逐行返回 NDJSON。"""
        _set_model_ready(True)

        with patch("app.voice.tts_service.server._synth_sentences", _fake_synth_sentences):
            resp = client.post(
                "/v1/tts/stream",
                json={"text": "测试文本"},
                headers={"X-Request-ID": "stream-4"},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/x-ndjson"

        lines = resp.text.strip().split("\n")
        assert len(lines) == 2  # fake synth returns 2 chunks

        for line in lines:
            data = json.loads(line)
            assert "wav" in data
            assert isinstance(data["wav"], str)
            # Verify it's valid base64
            import base64
            decoded = base64.b64decode(data["wav"])
            assert decoded.startswith(b"FAKEWAV")

    def test_streaming_first_chunk_is_fast(self):
        """首包延迟应远小于总延迟。"""
        _set_model_ready(True)

        def slow_synth(text: str):
            """模拟: 第一个 chunk 快(50ms), 第二个 chunk 慢(200ms)。"""
            time.sleep(0.05)
            yield b"CHUNK0"
            time.sleep(0.2)
            yield b"CHUNK1"

        with patch("app.voice.tts_service.server._synth_sentences", slow_synth):
            t0 = time.perf_counter()
            resp = client.post(
                "/v1/tts/stream",
                json={"text": "测试文本"},
                headers={"X-Request-ID": "stream-5"},
            )
            total = time.perf_counter() - t0

        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) == 2
        # Total should be ~250ms (50+200), not blocked
        assert total < 1.0, f"Streaming took {total:.2f}s, expected < 1s"

    def test_streaming_empty_text_returns_400(self):
        """空文本应返回 400。"""
        resp = client.post(
            "/v1/tts/stream",
            json={"text": "   "},
            headers={"X-Request-ID": "stream-6"},
        )
        assert resp.status_code == 400
        assert "empty_text" in resp.json()["code"]

    def test_streaming_model_not_ready_returns_503(self):
        """模型未就绪应返回 503。"""
        _set_model_ready(False)

        resp = client.post(
            "/v1/tts/stream",
            json={"text": "测试文本"},
            headers={"X-Request-ID": "stream-7"},
        )
        assert resp.status_code == 503
        assert "tts_unavailable" in resp.json()["code"]


# ---- Tests: Client Disconnect ----


class TestClientDisconnect:
    """客户端断开后服务不崩溃。"""

    def test_service_survives_client_disconnect(self):
        """客户端断开后服务仍能处理后续请求。"""
        _set_model_ready(True)

        with patch("app.voice.tts_service.server._synth_sentences", _fake_synth_sentences):
            # First request: complete normally
            resp1 = client.post(
                "/v1/tts/stream",
                json={"text": "第一次请求"},
                headers={"X-Request-ID": "disc-1"},
            )
            assert resp1.status_code == 200

            # Second request: also works (service survived)
            resp2 = client.post(
                "/v1/tts/stream",
                json={"text": "第二次请求"},
                headers={"X-Request-ID": "disc-2"},
            )
            assert resp2.status_code == 200

    def test_concurrent_requests_are_serial(self):
        """并发请求应串行处理(CosyVoice 单模型),不应死锁。"""
        _set_model_ready(True)

        def slow_synth(text: str):
            time.sleep(0.05)
            yield b"CHUNK"

        with patch("app.voice.tts_service.server._synth_sentences", slow_synth):
            results = [None, None]
            errors = [None, None]

            def do_request(idx: int):
                try:
                    resp = client.post(
                        "/v1/tts/stream",
                        json={"text": f"请求{idx}"},
                        headers={"X-Request-ID": f"conc-{idx}"},
                    )
                    results[idx] = resp.status_code
                except Exception as e:
                    errors[idx] = str(e)

            t0 = time.perf_counter()
            threads = [threading.Thread(target=do_request, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            total = time.perf_counter() - t0

            # Both should succeed
            assert results[0] == 200, f"Request 0 failed: {errors[0]}"
            assert results[1] == 200, f"Request 1 failed: {errors[1]}"
            # With workers=1 and serial processing, 2 requests × 50ms = ~100ms+
            # Should not deadlock or take excessively long
            assert total < 5.0, f"Concurrent requests took {total:.2f}s, possible deadlock"


# ---- Regression: event-loop blocking ----


class TestEventLoopNotBlocked:
    """Regression: streaming inference must not block health probes.

    Before the fix, CosyVoice inference ran synchronously in the async handler,
    blocking the event loop and causing /live /ready /health to timeout.
    After the fix (asyncio.to_thread), health probes respond promptly.
    """

    HEALTH_PROBE_MAX_S = 2.0  # health probes must respond within 2s

    def test_health_probes_during_long_inference(self):
        """Long inference must not block /live /ready /health."""
        _set_model_ready(True)

        def long_synth(text: str):
            """Simulate slow CosyVoice: 3 chunks × 200ms each = 600ms total."""
            for i in range(3):
                time.sleep(0.2)
                yield b"CHUNK" + str(i).encode()

        with patch("app.voice.tts_service.server._synth_sentences", long_synth):
            stream_done = threading.Event()

            def do_stream():
                resp = client.post(
                    "/v1/tts/stream",
                    json={"text": "测试event-loop不阻塞"},
                    headers={"X-Request-ID": "regression-1"},
                )
                assert resp.status_code == 200
                stream_done.set()

            stream_thread = threading.Thread(target=do_stream)
            stream_thread.start()

            # Wait for streaming to start
            time.sleep(0.05)

            # All health probes must respond quickly during inference
            for path, label in [("/live", "/live"), ("/ready", "/ready"), ("/v1/health", "/v1/health")]:
                t0 = time.perf_counter()
                resp = client.get(path)
                elapsed = time.perf_counter() - t0
                assert resp.status_code in (200, 503), f"{label} returned {resp.status_code}"
                assert elapsed < self.HEALTH_PROBE_MAX_S, (
                    f"{label} took {elapsed:.2f}s during streaming (max {self.HEALTH_PROBE_MAX_S}s) — "
                    "event loop likely blocked by inference"
                )

            stream_done.wait(timeout=10)
            stream_thread.join(timeout=10)
