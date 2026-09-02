"""llm:LLM 双源(职责表见 backend-plan §2)。"""

from .provider import LLMError, Message, OpenAICompatProvider, get_provider

__all__ = ["LLMError", "Message", "OpenAICompatProvider", "get_provider"]
