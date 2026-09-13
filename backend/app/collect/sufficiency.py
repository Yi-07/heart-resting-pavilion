"""充分度打分(backend-plan §4;数值单源=本模块,别处不复制)。

权重覆盖 formulation 六字段;停采两档:常规 0.7(常态 2~3 轮收尾,信念留白)、
测试档 0.85(约 3 轮挖信念)。档位取值归 config。
"""

from app import config
from app.schema import Formulation

WEIGHTS: dict[str, float] = {
    "situation": 0.20,
    "emotion": 0.20,
    "thought": 0.20,
    "behavior": 0.15,
    "intermediate_belief": 0.15,
    "core_belief": 0.10,
}


def sufficiency(f: Formulation) -> float:
    """已采字段(非 null)权重之和;填格判定单源=Formulation.is_filled。"""
    filled = 0.0
    for key, weight in WEIGHTS.items():
        if f.is_filled(key):
            filled += weight
    return round(filled, 4)


def should_stop(score: float, threshold: float | None = None) -> bool:
    stop_at = threshold if threshold is not None else config.COLLECT_STOP_THRESHOLD
    return score >= stop_at
