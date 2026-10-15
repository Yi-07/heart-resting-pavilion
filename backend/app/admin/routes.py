"""管理通道 REST(端点单源=ws-contract §1):记忆治理 + LLM 模型配置,不进 WS。

- POST /admin/clear_memory — 一键清除用户记忆(Redis 全键+冷层心情+方案书+语义库)。
  治理操作不降级:失败如实 503,不误报「已清除」(与记忆层「异常吞掉、保证回合进行」的默认行为相反,有意例外)
- GET /admin/memories — 语义记忆列表;DELETE /admin/memories/{id} — 单条删除(同治理纪律)
- GET /admin/trends?days=7 — 情绪趋势(冷层每日心情,日期降序)
- /admin/llm/* — 模型服务:catalog(服务商目录)/ models(实时发现)/
  profiles(多配置+单激活)。前端只提交 provider_id/model_id/api_key 三字段;
  URL 与 litellm 模型名映射由后端 catalog/presets 维护;**任何响应零密钥回显**

**状态一致性铁律**(全部变更操作在同一把 `_activate_lock` 内):
候选先在内存构造 → 模型 ID 格式校验 → 对所选模型真实最小
调用验证 → 单事务落库 → 提交成功才翻内存。任一步失败:库与内存双不动,
原激活配置继续服务;新建失败的配置**不留残行**(不是悄悄存成普通配置)。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import logger as app_logger
from app.admin.config_store import (
    ActiveProfileError,
    ConfigKeyError,
    Profile,
    apply_active,
    get_config_store,
)
from app.llm import catalog as llm_catalog
from app.llm.presets import get_preset, litellm_model_id
from app.llm.provider import LLMError, ProviderSpec, verify_provider
from app.memory import get_memory, get_semantic
from app.station.reports import get_reports

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="admin")

router = APIRouter(prefix="/admin", tags=["admin"])

# 变更锁:新建/编辑/激活/删除全部串行化。「单事务 + 提交后才翻内存」在并发下
# 仍可能库与内存指向不一致;锁内执行,失败两处皆不动。
_activate_lock = asyncio.Lock()


# ---- 记忆治理(原样保留) ----


@router.post("/clear_memory")
async def clear_memory() -> dict[str, Any]:
    try:
        counts = await get_memory().clear_all()
        counts["reports"] = get_reports().clear_all()
        counts["semantic"] = get_semantic().clear_all()
    except Exception as exc:
        logger.error("memory_clear_failed", reason=str(exc)[:120])
        raise HTTPException(status_code=503, detail="清除没有完成,请稍后再试一次。") from exc
    logger.info("memory_cleared", **counts)
    return {"ok": True, **counts}


@router.get("/memories")
async def list_memories(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """语义记忆列表(治理「用户可查看」;异常上抛→503,治理不降级)。"""
    try:
        items = get_semantic().list_items(limit)
    except Exception as exc:
        logger.error("semantic_list_failed", reason=str(exc)[:120])
        raise HTTPException(status_code=503, detail="记忆列表暂时读不出来,稍后再试一次。") from exc
    return {"items": items}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, Any]:
    """语义记忆单条删除(治理;id 不存在幂等删除,返回现状计数)。"""
    try:
        get_semantic().delete_items([memory_id])
    except Exception as exc:
        logger.error("semantic_delete_failed", reason=str(exc)[:120])
        raise HTTPException(status_code=503, detail="删除没有完成,请稍后再试一次。") from exc
    logger.info("semantic_deleted", memory_id=memory_id)
    return {"ok": True}


@router.get("/trends")
async def trends(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    """情绪趋势(治理视图口径):只回 mood_select 用户自我报告(R7 裁定,
    2026-10-15 分支会话);研判是系统分析产物,展示位在方案书/黑板。"""

    return {"moods": get_memory().recent_moods(days, source="mood_select")}


# ---- LLM 模型服务(/admin/llm/*) ----


class LiveModelsIn(BaseModel):
    """候选实时模型列表；编辑时可复用对应配置中已保存的密钥。"""

    provider_id: str
    api_key: str | None = None
    profile_id: str | None = None


class ProfileIn(BaseModel):
    """保存并激活(四字段表单的前三个;api_key 仅新建/更换时传)。"""

    provider_id: str
    model_id: str
    api_key: str | None = None


class ProfileUpdateIn(BaseModel):
    """编辑定位配置:缺省不动;api_key 空值=保留旧密钥。"""

    model_id: str | None = None
    api_key: str | None = None


def _profile_out(profile: Profile, active_id: str | None) -> dict[str, Any]:
    """响应形状(零密钥回显;verified 仅真实调用验证成功过才 true)。"""

    return {
        "id": profile.id,
        "provider_id": profile.provider_id,
        "model_id": profile.model_id,
        "display_name": profile.display_name,
        "api_key_set": profile.api_key is not None,
        "verified": profile.verified,
        "active": profile.id == active_id,
    }


def _require_preset(provider_id: str):
    preset = get_preset(provider_id)
    if preset is None:
        raise HTTPException(status_code=422, detail=f"未收录的服务商: {provider_id}")
    return preset


def _require_model_id(model_id: str) -> None:
    """只校验模型 ID 格式；真实可用性由连接验证确认。"""

    if not llm_catalog.is_valid_model_id(model_id):
        raise HTTPException(
            status_code=422,
            detail="模型 ID 格式不正确，请使用字母、数字、点、冒号、下划线或连字符。",
        )


async def _verify_candidate(provider_id: str, model_id: str, api_key: str | None) -> None:
    """真实验证:对**所选模型**发 max_tokens=1 的最小调用。

    /models 列表只证明 key 可见该模型,调用权限/额度只有真调用能证明。
    失败抛 HTTPException(400);429/5xx/超时区分「可重试」提示。
    """

    preset = _require_preset(provider_id)
    spec = ProviderSpec(
        model=litellm_model_id(provider_id, model_id),
        api_key=api_key or "",
        base_url=preset.base_url if preset.api_base_supported else "",
    )
    try:
        await verify_provider(spec)
    except LLMError as exc:
        detail = str(exc)
        retryable = any(k in detail for k in ("429", "503", "timeout", "Timeout", "rate"))
        suffix = "可能是限流或服务端波动,可重试激活。" if retryable else ""
        logger.warning(
            "llm_activate_rejected",
            provider=provider_id,
            model=model_id,
            reason=detail[:120],
        )
        raise HTTPException(status_code=400, detail=f"激活验证未通过:{detail[:160]}{suffix}") from exc


def _persist(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """落库包装:DB/OS 层失败 → 503(配置保存失败),不让异常裸奔成 500,
    更不会走到翻内存那一步。Domain 异常(Key/Activate)原样抛出交路由层。"""

    try:
        return fn(*args, **kwargs)
    except (ConfigKeyError, ActiveProfileError):
        raise
    except Exception as exc:
        logger.error("llm_persist_failed", reason=str(exc)[:120])
        raise HTTPException(status_code=503, detail="配置保存失败,请稍后再试。") from exc


@router.get("/llm/catalog")
async def llm_catalog_endpoint() -> dict[str, Any]:
    """服务商 + 本地 catalog 候选(preset 单源;**非实时清单**,实时发现走
    POST /llm/models;verified 只打激活配置的那一个 pair)。"""

    active = get_config_store().active_profile()
    verified_pairs = (
        frozenset({(active.provider_id, active.model_id)}) if active is not None else frozenset()
    )
    return {"providers": llm_catalog.catalog_payload(verified_pairs)}


@router.post("/llm/models")
async def llm_live_models(body: LiveModelsIn) -> dict[str, Any]:
    """提交 key 后的实时模型发现:探测成功 → live 置顶 + 回落 catalog 候选;
    探测失败 → **照样返回 catalog 候选**(不是空数组)+ live_error 说明。"""

    _require_preset(body.provider_id)
    api_key = body.api_key
    api_key_source = "submitted" if api_key else "none"
    if not api_key and body.profile_id:
        profile = get_config_store().get_profile(body.profile_id)
        if profile is not None and profile.provider_id == body.provider_id:
            api_key = profile.api_key
            if api_key:
                api_key_source = "saved"
    live = await llm_catalog.fetch_live_models(body.provider_id, api_key)
    live_error: str | None = None
    if live is None:
        live_error = "实时列表探测失败,以下为内置目录候选(可能不是最新)。"
        live = []
    merged = llm_catalog.merge_live(body.provider_id, live)
    return {
        "provider_id": body.provider_id,
        "models": [{"id": m.id, "name": m.name, "source": m.source} for m in merged],
        "live_error": live_error,
        "api_key_source": api_key_source,
    }


@router.get("/llm/profiles")
async def llm_profiles_list() -> dict[str, Any]:
    active_id = get_config_store().active_id()
    raw_profiles = get_config_store().list_profiles()
    raw_profiles.sort(key=lambda profile: profile.id != active_id)
    profiles = [_profile_out(p, active_id) for p in raw_profiles]
    return {"active_id": active_id, "profiles": profiles}


@router.post("/llm/profiles")
async def llm_profiles_create(body: ProfileIn) -> dict[str, Any]:
    """保存待启动配置；只有显式点击启动才验证并切换项目 LLM。"""

    store = get_config_store()
    preset = _require_preset(body.provider_id)
    _require_model_id(body.model_id)
    if preset.needs_key and not body.api_key:
        raise HTTPException(status_code=422, detail="该服务商需要 API Key，保存前请先填写。")
    async with _activate_lock:
        if any(profile.provider_id == body.provider_id for profile in store.list_profiles()):
            raise HTTPException(status_code=409, detail="同一服务商只能配置一个")
        try:
            profile = _persist(store.create_profile, body.provider_id, body.model_id, body.api_key)
        except ConfigKeyError as exc:
            raise HTTPException(
                status_code=400,
                detail="未配置可用的加密密钥,无法保存 API Key;配置未创建。",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("llm_profile_created", profile_id=profile.id, provider=profile.provider_id)
    return {"id": profile.id, "active": False, "display_name": profile.display_name}


@router.put("/llm/profiles/{profile_id}")
async def llm_profiles_update(profile_id: str, body: ProfileUpdateIn) -> dict[str, Any]:
    """编辑:锁内 构造候选 → (有变化则)验证 → 单事务落库 → 激活中才翻内存。

    - 激活中配置:验证失败 = 库与内存双不动(不会"库已新、内存还旧")
    - 非激活配置:不自动激活;改 model/key 清 verified(下次激活重新验证)
    - api_key 空/缺省 = 保留旧密钥(读原密文,不清空)
    """

    store = get_config_store()
    async with _activate_lock:
        current = store.get_profile(profile_id)
        if current is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        if body.model_id is not None and body.model_id != current.model_id:
            _require_model_id(body.model_id)
        candidate_changed = (body.model_id is not None and body.model_id != current.model_id) or bool(
            body.api_key
        )
        is_active = store.active_id() == profile_id
        if candidate_changed and is_active:
            # 激活中配置:候选先真实验证,再落库(验证失败库与内存双不动)
            await _verify_candidate(
                current.provider_id, body.model_id or current.model_id, body.api_key or current.api_key
            )
            verified_flag: bool | None = True
        else:
            # 非激活配置:不自动激活、不验证;model/key 变化时 verified 由 apply_edit 清
            verified_flag = None
        try:
            updated = _persist(
                store.apply_edit,
                profile_id,
                model_id=body.model_id,
                api_key=body.api_key,
                verified=verified_flag,
            )
        except ConfigKeyError as exc:
            raise HTTPException(
                status_code=400,
                detail="未配置可用的加密密钥,无法保存 API Key;修改未保存。",
            ) from exc
        if is_active:
            apply_active(updated)  # 提交成功后才翻内存
    return {
        "id": updated.id,
        "display_name": updated.display_name,
        "active": is_active,
        "verified": updated.verified,
    }


@router.post("/llm/profiles/{profile_id}/activate")
async def llm_profiles_activate(profile_id: str) -> dict[str, Any]:
    """切换激活:锁内 验证 → 单事务(指针 + verified 同提交)→ 翻内存。"""

    store = get_config_store()
    async with _activate_lock:
        profile = store.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        await _verify_candidate(profile.provider_id, profile.model_id, profile.api_key)
        activated = _persist(store.activate_verified, profile_id)
        apply_active(activated)
    logger.info(
        "llm_activated", profile_id=activated.id, provider=activated.provider_id,
        model=activated.model_id,
    )
    return {"ok": True, "active_id": activated.id}


@router.post("/llm/profiles/{profile_id}/verify")
async def llm_profiles_verify(profile_id: str) -> dict[str, Any]:
    """验证模型连接但不切换当前 active profile。"""

    store = get_config_store()
    async with _activate_lock:
        profile = store.get_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        await _verify_candidate(profile.provider_id, profile.model_id, profile.api_key)
        verified = _persist(store.apply_edit, profile_id, verified=True)
        if store.active_id() == profile_id:
            apply_active(verified)
    logger.info(
        "llm_connection_verified", profile_id=verified.id, provider=verified.provider_id,
        model=verified.model_id,
    )
    return {"ok": True, "active": verified.id == store.active_id(), "verified": verified.verified}


@router.delete("/llm/profiles/{profile_id}")
async def llm_profiles_delete(profile_id: str) -> dict[str, Any]:
    """删除(锁内,与激活/编辑串行);运行中的配置必须先切换后删除。"""

    async with _activate_lock:
        try:
            _persist(get_config_store().delete_profile, profile_id)
        except ActiveProfileError as exc:
            raise HTTPException(
                status_code=409, detail="运行中的模型不能删除,请先启动其他模型。"
            ) from exc
    logger.info("llm_profile_deleted", profile_id=profile_id)
    return {"ok": True}
