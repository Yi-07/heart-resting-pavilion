"""router:闸门+分类+话术(职责表见 backend-plan §2)。"""

from . import classifier, gate, phrases
from .classifier import Classification, classify
from .gate import GateResult, check

__all__ = ["Classification", "GateResult", "check", "classifier", "classify", "gate", "phrases"]
