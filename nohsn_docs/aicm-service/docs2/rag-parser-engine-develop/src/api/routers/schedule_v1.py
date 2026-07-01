"""``/api/v1/schedule`` — Bearer 인증 기반 일정 CRUD.

manifest yaml 의 ``list_endpoint: /api/v1/schedule`` 가 가리키는 frontend
페이지용 endpoint. 기존 ``/agent/data/schedules`` 는 phone query 기반
legacy 흐름이라 frontend (Bearer 토큰 사용) 와 맞지 않아 빈 화면이 나오던
문제 해결 (2026-04-28).

설계
----
- Bearer access token → account_id → email → ``e:<email>`` 형식 phone scope
- ``schedule_store`` 위임 — Redis 모드면 phone scope, KMS 모드면 personal_tenant_id
- ``scope_group`` 옵션 query 파라미터로 scope 별 조회 (T4 인지)
"""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.tools import schedule_store
from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/schedule", tags=["일정"])

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


async def _reset_engine_for_tests() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def _account_id_from_bearer(authorization: str) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "empty token")
    try:
        payload = decode_token(token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    if payload.get("type") not in (None, "access"):
        raise HTTPException(401, "not an access token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    return str(sub)


async def _resolve_args(account_id: str) -> dict[str, Any]:
    """phone scope + (KMS 모드면) personal_tenant_id 추출."""
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT email, phone, personal_tenant_id::text "
                    "FROM accounts WHERE id = :a LIMIT 1"
                ),
                {"a": account_id},
            )
        ).first()
    if row is None:
        raise HTTPException(404, "account not found")
    email, phone, personal_tid = row
    # signup hook 의 _synthetic_phone_for_email 와 동일 규칙 — 우선 accounts.phone
    # 사용. 없으면 email 기반 fallback.
    if not phone and email:
        sanitized = re.sub(r"[^a-zA-Z0-9_.@-]", "_", email.lower())
        phone = f"e:{sanitized}"[:32]
    args: dict[str, Any] = {"phone": phone}
    if (
        os.environ.get("AGENT_DATA_STORE", "redis").lower() == "kms"
        and personal_tid
    ):
        args["tenant_id"] = personal_tid
    return args


class ScheduleCreateBody(BaseModel):
    title: str
    when: str
    who: str | None = None
    where: str | None = None
    recurrence: str | None = None
    scope_group: str | None = None  # personal / sole_proprietor / company / business


@router.get("")
async def list_schedules(
    authorization: str = Header(...),
    scope_group: str | None = Query(None, description="scope 필터 (개인/사업/회사 등)"),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    if scope_group:
        args["scope_group"] = scope_group
    return await schedule_store.list_all(args)


@router.get("/summary")
async def schedule_summary(
    authorization: str = Header(...),
    scope_group: str | None = Query(None),
) -> dict[str, Any]:
    """Manifest summary_widgets 가 기대하는 stat/list 집계."""
    from datetime import datetime, timezone, timedelta

    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    if scope_group:
        args["scope_group"] = scope_group
    data = await schedule_store.list_all(args)
    items = data.get("items", []) or []

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    week_end = (now + timedelta(days=7)).date().isoformat()

    def _date_part(it: dict[str, Any]) -> str:
        w = (it.get("when") or "")[:10]
        return w

    today_count = sum(1 for it in items if _date_part(it) == today)
    week_count = sum(1 for it in items if today <= _date_part(it) <= week_end)
    upcoming = sorted(
        (it for it in items if _date_part(it) >= today),
        key=lambda it: it.get("when", ""),
    )[:5]
    return {
        "today_count": today_count,
        "week_count": week_count,
        "upcoming": upcoming,
    }


@router.get("/{sid}")
async def get_schedule(
    sid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    data = await schedule_store.list_all(args)
    for it in data.get("items", []) or []:
        if str(it.get("id")) == sid:
            return it
    raise HTTPException(404, "schedule not found")


@router.post("")
async def create_schedule(
    body: ScheduleCreateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await schedule_store.create(args)


class ScheduleUpdateBody(BaseModel):
    title: str | None = None
    when: str | None = None
    who: str | None = None
    where: str | None = None
    recurrence: str | None = None
    scope_group: str | None = None


@router.patch("/{sid}")
async def update_schedule(
    sid: str,
    body: ScheduleUpdateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = sid
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await schedule_store.update(args)


@router.delete("/{sid}")
async def delete_schedule(
    sid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = sid
    return await schedule_store.delete(args)


__all__ = ["router"]
