"""where_next 接缝钉测试(backend-plan §11):CollectEvent 四变体各分支
(继续问/陪聊/终结三因/升级);附 collect 三件小接缝(degrade/问题库)。"""

from app import collect
from app.agents.graph import where_next
from app.agents.state import CollectState
from app.schema import Emotion, Formulation


def _cs(**kwargs: object) -> CollectState:
    defaults: dict[str, object] = {
        "session_id": "sess_t",
        "route": "collect",
        "template": "beck_formulation",
        "emotion_label": "焦虑",
        "confidence": 0.9,
    }
    defaults.update(kwargs)
    return CollectState(**defaults)  # type: ignore[arg-type]


def test_branch_ask_when_fields_missing():
    cs = _cs()
    cs.formulation = Formulation(emotion=Emotion(label="焦虑"))
    cs.sufficiency = 0.2
    assert where_next(cs) == "ask"


def test_branch_chat_on_off_topic():
    cs = _cs()
    cs.degrade_reason = "off_topic"
    assert where_next(cs) == "chat"


def test_branch_finish_sufficient():
    cs = _cs()
    cs.sufficiency = 0.75  # ≥0.7
    assert where_next(cs) == "finish"


def test_branch_finish_max_rounds():
    cs = _cs()
    cs.round_index = 3
    cs.max_rounds = 3
    cs.sufficiency = 0.4  # 未达标但轮数到顶
    assert where_next(cs) == "finish"


def test_branch_finish_negative_degrade():
    cs = _cs()
    cs.degrade_reason = "negative"
    cs.sufficiency = 0.0
    assert where_next(cs) == "finish"


def test_branch_escalate_when_flagged():
    cs = _cs()
    cs.escalated = True
    assert where_next(cs) == "escalate"


def test_too_short_still_asks():
    cs = _cs()
    cs.degrade_reason = "too_short"  # 过短=重问,不终结
    assert where_next(cs) == "ask"


# ---- collect 三件小接缝 ----


def test_degrade_detect():
    assert collect.detect("嗯") == "too_short"
    assert collect.detect("我就是个废物,什么都做不好") == "negative"
    assert collect.detect("那天开会我被当众否定了,特别难受") is None


def test_next_field_order_and_skip():
    cs = _cs()
    cs.formulation = Formulation(
        emotion=Emotion(label="焦虑"), situation="x", thought="y"
    )
    assert collect.next_field(cs) == "behavior"  # 问序 situation→thought→behavior
    cs.formulation.behavior = "z"
    assert collect.next_field(cs) == "intermediate_belief"


def test_question_retry_variant():
    first = collect.question_for("thought")
    retry = collect.question_for("thought", retry=True)
    assert first != retry
