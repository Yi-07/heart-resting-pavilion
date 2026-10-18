"""三降级检测(spec §4 L4;只检测不定策略——映射归 where_next)。

- too_short:答案过短(<4 字),信息量不足 → 重问同字段(第二问法)
- negative:自指负面词命中(浓烈自责/绝望表述)→ 粗稿+已采字段收尾
- off_topic:不在本表——由 agents 提取阶段判(提取不出值=漂移)→ 转共情陪聊
negative 词表两档(评测集先行,T4):自指档命中即降级收尾;他指档须与第一人称
共现才收尾——「这份工作干着没意义」是日常抱怨,采集继续;「我觉得自己没用」
才是收尾信号。判定只吃本条回答(spec 约定,历史不参与)。
"""

from app.agents.state import DegradeReason

TOO_SHORT_LEN = 4

NEGATIVE_SELF_TERMS: tuple[str, ...] = (
    "废物", "失败者", "恨自己", "厌恶自己", "我没用", "我真没用",
    "全毁了", "撑不住了", "撑不下去", "烂透了自己",
)
"""自指档:词形本身即第一人称负面(self-reference 内嵌),命中即降级收尾。"""

NEGATIVE_OTHER_TERMS: tuple[str, ...] = (
    "没意义", "毫无意义", "没用", "烂透了", "糟透了",
)
"""他指档:可指事物可指自己(「没意义」的主语可以是工作也可以是人生),
须与第一人称线索共现才收尾,防日常抱怨误收尾。"""

SELF_HINTS: tuple[str, ...] = ("我", "自己", "俺", "本人", "活得")
"""第一人称/生存状态线索(negative 共现判定);「活得」覆盖「活得没意义」类
省略主语的生存陈述——它描述的是用户自身的生存状态,归自指。"""


def detect(answer: str) -> DegradeReason | None:
    """返回降级原因或 None;off_topic 归提取阶段(agents/extract)。"""
    if len(answer.strip()) < TOO_SHORT_LEN:
        return "too_short"
    if any(term in answer for term in NEGATIVE_SELF_TERMS):
        return "negative"
    if any(term in answer for term in NEGATIVE_OTHER_TERMS) and any(
        hint in answer for hint in SELF_HINTS
    ):
        return "negative"
    return None
