"""D72 (2026-05-12) — call-time allowed_tools 강제 가드.

# 결함 배경
D71 #261 사례: stock_info 봇 (allowed_tools=[]) 가 "삼성전자 매수해줘" 발화에
대해 *실제 stock.add_watch* 호출 + 등록 성공. 17/30 시나리오 도구 우회.

= call-time gate 우회. D39 의 admin allowlist filter 가 admin path 만 처리,
non-admin role agent 의 allowed_tools 가 도구 dispatch 직전에 무시됨.

# 설계 (GPT-5 사전 verdict 반영)

## 의미 통일
- ``allowed_tools is None``  → *open* (legacy / default chat / agent_context 없음)
- ``allowed_tools == []``    → *closed* (명시적 deny-all — admin 도 role 도 동일)
- ``allowed_tools == [...]`` → 명시 list 만 허용

admin asymmetry footgun 차단. D39 fallback 의 "admin 빈 list = 전체 허용"
동작은 호출 측 (tool_calling_loop) 에서 별도로 처리되며, helper 는 *순수 강제*
의미만 표현.

## 시그니처 — 덕 타이핑
``agent_context`` 는 다음 attribute 만 의존:
- ``is_admin`` (bool)
- ``allowed_tools`` (list[str] | None)
- ``agent_id`` (UUID | str | None) — 로깅용

D73 SenderContext 도입 시 별도 adapter 없이도 호환.

## 적용 — defense-in-depth
1. ``ToolRegistry.call()`` choke point (단일 dispatch — engine 11+ site 보호).
2. ``tool_calling_loop.py`` valid_names 검사 직전 (LLM 결과에 빠른 에러 피드백).
3. ``plan_orchestrator.py`` tool_subset 의 allowed_tools 교집합 (plan 단계 노출
   차단).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)


def _is_enabled() -> bool:
    """D78 kill-switch — 신규 키 우선, 미설정 시 구형 키 fallback.

    - ``KMS_TOOL_GUARD_ENABLED`` (신규) — 설정 시 이 값만 사용.
    - ``KMS_TOOL_GUARD_ENFORCE`` (구형 alias) — 신규 키 미설정 시 fallback.
    - default = true (회귀 0).

    false/0/no/off 시 가드 우회 (모든 호출 allowed=True 반환).
    """
    raw = os.getenv("KMS_TOOL_GUARD_ENABLED")
    if raw is None:
        raw = os.getenv("KMS_TOOL_GUARD_ENFORCE", "true")
    return (raw or "").strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class GuardDecision:
    """가드 결과.

    - ``allowed`` : 호출 허용 여부.
    - ``code``    : 차단 시 stable 코드 (테스트/메트릭 anchor).
    - ``reason``  : 사람-읽기 가능한 이유 (로그 용).
    """

    allowed: bool
    code: str | None = None
    reason: str | None = None


def enforce_allowed_tools(
    agent_context: Any,
    tool_name: str,
) -> GuardDecision:
    """agent_context.allowed_tools 강제 검증.

    Returns
    -------
    GuardDecision
        - ``agent_context is None`` → ``allowed=True`` (legacy / default chat).
        - ``allowed_tools is None``  → ``allowed=True`` (open — agent_context
          이 있지만 명시 list 미정의).
        - ``allowed_tools == []``    → ``allowed=False`` (명시적 deny-all).
        - ``tool_name not in allowed_tools`` → ``allowed=False``.
        - 그 외 → ``allowed=True``.
    """
    # D78 — 분모 metric (진입 횟수, kill-switch 검사 *전*).
    try:
        from src.common.metrics import inc_guard_input

        inc_guard_input("tool_guard")
    except Exception:  # noqa: BLE001
        pass

    # D78 kill-switch — bypass 시 모두 허용 (회귀 0; default=true 시 기존 동작).
    if not _is_enabled():
        return GuardDecision(allowed=True)

    if agent_context is None:
        return GuardDecision(allowed=True)

    allowed_raw = getattr(agent_context, "allowed_tools", None)
    # None = open. 빈 list/tuple 와 구별 (None 은 "정의 안 됨", [] 는 "명시적 빈").
    if allowed_raw is None:
        return GuardDecision(allowed=True)

    allowed = set(allowed_raw)
    if not allowed:
        # D78 — block hit counter (empty_allowed).
        try:
            from src.common.metrics import inc_tool_guard_block

            inc_tool_guard_block("empty_allowed")
        except Exception:  # noqa: BLE001
            pass
        return GuardDecision(
            allowed=False,
            code="empty_allowed_tools",
            reason=(
                f"Agent {getattr(agent_context, 'agent_id', '')} has no "
                f"allowed_tools (explicit deny-all)."
            ),
        )
    if tool_name not in allowed:
        # D78 — block hit counter (not_in_allowed).
        try:
            from src.common.metrics import inc_tool_guard_block

            inc_tool_guard_block("not_in_allowed")
        except Exception:  # noqa: BLE001
            pass
        return GuardDecision(
            allowed=False,
            code="tool_not_in_allowed_tools",
            reason=(
                f"Tool '{tool_name}' not in agent allowed_tools "
                f"(allowed={sorted(allowed)})."
            ),
        )
    return GuardDecision(allowed=True)


def blocked_result(tool_name: str, decision: GuardDecision) -> dict[str, Any]:
    """가드 차단 시 LLM 컨텍스트에 돌려줄 *통일된* tool_result dict.

    LLM 이 이 형식을 보고 다음 턴에 OOS 응답 합성하도록 유도.
    """
    return {
        "success": False,
        "error": "tool_blocked_by_allowed_tools",
        "blocked_reason": decision.code or "unknown",
        "tool": tool_name,
        "user_message": (
            "해당 도구는 이 에이전트의 권한 범위 밖이에요. 다른 방식으로"
            " 도와드릴게요."
        ),
    }


def log_block(
    *,
    agent_context: Any,
    tool_name: str,
    decision: GuardDecision,
    source: str,
) -> None:
    """차단 로그 — 단일 event_name (메트릭 anchor).

    ``source`` : "registry" | "tool_calling_loop" | "plan_orchestrator" | "engine"
                 등 호출 경로 식별.
    """
    log.warning(
        "tool_call_blocked_by_guard",
        agent_id=str(getattr(agent_context, "agent_id", "") or ""),
        agent_name=str(getattr(agent_context, "name", "") or ""),
        is_admin=bool(getattr(agent_context, "is_admin", False)),
        tool=tool_name,
        reason_code=decision.code or "unknown",
        source=source,
    )


def visible_tools(agent_context: Any, candidate: list[str]) -> list[str]:
    """plan_orchestrator / catalog 빌더가 *노출* 할 도구 list 를 강제 가드와
    정합되게 만드는 helper.

    - ``agent_context is None`` 또는 ``allowed_tools is None`` → candidate 그대로.
    - ``allowed_tools == []`` → ``[]`` (도구 미노출).
    - else → candidate ∩ allowed_tools.
    """
    if agent_context is None:
        return list(candidate)
    allowed_raw = getattr(agent_context, "allowed_tools", None)
    if allowed_raw is None:
        return list(candidate)
    allowed = set(allowed_raw)
    if not allowed:
        return []
    return [t for t in candidate if t in allowed]
