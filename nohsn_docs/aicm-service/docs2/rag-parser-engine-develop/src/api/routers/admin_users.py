"""/api/v1/admin/users — super_admin role 발급 관리 (D36 / #216).

D34 (#211) 의 superadmin RLSScope + bind_superadmin_scope() + JWT role 매핑 활용.
본 D36 은 super_admin role 의 *발급 path* — 현재 JWT 발급은 tenant_memberships.role
을 그대로 노출하므로, 본 라우터가 그 컬럼을 안전하게 update 한다.

Endpoint:
- ``GET    /api/v1/admin/users``                     — 멤버십 list (cross-tenant)
- ``POST   /api/v1/admin/users/{account_id}/role``   — role update + audit
- ``GET    /api/v1/admin/users/{account_id}/role-history``  — audit_logs view

권한:
- 모두 super-admin 전용. JWT.role ∈ ('super_admin', 'superadmin') 검증.
- bind_superadmin_scope async ctxmgr 안에서 DB 호출 — 077 의 superadmin SELECT
  정책 통과 (audit_logs cross-tenant SELECT). tenant_memberships/accounts 는 RLS
  미적용 (alembic 023) — application 단 _require_super_admin gate 만으로 충분.

Spec: docs/superpowers/specs/2026-05-10-d36-super-admin-ui.md
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.api.middleware.rls_context import bind_superadmin_scope
from src.common.logging import get_logger
from src.core.database import engine as core_engine
from src.core.services.audit_service import record_event


logger = get_logger(__name__)


router = APIRouter(prefix="/api/v1/admin/users", tags=["admin-users"])


# ---------------------------------------------------------------------------
# Engine — *core engine* 사용 (RLS begin 훅 보장).
#
# admin_global_view_v1 패턴은 별도 create_async_engine — RLS begin 훅 미설치.
# 본 D36 은 audit_logs (077 RLS 적용) 를 cross-tenant SELECT 해야 하므로
# core engine (src.core.database.engine) 의 begin 훅이 필수.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Auth — super-admin gate (JWT.role 만 신뢰; DB query 무).
# ---------------------------------------------------------------------------


_SUPER_ADMIN_ROLES = frozenset({"super_admin", "superadmin"})

# spec §1 — role whitelist (6 값).
_ROLE_WHITELIST = frozenset({
    "super_admin", "owner", "admin", "editor", "viewer", "member"
})


def _require_super_admin(authorization: str | None) -> tuple[UUID, str | None]:
    """Bearer token → (caller_account_id, caller_tenant_id). super_admin 아니면 403.

    JWT.role 만 신뢰 (DB query 무) — middleware 가 RLSContext.scope='superadmin'
    을 set 한 상태이므로 세션 변수 일관. 추가 DB lookup 은 race / 성능 비용만
    추가 — 신뢰 모델은 *JWT 서명* 단일.
    """
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
    role = (payload.get("role") or "").lower()
    if role not in _SUPER_ADMIN_ROLES:
        raise HTTPException(403, "super_admin role required")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    try:
        caller_id = UUID(str(sub))
    except ValueError as e:
        raise HTTPException(401, f"invalid subject: {e}") from e
    return caller_id, payload.get("tenant_id")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class UserMembershipItem(BaseModel):
    account_id: str
    email: str | None = None
    name: str | None = None
    personal_tenant_id: str | None = None
    tenant_id: str
    role: str
    membership_id: str
    created_at: str | None = None
    is_active: bool | None = None


class UserListResponse(BaseModel):
    items: list[UserMembershipItem]
    total: int
    limit: int
    offset: int


class RoleUpdateBody(BaseModel):
    tenant_id: str = Field(..., description="대상 membership 의 tenant_id")
    role: str = Field(..., description="새 role (whitelist 6 값)")
    reason: str | None = Field(None, description="변경 사유 (조건부 필수)")


class RoleUpdateResponse(BaseModel):
    account_id: str
    tenant_id: str
    membership_id: str
    old_role: str
    new_role: str
    audit_log_id: str | None = None


class RoleHistoryItem(BaseModel):
    audit_log_id: str
    actor_id: str | None
    old_role: str | None
    new_role: str | None
    reason: str | None
    created_at: str | None
    target_tenant_id: str | None


class RoleHistoryResponse(BaseModel):
    items: list[RoleHistoryItem]


# ---------------------------------------------------------------------------
# GET /api/v1/admin/users — list memberships (cross-tenant)
# ---------------------------------------------------------------------------


@router.get("", response_model=UserListResponse)
async def list_users(
    tenant_id: str | None = Query(None, description="특정 tenant 만 필터 (선택)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    authorization: str | None = Header(None, alias="Authorization"),
) -> UserListResponse:
    """super-admin 전용 — 멤버십 list (cross-tenant view)."""
    caller_id, _ = _require_super_admin(authorization)

    tenant_filter: UUID | None = None
    if tenant_id:
        try:
            tenant_filter = UUID(tenant_id)
        except ValueError as e:
            raise HTTPException(400, f"invalid tenant_id: {e}") from e

    where_extra = ""
    params: dict[str, Any] = {"lim": int(limit), "off": int(offset)}
    if tenant_filter is not None:
        where_extra = " WHERE m.tenant_id = :tid"
        params["tid"] = tenant_filter

    sql = f"""
        SELECT
            a.id AS account_id, a.email, a.name, a.personal_tenant_id,
            a.is_active, m.tenant_id, m.role, m.id AS membership_id,
            m.created_at
          FROM tenant_memberships m
          JOIN accounts a ON a.id = m.account_id
          {where_extra}
          ORDER BY m.created_at DESC
          LIMIT :lim OFFSET :off
    """

    count_sql = f"""
        SELECT count(*)
          FROM tenant_memberships m
          {where_extra}
    """

    async with bind_superadmin_scope(
        subject=str(caller_id), path="/api/v1/admin/users"
    ):
        async with core_engine.begin() as conn:
            rows = (await conn.execute(text(sql), params)).all()
            count_params = {"tid": tenant_filter} if tenant_filter is not None else {}
            total = (await conn.execute(text(count_sql), count_params)).scalar() or 0

    items = [
        UserMembershipItem(
            account_id=str(r[0]),
            email=r[1],
            name=r[2],
            personal_tenant_id=str(r[3]) if r[3] else None,
            is_active=bool(r[4]) if r[4] is not None else None,
            tenant_id=str(r[5]),
            role=r[6],
            membership_id=str(r[7]),
            created_at=r[8].isoformat() if r[8] else None,
        )
        for r in rows
    ]
    return UserListResponse(items=items, total=int(total), limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# POST /api/v1/admin/users/{account_id}/role — update role + audit
# ---------------------------------------------------------------------------


def _is_promotion(old_role: str, new_role: str) -> bool:
    """admin/owner 로의 권한 상승 — reason 필수 trigger."""
    elevated = {"admin", "owner"}
    weak = {"member", "viewer", "editor"}
    return new_role in elevated and old_role in weak


def _reason_required(old_role: str, new_role: str) -> bool:
    """reason 필수 조건 — spec §1.4 의 3 조건 합집합.

    1. super_admin 부여 (new == super_admin)
    2. super_admin 박탈 (old == super_admin AND new != super_admin)
    3. 권한 상승 (member/viewer/editor → admin/owner)
    """
    if new_role == "super_admin":
        return True
    if old_role == "super_admin" and new_role != "super_admin":
        return True
    if _is_promotion(old_role, new_role):
        return True
    return False


@router.post("/{account_id}/role", response_model=RoleUpdateResponse)
async def update_user_role(
    account_id: str,
    body: RoleUpdateBody,
    authorization: str | None = Header(None, alias="Authorization"),
) -> RoleUpdateResponse:
    """super-admin 전용 — 단건 멤버십 role 변경 + audit log INSERT.

    검증:
    1. role whitelist 6 값.
    2. Option B — role='super_admin' 시 body.tenant_id == account.personal_tenant_id.
    3. reason 필수 조건 (spec §1.4).
    4. self-demote 가드 — 마지막 super_admin 본인 강등 금지 (409).
    """
    caller_id, _ = _require_super_admin(authorization)

    # 입력 검증.
    new_role = (body.role or "").strip().lower()
    if new_role not in _ROLE_WHITELIST:
        raise HTTPException(
            422,
            f"invalid role (allowed: {sorted(_ROLE_WHITELIST)})",
        )
    try:
        target_account = UUID(account_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid account_id: {e}") from e
    try:
        target_tenant = UUID(body.tenant_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e

    async with bind_superadmin_scope(
        subject=str(caller_id),
        path=f"/api/v1/admin/users/{account_id}/role",
    ):
        async with core_engine.begin() as conn:
            # GPT-5 SHOULD — 동시성 race 차단: super_admin role guard 직렬화.
            # transaction-scope advisory lock — 같은 transaction 안에서만 유효.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('super_admin_role_guard'))")
            )

            # 1. 대상 membership + account.personal_tenant_id 조회.
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT m.id, m.role, a.personal_tenant_id, a.email
                          FROM tenant_memberships m
                          JOIN accounts a ON a.id = m.account_id
                         WHERE m.account_id = :aid
                           AND m.tenant_id = :tid
                         LIMIT 1
                        """
                    ),
                    {"aid": target_account, "tid": target_tenant},
                )
            ).first()
            if not row:
                raise HTTPException(404, "membership not found")
            membership_id, old_role_db, personal_tid, target_email = row
            old_role = (old_role_db or "").lower()

            # 2. Option B — super_admin role 은 personal tenant 멤버십에서만.
            #    (GPT-5 SHOULD: tenant 불일치를 reason 검증보다 먼저 — UX 명확)
            if new_role == "super_admin":
                if personal_tid is None or UUID(str(personal_tid)) != target_tenant:
                    raise HTTPException(
                        422,
                        "super_admin role requires personal tenant membership "
                        "(body.tenant_id must equal account.personal_tenant_id)",
                    )

            # 3. reason 필수 조건.
            if _reason_required(old_role, new_role):
                if not body.reason or not body.reason.strip():
                    raise HTTPException(
                        422,
                        "reason required for super_admin grant/revoke or promotion",
                    )

            # 4. self-demote 가드 — 마지막 super_admin 본인 강등 금지.
            #    GPT-5 MUST: Option B 기준 — personal tenant 멤버십의 super_admin
            #    만 카운트 (실효 super_admin = JWT 발급 가능). caller 제외.
            #    GPT-5 v3 권고 — 본인 personal tenant 멤버십 강등에만 가드 (개인
            #    테넌트 외 stale 'super_admin' row 강등은 false positive 방지).
            personal_tid_uuid = (
                UUID(str(personal_tid)) if personal_tid is not None else None
            )
            is_personal_tenant_demote = (
                personal_tid_uuid is not None and personal_tid_uuid == target_tenant
            )
            if (
                target_account == caller_id
                and old_role == "super_admin"
                and new_role != "super_admin"
                and is_personal_tenant_demote
            ):
                other_count = (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*) FROM tenant_memberships m
                              JOIN accounts a ON a.id = m.account_id
                             WHERE LOWER(m.role) = 'super_admin'
                               AND m.tenant_id = a.personal_tenant_id
                               AND m.account_id != :caller
                            """
                        ),
                        {"caller": caller_id},
                    )
                ).scalar() or 0
                if int(other_count) == 0:
                    raise HTTPException(
                        409,
                        "cannot demote the last super_admin (self-demote guard)",
                    )

            # 5. UPDATE — old_role == new_role 이어도 idempotent (audit row 만 추가).
            await conn.execute(
                text(
                    """
                    UPDATE tenant_memberships
                       SET role = :new_role
                     WHERE id = :mid
                    """
                ),
                {"new_role": new_role, "mid": membership_id},
            )

        # 6. audit_logs INSERT — *bind_superadmin_scope 안* (외곽 async with 가
        # 함수 끝까지 유지). record_event 가 자체 session 을 열 때 begin 훅이
        # 현재 contextvar (scope='superadmin') 을 읽어 SET LOCAL 발행.
        # 077 audit_logs INSERT 정책의 superadmin 분기 통과 + NULL owner 가드는
        # owner_scope='admin' 으로 우회.
        # tenant_id = 대상 membership.tenant_id (GPT-5 verdict §1 권고).
        audit_log_id: str | None = None
        try:
            audit = await record_event(
                tenant_id=target_tenant,
                actor_id=caller_id,
                actor_tier="superadmin",
                event_kind="tenant_membership.role_update",
                tool_name="admin_users.update_role",
                args_redacted={
                    "old_role": old_role,
                    "new_role": new_role,
                    "target_account": str(target_account),
                    "target_email": target_email,
                    "reason": (body.reason or "").strip() or None,
                },
                outcome="success",
                action="UPDATE",
                resource_type="tenant_membership",
                resource_id=membership_id,
                detail={
                    "old_role": old_role,
                    "new_role": new_role,
                    "target_account": str(target_account),
                    "target_email": target_email,
                    "reason": (body.reason or "").strip() or None,
                },
                # 077 audit_logs INSERT 정책의 NULL owner 글로벌 가드 통과:
                # owner_agent_id IS NOT NULL OR owner_scope IN ('admin', 'system').
                # super_admin 행위는 owner_scope='admin' (top-level admin) 으로 기록.
                owner_scope="admin",
            )
            audit_log_id = str(audit.id) if audit and getattr(audit, "id", None) else None
        except Exception as e:  # noqa: BLE001 — audit 실패가 role update 무효화 X.
            logger.warning(
                "admin_users_role_update_audit_failed",
                error=str(e),
                target_account=str(target_account),
                tenant_id=str(target_tenant),
            )

    logger.info(
        "admin_users_role_updated",
        caller=str(caller_id),
        target_account=str(target_account),
        tenant_id=str(target_tenant),
        old_role=old_role,
        new_role=new_role,
        reason_present=bool(body.reason and body.reason.strip()),
    )

    return RoleUpdateResponse(
        account_id=str(target_account),
        tenant_id=str(target_tenant),
        membership_id=str(membership_id),
        old_role=old_role,
        new_role=new_role,
        audit_log_id=audit_log_id,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/admin/users/{account_id}/role-history — audit log view
# ---------------------------------------------------------------------------


@router.get("/{account_id}/role-history", response_model=RoleHistoryResponse)
async def get_role_history(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
    authorization: str | None = Header(None, alias="Authorization"),
) -> RoleHistoryResponse:
    """super-admin 전용 — 특정 account 의 role 변경 audit history."""
    caller_id, _ = _require_super_admin(authorization)

    try:
        target_account = UUID(account_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid account_id: {e}") from e

    # GPT-5 MUST — core engine 사용 (RLS begin 훅 보장; audit_logs 077 RLS).
    # resource_type='tenant_membership' 필터 — 같은 event_kind 가 다른 resource
    # 로 미래 사용될 가능성에 대한 방어.
    sql = """
        SELECT id, user_id, detail, created_at, tenant_id
          FROM audit_logs
         WHERE event_kind = 'tenant_membership.role_update'
           AND resource_type = 'tenant_membership'
           AND detail->>'target_account' = :target
         ORDER BY created_at DESC
         LIMIT :lim
    """

    async with bind_superadmin_scope(
        subject=str(caller_id),
        path=f"/api/v1/admin/users/{account_id}/role-history",
    ):
        async with core_engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(sql),
                    {"target": str(target_account), "lim": int(limit)},
                )
            ).all()

    items: list[RoleHistoryItem] = []
    for r in rows:
        detail = r[2] or {}
        if not isinstance(detail, dict):
            detail = {}
        items.append(
            RoleHistoryItem(
                audit_log_id=str(r[0]),
                actor_id=str(r[1]) if r[1] else None,
                old_role=detail.get("old_role"),
                new_role=detail.get("new_role"),
                reason=detail.get("reason"),
                created_at=r[3].isoformat() if r[3] else None,
                target_tenant_id=str(r[4]) if r[4] else None,
            )
        )

    return RoleHistoryResponse(items=items)
