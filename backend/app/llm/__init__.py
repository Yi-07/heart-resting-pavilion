"""llm:LLM 统一传输(litellm-core 原生路由;职责表见 backend-plan §2)。"""

from .provider import (
    LLMError,
    Message,
    OpenAICompatProvider,
    ProviderSpec,
    get_provider,
    provider_for,
    verify_provider,
)

__all__ = [
    "LLMError",
    "Message",
    "OpenAICompatProvider",
    "ProviderSpec",
    "get_provider",
    "provider_for",
    "verify_provider",
]
