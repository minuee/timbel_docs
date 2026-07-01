"""Platform-level admin 가드.

Codex 검토 (2026-04-28) 발견 — 기존 ``require_role_dep("admin")`` 은 RBAC
순위가 ``owner > admin`` 이라 signup 시 owner role 받은 일반 사용자가
admin route 통과해 escalation. 동시에 ``manifest`` 의 admin 풀-액세스는
``preferences.user_groups`` 에 'admin' 포함 여부로 판정.

본 모듈은 **시스템 운영자(=platform admin)** 와 tenant-내 owner/admin 을
명확히 분리. account_settings PATCH 가 ``user_groups`` 키를 거부하도록
이미 수정 (RESERVED_KEYS) — ``preferences.user_groups`` 변경 경로는 시드
스크립트와 ``/api/v1/account/groups`` (admin 미허용) 둘뿐. 따라서
``preferences.user_groups`` 에 'admin' 가 들어오는 유일한 경로는 운영
시드 (server-owned) — platform admin 신뢰원으로 활용 가능.

향후 강화: ``accounts.platform_role`` 컬럼을 도입해 preferences 와 무관한
서버-소유 권한 컬럼으로 격리. 현재 단계에서는 시드 + RESERVED_KEYS 보호로
일관성 유지.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

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


async def require_platform_admin(
    authorization: str = Header(...),
) -> dict[str, Any]:
    """현재 사용자가 platform admin 인지 검증.

    조건: ``accounts.preferences.user_groups`` 가 list 이고 'admin' 포함.
    아니면 403.

    ``account_settings`` PATCH 의 RESERVED_KEYS 가드 + signup/account_groups
    화이트리스트 (admin 거부) 로 인해 'admin' 그룹은 운영 시드로만 부여.
    """
    account_id = _account_id_from_bearer(authorization)
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT preferences FROM accounts WHERE id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
    if row is None:
        raise HTTPException(403, "account not found")
    prefs = dict(row[0] or {})
    groups = prefs.get("user_groups")
    if not isinstance(groups, list) or "admin" not in groups:
        log.warning(
            "platform_admin_denied",
            account_id=account_id,
            groups=groups if isinstance(groups, list) else None,
        )
        raise HTTPException(403, "requires platform admin")
    return {"account_id": account_id, "platform_admin": True}


__all__ = ["require_platform_admin"]
