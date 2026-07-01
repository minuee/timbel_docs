"""/api/v1/admin/global-view — admin/owner 전용 통합 view (D29 §2 / #156).

D23 §1 (#152) + §7 (#162) 의 owner_agent_id 격리 정책으로 *cross-agent 이
default 차단* 됨. admin/owner 운영자가 tenant 안 모든 agent 의 자료를
한눈에 보는 endpoint.

설계
----
- backend 직접 query (helper 미사용 — owner_agent_id / agent_name /
  agent_is_active / created_at / preview shape 필요).
- defense-in-depth:
  1. JWT → tenant + role
  2. ``_verify_membership`` → role in (owner, admin) — 아니면 403
  3. doctype/scope/order/range 는 *static whitelist* — 임의 입력 거부
  4. ``q`` (title contains) 는 parameter binding 만 (no string interpolation)
  5. ``documents.tenant_id = :tid`` 강제 (cross-tenant 차단)
  6. 일반 caller path 는 ``include_null_owner`` 받지 않음 — admin 통과 시
     자동으로 NULL owner row 도 노출 (admin sentinel 동등)

권한 통과 시 admin 은 자기 tenant 안에서만 cross-agent 가시 — D23 admin
sentinel 의 endpoint layer (L3) 등가.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from src.api.routers.agents_v1 import (
    _account_from_token,
    _get_engine,
    _resolve_tenant,
    _verify_membership,
)
from src.core.services.audit_service import record_action


router = APIRouter(prefix="/api/v1/admin", tags=["admin-global-view"])


# ---------------------------------------------------------------------------
# Static whitelist
# ---------------------------------------------------------------------------


# scope alias → document_types.name 매핑. static — 외부 입력 영향 없음.
_SCOPE_TO_DOCTYPE: dict[str, str] = {
    "schedule": "agent_schedule",
    "memo": "agent_memo",
    "expense": "agent_expense",
    "diary": "agent_diary",
    "reminder": "agent_reminder",
}
_SCOPE_ALIASES = list(_SCOPE_TO_DOCTYPE.keys()) + ["all"]
_ORDER_ALIASES = ("desc", "asc")
_RANGE_ALIASES = ("today", "week", "month", "all")


# documents 의 repositories.name (agent_data repository 안 만 노출)
_AGENT_DATA_REPO_NAME = "__agent_data__"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class GlobalViewItem(BaseModel):
    scope: str
    id: str
    title: str | None = None
    preview: str | None = None
    created_at: str | None = None
    owner_agent_id: str | None = None
    agent_name: str | None = None
    agent_is_active: bool | None = None


class GlobalViewResponse(BaseModel):
    items: list[GlobalViewItem]
    total: int
    scope_counts: dict[str, int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_range(range_alias: str, now: datetime | None = None) -> datetime | None:
    """range alias → since 시각. 'all' 은 None (필터 안 함)."""
    now = now or datetime.now(timezone.utc)
    if range_alias == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_alias == "week":
        return now - timedelta(days=7)
    if range_alias == "month":
        return now - timedelta(days=30)
    return None  # 'all'


def _build_query(
    *,
    tenant_id: UUID,
    doctype_name: str,
    agent_id_filter: UUID | None,
    range_since: datetime | None,
    q: str | None,
    limit: int,
    order_desc: bool,
) -> tuple[str, dict[str, Any]]:
    """SQL + params 빌드. testable layer.

    NO injection points: order/scope 는 caller (global_view) 가 static
    whitelist 검증 후 호출. 본 함수의 입력은 server-controlled value 만.
    """
    order_sql = "DESC" if order_desc else "ASC"
    where_extra = ""
    params: dict[str, Any] = {
        "tid": tenant_id,
        "dt": doctype_name,
        "repo": _AGENT_DATA_REPO_NAME,
        "lim": int(limit),
    }
    if agent_id_filter is not None:
        where_extra += " AND d.owner_agent_id = :aid"
        params["aid"] = agent_id_filter
    if range_since is not None:
        where_extra += " AND d.created_at >= :since"
        params["since"] = range_since
    if q:
        where_extra += " AND d.title ILIKE :qpat"
        params["qpat"] = f"%{q}%"

    # D29 §2 (2026-05-08, GPT-5 사전 verdict NO-GO patch) — `d.tenant_id = :tid`
    # 강제. NULL tenant document 는 admin global view 에서 노출 금지 (cross-tenant
    # leak 위험). NULL owner row 노출은 별개 — owner_agent_id 필터를 걸지 않으면
    # 자연스럽게 보임 (admin sentinel L3 등가).
    sql = f"""
        SELECT
            d.id, d.title, d.processing_meta, d.created_at,
            d.owner_agent_id,
            a.name AS agent_name, a.is_active AS agent_is_active
        FROM documents d
        JOIN document_types dt ON d.document_type_id = dt.id
        JOIN repositories r ON d.repository_id = r.id
        LEFT JOIN agents a
          ON a.id = d.owner_agent_id
         AND a.tenant_id = :tid
        WHERE r.tenant_id = :tid
          AND dt.tenant_id = :tid
          AND d.tenant_id = :tid
          AND dt.name = :dt
          AND r.name = :repo
          AND d.status = 'active'
          {where_extra}
        ORDER BY d.created_at {order_sql}
        LIMIT :lim
    """
    return sql, params


async def _query_doctype(
    eng,
    *,
    tenant_id: UUID,
    doctype_name: str,
    scope_alias: str,
    agent_id_filter: UUID | None,
    range_since: datetime | None,
    q: str | None,
    limit: int,
    order_desc: bool,
) -> list[dict[str, Any]]:
    """단일 doctype 의 row 목록 — owner_agent_id / agent JOIN 포함."""
    sql, params = _build_query(
        tenant_id=tenant_id,
        doctype_name=doctype_name,
        agent_id_filter=agent_id_filter,
        range_since=range_since,
        q=q,
        limit=limit,
        order_desc=order_desc,
    )

    async with eng.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()

    out: list[dict[str, Any]] = []
    for r in rows:
        meta = r[2] or {}
        body = (meta.get("body") if isinstance(meta, dict) else None) or {}
        # preview — body 의 첫 textual 필드 80 char.
        preview: str | None = None
        for cand in ("note", "summary", "title", "description", "amount"):
            v = body.get(cand) if isinstance(body, dict) else None
            if isinstance(v, str) and v.strip():
                preview = v.strip()[:80]
                break
        if preview is None and isinstance(r[1], str):
            preview = r[1][:80]
        out.append(
            {
                "scope": scope_alias,
                "id": str(r[0]),
                "title": r[1],
                "preview": preview,
                "created_at": r[3].isoformat() if r[3] else None,
                "owner_agent_id": str(r[4]) if r[4] else None,
                "agent_name": r[5] if r[5] else None,
                "agent_is_active": (
                    bool(r[6]) if r[6] is not None else None
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/global-view", response_model=GlobalViewResponse)
async def global_view(
    scope: str = Query("all"),
    agent_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    order: str = Query("desc"),
    range: str = Query("all"),  # noqa: A002 (FastAPI param name)
    q: str | None = Query(None, max_length=200),
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> GlobalViewResponse:
    """admin/owner 의 통합 view — tenant 안 모든 agent 의 schedule/memo/
    expense/diary/reminder 통합 list.

    static whitelist:
      - scope ∈ {schedule, memo, expense, diary, reminder, all}
      - order ∈ {desc, asc}
      - range ∈ {today, week, month, all}
    """
    # 1. JWT → aid + tid + role
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)

    # 2. role gate — owner/admin 만
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")

    # 3. static whitelist 검증
    if scope not in _SCOPE_ALIASES:
        raise HTTPException(400, f"invalid scope (allowed: {_SCOPE_ALIASES})")
    if order not in _ORDER_ALIASES:
        raise HTTPException(400, f"invalid order (allowed: {_ORDER_ALIASES})")
    if range not in _RANGE_ALIASES:
        raise HTTPException(400, f"invalid range (allowed: {_RANGE_ALIASES})")

    # 4. agent_id 검증 (있으면 UUID parse)
    agent_id_filter: UUID | None = None
    if agent_id:
        try:
            agent_id_filter = UUID(agent_id)
        except ValueError as e:
            raise HTTPException(400, f"invalid agent_id: {e}") from e

    # 5. range → since 시각
    range_since = _resolve_range(range)

    # 6. scope 별 doctype 결정 (single 또는 all)
    if scope == "all":
        target_scopes = list(_SCOPE_TO_DOCTYPE.items())
    else:
        target_scopes = [(scope, _SCOPE_TO_DOCTYPE[scope])]

    eng = _get_engine()
    order_desc = order == "desc"

    # 7. 병렬 query (all scope 면 5개 doctype 동시).
    tasks = [
        _query_doctype(
            eng,
            tenant_id=tid,
            doctype_name=doctype,
            scope_alias=scope_name,
            agent_id_filter=agent_id_filter,
            range_since=range_since,
            q=q,
            limit=limit,  # per-scope cap; total 은 limit 로 다시 자름.
            order_desc=order_desc,
        )
        for scope_name, doctype in target_scopes
    ]
    results = await asyncio.gather(*tasks)

    # 8. flatten + global limit cap (created_at 정렬 후 자름)
    flat: list[dict[str, Any]] = []
    scope_counts: dict[str, int] = {}
    for scope_name, rows in zip(
        [s for s, _ in target_scopes], results
    ):
        scope_counts[scope_name] = len(rows)
        flat.extend(rows)

    flat.sort(
        key=lambda r: r.get("created_at") or "",
        reverse=order_desc,
    )
    if len(flat) > limit:
        flat = flat[:limit]

    # 9. audit log (별도 transaction OK)
    try:
        record_action(
            tenant_id=tid,
            user_id=aid,
            action="read",
            resource_type="admin_global_view",
            detail={
                "scope": scope,
                "agent_id": str(agent_id_filter) if agent_id_filter else None,
                "range": range,
                "q": q,
                "limit": limit,
                "result_count": len(flat),
            },
        )
    except Exception:  # noqa: BLE001
        pass

    return GlobalViewResponse(
        items=[GlobalViewItem(**r) for r in flat],
        total=len(flat),
        scope_counts=scope_counts,
    )
