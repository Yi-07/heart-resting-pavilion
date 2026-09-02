"""预置问题库(spec §4 L4:按空缺字段组织;骨架由预置库供,LLM 仅润色——MVP 不润色)。

每字段 2 个问法变体;过短降级重问时用第二变体。问序=Beck 概念化顺序:
情境→想法→行为→中间信念→核心信念(emotion 由粗稿/研判先填,空才问)。
"""

from app.agents.state import CollectState, FieldKey

FIELD_QUESTIONS: dict[FieldKey, list[str]] = {
    "situation": [
        "愿意说说最近发生了什么吗?挑一件最放不下的,简单描述一下当时的场景就好。",
        "嗯,换我问法——那件让你难受的事,是在什么场合、和谁之间发生的?",
    ],
    "emotion": [
        "这种感受更接近哪一种——焦虑、低落,还是疲惫?用一个词形容它。",
        "如果给这份感受起个名字,你会叫它什么?",
    ],
    "thought": [
        "当时脑子里闪过的第一个念头是什么?",
        "那一刻你心里对自己说了句什么?",
    ],
    "behavior": [
        "那之后你做了什么,或者忍住没做什么?",
        "这种时候,你通常会怎么应对?",
    ],
    "intermediate_belief": [
        "如果这类事反复发生,你会怎么总结其中的规则或前提?",
        "你觉得「必须怎样,否则就会怎样」的那个想法是什么?",
    ],
    "core_belief": [
        "再往深一点——这些经历让你觉得自己是个怎样的人?",
        "抛开所有角色,你内心深处最常冒出的那个自我评价是什么?",
    ],
}

ASK_ORDER: tuple[FieldKey, ...] = (
    "situation",
    "thought",
    "behavior",
    "emotion",
    "intermediate_belief",
    "core_belief",
)


def next_field(cs: CollectState) -> FieldKey | None:
    """按问序找第一个空缺字段;全满返回 None(由充分度/轮数收尾)。"""
    for field in ASK_ORDER:
        value = getattr(cs.formulation, field)
        if field == "emotion":
            if value.label is None:
                return field
        elif value is None:
            return field
    return None


def question_for(field: FieldKey, retry: bool = False) -> str:
    variants = FIELD_QUESTIONS[field]
    return variants[1] if retry and len(variants) > 1 else variants[0]
