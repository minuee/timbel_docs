"""Shared JWT tenant scope helper — Phase 1.5A Task 8c.2.

Single source of truth for tenant resolution from JWT + optional ``X-Tenant-ID``
header. JWT claim is authoritative; the header MUST match the claim if present.

Background (GPT-5.5 deep dive — 2026-05-06)
-------------------------------------------
The original pattern across many routers was::

    tid = x_tenant_id or payload.get("tenant_id")

This let any caller with a *valid* JWT impersonate any tenant by simply sending
a different ``X-Tenant-ID`` header — a cross-tenant impersonation primitive.
Task 8c fixed ``chat_v1._scope`` inline; Task 8c.2 sweeps the same fix to all
remaining routers via this shared helper.

Policy
------
- JWT ``tenant_id`` claim is the only trust source for tenant scope.
- ``X-Tenant-ID`` header **absent** (None or empty) → JWT claim is used.
- Header **present and equal** to JWT claim → OK (frontend round-trip
  compatibility).
- Header **present and different** from JWT claim → 401 ``tenant claim
  mismatch``.
- JWT claim **missing** → 401 ``missing tenant claim in JWT``.
"""
from __future__ import annotations

from fastapi import HTTPException


def resolve_tenant_id(
    jwt_payload: dict, x_tenant_header: str | None
) -> str:
    """Return the authoritative tenant_id string for this request.

    Args:
        jwt_payload: decoded JWT payload dict (must contain ``tenant_id``).
        x_tenant_header: raw ``X-Tenant-ID`` header value (may be None / "").

    Raises:
        HTTPException(401): JWT missing tenant claim, or header != claim.
    """
    jwt_tid = jwt_payload.get("tenant_id")
    if not jwt_tid:
        raise HTTPException(401, "missing tenant claim in JWT")
    # 빈 문자열 / None 은 "헤더 미지정" 으로 취급 (FastAPI Header(None) 기본값과 일관).
    if x_tenant_header is not None and x_tenant_header != "":
        if str(x_tenant_header) != str(jwt_tid):
            raise HTTPException(401, "tenant claim mismatch")
    return str(jwt_tid)
