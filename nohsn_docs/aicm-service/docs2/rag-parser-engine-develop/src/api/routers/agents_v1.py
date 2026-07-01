"""/api/v1/agents — External Agent 운영자 측 라우터 (JWT 인증).

frontend-v3 ``AgentsListPage`` / ``AgentDetailPage`` 가 호출.

Endpoint 요약:
- ``GET    /api/v1/agents``                          — 현재 tenant 의 agent 목록
- ``POST   /api/v1/agents``                          — agent 생성
- ``GET    /api/v1/agents/{agent_id}``               — 단건 상세
- ``PATCH  /api/v1/agents/{agent_id}``               — owner/admin: 부분 업데이트
- ``DELETE /api/v1/agents/{agent_id}``               — owner/admin: soft delete
- ``POST   /api/v1/agents/{agent_id}/test-chat``     — sandbox SSE 스트림 (영속 X)
- ``GET    /api/v1/agents/{agent_id}/api-keys``      — 메타데이터만 (key/hash 노출 X)
- ``POST   /api/v1/agents/{agent_id}/api-keys``      — 새 키 발급 (응답에만 평문)
- ``DELETE /api/v1/agents/{agent_id}/api-keys/{kid}``— owner/admin: soft revoke
- ``GET    /api/v1/agents/{agent_id}/logs``          — 최근 N 행

Phase P3.B (KMS-Plus). 외부 호출자 측은 ``external_agent_v1.py`` 참조.
"""
from __future__ import annotations

import json
import pathlib
import secrets
from typing import Any
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from src.agent_framework.api.dependencies import get_agent_engine
from src.agent_framework.llm.vllm_adapter import VLLMAdapter
from src.agent_framework.observability.latency_probe import LatencyProbe
from src.agent_framework.runtime.agent_context import AgentContext
from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.plan_router import CATEGORY_TOOLS
from src.agent_framework.runtime.sender_context import SenderContext
from src.api.auth.jwt_utils import InvalidToken, decode_token, hash_password
from src.api.schemas.agent import (
    AgentBulkSuggestRequest,
    AgentBulkSuggestResponse,
    AgentDraftRequest,
    AgentDraftResponse,
    AgentSuggestRequest,
    AgentSuggestResponse,
    InterviewDraftRequest,
    InterviewDraftResponse,
    _validate_tool_scope_overrides,
)
from src.common.config import settings
from src.common.feature_flags import FeatureFlag, is_enabled
from src.core.repositories.agent_repository import AgentRepository
from src.core.services.audit_service import record_action


router = APIRouter(prefix="/api/v1/agents", tags=["agents-v1"])


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


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

    이전: ``X-Tenant-ID`` 우선 → 다른 tenant 의 멤버일 경우 cross-tenant 위장 가능
    (membership check 통과해도 JWT 와 무관한 tenant 로 작업 가능).
    이제: token claim 만 신뢰. 헤더가 있으면 일치해야 통과.
    """
    if not token_tid:
        raise HTTPException(400, "tenant scope missing — supply X-Tenant-ID or relogin")
    if x_tenant_id is not None and x_tenant_id != "":
        if str(x_tenant_id) != str(token_tid):
            raise HTTPException(401, "tenant claim mismatch")
    try:
        return UUID(str(token_tid))
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e


async def _verify_membership(account_id: UUID, tenant_id: UUID) -> str:
    """tenant 의 role 반환. 멤버 아니면 403."""
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT role FROM tenant_memberships "
                    "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
                ),
                {"aid": account_id, "tid": tenant_id},
            )
        ).first()
    if not row:
        raise HTTPException(403, "not a member of this tenant")
    return row[0]


def _parse_uuid(raw: str, field: str = "id") -> UUID:
    try:
        return UUID(raw)
    except ValueError as e:
        raise HTTPException(400, f"invalid {field}: {e}") from e


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AgentOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None = None
    persona: str = ""
    system_prompt: str = ""
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_repos: list[str] = Field(default_factory=list)
    is_active: bool = True
    rate_limit_per_min: int = 60
    created_by: str
    created_at: str | None = None
    updated_at: str | None = None
    # 058 — admin (Locus 어시스턴트, 1 per tenant) vs role (사용자 정의 하부 에이전트).
    kind: str = "role"
    # Phase 1.5B-γ — multi-agent 위임 대상 ID 목록 (uuid string).
    delegate_to_agent_ids: list[str] = Field(default_factory=list)
    # Phase 1 admin fields — frontend AgentFull / AgentSopPage 가 의존.
    # GET /agents/{id} 응답이 이 필드들을 포함하지 않으면 SOP 페이지가 빈 화면이 됨
    # (실 데이터가 DB 에 있어도). 기본값은 안전한 빈 값.
    goal: str = ""
    guidelines_md: str = ""
    primary_repo_ids: list[str] = Field(default_factory=list)
    fallback_repo_ids: list[str] = Field(default_factory=list)
    sop_repo_ids: list[str] = Field(default_factory=list)
    knowledge_isolation: str = "priority"
    allowed_tools: list[str] = Field(default_factory=list)
    done_when: str | None = None
    test_mode_visible: bool = True
    template_id: str | None = None
    # 069 (Plan A v3) — 4-mode 웹검색 enum. default 'off'.
    web_search_mode: str = "off"
    # 075 (Phase 3 #154) — agent 별 도구 scope override. default {}.
    tool_scope_overrides: dict[str, str] = Field(default_factory=dict)


class AgentListOut(BaseModel):
    items: list[AgentOut]


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    persona: str | None = ""
    system_prompt: str | None = ""
    allowed_skills: list[str] | None = None
    allowed_repos: list[str] | None = None
    rate_limit_per_min: int | None = 60
    # 058 — 신규 생성 default 'role'. admin 변환은 별도 endpoint / migration 만.
    kind: str | None = "role"
    # Phase 1.5B-γ — 신규 생성 시점에서 delegate 지정 (선택).
    delegate_to_agent_ids: list[str] | None = None


class AgentPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    persona: str | None = None
    system_prompt: str | None = None
    allowed_skills: list[str] | None = None
    allowed_repos: list[str] | None = None
    rate_limit_per_min: int | None = None
    is_active: bool | None = None
    # Phase 1.5B-γ — admin 만 편집 가능. 검증은 update_agent 에서 수행.
    delegate_to_agent_ids: list[str] | None = None
    # 069 (Plan A v3) — 4-mode 웹검색 enum. None=미변경.
    web_search_mode: str | None = None
    # 2026-05-07 (#147 LibraryDocumentPicker 저장소 단위 옵션) —
    # 기존 admin agent edit 페이지가 이미 PATCH body 에 포함하던 필드를 정식 처리.
    # 이전에는 Pydantic 이 silently drop 해서 SOP/Primary repo 변경이 무시되었음
    # (regression). None=미변경, []=빈 배열로 명시 설정.
    primary_repo_ids: list[str] | None = None
    fallback_repo_ids: list[str] | None = None
    sop_repo_ids: list[str] | None = None
    # 075 (Phase 3 #154) — agent 별 도구 scope override.
    # None=미변경, {}=클리어, {"<tool>": "<scope>"}=설정.
    # 승격 금지 + 크기 상한 — update_agent 가 _validate_tool_scope_overrides 호출.
    tool_scope_overrides: dict[str, str] | None = None
    # D42 (2026-05-11) — 사용자 보고: "편집에서, 도구를 활성화 해도, 그게 적용이
    # 안되는것 같아". 원인: AgentPatch 가 allowed_tools / goal / guidelines_md /
    # knowledge_isolation / done_when / test_mode_visible 필드를 *전혀 정의하지
    # 않아* Pydantic 이 silently drop, UPDATE SQL 도 같은 필드 누락. primary_repo
    # 와 동일 regression 패턴 (line 210-213 history 참고).
    #
    # frontend EditTabContent.tsx (ToolPicker) / AgentEditPage.tsx 가 이 필드들을
    # PATCH body 로 전송하지만 백엔드가 모두 무시 → DB 변경 0 → runtime 영향 X.
    # None=미변경, [] / "" / False=명시 설정.
    goal: str | None = None
    guidelines_md: str | None = None
    knowledge_isolation: str | None = None
    allowed_tools: list[str] | None = None
    done_when: str | None = None
    test_mode_visible: bool | None = None


class TestChatRequest(BaseModel):
    text: str = Field(..., min_length=1)
    session_id: str | None = None


class ApiKeyMetaOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    last_used_at: str | None = None
    created_at: str | None = None
    revoked_at: str | None = None


class ApiKeyListOut(BaseModel):
    items: list[ApiKeyMetaOut]


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ApiKeyCreatedOut(BaseModel):
    """발급 직후 1회 응답 — ``key`` 필드는 plaintext (다시 조회 불가).

    클라이언트는 이 응답을 안전하게 보관해야 하고, 분실 시 새 키를 발급해야 함.
    """

    id: str
    name: str
    key_prefix: str
    key: str  # full plaintext key — ONLY in this create response
    created_at: str | None = None


class LogItemOut(BaseModel):
    id: str
    api_key_id: str | None = None
    channel: str | None = None
    external_session_id: str | None = None
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    status: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    created_at: str | None = None


class LogListOut(BaseModel):
    items: list[LogItemOut]


# ---------------------------------------------------------------------------
# Helpers — row → model
# ---------------------------------------------------------------------------


def _row_to_agent(row: Any) -> AgentOut:
    # row[14] = delegate_to_agent_ids (uuid[]) — 빈 배열 또는 NULL 처리.
    raw_delegates = row[14] if len(row) > 14 else None
    delegate_ids = [str(d) for d in (raw_delegates or [])]

    # Phase 1 admin fields (15-24) — DB 에 컬럼 있으면 채움. 없으면 default.
    def _safe_list_uuid(idx: int) -> list[str]:
        if len(row) <= idx or row[idx] is None:
            return []
        return [str(x) for x in row[idx]]

    def _safe_list_str(idx: int) -> list[str]:
        if len(row) <= idx or row[idx] is None:
            return []
        return list(row[idx])

    def _safe_str(idx: int, default: str = "") -> str:
        if len(row) <= idx or row[idx] is None:
            return default
        return str(row[idx])

    def _safe_bool(idx: int, default: bool) -> bool:
        if len(row) <= idx or row[idx] is None:
            return default
        return bool(row[idx])

    template_raw = row[24] if len(row) > 24 else None

    # 069 — web_search_mode (idx 25). 누락 시 default 'off'.
    web_mode = _safe_str(25, "off") or "off"

    # 075 — tool_scope_overrides (idx 26). asyncpg 가 jsonb 를 dict 로 자동 디코드.
    raw_overrides = row[26] if len(row) > 26 else None
    if isinstance(raw_overrides, dict):
        overrides = {str(k): str(v) for k, v in raw_overrides.items()}
    elif isinstance(raw_overrides, str) and raw_overrides:
        try:
            parsed = json.loads(raw_overrides)
            overrides = {str(k): str(v) for k, v in (parsed or {}).items()} if isinstance(parsed, dict) else {}
        except Exception:
            overrides = {}
    else:
        overrides = {}

    return AgentOut(
        id=str(row[0]),
        tenant_id=str(row[1]),
        name=row[2],
        description=row[3],
        persona=row[4] or "",
        system_prompt=row[5] or "",
        allowed_skills=list(row[6] or []),
        allowed_repos=list(row[7] or []),
        is_active=bool(row[8]),
        rate_limit_per_min=int(row[9]),
        created_by=str(row[10]) if row[10] else "",
        created_at=row[11].isoformat() if row[11] else None,
        updated_at=row[12].isoformat() if row[12] else None,
        kind=(row[13] or "role"),
        delegate_to_agent_ids=delegate_ids,
        goal=_safe_str(15),
        guidelines_md=_safe_str(16),
        primary_repo_ids=_safe_list_uuid(17),
        fallback_repo_ids=_safe_list_uuid(18),
        sop_repo_ids=_safe_list_uuid(19),
        knowledge_isolation=_safe_str(20, "priority") or "priority",
        allowed_tools=_safe_list_str(21),
        done_when=row[22] if len(row) > 22 and row[22] else None,
        test_mode_visible=_safe_bool(23, True),
        template_id=str(template_raw) if template_raw else None,
        web_search_mode=web_mode,
        tool_scope_overrides=overrides,
    )


_AGENT_COLS = (
    "id, tenant_id, name, description, persona, system_prompt, "
    "allowed_skills, allowed_repos, is_active, rate_limit_per_min, "
    "created_by, created_at, updated_at, kind, delegate_to_agent_ids, "
    "goal, guidelines_md, primary_repo_ids, fallback_repo_ids, sop_repo_ids, "
    "knowledge_isolation, allowed_tools, done_when, test_mode_visible, template_id, "
    "web_search_mode, tool_scope_overrides"
)


# Phase 1.5B-γ — multi-agent 위임 검증 상수.
_DELEGATE_MAX_DEPTH = 3  # A → B → C → D 면 D 부터 reject (chain 길이 4 이상).


async def _load_agent(agent_id: UUID) -> AgentOut:
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(f"SELECT {_AGENT_COLS} FROM agents WHERE id = :aid LIMIT 1"),
                {"aid": agent_id},
            )
        ).first()
    if not row:
        raise HTTPException(404, "agent not found")
    return _row_to_agent(row)


async def _load_agent_for_tenant(agent_id: UUID, tenant_id: UUID) -> AgentOut:
    """소속 검증 포함. 다른 테넌트의 agent 면 403."""
    agent = await _load_agent(agent_id)
    if agent.tenant_id != str(tenant_id):
        raise HTTPException(403, "agent does not belong to current tenant")
    return agent


# ---------------------------------------------------------------------------
# Phase 1.5B-γ — multi-agent 위임 검증 (cycle / depth / tenant)
# ---------------------------------------------------------------------------


async def _validate_delegate_targets(
    *,
    self_agent_id: UUID,
    tenant_id: UUID,
    delegate_ids: list[UUID],
) -> list[UUID]:
    """위임 대상 agent UUID 목록을 정규화 + 검증.

    검증 항목:
      1. 자기 자신 X (self-delegation 금지) — 400.
      2. 같은 tenant 의 active agent 만 가능 — 400.
      3. 순환 위임 (A → B → A 또는 더 긴 cycle) — 400.
      4. max_depth=3 — chain (예: A → B → C → D) 의 깊이가 3 초과면 400.

    반환: 중복 제거된 UUID 리스트 (입력 순서 유지).
    """
    # 1. 정규화 — 중복 제거 + 자기 자신 reject.
    seen: set[UUID] = set()
    normalized: list[UUID] = []
    for did in delegate_ids:
        if did in seen:
            continue
        if did == self_agent_id:
            raise HTTPException(400, "agent cannot delegate to itself")
        seen.add(did)
        normalized.append(did)

    if not normalized:
        return []

    # 2. tenant + active 검증 — 한 번의 SQL.
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id FROM agents "
                "WHERE id = ANY(:ids) AND tenant_id = :tid AND is_active = TRUE"
            ),
            {"ids": normalized, "tid": tenant_id},
        )
        valid_ids = {r[0] for r in rows}
    invalid = [str(d) for d in normalized if d not in valid_ids]
    if invalid:
        raise HTTPException(
            400,
            f"delegate target(s) not in same tenant or inactive: {invalid}",
        )

    # 3. cycle 검사 + depth 검사 — DFS.
    #    self → normalized 가 신규 graph 의 첫 hop. 그 후 각 target 의 기존
    #    delegate_to_agent_ids 를 따라 BFS/DFS.
    #    cycle: self_agent_id 가 어느 노드의 delegate 에 들어가면 cycle.
    #    depth: 시작 self 부터의 max chain length 가 _DELEGATE_MAX_DEPTH 초과면 reject.
    await _check_cycle_and_depth(
        self_agent_id=self_agent_id,
        tenant_id=tenant_id,
        proposed_targets=normalized,
    )

    return normalized


async def _check_cycle_and_depth(
    *,
    self_agent_id: UUID,
    tenant_id: UUID,
    proposed_targets: list[UUID],
) -> None:
    """DFS — proposed graph (self → targets → 기존 graph) 가 cycle 이거나
    depth 가 ``_DELEGATE_MAX_DEPTH`` 초과면 HTTPException(400)."""
    eng = _get_engine()
    # 한 번에 모든 active agent 의 (id, delegate_to_agent_ids) 가져옴.
    # tenant 격리 — 다른 tenant 노드는 graph 에 포함하지 않음.
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, delegate_to_agent_ids FROM agents "
                "WHERE tenant_id = :tid AND is_active = TRUE"
            ),
            {"tid": tenant_id},
        )
        graph: dict[UUID, list[UUID]] = {
            r[0]: list(r[1] or []) for r in rows
        }
    # self 가 신규 proposed_targets 로 override 됐다고 가정.
    graph[self_agent_id] = list(proposed_targets)

    # DFS — visited 는 cycle 탐지용 (현재 path), seen 은 중복 탐색 방지용.
    def dfs(node: UUID, path: list[UUID]) -> None:
        if len(path) > _DELEGATE_MAX_DEPTH:
            # path 길이 = 노드 수, edge 수 = path-1. _DELEGATE_MAX_DEPTH=3
            # 이면 노드 수 ≤4 (self 포함). edge 수 ≤3.
            raise HTTPException(
                400,
                f"delegate chain too deep (max depth = {_DELEGATE_MAX_DEPTH})",
            )
        for nxt in graph.get(node, []):
            if nxt == self_agent_id:
                # cycle back to start.
                raise HTTPException(
                    400,
                    f"circular delegation detected (cycle through {nxt})",
                )
            if nxt in path:
                # cycle within graph (not back to self) — 다른 cycle 도 reject.
                raise HTTPException(
                    400,
                    f"circular delegation detected (cycle node {nxt})",
                )
            dfs(nxt, path + [nxt])

    dfs(self_agent_id, [self_agent_id])


def _compose_persona_prefix(persona: str, system_prompt: str, user_text: str) -> str:
    """페르소나 + 추가 지시를 user message 앞에 prepend.

    빈 섹션은 생략. 둘 다 비어있으면 원문 그대로.
    """
    parts: list[str] = []
    persona_s = (persona or "").strip()
    sp_s = (system_prompt or "").strip()
    if persona_s:
        parts.append(f"[페르소나]\n{persona_s}")
    if sp_s:
        parts.append(f"[추가 지시]\n{sp_s}")
    if not parts:
        return user_text
    parts.append(f"[사용자]: {user_text}")
    return "\n\n".join(parts)


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=AgentListOut)
async def list_agents(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    include_inactive: bool = Query(False),
) -> AgentListOut:
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    eng = _get_engine()
    sql = (
        f"SELECT {_AGENT_COLS} FROM agents WHERE tenant_id = :tid"
        + ("" if include_inactive else " AND is_active = true")
        + " ORDER BY created_at DESC"
    )
    async with eng.begin() as conn:
        rows = await conn.execute(text(sql), {"tid": tid})
        items = [_row_to_agent(r) for r in rows]
    return AgentListOut(items=items)


@router.post("", response_model=AgentOut)
async def create_agent(
    body: AgentCreate,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentOut:
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")

    # 058 — kind 검증. 신규 생성은 default 'role'. admin 은 명시적 요청 + 기존
    # admin 이 없을 때만 허용 (partial unique index 가 추가 안전망).
    new_kind = (body.kind or "role").strip().lower()
    if new_kind not in ("admin", "role"):
        raise HTTPException(400, f"invalid kind: {body.kind}")

    eng = _get_engine()
    if new_kind == "admin":
        async with eng.begin() as conn:
            existing = (
                await conn.execute(
                    text(
                        "SELECT id FROM agents "
                        "WHERE tenant_id = :tid AND kind = 'admin' AND is_active = TRUE"
                    ),
                    {"tid": tid},
                )
            ).first()
        if existing:
            raise HTTPException(
                409,
                "admin agent already exists for this tenant — only one admin agent allowed",
            )

    async with eng.begin() as conn:
        new_id = (
            await conn.execute(
                text(
                    """
                    INSERT INTO agents
                      (tenant_id, name, description, persona, system_prompt,
                       allowed_skills, allowed_repos, rate_limit_per_min,
                       created_by, kind,
                       goal, guidelines_md)
                    VALUES
                      (:tid, :name, :desc, :persona, :sp,
                       CAST(:skills AS jsonb), CAST(:repos AS jsonb),
                       :rate, :cb, :kind,
                       :goal, :guide)
                    RETURNING id
                    """
                ),
                {
                    "tid": tid,
                    "name": body.name,
                    "desc": body.description,
                    "persona": body.persona or "",
                    "sp": body.system_prompt or "",
                    "skills": json.dumps(body.allowed_skills or []),
                    "repos": json.dumps(body.allowed_repos or []),
                    "rate": int(body.rate_limit_per_min or 60),
                    "cb": aid,
                    "kind": new_kind,
                    # goal / guidelines_md 는 NOT NULL — 빈 값으로 채워두고 PATCH 로 갱신.
                    "goal": body.persona or body.name,
                    "guide": body.system_prompt or "(편집 페이지에서 작성하세요)",
                },
            )
        ).scalar_one()

    # Phase 1.5B-γ — delegate_to_agent_ids 가 명시되면 검증 후 별도 UPDATE.
    # admin role 만 편집 가능. 신규 생성 직후 0이면 skip.
    if body.delegate_to_agent_ids:
        if role not in ("owner", "admin"):
            raise HTTPException(403, "owner or admin role required for delegate edit")
        try:
            uuid_targets = [UUID(str(d)) for d in body.delegate_to_agent_ids]
        except ValueError as e:
            raise HTTPException(400, f"invalid delegate uuid: {e}") from e
        validated = await _validate_delegate_targets(
            self_agent_id=new_id,
            tenant_id=tid,
            delegate_ids=uuid_targets,
        )
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE agents SET delegate_to_agent_ids = :ids, updated_at = now() "
                    "WHERE id = :aid"
                ),
                {"ids": validated, "aid": new_id},
            )

    # round 2 fix — agent 생성을 audit_logs 에 기록.
    try:
        record_action(
            tenant_id=tid,
            user_id=aid,
            action="create",
            resource_type="agent",
            resource_id=new_id,
            detail={"name": body.name, "kind": new_kind},
        )
    except Exception:
        pass
    return await _load_agent(new_id)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentOut:
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    return await _load_agent_for_tenant(_parse_uuid(agent_id, "agent_id"), tid)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str,
    body: AgentPatch,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentOut:
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)  # 소속 검증

    # D43 (2026-05-11) — delegate_to_agent_ids 권한 정책 정정.
    #
    # 이전 동작 (Phase 1.5B-γ): owner 도 거부, admin role 만 편집 가능.
    # 그러나 frontend EditTabContent.tsx 의 buildPayload() 는 *언제나*
    # `delegate_to_agent_ids: form.delegate_to_agent_ids` 를 포함 — 빈 배열도
    # 보냄. backend 는 `is not None` 만 검사하므로 변경 의도가 없어도 admin
    # gate 진입 → owner 인 정상 tenant 관리자가 *어떤 편집*도 못 함 (403).
    #
    # 사용자 절칙 (2026-05-11 #231): "tenant owner/admin 모두 자기 tenant 의
    # agent 편집 가능. super_admin 만 cross-tenant." 본 fix 는 POST handler
    # (line 648 — `("owner", "admin")`) 와 정합. 또한 *실제 변경 없음* (현재
    # DB 값과 동일한 빈 list 또는 동일 set) 인 경우 권한 게이트도 우회 — DB
    # write skip 으로 no-op idempotent 보장.
    validated_delegates: list[UUID] | None = None
    if body.delegate_to_agent_ids is not None:
        # 현재 DB 값과 동일하면 no-op (게이트/검증/UPDATE 모두 skip).
        # 이 분기는 frontend 가 *변경 의도 없이* 현재 값을 echo back 하는
        # 케이스 (대표 시나리오) 를 흡수.
        eng = _get_engine()
        async with eng.begin() as conn:
            current_row = (
                await conn.execute(
                    text(
                        "SELECT delegate_to_agent_ids FROM agents "
                        "WHERE id = :aid"
                    ),
                    {"aid": target_id},
                )
            ).first()
        current_delegates = list(current_row[0] or []) if current_row else []
        try:
            submitted_uuids = [UUID(str(d)) for d in body.delegate_to_agent_ids]
        except ValueError as e:
            raise HTTPException(400, f"invalid delegate uuid: {e}") from e
        # 정렬 후 set 비교 — 순서 무시 동등성.
        if {str(u) for u in submitted_uuids} == {str(u) for u in current_delegates}:
            # 변경 없음 — 권한 게이트 우회, validated_delegates 는 None 유지
            # (아래 SQL 의 CASE WHEN 으로 인해 미변경 보존).
            pass
        else:
            # *실제* 변경 의도 — owner 또는 admin 만 허용 (POST handler 정합).
            if role not in ("owner", "admin"):
                raise HTTPException(
                    403,
                    "owner or admin role required for delegate_to_agent_ids edit",
                )
            validated_delegates = await _validate_delegate_targets(
                self_agent_id=target_id,
                tenant_id=tid,
                delegate_ids=submitted_uuids,
            )

    # 069 — web_search_mode 검증 (None 이면 변경 안 함).
    if body.web_search_mode is not None:
        if body.web_search_mode not in ("off", "separate", "blended", "web_only"):
            raise HTTPException(
                400,
                f"invalid web_search_mode: {body.web_search_mode} "
                f"(allowed: off / separate / blended / web_only)",
            )

    # 2026-05-07 (#147) — repo id 배열 검증 + 변환. None 이면 변경 안 함, []
    # 이면 빈 배열 명시. UUID 문자열만 허용 — 잘못된 형식은 400.
    # GPT-5 P0/P1 fix: 배열 크기 상한 + 중복 제거 (안정 직렬화).
    _REPO_ARRAY_MAX = 200  # 한 agent 가 200 repo 이상 묶는 케이스는 비정상.

    def _validate_repo_uuids(field_name: str, raw: list[str] | None) -> list[UUID] | None:
        if raw is None:
            return None
        if len(raw) > _REPO_ARRAY_MAX:
            raise HTTPException(
                400,
                f"{field_name} array exceeds maximum size {_REPO_ARRAY_MAX} (got {len(raw)})",
            )
        seen: set[UUID] = set()
        out: list[UUID] = []
        for r in raw:
            try:
                u = UUID(str(r))
            except ValueError as e:
                raise HTTPException(
                    400,
                    f"invalid uuid in {field_name}: {r!r} ({e})",
                ) from e
            if u in seen:
                continue  # 중복 제거.
            seen.add(u)
            out.append(u)
        return out

    primary_repos = _validate_repo_uuids("primary_repo_ids", body.primary_repo_ids)
    fallback_repos = _validate_repo_uuids("fallback_repo_ids", body.fallback_repo_ids)
    sop_repos = _validate_repo_uuids("sop_repo_ids", body.sop_repo_ids)

    # D42 (2026-05-11) — knowledge_isolation enum + allowed_tools whitelist 검증.
    if body.knowledge_isolation is not None and body.knowledge_isolation not in (
        "strict",
        "priority",
        "broad",
    ):
        raise HTTPException(
            400,
            f"invalid knowledge_isolation: {body.knowledge_isolation!r} "
            f"(allowed: strict / priority / broad)",
        )

    # allowed_tools — None=미변경, []=모두 비활성, [...]=명시. 카탈로그 밖 도구는
    # silently drop (catalog 가 신규 도구를 모를 수 있는 race 회피). 단 빈 list
    # 의미는 사용자 의도라 보존.
    # D42 GPT-5 NO_GO 1차 fix — "unknown-only" 입력 (catalog race) 시 filter
    # 결과가 [] 가 되어 *기존 도구 전체 silent clear* 위험. 입력이 비어있을
    # 때만 명시 clear, 비어있지 않은데 filter 결과 [] 면 preserve (None) 처리.
    validated_tools: list[str] | None = None
    if body.allowed_tools is not None:
        if not isinstance(body.allowed_tools, list):
            raise HTTPException(400, "allowed_tools must be a list of strings")
        if len(body.allowed_tools) == 0:
            # 사용자 의도: 명시 clear (모든 도구 비활성).
            validated_tools = []
        else:
            # 카탈로그 화이트리스트 + 중복 제거 + 순서 보존.
            seen_t: set[str] = set()
            out_t: list[str] = []
            for t in body.allowed_tools:
                if not isinstance(t, str) or not t:
                    continue
                if t in seen_t:
                    continue
                if t in _ALL_AVAILABLE_TOOLS:
                    seen_t.add(t)
                    out_t.append(t)
            # filter 결과가 비어있으면 (unknown-only 입력) preserve — silent
            # 전체 clear 회귀 방지. catalog race 가 끝난 뒤 재시도하면 정상 반영.
            if out_t:
                validated_tools = out_t
            else:
                validated_tools = None

    # tool_scope_overrides — 075 (Phase 3 #154) 의 _validate_tool_scope_overrides
    # 재사용. None=미변경, {}=클리어.
    validated_overrides: dict[str, str] | None = None
    if body.tool_scope_overrides is not None:
        try:
            validated_overrides = _validate_tool_scope_overrides(
                body.tool_scope_overrides
            )
        except ValueError as e:
            raise HTTPException(400, f"tool_scope_overrides: {e}") from e

    # GPT-5 P0 fix — cross-tenant repo 차단. 전달된 모든 repo UUID 가
    # *이 agent 의 tenant* 에 속하고 *존재* 해야 함. 없거나 다른 tenant 면 400.
    # (정보 누출 차단을 위해 어떤 ID 가 어느 tenant 인지 노출하지 않음 — 단순 거절.)
    eng = _get_engine()
    all_check: list[UUID] = []
    for arr in (primary_repos, fallback_repos, sop_repos):
        if arr:
            all_check.extend(arr)
    if all_check:
        async with eng.begin() as conn:
            valid_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT id FROM repositories
                        WHERE id = ANY(:rids) AND tenant_id = :tid
                        """
                    ),
                    {"rids": list(set(all_check)), "tid": tid},
                )
            ).all()
        valid_ids = {row[0] for row in valid_rows}
        invalid_ids = [str(u) for u in set(all_check) if u not in valid_ids]
        if invalid_ids:
            raise HTTPException(
                400,
                f"unknown or cross-tenant repo id(s): {invalid_ids[:5]}"
                f"{' (+more)' if len(invalid_ids) > 5 else ''}",
            )

    # COALESCE 패턴 — None 인 필드는 기존 값 유지.
    # D42 (2026-05-11) — allowed_tools / goal / guidelines_md /
    # knowledge_isolation / done_when / test_mode_visible / tool_scope_overrides
    # 까지 SQL UPDATE 에 포함. 이전 regression: AgentPatch 가 필드 정의 누락
    # → silently drop → DB 미반영. (frontend ToolPicker 토글이 적용 안 됨)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE agents
                SET name = COALESCE(:name, name),
                    description = COALESCE(:desc, description),
                    persona = COALESCE(:persona, persona),
                    system_prompt = COALESCE(:sp, system_prompt),
                    allowed_skills = COALESCE(CAST(:skills AS jsonb), allowed_skills),
                    allowed_repos = COALESCE(CAST(:repos AS jsonb), allowed_repos),
                    rate_limit_per_min = COALESCE(:rate, rate_limit_per_min),
                    is_active = COALESCE(:active, is_active),
                    delegate_to_agent_ids = CASE
                        WHEN :delegates_set THEN CAST(:delegates AS uuid[])
                        ELSE delegate_to_agent_ids
                    END,
                    web_search_mode = COALESCE(:web_mode, web_search_mode),
                    primary_repo_ids = CASE
                        WHEN :primary_set THEN CAST(:primary_repos AS uuid[])
                        ELSE primary_repo_ids
                    END,
                    fallback_repo_ids = CASE
                        WHEN :fallback_set THEN CAST(:fallback_repos AS uuid[])
                        ELSE fallback_repo_ids
                    END,
                    sop_repo_ids = CASE
                        WHEN :sop_set THEN CAST(:sop_repos AS uuid[])
                        ELSE sop_repo_ids
                    END,
                    goal = COALESCE(:goal, goal),
                    guidelines_md = COALESCE(:guide, guidelines_md),
                    knowledge_isolation = COALESCE(:isolation, knowledge_isolation),
                    allowed_tools = CASE
                        WHEN :tools_set THEN CAST(:tools AS text[])
                        ELSE allowed_tools
                    END,
                    done_when = CASE
                        WHEN :done_set THEN :done_when
                        ELSE done_when
                    END,
                    test_mode_visible = COALESCE(:test_visible, test_mode_visible),
                    tool_scope_overrides = CASE
                        WHEN :overrides_set THEN CAST(:overrides AS jsonb)
                        ELSE tool_scope_overrides
                    END,
                    updated_at = now()
                WHERE id = :aid
                """
            ),
            {
                "name": body.name,
                "desc": body.description,
                "persona": body.persona,
                "sp": body.system_prompt,
                "skills": None if body.allowed_skills is None else json.dumps(body.allowed_skills),
                "repos": None if body.allowed_repos is None else json.dumps(body.allowed_repos),
                "rate": body.rate_limit_per_min,
                "active": body.is_active,
                "delegates_set": validated_delegates is not None,
                "delegates": validated_delegates if validated_delegates is not None else [],
                "web_mode": body.web_search_mode,
                "primary_set": primary_repos is not None,
                "primary_repos": primary_repos if primary_repos is not None else [],
                "fallback_set": fallback_repos is not None,
                "fallback_repos": fallback_repos if fallback_repos is not None else [],
                "sop_set": sop_repos is not None,
                "sop_repos": sop_repos if sop_repos is not None else [],
                # D42 (2026-05-11) — agent edit page 도구/goal/guidelines/isolation/
                # done_when/test_visible 적용 결함 fix.
                "goal": body.goal,
                "guide": body.guidelines_md,
                "isolation": body.knowledge_isolation,
                "tools_set": validated_tools is not None,
                "tools": validated_tools if validated_tools is not None else [],
                "done_set": body.done_when is not None,
                "done_when": body.done_when,
                "test_visible": body.test_mode_visible,
                "overrides_set": validated_overrides is not None,
                "overrides": (
                    json.dumps(validated_overrides)
                    if validated_overrides is not None
                    else "{}"
                ),
                "aid": target_id,
            },
        )
    # round 2 fix — agent 변경을 audit_logs 에 기록.
    # 이전: agent CRUD 가 audit chain 에 안 잡혀 admin/audit 페이지가 항상 빈
    # 상태. record_action 은 background task 로 fire-and-forget — PATCH 응답
    # latency 영향 없음.
    try:
        changed: dict[str, Any] = {
            k: v for k, v in {
                "name": body.name,
                "description": body.description,
                "is_active": body.is_active,
                "rate_limit_per_min": body.rate_limit_per_min,
                "allowed_skills": body.allowed_skills,
                "allowed_repos": body.allowed_repos,
                "delegate_to_agent_ids": (
                    [str(d) for d in validated_delegates]
                    if validated_delegates is not None else None
                ),
                "web_search_mode": body.web_search_mode,
                # 2026-05-07 (#147) — sop/primary/fallback repo 변경 audit.
                "primary_repo_ids": body.primary_repo_ids,
                "fallback_repo_ids": body.fallback_repo_ids,
                "sop_repo_ids": body.sop_repo_ids,
                # D42 (2026-05-11) — agent edit 도구/scope/isolation 변경 audit.
                "goal": body.goal,
                "guidelines_md": body.guidelines_md,
                "knowledge_isolation": body.knowledge_isolation,
                "allowed_tools": (
                    validated_tools if validated_tools is not None else None
                ),
                "done_when": body.done_when,
                "test_mode_visible": body.test_mode_visible,
                "tool_scope_overrides": (
                    validated_overrides
                    if validated_overrides is not None
                    else None
                ),
            }.items() if v is not None
        }
        record_action(
            tenant_id=tid,
            user_id=aid,
            action="update",
            resource_type="agent",
            resource_id=target_id,
            detail={"changed_fields": list(changed.keys())},
        )
    except Exception:
        pass
    # L9 (2026-05-07) — agent cache invalidate. webhook path 의 5 분 캐시가
    # 변경된 agent metadata 를 즉시 반영하도록 강제.
    try:
        from src.api.routers.external_agent_v1 import invalidate_agent_cache
        invalidate_agent_cache(target_id)
    except Exception:
        pass
    return await _load_agent(target_id)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    transfer_to_agent_id: str | None = Query(None),
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """soft delete — is_active=false. 키/로그는 보존.

    D29 §3 (#157, 2026-05-08) — `transfer_to_agent_id` 옵션 추가.
    명시 시 source agent 의 자원 (documents.owner_agent_id +
    library_folders.owner_agent_id + schedules.owner_agent_id 컬럼 존재 시)
    을 target agent 로 *단일 transaction 안에서* 이전 후 source soft delete.

    transfer_to_agent_id 미명시 (None) 시:
        기존 동작 — soft delete 만 (owner_agent_id 보존, admin global view
        에서 inactive agent 자원 보임).

    transaction 안 처리:
        BEGIN;
        SELECT id, tenant_id, is_active FROM agents
            WHERE id IN (:src, :tgt) AND tenant_id = :tid FOR UPDATE;
        -- application layer 재검증
        UPDATE documents SET owner_agent_id = :new
            WHERE owner_agent_id = :old AND tenant_id = :tid;
        UPDATE library_folders ... (동일);
        UPDATE schedules ... (information_schema 컬럼 존재 시);
        UPDATE agents SET is_active = false ... WHERE id = :src;
        COMMIT;
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")
    source_agent = await _load_agent_for_tenant(target_id, tid)

    # D29 §3 — transfer 모드 검증 (transaction 밖, 사전 검증)
    transfer_uuid: UUID | None = None
    if transfer_to_agent_id:
        transfer_uuid = _parse_uuid(transfer_to_agent_id, "transfer_to_agent_id")
        if transfer_uuid == target_id:
            raise HTTPException(
                400,
                "transfer_to_agent_id cannot equal the deleted agent (self-transfer)",
            )
        # cross-tenant + 미존재 차단 (soft delete 된 agent 도 reject)
        target_agent = await _load_agent_for_tenant(transfer_uuid, tid)
        if not target_agent.is_active:
            raise HTTPException(
                400,
                "transfer target agent is inactive — choose an active target",
            )

    eng = _get_engine()
    transferred_counts: dict[str, int] = {}
    already_inactive = False

    async with eng.begin() as conn:
        # D29 §3 — transaction 안 lock + 재검증 (GPT-5 phase 0 권고 #4 + #5).
        # GPT-5 사전 verdict 권고: ORDER BY id 로 lock 순서 고정 (반대 방향 동시
        # delete/transfer deadlock 방지).
        if transfer_uuid is not None:
            lock_rows = (
                await conn.execute(
                    text(
                        "SELECT id, tenant_id, is_active FROM agents "
                        "WHERE id IN (:src, :tgt) AND tenant_id = :tid "
                        "ORDER BY id FOR UPDATE"
                    ),
                    {"src": target_id, "tgt": transfer_uuid, "tid": tid},
                )
            ).all()
        else:
            lock_rows = (
                await conn.execute(
                    text(
                        "SELECT id, tenant_id, is_active FROM agents "
                        "WHERE id = :src AND tenant_id = :tid "
                        "FOR UPDATE"
                    ),
                    {"src": target_id, "tid": tid},
                )
            ).all()

        # 재검증: source 존재 + tenant 일치
        src_row = next((r for r in lock_rows if str(r[0]) == str(target_id)), None)
        if src_row is None:
            raise HTTPException(404, "agent not found in tenant (lock)")
        if src_row[2] is False:
            # idempotent — 이미 inactive 면 200 + summary "이미 삭제됨"
            already_inactive = True

        if transfer_uuid is not None and not already_inactive:
            tgt_row = next(
                (r for r in lock_rows if str(r[0]) == str(transfer_uuid)),
                None,
            )
            if tgt_row is None:
                raise HTTPException(
                    404, "transfer target not found in tenant (lock)"
                )
            if tgt_row[2] is False:
                raise HTTPException(
                    400, "transfer target became inactive during operation"
                )

            # transfer 실행 — documents + library_folders.
            doc_result = await conn.execute(
                text(
                    "UPDATE documents SET owner_agent_id = :new "
                    "WHERE owner_agent_id = :old AND tenant_id = :tid"
                ),
                {"new": transfer_uuid, "old": target_id, "tid": tid},
            )
            transferred_counts["documents"] = (
                doc_result.rowcount if doc_result.rowcount is not None else 0
            )
            lf_result = await conn.execute(
                text(
                    "UPDATE library_folders SET owner_agent_id = :new "
                    "WHERE owner_agent_id = :old AND tenant_id = :tid"
                ),
                {"new": transfer_uuid, "old": target_id, "tid": tid},
            )
            transferred_counts["library_folders"] = (
                lf_result.rowcount if lf_result.rowcount is not None else 0
            )

            # D29 §3 (GPT-5 phase 0 권고 #4 + 사전 verdict #4) —
            # schedules.owner_agent_id 컬럼 존재 시 (information_schema 동적
            # 탐지, current_schema() 한정) 동반 update. 미존재 시 skip (회귀 0).
            sch_col_check = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='schedules' "
                        "AND column_name='owner_agent_id' "
                        "AND table_schema=current_schema() LIMIT 1"
                    )
                )
            ).first()
            if sch_col_check is not None:
                # tenant_id 컬럼도 있는지 확인 (legacy 외부 schema 안전).
                sch_tenant_check = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name='schedules' "
                            "AND column_name='tenant_id' "
                            "AND table_schema=current_schema() LIMIT 1"
                        )
                    )
                ).first()
                if sch_tenant_check is not None:
                    sch_result = await conn.execute(
                        text(
                            "UPDATE schedules SET owner_agent_id = :new "
                            "WHERE owner_agent_id = :old AND tenant_id = :tid"
                        ),
                        {"new": transfer_uuid, "old": target_id, "tid": tid},
                    )
                    transferred_counts["schedules"] = (
                        sch_result.rowcount
                        if sch_result.rowcount is not None
                        else 0
                    )

        # source soft delete (idempotent — already_inactive 도 안전).
        # GPT-5 사전 verdict 권고: tenant_id 조건 추가 (UUID PK 가 unique 여도
        # multi-tenant 안전망).
        if not already_inactive:
            await conn.execute(
                text(
                    "UPDATE agents SET is_active = false, updated_at = now() "
                    "WHERE id = :aid AND tenant_id = :tid"
                ),
                {"aid": target_id, "tid": tid},
            )

    # round 2 fix — agent soft delete 를 audit_logs 에 기록.
    try:
        record_action(
            tenant_id=tid,
            user_id=aid,
            action="delete",
            resource_type="agent",
            resource_id=target_id,
            detail={
                "soft": True,
                "transfer_to": str(transfer_uuid) if transfer_uuid else None,
                "transferred": transferred_counts or None,
                "already_inactive": already_inactive,
            },
        )
    except Exception:
        pass
    # L9 — soft delete 후 agent cache invalidate.
    try:
        from src.api.routers.external_agent_v1 import invalidate_agent_cache
        invalidate_agent_cache(target_id)
        if transfer_uuid:
            invalidate_agent_cache(transfer_uuid)
    except Exception:
        pass

    response: dict[str, Any] = {
        "ok": True,
        "id": str(target_id),
        "is_active": False,
        "transferred_to": str(transfer_uuid) if transfer_uuid else None,
        "transferred": transferred_counts,
    }
    if already_inactive:
        response["already_inactive"] = True
    return response


# ---------------------------------------------------------------------------
# Test chat (sandbox — no chat_messages persistence)
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/test-chat")
async def test_chat(
    agent_id: str,
    body: TestChatRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    engine: AgentEngine = Depends(get_agent_engine),
) -> StreamingResponse:
    """sandbox 챗 — agent persona/system_prompt 를 prepend. 영속하지 않음.

    CRITICAL (2026-05-07): engine.turn 호출 시 ``agent_context`` 를 빌드해서
    전달해야 격리 layer (Tool RAG / SOP RAG / repo namespace / OOS policy) 가
    동작한다. 이전에는 미전달 → role agent (kbsoldier_advisor 등) 의 test mode
    가 모든 격리 우회. 이번 fix 로 AgentRepository 로 ORM 모델 fetch →
    AgentContext.from_agent → engine.turn 전달.

    test mode 는 운영자(admin/owner) 만 진입하므로 SenderContext.tier='admin',
    verified_via='session_login'. account_id_hint 도 JWT sub (aid) 로 채워
    user-scoped 도구 (mail.send 등) 가 정상 작동.
    """
    aid, token_tid, role = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    membership_role = await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")

    # ORM 모델 fetch — AgentContext.from_agent 가 ORM attribute 에 의존.
    # _load_agent_for_tenant 은 Pydantic AgentOut 을 반환하므로 별도 경로.
    _ae = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        async with AsyncSession(_ae) as _sess:
            _repo = AgentRepository(_sess)
            agent_orm = await _repo.get(target_id, tenant_id=tid)
            if agent_orm is None:
                raise HTTPException(404, "agent not found in tenant")
            if not agent_orm.is_active:
                raise HTTPException(403, "agent is inactive")
            # session 안에서 immutable AgentContext + persona snapshot 추출
            # (DetachedInstanceError 회피).
            agent_context = AgentContext.from_agent(agent_orm)
            _persona = agent_orm.persona or ""
            _system_prompt = agent_orm.system_prompt or ""
    finally:
        await _ae.dispose()

    sid = body.session_id or f"agent-test-{target_id}-{secrets.token_hex(6)}"
    composed = _compose_persona_prefix(_persona, _system_prompt, body.text)

    # SenderContext — test mode 는 운영자(admin/owner) 만 접근. JWT 의 role
    # 또는 tenant_membership.role 중 admin/owner 면 admin tier, 아니면 verified.
    _role_norm = (role or membership_role or "").lower()
    _tier: str = "admin" if _role_norm in ("admin", "owner") else "verified"
    sender = SenderContext(
        tier=_tier,  # type: ignore[arg-type]
        internal_user_id=aid,
        tenant_id=tid,
        channel_kind="web",
        verified_via="session_login",
        confirm_token=None,
    )

    # round 2 fix — test-chat turn 을 agent_message_log 에 INSERT.
    # 이전: test-chat 이 SSE 만 흘려보내고 영속화 0 → dashboard / billing /
    # insights 가 모든 agent 에 대해 turn=0 으로 표시되어 "데이터 안 맞음".
    # 이번 fix 로 turn 종료 시 1 row INSERT (status, latency, tokens 가능한 만큼).
    import time as _time_mod

    # Latency P0-1 (2026-05-07) — role agent 측정 활성. flag off 시 byte-equal.
    # chat_v1.py 의 probe wire 패턴 (line 605-622) 을 동일 적용 — 5 role agent
    # (baemin/homeshop/kb/samchully/Locus) phase 별 latency 측정 가능.
    _probe_enabled: bool = is_enabled(
        FeatureFlag.LATENCY_PROBE_SSE, tenant_id=str(tid)
    )

    async def stream():
        t0 = _time_mod.monotonic()
        final_status = "ok"
        final_response: dict[str, Any] = {}
        tokens_in = 0
        tokens_out = 0
        # 2026-05-08 (사용자 명시) — agent_message_log.response={} schema 결함 fix.
        # engine 은 token + done 만 emit (final/answer/message_end 안 씀) → 기존
        # capture 로직이 항상 빈 dict 저장. token chunk 누적 후 done 시 final_response
        # 에 "text" 로 저장 (jsonb cap 8000 고려).
        _accumulated_text: list[str] = []
        # P0-1: probe 활성 시 turn 시작 시각 기록 + phase mirror consumer.
        probe: LatencyProbe | None = None
        _turn_started: float = 0.0
        if _probe_enabled:
            probe = LatencyProbe()
            _turn_started = _time_mod.time()
        # D33 §3 — bind_agent_scope() 실 호출 site (test-chat path).
        # target_id = agent_id 항상 명시 → 명시적으로 agent scope 로 wrap.
        # async generator wrapper 패턴 — contextvars 가 매 __anext__ 마다 caller
        # context 를 따르므로 wrapper 안에서 bind_scope 활성 상태로 it 소진.
        from src.api.middleware.rls_context import bind_agent_scope as _bind_scope

        async def _scoped_engine_turn():
            async with _bind_scope(str(target_id), str(tid)):
                async for _it_item in engine.turn(
                    sid,
                    str(tid),
                    composed,
                    account_id_hint=str(aid),
                    agent_context=agent_context,
                    sender=sender,
                ):
                    yield _it_item

        try:
            async for item in _scoped_engine_turn():
                # P0-1: probe consume — flag off 시 분기 미진입.
                if probe is not None:
                    try:
                        probe.consume_event(item)
                    except Exception:
                        # observability 가 응답 막아선 안 됨.
                        pass
                ev = item.get("event", "message")
                data = item.get("data", {}) or {}
                # capture final answer / errors / token usage if engine emits.
                if ev in ("final", "answer", "message_end"):
                    final_response = data if isinstance(data, dict) else {"raw": data}
                elif ev == "error":
                    final_status = "error"
                    final_response = data if isinstance(data, dict) else {"raw": data}
                elif ev == "token":
                    # 2026-05-08 — assistant 본문 chunk 누적. engine 이 token event
                    # 에 {text} 만 emit (다른 event 와 mix 안 됨). 누적 후 done 시
                    # final_response["text"] 에 저장.
                    _t = data.get("text") if isinstance(data, dict) else None
                    if isinstance(_t, str) and _t:
                        _accumulated_text.append(_t)
                elif ev == "done":
                    # done 시점에 누적 텍스트가 있고 final_response 에 아직
                    # text 가 없으면 저장 (8000 char cap — DB jsonb 한도 정합).
                    if _accumulated_text and not (
                        isinstance(final_response, dict) and final_response.get("text")
                    ):
                        if not isinstance(final_response, dict):
                            final_response = {}
                        _full = "".join(_accumulated_text)
                        # 2026-05-08 — markdown 정합성 후처리 (heading/표 앞 빈 줄
                        # 자동 보장). LLM 답변에 `### 1.` heading 앞 빈 줄 누락 시
                        # raw 노출 결함 차단. idempotent — 이미 정상이면 no-op.
                        # GPT-5 Phase 1 §4: 8000 char truncate 가 표 한가운데를
                        # 자르면 frontend 렌더 깨짐. 직전 *문단 경계* (`\n\n`) 에서
                        # 자르도록 boundary-aware cap. 경계 없으면 hard cap.
                        try:
                            from src.common.text.markdown_normalizer import (
                                normalize_markdown,
                            )
                            _full = normalize_markdown(_full)
                        except Exception:
                            pass
                        # 2026-05-08 — LaTeX → 유니코드 변환 (D18-v2 hook 누락 fix).
                        # `$\rightarrow$` 같은 raw 노출 차단. normalize 후 적용.
                        try:
                            from src.common.text.latex_sanitizer import (
                                sanitize_latex_to_unicode,
                            )
                            _full = sanitize_latex_to_unicode(_full)
                        except Exception:
                            pass
                        if len(_full) > 8000:
                            # 8000 안쪽에서 마지막 `\n\n` 위치 찾기 — 표/heading
                            # 보호. 경계 없으면 hard cap.
                            cut = _full.rfind("\n\n", 0, 8000)
                            if cut > 4000:  # 너무 짧게 자르지 X (최소 50%).
                                final_response["text"] = _full[:cut]
                            else:
                                final_response["text"] = _full[:8000]
                            final_response["text_truncated"] = True
                        else:
                            final_response["text"] = _full
                # token usage (engine 이 emit 하면 사용; 없으면 0).
                tu = data.get("token_usage") if isinstance(data, dict) else None
                if isinstance(tu, dict):
                    tokens_in = int(tu.get("input", tokens_in) or tokens_in)
                    tokens_out = int(tu.get("output", tokens_out) or tokens_out)
                # 2026-05-08 D21 — done event 에 ``final_text`` (normalize + sanitize)
                # 주입. frontend 가 done 시 누적 buffer 를 final_text 로 교체 →
                # raw `### 1.` / `$\rightarrow$` 표시 차단. token chunk 는 변경 0
                # (실시간 부분 본문은 raw 일 수 있으나 done 즉시 교체).
                if ev == "done" and isinstance(final_response, dict):
                    _ft = final_response.get("text")
                    if isinstance(_ft, str) and _ft:
                        _done_data = dict(data) if isinstance(data, dict) else {}
                        _done_data["final_text"] = _ft
                        yield _sse(ev, _done_data)
                        continue
                yield _sse(ev, data)
            # P0-1: turn 종료 후 latency_probe payload emit. done event 뒤에 와도
            # frontend 영향 0 — observability 전용 event. flag off 시 미발사.
            if probe is not None:
                try:
                    probe.record_phase("engine_turn", _turn_started, _time_mod.time())
                    probe.finalize_derived_phases(_turn_started)
                    yield _sse("latency_probe", probe.to_sse_payload())
                except Exception:
                    pass
        except Exception as e:
            final_status = "error"
            final_response = {"error": str(e)[:500]}
            yield _sse("error", final_response)
        finally:
            latency_ms = int((_time_mod.monotonic() - t0) * 1000)
            try:
                eng = _get_engine()
                async with eng.begin() as conn:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO agent_message_log
                                (agent_id, channel, external_session_id, request,
                                 response, status, tokens_in, tokens_out, latency_ms)
                            VALUES
                                (:aid, :ch, :sid, CAST(:req AS jsonb),
                                 CAST(:res AS jsonb), :st, :ti, :to, :lat)
                            """
                        ),
                        {
                            "aid": target_id,
                            "ch": "web",
                            "sid": sid,
                            "req": json.dumps({"text": body.text[:2000]}),
                            "res": json.dumps(final_response)[:8000],
                            "st": final_status,
                            "ti": tokens_in,
                            "to": tokens_out,
                            "lat": latency_ms,
                        },
                    )
            except Exception:
                # 영속화 실패가 SSE 응답을 죽이지 않도록 — best effort.
                pass

    return StreamingResponse(stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


_KEY_PLAINTEXT_MAX = 32  # secrets.token_urlsafe(24) → ~32 chars after prefix


def _generate_api_key() -> tuple[str, str]:
    """(full_plaintext, prefix) — full = "aicm_agent_" + token, prefix = first 12 chars.

    plaintext 는 발급 응답에 1회만 노출. DB 에는 bcrypt hash 만 저장.
    """
    body_token = secrets.token_urlsafe(24)[:_KEY_PLAINTEXT_MAX]
    full = f"aicm_agent_{body_token}"
    return full, full[:12]


@router.get("/{agent_id}/api-keys", response_model=ApiKeyListOut)
async def list_api_keys(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiKeyListOut:
    """메타데이터만 — 평문 키/해시는 응답에 절대 포함되지 않음."""
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT id, name, key_prefix, last_used_at, created_at, revoked_at
                FROM agent_api_keys
                WHERE agent_id = :aid
                ORDER BY created_at DESC
                """
            ),
            {"aid": target_id},
        )
        items = [
            ApiKeyMetaOut(
                id=str(r[0]),
                name=r[1],
                key_prefix=r[2],
                last_used_at=r[3].isoformat() if r[3] else None,
                created_at=r[4].isoformat() if r[4] else None,
                revoked_at=r[5].isoformat() if r[5] else None,
            )
            for r in rows
        ]
    return ApiKeyListOut(items=items)


@router.post("/{agent_id}/api-keys", response_model=ApiKeyCreatedOut)
async def create_api_key(
    agent_id: str,
    body: ApiKeyCreate,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiKeyCreatedOut:
    """새 API key 발급.

    응답의 ``key`` 는 평문 (plaintext) — 이 응답에서만 단 한 번 노출된다.
    클라이언트는 이 값을 안전하게 보관해야 하며 (env/secret manager), 재조회는 불가능하다.
    분실 시 새 키를 발급하고 옛 키를 revoke 해야 함.
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)

    full_key, prefix = _generate_api_key()
    key_hash = hash_password(full_key)

    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO agent_api_keys
                      (agent_id, name, key_prefix, key_hash)
                    VALUES (:aid, :name, :prefix, :hash)
                    RETURNING id, created_at
                    """
                ),
                {
                    "aid": target_id,
                    "name": body.name,
                    "prefix": prefix,
                    "hash": key_hash,
                },
            )
        ).first()
    return ApiKeyCreatedOut(
        id=str(row[0]),
        name=body.name,
        key_prefix=prefix,
        key=full_key,
        created_at=row[1].isoformat() if row[1] else None,
    )


@router.delete("/{agent_id}/api-keys/{key_id}")
async def revoke_api_key(
    agent_id: str,
    key_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """soft revoke — revoked_at = now()."""
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")
    kid = _parse_uuid(key_id, "key_id")
    await _load_agent_for_tenant(target_id, tid)
    eng = _get_engine()
    async with eng.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE agent_api_keys
                SET revoked_at = now()
                WHERE id = :kid AND agent_id = :aid AND revoked_at IS NULL
                """
            ),
            {"kid": kid, "aid": target_id},
        )
        if result.rowcount == 0:
            raise HTTPException(404, "api key not found or already revoked")
    return {"ok": True, "id": str(kid), "revoked": True}


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/logs", response_model=LogListOut)
async def list_logs(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    limit: int = Query(100, ge=1, le=1000),
) -> LogListOut:
    """최근 ``limit`` 건의 외부 호출 로그 (created_at DESC)."""
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT id, api_key_id, channel, external_session_id,
                       request, response, status, tokens_in, tokens_out,
                       latency_ms, created_at
                FROM agent_message_log
                WHERE agent_id = :aid
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"aid": target_id, "lim": limit},
        )
        items = [
            LogItemOut(
                id=str(r[0]),
                api_key_id=str(r[1]) if r[1] else None,
                channel=r[2],
                external_session_id=r[3],
                request=r[4],
                response=r[5],
                status=r[6],
                tokens_in=r[7],
                tokens_out=r[8],
                latency_ms=r[9],
                created_at=r[10].isoformat() if r[10] else None,
            )
            for r in rows
        ]
    return LogListOut(items=items)


# ---------------------------------------------------------------------------
# Agent channels — 등록된 외부 채널 목록 (telegram, kakaowork, line 등)
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/channels")
async def list_agent_channels(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """agent 에 연결된 채널 목록.

    config_encrypted 는 노출 X. 메타만 (kind / external_id / is_active /
    timestamps). telegram 의 경우 bot_username 추출 (decrypt 후 token 은 절대
    응답에 포함 X).
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership(aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)
    eng = _get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT id, agent_id, kind, external_id, is_active,
                       config_encrypted, created_at, updated_at
                FROM agent_channels
                WHERE agent_id = :aid
                ORDER BY created_at DESC
                """
            ),
            {"aid": target_id},
        )
        items: list[dict[str, Any]] = []
        for r in rows:
            ch_id, ag_id, kind, ext_id, is_active, cfg_enc, created_at, updated_at = r
            # bot_username 만 추출 (telegram). token 은 절대 X.
            bot_username: str | None = None
            try:
                from src.common.crypto.fernet import decrypt_dict

                cfg = decrypt_dict(bytes(cfg_enc))
                bot_username = cfg.get("bot_username") or None
            except Exception:
                bot_username = None
            items.append(
                {
                    "id": str(ch_id),
                    "agent_id": str(ag_id),
                    "kind": kind,
                    "external_id": ext_id,
                    "is_active": bool(is_active),
                    "bot_username": bot_username,
                    "created_at": created_at.isoformat() if created_at else None,
                    "updated_at": updated_at.isoformat() if updated_at else None,
                }
            )
    return {"items": items}


# ---------------------------------------------------------------------------
# Channel connect 마법사 — admin UI (frontend ChannelConnectWizard) 가 호출.
# scripts/setup/register_telegram_agent.py 와 동일 로직 (channel_connect.py 공유).
# ---------------------------------------------------------------------------


class ChannelConnectIn(BaseModel):
    """admin 마법사 → 백엔드 — kind 별 입력 필드 union.

    kind=telegram: bot_token (필수), webhook_base_url (선택 — env 우선).
    kind=kakaowork: webhook_url (필수), secret (선택).
    kind=webhook: webhook_url (필수), auth_headers (선택), secret (선택).
    """

    kind: str = Field(..., pattern="^(telegram|kakaowork|webhook)$")
    bot_token: str | None = None
    webhook_url: str | None = None
    webhook_base_url: str | None = None
    secret: str | None = None
    auth_headers: dict[str, str] | None = None
    # telegram 한정 — getMe/setWebhook 까지 진행할지 (default true).
    register_webhook: bool = True


class ChannelConnectOut(BaseModel):
    channel_id: str
    kind: str
    external_id: str
    webhook_url: str | None = None
    status: str  # 'created' | 'updated'
    bot_username: str | None = None
    bot_id: int | None = None


@router.post("/{agent_id}/channels/connect", response_model=ChannelConnectOut)
async def connect_agent_channel(
    agent_id: str,
    body: ChannelConnectIn,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ChannelConnectOut:
    """채널 연결 마법사 — admin UI 가 호출.

    Telegram: BotFather token → getMe (검증) → secret_token 자동 생성 →
    agent_channels UPSERT → setWebhook 호출. 응답에 bot_username + webhook_url.

    KakaoWork / Webhook: webhook_url 등록만 (검증은 향후).

    권한: admin / owner 만. member 는 403.
    """
    from src.integration.external_agent.channel_connect import (
        ChannelConnectResult,
        connect_kakaowork_channel,
        connect_telegram_channel,
        connect_webhook_channel,
    )

    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("admin", "owner"):
        raise HTTPException(403, "channel connect requires admin/owner role")
    target_id = _parse_uuid(agent_id, "agent_id")
    await _load_agent_for_tenant(target_id, tid)

    eng = _get_engine()

    try:
        if body.kind == "telegram":
            if not body.bot_token:
                raise HTTPException(400, "bot_token is required for telegram")
            base = (body.webhook_base_url or "").strip() or settings.EXTERNAL_AGENT_WEBHOOK_BASE_URL.strip()
            if body.register_webhook and not base:
                raise HTTPException(
                    400,
                    "webhook_base_url 미설정 — env EXTERNAL_AGENT_WEBHOOK_BASE_URL "
                    "또는 admin 입력 (cloudflared trycloudflare URL 등) 필요.",
                )
            result: ChannelConnectResult = await connect_telegram_channel(
                eng,
                agent_id=target_id,
                tenant_id=tid,
                bot_token=body.bot_token,
                webhook_base_url=base,
                register_webhook=body.register_webhook,
            )
        elif body.kind == "kakaowork":
            if not body.webhook_url:
                raise HTTPException(400, "webhook_url is required for kakaowork")
            result = await connect_kakaowork_channel(
                eng,
                agent_id=target_id,
                tenant_id=tid,
                webhook_url=body.webhook_url,
                secret=body.secret,
            )
        elif body.kind == "webhook":
            if not body.webhook_url:
                raise HTTPException(400, "webhook_url is required for webhook")
            result = await connect_webhook_channel(
                eng,
                agent_id=target_id,
                tenant_id=tid,
                webhook_url=body.webhook_url,
                auth_headers=body.auth_headers,
                secret=body.secret,
            )
        else:
            raise HTTPException(400, f"unsupported kind: {body.kind}")
    except ValueError as e:
        # admin 입력 / token 검증 / silent rebind 차단 → 400.
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        # Telegram/외부 API 장애 → 502.
        raise HTTPException(502, f"channel external API failure: {e}") from e

    # 캐시 invalidate — 다음 webhook 호출 시 새 config 로드.
    try:
        from src.api.routers.external_agent_v1 import invalidate_channel_cache

        invalidate_channel_cache(result.kind, result.external_id)
    except Exception:
        pass  # best-effort — cache 미초기화 환경 무시.

    # audit log — record_action 은 fire-and-forget (background task).
    try:
        record_action(
            tenant_id=tid,
            user_id=aid,
            action="connect",
            resource_type="agent_channel",
            resource_id=result.channel_id,
            detail={
                "agent_id": str(target_id),
                "kind": result.kind,
                "external_id": result.external_id,
                "status": result.status,
                "register_webhook": body.register_webhook,
            },
        )
    except Exception:
        pass

    return ChannelConnectOut(
        channel_id=str(result.channel_id),
        kind=result.kind,
        external_id=result.external_id,
        webhook_url=result.webhook_url,
        status=result.status,
        bot_username=result.bot_username,
        bot_id=result.bot_id,
    )


# ---------------------------------------------------------------------------
# Agent draft (AI 자동 생성)
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent.parent / "agent_framework" / "agent_templates"

# 전체 가용 tool 목록 — CATEGORY_TOOLS 의 모든 값 합집합.
# plan_router 가 실제 런타임 카탈로그 정의이므로 여기서 직접 참조.
_ALL_AVAILABLE_TOOLS: frozenset[str] = frozenset(
    tool for tools in CATEGORY_TOOLS.values() for tool in tools
)

_DRAFT_SYSTEM_PROMPT = """\
당신은 KMS agent 정의 자동 생성기입니다. 사용자가 자연어로 설명한
업무 목표를 받아 다음 5요소를 한국어로 작성합니다:

1. goal: 1-2 단락 — agent 의 핵심 목표
2. guidelines_md: markdown — ## rules / ## slot_completeness_rules /
   ## escalation_rules 섹션 (마크다운 형식, 실제 업종/도메인 규칙 반영)
3. knowledge_isolation: strict / priority / broad 중 하나
   (의료/금융 등 컴플라이언스 강한 도메인 → strict, 일반 → priority)
4. allowed_tools: 가용 tool 카탈로그 중 *적합한* tool 만 선택 (배열)
5. done_when: 목표 달성 조건 (LLM 판정용 짧은 설명)

규칙:
- allowed_tools 는 반드시 입력 도구 카탈로그 안에서만 선택
- guidelines_md 는 해당 업종/도메인 의 실제 규칙 반영
- notes 에는 사용자가 참고할 주의사항이나 권고사항 작성 (없으면 빈 문자열)

JSON 출력 only (다른 텍스트 금지):
{
  "goal": "...",
  "guidelines_md": "## rules\\n- ...\\n\\n## slot_completeness_rules\\n- ...\\n\\n## escalation_rules\\n- ...",
  "knowledge_isolation": "priority",
  "allowed_tools": ["..."],
  "done_when": "...",
  "notes": "사용자에게 주의 사항"
}
"""

_DRAFT_USER_TEMPLATE = """\
업무 설명: {description}

{template_block}
가용 도구 카탈로그:
{tool_catalog}

위 설명에 맞는 agent 정의 JSON 을 작성하세요.
"""


def _load_template_block(category_id: str) -> str:
    """category_id 에 해당하는 템플릿 yaml 을 읽어 예시 prefill 블록 생성."""
    template_path = _TEMPLATES_DIR / f"{category_id}.yaml"
    if not template_path.exists():
        return ""
    try:
        data = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        tmpl = data.get("template", {})
        lines = [f"카테고리 템플릿 예시 ({category_id}):"]
        if tmpl.get("goal"):
            lines.append(f"  goal 예시: {tmpl['goal'].strip()[:200]}")
        if tmpl.get("guidelines"):
            lines.append(f"  guidelines 예시:\n{tmpl['guidelines'].strip()[:400]}")
        if tmpl.get("allowed_tools"):
            lines.append(f"  기본 tool: {tmpl['allowed_tools']}")
        if tmpl.get("knowledge_isolation"):
            lines.append(f"  knowledge_isolation 힌트: {tmpl['knowledge_isolation']}")
        return "\n".join(lines) + "\n\n"
    except Exception:
        return ""


def _build_tool_catalog() -> str:
    """가용 tool 이름 목록을 카탈로그 문자열로 변환."""
    return "\n".join(f"- {t}" for t in sorted(_ALL_AVAILABLE_TOOLS))


def _parse_draft_json(raw: str) -> dict:
    """LLM 응답에서 JSON 객체 추출 + 파싱."""
    raw = raw.strip()
    # json 코드블록 래퍼 제거
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # 첫 번째 { ~ 마지막 } 구간만 추출
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("JSON object not found in LLM response")
    return json.loads(raw[start : end + 1])


_VALID_ISOLATION = frozenset(["strict", "priority", "broad"])


@router.post("/draft", response_model=AgentDraftResponse)
async def draft_agent_from_description(
    body: AgentDraftRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentDraftResponse:
    """LLM 자동 agent 정의 생성.

    자연어 description + (선택) category_id → gemma-4-31b → goal / guidelines_md /
    knowledge_isolation / allowed_tools / done_when 추천 JSON.
    admin panel 의 "AI 생성" 버튼이 호출 — 사용자 자연어 한 줄 → 폼 자동 채움.
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")

    # 1. 카테고리 템플릿 prefill
    template_block = ""
    if body.category_id:
        template_block = _load_template_block(body.category_id)

    # 2. tool 카탈로그 구성
    tool_catalog = _build_tool_catalog()

    # 3. user prompt 구성
    user_prompt = _DRAFT_USER_TEMPLATE.format(
        description=body.description,
        template_block=template_block,
        tool_catalog=tool_catalog,
    )

    # 4. LLM 호출 (gemma-4-31b, json_object 모드)
    adapter = VLLMAdapter()
    try:
        raw = await adapter.complete(
            _DRAFT_SYSTEM_PROMPT,
            user_prompt,
            response_format="json_object",
        )
    except Exception as e:
        raise HTTPException(502, f"LLM 호출 실패: {e}") from e

    # 5. JSON 파싱
    try:
        data = _parse_draft_json(raw)
    except Exception as e:
        raise HTTPException(502, f"LLM 응답 파싱 실패: {e}") from e

    # 6. 필수 필드 검증
    goal = (data.get("goal") or "").strip()
    guidelines_md = (data.get("guidelines_md") or "").strip()
    if not goal:
        raise HTTPException(502, "LLM 이 goal 을 생성하지 못했습니다")
    if not guidelines_md:
        raise HTTPException(502, "LLM 이 guidelines_md 를 생성하지 못했습니다")

    # 7. knowledge_isolation 검증
    isolation = (data.get("knowledge_isolation") or "priority").strip()
    if isolation not in _VALID_ISOLATION:
        raise HTTPException(502, f"LLM 이 유효하지 않은 knowledge_isolation 을 반환했습니다: {isolation!r}")

    # 8. allowed_tools 화이트리스트 필터 (카탈로그 외 tool 거부)
    raw_tools: list = data.get("allowed_tools") or []
    if not isinstance(raw_tools, list):
        raw_tools = []
    allowed_tools = [t for t in raw_tools if isinstance(t, str) and t in _ALL_AVAILABLE_TOOLS]
    # kms_rag.search 는 항상 포함 (escape hatch)
    if "kms_rag.search" not in allowed_tools and "kms_rag.search" in _ALL_AVAILABLE_TOOLS:
        allowed_tools = ["kms_rag.search"] + allowed_tools

    return AgentDraftResponse(
        goal=goal,
        guidelines_md=guidelines_md,
        knowledge_isolation=isolation,  # type: ignore[arg-type]
        allowed_tools=allowed_tools,
        done_when=(data.get("done_when") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
    )


# ---------------------------------------------------------------------------
# Interview-driven SOP draft (Phase 1.5C Task 18)
# ---------------------------------------------------------------------------

# 19 카테고리 화이트리스트 — _meta.yaml 의 categories 와 일치해야 함.
_VALID_INTERVIEW_CATEGORIES: frozenset[str] = frozenset(
    [
        "beauty_skincare", "clothing_fashion", "culture_arts", "education",
        "finance", "hair_nail", "health_medical", "home_interior",
        "it_electronics", "kids_baby", "leisure_sports", "lodging",
        "other", "pet", "plants_flowers", "restaurant_cafe",
        "retail", "travel_agency", "wedding_dating",
    ]
)

_SOP_SAMPLES_DIR = _TEMPLATES_DIR / "sop_samples"
_INTERVIEW_DIR = _TEMPLATES_DIR / "interview_questions"


_INTERVIEW_SYSTEM_PROMPT = """\
당신은 KMS agent 의 *맞춤형 SOP markdown* 자동 작성기입니다.

입력으로 다음 3가지를 받습니다:
1. 산업 카테고리 (예: restaurant_cafe / health_medical)
2. 인터뷰 질문에 대한 사용자 답변 (dict)
3. 동일 카테고리의 표준 sample SOP markdown (참고용)

위 정보를 종합하여 사업장에 맞춤화된 SOP markdown 을 작성하세요.
sample SOP 의 7 섹션 구조 (페르소나 / 응대 시나리오 / 도구 사용 가이드 /
에스컬레이션 / 응답 톤 / 금지 사항 / 실패 응답 패턴) 를 그대로 유지하되,
사용자 답변의 구체 정보 (운영 시간 / 가격 / 인원 / 정책 등) 를 반영합니다.

규칙:
- markdown 7 섹션 모두 포함 (## 페르소나, ## 응대 시나리오, ## 도구 사용 가이드,
  ## 에스컬레이션, ## 응답 톤, ## 금지 사항, ## 실패 응답 패턴)
- sample 의 표현·뉘앙스 유지하되 사용자 답변으로 *구체화*
- 답변이 없는 영역은 sample 그대로 + 빈 항목은 "{관리자 작성 필요}" 표시
- suggested_tools 는 입력 도구 카탈로그 안에서만 선택
- persona 는 1-2 줄로 요약 (UI agent.persona 필드용)
- 이모지 절대 사용 X
- 의학·금융 등 컴플라이언스 영역의 주의사항은 강조

JSON 출력 only (다른 텍스트 금지):
{
  "sop_markdown": "# {카테고리} SOP\\n\\n## 페르소나\\n...\\n",
  "persona": "1-2 줄 페르소나 요약",
  "suggested_tools": ["kms_rag.search", "schedule.create", ...],
  "notes": "관리자 참고 사항 (없으면 빈 문자열)"
}
"""

_INTERVIEW_USER_TEMPLATE = """\
산업 카테고리: {category}

인터뷰 답변:
{answers_block}

표준 sample SOP (참고):
---
{sample_sop}
---

가용 도구 카탈로그:
{tool_catalog}

위 내용을 종합하여 *사업장 맞춤* SOP markdown 을 작성하세요.
"""


def _load_sample_sop(category: str) -> str:
    """sop_samples/{category}.md 로드. 없으면 빈 문자열."""
    path = _SOP_SAMPLES_DIR / f"{category}.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _format_interview_answers(answers: dict[str, str]) -> str:
    """answers dict → '- {id}: {value}' 라인."""
    if not answers:
        return "(인터뷰 답변 없음 — sample 기반 기본 SOP 작성)"
    lines: list[str] = []
    for k, v in answers.items():
        if v is None or str(v).strip() == "":
            continue
        # 너무 긴 답변은 잘라서 prompt 보호
        v_str = str(v).strip()
        if len(v_str) > 500:
            v_str = v_str[:500] + "..."
        lines.append(f"- {k}: {v_str}")
    if not lines:
        return "(인터뷰 답변 없음 — sample 기반 기본 SOP 작성)"
    return "\n".join(lines)


def _interview_default_response(
    category: str,
    sample_sop: str,
) -> InterviewDraftResponse:
    """answers 가 비어있을 때 sample 그대로 반환 (LLM 호출 생략).

    빈 인터뷰여도 admin 이 일단 작업 시작할 수 있도록 sample 을 그대로 prefill.
    """
    persona_line = ""
    # sample 의 ## 페르소나 섹션 첫 단락 추출 (best-effort)
    if "## 페르소나" in sample_sop:
        after = sample_sop.split("## 페르소나", 1)[1]
        # 다음 ## 섹션 직전까지
        if "\n##" in after:
            after = after.split("\n##", 1)[0]
        persona_line = after.strip().split("\n\n", 1)[0].strip()
        if len(persona_line) > 200:
            persona_line = persona_line[:200] + "..."
    return InterviewDraftResponse(
        sop_markdown=sample_sop or f"# {category} SOP\n\n(sample 미존재 — 직접 작성 필요)",
        persona=persona_line,
        suggested_tools=["kms_rag.search"],
        notes="인터뷰 답변이 비어있어 표준 sample 을 그대로 반환했습니다. 인터뷰 마법사로 답변을 채우시면 맞춤형 SOP 가 생성됩니다.",
    )


@router.post("/draft-from-interview", response_model=InterviewDraftResponse)
async def draft_sop_from_interview(
    body: InterviewDraftRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> InterviewDraftResponse:
    """인터뷰 답변 + 산업 sample SOP → 맞춤형 SOP markdown 자동 작성.

    - **category**: 19 카테고리 ID (예: restaurant_cafe / health_medical).
    - **answers**: ``interview_questions/{category}.yaml`` 의 question id 를
      key 로 하는 답변 dict. 비면 sample SOP 그대로 반환 (LLM 호출 X).

    Phase 1.5C Task 18. admin/owner role 만 호출 가능. Gemma-4-12b 권장 — 작고
    빠르며 한국어 markdown 생성에 충분.
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")

    category = body.category.strip().lower()
    if category not in _VALID_INTERVIEW_CATEGORIES:
        raise HTTPException(
            400,
            f"invalid category: {body.category!r}. "
            f"must be one of {sorted(_VALID_INTERVIEW_CATEGORIES)}",
        )

    # 1. sample SOP 로드 (참고용 / fallback)
    sample_sop = _load_sample_sop(category)

    # 2. answers 가 비면 sample 그대로 반환 — LLM 호출 생략
    filtered_answers = {
        k: v for k, v in (body.answers or {}).items()
        if v is not None and str(v).strip() != ""
    }
    if not filtered_answers:
        return _interview_default_response(category, sample_sop)

    # 3. user prompt 구성
    answers_block = _format_interview_answers(filtered_answers)
    tool_catalog = _build_tool_catalog()
    user_prompt = _INTERVIEW_USER_TEMPLATE.format(
        category=category,
        answers_block=answers_block,
        sample_sop=sample_sop or "(sample 미존재)",
        tool_catalog=tool_catalog,
    )

    # 4. LLM 호출 (gemma-4-12b 권장 — 빠름 + 충분한 한국어 markdown 작성 능력)
    adapter = VLLMAdapter()
    try:
        raw = await adapter.complete(
            _INTERVIEW_SYSTEM_PROMPT,
            user_prompt,
            response_format="json_object",
            model="gemma-4-12b",
        )
    except Exception as e:
        raise HTTPException(502, f"LLM 호출 실패: {e}") from e

    # 5. JSON 파싱
    try:
        data = _parse_draft_json(raw)
    except Exception as e:
        raise HTTPException(502, f"LLM 응답 파싱 실패: {e}") from e

    # 6. 필수 필드 검증
    sop_md = (data.get("sop_markdown") or "").strip()
    if not sop_md:
        raise HTTPException(502, "LLM 이 sop_markdown 을 생성하지 못했습니다")

    persona = (data.get("persona") or "").strip()
    if len(persona) > 500:
        persona = persona[:500]

    # 7. suggested_tools 화이트리스트 필터
    raw_tools = data.get("suggested_tools") or []
    if not isinstance(raw_tools, list):
        raw_tools = []
    suggested = [
        t for t in raw_tools
        if isinstance(t, str) and t in _ALL_AVAILABLE_TOOLS
    ]
    if "kms_rag.search" not in suggested and "kms_rag.search" in _ALL_AVAILABLE_TOOLS:
        suggested = ["kms_rag.search"] + suggested

    return InterviewDraftResponse(
        sop_markdown=sop_md,
        persona=persona,
        suggested_tools=suggested,
        notes=(data.get("notes") or "").strip() or None,
    )


# ---------------------------------------------------------------------------
# Field-level AI suggestion (2026-05-07)
#
# AgentEditPage 의 각 input 옆 "AI 제안" 버튼이 호출. 한 필드씩 LLM 제안 받아
# 사용자가 막막함 없이 시작/이어 작성 가능하게 함.
#
# 8 field × 동일 endpoint — field 별 prompt 분기.
# 한국어 강제 + alternatives 2-3개 + reasoning (선택).
# ---------------------------------------------------------------------------

# 필드별 시스템 프롬프트 — 각각 짧고 명확하게.
_SUGGEST_SYSTEM_BASE = """\
당신은 한국어 전용 KMS 에이전트 정의 보조 작성기입니다.

역할:
- 사용자가 비어 있는 입력 필드를 채울 수 있도록 *구체적이고 사용 가능한* 한국어 제안을 만듭니다.
- 항상 한국어로 답변합니다 (영어 / 일본어 / 다른 언어 금지).
- 이모지 사용 절대 금지.
- 군대 어휘 (발사·발화 등) 금지 — 송출·전달·실행 같은 업무 어휘 사용.
- 사용자가 이미 채워둔 다른 필드 (context.existing) 와 *일관성* 유지 — 이름이 카페 봇이면 의료 페르소나 추천 X.
- alternatives 는 같은 의도지만 어조·관점이 다른 2-3 개 대안.
- JSON 출력만, 다른 텍스트 금지.
"""

_FIELD_PROMPTS: dict[str, str] = {
    "name": """\
이번에 작성할 필드: name (에이전트 이름).

요구 사항:
- 짧고 친근한 한국어 봇 이름 (8-20자 권장).
- 도메인이 한 눈에 보이도록 — 예: "꽃집 주문 봇", "치과 예약 도우미".
- 영어 대문자/약자 남용 금지.

JSON 출력 형식:
{
  "suggestion": "1차 추천 이름",
  "alternatives": ["대안1", "대안2", "대안3"],
  "reasoning": "왜 이 이름인지 한 줄 (선택)"
}
""",
    "description": """\
이번에 작성할 필드: description (한 줄 설명).

요구 사항:
- 1-2 문장 한국어 — 봇이 누구를 어떻게 도와주는지 명확하게.
- 마케팅 카피 X, 사용자가 첫 화면에서 보고 즉시 용도를 이해할 수 있는 문장.

JSON 출력 형식:
{
  "suggestion": "1-2 문장 설명",
  "alternatives": ["대안1", "대안2"],
  "reasoning": null
}
""",
    "persona": """\
이번에 작성할 필드: persona (페르소나 — 어조·성격·전문성).

요구 사항:
- 1-3 줄 한국어 — 봇이 어떤 어조와 태도로 응대하는지 묘사.
- name + description 과 일관 — 카페 봇은 친근하게, 의료 봇은 차분하고 정확하게.
- 금지 표현 (이모지·군대 어휘) 명시 권장.

JSON 출력 형식:
{
  "suggestion": "1-3 줄 페르소나 묘사",
  "alternatives": ["대안1", "대안2"],
  "reasoning": null
}
""",
    "system_prompt": """\
이번에 작성할 필드: system_prompt (LLM 매 turn 상단 inject 되는 최상위 행동 규칙).

요구 사항:
- 3-7 줄 한국어 — *최상위 행동 규칙* (goal/guidelines 보다 우선되는).
- name + persona + goal + guidelines_md 종합하여 *이 봇이 응대 시 항상 지킬* 핵심 5-7개 규칙 압축.
- 첫 줄: "당신은 {name} 입니다. {1줄 역할 요약}." 형식.
- 마지막 줄: 항상 한국어 응답 강제 + 권한·도구 제약 명시.

JSON 출력 형식:
{
  "suggestion": "system_prompt 본문 (3-7 줄)",
  "alternatives": ["보수적 버전", "친근한 버전"],
  "reasoning": null
}
""",
    "goal": """\
이번에 작성할 필드: goal (이 봇이 무엇을 해결하는가).

요구 사항:
- 1-2 문장 한국어 — *봇 존재 이유*. KPI/달성 조건 명확.
- name + description 과 일관.

JSON 출력 형식:
{
  "suggestion": "1-2 문장 goal",
  "alternatives": ["대안1", "대안2"],
  "reasoning": null
}
""",
    "guidelines_md": """\
이번에 작성할 필드: guidelines_md (markdown 형식 동작 지침).

요구 사항:
- markdown 4-6 섹션 한국어 — ## 역할 / ## 응대 흐름 / ## 도구 사용 / ## 제약 / ## 실패 응답.
- name + persona + goal 종합 — 이 봇이 실제로 응대할 때 따를 *구체* 규칙.
- 사용자가 그대로 사용해도 동작할 정도로 구체적.

JSON 출력 형식:
{
  "suggestion": "markdown 본문",
  "alternatives": ["짧은 버전 (2-3 섹션)"],
  "reasoning": null
}
""",
    "done_when": """\
이번에 작성할 필드: done_when (대화 종료 판정 조건).

요구 사항:
- 1 문장 한국어 — *언제 봇이 한 turn / 한 대화를 마무리하는가*.
- goal 과 자연스럽게 연결.

JSON 출력 형식:
{
  "suggestion": "1 문장 종료 조건",
  "alternatives": ["대안1", "대안2"],
  "reasoning": null
}
""",
    "allowed_tools": """\
이번에 작성할 필드: allowed_tools (이 봇이 사용 가능한 도구 ID 리스트).

요구 사항:
- name + description + goal 분석하여 *반드시 필요한* 도구만 추천.
- 가용 도구 카탈로그 안에서만 선택 — 카탈로그 외 ID 절대 X.
- kms_rag.search 는 항상 포함.
- 추천 이유를 reasoning 에 1-2 줄 한국어로.

JSON 출력 형식:
{
  "suggestion": "선택한 도구 ID 들을 콤마(,)로 연결한 문자열",
  "tool_ids": ["kms_rag.search", "schedule.create", ...],
  "alternatives": [],
  "reasoning": "왜 이 도구들이 필요한지 한국어 1-2 줄"
}
""",
}


def _format_existing_context(ctx: dict[str, Any]) -> str:
    """이미 채워진 context dict → '- {key}: {value}' lines."""
    lines: list[str] = []
    if ctx.get("industry_hint"):
        lines.append(f"- industry_hint (사용자 자연어 hint): {ctx['industry_hint']}")
    for key in ("name", "description", "persona", "goal", "done_when", "system_prompt"):
        v = ctx.get(key)
        if v and isinstance(v, str) and v.strip():
            v_trim = v.strip()
            if len(v_trim) > 400:
                v_trim = v_trim[:400] + "..."
            lines.append(f"- {key}: {v_trim}")
    gm = ctx.get("guidelines_md")
    if gm and isinstance(gm, str) and gm.strip():
        v_trim = gm.strip()
        if len(v_trim) > 600:
            v_trim = v_trim[:600] + "..."
        lines.append(f"- guidelines_md (요약):\n{v_trim}")
    tools = ctx.get("allowed_tools")
    if tools and isinstance(tools, list):
        lines.append(f"- allowed_tools: {tools}")
    if not lines:
        return "(아직 입력된 정보가 없습니다 — 일반적인 KMS 봇 가정)"
    return "\n".join(lines)


def _coerce_str_list(raw: Any, *, max_len: int = 3) -> list[str]:
    """LLM 출력의 alternatives 등 — 문자열 리스트로 안전하게 변환."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
        if len(out) >= max_len:
            break
    return out


@router.post("/suggest", response_model=AgentSuggestResponse)
async def suggest_agent_field(
    body: AgentSuggestRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentSuggestResponse:
    """단일 필드 AI 제안 — 사용자가 입력 필드 옆 "AI 제안" 버튼 클릭 시 호출.

    field = name | description | persona | system_prompt | goal |
            guidelines_md | done_when | allowed_tools

    context.existing 의 다른 필드 + industry_hint 를 종합하여
    gemma-4-31b 가 한국어 서술형 추천 + 2-3 alternatives 생성.
    응답 timeout 10s — 실패 시 502 (frontend 가 placeholder 로 fallback).
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")

    field = body.field
    if field not in _FIELD_PROMPTS:
        raise HTTPException(400, f"unknown field: {field!r}")

    ctx_dict = body.context.model_dump(exclude_none=True)
    existing_block = _format_existing_context(ctx_dict)

    user_prompt_parts = [
        "현재 사용자가 채운 다른 필드 (context):",
        existing_block,
        "",
    ]
    # allowed_tools 필드는 가용 카탈로그도 함께 prompt 에 동봉.
    if field == "allowed_tools":
        user_prompt_parts.extend([
            "가용 도구 카탈로그:",
            _build_tool_catalog(),
            "",
        ])
    user_prompt_parts.append(_FIELD_PROMPTS[field])
    user_prompt = "\n".join(user_prompt_parts)

    system_prompt = _SUGGEST_SYSTEM_BASE + "\n" + _FIELD_PROMPTS[field]

    adapter = VLLMAdapter()
    try:
        # gemma-4-31b 기본 — vLLM endpoint. 한국어 질이 가장 좋음.
        raw = await adapter.complete(
            system_prompt,
            user_prompt,
            response_format="json_object",
        )
    except Exception as e:
        raise HTTPException(502, f"LLM 호출 실패: {e}") from e

    try:
        data = _parse_draft_json(raw)
    except Exception as e:
        raise HTTPException(502, f"LLM 응답 파싱 실패: {e}") from e

    suggestion = (data.get("suggestion") or "").strip()
    if not suggestion:
        raise HTTPException(502, "LLM 이 suggestion 을 생성하지 못했습니다")

    alternatives = _coerce_str_list(data.get("alternatives"), max_len=3)
    reasoning_raw = data.get("reasoning")
    reasoning = reasoning_raw.strip() if isinstance(reasoning_raw, str) else None
    if reasoning == "":
        reasoning = None

    tool_ids: list[str] | None = None
    if field == "allowed_tools":
        raw_tool_ids = data.get("tool_ids") or []
        if not isinstance(raw_tool_ids, list):
            raw_tool_ids = []
        tool_ids = [
            t for t in raw_tool_ids
            if isinstance(t, str) and t in _ALL_AVAILABLE_TOOLS
        ]
        if "kms_rag.search" not in tool_ids and "kms_rag.search" in _ALL_AVAILABLE_TOOLS:
            tool_ids = ["kms_rag.search"] + tool_ids
        # suggestion 도 tool_ids 와 일치하게 — UI 가 표시할 때 안정성.
        suggestion = ", ".join(tool_ids) if tool_ids else suggestion

    return AgentSuggestResponse(
        suggestion=suggestion,
        alternatives=alternatives,
        reasoning=reasoning,
        tool_ids=tool_ids,
    )


_BULK_SUGGEST_SYSTEM = """\
당신은 한국어 전용 KMS 에이전트 정의 일괄 작성 보조기입니다.

역할:
- 사용자가 자연어로 적은 한 줄 industry_hint (예: "치과 예약 봇") 를 받아
  *5 개 필드를 한 번에* 한국어로 작성합니다:
  name / description / persona / goal / guidelines_md.
- 추가로 추천 도구 ID 리스트 (suggested_tools) 를 가용 카탈로그에서만 선택합니다.

규칙:
- 항상 한국어 (영어 / 일본어 / 다른 언어 금지).
- 이모지 절대 금지.
- 군대 어휘 금지.
- 5 필드는 서로 일관 — name 의 도메인이 description / persona / goal 에 동일하게 반영.
- guidelines_md 는 markdown — ## 역할, ## 응대 흐름, ## 도구 사용, ## 제약, ## 실패 응답 5 섹션.
- suggested_tools 는 카탈로그 안에서만, 꼭 필요한 도구만 (kms_rag.search 항상 포함).
- JSON 출력만, 다른 텍스트 금지.

JSON 출력 형식:
{
  "name": "봇 이름",
  "description": "1-2 문장 설명",
  "persona": "1-3 줄 페르소나",
  "goal": "1-2 문장 goal",
  "guidelines_md": "## 역할\\n...\\n\\n## 응대 흐름\\n...",
  "suggested_tools": ["kms_rag.search", ...],
  "notes": "사용자 참고 사항 (없으면 빈 문자열)"
}
"""


@router.post("/suggest/bulk-from-hint", response_model=AgentBulkSuggestResponse)
async def suggest_agent_bulk_from_hint(
    body: AgentBulkSuggestRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> AgentBulkSuggestResponse:
    """industry_hint 한 줄 → 5 필드 + 도구 추천 일괄 생성.

    AgentEditPage 상단 "AI 추천 시작" 버튼이 호출. 사용자가 hint 입력 ("치과 예약 봇") →
    name / description / persona / goal / guidelines_md / suggested_tools 한 번에 채움.
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership(aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")

    hint = body.industry_hint.strip()
    if not hint:
        raise HTTPException(400, "industry_hint must not be empty")

    user_prompt = (
        f"industry_hint: {hint}\n\n"
        f"가용 도구 카탈로그:\n{_build_tool_catalog()}\n\n"
        "위 정보로 5 필드 + suggested_tools JSON 을 작성하세요."
    )

    adapter = VLLMAdapter()
    try:
        raw = await adapter.complete(
            _BULK_SUGGEST_SYSTEM,
            user_prompt,
            response_format="json_object",
        )
    except Exception as e:
        raise HTTPException(502, f"LLM 호출 실패: {e}") from e

    try:
        data = _parse_draft_json(raw)
    except Exception as e:
        raise HTTPException(502, f"LLM 응답 파싱 실패: {e}") from e

    raw_tools = data.get("suggested_tools") or []
    if not isinstance(raw_tools, list):
        raw_tools = []
    tools = [t for t in raw_tools if isinstance(t, str) and t in _ALL_AVAILABLE_TOOLS]
    if "kms_rag.search" not in tools and "kms_rag.search" in _ALL_AVAILABLE_TOOLS:
        tools = ["kms_rag.search"] + tools

    return AgentBulkSuggestResponse(
        name=(data.get("name") or "").strip(),
        description=(data.get("description") or "").strip(),
        persona=(data.get("persona") or "").strip(),
        goal=(data.get("goal") or "").strip(),
        guidelines_md=(data.get("guidelines_md") or "").strip(),
        suggested_tools=tools,
        notes=(data.get("notes") or "").strip() or None,
    )
