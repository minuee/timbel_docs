"""Account groups — company / business 추가 활성화 + 비활성화.

배경
----
회원가입 시 사용자는 personal / sole_proprietor 그룹만 선택. 회사(company) 또는
사업체(business) 는 본인이 대표일 때 별도 활성화 endpoint 로 추가:

- ``POST /api/v1/account/groups`` — 신규 company / business 활성화. 새 tenant
  생성 + ``account_tenants`` 멤버십 row(scope_group=group, role='owner') 추가
  + ``preferences.user_groups`` 동기화.
- ``DELETE /api/v1/account/groups/{tenant_id}`` — 비활성화. 멤버십
  ``is_active=false`` (데이터 row 는 보존). 같은 그룹의 다른 활성 멤버십이
  없으면 ``preferences.user_groups`` 에서도 그룹 제거.
- ``GET /api/v1/account/groups`` — 본인이 활성 멤버십을 가진 모든 tenant 목록.

design rules
- ``personal`` scope 는 가입 시 자동 추가 — 본 endpoint 로 추가/제거 불가.
- ``sole_proprietor`` 는 별개 tenant 가 아님 — preferences 에만 토글 (별도
  endpoint 또는 기존 settings 로 처리, 본 모듈은 tenant 분리가 필요한 그룹만).
- 한 사용자가 같은 그룹에 N개 tenant 가입 가능 (예: 회사 A + 회사 B 동시
  소유). 단 동일 (account, tenant, group) 중복은 unique 제약으로 차단.
"""
from __future__ import annotations

import json as _json
import re
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/account/groups", tags=["계정 그룹"])


# 본 endpoint 가 다루는 그룹 — tenant 분리가 필요한 사업체 단위만.
ACTIVATABLE_GROUPS = {"company", "business"}

# personal_tenant 안의 sub-scope 토글 가능 그룹 — 별개 tenant 안 만듦.
# personal 은 가입 시 결정되어 잠금, admin 은 시스템 영역.
TOGGLEABLE_SCOPES = {"sole_proprietor"}


# ---------------------------------------------------------------------------
# DB engine — account_settings.py 와 동일 패턴.
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
# Auth helper.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Schemas.
# ---------------------------------------------------------------------------


class ActivateBody(BaseModel):
    group: str = Field(..., description="company 또는 business")
    tenant_name: str = Field(..., min_length=1, max_length=200)
    tenant_slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("group")
    @classmethod
    def _v_group(cls, v: str) -> str:
        g = v.strip().lower()
        if g not in ACTIVATABLE_GROUPS:
            raise ValueError(
                f"group '{v}' not activatable here — allowed: "
                f"{sorted(ACTIVATABLE_GROUPS)}"
            )
        return g


class GroupMembership(BaseModel):
    tenant_id: str
    name: str
    slug: str
    tenant_type: str
    role: str
    scope_group: str
    is_active: bool


class GroupListResponse(BaseModel):
    memberships: list[GroupMembership]
    user_groups: list[str]


class ActivateResponse(BaseModel):
    membership: GroupMembership
    user_groups: list[str]


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _slugify(value: str, fallback: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.lower()).strip("_")
    if not s:
        s = fallback
    return s[:60]


async def _user_groups(conn, account_id: str) -> list[str]:
    row = (
        await conn.execute(
            text("SELECT preferences FROM accounts WHERE id = :aid"),
            {"aid": account_id},
        )
    ).first()
    if row is None:
        raise HTTPException(404, "account not found")
    prefs = dict(row[0] or {})
    raw = prefs.get("user_groups")
    if isinstance(raw, list):
        return [str(g) for g in raw]
    return []


async def _set_user_groups(conn, account_id: str, groups: list[str]) -> None:
    """preferences.user_groups 갱신 — 다른 키는 보존."""
    row = (
        await conn.execute(
            text("SELECT preferences FROM accounts WHERE id = :aid"),
            {"aid": account_id},
        )
    ).first()
    prefs = dict(row[0] or {}) if row else {}
    # 순서 안정화 — admin 먼저 / personal / sole_proprietor / company / business.
    order = ["admin", "personal", "sole_proprietor", "company", "business"]
    sorted_groups = sorted(set(groups), key=lambda g: order.index(g) if g in order else 99)
    prefs["user_groups"] = sorted_groups
    await conn.execute(
        text(
            """
            UPDATE accounts
               SET preferences = CAST(:p AS JSONB),
                   updated_at = NOW()
             WHERE id = :aid
            """
        ),
        {"p": _json.dumps(prefs), "aid": account_id},
    )


# ---------------------------------------------------------------------------
# Endpoints.
# ---------------------------------------------------------------------------


@router.get("", response_model=GroupListResponse)
async def list_groups(authorization: str = Header(...)) -> GroupListResponse:
    """본인의 모든 활성 멤버십 + 현재 user_groups 반환."""
    account_id = _account_id_from_bearer(authorization)
    eng = _get_engine()
    async with eng.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT t.id::text, t.name, t.slug, t.tenant_type,
                           at.role, at.scope_group, at.is_active
                      FROM account_tenants at
                      JOIN tenants t ON t.id = at.tenant_id
                     WHERE at.account_id = :aid
                       AND at.is_active = TRUE
                       AND t.is_active = TRUE
                     ORDER BY at.scope_group, t.name
                    """
                ),
                {"aid": account_id},
            )
        ).all()
        groups = await _user_groups(conn, account_id)

    memberships = [
        GroupMembership(
            tenant_id=r[0],
            name=r[1],
            slug=r[2],
            tenant_type=r[3],
            role=r[4],
            scope_group=r[5],
            is_active=r[6],
        )
        for r in rows
    ]
    return GroupListResponse(memberships=memberships, user_groups=groups)


@router.post("", response_model=ActivateResponse, status_code=201)
async def activate_group(
    body: ActivateBody,
    authorization: str = Header(...),
) -> ActivateResponse:
    """company / business 신규 활성화 — 본인이 대표인 새 사업체 가입.

    동일 ``tenant_slug`` 가 이미 존재하면 409. ``account_tenants`` unique
    제약으로 동일 (account, tenant, group) 중복도 409.
    """
    account_id = _account_id_from_bearer(authorization)

    base_slug = body.tenant_slug or _slugify(
        f"{body.group}_{body.tenant_name}", fallback=body.group
    )
    # account 별 충돌 회피 — slug 끝에 short uuid 부여 (사용자 직접 명시 시 그대로).
    if not body.tenant_slug:
        suffix = uuid.uuid4().hex[:6]
        slug = f"{base_slug}_{suffix}"[:60]
    else:
        slug = base_slug

    eng = _get_engine()
    async with eng.begin() as conn:
        # tenant slug 중복 체크.
        dup = (
            await conn.execute(
                text("SELECT id FROM tenants WHERE slug = :s LIMIT 1"),
                {"s": slug},
            )
        ).first()
        if dup is not None:
            raise HTTPException(409, f"tenant slug '{slug}' already taken")

        # 새 tenant 생성.
        config = {"description": body.description} if body.description else {}
        tr = await conn.execute(
            text(
                """
                INSERT INTO tenants
                  (id, slug, name, tenant_type, plan, config, context_config, is_active)
                VALUES
                  (gen_random_uuid(), :slug, :name, :ttype, 'free',
                   CAST(:config AS JSONB), '{}'::jsonb, true)
                RETURNING id
                """
            ),
            {
                "slug": slug,
                "name": body.tenant_name,
                "ttype": body.group,
                "config": _json.dumps(config),
            },
        )
        tenant_id: uuid.UUID = tr.scalar_one()

        # account_tenants 멤버십.
        await conn.execute(
            text(
                """
                INSERT INTO account_tenants
                  (account_id, tenant_id, scope_group, role)
                VALUES (:aid, :tid, :sg, 'owner')
                """
            ),
            {"aid": account_id, "tid": tenant_id, "sg": body.group},
        )

        # tenant_memberships — 기존 다른 코드 호환 (members 조회 시 사용).
        await conn.execute(
            text(
                """
                INSERT INTO tenant_memberships (id, account_id, tenant_id, role)
                VALUES (gen_random_uuid(), :aid, :tid, 'owner')
                """
            ),
            {"aid": account_id, "tid": tenant_id},
        )

        # user_groups 갱신 — legacy 사용자(preferences NULL/공백) 라도 personal
        # 그룹은 항상 보존. account_tenants 의 active 멤버십에서 seed 해 드러난
        # scope 도 함께 유지.
        existing_scopes = (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT scope_group FROM account_tenants
                     WHERE account_id = :aid AND is_active = TRUE
                    """
                ),
                {"aid": account_id},
            )
        ).all()
        groups = set(await _user_groups(conn, account_id))
        for (sg,) in existing_scopes:
            groups.add(sg)
        groups.add("personal")  # legacy 호환 — personal 항상 포함.
        groups.add(body.group)
        await _set_user_groups(conn, account_id, list(groups))
        new_groups = await _user_groups(conn, account_id)

    log.info(
        "account_group_activated",
        account_id=account_id,
        group=body.group,
        tenant_id=str(tenant_id),
        slug=slug,
    )

    return ActivateResponse(
        membership=GroupMembership(
            tenant_id=str(tenant_id),
            name=body.tenant_name,
            slug=slug,
            tenant_type=body.group,
            role="owner",
            scope_group=body.group,
            is_active=True,
        ),
        user_groups=new_groups,
    )


@router.delete("/{tenant_id}", response_model=GroupListResponse)
async def deactivate_group(
    tenant_id: str,
    authorization: str = Header(...),
) -> GroupListResponse:
    """특정 tenant 멤버십 비활성화. 데이터 row 는 보존 (실수 복구 가능).

    personal scope 는 거부 — 사용자 단독 데이터는 가입 흐름과 함께 잠금.
    같은 group 의 다른 활성 멤버십이 없으면 user_groups 에서도 제거.
    """
    account_id = _account_id_from_bearer(authorization)

    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT scope_group, is_active
                      FROM account_tenants
                     WHERE account_id = :aid AND tenant_id = :tid
                     LIMIT 1
                    """
                ),
                {"aid": account_id, "tid": tenant_id},
            )
        ).first()
        if row is None:
            raise HTTPException(404, "membership not found")
        scope_group, is_active = row[0], row[1]
        if scope_group == "personal":
            raise HTTPException(400, "personal scope cannot be deactivated")
        if not is_active:
            # 이미 비활성 — idempotent 처리, 응답 그대로.
            log.info(
                "account_group_already_inactive",
                account_id=account_id,
                tenant_id=tenant_id,
                scope_group=scope_group,
            )
        else:
            await conn.execute(
                text(
                    """
                    UPDATE account_tenants
                       SET is_active = FALSE, updated_at = NOW()
                     WHERE account_id = :aid AND tenant_id = :tid
                    """
                ),
                {"aid": account_id, "tid": tenant_id},
            )

        # tenant_memberships 정리 — is_active 분기와 무관하게 매 호출 idempotent.
        # 본 PR 이전 배포에서 이미 비활성화된 멤버십(tenant_memberships row 잔존)
        # 도 재호출 시 cleanup 되도록 if/else 밖에 둠 (gpt-5.5 검토 발견).
        # personal_tenant 보호는 위 분기에서 이미 400 처리.
        await conn.execute(
            text(
                """
                DELETE FROM tenant_memberships
                 WHERE account_id = :aid AND tenant_id = :tid
                """
            ),
            {"aid": account_id, "tid": tenant_id},
        )

        # 같은 group 의 다른 활성 멤버십이 있는지 확인.
        remaining = (
            await conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM account_tenants
                     WHERE account_id = :aid
                       AND scope_group = :sg
                       AND is_active = TRUE
                    """
                ),
                {"aid": account_id, "sg": scope_group},
            )
        ).scalar_one()

        groups = set(await _user_groups(conn, account_id))
        if remaining == 0 and scope_group in groups:
            groups.discard(scope_group)
            await _set_user_groups(conn, account_id, list(groups))

        new_groups = await _user_groups(conn, account_id)

        # 활성 멤버십 다시 조회.
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT t.id::text, t.name, t.slug, t.tenant_type,
                           at.role, at.scope_group, at.is_active
                      FROM account_tenants at
                      JOIN tenants t ON t.id = at.tenant_id
                     WHERE at.account_id = :aid
                       AND at.is_active = TRUE
                       AND t.is_active = TRUE
                     ORDER BY at.scope_group, t.name
                    """
                ),
                {"aid": account_id},
            )
        ).all()

    log.info(
        "account_group_deactivated",
        account_id=account_id,
        tenant_id=tenant_id,
        scope_group=scope_group,
    )

    memberships = [
        GroupMembership(
            tenant_id=r[0],
            name=r[1],
            slug=r[2],
            tenant_type=r[3],
            role=r[4],
            scope_group=r[5],
            is_active=r[6],
        )
        for r in rows
    ]
    return GroupListResponse(memberships=memberships, user_groups=new_groups)


class ScopeToggleBody(BaseModel):
    scope: str = Field(..., description="sole_proprietor")
    enabled: bool

    @field_validator("scope")
    @classmethod
    def _v_scope(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in TOGGLEABLE_SCOPES:
            raise ValueError(
                f"scope '{v}' not toggleable here — allowed: "
                f"{sorted(TOGGLEABLE_SCOPES)}"
            )
        return s


@router.patch("/scope", response_model=GroupListResponse)
async def toggle_scope(
    body: ScopeToggleBody,
    authorization: str = Header(...),
) -> GroupListResponse:
    """personal_tenant 안 sub-scope 토글 — sole_proprietor enable/disable.

    별개 tenant 를 만들지 않고 ``preferences.user_groups`` 에만 추가/제거.
    가입 시 결정한 scope 외에 사용자가 사후에 1인사업자 시작/종료 시 사용.
    settings PATCH 의 user_groups 키가 보안상 차단됐기 때문에 본 endpoint
    가 유일한 변경 경로 (personal / company / business / admin 은 다른
    경로로만 갱신).
    """
    account_id = _account_id_from_bearer(authorization)
    eng = _get_engine()
    async with eng.begin() as conn:
        groups = set(await _user_groups(conn, account_id))
        # 안전 가드 — 다른 그룹은 본 endpoint 로 변경 불가, 기존 값 보존.
        if body.enabled:
            groups.add(body.scope)
        else:
            groups.discard(body.scope)
        groups.add("personal")  # personal 잠금.
        await _set_user_groups(conn, account_id, list(groups))
        new_groups = await _user_groups(conn, account_id)

        rows = (
            await conn.execute(
                text(
                    """
                    SELECT t.id::text, t.name, t.slug, t.tenant_type,
                           at.role, at.scope_group, at.is_active
                      FROM account_tenants at
                      JOIN tenants t ON t.id = at.tenant_id
                     WHERE at.account_id = :aid
                       AND at.is_active = TRUE
                       AND t.is_active = TRUE
                     ORDER BY at.scope_group, t.name
                    """
                ),
                {"aid": account_id},
            )
        ).all()

    log.info(
        "account_scope_toggled",
        account_id=account_id,
        scope=body.scope,
        enabled=body.enabled,
        new_groups=new_groups,
    )

    memberships = [
        GroupMembership(
            tenant_id=r[0],
            name=r[1],
            slug=r[2],
            tenant_type=r[3],
            role=r[4],
            scope_group=r[5],
            is_active=r[6],
        )
        for r in rows
    ]
    return GroupListResponse(memberships=memberships, user_groups=new_groups)


__all__ = ["router"]
