"""LLMProvider 接缝钉测试(backend-plan §11):chat_json 校验失败路径、LLMError。"""

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from app.llm import LLMError, Message
from app.llm.provider import OpenAICompatProvider, extract_json


class _Out(BaseModel):
    route: str
    confidence: float


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    async def create(self, **kwargs: object) -> _FakeResponse:
        return _FakeResponse([_FakeChoice(_FakeMessage(self._content))])


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions(content)  # type: ignore[attr-defined]


def _provider(content: str) -> OpenAICompatProvider:
    return OpenAICompatProvider(_FakeClient(content), model="fake")  # type: ignore[arg-type]


async def test_chat_json_plain():
    out = await _provider('{"route": "answer", "confidence": 0.9}').chat_json(
        [Message("user", "x")], _Out
    )
    assert out.route == "answer"
    assert out.confidence == 0.9


async def test_chat_json_fenced():
    out = await _provider('```json\n{"route": "collect", "confidence": 0.8}\n```').chat_json(
        [Message("user", "x")], _Out
    )
    assert out.route == "collect"


async def test_chat_json_invalid_json_raises_llm_error():
    with pytest.raises(LLMError, match="非 JSON"):
        await _provider("我觉得应该走 collect").chat_json([Message("user", "x")], _Out)


async def test_chat_json_schema_violation_raises_llm_error():
    with pytest.raises(LLMError, match="schema"):
        await _provider('{"route": 123}').chat_json([Message("user", "x")], _Out)


def test_extract_json_variants():
    assert extract_json('```json\n{"a":1}\n```') == '{"a":1}'
    assert extract_json('  {"a":1} ') == '{"a":1}'
