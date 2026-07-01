"""``/api/v1/verification`` — KMS-Plus P0.2 backend wrapper layer (PR P9 의존).

frontend-v3 Verification Suite (PR P9) 가 호출. 시나리오/실행/제안 조회 +
실행 시작 stub. admin 권한 (``preferences.user_groups`` 에 'admin' 포함)
필요. 실 실행 로직은 P9 에서.

엔드포인트
----------
- GET  /api/v1/verification/scenarios             — yaml 첫 5줄 + truncate flag
- GET  /api/v1/verification/scenarios/{id}        — 전체 yaml (admin)
- GET  /api/v1/verification/runs?limit=20         — summary (trace 제외)
- GET  /api/v1/verification/runs/{id}/trace       — 전체 trace (admin, audit log)
- GET  /api/v1/verification/proposals?status=...  — summary (evidence 200자)
- GET  /api/v1/verification/proposals/{id}        — 전체 evidence (admin)
- POST /api/v1/verification/runs/start?scenario_id=<id>  — pending row 생성

P0.2 hardening (codex 2차 review):
    - runs/proposals 가 trace/evidence 전체를 반환하던 부분 → summary 만.
    - PII/secret leak 방지 + 페이로드 크기 절감.
    - runs/start 가 invalid scenario_id 도 통과시키던 부분 → 사전 SELECT 검증.
    - 동시 pending 중복 row 방지 — 409 conflict.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger


log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/verification", tags=["verification-v1"])


_engine: AsyncEngine | None = None

# P0.2 hardening — debug payload truncation 한도. 일반 패턴: 코드를 읽지 않은
# 사용자도 식별 가능한 짧은 미리보기.
_YAML_PREVIEW_LINES = 5
_EVIDENCE_PREVIEW_CHARS = 200


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


def _account_id_from_bearer(authorization: str) -> UUID:
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
    try:
        return UUID(str(sub))
    except ValueError as e:
        raise HTTPException(401, f"invalid subject: {e}") from e


async def _require_admin(account_id: UUID) -> None:
    """``accounts.preferences.user_groups`` 에 'admin' 포함 시에만 통과.

    manifest 와 동일한 admin 식별 규칙. tenant 별 role (owner/admin) 과는 별개로
    "시스템 운영자" 그룹을 표현. 옛 ``tenant_memberships.role`` 기반 추가 게이트
    가 필요하면 P9 에서 강화.
    """
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
        raise HTTPException(403, "account not found or not admin")
    raw_prefs = row[0] or {}
    if isinstance(raw_prefs, str):
        try:
            raw_prefs = json.loads(raw_prefs)
        except Exception:
            raw_prefs = {}
    if not isinstance(raw_prefs, dict):
        raise HTTPException(403, "admin role required")
    user_groups = raw_prefs.get("user_groups") or []
    if not isinstance(user_groups, list) or "admin" not in user_groups:
        raise HTTPException(403, "admin role required")


def _coerce_jsonb(val: Any, default: Any) -> Any:
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return default


def _iso_or_none(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else None


def _yaml_preview(yaml_text: str | None) -> tuple[str, bool]:
    """yaml_text 의 처음 5줄만 반환 + truncated flag.

    None / 빈 문자열은 그대로 반환 (truncated=False).
    """
    if not yaml_text:
        return "", False
    lines = yaml_text.splitlines()
    if len(lines) <= _YAML_PREVIEW_LINES:
        return yaml_text, False
    return "\n".join(lines[:_YAML_PREVIEW_LINES]), True


def _evidence_summary(evidence: Any) -> tuple[str, bool]:
    """evidence (json 또는 str) → 200자 미리보기 + truncated flag."""
    if evidence is None:
        return "", False
    if isinstance(evidence, (dict, list)):
        s = json.dumps(evidence, ensure_ascii=False)
    else:
        s = str(evidence)
    if len(s) <= _EVIDENCE_PREVIEW_CHARS:
        return s, False
    return s[:_EVIDENCE_PREVIEW_CHARS], True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/scenarios")
async def list_scenarios(
    authorization: str = Header(...),
) -> dict[str, list[dict[str, Any]]]:
    """시나리오 목록 — yaml 은 첫 5줄 미리보기. 전체 yaml 은 detail endpoint."""
    aid = _account_id_from_bearer(authorization)
    await _require_admin(aid)
    eng = _get_engine()
    async with eng.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, name, yaml_text, last_pass_at, created_at "
                    "FROM verification_scenarios ORDER BY name"
                )
            )
        ).all()
    items: list[dict[str, Any]] = []
    for r in rows:
        preview, truncated = _yaml_preview(r[2])
        items.append(
            {
                "id": str(r[0]),
                "name": r[1],
                "yaml_preview": preview,
                "yaml_truncated": truncated,
                "last_pass_at": _iso_or_none(r[3]),
                "created_at": _iso_or_none(r[4]),
            }
        )
    return {"items": items}


@router.get("/scenarios/{scenario_id}")
async def get_scenario_detail(
    scenario_id: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    """전체 yaml 반환 (admin only). audit log 1줄."""
    aid = _account_id_from_bearer(authorization)
    await _require_admin(aid)
    try:
        sid = UUID(scenario_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid scenario_id: {e}") from e
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, name, yaml_text, last_pass_at, created_at "
                    "FROM verification_scenarios WHERE id = :sid"
                ),
                {"sid": sid},
            )
        ).first()
    if not row:
        raise HTTPException(404, "scenario not found")
    log.info(
        "verification_scenario_detail_accessed",
        account_id=str(aid),
        scenario_id=str(sid),
    )
    return {
        "id": str(row[0]),
        "name": row[1],
        "yaml_text": row[2],
        "last_pass_at": _iso_or_none(row[3]),
        "created_at": _iso_or_none(row[4]),
    }


@router.get("/runs")
async def list_runs(
    authorization: str = Header(...),
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, list[dict[str, Any]]]:
    """실행 목록 — summary (trace 제외). 전체 trace 는 detail endpoint."""
    aid = _account_id_from_bearer(authorization)
    await _require_admin(aid)
    eng = _get_engine()
    async with eng.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, scenario_id, started_at, finished_at, status, "
                    "       trace, duration_ms "
                    "FROM verification_runs ORDER BY started_at DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
        ).all()
    items: list[dict[str, Any]] = []
    for r in rows:
        # trace 자체는 반환하지 않고 has_trace boolean 만.
        raw_trace = r[5]
        if isinstance(raw_trace, str):
            try:
                raw_trace = json.loads(raw_trace)
            except Exception:
                raw_trace = None
        has_trace = bool(raw_trace) and raw_trace not in ({}, [])
        items.append(
            {
                "id": str(r[0]),
                "scenario_id": str(r[1]) if r[1] else None,
                "started_at": _iso_or_none(r[2]),
                "finished_at": _iso_or_none(r[3]),
                "status": r[4],
                "has_trace": has_trace,
                "duration_ms": r[6],
            }
        )
    return {"items": items}


@router.get("/runs/{run_id}/trace")
async def get_run_trace(
    run_id: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    """전체 trace JSON 반환 (admin only). audit log 1줄."""
    aid = _account_id_from_bearer(authorization)
    await _require_admin(aid)
    try:
        rid = UUID(run_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid run_id: {e}") from e
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, scenario_id, status, trace "
                    "FROM verification_runs WHERE id = :rid"
                ),
                {"rid": rid},
            )
        ).first()
    if not row:
        raise HTTPException(404, "run not found")
    log.info(
        "verification_run_trace_accessed",
        account_id=str(aid),
        run_id=str(rid),
    )
    return {
        "id": str(row[0]),
        "scenario_id": str(row[1]) if row[1] else None,
        "status": row[2],
        "trace": _coerce_jsonb(row[3], {}),
    }


@router.get("/proposals")
async def list_proposals(
    authorization: str = Header(...),
    status: str = Query("proposed"),
) -> dict[str, list[dict[str, Any]]]:
    """제안 목록 — evidence 는 200자 미리보기. 전체 evidence 는 detail endpoint."""
    aid = _account_id_from_bearer(authorization)
    await _require_admin(aid)
    eng = _get_engine()
    async with eng.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, source, suggested_yaml, evidence, status, "
                    "       created_at, reviewed_at, reviewer_account_id "
                    "FROM verification_proposals "
                    "WHERE status = :st ORDER BY created_at DESC LIMIT 200"
                ),
                {"st": status},
            )
        ).all()
    items: list[dict[str, Any]] = []
    for r in rows:
        # suggested_yaml 도 미리보기.
        yaml_preview, yaml_truncated = _yaml_preview(r[2])
        evidence_preview, evidence_truncated = _evidence_summary(
            _coerce_jsonb(r[3], None)
        )
        items.append(
            {
                "id": str(r[0]),
                "source": r[1],
                "yaml_preview": yaml_preview,
                "yaml_truncated": yaml_truncated,
                "evidence_preview": evidence_preview,
                "evidence_truncated": evidence_truncated,
                "status": r[4],
                "created_at": _iso_or_none(r[5]),
                "reviewed_at": _iso_or_none(r[6]),
                "reviewer_account_id": str(r[7]) if r[7] else None,
            }
        )
    return {"items": items}


@router.get("/proposals/{proposal_id}")
async def get_proposal_detail(
    proposal_id: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    """전체 yaml + evidence 반환 (admin only). audit log 1줄."""
    aid = _account_id_from_bearer(authorization)
    await _require_admin(aid)
    try:
        pid = UUID(proposal_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid proposal_id: {e}") from e
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, source, suggested_yaml, evidence, status, "
                    "       created_at, reviewed_at, reviewer_account_id "
                    "FROM verification_proposals WHERE id = :pid"
                ),
                {"pid": pid},
            )
        ).first()
    if not row:
        raise HTTPException(404, "proposal not found")
    log.info(
        "verification_proposal_detail_accessed",
        account_id=str(aid),
        proposal_id=str(pid),
    )
    return {
        "id": str(row[0]),
        "source": row[1],
        "suggested_yaml": row[2],
        "evidence": _coerce_jsonb(row[3], {}),
        "status": row[4],
        "created_at": _iso_or_none(row[5]),
        "reviewed_at": _iso_or_none(row[6]),
        "reviewer_account_id": str(row[7]) if row[7] else None,
    }


@router.post("/runs/start")
async def start_run(
    authorization: str = Header(...),
    scenario_id: str | None = Query(None),
) -> dict[str, str]:
    """pending 상태 verification_runs row 생성. 실 실행은 P9 background worker.

    P0.2 hardening (codex 2차):
        - scenario_id 가 주어졌으나 verification_scenarios 에 없으면 404
          (FK 위반 raw error 가 500 으로 새지 않게 사전 차단).
        - 같은 scenario 의 ``pending`` / ``running`` row 가 이미 있으면 409
          (중복 실행 / race 차단).
    """
    aid = _account_id_from_bearer(authorization)
    await _require_admin(aid)
    sid_uuid: UUID | None = None
    if scenario_id:
        try:
            sid_uuid = UUID(scenario_id)
        except ValueError as e:
            raise HTTPException(400, f"invalid scenario_id: {e}") from e
    eng = _get_engine()
    async with eng.begin() as conn:
        # 1. 시나리오 존재 검증.
        if sid_uuid is not None:
            r = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM verification_scenarios "
                        "WHERE id = :sid LIMIT 1"
                    ),
                    {"sid": sid_uuid},
                )
            ).first()
            if not r:
                raise HTTPException(404, "scenario not found")
            # 2. 동일 시나리오 pending/running 중복 차단.
            dup = (
                await conn.execute(
                    text(
                        "SELECT id FROM verification_runs "
                        "WHERE scenario_id = :sid "
                        "  AND status IN ('pending', 'running') "
                        "LIMIT 1"
                    ),
                    {"sid": sid_uuid},
                )
            ).first()
            if dup:
                raise HTTPException(
                    409,
                    "another pending/running run exists for this scenario",
                )
        row = await conn.execute(
            text(
                "INSERT INTO verification_runs (scenario_id, status) "
                "VALUES (:sid, 'pending') RETURNING id"
            ),
            {"sid": sid_uuid},
        )
        run_id = row.scalar_one()
    return {"run_id": str(run_id)}
