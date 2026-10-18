"""停采后同步分析(spec §4 L5 / backend-plan §3.3):emotion 复核 + RAG 引用 + 人话总结。

两级标签第二级:LLM 复核 emotion(label/intensity)合入精稿;失败保留研判值。
总结基于完整 formulation + RAG 引用流式生成;邀请语由网关在总结末尾拼
(phrases 话术库模板,不走 LLM)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from app.agents.state import CollectState
from app.llm import LLMError, Message, get_provider
from app.schema import Emotion, Formulation

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


def summary_messages(
    cs: CollectState, refs: list[Ref], memories: list[dict[str, Any]] | None = None
) -> list[Message]:
    """总结 prompt:人话总结 formulation + RAG 引用建议(资料没有的不编造);
    带热层历史摘要时先交代上回语境(跨回合连续性,唯一 prompt 侧消费点);
    语义记忆条目注入(「想起」非翻旧账——LLM 临场取舍,PRD 防线设计)。
    user 段剔 intensity(数值类字段不进 prompt,防「xx%」混入人话总结,PRD)。"""
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
    mem_note = ""
    if memories:
        mem_desc = "\n".join(f"- {m['text']}" for m in memories)
        mem_note = (
            "\n\n用户之前还聊过这些(与本轮相关时自然呼应一句即可,"
            "用户没主动提就别展开翻旧账):\n" + mem_desc
        )
    system = (
        "你是心栖阁的共情陪伴者。基于认知概念化表格,用人话帮用户回看这次梳理:"
        "先温柔地照见情境与情绪,再点出想法-行为之间的联系,最后给 1~2 条贴合的"
        "小建议(建议式非命令式,不做医疗诊断)。温暖口语,250 字内,不用列表。"
        # 纯文本约束(与 answer 同意图,措辞独立):总结同样要上屏 + 逐句 TTS。
        # 放在 {context} 之前,RAG 资料仍留在最后一段。
        "只输出自然连贯的纯文本，不使用 Markdown，不使用列表或标题格式。"
        "不要使用「」或类似符号。"
        "不要输出等号，统一写成“等于”。"
        "不要输出格式说明、引用标记或特殊排版符号。"
        f"{context}"
    )
    data = cs.formulation.model_dump(by_alias=True)
    if isinstance(data.get("emotion"), dict):
        # 数值强度不进 prompt:总结是人话不是量表读数(PRD 裁定)
        data["emotion"] = {"label": data["emotion"].get("label")}
    user = Formulation(**data).model_dump_json(by_alias=True) + history + mem_note
    return [Message("system", system), Message("user", user)]


async def summary_stream(
    cs: CollectState, refs: list[Ref], memories: list[dict[str, Any]] | None = None
) -> AsyncIterator[str]:
    """总结流式;LLMError 甩给调用方降级(话术库兜底)。"""
    chunks = get_provider().stream(summary_messages(cs, refs, memories))
    async for chunk in chunks:
        yield chunk


_NOTE_SYSTEM = (
    "你是记忆归档员。把这次梳理压成给未来检索用的短笔记。"
    "只输出 JSON:{\"new\":[\"30~60字笔记,只留主题+关键线索,不写建议不写客套\"],"
    "\"settled\":[\"本轮已化解的旧条目id\"]}。笔记是转述,绝不引用用户原话。"
)

_NOTE_USER_TEMPLATE = (
    "本次表格:{formulation}\n"
    "本次召回的历史记忆:{recalled}\n"
    "若其中某条与本次话题相关且本次已化解/推进,把它的 id 放进 settled;没有则空数组。"
)


def note_messages(cs: CollectState, recalled: list[dict[str, Any]]) -> list[Message]:
    """检索笔记 prompt:笔记 + 状态闭环一并产出(回合末异步,不碰回合时延)。"""
    recalled_desc = (
        "\n".join(f"- {r['id']}: {r['text']}" for r in recalled) if recalled else "无"
    )
    user = _NOTE_USER_TEMPLATE.format(
        formulation=cs.formulation.model_dump_json(by_alias=True)[:600],
        recalled=recalled_desc,
    )
    return [Message("system", _NOTE_SYSTEM), Message("user", user)]


async def generate_note_raw(cs: CollectState, recalled: list[dict[str, Any]]) -> str:
    """检索笔记 LLM 输出原文(非流式);LLMError 上抛由网关降级为确定性拼接。"""
    return await get_provider().chat(note_messages(cs, recalled))
