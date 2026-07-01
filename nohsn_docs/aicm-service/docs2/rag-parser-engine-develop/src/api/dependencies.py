"""FastAPI 의존성 주입 팩토리.

서비스 클래스 인스턴스를 DB 세션과 함께 요청 스코프로 주입한다.

Phase 9 (KMS-Plus) — Auth v2 (JWT + RBAC):
- ``get_current_user_id`` — 기존 호환 유지 (UUID | None). JWT Bearer 가 있으면
  payload["sub"] 을 UUID 로 변환해 반환, 없으면 ``request.state.user_id`` fallback.
- ``get_current_principal`` — Auth v2 신규. dict 형식으로 user_id/tenant_id/role/auth_v2
  반환. RBAC decorator (``require_role``) 이 사용.
"""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.database import get_db

logger = get_logger(__name__)


async def get_current_tenant_id(
    request: Request,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
) -> UUID:
    """현재 요청의 테넌트 ID를 반환한다.

    미들웨어가 설정한 request.state.tenant_id 를 우선 사용하고,
    없으면 X-Tenant-Id 헤더에서 추출한다.
    개발 환경 또는 LUCAS_AUTH_DISABLED=true 에서는 기본 tenant 로 fallback.
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id
    if x_tenant_id:
        logger.debug("tenant_id_from_header", x_tenant_id=x_tenant_id)
        return UUID(x_tenant_id)

    from src.common.config import settings

    # Lucas-KMS 무인증 모드 — 키 없이 호출 가능 (테스트/시연/staging).
    if settings.LUCAS_AUTH_DISABLED:
        logger.debug("tenant_id_from_default", default=settings.LUCAS_DEFAULT_TENANT_ID)
        return UUID(settings.LUCAS_DEFAULT_TENANT_ID)
    if settings.APP_ENV == "development":
        return UUID("00000000-0000-0000-0000-000000000000")

    from src.common.exceptions import AICMError

    raise AICMError(
        code="TENANT_ID_REQUIRED",
        message="X-Tenant-Id 헤더가 필요합니다.",
    )


def _decode_bearer(authorization: str | None) -> dict[str, Any] | None:
    """``Authorization: Bearer <jwt>`` 헤더에서 payload 추출.

    헤더가 없거나 형식이 틀리거나 디코딩 실패면 None.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    # 지연 import — 모듈 로드 시 jose/passlib 강제 의존을 피함.
    from src.api.auth.jwt_utils import InvalidToken, decode_token

    try:
        payload = decode_token(token)
    except InvalidToken:
        return None
    # access token 만 인정 — refresh 는 /auth/v2/refresh 전용.
    if payload.get("type") not in (None, "access"):
        return None
    return payload


async def get_current_user_id(
    request: Request,
    authorization: str | None = Header(None),
) -> UUID | None:
    """현재 인증된 사용자 ID 반환 (UUID | None — 기존 시그니처 유지).

    우선순위:
    1. ``Authorization: Bearer <jwt>`` payload["sub"] (Auth v2) → UUID 변환 시도.
    2. ``request.state.user_id`` (legacy 미들웨어).
    3. None (미인증).

    JWT sub 가 UUID 가 아닌 경우 (email 등) 는 None 으로 fallback —
    기존 호출자 (notes/rag/pii) 가 UUID 만 다루므로 호환성 유지.
    """
    payload = _decode_bearer(authorization)
    if payload:
        sub = payload.get("sub")
        if sub:
            try:
                return UUID(str(sub))
            except (ValueError, TypeError):
                pass  # email/non-UUID subject — legacy fallback.
    state_user_id = getattr(request.state, "user_id", None)
    if state_user_id:
        return state_user_id
    # Lucas-KMS 무인증 모드 — 기본 user 반환 (None 대신 default UUID 로 RBAC 통과).
    from src.common.config import settings
    if settings.LUCAS_AUTH_DISABLED:
        try:
            return UUID(settings.LUCAS_DEFAULT_USER_ID)
        except (ValueError, TypeError):
            return None
    return None


async def get_current_principal(
    request: Request,
    authorization: str | None = Header(None),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-Id"),
) -> dict[str, Any]:
    """Auth v2 — JWT 우선 + legacy X-Tenant-Id fallback.

    Returns:
        ``{"user_id": str|None, "tenant_id": str|None, "role": str, "auth_v2": bool}``

    JWT 가 유효하면 payload 의 sub/tenant_id/role 사용 (auth_v2=True).
    아니면 X-Tenant-Id 헤더만 사용하고 role 은 viewer 로 다운그레이드 (auth_v2=False).
    """
    payload = _decode_bearer(authorization)
    if payload:
        return {
            "user_id": payload.get("sub"),
            "tenant_id": payload.get("tenant_id"),
            "role": payload.get("role", "viewer"),
            "auth_v2": True,
        }
    # Lucas-KMS 무인증 모드 — admin role 부여로 RBAC bypass.
    from src.common.config import settings
    if settings.LUCAS_AUTH_DISABLED:
        return {
            "user_id": settings.LUCAS_DEFAULT_USER_ID,
            "tenant_id": x_tenant_id or settings.LUCAS_DEFAULT_TENANT_ID,
            "role": "admin",
            "auth_v2": False,
            "auth_disabled": True,
        }
    return {
        "user_id": None,
        "tenant_id": x_tenant_id,
        "role": "viewer",
        "auth_v2": False,
    }
