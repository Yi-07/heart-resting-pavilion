"""TTS 异常:两种运行模式共用。

为什么要单独一个模块:tts.py 是 `if remote: import ... else: define ...` 的路由层,
异常类若在两个分支各定义一次,mypy 会报 no-redef(现有的 TTSError 就是这样)。
把异常放到中立模块、两个分支都 import,mypy 就认得它们是同一个类。

打断异常与失败异常必须分开:抢占是正常业务事件,不该在日志里刷 degraded。
"""

from __future__ import annotations


class TTSError(RuntimeError):
    """TTS 不可用/合成失败;调用方按契约降级跳过音频、不杀回合。"""


class TTSCancelled(TTSError):
    """回合被打断(不是故障)。

    继承 TTSError 是为了让"粗粒度只捕 TTSError"的老代码不至于漏掉它;
    需要区分"打断"与"故障"的地方必须先捕 TTSCancelled。
    """
