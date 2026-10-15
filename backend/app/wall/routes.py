"""留言墙 REST。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .store import get_store

router = APIRouter(prefix="/wall", tags=["wall"])


class WallMessageIn(BaseModel):
    session_id: str = Field(min_length=8, max_length=128)
    text: str = Field(min_length=1, max_length=2000)


@router.get("")
async def list_wall(session_id: str = Query(min_length=8, max_length=128)) -> dict[str, Any]:
    return {"messages": get_store().list_messages(session_id), "unread": get_store().unread_count(session_id)}


@router.post("/read")
async def mark_wall_read(session_id: str = Query(min_length=8, max_length=128)) -> dict[str, Any]:
    """用户已经打开并看到留言后才清除未读状态。"""

    return {"ok": True, "read": get_store().mark_read(session_id)}


@router.get("/unread")
async def unread_wall(session_id: str = Query(min_length=8, max_length=128)) -> dict[str, Any]:
    return {"unread": get_store().unread_count(session_id)}


@router.post("")
async def create_wall(body: WallMessageIn) -> dict[str, Any]:
    return {"message": get_store().add(body.session_id, body.text)}


@router.delete("")
async def clear_wall(session_id: str = Query(min_length=8, max_length=128)) -> dict[str, Any]:
    return {"ok": True, "deleted": get_store().clear(session_id)}
