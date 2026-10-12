"""采集问序单源(spec §4 L4:预置问题库降级为字段选择/问序的内部结构单源,
不作对外话术——问话由 LLM 流式生成,backend-plan §2 collect 行)。

问序=Beck 概念化顺序:情境→想法→行为→中间信念→核心信念(emotion 由粗稿/
研判先填,空才问)。字段信息需求描述供问话 prompt 使用。
"""

from app.agents.state import CollectState, FieldKey

ASK_ORDER: tuple[FieldKey, ...] = (
    "situation",
    "thought",
    "behavior",
    "emotion",
    "intermediate_belief",
    "core_belief",
)

FIELD_INFO_NEED: dict[FieldKey, str] = {
    "situation": "触发情境——具体发生了什么、在什么场合、和谁之间",
    "emotion": "情绪反应——这份感受更像什么(一个情绪词)",
    "thought": "自动思维——当时脑子里闪过的念头、心里对自己说的话",
    "behavior": "行为反应——当时做了什么、或忍住没做什么",
    "intermediate_belief": "中间信念——这类事反复发生时,「必须怎样否则就会怎样」的规则或前提",
    "core_belief": "核心信念——这些经历让人对自己产生怎样的自我评价",
}


def next_field(cs: CollectState) -> FieldKey | None:
    """按问序找第一个空缺字段;全满返回 None(由充分度/轮数收尾)。"""
    for field in ASK_ORDER:
        if not cs.formulation.is_filled(field):
            return field
    return None
