"""Agent identity API — chat 첫 방문 시 account 자동 생성 훅.

Stage B-1 원안 복귀 2단계.

- ``POST /agent/identity/register`` — phone+name 으로 account (없으면 생성,
  있으면 조회). idempotent — 재호출해도 같은 account_id/personal_tenant_id 반환.
- ``GET /agent/identity/memberships`` — account 가 속한 tenant 목록.

프런트 ``identity_gate.js`` 가 모달 제출 시 이 endpoint 를 호출해
localStorage 에 account_id / personal_tenant_id 를 캐시.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agent_framework.core.accounts import (
    get_account_by_phone,
    get_or_create_account,
    list_tenant_memberships,
)

router = APIRouter(prefix="/agent/identity", tags=["agent-identity"])


class IdentityRegisterRequest(BaseModel):
    phone: str = Field(..., min_length=3, max_length=32)
    name: str | None = Field(default=None, max_length=100)


class IdentityRegisterResponse(BaseModel):
    account_id: str
    phone: str
    name: str | None
    personal_tenant_id: str


@router.post("/register", response_model=IdentityRegisterResponse)
async def register_identity(body: IdentityRegisterRequest) -> IdentityRegisterResponse:
    """chat 첫 방문 시 phone+name 으로 account 자동 생성 (idempotent)."""
    ctx = await get_or_create_account(phone=body.phone, name=body.name)
    return IdentityRegisterResponse(
        account_id=str(ctx.account_id),
        phone=ctx.phone,
        name=ctx.name,
        personal_tenant_id=str(ctx.personal_tenant_id),
    )


@router.get("/lookup", response_model=IdentityRegisterResponse | None)
async def lookup_identity(phone: str) -> IdentityRegisterResponse | None:
    """phone 으로 account 조회 (없으면 None 반환)."""
    ctx = await get_account_by_phone(phone=phone)
    if ctx is None:
        return None
    return IdentityRegisterResponse(
        account_id=str(ctx.account_id),
        phone=ctx.phone,
        name=ctx.name,
        personal_tenant_id=str(ctx.personal_tenant_id),
    )


@router.get("/memberships")
async def memberships(account_id: str) -> dict:
    """account 가 속한 tenant 목록 (type 별)."""
    try:
        aid = UUID(account_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid account_id: {e}") from e
    rows = await list_tenant_memberships(aid)
    return {
        "account_id": account_id,
        "memberships": [
            {
                "tenant_id": str(r["tenant_id"]),
                "slug": r["slug"],
                "name": r["name"],
                "type": r["type"],
                "role": r["role"],
            }
            for r in rows
        ],
    }
