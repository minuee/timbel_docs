"""``/api/v1/expense`` — Bearer 인증 기반 가계부 CRUD."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from src.agent_framework.tools import expense_store
from src.api.routers.schedule_v1 import (
    _account_id_from_bearer,
    _resolve_args,
)
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/expense", tags=["가계부"])


class ExpenseCreateBody(BaseModel):
    amount: int | str
    category: str
    description: str | None = None
    spent_at: str | None = None
    payment_method: str | None = None
    scope_group: str | None = None


@router.get("")
async def list_expenses(
    authorization: str = Header(...),
    period_start: str | None = Query(None),
    period_end: str | None = Query(None),
    scope_group: str | None = Query(None),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    if period_start:
        args["period_start"] = period_start
    if period_end:
        args["period_end"] = period_end
    if scope_group:
        args["scope_group"] = scope_group
    return await expense_store.list_all(args)


@router.post("")
async def create_expense(
    body: ExpenseCreateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await expense_store.create(args)


@router.delete("/{eid}")
async def delete_expense(
    eid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = eid
    return await expense_store.delete(args)


@router.get("/summary")
async def expense_summary(
    authorization: str = Header(...),
    period_start: str | None = Query(None),
    period_end: str | None = Query(None),
    scope_group: str | None = Query(None),
) -> dict[str, Any]:
    """Manifest summary_widgets — 합계 / 일평균 / 카테고리별 / 일자별."""
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    if period_start:
        args["period_start"] = period_start
    if period_end:
        args["period_end"] = period_end
    if scope_group:
        args["scope_group"] = scope_group
    data = await expense_store.list_all(args)
    items = data.get("items", []) or []
    total = 0
    by_category: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for it in items:
        amt = it.get("amount") or 0
        try:
            amt = int(amt)
        except (ValueError, TypeError):
            amt = 0
        total += amt
        cat = (it.get("category") or "기타").strip() or "기타"
        by_category[cat] = by_category.get(cat, 0) + amt
        day = (it.get("spent_at") or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + amt
    daily_avg = (total // max(len(by_day), 1)) if by_day else 0
    return {
        "total": total,
        "daily_avg": daily_avg,
        "by_category": by_category,
        "by_day": by_day,
    }


@router.get("/{eid}")
async def get_expense(
    eid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    data = await expense_store.list_all(args)
    for it in data.get("items", []) or []:
        if str(it.get("id")) == eid:
            return it
    raise HTTPException(404, "expense not found")


__all__ = ["router"]
