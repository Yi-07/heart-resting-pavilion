"""admin 接缝钉测试:clear_memory 三清+失败 503 / trends 形状 / config AES-GCM
落库(明文绝不落库)+ 进程内应用 / 缺加密密钥拒存 api_key。
记忆走 conftest 假记忆;config 库与 reports 库用临时文件。"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.admin import get_config_store, reset_config_store
from app.admin.config_store import ConfigStore
from app.main import app
from app.station.reports import get_reports

client = TestClient(app)

_KEY_HEX = "ab" * 32  # 32 字节合法 AES-256 hex


@pytest.fixture()
def cfg_store(tmp_path: pytest.TempPathFactory) -> ConfigStore:
    reset_config_store(ConfigStore(str(tmp_path / "config.db")))
    yield get_config_store()
    reset_config_store()


def _set_key(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setattr("app.config.CONFIG_AES_KEY", key)


# ---- clear_memory ----


def test_clear_memory_clears_all_three(fake_memory: Any, tmp_reports: Any):
    tmp_reports.upsert("s", "ready", "# 稿")
    res = client.post("/admin/clear_memory")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "redis_keys": 2, "mood_rows": 3, "reports": 1}
    assert tmp_reports.get("s") is None
    assert ("clear_all", {}) in fake_memory.calls


def test_clear_memory_failure_503(
    fake_memory: Any, tmp_reports: Any, monkeypatch: pytest.MonkeyPatch
):
    async def _boom() -> dict[str, int]:
        raise RuntimeError("redis down")

    monkeypatch.setattr(fake_memory, "clear_all", _boom)
    res = client.post("/admin/clear_memory")
    assert res.status_code == 503


# ---- trends ----


def test_trends_shape(fake_memory: Any):
    fake_memory.moods = [
        {"date": "2026-09-05", "source": "mood_select", "mood_label": "低落", "intensity": None}
    ]
    res = client.get("/admin/trends")
    assert res.status_code == 200
    assert res.json() == {"moods": fake_memory.moods}
    res = client.get("/admin/trends", params={"days": 30})
    assert fake_memory.calls[-1] == ("recent_moods", {"days": 30})


# ---- config ----


def test_config_save_encrypt_and_apply(
    cfg_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
):
    _set_key(monkeypatch, _KEY_HEX)
    monkeypatch.setattr(config, "LLM_PROVIDER", config.LLM_PROVIDER)  # 登记恢复
    monkeypatch.setattr(config, "DEEPSEEK_MODEL", config.DEEPSEEK_MODEL)

    res = client.post(
        "/admin/config",
        json={"provider": "deepseek", "model": "m1", "api_key": "sk-plain-text"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "provider": "deepseek", "model": "m1"}  # 无密钥回显

    # 明文绝不落库:原始行里只有密文
    with sqlite3.connect(cfg_store._db_path) as conn:
        row = conn.execute(
            "SELECT provider, model, api_key_enc FROM llm_config WHERE id = 1"
        ).fetchone()
    assert row is not None
    assert row[0] == "deepseek" and row[1] == "m1"
    assert row[2] is not None and "sk-plain-text" not in row[2]

    loaded = cfg_store.load()
    assert loaded is not None
    assert loaded.api_key == "sk-plain-text"  # 解密回读 roundtrip
    assert config.LLM_PROVIDER == "deepseek" and config.DEEPSEEK_MODEL == "m1"  # 进程内应用


def test_config_rejects_api_key_without_aes_key(
    cfg_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
):
    _set_key(monkeypatch, "")
    monkeypatch.setattr(config, "LLM_PROVIDER", config.LLM_PROVIDER)
    res = client.post(
        "/admin/config", json={"provider": "ollama", "model": "q", "api_key": "sk-x"}
    )
    assert res.status_code == 400
    assert cfg_store.load() is None  # 整体未落


def test_config_without_key_field_ok(
    cfg_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
):
    _set_key(monkeypatch, "")
    monkeypatch.setattr(config, "LLM_PROVIDER", config.LLM_PROVIDER)
    res = client.post("/admin/config", json={"provider": "ollama", "model": "qwen3:8b"})
    assert res.status_code == 200
    loaded = cfg_store.load()
    assert loaded is not None and loaded.model == "qwen3:8b"
    assert config.LLM_PROVIDER == "ollama"


def test_config_invalid_provider_422(cfg_store: ConfigStore):
    res = client.post("/admin/config", json={"provider": "openai"})
    assert res.status_code == 422


def test_config_get_shape_no_key(monkeypatch: pytest.MonkeyPatch):
    """GET /admin/config:形状正确,providers 两源,api_key 只给布尔绝不回显。"""

    monkeypatch.setattr(config, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "DEEPSEEK_MODEL", "m1")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-plain-text")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "qwen3:8b")

    res = client.get("/admin/config")
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "deepseek"
    assert body["api_key_set"] is True
    ids = {p["id"]: p for p in body["providers"]}
    assert ids["deepseek"]["model"] == "m1"
    assert ids["ollama"]["model"] == "qwen3:8b"
    # 无密钥回显:任何字段都不含明文
    assert "sk-plain-text" not in res.text


def test_config_store_singleton_reset_guard():
    """reset_config_store 后 get 重建(测试隔离口可用)。"""

    reset_config_store()
    first = get_config_store()
    assert first is get_config_store()
    assert get_reports() is not first


def test_llm_profile_verify_does_not_activate(
    cfg_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
):
    """连接测试只更新 verified，不切换项目当前模型。"""

    profile = cfg_store.create_profile("deepseek", "deepseek-v4-flash", None)

    async def _verify(*_: Any) -> None:
        return None

    monkeypatch.setattr("app.admin.routes._verify_candidate", _verify)
    response = client.post(f"/admin/llm/profiles/{profile.id}/verify")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "active": False, "verified": True}
    saved = cfg_store.get_profile(profile.id)
    assert saved is not None and saved.verified is True
    assert cfg_store.active_id() is None
