"""``/api/v1/diary`` — Bearer 인증 기반 일기 CRUD.

schedule_v1 과 동일 패턴 — manifest yaml 이 명시한 endpoint 를 실제로 만든다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from src.agent_framework.tools import diary_store
from src.api.routers.schedule_v1 import (
    _account_id_from_bearer,
    _resolve_args,
)
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/diary", tags=["일기"])


class DiaryCreateBody(BaseModel):
    entry_text: str
    emotion: str | None = None
    date: str | None = None
    scope_group: str | None = None


@router.get("")
async def list_diaries(
    authorization: str = Header(...),
    query: str = Query("", description="본문 검색어"),
    emotion: str | None = Query(None),
    top_k: int = Query(50, ge=1, le=500),
    scope_group: str | None = Query(None),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({"query": query, "emotion": emotion, "top_k": top_k})
    if scope_group:
        args["scope_group"] = scope_group
    return await diary_store.search(args)


@router.post("")
async def create_diary(
    body: DiaryCreateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await diary_store.save(args)


class DiaryUpdateBody(BaseModel):
    entry_text: str | None = None
    emotion: str | None = None
    date: str | None = None
    scope_group: str | None = None


@router.patch("/{did}")
async def update_diary(
    did: str,
    body: DiaryUpdateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = did
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await diary_store.update(args)


@router.delete("/{did}")
async def delete_diary(
    did: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = did
    return await diary_store.delete(args)


@router.get("/summary")
async def diary_summary(
    authorization: str = Header(...),
    scope_group: str | None = None,
) -> dict[str, Any]:
    """Manifest summary_widgets — 이번 달 기록수 / 연속일 / 기분 분포."""
    from datetime import datetime, timezone

    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({"query": "", "emotion": None, "top_k": 1000})
    if scope_group:
        args["scope_group"] = scope_group
    data = await diary_store.search(args)
    hits = data.get("hits", []) or []
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")
    month_count = sum(
        1 for h in hits if (h.get("date") or "").startswith(month_prefix)
    )
    by_mood: dict[str, int] = {}
    for h in hits:
        m = (h.get("emotion") or "기타").strip() or "기타"
        by_mood[m] = by_mood.get(m, 0) + 1
    # streak — 연속 작성일 (오늘부터 거꾸로).
    dates = sorted({h.get("date") for h in hits if h.get("date")}, reverse=True)
    streak = 0
    cur = now.date()
    for d in dates:
        try:
            from datetime import date as _date

            dd = _date.fromisoformat(d)
        except Exception:
            continue
        if dd == cur:
            streak += 1
            cur = cur.fromordinal(cur.toordinal() - 1)
        elif dd < cur:
            break
    return {
        "month_count": month_count,
        "streak_days": streak,
        "by_mood": by_mood,
    }


@router.get("/{did}")
async def get_diary(
    did: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({"query": "", "emotion": None, "top_k": 1000})
    data = await diary_store.search(args)
    for it in data.get("hits", []) or []:
        if str(it.get("id")) == did:
            return it
    raise HTTPException(404, "diary not found")


__all__ = ["router"]
