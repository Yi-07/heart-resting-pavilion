"""LLM 双源抽象(backend-plan §2 llm 行/§7):OpenAI 兼容统一入口。

DeepSeek(base_url=https://api.deepseek.com)与 Ollama(本地兜底)同接口,
由 config.LLM_PROVIDER 切换。出错抛 LLMError,由调用方捕获后降级到话术库;
不做自动重试(成本热点,失败显式降级)。流式走 create(stream=True) 裸 chunk
(对 OpenAI 兼容端点最稳);chat_json 自带围栏剥离与 schema 校验。
"""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeVar, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from app import config

MessageRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: MessageRole
    content: str


class LLMError(Exception):
    """LLM 调用/解析失败;调用方降级到话术库"""


T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def extract_json(text: str) -> str:
    """剥掉 ```json 围栏;无围栏返回原文。"""
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _oai_messages(messages: list[Message]) -> list[ChatCompletionMessageParam]:
    """Message → openai 参数;cast 收窄字面量联合(openai TypedDict 联合的已知钉子)。"""
    return [
        cast(ChatCompletionMessageParam, {"role": m.role, "content": m.content})
        for m in messages
    ]


class OpenAICompatProvider:
    """AsyncOpenAI 参数化实现;client 可注入(测试)。"""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self.model = model

    async def chat(self, messages: list[Message]) -> str:
        try:
            resp = await self._client.chat.completions.create(
                model=self.model, messages=_oai_messages(messages)
            )
        except Exception as exc:  # 网络/鉴权/限流统一包装
            raise LLMError(f"chat 调用失败: {exc}") from exc
        return resp.choices[0].message.content or ""

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        try:
            raw = await self._client.chat.completions.create(
                model=self.model, messages=_oai_messages(messages), stream=True
            )
            async for chunk in raw:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            raise LLMError(f"stream 调用失败: {exc}") from exc

    async def chat_json(self, messages: list[Message], schema: type[T]) -> T:
        text = await self.chat(messages)
        try:
            data = json.loads(extract_json(text))
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM 返回非 JSON: {text[:80]}") from exc
        try:
            return schema.model_validate(data)
        except ValidationError as exc:
            raise LLMError(f"LLM JSON 不合 schema: {exc.errors()[0]}") from exc


def get_provider() -> OpenAICompatProvider:
    """按 config.LLM_PROVIDER 构造单例式 provider(轻对象,按需新建)。"""
    if config.LLM_PROVIDER == "ollama":
        return OpenAICompatProvider(
            AsyncOpenAI(base_url=config.OLLAMA_URL, api_key="ollama"),
            config.OLLAMA_MODEL,
        )
    return OpenAICompatProvider(
        AsyncOpenAI(base_url=config.DEEPSEEK_BASE_URL, api_key=config.DEEPSEEK_API_KEY),
        config.DEEPSEEK_MODEL,
    )
