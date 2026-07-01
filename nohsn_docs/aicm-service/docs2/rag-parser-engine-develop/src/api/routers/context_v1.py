"""/api/v1/context — frontend-v2 호환 개인/조직 컨텍스트 CRUD.

frontend 호출:
- life: GET/POST /context/life, PUT/DELETE /context/life/{id}
- corporate: GET/POST /context/corporate, PUT/DELETE /context/corporate/{id},
  GET /context/corporate/scope

Phase P1.5. account 1명당 N (life), tenant 1개당 N (corporate).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings


router = APIRouter(prefix="/api/v1/context", tags=["context-v1"])


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


def _scope(authorization: str, x_tenant_id: str | None) -> tuple[UUID, UUID | None, str]:
    """(account_id, tenant_id?, role). JWT tenant claim authoritative.

    Phase 1.5A Task 8c.2 (2026-05-07): 이전 ``x_tenant_id or payload.get("tenant_id")``
    패턴은 cross-tenant 위장 가능. ``_tenant_scope.resolve_tenant_id`` 사용 —
    헤더 mismatch → 401. tenant_id 가 JWT 에 없으면 None 으로 폴백 (기존 동작).
    """
    from src.api.routers._tenant_scope import resolve_tenant_id

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        payload = decode_token(authorization[7:].strip())
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    sub = payload.get("sub")
    role = payload.get("role") or "member"
    if not sub:
        raise HTTPException(401, "missing subject")
    # JWT claim 부재 시: 헤더가 있으면 mismatch → 401; 없으면 None tid 로 폴백.
    if payload.get("tenant_id"):
        tid_str: str | None = resolve_tenant_id(payload, x_tenant_id)
    else:
        # claim 없음. 헤더로 tenant 주장은 거부 (헤더 = JWT 만 허용 정책).
        if x_tenant_id is not None and x_tenant_id != "":
            raise HTTPException(401, "tenant claim mismatch")
        tid_str = None
    try:
        aid = UUID(str(sub))
        tid = UUID(str(tid_str)) if tid_str else None
    except ValueError as e:
        raise HTTPException(400, f"invalid uuid: {e}") from e
    return aid, tid, role


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ContextItemIn(BaseModel):
    title: str
    content: str = ""
    category: str | None = None  # life only
    scope: str | None = None     # corporate only
    metadata: dict[str, Any] | None = None


class ContextItemOut(BaseModel):
    id: str
    title: str
    content: str
    category: str | None = None
    scope: str | None = None
    metadata: dict[str, Any]
    created_at: str | None
    updated_at: str | None


# ---------------------------------------------------------------------------
# /context/life CRUD
# ---------------------------------------------------------------------------


@router.get("/life")
async def list_life(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    aid, _, _ = _scope(authorization, x_tenant_id)
    db = _get_engine()
    async with db.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, title, content, category, metadata,
                           created_at, updated_at
                    FROM user_life_context
                    WHERE account_id = :aid
                    ORDER BY updated_at DESC
                    """
                ),
                {"aid": aid},
            )
        ).all()
    items = [
        ContextItemOut(
            id=str(r[0]),
            title=r[1],
            content=r[2],
            category=r[3],
            metadata=r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {}),
            created_at=r[5].isoformat() if r[5] else None,
            updated_at=r[6].isoformat() if r[6] else None,
        ).model_dump()
        for r in rows
    ]
    return {"items": items}


@router.post("/life", response_model=ContextItemOut)
async def create_life(
    body: ContextItemIn,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ContextItemOut:
    aid, _, _ = _scope(authorization, x_tenant_id)
    db = _get_engine()
    async with db.begin() as conn:
        row = await conn.execute(
            text(
                """
                INSERT INTO user_life_context
                  (account_id, category, title, content, metadata)
                VALUES
                  (:aid, COALESCE(:cat, 'general'), :title, :content,
                   CAST(:meta AS jsonb))
                RETURNING id, created_at, updated_at
                """
            ),
            {
                "aid": aid,
                "cat": body.category,
                "title": body.title,
                "content": body.content,
                "meta": json.dumps(body.metadata or {}),
            },
        )
        rid, ca, ua = row.first()
    return ContextItemOut(
        id=str(rid),
        title=body.title,
        content=body.content,
        category=body.category or "general",
        metadata=body.metadata or {},
        created_at=ca.isoformat() if ca else None,
        updated_at=ua.isoformat() if ua else None,
    )


@router.put("/life/{item_id}", response_model=ContextItemOut)
async def update_life(
    item_id: str,
    body: ContextItemIn,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ContextItemOut:
    aid, _, _ = _scope(authorization, x_tenant_id)
    try:
        iid = UUID(item_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid item_id: {e}") from e
    db = _get_engine()
    async with db.begin() as conn:
        r = await conn.execute(
            text(
                """
                UPDATE user_life_context
                SET title = :title,
                    content = :content,
                    category = COALESCE(:cat, category),
                    metadata = CAST(:meta AS jsonb),
                    updated_at = now()
                WHERE id = :iid AND account_id = :aid
                RETURNING id, title, content, category, metadata,
                          created_at, updated_at
                """
            ),
            {
                "iid": iid,
                "aid": aid,
                "title": body.title,
                "content": body.content,
                "cat": body.category,
                "meta": json.dumps(body.metadata or {}),
            },
        )
        row = r.first()
        if not row:
            raise HTTPException(404, "context item not found")
    return ContextItemOut(
        id=str(row[0]),
        title=row[1],
        content=row[2],
        category=row[3],
        metadata=row[4] if isinstance(row[4], dict) else (json.loads(row[4]) if row[4] else {}),
        created_at=row[5].isoformat() if row[5] else None,
        updated_at=row[6].isoformat() if row[6] else None,
    )


@router.delete("/life/{item_id}")
async def delete_life(
    item_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    aid, _, _ = _scope(authorization, x_tenant_id)
    try:
        iid = UUID(item_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid item_id: {e}") from e
    db = _get_engine()
    async with db.begin() as conn:
        r = await conn.execute(
            text(
                "DELETE FROM user_life_context "
                "WHERE id = :iid AND account_id = :aid"
            ),
            {"iid": iid, "aid": aid},
        )
    if (r.rowcount or 0) == 0:
        raise HTTPException(404, "context item not found")
    return {"ok": True, "id": item_id}


# ---------------------------------------------------------------------------
# /context/corporate CRUD
# ---------------------------------------------------------------------------


@router.get("/corporate")
async def list_corporate(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    aid, tid, _ = _scope(authorization, x_tenant_id)
    if tid is None:
        raise HTTPException(400, "tenant scope required")
    db = _get_engine()
    async with db.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, title, content, scope, metadata,
                           created_at, updated_at
                    FROM user_corporate_context
                    WHERE tenant_id = :tid
                    ORDER BY updated_at DESC
                    """
                ),
                {"tid": tid},
            )
        ).all()
    items = [
        ContextItemOut(
            id=str(r[0]),
            title=r[1],
            content=r[2],
            scope=r[3],
            metadata=r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {}),
            created_at=r[5].isoformat() if r[5] else None,
            updated_at=r[6].isoformat() if r[6] else None,
        ).model_dump()
        for r in rows
    ]
    return {"items": items}


@router.get("/corporate/scope")
async def corporate_scope(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """frontend 가 요청하는 scope 옵션 목록."""
    _scope(authorization, x_tenant_id)
    return {
        "scopes": [
            {"key": "general", "label": "전체"},
            {"key": "policy", "label": "정책/규정"},
            {"key": "domain", "label": "도메인 지식"},
            {"key": "team", "label": "팀 정보"},
            {"key": "product", "label": "제품 정보"},
        ],
    }


@router.post("/corporate", response_model=ContextItemOut)
async def create_corporate(
    body: ContextItemIn,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ContextItemOut:
    aid, tid, role = _scope(authorization, x_tenant_id)
    if tid is None:
        raise HTTPException(400, "tenant scope required")
    db = _get_engine()
    async with db.begin() as conn:
        # 멤버 검증
        r = (
            await conn.execute(
                text(
                    "SELECT 1 FROM tenant_memberships "
                    "WHERE account_id = :aid AND tenant_id = :tid"
                ),
                {"aid": aid, "tid": tid},
            )
        ).first()
        if not r:
            raise HTTPException(403, "not a member of this tenant")
        row = await conn.execute(
            text(
                """
                INSERT INTO user_corporate_context
                  (tenant_id, scope, title, content, metadata)
                VALUES
                  (:tid, COALESCE(:scope, 'general'), :title, :content,
                   CAST(:meta AS jsonb))
                RETURNING id, created_at, updated_at
                """
            ),
            {
                "tid": tid,
                "scope": body.scope,
                "title": body.title,
                "content": body.content,
                "meta": json.dumps(body.metadata or {}),
            },
        )
        rid, ca, ua = row.first()
    return ContextItemOut(
        id=str(rid),
        title=body.title,
        content=body.content,
        scope=body.scope or "general",
        metadata=body.metadata or {},
        created_at=ca.isoformat() if ca else None,
        updated_at=ua.isoformat() if ua else None,
    )


@router.put("/corporate/{item_id}", response_model=ContextItemOut)
async def update_corporate(
    item_id: str,
    body: ContextItemIn,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ContextItemOut:
    aid, tid, _ = _scope(authorization, x_tenant_id)
    if tid is None:
        raise HTTPException(400, "tenant scope required")
    try:
        iid = UUID(item_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid item_id: {e}") from e
    db = _get_engine()
    async with db.begin() as conn:
        r = await conn.execute(
            text(
                """
                UPDATE user_corporate_context
                SET title = :title,
                    content = :content,
                    scope = COALESCE(:scope, scope),
                    metadata = CAST(:meta AS jsonb),
                    updated_at = now()
                WHERE id = :iid AND tenant_id = :tid
                RETURNING id, title, content, scope, metadata,
                          created_at, updated_at
                """
            ),
            {
                "iid": iid,
                "tid": tid,
                "title": body.title,
                "content": body.content,
                "scope": body.scope,
                "meta": json.dumps(body.metadata or {}),
            },
        )
        row = r.first()
        if not row:
            raise HTTPException(404, "context item not found")
    return ContextItemOut(
        id=str(row[0]),
        title=row[1],
        content=row[2],
        scope=row[3],
        metadata=row[4] if isinstance(row[4], dict) else (json.loads(row[4]) if row[4] else {}),
        created_at=row[5].isoformat() if row[5] else None,
        updated_at=row[6].isoformat() if row[6] else None,
    )


@router.delete("/corporate/{item_id}")
async def delete_corporate(
    item_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    aid, tid, _ = _scope(authorization, x_tenant_id)
    if tid is None:
        raise HTTPException(400, "tenant scope required")
    try:
        iid = UUID(item_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid item_id: {e}") from e
    db = _get_engine()
    async with db.begin() as conn:
        r = await conn.execute(
            text(
                "DELETE FROM user_corporate_context "
                "WHERE id = :iid AND tenant_id = :tid"
            ),
            {"iid": iid, "tid": tid},
        )
    if (r.rowcount or 0) == 0:
        raise HTTPException(404, "context item not found")
    return {"ok": True, "id": item_id}
