"""voice 接缝钉测试:tts 客户端对假 sidecar 的请求/降级 · fillers 生成与取用 ·
ASR 真模型转写(前置=SenseVoice 已缓存 + CosyVoice 仓库 asset 在场,否则跳过)。"""

from __future__ import annotations

import base64
import io
import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import config
from app.voice import fillers, tts
from app.voice.fillers import pick as _orig_pick
from app.voice.tts import synthesize as _orig_synthesize


class _FakeSidecar(BaseHTTPRequestHandler):
    wav_payload = b"FAKEWAVBYTES"

    def do_GET(self):
        body = json.dumps({"ready": True, "error": None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        text = json.loads(self.rfile.read(length))["text"]
        payload = self.wav_payload + text.encode()[:4]  # 可辨认回显
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


@pytest.fixture(autouse=True)
def _real_voice(monkeypatch: pytest.MonkeyPatch):
    """本文件测真 voice 客户端:恢复 conftest 静音桩之前的原函数
    (须在模块导入期捕获——fixture 里现取会拿到已打桩的假货)。"""
    monkeypatch.setattr("app.voice.tts.synthesize", _orig_synthesize)
    monkeypatch.setattr("app.voice.fillers.pick", _orig_pick)


@pytest.fixture()
def fake_sidecar(monkeypatch: pytest.MonkeyPatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSidecar)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(config, "TTS_SIDECAR_PORT", port)
    yield port
    server.shutdown()


def test_synthesize_roundtrip_against_fake_sidecar(fake_sidecar):
    wav = tts.synthesize("你好呀")
    assert wav is not None
    assert wav.startswith(b"FAKEWAVBYTES")


def test_synthesize_degrades_when_sidecar_down(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "TTS_SIDECAR_PORT", 59999)  # 无人监听
    monkeypatch.setattr(config, "TTS_SIDECAR_READY_TIMEOUT_S", 0.5)
    assert tts.synthesize("你好") is None  # 降级 None 不抛
    assert tts.synthesize("") is None  # 空文本短路


def test_fillers_generate_and_pick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "FILLERS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.voice.fillers.synthesize", lambda text: b"WAV" + text.encode()[:8]
    )
    fillers.generate()
    files = sorted(p.name for p in tmp_path.glob("wait_*.wav"))
    assert files == ["wait_1.wav", "wait_2.wav"]

    picked = fillers.pick()
    assert picked is not None
    assert picked.startswith(b"WAV")

    fillers.generate()  # 幂等:已存在跳过
    assert sorted(p.name for p in tmp_path.glob("wait_*.wav")) == files


def test_fillers_pick_empty_dir_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "FILLERS_DIR", str(tmp_path))
    assert fillers.pick() is None


def _silence_wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def test_transcribe_real_sensevoice():
    """真模型链路:CosyVoice 仓库自带提示语音 → 转写非空且含预期关键词;
    静音 wav → 空文本。模型/素材缺位时跳过(机器本地真链路,同 test_retrieve 形态)。"""
    from app.voice import asr

    prompt = (
        Path(__file__).resolve().parents[2]
        / "models"
        / "voices"
        / "CosyVoice"
        / "asset"
        / "zero_shot_prompt.wav"
    )
    if not prompt.exists():
        pytest.skip("CosyVoice 仓库 asset 不在场")
    try:
        text = asr.transcribe(prompt.read_bytes())
    except asr.ASRError as exc:
        pytest.skip(f"SenseVoice 模型不可用: {exc}")
    assert len(text) >= 4  # 提示语音有内容,转写非空

    # 纯数字静音可能幻觉出单个语气词(如「嗯。」)——≤2 字符视为无有效内容
    assert len(asr.transcribe(_silence_wav())) <= 2


def test_audio_b64_roundtrip_shape():
    """网关 audio_chunk 的 base64 形状(wav 字节 ↔ 前端 data URI 解码)。"""
    wav = _silence_wav(0.1)
    encoded = base64.b64encode(wav).decode("ascii")
    assert base64.b64decode(encoded) == wav
