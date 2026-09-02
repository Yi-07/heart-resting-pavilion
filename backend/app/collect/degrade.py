"""三降级检测(spec §4 L4;只检测不定策略——映射归 where_next)。

- too_short:答案过短(<4 字),信息量不足 → 重问同字段(第二问法)
- negative:负面词命中(浓烈自责/绝望表述)→ 粗稿+已采字段收尾
- off_topic:不在本表——由 agents 提取阶段判(提取不出值=漂移)→ 转共情陪聊
词表 MVP 占位,运行时补。
"""

from app.agents.state import DegradeReason

TOO_SHORT_LEN = 4

NEGATIVE_TERMS: tuple[str, ...] = (
    "没意义", "毫无意义", "没用", "废物", "失败者", "烂透了",
    "糟透了", "恨自己", "厌恶自己", "全毁了", "撑不住了",
)


def detect(answer: str) -> DegradeReason | None:
    """返回降级原因或 None;off_topic 归提取阶段(agents/extract)。"""
    if len(answer.strip()) < TOO_SHORT_LEN:
        return "too_short"
    if any(term in answer for term in NEGATIVE_TERMS):
        return "negative"
    return None
