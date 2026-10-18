"""轮次填格提取(L5;每轮一次轻 LLM,失败降级填原文截断)。

跨字段提取:一次调用返回所有可填字段的值(所问字段优先)——答案里与表格
相关的信息不再因"不是所问字段"而被丢弃。返回空 dict → 由 where_next 走
共情陪聊轮。值截断到 MAX_FIELD_LEN(黑板槽位容量);中间信念/核心信念不进
提取(信念留白,spec 约束,由调用方的可填字段清单保证)。
blackboard-v1:同一调用顺带为黑板场景选图标(assets 键,board 模块供给
system 段与白名单校验;不加 LLM 调用次数)。
risk_signal:与字段提取同一次调用附带输出的自伤/自杀暗示判定(零额外调用)——
词典外委婉表述(「有时候真想一走了之」)不触发闸门也不触发软预筛,
复核触达不到;此信号只触发 graph._soft_review 复核,升级验收权仍在复核节点
(唯一升级验收点架构不变)。
"""

from pydantic import BaseModel, Field

from app import logger as app_logger
from app.agents.state import FieldKey
from app.llm import LLMError, Message, get_provider

MAX_FIELD_LEN = 24
"""提炼值截断上限:黑板槽位下文本区约 13 字/行(2 行封顶的安全线),超出折行堆积;
黑板是速写不是全文,短提炼值同时贴「图标为主、文字弱化」的展示定位。"""

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="extract")


class _ExtractOut(BaseModel):
    fields: dict[str, str] = Field(default_factory=dict)
    assets: dict[str, str] = Field(default_factory=dict)
    off_topic: bool = False
    risk_signal: bool = False


_SYSTEM = (
    "你从用户回答中为认知概念化表格提取字段值,只输出 JSON:"
    '{"fields":{"字段名":"提炼后的短句(≤24字)"},"risk_signal":false}。'
    "规则:回答中出现了某个可填字段的信息就填它,即使不是所问的字段;"
    "所问字段优先;相关但信息不足的字段不要填;"
    "整段与表格完全无关时输出 {\"fields\":{},\"off_topic\":true}。"
    "risk_signal:回答含自伤/自杀的意图、计划或暗示(含委婉表述如「一走了之」「解脱」),"
    "true;单纯情绪痛苦为 false——拿不准时 false。"
)


async def extract_fields(
    question: str,
    target_field: FieldKey,
    answer: str,
    open_fields: list[FieldKey],
    *,
    asset_hint: str | None = None,
    raw_fallback: bool = True,
) -> tuple[dict[FieldKey, str], dict[str, str], bool]:
    """跨字段提取:返回 ({字段: 提炼值}, {字段: 图标id原始选材}, risk_signal)
    (空 dict=无可填,走陪聊轮)。

    选材为原始输出,白名单校验/熔断由调用方(board.Selector)处理——本函数
    不持状态。asset_hint=None 时模型仍可能吐 assets 键,静默丢弃,行为等价旧版。
    risk_signal 为同一次调用附带输出的自伤/自杀暗示判定(词典外委婉表述的
    复核入口),调用方只许拿它触发软信号复核,不直接升级(升级验收权在
    graph._soft_review)。
    LLMError 降级:所问字段填原文截断(与单字段时代同语义);entry 即提取传
    raw_fallback=False——失败回退旧行为(只留研判标签),不阻断回合(PRD)。
    LLMError 时 risk_signal 记 False:复核通道缺失下不制造伪信号;本函数日志
    只记字段名与长度,不落提炼值原文(脱敏红线 §7)。
    """
    system = _SYSTEM + (f"\n{asset_hint}" if asset_hint else "")
    user = (
        f"所问字段:{target_field}\n问题:{question}\n"
        f"可填字段:{','.join(open_fields)}\n用户回答:{answer}"
    )
    try:
        out = await get_provider().chat_json(
            [Message("system", system), Message("user", user)], _ExtractOut
        )
    except LLMError:
        if not raw_fallback:
            return {}, {}, False
        fallback = answer.strip()[:MAX_FIELD_LEN]
        if fallback and target_field in open_fields:
            logger.info("extract_filled", fields=target_field, source="llm_error_fallback")
            return {target_field: fallback}, {}, False
        return {}, {}, False
    values: dict[FieldKey, str] = {
        key: val.strip()[:MAX_FIELD_LEN]
        for key, val in out.fields.items()
        if key in open_fields and val and val.strip()
    }
    if values:
        logger.info("extract_filled",
                    fields=",".join(values),
                    lengths=",".join(str(len(v)) for v in values.values()))
    else:
        logger.info("extract_empty", off_topic=out.off_topic)
    if out.risk_signal:
        # 留痕不落原文:哪个回答触发,供 risk 复核去重与审计对账
        logger.info("extract_risk_signal")
    return values, dict(out.assets), out.risk_signal
