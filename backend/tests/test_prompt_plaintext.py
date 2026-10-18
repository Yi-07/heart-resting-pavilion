"""用户可见 LLM 输出的纯文本约束(仅提示词侧,本轮无后处理、无清洗测试)。

answer 直答两分支与 collect 停采总结的 system 段必须带纯文本/禁 Markdown/
等号改「等于」的要求,同时原有字数、非医疗诊断、「不用列表」等约束不能被挤掉;
collect 追问与陪聊 prompt 本轮不动,按原文逐字钉死当回归线。

钉原文的预期值在本文件内独立抄写,**不从 app.agents.ask 导入 _SYSTEM 再自比**
——那样断言恒真,等于没钉。
"""

from app.agents import ask as ask_mod
from app.agents.analysis import summary_messages
from app.agents.state import CollectState, PendingQuestion
from app.rag.corpus import Ref
from app.ws_gateway.gateway import _answer_messages

_ANSWER_KEYS = ("纯文本", "不要使用 Markdown 格式", "等于", "不要解释这些输出规则")
_SUMMARY_KEYS = ("纯文本", "不使用 Markdown", "等于", "不要输出格式说明")


def _state() -> CollectState:
    return CollectState(
        session_id="sess_t",
        route="collect",
        template="scene_default",
        emotion_label="焦虑",
        confidence=0.9,
        max_rounds=3,
    )


def _ref() -> Ref:
    return Ref(id="r1", question="什么是正念", answer="正念是觉察练习")


def test_answer_science_prompt_has_plaintext_rules():
    """科普分支(带 RAG 资料):新约束到位,原有字数与不诊断约束保留。"""
    system = _answer_messages("什么是正念", [_ref()])[0].content
    for key in _ANSWER_KEYS:
        assert key in system
    assert "150 字内" in system
    assert "不做医疗诊断" in system


def test_answer_companion_prompt_has_plaintext_rules():
    """陪伴分支(无 RAG 资料):同样带约束,80 字内与不连续追问保留。"""
    system = _answer_messages("今天有点累", [])[0].content
    for key in _ANSWER_KEYS:
        assert key in system
    assert "80 字内" in system
    assert "不做医疗诊断" in system


def test_summary_prompt_has_plaintext_rules():
    """collect 总结:新约束到位,「不列条目」「不用列表」「不做医疗诊断」保留。"""
    system = summary_messages(_state(), [_ref()])[0].content
    for key in _SUMMARY_KEYS:
        assert key in system
    assert "不列条目" in system
    assert "不用列表" in system
    assert "不做医疗诊断" in system


_ASK_SYSTEM_EXPECTED = (
    "你是心栖阁的共情陪伴者,正在陪用户做认知梳理。你根据当前要了解的信息,"
    "用自然、温暖、口语化的方式向用户提出**一个**问题(不要列表,不要一次性问多件事)。"
    "建议式非命令式,不做医疗诊断,不说教。问之前如果用户刚说了新内容,"
    "先用半句自然地接住它(确认随问句带出,不单独成段),再顺势问下去。"
    "问题要具体、好回答,像一个真的在听的人随口问出来的。40 字内。"
    "不要自我介绍,不要每次都叫用户「我注意到你」这类套话。"
)

_CHAT_SYSTEM_BASE_EXPECTED = (
    "你是心栖阁的共情陪伴者。用户暂时跑题了或没接上梳理的问题,"
    "不评判、不硬拉回正题,先自然地接住这轮的话(短回应,60 字内),"
    "口语化、温暖,不做医疗诊断。"
)

_CHAT_SYSTEM_PENDING_EXPECTED = _CHAT_SYSTEM_BASE_EXPECTED + (
    "接住之后,用一句与回应自然衔接的话,把话题轻轻带回那个还没聊完的部分——"
    "比如顺着共同点问下去;实在没有关联,就点一下它(「前面你提到的…」)。"
    "只带一句,用户接不接由他,别追问别催。"
)


def test_ask_system_prompt_unchanged():
    """追问 prompt 本轮不动:system 段逐字钉死,纯文本约束不许渗进来。"""
    system = ask_mod.ask_messages(_state(), "thought", "工作上老担心做不好")[0].content
    assert system == _ASK_SYSTEM_EXPECTED


def test_chat_system_prompt_unchanged():
    """陪聊 prompt 本轮不动:有无挂起提问两种 system 均逐字钉死。"""
    cs = _state()
    assert ask_mod.chat_messages(cs, "聊聊天气吧")[0].content == _CHAT_SYSTEM_BASE_EXPECTED

    cs.pending_question = PendingQuestion(text="当时你在想什么?", target_field="thought")
    assert (
        ask_mod.chat_messages(cs, "聊聊天气吧")[0].content
        == _CHAT_SYSTEM_PENDING_EXPECTED
    )