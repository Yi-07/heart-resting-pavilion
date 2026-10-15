"""契约类型单源——Pydantic 对齐 ws-contract.md。

子模块:literals(枚举取值)· formulation(§5.1 数据对象)· ws_messages(10 种消息)
· station(§1 补给站 REST 响应)。
改契约先改 ws-contract,再同步本包与 frontend/src/ws/messages.ts;
StageMapData.from_ 序列化需 model_dump(by_alias=True)。
"""

from .formulation import (
    TEMPLATE_DATA,
    Emotion,
    EmotionWheelData,
    EmotionWheelDatum,
    Formulation,
    SceneFormulation,
    SceneNoteData,
    StageMapData,
    TemplateData,
)
from .literals import ErrorCode, MoodKey, Route, TemplateId
from .station import StationReportResponse, StationReportStatus
from .ws_messages import (
    AudioChunk,
    CSMsg,
    Done,
    Draw,
    ErrorFrame,
    FirstFrame,
    MoodSelect,
    ReplayFrame,
    ReplayTurn,
    S2CMsg,
    TextDelta,
    UserInput,
    WallReply,
)

__all__ = [
    "TEMPLATE_DATA",
    "AudioChunk",
    "CSMsg",
    "Done",
    "Draw",
    "Emotion",
    "EmotionWheelData",
    "EmotionWheelDatum",
    "ErrorCode",
    "ErrorFrame",
    "FirstFrame",
    "Formulation",
    "MoodKey",
    "MoodSelect",
    "ReplayFrame",
    "ReplayTurn",
    "Route",
    "S2CMsg",
    "SceneFormulation",
    "SceneNoteData",
    "StageMapData",
    "StationReportResponse",
    "StationReportStatus",
    "TemplateData",
    "TemplateId",
    "TextDelta",
    "UserInput",
    "WallReply",
]
