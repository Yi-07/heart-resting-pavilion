"""collect:采集三件——预置问题库/充分度/降级检测(spec §4 L4;管状态不管话术)。"""

from .degrade import detect
from .questions import ASK_ORDER, FIELD_QUESTIONS, next_field, question_for
from .sufficiency import WEIGHTS, should_stop, sufficiency

__all__ = [
    "ASK_ORDER",
    "FIELD_QUESTIONS",
    "WEIGHTS",
    "detect",
    "next_field",
    "question_for",
    "should_stop",
    "sufficiency",
]
