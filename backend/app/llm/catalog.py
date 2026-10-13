"""服务商模型目录与实时模型登记。"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from app.llm.presets import (
    PROVIDER_PRESETS,
    ProviderPreset,
    get_preset,
    litellm_model_id,
)

_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_SPECIAL = {"realtime", "audio", "transcribe", "tts", "asr", "embedding", "embeddings", "rerank", "moderation", "image", "computer", "research"}
_PRETTY = {"gpt": "GPT", "qwen": "Qwen", "kimi": "Kimi", "deepseek": "DeepSeek", "claude": "Claude", "gemini": "Gemini", "glm": "GLM", "openai": "OpenAI", "vl": "VL"}
_SUGGESTED = {
    # 这些是 UI 的常用起步候选；最终仍会经过 LiteLLM 最小调用验证。
    "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
    "qwen": ["qwen3.8-flash", "qwen3.8-max", "qwen3.7-plus", "qwen3.7-flash", "qwen3.5-plus", "qwen3-max", "qwen-plus", "qwen-turbo"],
    "kimi": ["kimi-k2", "kimi-k2-thinking", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    "glm": ["glm-5", "glm-4.5-air", "glm-4-flash", "glm-4-plus", "glm-4-long"],
    "openai": ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-cyber", "gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"],
    "gemini": ["gemini-3.1-pro", "gemini-3-flash", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
    "claude": ["claude-opus-4.7", "claude-sonnet-4.7", "claude-haiku-4.5", "claude-sonnet-4", "claude-3-7-sonnet"],
    "ollama": ["qwen3:8b", "qwen3:14b", "llama3.3:70b", "gemma3:12b", "deepseek-r1:8b", "mistral:7b"],
}
_cache: tuple[ProviderCatalog, ...] | None = None
_live: OrderedDict[tuple[str, str], frozenset[str]] = OrderedDict()


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str
    source: str


@dataclass(frozen=True)
class ProviderCatalog:
    id: str
    name: str
    base_url: str
    needs_key: bool
    models: tuple[CatalogModel, ...]


def _pretty(model_id: str) -> str:
    """保留点号版本号，兼容 Ollama 的 ``name:tag``。"""

    words: list[str] = []
    for token in re.split(r"[-_:/+]+", model_id):
        if not token:
            continue
        low = token.lower()
        words.append(_PRETTY.get(low, token.lower() if any(c.isdigit() for c in token) else token.capitalize()))
    return " ".join(words) or model_id


def _tokens(value: str) -> list[str]:
    return [x for x in re.split(r"[-_./:+]+", value.lower()) if x]


def _brand_match(preset: ProviderPreset, model_id: str) -> bool:
    tokens = _tokens(model_id)
    return not preset.brand_tokens or bool(tokens and tokens[0] in preset.brand_tokens)


def _catalog_entries(preset: ProviderPreset) -> list[str]:
    fallback = _SUGGESTED
    try:
        from app.llm.provider import load_litellm
        model_cost: dict[str, Any] = getattr(load_litellm(), "model_cost", {})
    except Exception:  # noqa: BLE001 — LiteLLM 未安装或目录损坏时回退内置候选
        return fallback.get(preset.id, [])
    prefix = f"{preset.litellm_key}/"
    result: list[str] = []
    for key, entry in model_cost.items():
        if not isinstance(entry, dict) or entry.get("litellm_provider") != preset.litellm_key or entry.get("mode") != "chat":
            continue
        full = key if key.startswith(prefix) else prefix + key
        model_id = full[len(prefix):]
        tokens = set(_tokens(model_id))
        if model_id.startswith("ft:") or tokens & _SPECIAL or not _brand_match(preset, model_id):
            continue
        result.append(model_id)
    return list(dict.fromkeys([*fallback.get(preset.id, []), *result]))


def get_catalog(*, refresh: bool = False) -> tuple[ProviderCatalog, ...]:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    values: list[ProviderCatalog] = []
    for preset in PROVIDER_PRESETS:
        ids = list(dict.fromkeys(_catalog_entries(preset)))
        values.append(ProviderCatalog(preset.id, preset.label, preset.base_url, preset.needs_key, tuple(CatalogModel(i, _pretty(i), "catalog") for i in ids)))
    _cache = tuple(values)
    return _cache


def reset_catalog_cache() -> None:
    global _cache
    _cache = None


def model_ids(provider_id: str, *, refresh: bool = False) -> frozenset[str]:
    return frozenset(m.id for p in get_catalog(refresh=refresh) if p.id == provider_id for m in p.models)


def _key_fp(api_key: str | None) -> str:
    return sha256((api_key or "nokey").encode()).hexdigest()[:16]


def remember_live(provider_id: str, api_key: str | None, ids: list[str]) -> None:
    valid = frozenset(x for x in ids if _MODEL_ID_RE.fullmatch(x) and not x.startswith("ft:"))
    if valid:
        key = (provider_id, _key_fp(api_key))
        _live[key] = valid
        _live.move_to_end(key)
        while len(_live) > 64:
            _live.popitem(last=False)


def live_ids(provider_id: str, api_key: str | None) -> frozenset[str]:
    return _live.get((provider_id, _key_fp(api_key)), frozenset())


def allowed_model_ids(provider_id: str, api_key: str | None) -> frozenset[str]:
    return model_ids(provider_id) | live_ids(provider_id, api_key)


def is_allowed_model(provider_id: str, model_id: str, api_key: str | None) -> bool:
    # Ollama 的 /api/tags 在没有 litellm 本地目录时仍可登记；其它服务商必须走目录或实时发现。
    return model_id in allowed_model_ids(provider_id, api_key)


def is_valid_model_id(model_id: str) -> bool:
    """允许用户输入尚未出现在目录中的模型 ID；真实可用性由连接验证确认。"""

    return bool(_MODEL_ID_RE.fullmatch(model_id))


def full_model_id(provider_id: str, model_id: str) -> str:
    return litellm_model_id(provider_id, model_id)


def catalog_payload(verified_pairs: frozenset[tuple[str, str]] = frozenset()) -> list[dict[str, Any]]:
    return [{"id": p.id, "name": p.name, "base_url": p.base_url, "needs_key": p.needs_key, "models": [{"id": m.id, "name": m.name, "source": "verified" if (p.id, m.id) in verified_pairs else m.source} for m in p.models]} for p in get_catalog()]


def _extract_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data") or payload.get("models") or []
    return [str(row.get("id") or row.get("name")) for row in rows if isinstance(row, dict) and (row.get("id") or row.get("name"))]


async def fetch_live_models(provider_id: str, api_key: str | None) -> list[str] | None:
    """实时探测失败返回 None，前端仍可使用离线目录。"""
    preset = get_preset(provider_id)
    if preset is None:
        return None
    try:
        import aiohttp
        params: dict[str, str] | None = None
        if provider_id == "ollama":
            url = preset.base_url.rstrip("/") + "/api/tags"
            headers: dict[str, str] = {}
        elif provider_id == "gemini":
            url = preset.base_url.rstrip("/") + "/v1beta/models"
            headers = {}
            params = {"key": api_key} if api_key else None
        elif provider_id == "claude":
            url = preset.base_url.rstrip("/") + "/v1/models"
            headers = {
                "x-api-key": api_key or "",
                "anthropic-version": "2023-06-01",
            }
        elif provider_id == "qwen":
            url = "https://dashscope.aliyuncs.com/api/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        else:
            url = preset.base_url.rstrip("/") + "/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with aiohttp.ClientSession() as session, session.get(
            url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=8)
        ) as response:
                if response.status >= 400:
                    return None
                return _extract_ids(await response.json())
    except Exception:  # noqa: BLE001 — 各家模型列表接口失败统一回退离线目录
        return None


def merge_live(provider_id: str, live: list[str]) -> list[CatalogModel]:
    seen = set(live)
    result = [CatalogModel(i, _pretty(i), "live") for i in sorted(seen)]
    result.extend(m for p in get_catalog() if p.id == provider_id for m in p.models if m.id not in seen)
    return result
