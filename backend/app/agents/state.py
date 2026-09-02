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
    """记忆层快照(memory 步骤 6 接入;MVP 恒空档)"""

    history_summary: str | None = None
    mood_recent: list[MoodKey] = field(default_factory=list)


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


@dataclass(frozen=True)
class Escalate:
    pass


CollectEvent = AskNext | EmpathChat | Finish | Escalate
