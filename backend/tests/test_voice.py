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
from app.voice.sidecar_protocol import SIDECAR_VERSION

# local-mode symbols only exist when TTS_MODE=local
if config.TTS_MODE == "local":
    from app.voice.tts import ensure_sidecar as _orig_ensure_sidecar
    from app.voice.tts import synthesize as _orig_synthesize
    from app.voice.tts import synthesize_stream as _orig_synthesize_stream
else:
    # remote 模式:测试本地 sidecar 需要临时切换到 local 模式
    _orig_ensure_sidecar = None  # type: ignore[assignment]
    _orig_synthesize = None  # type: ignore[assignment]
    _orig_synthesize_stream = None  # type: ignore[assignment]


class _FakeSidecar(BaseHTTPRequestHandler):
    sentence_frames = b"\x01\x00" * 160  # 每句 160 帧(10ms@16k)真 wav,验证剥头拼合

    def do_GET(self):
        body = json.dumps({"ready": True, "error": None, "version": SIDECAR_VERSION}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(length))["text"]  # 读掉请求体(内容不参与断言)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for i in range(2):  # 两个分句块:验证逐句流式(每块=完整 wav,各带 RIFF 头)
            payload = _sentence_wav(self.sentence_frames, tag=i)
            line = json.dumps({"wav": base64.b64encode(payload).decode("ascii")}) + "\n"
            self.wfile.write(line.encode("ascii"))

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def _sentence_wav(frames: bytes, *, tag: int = 0) -> bytes:
    """真 wav(16k 单声道 16bit,帧数据打 tag 便于拼合断言)。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(frames + tag.to_bytes(2, "little"))
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _real_voice(monkeypatch: pytest.MonkeyPatch):
    """本文件测真 voice 客户端:恢复 conftest 静音桩之前的原函数
    (须在模块导入期捕获——fixture 里现取会拿到已打桩的假货);
    进程编排状态(_stopping/_spawned)一并复位。"""
    if config.TTS_MODE == "local" and _orig_ensure_sidecar is not None:
        monkeypatch.setattr("app.voice.tts.synthesize", _orig_synthesize)
        monkeypatch.setattr("app.voice.tts.synthesize_stream", _orig_synthesize_stream)
        monkeypatch.setattr("app.voice.tts.ensure_sidecar", _orig_ensure_sidecar)
        monkeypatch.setattr(tts, "_stopping", False)
        monkeypatch.setattr(tts, "_spawned", None)
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


@pytest.mark.skipif(config.TTS_MODE == "remote", reason="sidecar tests require local mode")
def test_synthesize_stream_roundtrip_against_fake_sidecar(fake_sidecar):
    """流式:逐句 NDJSON → 按序产出两个分句块(各为完整 wav)。"""
    chunks = list(tts.synthesize_stream("你好呀"))
    assert len(chunks) == 2
    for chunk in chunks:
        with wave.open(io.BytesIO(chunk), "rb") as r:  # 每块都是独立完整 wav
            assert r.getnframes() == 161


@pytest.mark.skipif(config.TTS_MODE == "remote", reason="sidecar tests require local mode")
def test_synthesize_roundtrip_against_fake_sidecar(fake_sidecar):
    """整段包装:剥头拼 PCM 重写单 RIFF 头(裸拼接损坏,T3fix 问题 A 回归钉)。"""
    wav = tts.synthesize("你好呀")
    assert wav is not None
    with wave.open(io.BytesIO(wav), "rb") as r:
        assert r.getnchannels() == 1 and r.getframerate() == 16000
        assert r.getnframes() == 322  # 两句帧数之和(160+1)×2,截断即失败


@pytest.mark.skipif(config.TTS_MODE == "remote", reason="sidecar tests require local mode")
def test_synthesize_degrades_when_sidecar_down(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "TTS_SIDECAR_PORT", 59999)  # 无人监听
    monkeypatch.setattr(
        "app.voice.tts.ensure_sidecar", lambda timeout_s=None: False
    )  # 显式不可用:不能走真拉起(会遗留 sidecar 进程)
    monkeypatch.setattr(config, "TTS_SIDECAR_READY_TIMEOUT_S", 0.5)
    assert tts.synthesize("你好") is None  # 降级 None 不抛
    assert tts.synthesize("") is None  # 空文本短路


def test_split_for_tts_rules():
    """分句规则钉:硬切/首句软标点提前切(首包优先)/超长软切。"""
    from app.voice.sidecar_protocol import split_for_tts

    assert split_for_tts("最近很焦虑睡不着") == ["最近很焦虑睡不着"]
    assert split_for_tts("我知道你很辛苦，先深呼吸一下。慢慢来。") == [
        "我知道你很辛苦，",
        "先深呼吸一下。",
        "慢慢来。",
    ]
    # 首句无软标点则整句照常;超 30 字软切不产生空句
    long_text = (
        "很累的时候身体会先发出信号，比如肩膀变重，呼吸变浅，这些都是正常的，"
        "不是你不够坚强，只是身体在提醒你需要休息了，现在把注意力放在呼吸上。"
    )
    parts = split_for_tts(long_text)
    assert all(p.strip() for p in parts)
    assert parts[0].endswith("，")  # 首包句在首个软标点提前切


def test_join_sentence_wavs_structure():
    """拼接结构钉:单 RIFF 头、帧数=各句之和、参数不一致 fail loud(T3fix 问题 A)。"""
    from app.voice.wav_join import join_sentence_wavs

    joined = join_sentence_wavs(
        [_sentence_wav(b"\x01\x00" * 10, tag=0), _sentence_wav(b"\x02\x00" * 15, tag=1)]
    )
    with wave.open(io.BytesIO(joined), "rb") as r:
        assert r.getnframes() == 27  # 10+15+tag×2,裸拼会按首句头截成 11
        assert r.getnchannels() == 1 and r.getframerate() == 16000

    # 参数不一致(8k vs 16k):拒绝拼接(fail loud,不落损坏产物)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8)
    with pytest.raises(tts.TTSError, match="参数不一致"):
        join_sentence_wavs([_sentence_wav(b"\x01\x00" * 10), buf.getvalue()])

    assert join_sentence_wavs([]) == b""  # 空流:空 bytes(synthesize 已短路,防御)

    # 句 wav 损坏(非 RIFF)→ TTSError 降级,不裸崩
    with pytest.raises(tts.TTSError, match="解析失败"):
        join_sentence_wavs([b"NOTWAV"])


def test_fillers_generate_and_pick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "FILLERS_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.voice.fillers.synthesize", lambda text: b"WAV" + text.encode()[:8]
    )
    fillers.generate()
    names = sorted(p.name for p in tmp_path.glob("*.wav"))
    # 通用「话术→wav」表:等待×2 + 心情回执×6(P13) + 危机×2(P10/P11)
    assert names == sorted(
        ["wait_1.wav", "wait_2.wav"]
        + [f"mood_{m}.wav" for m in ("难过", "低落", "平静", "还好", "开心", "很好")]
        + ["crisis_soothe.wav", "crisis_hotline.wav"]
    )

    picked = fillers.pick()
    assert picked is not None
    assert picked.startswith(b"WAV")

    fillers.generate()  # 幂等:已存在跳过
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == names


def test_fillers_pick_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """按名取预置语音(危机 P10/P11 · 心情回执 P13);缺文件返回 None。"""
    monkeypatch.setattr(config, "FILLERS_DIR", str(tmp_path))
    assert fillers.pick_named("crisis_soothe") is None
    assert fillers.pick_named(fillers.mood_ack_name("低落")) is None

    (tmp_path / "crisis_soothe.wav").write_bytes(b"S")
    (tmp_path / f"{fillers.mood_ack_name('低落')}.wav").write_bytes(b"M")
    assert fillers.pick_named("crisis_soothe") == b"S"
    assert fillers.pick_named(fillers.mood_ack_name("低落")) == b"M"


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
