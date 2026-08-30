"""router:闸门+分类+话术(职责表见 backend-plan §2)。

分类器(classifier)随步骤 3/4 分层判定接入;当前暴露 gate 与 phrases。
"""

from . import gate, phrases
from .gate import GateResult, check

__all__ = ["GateResult", "check", "gate", "phrases"]
