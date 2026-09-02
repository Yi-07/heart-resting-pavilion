"""轮次填格提取(L5;每轮一次轻 LLM,失败降级填原文截断)。

提取不出值(off_topic=true 或 value=null)→ 返回 None,由 where_next 走
共情陪聊轮。值截断到 40 字(黑板格子容量)。
"""

from pydantic import BaseModel

from app.agents.state import FieldKey
from app.llm import LLMError, Message, get_provider

MAX_FIELD_LEN = 40


class _ExtractOut(BaseModel):
    value: str | None = None
    off_topic: bool = False


_SYSTEM = (
    "你从用户回答中提取指定字段的值,用于认知概念化表格。只输出 JSON:"
    '{"value":"提炼后的短句(≤30字)或null","off_topic":true|false}。'
    "规则:用户答的是这个问题→提炼(去口语、保原意);答非所问/跑题→off_topic=true;"
    "回答相关但没给出可用信息→value=null。"
)


async def extract_field(field: FieldKey, question: str, answer: str) -> str | None:
    """返回提炼值(截断);None=本轮没采到(陪聊轮);LLMError 降级填原文截断。"""
    user = f"字段:{field}\n问题:{question}\n用户回答:{answer}"
    try:
        out = await get_provider().chat_json(
            [Message("system", _SYSTEM), Message("user", user)], _ExtractOut
        )
    except LLMError:
        return answer.strip()[:MAX_FIELD_LEN] or None
    if out.off_topic or out.value is None:
        return None
    return out.value.strip()[:MAX_FIELD_LEN]
