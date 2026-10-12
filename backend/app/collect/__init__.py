"""collect:采集三件——问序单源/充分度/降级检测(spec §4 L4;管状态不管话术)。"""

from .degrade import detect
from .questions import ASK_ORDER, FIELD_INFO_NEED, next_field
from .sufficiency import WEIGHTS, should_stop, sufficiency

__all__ = [
    "ASK_ORDER",
    "FIELD_INFO_NEED",
    "WEIGHTS",
    "detect",
    "next_field",
    "should_stop",
    "sufficiency",
]
