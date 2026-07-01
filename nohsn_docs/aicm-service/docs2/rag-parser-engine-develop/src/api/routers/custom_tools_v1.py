"""/api/v1/custom-tools — custom webhook tool CRUD + 카탈로그.

admin/owner role 필수 (writes). list/read 는 member 도 가능.

Endpoints:
- POST   /api/v1/custom-tools                       — 등록 (admin+)
- GET    /api/v1/custom-tools                       — 목록 (member+) — ToolPicker 카탈로그 용도
- GET    /api/v1/custom-tools/examples              — 공식 서비스 예시 카탈로그 (admin+)
- POST   /api/v1/custom-tools/from-example/{id}    — 예시 복사 + auth fill 후 등록 (admin+)
- GET    /api/v1/custom-tools/{id}                  — 단건 조회 (member+)
- PATCH  /api/v1/custom-tools/{id}                  — 수정 (admin+)
- DELETE /api/v1/custom-tools/{id}                  — soft delete (admin+)
- POST   /api/v1/custom-tools/{id}/test             — admin panel 테스트 호출 (admin+)

auth_headers 는 Fernet 암호화 저장, 응답에 절대 노출 X.
builtin tools_v1.py (다른 background 작업) 와 충돌 없음 — 별도 prefix.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.api.schemas.custom_tool import (
    CustomToolCreate,
    CustomToolResponse,
    CustomToolTestRequest,
    CustomToolUpdate,
)
from src.common.config import settings
from src.common.crypto.fernet import encrypt_dict

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/custom-tools", tags=["custom-tools"])


# ---------------------------------------------------------------------------
# Engine — 전용 pool (main.py get_db 세션과 별개, agents_v1 패턴 통일)
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
# Auth helpers — agents_v1 와 동일 패턴
# ---------------------------------------------------------------------------


def _account_from_token(authorization: str) -> tuple[UUID, str | None, str]:
    """Bearer token → (account_id, tenant_id, role). 401 if invalid."""
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
        return UUID(str(sub)), payload.get("tenant_id"), payload.get("role") or "member"
    except ValueError as e:
        raise HTTPException(401, f"invalid subject: {e}") from e


def _resolve_tenant(token_tid: str | None, x_tenant_id: str | None) -> UUID:
    """JWT tenant claim authoritative — Phase 1.5A Task 8c.2 (2026-05-07).

    이전: ``X-Tenant-ID`` 우선 → cross-tenant 위장 가능 (membership 검사 없는
    custom_tools 에서는 직접적 자료 노출).
    이제: token claim 만 신뢰. 헤더 있으면 claim 과 일치해야 통과.
    """
    if not token_tid:
        raise HTTPException(
            400, "tenant scope missing — supply X-Tenant-ID or relogin"
        )
    if x_tenant_id is not None and x_tenant_id != "":
        if str(x_tenant_id) != str(token_tid):
            raise HTTPException(401, "tenant claim mismatch")
    try:
        return UUID(str(token_tid))
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e


def _require_admin_role(role: str) -> None:
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _fetch_tool_row(tool_id: UUID, tenant_id: UUID) -> dict[str, Any]:
    """단건 조회 — 없으면 404."""
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, tenant_id, name, description, category, "
                    "endpoint_url, method, input_schema, output_schema, "
                    "is_active, created_at, updated_at "
                    "FROM custom_tools "
                    "WHERE id = :id AND tenant_id = :tid LIMIT 1"
                ),
                {"id": tool_id, "tid": tenant_id},
            )
        ).mappings().first()
    if not row:
        raise HTTPException(404, "custom tool not found")
    return dict(row)


def _row_to_response(row: dict[str, Any]) -> CustomToolResponse:
    return CustomToolResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        description=row["description"],
        category=row["category"],
        endpoint_url=row["endpoint_url"],
        method=row["method"],
        input_schema=row.get("input_schema") or {},
        output_schema=row.get("output_schema") or {},
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=CustomToolResponse, status_code=201)
async def create_custom_tool(
    body: CustomToolCreate,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
):
    """webhook custom tool 등록 (admin+). auth_headers Fernet 암호화 저장."""
    aid, token_tid, role = _account_from_token(authorization)
    _require_admin_role(role)
    tenant_id = _resolve_tenant(token_tid, x_tenant_id)

    config_payload = {"auth_headers": body.auth_headers}
    encrypted = encrypt_dict(config_payload)

    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO custom_tools "
                    "(tenant_id, name, description, category, endpoint_url, "
                    "method, config_encrypted, input_schema, output_schema, "
                    "is_active, created_by) "
                    "VALUES (:tenant_id, :name, :description, :category, "
                    ":endpoint_url, :method, :config_encrypted, "
                    ":input_schema, :output_schema, TRUE, :created_by) "
                    "RETURNING id, tenant_id, name, description, category, "
                    "endpoint_url, method, input_schema, output_schema, "
                    "is_active, created_at, updated_at"
                ),
                {
                    "tenant_id": tenant_id,
                    "name": body.name,
                    "description": body.description,
                    "category": body.category,
                    "endpoint_url": body.endpoint_url,
                    "method": body.method,
                    "config_encrypted": encrypted,
                    "input_schema": body.input_schema,
                    "output_schema": body.output_schema,
                    "created_by": aid,
                },
            )
        ).mappings().first()

    if not row:
        raise HTTPException(500, "insert failed")

    log.info(
        "custom_tool_created",
        extra={"name": body.name, "tenant_id": str(tenant_id), "by": str(aid)},
    )
    return _row_to_response(dict(row))


@router.get("", response_model=list[CustomToolResponse])
async def list_custom_tools(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
):
    """tenant 의 활성 custom tool 목록. member+ 접근 가능.
    GET /api/v1/custom-tools — ToolPicker 카탈로그 별도 endpoint.
    """
    aid, token_tid, role = _account_from_token(authorization)
    tenant_id = _resolve_tenant(token_tid, x_tenant_id)

    eng = _get_engine()
    async with eng.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, tenant_id, name, description, category, "
                    "endpoint_url, method, input_schema, output_schema, "
                    "is_active, created_at, updated_at "
                    "FROM custom_tools "
                    "WHERE tenant_id = :tid AND is_active = TRUE "
                    "ORDER BY created_at DESC"
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()

    return [_row_to_response(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Example catalog — 공식 서비스 webhook 예시
# ---------------------------------------------------------------------------

_EXAMPLES_DIR = (
    Path(__file__).parent.parent.parent
    / "agent_framework/agent_templates/custom_tool_examples"
)


@router.get("/examples", response_model=list[dict])
async def list_custom_tool_examples(
    authorization: str = Header(...),
):
    """공식 서비스 webhook 예시 카탈로그 — admin 이 복사 + auth fill 후 사용.

    auth 는 admin+ 만 접근 가능 (member 에게 setup_instructions 노출 불필요).
    """
    _account_from_token(authorization)  # 유효한 토큰인지만 확인
    out: list[dict] = []
    for f in sorted(_EXAMPLES_DIR.glob("*.json")):
        with f.open(encoding="utf-8") as fp:
            out.append(json.load(fp))
    return out


@router.post("/from-example/{example_id}", response_model=CustomToolResponse, status_code=201)
async def create_from_example(
    example_id: str,
    body: dict,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
):
    """예시를 복사해서 tenant 에 등록.

    body 에 endpoint_url (placeholder 교체) 과 auth_headers 를 명시하면
    해당 값으로 덮어씁니다.
    """
    aid, token_tid, role = _account_from_token(authorization)
    _require_admin_role(role)
    tenant_id = _resolve_tenant(token_tid, x_tenant_id)

    example_file = _EXAMPLES_DIR / f"{example_id}.json"
    if not example_file.exists():
        raise HTTPException(404, f"example '{example_id}' not found")

    with example_file.open(encoding="utf-8") as fp:
        example = json.load(fp)

    config_payload = {"auth_headers": body.get("auth_headers", example.get("auth_headers", {}))}
    encrypted = encrypt_dict(config_payload)

    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO custom_tools "
                    "(tenant_id, name, description, category, endpoint_url, "
                    "method, config_encrypted, input_schema, output_schema, "
                    "is_active, created_by) "
                    "VALUES (:tenant_id, :name, :description, :category, "
                    ":endpoint_url, :method, :config_encrypted, "
                    ":input_schema, :output_schema, TRUE, :created_by) "
                    "RETURNING id, tenant_id, name, description, category, "
                    "endpoint_url, method, input_schema, output_schema, "
                    "is_active, created_at, updated_at"
                ),
                {
                    "tenant_id": tenant_id,
                    "name": example["name"],
                    "description": example["description"],
                    "category": example.get("category", "custom"),
                    "endpoint_url": body.get("endpoint_url", example["endpoint_url"]),
                    "method": example["method"],
                    "config_encrypted": encrypted,
                    "input_schema": json.dumps(example.get("input_schema", {})),
                    "output_schema": json.dumps(example.get("output_schema", {})),
                    "created_by": aid,
                },
            )
        ).mappings().first()

    if not row:
        raise HTTPException(500, "insert failed")

    log.info(
        "custom_tool_created_from_example",
        extra={"example_id": example_id, "tenant_id": str(tenant_id), "by": str(aid)},
    )
    return _row_to_response(dict(row))


@router.get("/{tool_id}", response_model=CustomToolResponse)
async def get_custom_tool(
    tool_id: UUID,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
):
    """단건 조회. member+ 접근 가능."""
    aid, token_tid, role = _account_from_token(authorization)
    tenant_id = _resolve_tenant(token_tid, x_tenant_id)
    row = await _fetch_tool_row(tool_id, tenant_id)
    return _row_to_response(row)


@router.patch("/{tool_id}", response_model=CustomToolResponse)
async def update_custom_tool(
    tool_id: UUID,
    body: CustomToolUpdate,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
):
    """부분 업데이트 (admin+). auth_headers 변경 시 config_encrypted 재계산."""
    aid, token_tid, role = _account_from_token(authorization)
    _require_admin_role(role)
    tenant_id = _resolve_tenant(token_tid, x_tenant_id)

    # 현재 row 확인
    await _fetch_tool_row(tool_id, tenant_id)

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(400, "no fields to update")

    set_clauses: list[str] = []
    params: dict[str, Any] = {"id": tool_id, "tid": tenant_id}

    # auth_headers → config_encrypted 재계산
    if "auth_headers" in patch:
        ah = patch.pop("auth_headers")
        params["config_encrypted"] = encrypt_dict({"auth_headers": ah})
        set_clauses.append("config_encrypted = :config_encrypted")

    field_map = {
        "description": "description",
        "category": "category",
        "endpoint_url": "endpoint_url",
        "method": "method",
        "input_schema": "input_schema",
        "output_schema": "output_schema",
        "is_active": "is_active",
    }
    for k, col in field_map.items():
        if k in patch:
            params[k] = patch[k]
            set_clauses.append(f"{col} = :{k}")

    set_clauses.append("updated_at = now()")
    set_sql = ", ".join(set_clauses)

    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    f"UPDATE custom_tools SET {set_sql} "
                    "WHERE id = :id AND tenant_id = :tid "
                    "RETURNING id, tenant_id, name, description, category, "
                    "endpoint_url, method, input_schema, output_schema, "
                    "is_active, created_at, updated_at"
                ),
                params,
            )
        ).mappings().first()

    if not row:
        raise HTTPException(404, "custom tool not found or update failed")

    log.info("custom_tool_updated", extra={"id": str(tool_id), "by": str(aid)})
    return _row_to_response(dict(row))


@router.delete("/{tool_id}", status_code=204)
async def delete_custom_tool(
    tool_id: UUID,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
):
    """soft delete — is_active = FALSE (admin+)."""
    aid, token_tid, role = _account_from_token(authorization)
    _require_admin_role(role)
    tenant_id = _resolve_tenant(token_tid, x_tenant_id)

    eng = _get_engine()
    async with eng.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE custom_tools SET is_active = FALSE, updated_at = now() "
                "WHERE id = :id AND tenant_id = :tid AND is_active = TRUE"
            ),
            {"id": tool_id, "tid": tenant_id},
        )
    if result.rowcount == 0:
        raise HTTPException(404, "custom tool not found")

    log.info("custom_tool_deleted", extra={"id": str(tool_id), "by": str(aid)})


@router.post("/{tool_id}/test", response_model=dict)
async def test_custom_tool(
    tool_id: UUID,
    body: CustomToolTestRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
):
    """admin panel '도구 테스트' 버튼 — 등록 후 실 webhook 호출 검증.

    성공: {"ok": True, "tool": str, "status_code": int, "data": dict}
    실패: {"ok": False, "error": str}  — HTTP 200 으로 래핑 (UI 에서 구분 표시)
    """
    aid, token_tid, role = _account_from_token(authorization)
    _require_admin_role(role)
    tenant_id = _resolve_tenant(token_tid, x_tenant_id)

    # tool 존재 확인
    row = await _fetch_tool_row(tool_id, tenant_id)
    if not row["is_active"]:
        raise HTTPException(400, "tool is inactive — cannot test")

    from src.agent_framework.tools.webhook_caller import (
        CustomToolCallError,
        CustomToolNotFound,
        call_custom_tool,
    )
    from src.core.database import get_db as _get_db_gen

    # test_custom_tool 은 일회성 세션이 필요 — create_async_engine 세션 대신
    # 모듈 engine 공유로 간단히 처리.
    from sqlalchemy.ext.asyncio import AsyncSession

    eng = _get_engine()
    async with AsyncSession(eng) as session:
        try:
            result = await call_custom_tool(
                session,
                tenant_id,
                row["name"],
                body.input_data,
            )
            return result
        except CustomToolNotFound as e:
            return {"ok": False, "error": str(e)}
        except CustomToolCallError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("custom_tool_test_unexpected", extra={"id": str(tool_id)})
            return {"ok": False, "error": f"unexpected error: {e!r}"}
