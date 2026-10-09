"""Client ↔ TTS Service HTTP contract 验证。

path/method 用静态正则比对(两端都是字面量,正则最直接);
**NDJSON 响应行一律跑客户端真实解析代码** —— 对源码做正则匹配等于把实现细节
钉成契约,改个解析写法就误报失败(踩过)。

服务侧源码在 GPT-SoVITS 引擎件(仓库外,见 docs/guides/gpt-sovits-guide.md),
引擎件不在场时静态比对跳过;行为断言(解析/异常映射)不依赖引擎件,恒跑。
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

from app.voice.tts_client import (
    TTSCancelled,
    TTSError,
    synthesize_stream_detailed,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
REPO_ROOT = BACKEND_DIR.parent
GPT_SOVITS_SERVER = REPO_ROOT / "GPT-SoVITS" / "tts_service" / "server.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _service_code() -> str:
    """引擎件服务端源码;不在场则 skip(引擎件独立交付,见看板 D3)。"""
    if not GPT_SOVITS_SERVER.exists():
        pytest.skip("GPT-SoVITS 引擎件不在场(独立交付,不入库)")
    return _read(GPT_SOVITS_SERVER)


def _consume_rows(rows: list[str], monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """把若干 NDJSON 行喂给真实的 synthesize_stream_detailed,收集产出的 wav。

    用 monkeypatch 换掉 urlopen,不起真服务 —— 测的是解析与异常映射,
    不是网络。
    """
    import io
    import urllib.request

    body = ("\n".join(rows) + "\n").encode()

    class _Resp(io.BytesIO):
        def __iter__(self):  # type: ignore[override]
            return iter(body.splitlines(keepends=True))

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    return list(synthesize_stream_detailed("测试"))


# ---- TTS Contract ----


class TestTTSContract:
    """tts_client.py ↔ GPT-SoVITS/tts_service/server.py contract."""

    def test_stream_path_matches(self):
        client_code = _read(APP_DIR / "voice" / "tts_client.py")
        service_code = _service_code()
        # Client: f"{_base()}/v1/tts/stream"
        assert re.search(r'/v1/tts/stream', client_code)
        assert re.search(r'@app\.post\("/v1/tts/stream"\)', service_code)

    def test_stream_body_format(self):
        client_code = _read(APP_DIR / "voice" / "tts_client.py")
        service_code = _service_code()
        assert re.search(r'"text":\s*text', client_code)
        assert re.search(r'class TTSRequest', service_code)
        assert re.search(r'text:\s*str', service_code)

    def test_stream_response_format(self, monkeypatch):
        # 行为断言:客户端真的会把 {"wav": ...} 解析成 bytes。
        # 之前这测的是源码字面量 piece["wav"],改一下解析写法就误报失败 ——
        # 测的是实现细节,不是行为。改为跑真的解析代码。
        service_code = _service_code()
        assert re.search(r'"wav":\s*base64\.b64encode', service_code)

        wav_b64 = base64.b64encode(b"RIFF----WAVEfake").decode()
        rows = [
            f'{{"wav":"{wav_b64}","round_id":"r-1"}}',
            f'{{"wav":"{wav_b64}","round_id":"r-1"}}',
        ]
        assert _consume_rows(rows, monkeypatch) == [b"RIFF----WAVEfake"] * 2

    def test_stream_error_format(self, monkeypatch):
        service_code = _service_code()
        assert re.search(r'"code":\s*"synth_failed"', service_code)

        # 服务端报 error 行时,客户端必须抛 TTSError(而不是 KeyError 或静默)
        with pytest.raises(TTSError):
            _consume_rows(
                ['{"error":"boom","code":"synth_failed","round_id":"r-1"}'], monkeypatch
            )

    def test_stream_cancelled_row_raises_cancelled(self, monkeypatch):
        # 打断行要翻译成 TTSCancelled,调用方据此区分"抢占"与"故障"
        with pytest.raises(TTSCancelled):
            _consume_rows(['{"cancelled":true,"round_id":"r-1"}'], monkeypatch)

    def test_stream_ignores_unknown_rows(self, monkeypatch):
        # 向后兼容:服务侧在同一行加新字段,客户端不能因此炸掉
        wav_b64 = base64.b64encode(b"x").decode()
        assert _consume_rows(
            [f'{{"wav":"{wav_b64}","round_id":"r-1","future_field":123}}'], monkeypatch
        ) == [b"x"]

    def test_ready_path_matches(self):
        client_code = _read(APP_DIR / "voice" / "tts_client.py")
        service_code = _service_code()
        assert re.search(r'/ready', client_code)
        assert re.search(r'@app\.get\("/ready"\)', service_code)

    def test_health_path_matches(self):
        client_code = _read(APP_DIR / "voice" / "tts_client.py")
        service_code = _service_code()
        assert re.search(r'/v1/health', client_code)
        assert re.search(r'@app\.get\("/v1/health"\)', service_code)
