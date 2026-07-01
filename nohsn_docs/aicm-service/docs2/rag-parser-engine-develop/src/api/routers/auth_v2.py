"""Auth v2 — email/password + JWT 엔드포인트.

Phase 9 (KMS-Plus). 기존 ``/auth/login`` (phone-only, opaque session_token) 와 공존.

엔드포인트:
- ``POST /auth/v2/signup`` — email + password 로 새 account 생성 + JWT pair 발급.
- ``POST /auth/v2/login``  — email + password verify → JWT pair.
- ``POST /auth/v2/refresh`` — refresh token → 새 access token.
- ``GET  /auth/v2/me``     — Bearer access → user/tenant/role 반환.

설계 메모:
- ``accounts`` 테이블은 phone 이 NOT NULL 이므로 signup 시 ``email`` 을 phone 으로
  도 채운다 (UNIQUE 충돌 방지하려고 ``email:`` prefix 추가). 추후 phone 분리 마이그
  레이션 시 별도 처리.
- legacy account (phone-only, password_hash IS NULL) 는 v2 로그인 X — 명확한
  401 ``no password set`` 응답.
- v2 signup 은 personal tenant 자동 생성 (v1 ``get_or_create_account`` 와 동일).
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import (
    InvalidToken,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth/v2", tags=["auth-v2"])


# ---------------------------------------------------------------------------
# DB engine — accounts.py 의 _get_engine() 와 별개로 자체 lazy singleton.
# 테스트는 _reset_engine_for_tests() 로 재생성 가능.
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email_str(v: str) -> str:
    s = (v or "").strip().lower()
    if not _EMAIL_RE.match(s):
        raise ValueError("invalid email format")
    if len(s) > 320:
        raise ValueError("email too long")
    return s


# 가입 시 선택 가능한 group — admin / company / business 는 별도 endpoint.
# - personal: 모든 사용자 default. 단독 personal_tenant 안 데이터.
# - sole_proprietor: 개인 사업자 (1인 미용실 등). personal_tenant 안 scope_group
#   으로 데이터 분리, 별개 tenant 생성 X.
# 회사(company) / 사업체(business) 는 본인이 대표일 때 가입 후 별도 활성화
# endpoint (T3) 로 추가 — 별도 tenant 생성 + M:N 멤버십.
SIGNUP_ALLOWED_GROUPS = {"personal", "sole_proprietor"}


class SignupBody(BaseModel):
    email: str
    password: str = Field(..., min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=100)
    groups: list[str] = Field(
        default_factory=lambda: ["personal"],
        description="사용자가 가입 시 활성화할 그룹. personal / sole_proprietor.",
    )

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        return _validate_email_str(v)

    @field_validator("groups")
    @classmethod
    def _v_groups(cls, v: list[str]) -> list[str]:
        if not v:
            return ["personal"]
        seen: list[str] = []
        for g in v:
            g_norm = str(g).strip().lower()
            if g_norm not in SIGNUP_ALLOWED_GROUPS:
                raise ValueError(
                    f"invalid signup group '{g}' — allowed: "
                    f"{sorted(SIGNUP_ALLOWED_GROUPS)}. company/business 는 "
                    "별도 활성화 endpoint 사용."
                )
            if g_norm not in seen:
                seen.append(g_norm)
        # personal 은 항상 포함 — 사용자 단독 데이터 풀 보장.
        if "personal" not in seen:
            seen.insert(0, "personal")
        return seen


class LoginBody(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        return _validate_email_str(v)


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class AccessOnly(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: str
    email: str | None
    tenant_id: str | None
    role: str
    name: str | None = None
    display_name: str | None = None
    preferences: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synthetic_phone_for_email(email: str) -> str:
    """``accounts.phone`` 은 NOT NULL UNIQUE — email-only signup 용 placeholder.

    형식: ``email:<sanitized>`` — 32 자 제한 안에 들도록 hash fallback.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_.@-]", "_", email.lower())
    candidate = f"e:{sanitized}"
    if len(candidate) > 32:
        # phone 은 String(32) — 너무 길면 hash 8자로 축약.
        import hashlib

        h = hashlib.sha1(email.lower().encode()).hexdigest()[:8]
        candidate = f"e:{h}"
    return candidate


async def _create_account_with_email(
    conn,
    email: str,
    password_hash: str,
    name: str | None,
    groups: list[str] | None = None,
) -> tuple[UUID, UUID]:
    """email + password 로 새 account + personal_tenant + 그룹 멤버십 생성.

    ``groups`` 의 모든 값은 personal_tenant 안 scope_group 으로 매핑 — 1인
    사업자(sole_proprietor) 도 별개 tenant 가 아닌 같은 personal_tenant 안
    scope 만 분리. company / business 는 가입 흐름에서 받지 않음 (별도 활성화
    endpoint).

    Returns (account_id, personal_tenant_id).
    """
    import json as _json

    user_groups = list(groups) if groups else ["personal"]
    if "personal" not in user_groups:
        user_groups.insert(0, "personal")

    tenant_name = (name or email.split("@")[0]) + " 개인"
    tenant_slug = f"personal_e_{re.sub(r'[^a-zA-Z0-9]', '', email.lower())[:40]}"
    tr = await conn.execute(
        text(
            """
            INSERT INTO tenants
              (id, slug, name, tenant_type, plan, config, context_config, is_active)
            VALUES
              (gen_random_uuid(), :slug, :name, 'personal', 'free',
               '{}'::jsonb, '{}'::jsonb, true)
            RETURNING id
            """
        ),
        {"slug": tenant_slug, "name": tenant_name},
    )
    tenant_id: UUID = tr.scalar_one()

    phone = _synthetic_phone_for_email(email)
    ar = await conn.execute(
        text(
            """
            INSERT INTO accounts
              (id, phone, email, name, personal_tenant_id, password_hash,
               email_verified, is_active, preferences)
            VALUES
              (gen_random_uuid(), :phone, :email, :name, :tid, :pwd,
               false, true, CAST(:prefs AS JSONB))
            RETURNING id
            """
        ),
        {
            "phone": phone,
            "email": email,
            "name": name,
            "tid": tenant_id,
            "pwd": password_hash,
            "prefs": _json.dumps({"user_groups": user_groups}),
        },
    )
    account_id: UUID = ar.scalar_one()

    # tenant_memberships — 기존 호환 유지 (personal owner 1건).
    await conn.execute(
        text(
            """
            INSERT INTO tenant_memberships (id, account_id, tenant_id, role)
            VALUES (gen_random_uuid(), :aid, :tid, 'owner')
            """
        ),
        {"aid": account_id, "tid": tenant_id},
    )

    # account_tenants — personal scope 멤버십 1건. sole_proprietor 는 같은
    # tenant 안 데이터 row 의 scope_group 컬럼으로만 표현, 별도 멤버십 row 없음.
    await conn.execute(
        text(
            """
            INSERT INTO account_tenants
              (account_id, tenant_id, scope_group, role)
            VALUES (:aid, :tid, 'personal', 'owner')
            ON CONFLICT (account_id, tenant_id, scope_group) DO NOTHING
            """
        ),
        {"aid": account_id, "tid": tenant_id},
    )

    return account_id, tenant_id


def _issue_pair(*, account_id: str, tenant_id: str | None, role: str) -> tuple[str, str]:
    return (
        create_access_token(subject=account_id, tenant_id=tenant_id, role=role),
        create_refresh_token(account_id),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=TokenPair)
async def signup(body: SignupBody) -> TokenPair:
    """email + password 로 신규 가입. 동일 email 재사용은 409."""
    from sqlalchemy.exc import IntegrityError

    eng = _get_engine()
    try:
        async with eng.begin() as conn:
            # 중복 email — active 만 검사 (race window 존재 — 동시 가입 시
            # IntegrityError 로 재포착해 409 변환).
            existing = (
                await conn.execute(
                    text(
                        "SELECT id FROM accounts WHERE email = :email "
                        "AND is_active = true LIMIT 1"
                    ),
                    {"email": body.email},
                )
            ).first()
            if existing:
                raise HTTPException(409, "email already registered")
            pwd_hash = hash_password(body.password)
            account_id, tenant_id = await _create_account_with_email(
                conn,
                email=body.email,
                password_hash=pwd_hash,
                name=body.name,
                groups=body.groups,
            )
    except IntegrityError as e:
        # accounts.phone / accounts.email unique violation — 동시 가입 race.
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg:
            raise HTTPException(409, "email already registered") from e
        raise
    role = "owner"  # signup 한 사용자는 본인의 personal tenant owner.
    access, refresh = _issue_pair(
        account_id=str(account_id), tenant_id=str(tenant_id), role=role
    )
    log.info(
        "auth_v2_signup",
        account_id=str(account_id),
        email_hash=hash(body.email) & 0xFFFF,
        groups=body.groups,
    )
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        user={
            "id": str(account_id),
            "email": body.email,
            "tenant_id": str(tenant_id),
            "role": role,
            "name": body.name,
            "groups": body.groups,
        },
    )


@router.post("/login", response_model=TokenPair)
async def login(body: LoginBody) -> TokenPair:
    """email + password verify → JWT pair.

    실패 시 401 — 이메일 존재 여부는 노출하지 않음 (timing 차이는 별도 mitigation 필요).
    """
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT a.id, a.email, a.name, a.personal_tenant_id,
                           a.password_hash, a.is_active,
                           m.role
                      FROM accounts a
                      LEFT JOIN tenant_memberships m
                             ON m.account_id = a.id
                            AND m.tenant_id = a.personal_tenant_id
                     WHERE a.email = :email
                     LIMIT 1
                    """
                ),
                {"email": body.email},
            )
        ).first()
    if not row:
        raise HTTPException(401, "invalid credentials")
    account_id, email, name, tenant_id, pwd_hash, is_active, role = row
    if not is_active:
        raise HTTPException(401, "account disabled")
    if not pwd_hash:
        raise HTTPException(401, "no password set (legacy account — use /auth/login)")
    if not verify_password(body.password, pwd_hash):
        raise HTTPException(401, "invalid credentials")
    role = role or "owner"
    access, refresh = _issue_pair(
        account_id=str(account_id),
        tenant_id=str(tenant_id) if tenant_id else None,
        role=role,
    )
    log.info("auth_v2_login", account_id=str(account_id))
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        user={
            "id": str(account_id),
            "email": email,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "role": role,
            "name": name,
        },
    )


@router.post("/refresh", response_model=AccessOnly)
async def refresh(body: RefreshBody) -> AccessOnly:
    """refresh token → 새 access token.

    refresh 자체는 회전 (rotation) 하지 않는다 — 후속 보안 강화 단계에서 도입.
    """
    try:
        payload = decode_token(body.refresh_token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid refresh token: {e}") from e
    if payload.get("type") != "refresh":
        raise HTTPException(401, "not a refresh token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "refresh token missing subject")

    # tenant/role 은 DB 재조회로 최신 상태 반영.
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT a.personal_tenant_id, a.is_active, m.role
                      FROM accounts a
                      LEFT JOIN tenant_memberships m
                             ON m.account_id = a.id
                            AND m.tenant_id = a.personal_tenant_id
                     WHERE a.id = :aid
                     LIMIT 1
                    """
                ),
                {"aid": sub},
            )
        ).first()
    if not row:
        raise HTTPException(401, "account not found")
    tenant_id, is_active, role = row
    if not is_active:
        raise HTTPException(401, "account disabled")
    new_access = create_access_token(
        subject=str(sub),
        tenant_id=str(tenant_id) if tenant_id else None,
        role=role or "owner",
    )
    return AccessOnly(access_token=new_access)


@router.get("/me", response_model=MeResponse)
async def me(authorization: str = Header(...)) -> MeResponse:
    """현재 access token 의 user 정보 반환."""
    if not authorization.startswith("Bearer "):
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

    # email/name/display_name/preferences 는 DB 에서 최신 fetch.
    # display_name + preferences 는 마이그레이션 039 이전 환경 호환 위해
    # 컬럼 부재 시 graceful degrade.
    eng = _get_engine()
    email: str | None = None
    name: str | None = None
    display_name: str | None = None
    preferences: dict[str, Any] = {}
    async with eng.begin() as conn:
        try:
            row = (
                await conn.execute(
                    text(
                        "SELECT email, name, display_name, preferences "
                        "FROM accounts WHERE id = :aid LIMIT 1"
                    ),
                    {"aid": sub},
                )
            ).first()
            if row:
                email, name, display_name, preferences = row
                preferences = dict(preferences or {})
        except Exception:
            # 마이그레이션 미적용 환경 fallback.
            row = (
                await conn.execute(
                    text("SELECT email, name FROM accounts WHERE id = :aid LIMIT 1"),
                    {"aid": sub},
                )
            ).first()
            if row:
                email, name = row

    return MeResponse(
        user_id=str(sub),
        email=email,
        tenant_id=payload.get("tenant_id"),
        role=payload.get("role", "viewer"),
        name=name,
        display_name=display_name,
        preferences=preferences,
    )
