"""``/api/v1/feed`` — KMS-Plus P0.2 backend wrapper layer (PR P3 의존).

frontend-v3 FeedPage 가 호출. account 단위 이벤트 카드 목록 + read 상태 토글.

엔드포인트
----------
- ``GET  /api/v1/feed?limit=20&only_today=false&cursor=<iso>__<uuid>``
- ``POST /api/v1/feed/{fid}/read`` — idempotent (이미 읽음 → success=False)

cursor pagination — composite (produced_at, id):
    cursor 형식 = ``<ISO8601>__<UUID>``.
    predicate ``(produced_at, id) < (:cur_ts, :cur_id)`` 로
    같은 produced_at 을 갖는 row 도 누락 없이 페이지네이션.

scope: Bearer 토큰 → account_id. P0.2 hardening (codex 2차 review):
    ``X-Tenant-ID`` 헤더 또는 토큰 claim 으로 tenant 격리.
    멤버십 검증 (``tenant_memberships``) 후 필터.
    헤더 부재 시 ``accounts.personal_tenant_id`` 로 fallback.

rate limit: ``KMS_RATE_LIMIT_ENABLED=true`` 일 때 60/minute IP 기준 적용.
    middleware 가 off 면 decorator 는 no-op (개발/테스트 호환).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.api.middleware.rate_limit import limiter
from src.common.config import settings
from src.common.logging import get_logger


log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/feed", tags=["feed-v1"])


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


def _account_id_from_bearer(authorization: str) -> UUID:
    """Bearer JWT → account_id (UUID). schedule_v1 / tenants_v1 동일 패턴."""
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
    try:
        return UUID(str(sub))
    except ValueError as e:
        raise HTTPException(401, f"invalid subject: {e}") from e


async def _resolve_active_tenant(
    account_id: UUID, x_tenant_id: str | None
) -> UUID:
    """X-Tenant-ID 헤더 우선, 없으면 personal_tenant_id fallback (chat_upload 패턴).

    P0.2 hardening (codex 2차):
    - 헤더 비어있는 문자열 → 400 (silent fallback 차단)
    - 헤더 UUID 잘못 → 400
    - 헤더 UUID 맞지만 멤버십 row 없음 → 403
    - 헤더 부재 → ``accounts.personal_tenant_id`` (없으면 404)
    """
    if x_tenant_id is not None:
        cleaned = x_tenant_id.strip()
        if not cleaned:
            raise HTTPException(400, "X-Tenant-ID cannot be empty")
        try:
            tid = UUID(cleaned)
        except (ValueError, AttributeError) as e:
            raise HTTPException(400, f"invalid X-Tenant-ID: {e}") from e
        eng = _get_engine()
        async with eng.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM tenant_memberships "
                        "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
                    ),
                    {"aid": account_id, "tid": tid},
                )
            ).first()
        if not row:
            raise HTTPException(403, "not a member of this tenant")
        return tid
    # fallback: personal_tenant_id
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT personal_tenant_id FROM accounts "
                    "WHERE id = :aid AND is_active = true LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
    if not row or not row[0]:
        raise HTTPException(404, "account missing personal_tenant_id")
    return UUID(str(row[0]))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FeedItem(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    body_html: str | None = None
    pills: list[Any] = []
    read_at: str | None = None
    produced_at: str
    source: dict[str, Any] = {}


class FeedListOut(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None = None


class MarkReadOut(BaseModel):
    success: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_start_utc() -> datetime:
    """UTC 기준 오늘 자정 (00:00). only_today 필터 기준."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _coerce_jsonb(val: Any, default: Any) -> Any:
    """asyncpg/psycopg2 가 jsonb 를 dict/list 또는 str 로 돌려주는 경우 모두 허용."""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return default


# P0.2 hardening (codex P2-2): cursor 는 produced_at + id 의 composite.
# 옛 구현은 produced_at 단독 → 동일 시각의 row 가 누락. 새 구현은
# ``<ISO8601>__<UUID>`` 형식.
_CURSOR_DELIM = "__"


def _parse_cursor(cursor: str) -> tuple[datetime, UUID]:
    """``<ISO8601>__<UUID>`` → (timestamp, id). 잘못된 형식이면 ValueError."""
    if _CURSOR_DELIM not in cursor:
        raise ValueError(
            f"cursor must be '<ISO8601>{_CURSOR_DELIM}<UUID>'"
        )
    iso_part, uuid_part = cursor.rsplit(_CURSOR_DELIM, 1)
    dt = datetime.fromisoformat(iso_part)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    uid = UUID(uuid_part)
    return dt, uid


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=FeedListOut)
@limiter.limit("60/minute")
async def list_feed(
    request: Request,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    limit: int = Query(20, ge=1, le=100),
    only_today: bool = Query(False),
    cursor: str | None = Query(
        None,
        description=(
            "composite cursor — '<ISO8601 produced_at>__<UUID id>'. "
            "이 row 직후부터 반환."
        ),
    ),
) -> FeedListOut:
    """현재 (account, tenant) 의 feed 이벤트 목록 (produced_at, id) DESC.

    P0.2 hardening — tenant 격리:
        ``X-Tenant-ID`` 헤더 우선, 없으면 personal_tenant_id 로 resolve.
        멤버십 검증 후 ``tenant_id`` 컬럼으로 WHERE 필터.

    P0.2 hardening — cursor 무손실:
        composite ``(produced_at, id)`` predicate 로 동일 시각 row 도 모두 거치게.
    """
    aid = _account_id_from_bearer(authorization)
    tid = await _resolve_active_tenant(aid, x_tenant_id)
    eng = _get_engine()

    # cursor 파싱 — 잘못된 형식이면 400.
    cursor_dt: datetime | None = None
    cursor_id: UUID | None = None
    if cursor:
        try:
            cursor_dt, cursor_id = _parse_cursor(cursor)
        except ValueError as e:
            raise HTTPException(400, f"invalid cursor: {e}") from e

    # WHERE 절을 동적으로 조립. 파라미터 바인딩만 사용 (string concat X).
    conditions = ["account_id = :aid", "tenant_id = :tid"]
    params: dict[str, Any] = {
        "aid": aid,
        "tid": tid,
        "lim": limit + 1,
    }
    if only_today:
        conditions.append("produced_at >= :today_start")
        params["today_start"] = _today_start_utc()
    if cursor_dt is not None and cursor_id is not None:
        # composite predicate — produced_at 가 같으면 id 로 tie-break.
        conditions.append("(produced_at, id) < (:cur_ts, :cur_id)")
        params["cur_ts"] = cursor_dt
        params["cur_id"] = cursor_id

    sql = (
        "SELECT id, kind, title, body, body_html, pills, read_at, "
        "       produced_at, source "
        "FROM feed_events "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY produced_at DESC, id DESC "
        "LIMIT :lim"
    )

    async with eng.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()

    # limit+1 fetch → next_cursor 계산.
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor: str | None = None
    if has_more and rows:
        last_id = rows[-1][0]
        last_produced = rows[-1][7]
        if isinstance(last_produced, datetime):
            next_cursor = (
                f"{last_produced.isoformat()}{_CURSOR_DELIM}{last_id}"
            )

    items: list[FeedItem] = []
    for r in rows:
        items.append(
            FeedItem(
                id=str(r[0]),
                kind=r[1],
                title=r[2],
                body=r[3],
                body_html=r[4],
                pills=_coerce_jsonb(r[5], []),
                read_at=r[6].isoformat() if isinstance(r[6], datetime) else None,
                produced_at=r[7].isoformat() if isinstance(r[7], datetime) else "",
                source=_coerce_jsonb(r[8], {}),
            )
        )
    return FeedListOut(items=items, next_cursor=next_cursor)


@router.post("/{fid}/read", response_model=MarkReadOut)
async def mark_feed_read(
    fid: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> MarkReadOut:
    """feed_event 를 읽음 처리. 이미 읽음 / 본인 row 아님 / 다른 tenant → success=False.

    P0.2 hardening — cross-tenant mark_read 차단: WHERE 에 tenant_id 추가.
    """
    aid = _account_id_from_bearer(authorization)
    tid = await _resolve_active_tenant(aid, x_tenant_id)
    try:
        feed_id = UUID(fid)
    except ValueError as e:
        raise HTTPException(400, f"invalid feed id: {e}") from e

    eng = _get_engine()
    async with eng.begin() as conn:
        # read_at IS NULL 조건 — idempotent. 두 번째 호출은 0 row affected.
        # tenant_id 도 함께 검사 — 다른 tenant 의 row 는 0 row affected.
        r = await conn.execute(
            text(
                """
                UPDATE feed_events
                   SET read_at = now()
                 WHERE id = :fid
                   AND account_id = :aid
                   AND tenant_id = :tid
                   AND read_at IS NULL
                """
            ),
            {"fid": feed_id, "aid": aid, "tid": tid},
        )
        rowcount = r.rowcount or 0
    return MarkReadOut(success=rowcount > 0)
