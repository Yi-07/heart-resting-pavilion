"""9 种 WS 消息(ws-contract §2/§3/§4),判别字段 type。

seq:会话内全局递增,仅 draw/text_delta/audio_chunk/done 携带(§3.2);
first_frame/error/replay 不带不消耗。session_id 随 first_frame/done 带回(§1),
C→S 侧重连时带原 id、首条可省(连接即建会话,由网关按连接补全)。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from .formulation import TEMPLATE_DATA, TemplateData
from .literals import ErrorCode, MoodKey, TemplateId

# ---------- S→C ----------


class FirstFrame(BaseModel):
    """§3.1 新回合起点(清黑板/重置 seq 基线);answer 型不发"""

    type: Literal["first_frame"] = "first_frame"
    session_id: str
    route: Literal["collect", "crisis"]
    template: TemplateId | None = None  # collect 才有;crisis=None
    emotion_label: str | None = None
    mood_select: bool  # crisis 恒 false;collect true
    text: str  # 安抚语(phrases 话术库)


class Draw(BaseModel):
    """§3.2 黑板绘制;data=完整 formulation(非增量),前端按 seq 差动画"""

    type: Literal["draw"] = "draw"
    seq: int
    template: TemplateId
    data: TemplateData

    @model_validator(mode="after")
    def _template_matches_data(self) -> "Draw":
        if not isinstance(self.data, TEMPLATE_DATA[self.template]):
            # ValueError 而非 TypeError:pydantic 只把 ValueError 包成 ValidationError
            raise ValueError(f"template={self.template} 与 data 型不符")  # noqa: TRY004
        return self


class TextDelta(BaseModel):
    """§3.3 流式回复文本;final=true 标记最后一块(可不依赖)"""

    type: Literal["text_delta"] = "text_delta"
    seq: int
    text: str
    final: bool = False


class AudioChunk(BaseModel):
    """§3.4 TTS 音频块(base64)"""

    type: Literal["audio_chunk"] = "audio_chunk"
    seq: int
    format: str
    data: str
    final: bool = False


class Done(BaseModel):
    """§3.5 回合结束;session_id 随 first_frame/done 带回(§1)"""

    type: Literal["done"] = "done"
    session_id: str
    seq: int


class ErrorFrame(BaseModel):
    """§3.7 错误帧;不带 seq 不消耗号"""

    type: Literal["error"] = "error"
    code: ErrorCode
    message: str


class ReplayTurn(BaseModel):
    """§3.6 回放轮次:role 限 user/assistant,text=原话(仅 30min 内热层有)"""

    role: Literal["user", "assistant"]
    text: str


class ReplayFrame(BaseModel):
    """§3.6 重连回放(ADR-005);无 seq 不进回合计数,重连认领后主动推一次。

    bubbles=热层 recent_turns 还在(30min 内),turns 携带原话+summary 可空;
    digest=热层已过,只带 summary(必有);热温均无 → 不发帧。
    """

    type: Literal["replay"] = "replay"
    mode: Literal["bubbles", "digest"]
    turns: list[ReplayTurn] = Field(default_factory=list)
    summary: str | None = None
    session_id: str


S2CMsg = Annotated[
    FirstFrame | Draw | TextDelta | AudioChunk | Done | ErrorFrame | ReplayFrame,
    Field(discriminator="type"),
]
"""S→C 消息联合(7 种),按 type 判别"""


# ---------- C→S ----------


class UserInput(BaseModel):
    """§4.1 用户文本输入;语音经 /asr/transcribe 转写回填后同此发送(ADR-004,输入单源文本)"""

    type: Literal["user_input"] = "user_input"
    session_id: str | None = None
    text: str = Field(min_length=1)  # 空串拒收(与原 mode validator 等价)
    ts: int


class MoodSelect(BaseModel):
    """§4.2 心情选择上报(六档;独立/回合内两种到达,§4.2)"""

    type: Literal["mood_select"] = "mood_select"
    session_id: str | None = None
    mood: MoodKey
    ts: int


CSMsg = Annotated[UserInput | MoodSelect, Field(discriminator="type")]
"""C→S 消息联合(2 种),按 type 判别"""
