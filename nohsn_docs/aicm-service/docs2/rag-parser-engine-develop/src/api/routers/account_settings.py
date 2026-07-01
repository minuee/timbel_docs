"""Account settings — display_name + preferences (호칭 / 톤 / 시간대 / 알림 등).

Phase F10 (KMS-Plus). frontend-v3 ``/settings`` 페이지가 호출.

엔드포인트:
- ``GET  /api/v1/account/settings`` — 현재 사용자의 display_name + preferences 반환.
- ``PATCH /api/v1/account/settings`` — body: ``{display_name?, preferences?}``
  - ``preferences`` 는 부분 머지 (기존 키 보존, 새 키만 덮어쓰기). 키를 제거하려면
    ``null`` 값으로 보내면 해당 키 drop.

설계:
- 스키마는 강제하지 않음 — 프론트가 톤/시간대/알림 등 자유 형식 키 관리.
- display_name 길이 100자 제한 (DB 컬럼 제약과 일치).
- preferences 깊이 1 머지만 — 중첩 객체는 통째로 교체.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/account", tags=["계정 설정"])


# ---------------------------------------------------------------------------
# DB engine — auth_v2.py 와 동일 패턴 (lazy singleton).
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


class SettingsResponse(BaseModel):
    user_id: str
    display_name: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)


class SettingsPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    preferences: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Auth helper
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
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(authorization: str = Header(...)) -> SettingsResponse:
    """현재 사용자의 display_name + preferences 반환."""
    account_id = _account_id_from_bearer(authorization)
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT display_name, preferences FROM accounts "
                    "WHERE id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
    if not row:
        raise HTTPException(404, "account not found")
    display_name, preferences = row
    return SettingsResponse(
        user_id=account_id,
        display_name=display_name,
        preferences=preferences or {},
    )


@router.patch("/settings", response_model=SettingsResponse)
async def patch_settings(
    body: SettingsPatch, authorization: str = Header(...)
) -> SettingsResponse:
    """display_name + preferences 업데이트.

    - display_name: 명시적으로 보낸 경우만 변경. 빈 문자열은 NULL 로 저장.
    - preferences: 깊이 1 머지. 키 값이 ``null`` 이면 해당 키 drop.
    """
    account_id = _account_id_from_bearer(authorization)
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT display_name, preferences FROM accounts "
                    "WHERE id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
        if not row:
            raise HTTPException(404, "account not found")
        cur_display, cur_prefs = row
        cur_prefs = dict(cur_prefs or {})

        new_display = cur_display
        if body.display_name is not None:
            cleaned = body.display_name.strip()
            new_display = cleaned if cleaned else None

        new_prefs = cur_prefs
        if body.preferences is not None:
            new_prefs = dict(cur_prefs)
            # 권한 영역 키는 settings PATCH 로 변경 금지 — 사용자 self-escalation
            # 방지. user_groups 는 /api/v1/account/groups 만이 유일한 writer.
            RESERVED_KEYS = {"user_groups"}
            for k, v in body.preferences.items():
                if k in RESERVED_KEYS:
                    log.warning(
                        "settings_patch_blocked_reserved_key",
                        account_id=account_id,
                        key=k,
                    )
                    continue
                if v is None:
                    new_prefs.pop(k, None)
                else:
                    new_prefs[k] = v

        await conn.execute(
            text(
                "UPDATE accounts "
                "SET display_name = :dn, preferences = CAST(:prefs AS JSONB), "
                "    updated_at = now() "
                "WHERE id = :aid"
            ),
            {
                "aid": account_id,
                "dn": new_display,
                "prefs": _json_dumps(new_prefs),
            },
        )

    log.info("account_settings_patched", account_id=account_id)
    return SettingsResponse(
        user_id=account_id,
        display_name=new_display,
        preferences=new_prefs,
    )


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
