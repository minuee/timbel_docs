from __future__ import annotations
import json
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_validator

# Phase 3 (#154) — 도구 scope override 정책.
from src.agent_framework.tools.scope_resolver import (
    SCOPE_RANK,
    get_default_scope,
)


# 입력 크기 상한 (GPT-5 P1 fix — DoS 방지).
_TOOL_SCOPE_OVERRIDES_MAX_KEYS = 200
_TOOL_SCOPE_OVERRIDES_MAX_BYTES = 16 * 1024  # 16 KB JSON 직렬화


def _validate_tool_scope_overrides(v: dict[str, str] | None) -> dict[str, str]:
    """tool_scope_overrides validator — 승격 금지 + 크기 상한 + 알 수 없는 scope.

    Phase 3 (#154) 정책:
    - SCOPE_RANK = {tenant:4, user:3, agent:2, session:1}
    - default 보다 *낮거나 같은* 등급만 허용 (승격 차단).
    - 미등록 tool 은 'agent' fallback (가장 좁은 안전 default — Phase 4 가
      manifest 와 통합 시 차단으로 승격 가능).
    - 키 수 200 + 16KB JSON 상한 (GPT-5 P1).
    """
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ValueError("tool_scope_overrides must be a dict")
    if len(v) > _TOOL_SCOPE_OVERRIDES_MAX_KEYS:
        raise ValueError(
            f"tool_scope_overrides has too many keys "
            f"(max {_TOOL_SCOPE_OVERRIDES_MAX_KEYS}, got {len(v)})"
        )
    serialized = json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    if len(serialized.encode("utf-8")) > _TOOL_SCOPE_OVERRIDES_MAX_BYTES:
        raise ValueError(
            f"tool_scope_overrides too large "
            f"(max {_TOOL_SCOPE_OVERRIDES_MAX_BYTES} bytes serialized)"
        )
    out: dict[str, str] = {}
    for tool, scope in v.items():
        if not isinstance(tool, str) or not tool:
            raise ValueError(f"invalid tool key: {tool!r}")
        if not isinstance(scope, str) or scope not in SCOPE_RANK:
            raise ValueError(
                f"{tool}: invalid scope {scope!r} "
                f"(allowed: {sorted(SCOPE_RANK)})"
            )
        default = get_default_scope(tool)
        if SCOPE_RANK[scope] > SCOPE_RANK[default]:
            raise ValueError(
                f"{tool}: cannot promote default '{default}' → '{scope}' "
                "(승격 금지 — 동등 또는 하향만 허용)"
            )
        out[tool] = scope
    return out


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    goal: str = Field(min_length=10)
    guidelines_md: str = Field(min_length=10)
    primary_repo_ids: list[UUID] = Field(default_factory=list)
    fallback_repo_ids: list[UUID] = Field(default_factory=list)
    knowledge_isolation: Literal["strict", "priority", "broad"] = "priority"
    allowed_tools: list[str] = Field(default_factory=list)
    done_when: str | None = None
    test_mode_visible: bool = True


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    goal: str | None = None
    guidelines_md: str | None = None
    primary_repo_ids: list[UUID] | None = None
    fallback_repo_ids: list[UUID] | None = None
    knowledge_isolation: Literal["strict", "priority", "broad"] | None = None
    allowed_tools: list[str] | None = None
    done_when: str | None = None
    test_mode_visible: bool | None = None
    is_active: bool | None = None
    # 069 (Plan A v3) — 4-mode 웹검색 enum.
    web_search_mode: Literal["off", "separate", "blended", "web_only"] | None = None
    # 075 (Phase 3 #154) — agent 별 도구 scope override (승격 금지).
    tool_scope_overrides: dict[str, str] | None = None

    @field_validator("tool_scope_overrides")
    @classmethod
    def _check_overrides(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return None
        return _validate_tool_scope_overrides(v)


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    goal: str
    guidelines_md: str
    primary_repo_ids: list[UUID]
    fallback_repo_ids: list[UUID]
    knowledge_isolation: str
    allowed_tools: list[str]
    done_when: str | None
    test_mode_visible: bool
    is_active: bool
    template_id: UUID | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    # 069 (Plan A v3) — 4-mode 웹검색 enum. default 'off'.
    web_search_mode: Literal["off", "separate", "blended", "web_only"] = "off"
    # 075 (Phase 3 #154) — agent 별 도구 scope override (승격 금지).
    tool_scope_overrides: dict[str, str] = Field(default_factory=dict)


class AgentDraftRequest(BaseModel):
    description: str = Field(min_length=5, max_length=500)
    category_id: str | None = None  # 19 템플릿 카테고리 (선택)


class AgentDraftResponse(BaseModel):
    goal: str
    guidelines_md: str
    knowledge_isolation: Literal["strict", "priority", "broad"] = "priority"
    allowed_tools: list[str]
    done_when: str | None = None
    notes: str | None = None  # LLM 의 자연어 설명 / 주의사항


# ---------------------------------------------------------------------------
# Interview-driven SOP draft (Phase 1.5C Task 18)
# ---------------------------------------------------------------------------


class InterviewDraftRequest(BaseModel):
    """카테고리 + 인터뷰 답변 → 맞춤형 SOP markdown 자동 작성 요청."""

    category: str = Field(min_length=1, max_length=50)
    answers: dict[str, str] = Field(default_factory=dict)


class InterviewDraftResponse(BaseModel):
    """LLM 이 생성한 SOP markdown + 메타.

    - sop_markdown: 7 섹션 (페르소나 / 응대 시나리오 / 도구 사용 가이드 /
      에스컬레이션 / 응답 톤 / 금지 사항 / 실패 응답 패턴) 포함 markdown.
    - persona: 1-2 줄 요약 (UI agent.persona 필드에 prefill).
    - suggested_tools: 카탈로그 내 추천 도구 화이트리스트.
    """

    sop_markdown: str
    persona: str = ""
    suggested_tools: list[str] = Field(default_factory=list)
    notes: str | None = None


# ---------------------------------------------------------------------------
# Field-level AI suggestion (2026-05-07 — admin agent edit page 막막함 해소)
# ---------------------------------------------------------------------------

# 8 개 가능한 field — 한 번에 한 필드씩 LLM 제안.
SuggestField = Literal[
    "name",
    "description",
    "persona",
    "system_prompt",
    "goal",
    "guidelines_md",
    "done_when",
    "allowed_tools",
]


class AgentSuggestContext(BaseModel):
    """이미 채워진 다른 필드 + 사용자 hint — LLM 일관성 유지에 사용."""

    name: str | None = None
    description: str | None = None
    persona: str | None = None
    system_prompt: str | None = None
    goal: str | None = None
    guidelines_md: str | None = None
    done_when: str | None = None
    allowed_tools: list[str] | None = None
    industry_hint: str | None = None  # "치과 예약 봇" 같은 자연어 hint


class AgentSuggestRequest(BaseModel):
    """단일 필드 제안 요청."""

    field: SuggestField
    context: AgentSuggestContext = Field(default_factory=AgentSuggestContext)


class AgentSuggestResponse(BaseModel):
    """LLM 이 생성한 단일 필드 제안.

    - suggestion: 1차 추천 (서술형 텍스트 또는 도구 ID 리스트의 JSON 문자열).
    - alternatives: 2-3 개 대안 (선택지 picker 용).
    - reasoning: 왜 이 제안인지 (선택, 설명 필요한 필드만).
    - tool_ids: allowed_tools 필드일 때만 채움 — 화이트리스트된 도구 ID 리스트.
    """

    suggestion: str
    alternatives: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    tool_ids: list[str] | None = None


class AgentBulkSuggestRequest(BaseModel):
    """industry_hint 한 줄 → 5 필드 일괄 제안."""

    industry_hint: str = Field(min_length=1, max_length=200)


class AgentBulkSuggestResponse(BaseModel):
    """name + description + persona + goal + guidelines_md 한 번에."""

    name: str = ""
    description: str = ""
    persona: str = ""
    goal: str = ""
    guidelines_md: str = ""
    suggested_tools: list[str] = Field(default_factory=list)
    notes: str | None = None
