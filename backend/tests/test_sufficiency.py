"""sufficiency 接缝钉测试(backend-plan §11):字段组合覆盖权重;停采两档边界。"""

import pytest

from app import config
from app.collect.sufficiency import WEIGHTS, should_stop, sufficiency
from app.schema import Emotion, Formulation


def _f(**filled: str) -> Formulation:
    f = Formulation()
    for key, value in filled.items():
        if key == "emotion":
            f.emotion = Emotion(label=value)
        else:
            setattr(f, key, value)
    return f


def test_empty_scores_zero():
    assert sufficiency(Formulation()) == 0.0


def test_single_field_weights():
    assert sufficiency(_f(situation="x")) == 0.20
    assert sufficiency(_f(emotion="焦虑")) == 0.20
    assert sufficiency(_f(thought="x")) == 0.20
    assert sufficiency(_f(behavior="x")) == 0.15
    assert sufficiency(_f(intermediate_belief="x")) == 0.15
    assert sufficiency(_f(core_belief="x")) == 0.10


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_combined_fields_accumulate():
    f = _f(emotion="焦虑", situation="x", thought="y")
    assert sufficiency(f) == 0.60


def test_emotion_null_label_scores_zero():
    f = Formulation(emotion=Emotion(label=None, intensity=0.8))
    assert sufficiency(f) == 0.0  # intensity 不算,label 才算


def test_stop_thresholds_boundaries():
    assert should_stop(0.70) is True  # 恰好=常规档 → 停(≥)
    assert should_stop(0.6999) is False
    assert should_stop(0.60, threshold=0.60) is True  # 测试档边界
    assert should_stop(0.85, threshold=config.COLLECT_TEST_STOP_THRESHOLD) is True
    assert should_stop(0.84, threshold=config.COLLECT_TEST_STOP_THRESHOLD) is False
