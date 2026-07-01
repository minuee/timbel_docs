"""ToolOutcome enum + ToolResult 표준 contract — Phase 1.5A.

핵심 원칙: success ≠ outcome 분리.
- success: tool 실행 성공 여부 (외부 dependency / runtime error 만 false)
- meta.outcome: 사용자 요청 결과 상태 (empty/saturated/conflict 등도 success=true)

plan executor 가 success=true 면 retry/대체 호출 안 함.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class ToolOutcome(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    PARTIAL = "partial"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    TOO_MANY_MATCHES = "too_many_matches"
    AMBIGUOUS_TARGET = "ambiguous_target"
    INVALID_INPUT = "invalid_input"
    MISSING_REQUIRED_SLOT = "missing_required_slot"
    PAST_TIME = "past_time"
    TOO_FAR_FUTURE = "too_far_future"
    PERMISSION_DENIED = "permission_denied"
    AUTH_REQUIRED = "auth_required"
    NOT_OWNER = "not_owner"
    QUOTA_EXCEEDED = "quota_exceeded"
    RATE_LIMITED = "rate_limited"
    COOLDOWN = "cooldown"
    TIMEOUT = "timeout"
    EXTERNAL_API_FAIL = "external_api_fail"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    LOW_CONFIDENCE = "low_confidence"
    POLICY_BLOCKED = "policy_blocked"
    UNSAFE_NEEDS_CONFIRM = "unsafe_needs_confirm"
    SATURATED = "saturated"
    OUTSIDE_WORKING_HOURS = "outside_working_hours"
    UNKNOWN_RESOURCE = "unknown_resource"
    SOP_MISSING = "sop_missing"
    SOP_STALE = "sop_stale"
    UNSUPPORTED = "unsupported"


class OutcomeKind(str, Enum):
    DOMAIN_EMPTY = "domain_empty"
    DOMAIN_CONFLICT = "domain_conflict"
    POLICY = "policy"
    EXTERNAL_DEPENDENCY = "external_dependency"
    VALIDATION = "validation"


@dataclass
class ToolResultMeta:
    outcome: ToolOutcome
    reason: str
    kind: str  # OutcomeKind value
    retryable: bool = False
    user_action_required: bool = False
    alternatives: list[Any] = field(default_factory=list)
    slots_echo: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    success: bool
    items: list[Any] | None = None
    summary: str = ""
    meta: ToolResultMeta = field(default_factory=lambda: ToolResultMeta(
        outcome=ToolOutcome.OK, reason="", kind=OutcomeKind.DOMAIN_EMPTY.value,
    ))
    error: str | None = None
    error_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # outcome enum → string
        if "meta" in d and "outcome" in d["meta"]:
            d["meta"]["outcome"] = self.meta.outcome.value if isinstance(self.meta.outcome, ToolOutcome) else self.meta.outcome
        return d
