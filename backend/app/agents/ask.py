"""问话 LLM prompt(spec §4 L4 采集器规格「问题生成/进度感知」)。

系统提示词规范共情陪伴者风格(建议式、口语化、不做医疗诊断);已采字段与
剩余轮数进 prompt(进度感知由对话自然带出);对话历史注入(turns 原话,热层
过期降级回合摘要,spec L7 问话注入通道);语义记忆召回注入(「想起」非
翻旧账)。target_field 由字段选择单源(collect 模块)定,信息需求描述进
prompt,文本不落预置。
"""

from app import config
from app.agents.state import CollectState, FieldKey, Turn
from app.llm import Message

_HISTORY_ROUNDS = 6
"""对话历史注入轮数上限(与风险复核 recent 6 轮同族;prompt 不落日志,原话
进 prompt 不碰脱敏红线,截轮数即控上下文体积)。"""

_HISTORY_SUMMARY_CAP = 200
"""热层过期降级注入的回合摘要截断(与总结 prompt 同口径)。"""

_SYSTEM = (
    "你是心栖阁的共情陪伴者,正在陪用户做认知梳理。你根据当前要了解的信息,"
    "用自然、温暖、口语化的方式向用户提出**一个**问题(不要列表,不要一次性问多件事)。"
    "建议式非命令式,不做医疗诊断,不说教。问之前如果用户刚说了新内容,"
    "先用半句自然地接住它(确认随问句带出,不单独成段),再顺势问下去。"
    "问题要具体、好回答,像一个真的在听的人随口问出来的。40 字内。"
    "不要自我介绍,不要每次都叫用户「我注意到你」这类套话。"
)

_PROGRESS_TMPL = (
    "本轮要了解的信息:{info_need}(所问主题:{field})。"
    "已聊过的内容:{filled}。还能问的轮数不多了({rounds_left} 轮以内),"
    "如果接近尾声就把最重要的问出来。"
)

_EMPTY_FILLED = "(用户刚开口,还没有梳理内容——第一问,自然地开场)"


def turns_context(turns: list[Turn], *, exclude_last_user: bool = False) -> str:
    """对话历史段(三注入点共用):最近若干轮原话,role 标注,时间正序。

    exclude_last_user=True 排除最后一条 user 轮——它是本轮回答,调用方已单独
    注入,重复注入会让 LLM 把同一句话当两轮对话。空历史返回空串(调用方跳段)。
    """
    recent = list(turns)
    if exclude_last_user and recent and recent[-1].role == "user":
        recent = recent[:-1]
    recent = recent[-_HISTORY_ROUNDS:]
    if not recent:
        return ""
    lines = [f"{'用户' if t.role == 'user' else '小栖'}:{t.text}" for t in recent]
    return "\n".join(lines)


def _history_block(cs: CollectState) -> str:
    """collect 侧历史段:turns 原话优先,末条 user 轮排除(网关先 append 再跑图,
    它就是本轮回答,answer 参数已单独注入);turns 空(热层过期)降级注入回合摘要。"""
    ctx = turns_context(cs.turns, exclude_last_user=True)
    if ctx:
        return f"\n\n刚才的对话:\n{ctx}"
    summary = cs.session_context.history_summary
    if summary:
        return f"\n\n之前那次梳理的摘要:{summary[:_HISTORY_SUMMARY_CAP]}"
    return ""


def ask_messages(
    cs: CollectState,
    target_field: FieldKey,
    answer: str,
    *,
    retry: bool = False,
    memories: list[dict[str, object]] | None = None,
) -> list[Message]:
    """问话 prompt:系统段(共情风格) + user 段(进度感知+本轮回答+记忆)。

    retry=True 表示上条回答过短,语气放轻(接住,别催);memories 为语义记忆
    召回条目(注入措辞与 answer/总结同族——「想起」非翻旧账)。
    """
    filled = ", ".join(
        f"{key}={value}"
        for key in ("situation", "thought", "behavior")
        if (value := getattr(cs.formulation, key)) is not None
    ) or _EMPTY_FILLED
    rounds_left = max(0, cs.max_rounds - cs.round_index)
    progress = _PROGRESS_TMPL.format(
        info_need=collect_info_need(target_field),
        field=target_field,
        filled=filled,
        rounds_left=rounds_left,
    )
    user = progress + f"\n用户本轮回答:{answer}{_history_block(cs)}"
    if retry:
        user += "\n(这条回答比较短,轻轻接住再问,别重复催促;同主题换个更好答的问法)"
    if memories:
        mem_desc = "\n".join(f"- {m['text']}" for m in memories)
        user += (
            "\n\n你可能还记得用户之前聊过这些(与当前话题相关时自然衔接一句即可,"
            "用户没提就别主动翻旧账):\n" + mem_desc
        )
    return [Message("system", _SYSTEM), Message("user", user)]


def chat_messages(
    cs: CollectState, answer: str, *, memories: list[dict[str, object]] | None = None
) -> list[Message]:
    """陪聊轮 prompt(off_topic 共情回应;PRD:EMPATH_CHAT_REPLY 固定文案废弃)。

    引导回题(spec「陪聊引导」):回应后带出一句指向挂起提问信息需求的语句;
    无挂起提问(entry 前打岔等)只共情不引导。"""
    user = f"用户这轮的话:{answer}{_history_block(cs)}"
    filled = ", ".join(
        f"{key}={value}"
        for key in ("situation", "thought", "behavior")
        if (value := getattr(cs.formulation, key)) is not None
    )
    if filled:
        user += f"\n此前梳理到的内容:{filled}"
    pending = cs.pending_question
    if pending is not None:
        user += (
            f"\n有个还没聊完的话题:{collect_info_need(pending.target_field)}"
            "（用户还没说到这部分）"
        )
    if memories:
        mem_desc = "\n".join(f"- {m['text']}" for m in memories)
        user += (
            "\n\n你可能还记得用户之前聊过这些(相关时自然衔接,没提就别翻旧账):\n" + mem_desc
        )
    system = (
        "你是心栖阁的共情陪伴者。用户暂时跑题了或没接上梳理的问题,"
        "不评判、不硬拉回正题,先自然地接住这轮的话(短回应,60 字内),"
        "口语化、温暖,不做医疗诊断。"
    )
    if pending is not None:
        system += (
            "接住之后,用一句与回应自然衔接的话,把话题轻轻带回那个还没聊完的部分——"
            "比如顺着共同点问下去;实在没有关联,就点一下它(「前面你提到的…」)。"
            "只带一句,用户接不接由他,别追问别催。"
        )
    return [Message("system", system), Message("user", user)]


def collect_info_need(field: FieldKey) -> str:
    """字段信息需求描述(问序单源转发;测试与 prompt 共用)。"""
    from app.collect import FIELD_INFO_NEED

    return FIELD_INFO_NEED[field]


def first_max_hanzi() -> int:
    """问话首句限短(与 answer 同旋钮;TTFB ≈ 首句字数 × LLM 每字耗时)。"""
    return config.TTS_FIRST_SENTENCE_HANZI
