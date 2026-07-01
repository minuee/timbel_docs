"""/api/v1/tenants — frontend-v2 호환 tenants 라우터.

frontend-v2 가 호출하는 path:
- ``GET  /api/v1/tenants`` — 현재 user 의 tenant 목록
- ``POST /api/v1/tenants`` — 신규 tenant 생성 (admin / LUCAS_AUTH_DISABLED 만)
- ``GET  /api/v1/tenants/{tenant_id}`` — 단건 조회
- ``PATCH /api/v1/tenants/{tenant_id}`` — name/config 수정 (owner/admin 만)
- ``POST /api/v1/tenants/{tenant_id}/switch`` — 활성 테넌트 전환 (JWT 재발급)
- ``GET  /api/v1/tenants/{tenant_id}/members`` — 멤버 목록

JWT (Bearer) 에서 account_id (sub) 추출. tenant 별 membership 검증.
"""
from __future__ import annotations

import re
import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import (
    InvalidToken,
    create_access_token,
    decode_token,
)
from src.api.dependencies import get_current_principal
from src.common.config import settings


router = APIRouter(prefix="/api/v1/tenants", tags=["tenants-v1"])


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


def _account_from_token(authorization: str) -> tuple[UUID, str | None, str]:
    """Bearer token → (account_id, tenant_id, role). 401 if invalid."""
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
        return UUID(str(sub)), payload.get("tenant_id"), payload.get("role") or "member"
    except ValueError as e:
        raise HTTPException(401, f"invalid subject: {e}") from e


async def _verify_membership(account_id: UUID, tenant_id: UUID) -> str:
    """tenant 의 role 반환. 멤버 아니면 403."""
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT role FROM tenant_memberships "
                    "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
                ),
                {"aid": account_id, "tid": tenant_id},
            )
        ).first()
    if not row:
        raise HTTPException(403, "not a member of this tenant")
    return row[0]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TenantOut(BaseModel):
    id: str
    name: str
    slug: str
    tenant_type: str
    role: str
    is_active: bool
    created_at: str | None = None


class TenantListOut(BaseModel):
    items: list[TenantOut]


class TenantPatch(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None


class TenantCreate(BaseModel):
    """신규 tenant 생성 입력.

    무인증 모드 또는 admin 만 허용 (endpoint 가드).
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Tenant 표시명 (한글/영문 가능)",
        examples=["공공기관 테스트"],
    )
    slug: str | None = Field(
        default=None,
        max_length=100,
        description="비어 있으면 name 에서 자동 생성. 충돌 시 suffix 추가.",
        examples=["public-test"],
    )
    tenant_type: str = Field(
        default="corporate",
        max_length=20,
        description="Tenant 유형 (corporate / personal / public)",
        examples=["corporate"],
    )
    plan: str = Field(
        default="standard",
        max_length=50,
        description="구독 플랜 (standard / pro / enterprise)",
        examples=["standard"],
    )
    description: str | None = Field(
        None,
        description="설명 (선택) — config.description 에 저장",
        examples=["조달청 PoC 테스트용"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "공공기관 테스트",
                    "slug": "public-test",
                    "tenant_type": "corporate",
                    "plan": "standard",
                    "description": "조달청 PoC 테스트용",
                }
            ]
        }
    }


class TenantSwitchOut(BaseModel):
    access_token: str
    tenant_id: str
    role: str


class MemberOut(BaseModel):
    account_id: str
    name: str | None
    email: str | None
    phone: str | None
    role: str


# ---------------------------------------------------------------------------
# Slug 자동 생성 — name 에서 ASCII slug 추출 + 충돌 시 random suffix.
# ---------------------------------------------------------------------------


_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """name → kebab-case slug. 빈 결과 시 random fallback.

    - 소문자화 + 영숫자 외 모두 ``-`` 로 치환
    - 양끝 ``-`` 제거
    - 100 자 제한 (tenants.slug VARCHAR(100))
    - 결과 비어 있으면 ``tenant-<random>`` 으로 fallback (한글-only name 대응).
    """
    base = _SLUG_INVALID.sub("-", name.lower()).strip("-")
    if not base:
        base = f"tenant-{secrets.token_hex(4)}"
    return base[:100]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=TenantListOut,
    summary="내 Tenant 목록",
    description=(
        "현재 사용자가 속한 tenant 전체 목록. tenant_type 우선 정렬 후 name 알파벳 순. "
        "각 항목의 role 은 호출자의 membership 역할 — tenant 전환 (`/switch`) 시 "
        "이 role 이 새 JWT 의 클레임으로 들어간다."
    ),
    responses={200: {"description": "TenantListOut (items 배열)"}},
)
async def list_tenants(authorization: str = Header(...)) -> TenantListOut:
    """현재 사용자가 속한 tenant 전체 목록."""
    account_id, _, _ = _account_from_token(authorization)
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT t.id, t.name, t.slug, t.tenant_type, m.role,
                       t.is_active, t.created_at
                FROM tenant_memberships m
                JOIN tenants t ON m.tenant_id = t.id
                WHERE m.account_id = :aid
                ORDER BY t.tenant_type DESC, t.name
                """
            ),
            {"aid": account_id},
        )
        items = [
            TenantOut(
                id=str(r[0]),
                name=r[1],
                slug=r[2],
                tenant_type=r[3],
                role=r[4],
                is_active=r[5],
                created_at=r[6].isoformat() if r[6] else None,
            )
            for r in rows
        ]
    return TenantListOut(items=items)


@router.post(
    "",
    response_model=TenantOut,
    status_code=201,
    summary="Tenant 신규 생성",
    description=(
        "신규 tenant 를 생성한다.\n\n"
        "**허용 조건** (둘 중 하나):\n"
        "- `LUCAS_AUTH_DISABLED=true` (principal.auth_disabled) — 무인증 모드\n"
        "- `principal.role == 'admin'` — 운영 admin\n\n"
        "**slug 정책**: 미지정 시 name 에서 자동 생성 (소문자 + `-` 변환). "
        "UNIQUE 충돌 시 409 — 호출자가 명시적 slug 로 재시도해야 한다.\n\n"
        "tenants 행만 INSERT — 호출자 자동 membership 부착은 별도 endpoint 호출 필요."
    ),
    responses={
        201: {"description": "생성된 TenantOut"},
        403: {"description": "admin 권한 필요 (무인증 모드 아닌 경우)"},
        409: {"description": "slug 중복 — 명시적 slug 로 재시도"},
        422: {"description": "name 빈 문자열 등 validation 실패"},
    },
)
async def create_tenant(
    body: TenantCreate,
    principal: dict[str, Any] = Depends(get_current_principal),
) -> TenantOut:
    """신규 tenant 생성."""
    is_admin = principal.get("role") == "admin"
    is_auth_disabled = bool(principal.get("auth_disabled"))
    if not (is_admin or is_auth_disabled):
        raise HTTPException(403, "신규 tenant 생성은 admin 권한 필요")

    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name 은 빈 문자열일 수 없습니다.")

    slug = (body.slug or "").strip() or _slugify(name)

    cfg: dict[str, Any] = {}
    if body.description:
        cfg["description"] = body.description

    eng = _get_engine()
    try:
        async with eng.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO tenants (
                            name, slug, config, plan, tenant_type,
                            context_config, feature_flags
                        ) VALUES (
                            :name, :slug, CAST(:cfg AS jsonb), :plan, :ttype,
                            '{}'::jsonb, '{}'::jsonb
                        )
                        RETURNING id, name, slug, tenant_type, is_active, created_at
                        """
                    ),
                    {
                        "name": name,
                        "slug": slug,
                        "cfg": __import__("json").dumps(cfg),
                        "plan": body.plan,
                        "ttype": body.tenant_type,
                    },
                )
            ).first()
    except IntegrityError as e:
        # slug UNIQUE 충돌 — 409. 호출자가 명시적 slug 재시도.
        raise HTTPException(
            409, f"slug 충돌 — 이미 존재 ({slug!r}). 명시적 slug 지정 권장."
        ) from e

    if not row:
        raise HTTPException(500, "tenant 생성 실패 — RETURNING 빈 응답.")

    # role: auth_disabled 모드는 'admin' 으로 부여 (principal 기준).
    role = principal.get("role") or ("admin" if is_auth_disabled else "viewer")
    return TenantOut(
        id=str(row[0]),
        name=row[1],
        slug=row[2],
        tenant_type=row[3],
        role=role,
        is_active=row[4],
        created_at=row[5].isoformat() if row[5] else None,
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantOut,
    summary="Tenant 단건 조회",
    description=(
        "특정 tenant 의 상세 정보 (name/slug/tenant_type/role/is_active) 를 반환. "
        "호출자가 해당 tenant 의 membership 을 가져야 함 (없으면 403). "
        "role 은 tenant_memberships 의 호출자 역할 (owner/admin/member/viewer)."
    ),
    responses={
        200: {"description": "TenantOut"},
        400: {"description": "invalid tenant_id (UUID 형식 오류)"},
        403: {"description": "membership 없음"},
        404: {"description": "tenant 미발견"},
    },
)
async def get_tenant(tenant_id: str, authorization: str = Header(...)) -> TenantOut:
    try:
        tid = UUID(tenant_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e
    account_id, _, _ = _account_from_token(authorization)
    role = await _verify_membership(account_id, tid)
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, name, slug, tenant_type, is_active, created_at "
                    "FROM tenants WHERE id = :tid LIMIT 1"
                ),
                {"tid": tid},
            )
        ).first()
    if not row:
        raise HTTPException(404, "tenant not found")
    return TenantOut(
        id=str(row[0]),
        name=row[1],
        slug=row[2],
        tenant_type=row[3],
        role=role,
        is_active=row[4],
        created_at=row[5].isoformat() if row[5] else None,
    )


@router.patch(
    "/{tenant_id}",
    response_model=TenantOut,
    summary="Tenant 수정",
    description=(
        "tenant 의 name / config 를 수정한다. None 으로 전달된 필드는 기존 값 유지. "
        "owner 또는 admin 역할만 호출 가능. config 는 JSONB 로 통째 저장 — "
        "부분 머지 X (병합 필요 시 GET → 머지 → PATCH 패턴 권장)."
    ),
    responses={
        200: {"description": "수정된 TenantOut"},
        400: {"description": "invalid tenant_id"},
        403: {"description": "owner/admin 권한 필요"},
    },
)
async def update_tenant(
    tenant_id: str, body: TenantPatch, authorization: str = Header(...)
) -> TenantOut:
    try:
        tid = UUID(tenant_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e
    account_id, _, _ = _account_from_token(authorization)
    role = await _verify_membership(account_id, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    eng = _get_engine()
    async with eng.begin() as conn:
        # 어느 쪽이 None 이면 기존 값 유지.
        await conn.execute(
            text(
                """
                UPDATE tenants
                SET name = COALESCE(:name, name),
                    config = COALESCE(CAST(:cfg AS jsonb), config),
                    updated_at = now()
                WHERE id = :tid
                """
            ),
            {
                "name": body.name,
                "cfg": None if body.config is None else __import__("json").dumps(body.config),
                "tid": tid,
            },
        )
    return await get_tenant(tenant_id=tenant_id, authorization=authorization)


@router.post(
    "/{tenant_id}/switch",
    response_model=TenantSwitchOut,
    summary="활성 Tenant 전환",
    description=(
        "활성 tenant 를 변경하고 새 JWT access_token 을 발급한다. "
        "새 토큰의 `tenant_id` 클레임 = 전환 대상, `role` 클레임 = 해당 tenant 의 "
        "membership 역할. 호출자는 대상 tenant 의 멤버여야 한다 (없으면 403). "
        "발급된 토큰을 다음 요청부터 `Authorization` 헤더에 사용하면 된다."
    ),
    responses={
        200: {"description": "새 access_token + tenant_id + role"},
        400: {"description": "invalid tenant_id"},
        403: {"description": "membership 없음"},
    },
)
async def switch_tenant(
    tenant_id: str, authorization: str = Header(...)
) -> TenantSwitchOut:
    """활성 테넌트 변경 — 새 access_token (tenant_id 클레임 갱신) 발급."""
    try:
        tid = UUID(tenant_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e
    account_id, _, _ = _account_from_token(authorization)
    role = await _verify_membership(account_id, tid)
    new_token = create_access_token(
        subject=str(account_id), tenant_id=str(tid), role=role
    )
    return TenantSwitchOut(access_token=new_token, tenant_id=str(tid), role=role)


@router.get(
    "/{tenant_id}/members",
    summary="Tenant 멤버 목록",
    description=(
        "tenant 에 속한 사용자 (account) 와 각자의 role 을 반환한다. "
        "membership 보유자만 조회 가능. role 별 (owner > admin > member > viewer) "
        "정렬 후 name 알파벳 순. 응답은 `{ items: [MemberOut, ...] }` 형태."
    ),
    responses={
        200: {"description": "멤버 배열"},
        400: {"description": "invalid tenant_id"},
        403: {"description": "membership 없음"},
    },
)
async def list_members(
    tenant_id: str, authorization: str = Header(...)
) -> dict[str, list[MemberOut]]:
    try:
        tid = UUID(tenant_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e
    account_id, _, _ = _account_from_token(authorization)
    await _verify_membership(account_id, tid)
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT a.id, a.name, a.email, a.phone, m.role
                FROM tenant_memberships m
                JOIN accounts a ON m.account_id = a.id
                WHERE m.tenant_id = :tid
                ORDER BY m.role, a.name
                """
            ),
            {"tid": tid},
        )
        items = [
            MemberOut(
                account_id=str(r[0]),
                name=r[1],
                email=r[2],
                phone=r[3],
                role=r[4],
            )
            for r in rows
        ]
    return {"items": items}
