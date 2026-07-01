"""``/api/v1/stock`` — Bearer 인증 기반 주식 시세·관심 종목·시장 동향 endpoint.

frontend Stocks 탭이 직접 호출. tool layer 의 stock_data / stock_watch 를 wrap.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel

from src.agent_framework.tools import stock_data, stock_watch
from src.api.routers.schedule_v1 import (
    _account_id_from_bearer,
    _resolve_args,
)
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/stock", tags=["주식"])


@router.get("/quote")
async def get_quote(
    symbol: str = Query(..., description="종목명 또는 6자리 코드"),
) -> dict[str, Any]:
    return await stock_data.quote({"symbol": symbol})


@router.get("/movers")
async def get_movers(
    market: str = Query("ALL"),
    top_n: int = Query(5, ge=1, le=30),
) -> dict[str, Any]:
    return await stock_data.market_movers({"market": market, "top_n": top_n})


@router.get("/watch")
async def list_watch(
    authorization: str = Header(...),
    scope_group: str | None = Query(None),
) -> dict[str, Any]:
    """관심·보유 종목 목록 + 현재가/손익."""
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    if scope_group:
        args["scope_group"] = scope_group
    return await stock_watch.list_watch(args)


class WatchAddBody(BaseModel):
    symbol: str
    qty: int | None = None
    avg_cost: int | None = None
    alert_high: int | None = None
    alert_low: int | None = None
    monitor_interval_min: int | None = None
    note: str | None = None
    scope_group: str | None = None


@router.post("/watch")
async def add_watch(
    body: WatchAddBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await stock_watch.add_watch(args)


class WatchUpdateBody(BaseModel):
    qty: int | None = None
    avg_cost: int | None = None
    alert_high: int | None = None
    alert_low: int | None = None
    monitor_interval_min: int | None = None
    note: str | None = None


@router.patch("/watch/{wid}")
async def update_watch(
    wid: str,
    body: WatchUpdateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = wid
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await stock_watch.update_watch(args)


@router.delete("/watch/{wid}")
async def delete_watch(
    wid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = wid
    return await stock_watch.delete_watch(args)
