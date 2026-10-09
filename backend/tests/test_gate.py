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


def test_all_core_terms_hit_individually():
    # A1 扩充钉死:核心词表每条必须独立命中(防词表手滑改档/漏登记)
    for term in gate.CORE_TERMS:
        r = gate.check(term)
        assert r.hit is True, f"核心词未命中: {term}"
        assert r.severity == 1.0
        assert term in r.matched


def test_all_soft_terms_match_below_threshold():
    for term in gate.SOFT_TERMS:
        r = gate.check(term)
        assert r.hit is False, f"软信号词单独不应触危机: {term}"
        assert r.severity == 0.4
        assert term in r.matched


def test_new_real_expressions_hit():
    # 真实表述抽钉(全量覆盖见 test_all_core_terms_hit_individually);含软埋消失族表述
    for text in ["站在天台上想跳楼", "手腕上有伤是割腕的", "觉得一了百了就轻松了",
                 "我想离开这个世界", "没有我会更好吧", "吞药是不是就不疼了",
                 "要是我能从这个世界上消失就好了", "真想从这个世上消失一阵子"]:
        r = gate.check(text)
        assert r.hit is True, f"真实危机表述未命中: {text}"


def test_medical_sleeping_pill_usage_no_hit():
    # "吃安眠药"有医疗正用→软档:单独出现不触发,但仍入 matched 供 risk 复核
    r = gate.check("我每晚都要吃安眠药才能睡着")
    assert r.hit is False
    assert "吃安眠药" in r.matched
    # 过量自杀表述仍走核心档命中
    assert gate.check("想吞药一了百了").hit is True
