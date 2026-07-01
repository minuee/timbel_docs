"""Admin Settings — runtime feature flag toggle (2026-05-07).

Spec: docs/superpowers/specs/2026-05-07-feature-flags-runtime-toggle.md

Endpoints (platform admin only):
- GET  /api/v1/admin/settings/feature-flags
    → {flags: {sop_rag: bool, ...}, sources: {sop_rag: 'env'|'db'|'redis'|'default', ...}}
- PATCH /api/v1/admin/settings/feature-flags  body {key: 'sop_rag', value: bool}
    → {flags: {...new}, sources: {...}}, audit_logs INSERT, cache evict.

설계:
- platform admin gate (preferences.user_groups 'admin') — Depends(require_platform_admin).
- tenant 격리 — JWT tenant_id 만 update (X-Tenant-ID 매칭 검증).
- 원자 부분 업데이트 — jsonb_set(feature_flags, '{key}', to_jsonb(:value::bool), true).
- 단일 트랜잭션 — UPDATE … RETURNING + audit INSERT.
- commit 후 evict_tenant(tid) — 즉시 cache 반영 + Redis pub/sub publish.
- key whitelist — FeatureFlag enum value 만.
- env override 시 WARNING — DB 변경해도 env kill-switch 가 압도.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.api.auth.platform_role import require_platform_admin
from src.common.feature_flags import (
    FeatureFlag,
    _env_explicit,
    evict_tenant,
    get_all_flags,
)
from src.common.logging import get_logger
from src.core.database import get_db

logger = get_logger(__name__)


router = APIRouter(
    prefix="/api/v1/admin/settings",
    tags=["관리자 — Feature Flags"],
    dependencies=[Depends(require_platform_admin)],
)


# ---------------------------------------------------------------------------
# Auth helpers (token sub + tenant_id 추출).
# ---------------------------------------------------------------------------


def _account_and_tenant(authorization: str) -> tuple[UUID, UUID]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "empty token")
    try:
        payload = decode_token(token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    sub = payload.get("sub")
    tid = payload.get("tenant_id")
    if not sub or not tid:
        raise HTTPException(401, "token missing subject or tenant")
    try:
        return UUID(str(sub)), UUID(str(tid))
    except ValueError as e:
        raise HTTPException(401, f"invalid token claims: {e}") from e


def _resolve_tenant(token_tid: UUID, x_tenant_id: str | None) -> UUID:
    """JWT tenant authoritative + X-Tenant-ID 매칭 검증.

    GPT-5 P1: tenant 불일치는 403 Forbidden 가 의미상 정확.
    """
    if x_tenant_id is not None and x_tenant_id != "":
        if str(x_tenant_id) != str(token_tid):
            raise HTTPException(403, "tenant claim mismatch")
    return token_tid


# ---------------------------------------------------------------------------
# Response / Request models
# ---------------------------------------------------------------------------


class FlagSource(BaseModel):
    value: bool
    source: str  # 'env' | 'db' | 'redis' | 'default'


class FeatureFlagsResponse(BaseModel):
    flags: dict[str, bool]
    sources: dict[str, str]


class FeatureFlagPatchBody(BaseModel):
    key: str = Field(
        ..., description="FeatureFlag enum value (snake_case), e.g. 'sop_rag'."
    )
    value: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _to_response(detail: dict[str, dict[str, Any]]) -> FeatureFlagsResponse:
    return FeatureFlagsResponse(
        flags={k: bool(v["value"]) for k, v in detail.items()},
        sources={k: str(v["source"]) for k, v in detail.items()},
    )


@router.get(
    "/feature-flags",
    response_model=FeatureFlagsResponse,
    summary="모든 feature flag 의 effective 값 + source",
)
async def get_feature_flags(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> FeatureFlagsResponse:
    """현재 tenant 의 모든 flag effective 값 반환.

    source 값:
    - 'env'     — FEATURE_<NAME> env 변수 (kill-switch).
    - 'db'      — tenants.feature_flags JSONB 값.
    - 'redis'   — legacy Redis key.
    - 'default' — 위 셋 다 미설정 (false).
    """
    _aid, token_tid = _account_and_tenant(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    detail = get_all_flags(tenant_id=str(tid))
    return _to_response(detail)


@router.patch(
    "/feature-flags",
    response_model=FeatureFlagsResponse,
    summary="feature flag 토글 — admin only, tenant scope",
)
async def patch_feature_flag(
    body: FeatureFlagPatchBody,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> FeatureFlagsResponse:
    """tenants.feature_flags[key] 를 value 로 set.

    - key whitelist: FeatureFlag enum value (snake_case).
    - 원자 jsonb_set 업데이트 — 다른 키 보존, 동시 PATCH 안전.
    - audit_logs INSERT (event_kind='feature_flag_update', old_value/new_value).
    - 단일 트랜잭션 — commit 또는 rollback 함께.
    - commit 후 evict_tenant(tid) + Redis publish (multi-replica).
    - env override 시 WARNING 로그 (DB 변경은 commit 되나 effective 값 무변).
    """
    aid, token_tid = _account_and_tenant(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)

    # 1. key whitelist — FeatureFlag enum value 만.
    valid_keys = {f.value for f in FeatureFlag}
    if body.key not in valid_keys:
        raise HTTPException(
            400, f"unknown flag '{body.key}'. valid: {sorted(valid_keys)}"
        )

    # 2. env override 검사 — 명시값 있으면 DB 변경해도 effective 값 무변.
    flag_enum = FeatureFlag(body.key)
    env_explicit_val = _env_explicit(flag_enum)
    if env_explicit_val is not None:
        logger.warning(
            "feature_flag_patch_overridden_by_env",
            tenant_id=str(tid),
            actor_id=str(aid),
            flag=body.key,
            env_value=env_explicit_val,
            requested_value=body.value,
            note="env FEATURE_* 가 kill-switch — DB 변경 commit 되나 effective 값 무변",
        )

    # 3. 원자 업데이트 + audit INSERT, 단일 트랜잭션.
    try:
        # old value 캡처 (FOR UPDATE — 동일 row 직렬화).
        old_row = (
            await db.execute(
                text(
                    "SELECT feature_flags FROM tenants "
                    "WHERE id = :tid FOR UPDATE"
                ),
                {"tid": tid},
            )
        ).first()
        if old_row is None:
            raise HTTPException(404, "tenant not found")
        old_flags_full = dict(old_row[0] or {})
        old_value_for_key = old_flags_full.get(body.key)

        # UPDATE — jsonb_set 으로 부분 업데이트 (다른 키 보존).
        # 검증 (2026-05-07 라이브 테스트) — asyncpg 에서 ARRAY[:key] bind 정상 동작.
        # GPT-5 P0 false positive 였음 (psycopg2 와 다름). key 는 FeatureFlag
        # enum value whitelist 통과 — SQL injection 0. asyncpg dialect 가 single
        # element TEXT[] 배열로 정확히 bind.
        upd_stmt = text(
            "UPDATE tenants SET feature_flags = "
            "jsonb_set(COALESCE(feature_flags, '{}'::jsonb), "
            "ARRAY[:key], to_jsonb(CAST(:val AS BOOLEAN)), true) "
            "WHERE id = :tid RETURNING feature_flags"
        )
        upd_row = (
            await db.execute(
                upd_stmt,
                {"tid": tid, "key": body.key, "val": body.value},
            )
        ).first()
        new_flags_full = dict(upd_row[0] or {}) if upd_row is not None else {}

        # audit_logs INSERT — event_kind='feature_flag_update'.
        # GPT-5 P1: explicit ::jsonb cast — 드라이버 변동에도 안전.
        await db.execute(
            text(
                "INSERT INTO audit_logs "
                "(id, tenant_id, user_id, action, event_kind, "
                "old_value, new_value, created_at) "
                "VALUES (:lid, :tid, :uid, 'UPDATE', 'feature_flag_update', "
                "CAST(:old_val AS JSONB), CAST(:new_val AS JSONB), now())"
            ),
            {
                "lid": uuid4(),
                "tid": tid,
                "uid": aid,
                "old_val": _jsonb_dumps({body.key: old_value_for_key}),
                "new_val": _jsonb_dumps({body.key: body.value}),
            },
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(
            "feature_flag_patch_failed",
            tenant_id=str(tid),
            actor_id=str(aid),
            flag=body.key,
            error=str(e),
        )
        raise HTTPException(500, f"feature flag update failed: {e}") from e

    # 4. commit 후 cache evict + Redis publish (multi-replica 일관성).
    try:
        evict_tenant(str(tid))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "feature_flag_cache_evict_failed", tenant_id=str(tid), error=str(e)
        )

    logger.info(
        "feature_flag_updated",
        tenant_id=str(tid),
        actor_id=str(aid),
        flag=body.key,
        old_value=old_value_for_key,
        new_value=body.value,
        env_override=env_explicit_val,
    )

    # 5. 새 effective 값 반환 (env override 가 있으면 그 값).
    detail = get_all_flags(tenant_id=str(tid))
    return _to_response(detail)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonb_dumps(d: dict) -> str:
    """psycopg2 가 dict 자체로 JSONB bind 안 받을 때 명시적 직렬화."""
    import json

    return json.dumps(d, ensure_ascii=False, default=str)
