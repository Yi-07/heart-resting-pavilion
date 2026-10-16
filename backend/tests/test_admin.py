"""admin 接缝钉测试:clear_memory 三清+失败 503 / trends 形状 / config AES-GCM
落库(明文绝不落库)+ 进程内应用 / 缺加密密钥拒存 api_key。
记忆走 conftest 假记忆;config 库与 reports 库用临时文件。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
    """治理清除:Redis+冷层+方案书;轮次高水位不重置(D8)。"""
    now = datetime.now()  # noqa: DTZ005 — 与 app 侧同基准
    tmp_reports.begin_generation(
        "s", "1", "t", collected_at=now, expires_at=now + timedelta(days=7), title="t"
    )
    res = client.post("/admin/clear_memory")
    assert res.status_code == 200
    assert res.json() == {
        "ok": True,
        "redis_keys": 2,
        "mood_rows": 3,
        "reports": 1,
        "semantic": 0,
    }
    assert tmp_reports.list_by_session("s") == []
    assert ("clear_all", {}) in fake_memory.calls
    assert ("clear_all", {}) in fake_memory.semantic.calls  # 语义层一并清除
    # D8:高水位不复用——治理清除后旧聊天链接不会指向同号新报告
    assert tmp_reports.next_round_id("s") == "1"
    tmp_reports.clear_all()
    assert tmp_reports.next_round_id("s") == "2"  # 高水位不复用


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
    assert fake_memory.calls[-1] == ("recent_moods", {"days": 30, "source": "mood_select"})


def test_trends_only_mood_select_source(fake_memory: Any):
    """R7 裁定:治理趋势只回用户自我报告;研判不入趋势(展示位在方案书)。"""

    fake_memory.moods = [
        {"date": "2026-10-15", "source": "mood_select", "mood_label": "平静", "intensity": None},
        {"date": "2026-10-15", "source": "研判", "mood_label": "焦虑", "intensity": 0.8},
    ]
    res = client.get("/admin/trends")
    labels = [m["mood_label"] for m in res.json()["moods"]]
    assert labels == ["平静"]


# ---- config store(旧 /admin/config 双源口已随 T4 清理;仅存 store 单例守卫) ----


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


def test_llm_profile_accepts_manual_model_id(
    cfg_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
):
    """不在内置目录中的合法模型 ID 也可以先保存,等待后续真实验证。"""

    _set_key(monkeypatch, _KEY_HEX)
    response = client.post(
        "/admin/llm/profiles",
        json={"provider_id": "openai", "model_id": "my-private-model:v2", "api_key": "sk-manual"},
    )

    assert response.status_code == 200
    saved = cfg_store.get_profile(response.json()["id"])
    assert saved is not None and saved.model_id == "my-private-model:v2"


def test_llm_profile_requires_key_for_key_provider(cfg_store: ConfigStore):
    response = client.post(
        "/admin/llm/profiles",
        json={"provider_id": "openai", "model_id": "gpt-private"},
    )

    assert response.status_code == 422
    assert "需要 API Key" in response.json()["detail"]
    assert not any(profile.provider_id == "openai" for profile in cfg_store.list_profiles())


def test_live_models_reuses_saved_profile_key(
    cfg_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
):
    """编辑模型时不重新填写 Key,实时刷新仍使用已保存的密钥。"""

    _set_key(monkeypatch, _KEY_HEX)
    profile = cfg_store.create_profile("openai", "gpt-private", "sk-saved")
    captured: dict[str, Any] = {}

    async def _fetch(provider_id: str, api_key: str | None) -> list[str]:
        captured.update(provider_id=provider_id, api_key=api_key)
        return []

    monkeypatch.setattr("app.admin.routes.llm_catalog.fetch_live_models", _fetch)
    response = client.post(
        "/admin/llm/models",
        json={"provider_id": "openai", "profile_id": profile.id},
    )

    assert response.status_code == 200
    assert captured == {"provider_id": "openai", "api_key": "sk-saved"}


def test_live_models_does_not_reuse_key_after_explicit_clear(
    cfg_store: ConfigStore, monkeypatch: pytest.MonkeyPatch
):
    _set_key(monkeypatch, _KEY_HEX)
    cfg_store.create_profile("openai", "gpt-private", "sk-saved")
    captured: dict[str, Any] = {}

    async def _fetch(provider_id: str, api_key: str | None) -> list[str]:
        captured.update(provider_id=provider_id, api_key=api_key)
        return []

    monkeypatch.setattr("app.admin.routes.llm_catalog.fetch_live_models", _fetch)
    response = client.post(
        "/admin/llm/models",
        json={"provider_id": "openai"},
    )

    assert response.status_code == 200
    assert captured == {"provider_id": "openai", "api_key": None}
    assert response.json()["api_key_source"] == "none"
