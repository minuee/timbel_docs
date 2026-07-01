"""D25 (#158) — RLS context (contextvars) for transaction-scoped session vars.

D25 spec §3 — middleware/session 구현. application 이 transaction 시작 직전
``set_rls_context`` 로 sender 의 scope/agent_id/tenant_id 를 등록하면, SQLAlchemy
``begin`` event listener (``src/core/database.py`` 의 ``_rls_set_session_vars``)
가 ``SET LOCAL app.current_*`` 를 자동 발행한다.

사용자 절칙 (2026-05-08):
- bypass 는 *PostgreSQL role attribute* (BYPASSRLS) 로만 — GUC 토글 폐기 (R1 FAIL).
- application role (kms_app) 은 NOBYPASSRLS — SET LOCAL 으로 우회 불가능.
- migration role (kms_migration) 은 BYPASSRLS — alembic / break-glass 전용.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Literal


# RLSScope = '' | 'admin' | 'agent' | 'role' | 'superadmin' | 'system'
# - ''         : 빈 → default-deny (SELECT 0, INSERT 거부)
# - 'admin'    : 자기 tenant 안 모든 row + NULL owner. tenant 경계 강제.
# - 'agent'    : 본인 owner_agent_id 만. tenant 경계 강제.
# - 'role'     : 향후 D26 + role-based 격리.
# - 'superadmin' : cross-tenant — Locus 운영자 only (admin global view 등).
# - 'system'   : background worker / cron / dispatcher 의 system audit row.
RLSScope = Literal["", "admin", "agent", "role", "superadmin", "system"]


@dataclass(frozen=True)
class RLSContext:
    """transaction-scope session var 주입용 context.

    Attributes:
        agent_id: 본인 agent UUID (없으면 None).
        scope: sender 의 scope.
        tenant_id: tenant UUID (admin/agent scope: 자기 tenant. superadmin: 무관).
    """
    agent_id: str | None
    scope: RLSScope
    tenant_id: str | None


_RLS_CONTEXT: contextvars.ContextVar[RLSContext | None] = contextvars.ContextVar(
    "rls_context", default=None
)


def get_rls_context() -> RLSContext | None:
    """현재 contextvar 값 (없으면 None)."""
    return _RLS_CONTEXT.get(None)


def set_rls_context(ctx: RLSContext) -> contextvars.Token:
    """RLS context 등록. token 반환 — 종료 시 ``reset_rls_context(token)`` 필수."""
    return _RLS_CONTEXT.set(ctx)


def reset_rls_context(token: contextvars.Token) -> None:
    """contextvar 원복 — 호출 site 의 try/finally 안에서 호출 권장."""
    _RLS_CONTEXT.reset(token)


# D32 §2 — agent scope 재바인딩 헬퍼 (사후 GPT-5 §2 SHOULD).
# dispatcher 가 sender 식별 직후 ``async with bind_agent_scope(agent_id)`` 로
# admin → agent scope 전환. turn 종료 시 자동 복원.
from contextlib import asynccontextmanager  # noqa: E402


def _normalize_uuid_str(value: str | None) -> str | None:
    """UUID 정규화 — 파싱 실패 시 None (begin 훅의 _validated_uuid 와 일관)."""
    if not value:
        return None
    try:
        from uuid import UUID as _UUID
        return str(_UUID(value))
    except (ValueError, TypeError):
        return None


@asynccontextmanager
async def bind_agent_scope(
    agent_id: str | None,
    tenant_id: str | None = None,
):  # type: ignore[no-untyped-def]
    """현재 RLSContext 위에 agent scope 를 일시적으로 적용.

    Args:
        agent_id: 본인 agent UUID. None / 비-UUID 면 no-op (RLSContext 변경 X).
        tenant_id: 명시 시 RLSContext.tenant_id 도 override. 부재 시 기존 ctx
            (middleware 가 JWT 로 set 한 값) 의 tenant_id 사용.

    Usage:
        async with bind_agent_scope(str(agent_id), tenant_id):
            await engine.run_turn(...)
    """
    # 사후 GPT-5 §2+§3 권고 — agent_id UUID 정규화 (begin 훅 정책과 일관).
    norm_agent_id = _normalize_uuid_str(agent_id)
    if not norm_agent_id:
        # no-op — 기존 ctx 그대로 (admin scope 라면 admin 으로 진행).
        # D31d Phase 3 §2 — RLS violation counter (비파괴 inc only).
        try:
            from src.common.metrics import KMS_RLS_VIOLATION_TOTAL

            KMS_RLS_VIOLATION_TOTAL.labels(
                source="middleware",
                table="any",
                operation="bind_agent_scope_invalid_id",
            ).inc()
        except Exception:  # noqa: BLE001 — metrics 미초기화 등.
            pass
        yield
        return

    prev = get_rls_context()
    norm_tenant_id = _normalize_uuid_str(tenant_id) or (
        prev.tenant_id if prev else None
    )
    new_ctx = RLSContext(
        scope="agent",
        agent_id=norm_agent_id,
        tenant_id=norm_tenant_id,
    )
    token = set_rls_context(new_ctx)
    try:
        yield
    finally:
        reset_rls_context(token)


# D34 §1 — pipeline-worker / background task 용 system scope 헬퍼.
# alembic 079 가 system SELECT 를 cross-tenant 허용 + INSERT/UPDATE/DELETE 는
# tenant_id 매칭 강제 → write 는 반드시 tenant_id 명시 후 진입.
@asynccontextmanager
async def bind_system_scope(
    tenant_id: str | None = None,
    *,
    allow_null_tenant: bool = False,
):  # type: ignore[no-untyped-def]
    """pipeline-worker / kafka consumer / background task 용 system scope 적용.

    Args:
        tenant_id: 작업 대상 tenant UUID. write (INSERT/UPDATE/DELETE) 가 발생할 때
            는 *반드시 명시 필요* (alembic 079 의 system 분기는 tenant_id 매칭 강제).
        allow_null_tenant: tenant_id=None 으로 진입 허용 여부.
            - True: read-only path (recover_stale_documents / dlq_scheduler /
              reminder_worker / tenant lookup 직전 1회 SELECT 등).
            - False (default): tenant_id None 시 *경고 log* (write 발생 시 RLS 차단
              자체는 정책 단계에서 거절 — helper 단에서는 차단 X).

    Note: bind_agent_scope 와 달리 *항상* RLSContext 를 새로 set (no-op 분기 없음).
    system scope 는 owner_agent_id 무관 (alembic 079 정책).

    Usage:
        # tenant 명시 (write 안전).
        async with bind_system_scope(str(doc.tenant_id)):
            await session.execute(insert(Document).values(...))

        # tenant 파악 전 SELECT.
        async with bind_system_scope(None, allow_null_tenant=True):
            row = await session.execute(select(Document.tenant_id).where(...))
    """
    norm_tenant_id = _normalize_uuid_str(tenant_id)

    # tenant 미명시 + read-only 미선언 → 경고 (write 차단은 RLS 정책이 처리).
    if not norm_tenant_id and not allow_null_tenant:
        try:
            from src.common.logging import get_logger as _gl

            _gl(__name__).warning(
                "bind_system_scope_null_tenant",
                hint=(
                    "system writes require tenant_id — "
                    "set tenant_id or allow_null_tenant=True for SELECT-only path"
                ),
            )
        except Exception:  # noqa: BLE001
            pass
        # D31d Phase 3 §2 — RLS violation counter (비파괴 inc only).
        try:
            from src.common.metrics import KMS_RLS_VIOLATION_TOTAL

            KMS_RLS_VIOLATION_TOTAL.labels(
                source="middleware",
                table="any",
                operation="bind_system_scope_null_tenant",
            ).inc()
        except Exception:  # noqa: BLE001
            pass

    new_ctx = RLSContext(
        scope="system",
        agent_id=None,
        tenant_id=norm_tenant_id,
    )
    token = set_rls_context(new_ctx)
    try:
        yield
    finally:
        reset_rls_context(token)


# D34 §5 — superadmin scope 헬퍼 (cross-tenant view 진입).
@asynccontextmanager
async def bind_superadmin_scope(
    *,
    subject: str | None = None,
    path: str | None = None,
):  # type: ignore[no-untyped-def]
    """super-admin role 용 cross-tenant scope. 진입/종료 INFO log 강제 (audit).

    Args:
        subject: super-admin 의 account/sub (audit log 용).
        path: 호출 path (audit log 용).

    GPT-5 §5 권고: cross-tenant 접근 추적성 — 모든 진입/종료 INFO log.
    """
    new_ctx = RLSContext(
        scope="superadmin",
        agent_id=None,
        tenant_id=None,
    )
    token = set_rls_context(new_ctx)
    try:
        try:
            from src.common.logging import get_logger as _gl

            _gl(__name__).info(
                "bind_superadmin_scope_enter",
                subject=subject,
                path=path,
            )
        except Exception:  # noqa: BLE001
            pass
        yield
    finally:
        try:
            from src.common.logging import get_logger as _gl

            _gl(__name__).info(
                "bind_superadmin_scope_exit",
                subject=subject,
                path=path,
            )
        except Exception:  # noqa: BLE001
            pass
        reset_rls_context(token)


__all__ = [
    "RLSContext",
    "RLSScope",
    "bind_agent_scope",
    "bind_superadmin_scope",
    "bind_system_scope",
    "get_rls_context",
    "set_rls_context",
    "reset_rls_context",
]
