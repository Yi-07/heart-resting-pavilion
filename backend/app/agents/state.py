"""CollectState 14 字段 + 图出口事件(backend-plan §3.2/§3.4)。

State 挂 WS 连接对象,图节点只读写、不持有;相位不落 state(下一步动作由
where_next 纯函数从字段算出)。脱敏:state 含用户原文,只活连接内存,
日志只记长度/哈希;落盘唯一出口=回合结束 station:input(步骤 9)。
"""

from dataclasses import dataclass, field
from typing import Literal

from app.schema import Formulation, MoodKey, TemplateId

FieldKey = Literal[
    "situation", "emotion", "thought", "behavior", "intermediate_belief", "core_belief"
]
DegradeReason = Literal["too_short", "off_topic", "negative"]
FinishCause = Literal["sufficient", "max_rounds"] | DegradeReason


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class PendingQuestion:
    text: str
    target_field: FieldKey


@dataclass(frozen=True)
class SessionContext:
    """记忆层快照(memory 步骤 6 接入;MVP 恒空档)

    recent_turns=热层最近轮次原话(ADR-001/005:重连重建 turns + 回放帧数据源);
    只活 30min(隐私线 §9.4),隔天只剩 history_summary。
    """

    history_summary: str | None = None
    mood_recent: list[MoodKey] = field(default_factory=list)
    recent_turns: list[Turn] = field(default_factory=list)


@dataclass
class CollectState:
    """A 身份路由(网关写入,图内只读)· B 采集进度(图内写)· C 上下文(追加)"""

    # A
    session_id: str
    route: Literal["answer", "collect"]
    template: TemplateId | None
    emotion_label: str | None
    confidence: float
    # B
    formulation: Formulation = field(default_factory=Formulation)
    round_index: int = 0
    sufficiency: float = 0.0
    degrade_reason: DegradeReason | None = None
    pending_question: PendingQuestion | None = None
    max_rounds: int = 3
    escalated: bool = False
    # C
    turns: list[Turn] = field(default_factory=list)
    session_context: SessionContext = field(default_factory=SessionContext)
    suspended: bool = False
    """短答支线挂起标记(ADR-003 采集态门控):概念问句切 answer 时不弃采集态,
    只置挂起;下一输入恢复(turns/字段全保留)。只活连接内存,不进记忆快照。"""
    pending_ask_count: int = 0
    """采集内连续追问计数(ADR-003 短答升级):answer 命中且非纯概念时累加,
    满 2 或显式要求回答即允许短答;回采集后清零。"""


# ---- 图出口事件(§3.4;网关按事件收尾,不读 state 内部) ----


@dataclass(frozen=True)
class AskNext:
    confirm: str
    next_question: str
    target_field: FieldKey


@dataclass(frozen=True)
class EmpathChat:
    reply: str


@dataclass(frozen=True)
class Finish:
    cause: FinishCause
    # 本回合总结文本(analysis 产出;网关回合三动作落温层用。None=未经 analysis 的
    # 兜底终结,网关按空摘要降级)。事件携带而非网关读 state(§3.4 原则延伸)
    summary: str | None = None


@dataclass(frozen=True)
class Escalate:
    pass


CollectEvent = AskNext | EmpathChat | Finish | Escalate
