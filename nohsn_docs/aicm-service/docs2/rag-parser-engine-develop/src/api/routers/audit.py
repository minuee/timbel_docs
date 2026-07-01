"""Audit log API — Phase 8 admin 페이지용.

tool_invocations / freshness_runs 두 테이블에서 최근 기록을 합쳐 반환.

read-only. tenant 필터는 X-Tenant-Id 헤더 또는 query string 으로 받는다.

D24 §1 (2026-05-08, GPT-5 phase 0 patch): admin role 강제는 *항상* 적용 —
KMS_RBAC_ENFORCED 환경 변수와 무관하게 require_role_dep("admin") 고정. 시연/dev
환경에서도 cross-agent audit 노출 차단. 테스트는 admin role fixture 로 진입.

owner_agent_id query 파라미터 (admin 전용) — agent 별 audit 디버그 view.
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


def _admin_dependencies() -> list:
    """D24 §1 — audit 라우트는 *항상* admin only.

    KMS_RBAC_ENFORCED 와 무관하게 require_role_dep("admin") 강제. 시연/dev 에서도
    cross-agent 노출 차단 (GPT-5 phase 0 verdict 권고).

    GPT-5 phase 1 post 권고: 우회 환경변수는 *pytest 실행 컨텍스트* 에서만 인정.
    `PYTEST_CURRENT_TEST` 가 set 되어 있고 + `KMS_AUDIT_AUTH_BYPASS=1` 인 경우에만
    bypass — 운영/dev 환경에서 환경변수만 켜는 것으로는 우회 불가.
    """
    pytest_active = bool(os.environ.get("PYTEST_CURRENT_TEST", "").strip())
    bypass_flag = os.environ.get("KMS_AUDIT_AUTH_BYPASS", "").strip() == "1"
    if pytest_active and bypass_flag:
        return []
    from src.api.auth.rbac import require_role_dep

    return [Depends(require_role_dep("admin"))]


router = APIRouter(
    prefix="/api/v1/admin/audit",
    tags=["감사"],
    dependencies=_admin_dependencies(),
)


def _sync_url() -> str:
    return (
        os.environ["DATABASE_URL"]
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )


def _engine():
    # v1: 요청당 engine — 프로덕션에서 싱글톤 pool 로 교체.
    return create_engine(_sync_url())


@router.get("/tool_invocations")
def list_tool_invocations(
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None),
    skill_id: str | None = Query(None),
) -> dict:
    """최근 tool_invocations.

    필터:
    - status (e.g. succeeded, failed, pending_confirm)
    - skill_id
    """
    sql = """
        SELECT id, tenant_id, skill_id, tool_name, status,
               created_at, executed_at, duration_ms,
               cc_pair_id, dry_run, error
          FROM tool_invocations
         WHERE 1=1
    """
    params: dict = {}
    if status:
        sql += " AND status = :status"
        params["status"] = status
    if skill_id:
        sql += " AND skill_id = :skill_id"
        params["skill_id"] = skill_id
    sql += " ORDER BY COALESCE(executed_at, created_at) DESC LIMIT :limit"
    params["limit"] = limit

    eng = _engine()
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            items = [dict(r) for r in rows]
            # datetime → ISO string for JSON
            for it in items:
                for k in ("created_at", "executed_at"):
                    if it.get(k) is not None:
                        it[k] = it[k].isoformat()
            return {"data": {"items": items, "count": len(items)}}
    finally:
        eng.dispose()


@router.get("/freshness_runs")
def list_freshness_runs(limit: int = Query(10, ge=1, le=100)) -> dict:
    """최근 knowledge_freshness_runs."""
    sql = """
        SELECT id, tenant_id, started_at, finished_at, status,
               docs_scanned, pairs_classified, issues_found,
               trigger, error
          FROM knowledge_freshness_runs
         ORDER BY started_at DESC
         LIMIT :limit
    """
    eng = _engine()
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(sql), {"limit": limit}).mappings().all()
            items = [dict(r) for r in rows]
            for it in items:
                for k in ("started_at", "finished_at"):
                    if it.get(k) is not None:
                        it[k] = it[k].isoformat()
            return {"data": {"items": items, "count": len(items)}}
    finally:
        eng.dispose()


@router.get("/combined")
def list_combined(
    inv_limit: int = Query(50, ge=1, le=200),
    fresh_limit: int = Query(10, ge=1, le=50),
) -> dict:
    """tool_invocations + freshness_runs 한 번에. UI 용."""
    inv = list_tool_invocations(limit=inv_limit, status=None, skill_id=None)
    fr = list_freshness_runs(limit=fresh_limit)
    return {
        "data": {
            "tool_invocations": inv["data"]["items"],
            "freshness_runs": fr["data"]["items"],
        }
    }


@router.get("/logs")
def list_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    tenant_id: str | None = Query(
        None, description="tenant UUID 필터 (composite index 활용)"
    ),
    owner_scope: str | None = Query(None, description="admin/agent/role 필터"),
    owner_agent_id: str | None = Query(
        None, description="agent UUID 필터 (admin 디버그)"
    ),
    include_null_owner: bool = Query(
        False, description="owner_scope NULL row 포함 여부 (admin 전용)"
    ),
) -> dict:
    """audit_logs 목록 — D24 §1 신규. admin only (라우트 dependency 가 보장).

    필터:
    - tenant_id: tenant UUID — 지정 시 composite index
      ``ix_audit_logs_owner_scope_tenant`` 활용 (성능 향상).
    - owner_scope: 'admin' / 'agent' / 'role' / None (NULL 만 보고 싶으면
      include_null_owner=true 사용).
    - owner_agent_id: 특정 agent 가 produce 한 audit row 만.
    - include_null_owner: legacy NULL owner_scope row 포함 여부 (default False).

    NOTE: 본 라우트는 admin only — non-admin 은 dependency 단계에서 403.
    """
    sql = """
        SELECT id, tenant_id, user_id, action, resource_type, resource_id,
               event_kind, tool_name, outcome, actor_tier,
               owner_scope, owner_agent_id,
               created_at
          FROM audit_logs
         WHERE 1=1
    """
    params: dict = {}
    if tenant_id:
        sql += " AND tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id
    if owner_scope:
        sql += " AND owner_scope = :owner_scope"
        params["owner_scope"] = owner_scope
    elif not include_null_owner:
        # default-deny: legacy NULL owner_scope 는 명시적으로 요청해야 노출.
        sql += " AND owner_scope IS NOT NULL"
    if owner_agent_id:
        sql += " AND owner_agent_id = :owner_agent_id"
        params["owner_agent_id"] = owner_agent_id
    sql += " ORDER BY created_at DESC LIMIT :limit"
    params["limit"] = limit

    eng = _engine()
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            items = [dict(r) for r in rows]
            for it in items:
                if it.get("created_at") is not None:
                    it["created_at"] = it["created_at"].isoformat()
                # UUID → str (JSON)
                for k in ("id", "tenant_id", "user_id", "resource_id", "owner_agent_id"):
                    if it.get(k) is not None:
                        it[k] = str(it[k])
            return {"data": {"items": items, "count": len(items)}}
    finally:
        eng.dispose()
