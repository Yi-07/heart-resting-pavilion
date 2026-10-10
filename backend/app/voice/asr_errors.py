"""ASR 异常:两种运行模式共用。

为什么要单独一个模块:asr.py 是 `if remote: import ... else: define ...` 的路由层,
异常类若在两个分支各定义一次,mypy 会报 no-redef。把 ASRError 放到中立模块、
两个分支都 import,mypy 就认得它们是同一个类。

与 app.voice.tts_errors 同理。"""

from __future__ import annotations


class ASRError(RuntimeError):
    """转写失败(转码/模型/服务不可用);调用方降级直答/温和降级。"""
