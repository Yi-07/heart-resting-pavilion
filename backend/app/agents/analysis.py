"""停采后同步分析(spec §4 L5 / backend-plan §3.3):emotion 复核 + RAG 引用 + 人话总结。

两级标签第二级:LLM 复核 emotion(label/intensity)合入精稿;失败保留研判值。
总结基于完整 formulation + RAG 引用流式生成;邀请语由网关在总结末尾拼
(phrases 话术库模板,不走 LLM)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from pydantic import BaseModel

from app.agents.state import CollectState
from app.llm import LLMError, Message, get_provider
from app.schema import Emotion

if TYPE_CHECKING:
    from app.rag.corpus import Ref

_REVIEW_SYSTEM = (
    "你是情绪研判器。基于采集到的认知概念化表格,复核用户的主导情绪与强度。"
    '只输出 JSON:{"label":"一个中文情绪词","intensity":0到1的小数}。'
)


class _ReviewOut(BaseModel):
    label: str
    intensity: float


async def review_emotion(cs: CollectState) -> Emotion:
    """emotion 复核;失败返回当前值(LLMError 降级,精稿照发)。"""
    current = cs.formulation.emotion
    lines = "\n".join(
        f"{t.role}: {t.text}" for t in cs.turns if t.role == "user"
    )
    user = (
        f"快速研判标签:{cs.emotion_label}\n已采表格:{cs.formulation.model_dump_json(by_alias=True)}"
        f"\n对话记录:\n{lines[:600]}"
    )
    try:
        out = await get_provider().chat_json(
            [Message("system", _REVIEW_SYSTEM), Message("user", user)], _ReviewOut
        )
    except LLMError:
        return Emotion(label=current.label, intensity=current.intensity)
    return Emotion(label=out.label, intensity=min(max(out.intensity, 0.0), 1.0))


def summary_messages(cs: CollectState, refs: list[Ref]) -> list[Message]:
    """总结 prompt:人话总结 formulation + RAG 引用建议(资料没有的不编造);
    带热层历史摘要时先交代上回语境(跨回合连续性,唯一 prompt 侧消费点)。"""
    context = ""
    if refs:
        context = (
            "\n\n可参考的心理科普资料(自然融入,不列条目,资料没有的不编造):\n"
            + "\n\n".join(f"【{r.question}】\n{r.answer}" for r in refs)
        )
    history = ""
    if cs.session_context.history_summary:
        clipped = cs.session_context.history_summary[:200]
        history = f"\n\n用户这轮之前还有一次梳理,摘要是:{clipped}"
    system = (
        "你是心栖阁的共情陪伴者。基于认知概念化表格,用人话帮用户回看这次梳理:"
        "先温柔地照见情境与情绪,再点出想法-行为之间的联系,最后给 1~2 条贴合的"
        f"小建议(建议式非命令式,不做医疗诊断)。温暖口语,250 字内,不用列表。{context}"
    )
    user = cs.formulation.model_dump_json(by_alias=True) + history
    return [Message("system", system), Message("user", user)]


async def summary_stream(cs: CollectState, refs: list[Ref]) -> AsyncIterator[str]:
    """总结流式;LLMError 甩给调用方降级(话术库兜底)。"""
    chunks = get_provider().stream(summary_messages(cs, refs))
    async for chunk in chunks:
        yield chunk
