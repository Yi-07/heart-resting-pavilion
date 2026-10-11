"""管理通道 REST(端点单源=ws-contract §1):治理查看/一键清除/模型配置,不进 WS。

- POST /admin/clear_memory — 一键清除用户记忆(Redis 全键+冷层心情+方案书+语义库)。
  治理操作不降级:失败如实 503,不误报「已清除」(与记忆层「异常吞掉、保证回合进行」的默认行为相反,有意例外)
- GET /admin/memories — 语义记忆列表;DELETE /admin/memories/{id} — 单条删除(同治理纪律)
- GET /admin/trends?days=7 — 情绪趋势(冷层每日心情,日期降序)
- POST /admin/config — LLM 引擎配置:落库(api_key AES-GCM)+进程内即时应用;
  响应永不回显密钥(前端零密钥,spec §4 L7)
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import config
from app import logger as app_logger
from app.admin.config_store import (
    ConfigKeyError,
    StoredLLMConfig,
    apply_llm_config,
    get_config_store,
)
from app.memory import get_memory, get_semantic
from app.station.reports import get_reports

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="admin")

router = APIRouter(prefix="/admin", tags=["admin"])


class LLMConfigIn(BaseModel):
    """契约未定义 admin 请求体,形状归本模块;provider 两源与 config/env 对齐。"""

    provider: Literal["deepseek", "ollama"]
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


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
    return {"moods": get_memory().recent_moods(days)}


@router.post("/config")
async def set_config(body: LLMConfigIn) -> dict[str, Any]:
    stored = StoredLLMConfig(
        provider=body.provider, model=body.model, base_url=body.base_url, api_key=body.api_key
    )
    try:
        get_config_store().save(stored)
    except ConfigKeyError as exc:
        raise HTTPException(
            status_code=400,
            detail="未配置可用的 HRP_CONFIG_AES_KEY,无法加密存储 api_key;本次配置未保存。",
        ) from exc
    apply_llm_config(stored)
    logger.info("config_saved", provider=body.provider, has_key=body.api_key is not None)
    return {"ok": True, "provider": body.provider, "model": body.model}


def _current_llm_config() -> dict[str, Any]:
    """当前生效 LLM 配置(读进程 config;api_key 只给布尔,绝不回显密钥,spec §4 L7)。"""

    active = config.LLM_PROVIDER
    active_key_set = bool(config.DEEPSEEK_API_KEY) if active == "deepseek" else False
    providers = [
        {
            "id": "deepseek",
            "model": config.DEEPSEEK_MODEL,
            "base_url": config.DEEPSEEK_BASE_URL,
        },
        {
            "id": "ollama",
            "model": config.OLLAMA_MODEL,
            "base_url": config.OLLAMA_URL,
        },
    ]
    return {"provider": active, "api_key_set": active_key_set, "providers": providers}


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """读当前 LLM 配置供前端预填;绝不回显 api_key。"""

    return _current_llm_config()
