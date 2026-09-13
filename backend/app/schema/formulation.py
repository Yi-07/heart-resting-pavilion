"""数据对象(ws-contract §5.1):formulation 三型。

beck_formulation 为 MVP 采集默认;emotion_wheel / stage_map 为测试模板。
未采字段 = null(前端不画该格;belief 允许留白,后端不硬填)。
"""

from pydantic import BaseModel, ConfigDict, Field

from .literals import TemplateId


class Emotion(BaseModel):
    """formulation.emotion 子对象;label/intensity 均可 null(研判无强度可缺省)"""

    label: str | None = None
    intensity: float | None = Field(default=None, ge=0.0, le=1.0)


class Formulation(BaseModel):
    """beck_formulation 黑板数据(六字段);初始全 null,采集逐步填格"""

    situation: str | None = None
    emotion: Emotion = Field(default_factory=Emotion)
    thought: str | None = None
    behavior: str | None = None
    intermediate_belief: str | None = None
    core_belief: str | None = None

    def is_filled(self, key: str) -> bool:
        """字段已填判定单源(D10):emotion 看 label,其余看 None——三处重复判定收拢此处。"""
        if key == "emotion":
            return self.emotion.label is not None
        return getattr(self, key) is not None


class EmotionWheelDatum(BaseModel):
    label: str
    intensity: float = Field(ge=0.0, le=1.0)
    color: str


class EmotionWheelData(BaseModel):
    """emotion_wheel 测试模板 data"""

    emotions: list[EmotionWheelDatum]


class StageMapData(BaseModel):
    """stage_map 测试模板 data;from 为 Python 关键字,序列化需 by_alias=True"""

    model_config = ConfigDict(populate_by_name=True)

    nodes: list[str]
    current: int
    from_: str = Field(alias="from")


TemplateData = Formulation | EmotionWheelData | StageMapData
"""draw.data 三型联合,随 template 字段取其一"""

TEMPLATE_DATA: dict[TemplateId, type[BaseModel]] = {
    "beck_formulation": Formulation,
    "emotion_wheel": EmotionWheelData,
    "stage_map": StageMapData,
}
"""template id → data 型映射;Draw 校验 template 与 data 一致用"""
