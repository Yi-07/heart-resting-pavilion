"""语音模块门面(backend-plan §2 voice 行):asr 转写 · tts 合成 · fillers 预生成。

远程模式(TTS_MODE=remote / ASR_MODE=remote):经 HTTP 调远程服务,主服务零模型成本。
本地模式:funasr 本地推理(asr.py) + CosyVoice sidecar(tts.py)。
"""

from app.voice import fillers
from app.voice.asr import transcribe
from app.voice.tts import synthesize, synthesize_stream

__all__ = ["fillers", "synthesize", "synthesize_stream", "transcribe"]
