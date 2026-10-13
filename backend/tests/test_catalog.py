"""模型目录实时发现的 URL 选择测试。"""

from __future__ import annotations

import sys
from typing import Any

from app.llm import catalog
from app.llm.presets import ProviderPreset


class _Response:
    status = 200

    async def __aenter__(self) -> _Response:  # noqa: PYI034 - 兼容 Python 3.10
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def json(self) -> dict[str, list[dict[str, str]]]:
        return {"data": [{"id": "qwen-private"}]}


class _Session:
    def __init__(self, captured: dict[str, Any]) -> None:
        self.captured = captured

    async def __aenter__(self) -> _Session:  # noqa: PYI034 - 兼容 Python 3.10
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.captured.update(url=url, **kwargs)
        return _Response()


async def test_qwen_live_models_uses_preset_base_url(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    fake_aiohttp = type(
        "_Aiohttp",
        (),
        {
            "ClientSession": lambda: _Session(captured),
            "ClientTimeout": lambda **kwargs: kwargs,
        },
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    monkeypatch.setattr(
        catalog,
        "get_preset",
        lambda _: ProviderPreset(
            "qwen",
            "Qwen",
            "dashscope",
            "https://proxy.example/compatible-mode/v1",
            True,
        ),
    )

    result = await catalog.fetch_live_models("qwen", "sk-test")

    assert result == ["qwen-private"]
    assert captured["url"] == "https://proxy.example/compatible-mode/v1/models"
    assert captured["headers"] == {"Authorization": "Bearer sk-test"}
