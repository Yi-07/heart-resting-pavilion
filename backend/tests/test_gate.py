"""gate.check 接缝钉测试(backend-plan §11):命中/未命中/阈值边界/matched 审计覆盖。"""

from app import config
from app.router import gate


def test_hit_direct_phrase():
    r = gate.check("我不想活了")
    assert r.hit is True
    assert r.severity == 1.0
    assert "不想活" in r.matched  # matched 覆盖审计所需命中项


def test_miss_collect_like_text():
    r = gate.check("最近很焦虑睡不着")
    assert r.hit is False
    assert r.matched == []
    assert r.severity == 0.0


def test_soft_term_alone_below_threshold():
    r = gate.check("我觉得很绝望")
    assert r.hit is False  # 0.4 < 0.7
    assert "绝望" in r.matched
    assert r.severity == 0.4


def test_threshold_boundary_hit(monkeypatch):
    monkeypatch.setattr(config, "CRISIS_GATE_THRESHOLD", 0.4)
    r = gate.check("我觉得很绝望")  # severity == 阈值 → hit(判据 ≥)
    assert r.hit is True


def test_multiple_soft_matches_max_not_sum():
    r = gate.check("很绝望,也想消失")  # 0.4 + 0.4 → 取最大值,不累加
    assert r.severity == 0.4
    assert r.hit is False
    assert set(r.matched) == {"绝望", "想消失"}


def test_core_beats_soft():
    r = gate.check("撑不下去了,想自杀")
    assert r.hit is True
    assert r.severity == 1.0


def test_empty_text_safe():
    r = gate.check("")
    assert r.hit is False
    assert r.matched == []
    assert r.severity == 0.0
