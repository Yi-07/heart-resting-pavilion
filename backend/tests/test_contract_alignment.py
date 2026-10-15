"""契约对齐接缝:抽 ws-contract §5.1 字段名与 schema 比对,防两端漂移(backend-plan §11)。

同时把契约 §3/§4 的 fenced JSON 示例全部喂给消息联合解析——8 种消息示例
本身即回归样本,契约改动即刻在此炸。
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from app.schema import (
    CSMsg,
    Emotion,
    EmotionWheelData,
    EmotionWheelDatum,
    Formulation,
    S2CMsg,
    StageMapData,
)

WS_CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "ws-contract.md"

S2C_TYPES = frozenset({"first_frame", "draw", "text_delta", "audio_chunk", "done", "replay", "wall_reply", "error"})
CS_TYPES = frozenset({"user_input", "mood_select"})


def _field_names(model: type[BaseModel]) -> set[str]:
    """字段名(序列化别名优先,如 StageMapData.from_ → from)"""
    return {f.alias or name for name, f in model.model_fields.items()}


def _section_51_json() -> dict:
    text = WS_CONTRACT.read_text(encoding="utf-8")
    m = re.search(r"### 5\.1.*?```json\n(.*?)```", text, re.DOTALL)
    assert m, "ws-contract §5.1 formulation JSON 块缺失"
    return json.loads(m.group(1))


def _template_bullets() -> dict[str, str]:
    text = WS_CONTRACT.read_text(encoding="utf-8")
    m = re.search(r"\*\*测试模板 data\*\*：(.*?)### 5\.2", text, re.DOTALL)
    assert m, "ws-contract §5.1 测试模板 bullet 缺失"
    return dict(re.findall(r"`(\w+)`：`([^`]+)`", m.group(1)))


def _body_keys(body: str) -> set[str]:
    return set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", body))


def _fenced_json_blocks(text: str) -> Iterator[dict]:
    for m in re.finditer(r"```json\n(.*?)```", text, re.DOTALL):
        block = json.loads(m.group(1))
        if isinstance(block, dict) and "type" in block:
            yield block


def test_formulation_fields_match_contract():
    block = _section_51_json()
    assert set(block) == _field_names(Formulation)
    assert set(block["emotion"]) == _field_names(Emotion)


def test_template_data_keys_match_contract():
    bullets = _template_bullets()
    assert set(bullets) == {"emotion_wheel", "stage_map"}
    assert _body_keys(bullets["emotion_wheel"]) == _field_names(EmotionWheelData) | _field_names(
        EmotionWheelDatum
    )
    assert _body_keys(bullets["stage_map"]) == _field_names(StageMapData)


def test_contract_examples_parse():
    text = WS_CONTRACT.read_text(encoding="utf-8")
    blocks = list(_fenced_json_blocks(text))
    assert {b["type"] for b in blocks} == S2C_TYPES | CS_TYPES  # 9 种消息示例全覆盖(ADR-005 +replay)

    s2c = TypeAdapter(S2CMsg)
    cs = TypeAdapter(CSMsg)
    for block in blocks:
        adapter = s2c if block["type"] in S2C_TYPES else cs
        adapter.validate_python(block)  # 契约示例必须可解析


def test_stage_map_serializes_from_alias():
    data = StageMapData.model_validate({"nodes": ["现在"], "current": 0, "from": "来源"})
    dumped = data.model_dump(by_alias=True)
    assert dumped["from"] == "来源"
    assert "from_" not in dumped
