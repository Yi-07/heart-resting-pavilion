"""LLM 服务商目录的唯一数据源。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    litellm_key: str
    base_url: str
    needs_key: bool
    api_base_supported: bool = True
    brand_tokens: tuple[str, ...] = ()


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset("deepseek", "DeepSeek", "deepseek", "https://api.deepseek.com", True, brand_tokens=("deepseek",)),
    ProviderPreset("qwen", "Qwen", "dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1", True, brand_tokens=("qwen", "qwq", "qvq")),
    ProviderPreset("kimi", "Kimi", "moonshot", "https://api.moonshot.cn/v1", True, brand_tokens=("kimi", "moonshot")),
    ProviderPreset("glm", "智谱 GLM", "zai", "https://open.bigmodel.cn/api/paas/v4", True, brand_tokens=("glm", "chatglm")),
    ProviderPreset("openai", "OpenAI", "openai", "https://api.openai.com/v1", True, brand_tokens=("gpt", "o1", "o3", "o4", "chatgpt", "codex")),
    ProviderPreset("gemini", "Gemini", "gemini", "https://generativelanguage.googleapis.com", True, False, ("gemini", "gemma")),
    ProviderPreset("claude", "Claude", "anthropic", "https://api.anthropic.com", True, False, ("claude",)),
    ProviderPreset("ollama", "Ollama", "ollama", "http://127.0.0.1:11434", False),
)

_BY_ID = {item.id: item for item in PROVIDER_PRESETS}


def get_preset(provider_id: str) -> ProviderPreset | None:
    return _BY_ID.get(provider_id)


def litellm_model_id(provider_id: str, model_id: str) -> str:
    preset = get_preset(provider_id)
    if preset is None:
        raise KeyError(f"未收录的服务商: {provider_id}")
    return f"{preset.litellm_key}/{model_id}"
