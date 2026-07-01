"""Agent auth shim — v1 데모 로그인 엔드포인트.

2026-04-24 — 사용자 요청: 문서관리 페이지가 로그인된 계정 문서만 보여주도록.

설계 메모:
- 실제 auth 검증 (JWT/OAuth) 은 후속 작업. ``session_token`` 은 opaque UUID 로
  발급만 하고 이후 검증 경로 없음. v1 은 localStorage 기반 식별 모델.
- ``/agent/identity/register`` 와 겹치지만, ``/auth/login`` 은 전용 로그인 페이지
  (``/login.html``) 에서 호출하는 별도 shim. 내부 로직은 동일하게
  ``get_or_create_account`` 를 사용 — idempotent.
- 프런트는 응답 payload 의 ``personal_tenant_id`` 를 localStorage 에 저장해
  ``X-Tenant-Id`` 헤더로 사용 → documents 라우터의 테넌트 필터가 자동 적용.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.agent_framework.core.accounts import get_or_create_account

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=3, max_length=32)
    name: str | None = Field(default=None, max_length=100)


class LoginResponse(BaseModel):
    account_id: str
    personal_tenant_id: str
    phone: str
    name: str | None
    session_token: str  # v1 opaque — 실제 검증 로직 없음


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """phone + name 으로 로그인 (idempotent).

    account 없으면 자동 생성. 세션 토큰은 opaque 로 발급만 하고 검증 없음 (v1).
    """
    ctx = await get_or_create_account(phone=body.phone, name=body.name)
    return LoginResponse(
        account_id=str(ctx.account_id),
        personal_tenant_id=str(ctx.personal_tenant_id),
        phone=body.phone,
        name=body.name if body.name is not None else ctx.name,
        session_token=str(uuid.uuid4()),
    )
