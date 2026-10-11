"""语音模块门面(backend-plan §2 voice 行):asr 转写 · tts 合成 · fillers 预生成。

asr 在 backend venv(funasr+SenseVoice);tts 经 sidecar HTTP 调 CosyVoice 仓库
自备 venv(两套 torch 不兼容,进程隔离);全部懒加载,网关启动零模型成本。
"""

from app.voice import fillers
from app.voice.asr import transcribe
from app.voice.tts import synthesize, synthesize_stream

__all__ = ["fillers", "synthesize", "synthesize_stream", "transcribe"]
