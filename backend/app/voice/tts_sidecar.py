"""CosyVoice2 TTS sidecar —— 在 models/voices/CosyVoice 自备 venv(Python 3.10)下
运行的独立 HTTP 服务,与 backend venv 进程隔离(两套 torch 版本互不兼容)。

- stdlib http.server,零框架依赖;POST /tts {"text": ...} → audio/wav(24k);
  GET /health → {"ready": bool}(模型后台加载,首次合成前 ready=false)
- 音色:零样本模式,固定用仓库自带 asset/zero_shot_prompt.wav(+ 配套提示文本),
  保证与 fillers 预生成同音色
- 启动方式:backend/app/voice/tts.py 懒拉起(也可手动:
  models/voices/CosyVoice/.venv/Scripts/python.exe backend/app/voice/tts_sidecar.py)
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sidecar_protocol import (
    SIDECAR_VERSION,
)

if TYPE_CHECKING:
    import torch

REPO = Path(__file__).resolve().parents[3] / "models" / "voices" / "CosyVoice"
MODEL_DIR = REPO / "pretrained_models" / "CosyVoice2-0.5B"
PROMPT_WAV = REPO / "asset" / "zero_shot_prompt.wav"
PROMPT_TEXT = "希望你以后能够做的比我还好呦。"

PORT = int(os.environ.get("TTS_SIDECAR_PORT", "9880"))

_state_lock = threading.Lock()
_state: dict[str, Any] = {"ready": False, "error": None}


def _health_payload() -> dict[str, Any]:
    with _state_lock:
        return {
            "ready": bool(_state["ready"]),
            "error": _state["error"],
            "version": SIDECAR_VERSION,
        }


def _tensor_from_wav_path(path: str | Path, target_sr: int) -> torch.Tensor:
    """任意 wav(含 IEEE-float)→ ffmpeg 16k/mono/s16 → (1,T) float 张量。
    不用 torchaudio.load:该 venv 被 pip 升级过 torch,新 torchaudio 要 torchcodec;
    ffmpeg 现转 + stdlib wave 解析,对版本地狱免疫。"""
    import struct
    import wave

    import torch

    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(target_sr),
            "-sample_fmt", "s16", "-f", "wav", "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    with wave.open(io.BytesIO(proc.stdout), "rb") as w:
        frames = w.readframes(w.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    return torch.tensor(samples, dtype=torch.float32).unsqueeze(0) / 32768.0


def _wav_bytes(t: torch.Tensor, sr: int) -> bytes:
    """(1,T) float 张量 → 16bit PCM wav 字节(stdlib,同上免疫)。"""
    import wave

    import torch

    data = (t.squeeze(0).clamp(-1.0, 1.0) * 32767.0).to(torch.int16).cpu().numpy().tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data)
    return buf.getvalue()


def _patch_load_wav() -> None:
    """替换 cosyvoice 的 load_wav(frontend 对 prompt 张量/路径都会调它;原实现走
    torchaudio.load,在新 torchaudio 下要 torchcodec)。张量直通,路径走 ffmpeg。
    注意 frontend 是 from-import 绑定——必须先补 file_utils 再让 frontend 导入,
    并双保险重绑 frontend 模块属性。"""
    import cosyvoice.utils.file_utils as fu
    import torch
    import torchaudio.transforms

    def load_wav(wav: object, target_sr: int, min_sr: int = 16000) -> torch.Tensor:
        if isinstance(wav, torch.Tensor):
            speech = wav if wav.dim() == 2 else wav.unsqueeze(0)
            sr = 16000  # 本 sidecar 传入的 prompt 恒为 16k
        else:
            speech = _tensor_from_wav_path(str(wav), target_sr)
            sr = target_sr
        if sr != target_sr:
            speech = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)(speech)
        return speech

    fu.load_wav = load_wav
    import cosyvoice.cli.frontend as frontend_mod

    frontend_mod.load_wav = load_wav


def _load_model() -> None:
    try:
        sys.path.insert(0, str(REPO))
        _patch_load_wav()
        from cosyvoice.cli.cosyvoice import CosyVoice2

        prompt = _tensor_from_wav_path(PROMPT_WAV, 16000)
        cosyvoice = CosyVoice2(str(MODEL_DIR), load_jit=False, load_trt=False)
        with _state_lock:
            _state["model"] = cosyvoice
            _state["prompt"] = prompt
            _state["ready"] = True
        print(f"[sidecar] ready: {MODEL_DIR}", flush=True)
    except Exception as exc:  # noqa: BLE001 — 启动失败写进 /health 供诊断
        with _state_lock:
            _state["error"] = str(exc)
        print(f"[sidecar] load failed: {exc}", flush=True)


def synth(text: str) -> bytes:
    """文本 → wav 字节(24k);合成串行(单卡单模型)。"""
    with _state_lock:
        model = _state.get("model")
        prompt = _state.get("prompt")
    if model is None or prompt is None:
        raise RuntimeError("模型未就绪")
    result = next(model.inference_zero_shot(text, PROMPT_TEXT, prompt, stream=False))
    return _wav_bytes(result["tts_speech"], 24000)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps(_health_payload()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/tts":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            text = json.loads(self.rfile.read(length))["text"]
            wav = synth(text)
        except Exception as exc:  # noqa: BLE001 — 合成失败回 500 文本
            body = str(exc).encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav)))
        self.end_headers()
        self.wfile.write(wav)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[sidecar] {fmt % args}", flush=True)


def main() -> None:
    threading.Thread(target=_load_model, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[sidecar] listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
