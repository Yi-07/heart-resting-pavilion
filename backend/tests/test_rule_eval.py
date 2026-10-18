"""规则研判评测集(单源):带标注输入×期望判定,离线 pytest 全量跑分(零 LLM)。

- 组数:crisis(危机直述/否定/医学正用)、distress(困扰倾诉)、knowledge(知识问句,
  含错字)、greeting(问候)、ambiguous(规则层不可判,期望=落 LLM 或 collect 兜底)
- 期望判定分两层:gate(crisis 组 expected_gate=True)与 route/classify_rules
  (其余组 expected_route)。ambiguous 组钉「不误判 answer」:规则层期望 collect
  或 fallback(LLM 兜底同为 collect,安全侧),绝不 answer。
- 词表/规则改动(T2/T3/T4)必须过本集;扩词表先在这里加 case 再改码。
"""

from __future__ import annotations

import pytest

from app.collect import degrade
from app.router import classifier, gate
from app.router.classifier import Classification

# ---- 评测数据(标注单源;新增场景先加行再改码) ----

# 危机组:expected_gate=True;route 不评(危机闸门在分类器之前,命中即终结)
CRISIS_CASES: list[tuple[str, str]] = [
    # 直述
    ("我不想活了", "直述"),
    ("最近总是想着自杀", "直述"),
    ("站在天台上想跳楼", "方式直述"),
    ("想吞药一了百了", "方式直述"),
    # 委婉/变体(词表内)
    ("真想从这个世界上消失", "委婉"),
    ("没有我会更好吧", "自我否定危机"),
    # 医学正用不触发
    ("我每晚都要吃安眠药才能睡着", "医学正用"),
]

# 困扰组:route=collect;label 快速研判抽查个别
DISTRESS_CASES: list[tuple[str, str | None]] = [
    ("最近很焦虑睡不着", "焦虑"),
    ("心情一直低落,什么都提不起劲", None),
    ("压力大,好累啊", "疲惫"),
    ("最近总是失眠", None),
    ("感觉好孤独,没人理我", None),
    ("孩子升学的事让我很内耗", None),
]

# 知识组:route=answer+needs_rag(问候除外);含错字/口语问式
KNOWLEDGE_CASES: list[tuple[str, bool]] = [
    # (输入, needs_rag;问候类恒 False)
    ("什么是正念", True),
    ("正念有什么用", True),
    ("焦虑和紧张有什么区别", True),
    ("失眠怎么办", True),
    ("给我介绍下呼吸放松法", True),
    ("什么样正念", True),  # 人实测错字 case(T2 前规则层必 miss,见 test_ambiguous_no_answer)
    ("啥叫认知行为疗法", True),  # T2 词表扩容目标
    ("你好", False),
    ("晚上好呀", False),
]

# 歧义组:规则层判不了,期望=collect 或 fallback(LLM 兜底同为 collect);
# 钉死「绝不误判 answer」——错字/口语倾诉落进 LLM 层或安全侧兜底,不科普抢答
AMBIGUOUS_CASES: list[str] = [
    "帮我说说这事儿",
    "我最近那什么有点难受",
    "就是很烦说不清",
    "唉",
]

# 降级组:collect 链路 degrade.detect 期望
DEGRADE_CASES: list[tuple[str, str | None]] = [
    ("好", "too_short"),
    ("嗯", "too_short"),
    ("感觉自己就是个废物", "negative"),
    ("这事儿让我很崩溃,撑不住了", "negative"),
    ("上周开会的时候,领导当众批评我,我脑子里一片空白。", None),
    ("每天晚上都睡不着,白天上班没精神", None),
    # T4 自指/他指分档
    ("我觉得自己没用,什么都做不好", "negative"),  # 他指词+自指线索共现 → 收尾
    ("这份工作干着没意义,想换", None),  # 他指词无自指 → 继续采集
    ("这个功能设计得真糟透了", None),  # 评价事物 → 继续采集
    ("最近总觉得活得没意义", "negative"),  # 生存陈述归自指
]


# ---- gate 层全量 ----


@pytest.mark.parametrize(("text", "_tag"), CRISIS_CASES)
def test_crisis_gate(text: str, _tag: str) -> None:
    r = gate.check(text)
    expected = "医学正用" not in _tag
    assert r.hit is expected, f"{_tag}: {text} → hit={r.hit}"


def test_crisis_medical_positive_use_detail() -> None:
    # 医学正用:不 hit 但 matched 留痕,软信号复核仍有入口
    r = gate.check("我每晚都要吃安眠药才能睡着")
    assert r.hit is False
    assert "吃安眠药" in r.matched


# ---- classify_rules 层全量 ----


def _assert_no_answer(text: str, c: Classification) -> None:
    assert c.route == "collect" and c.source in ("rule", "fallback"), (
        f"歧义输入误判 answer: {text} → {c}"
    )


@pytest.mark.parametrize("text", AMBIGUOUS_CASES)
def test_ambiguous_no_answer(text: str) -> None:
    _assert_no_answer(text, classifier.classify_rules(text))


@pytest.mark.parametrize(("text", "label"), DISTRESS_CASES)
def test_distress_collect(text: str, label: str | None) -> None:
    c = classifier.classify_rules(text)
    assert c.route == "collect" and c.source == "rule", f"{text} → {c}"
    if label is not None:
        assert c.emotion_label == label, f"{text} label={c.emotion_label}"


# T2 词表扩容已落地,基线 miss 全部转正;集合留空位,新缺口先入此再改码。
KNOWN_T2_PENDING: set[str] = set()


@pytest.mark.parametrize(("text", "needs_rag"), KNOWLEDGE_CASES)
def test_knowledge_route(text: str, needs_rag: bool) -> None:
    if text in KNOWN_T2_PENDING:
        pytest.xfail("词表扩容目标:基线已知 miss,扩词表后从 KNOWN_T2_PENDING 删除转正")
    c = classifier.classify_rules(text)
    assert c.route == "answer" and c.needs_rag is needs_rag


# ---- T2 规则序纠偏钉:倾诉优先于知识问法(双方向防回退) ----


@pytest.mark.parametrize(
    "text",
    [
        "我最近很痛苦,怎么办",  # 人报案例:原知识词先行→answer 科普抢答
        "我睡不着,有什么办法",
        "总是很难受,有什么方法能改善",
        "我很焦虑,你有什么建议",
    ],
)
def test_distress_beats_knowledge(text: str) -> None:
    c = classifier.classify_rules(text)
    assert c.route == "collect" and c.source == "rule", f"倾诉被科普抢答: {text} → {c}"


@pytest.mark.parametrize(
    ("text", "needs_rag"),
    [("怎么缓解焦虑", True), ("失眠有什么办法", True), ("有什么方法可以缓解紧张", True)],
)
def test_pure_knowledge_still_answer(text: str, needs_rag: bool) -> None:
    # 无自指线索的纯知识问句不受规则序调整影响(防按下葫芦浮起瓢)
    c = classifier.classify_rules(text)
    assert c.route == "answer" and c.needs_rag is needs_rag, f"{text} → {c}"


# ---- degrade 层全量 ----


@pytest.mark.parametrize(("text", "expected"), DEGRADE_CASES)
def test_degrade(text: str, expected: str | None) -> None:
    assert degrade.detect(text) == expected
