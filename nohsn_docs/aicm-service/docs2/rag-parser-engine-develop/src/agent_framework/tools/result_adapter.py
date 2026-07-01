"""ToolResult ↔ legacy dict 호환 adapter — Phase 1.5A D73 선반영 (최소 스코프).

목적
----
기존 도구 호출 결과는 *plain dict* (success/error/confirm_id/op_type/...) 형태.
Phase 1.5A spec § 5 의 ``ToolResult`` 표준 contract (outcomes.py 의 dataclass) 도
이미 정의되어 있음. 단 두 형식 사이 *호환성 + 정합* 보장이 누락.

본 모듈은 양방향 adapter:
- ``to_tool_result(legacy_dict)`` — legacy dict → ToolResult dataclass
- ``to_legacy_dict(tool_result)`` — ToolResult → adversarial_checker / engine 호환 dict

prod 경로 *변경 없음*. import 만 가능. D74 의 _guarded_tool_call 통합 시
adapter 가 호출됨.

D68 adversarial_checker 호환성 (GPT-5 사후 권고 반영)
-----------------------------------------------------
``adversarial_checker._has_state_change_evidence`` 가 검사하는 key:
    confirm_id / evidence_id / op_type / success / rows_affected / ok / status

본 adapter 는 위 키들을 *왕복 무손실* 로 보존한다. 메커니즘:
- to_tool_result: legacy dict 의 _ADV_CHECKER_KEYS 를 meta.slots_echo 의
  특별 prefix (`_legacy:<key>`) 로 stash.
- to_legacy_dict: meta.slots_echo 에서 꺼내 *원래 key* 로 복원.

OK outcome 의 kind 매핑은 *SUCCESS* (이전 fallback=DOMAIN_EMPTY 결함 수정).

D75+ 의 본격 migration 전에 *계약 테스트* 로 동등성 보장.
"""
from __future__ import annotations

from typing import Any

from src.agent_framework.tools.outcomes import (
    OutcomeKind,
    ToolOutcome,
    ToolResult,
    ToolResultMeta,
)


# 상태 변경 op_type — adversarial_checker 와 정합 (.create/.update/.delete/.send 어간).
_STATE_CHANGE_OPS = {"create", "update", "delete", "send"}

# adversarial_checker 가 의존하는 legacy key — 왕복 무손실 보존 강제.
_ADV_CHECKER_KEYS = (
    "confirm_id",
    "evidence_id",
    "op_type",
    "rows_affected",
    "ok",
    "status",
    "tool_name",  # legacy["result"]["tool_name"] 케이스 (engine 일부 path)
)

# slots_echo 안의 stash prefix — 정상 slots 와 충돌 회피.
_LEGACY_STASH_PREFIX = "_legacy:"


def _outcome_from_legacy(legacy: dict[str, Any]) -> ToolOutcome:
    """legacy dict 의 success/error/duplicate/conflict/empty 신호 → ToolOutcome.

    매핑 우선순위:
    1. legacy["outcome"] 명시 → 그대로 enum 변환 (없으면 fallthrough)
    2. legacy["duplicate"] / legacy["merged"] → DUPLICATE
    3. legacy["conflict"] / legacy["error"] 가 conflict 시그널 → CONFLICT
    4. legacy["empty"] / total=0 → EMPTY
    5. success=False → INVALID_INPUT (validation) / EXTERNAL_API_FAIL (외부)
    6. success=True → OK
    """
    # 1
    raw_outcome = legacy.get("outcome")
    if isinstance(raw_outcome, str):
        try:
            return ToolOutcome(raw_outcome)
        except ValueError:
            pass

    # 2
    if legacy.get("duplicate") or legacy.get("merged"):
        return ToolOutcome.DUPLICATE

    # 3
    err = (legacy.get("error") or "").lower()
    if legacy.get("conflict") or "conflict" in err or "duplicate" in err:
        return ToolOutcome.CONFLICT

    # 4
    if legacy.get("empty") is True:
        return ToolOutcome.EMPTY
    total = legacy.get("total")
    if isinstance(total, int) and total == 0 and legacy.get("success") is True:
        return ToolOutcome.EMPTY

    # 5
    if legacy.get("success") is False:
        if "permission" in err or "denied" in err or "forbidden" in err:
            return ToolOutcome.PERMISSION_DENIED
        if "timeout" in err:
            return ToolOutcome.TIMEOUT
        if "rate" in err and "limit" in err:
            return ToolOutcome.RATE_LIMITED
        return ToolOutcome.EXTERNAL_API_FAIL

    # 6
    return ToolOutcome.OK


def _kind_for_outcome(outcome: ToolOutcome) -> str:
    """ToolOutcome → kind string (spec § 5.1).

    GPT-5 사후 권고: OK 의 fallback 이 DOMAIN_EMPTY 였음 → 부정확. "success" 로
    분리 (OutcomeKind enum 은 spec 의 5 카테고리 — 본 helper 만 string 으로 표현).
    """
    if outcome == ToolOutcome.OK:
        return "success"
    if outcome in {ToolOutcome.EMPTY, ToolOutcome.NOT_FOUND, ToolOutcome.SATURATED}:
        return OutcomeKind.DOMAIN_EMPTY.value
    if outcome in {ToolOutcome.CONFLICT, ToolOutcome.DUPLICATE, ToolOutcome.AMBIGUOUS_TARGET}:
        return OutcomeKind.DOMAIN_CONFLICT.value
    if outcome in {
        ToolOutcome.PERMISSION_DENIED,
        ToolOutcome.AUTH_REQUIRED,
        ToolOutcome.NOT_OWNER,
        ToolOutcome.POLICY_BLOCKED,
        ToolOutcome.UNSAFE_NEEDS_CONFIRM,
    }:
        return OutcomeKind.POLICY.value
    if outcome in {
        ToolOutcome.EXTERNAL_API_FAIL,
        ToolOutcome.BACKEND_UNAVAILABLE,
        ToolOutcome.TIMEOUT,
        ToolOutcome.RATE_LIMITED,
    }:
        return OutcomeKind.EXTERNAL_DEPENDENCY.value
    if outcome in {
        ToolOutcome.INVALID_INPUT,
        ToolOutcome.MISSING_REQUIRED_SLOT,
        ToolOutcome.PAST_TIME,
        ToolOutcome.TOO_FAR_FUTURE,
    }:
        return OutcomeKind.VALIDATION.value
    # 매핑되지 않은 outcome — "other" 로 분류 (DOMAIN_EMPTY 결함 수정).
    return "other"


def to_tool_result(legacy: dict[str, Any] | None) -> ToolResult:
    """legacy tool 반환 dict → ToolResult dataclass.

    - legacy is None → success=False / outcome=EXTERNAL_API_FAIL.
    - success 키 부재 → True 추정 (대다수 read 도구가 success 생략).
    - items / summary / error / confirm_id 보존.

    legacy 가 *이미 ToolResult 호환 dict* (meta.outcome 명시) 면 그대로 매핑.
    """
    if legacy is None:
        return ToolResult(
            success=False,
            items=None,
            summary="",
            meta=ToolResultMeta(
                outcome=ToolOutcome.EXTERNAL_API_FAIL,
                reason="legacy_result_none",
                kind=OutcomeKind.EXTERNAL_DEPENDENCY.value,
                retryable=True,
            ),
            error="legacy_result_none",
        )

    success = bool(legacy.get("success", True))
    items = legacy.get("items") or legacy.get("hits") or legacy.get("results")
    summary = str(legacy.get("summary") or "")
    error = legacy.get("error")
    error_ref = legacy.get("error_ref") or legacy.get("invocation_id")

    # GPT-5 권고 — adversarial_checker 의존 key 를 stash. to_legacy_dict 에서 복원.
    stash: dict[str, Any] = {}
    for k in _ADV_CHECKER_KEYS:
        if k in legacy and legacy[k] is not None:
            stash[f"{_LEGACY_STASH_PREFIX}{k}"] = legacy[k]
    # NOTE: ok 자동 미러는 *하지 않는다* — adversarial_checker 가 result.get("ok")
    # is True 만 보고 evidence True 판단. read 도구는 ok 가 없어야 정상.
    # legacy 에 ok 가 명시된 경우만 stash (위 _ADV_CHECKER_KEYS 루프 처리).

    # meta — 이미 정의돼 있으면 우선
    meta_in = legacy.get("meta")
    if isinstance(meta_in, dict) and "outcome" in meta_in:
        try:
            outcome = ToolOutcome(meta_in["outcome"])
        except ValueError:
            outcome = _outcome_from_legacy(legacy)
        kind = meta_in.get("kind") or _kind_for_outcome(outcome)
        # 기존 slots_echo + stash 머지 (stash 우선 X — 정상 slot 덮어쓰기 회피).
        slots_echo_merged = dict(meta_in.get("slots_echo") or {})
        for sk, sv in stash.items():
            if sk not in slots_echo_merged:
                slots_echo_merged[sk] = sv
        meta = ToolResultMeta(
            outcome=outcome,
            reason=str(meta_in.get("reason") or legacy.get("reason") or ""),
            kind=str(kind),
            retryable=bool(meta_in.get("retryable", False)),
            user_action_required=bool(meta_in.get("user_action_required", False)),
            alternatives=list(meta_in.get("alternatives") or legacy.get("alternatives") or []),
            slots_echo=slots_echo_merged,
        )
    else:
        outcome = _outcome_from_legacy(legacy)
        meta = ToolResultMeta(
            outcome=outcome,
            reason=str(legacy.get("reason") or error or ""),
            kind=_kind_for_outcome(outcome),
            retryable=outcome in {
                ToolOutcome.EXTERNAL_API_FAIL,
                ToolOutcome.BACKEND_UNAVAILABLE,
                ToolOutcome.TIMEOUT,
                ToolOutcome.RATE_LIMITED,
            },
            user_action_required=outcome in {
                ToolOutcome.PERMISSION_DENIED,
                ToolOutcome.AUTH_REQUIRED,
                ToolOutcome.MISSING_REQUIRED_SLOT,
                ToolOutcome.UNSAFE_NEEDS_CONFIRM,
            },
            alternatives=list(legacy.get("alternatives") or []),
            slots_echo=stash,
        )

    return ToolResult(
        success=success,
        items=items if isinstance(items, list) else None,
        summary=summary,
        meta=meta,
        error=str(error) if error else None,
        error_ref=str(error_ref) if error_ref else None,
    )


def to_legacy_dict(result: ToolResult) -> dict[str, Any]:
    """ToolResult dataclass → adversarial_checker / engine 호환 dict.

    *반드시 보존* 해야 하는 key (D68 adversarial_checker 의존):
    - success
    - confirm_id (없으면 omit)
    - evidence_id (없으면 omit)
    - op_type (있으면)
    - rows_affected
    - status (있으면)

    추가:
    - items / summary / error / error_ref / meta (outcome / reason / kind / ...)
    """
    legacy: dict[str, Any] = {
        "success": result.success,
    }
    if result.items is not None:
        legacy["items"] = result.items
    if result.summary:
        legacy["summary"] = result.summary
    if result.error:
        legacy["error"] = result.error
    if result.error_ref:
        legacy["error_ref"] = result.error_ref

    # GPT-5 권고 — slots_echo 안 _legacy:<key> 를 *원래 key* 로 복원.
    # adversarial_checker 가 confirm_id / op_type / rows_affected / ok / status 검사.
    restored_slots: dict[str, Any] = {}
    for k, v in (result.meta.slots_echo or {}).items():
        if isinstance(k, str) and k.startswith(_LEGACY_STASH_PREFIX):
            legacy[k[len(_LEGACY_STASH_PREFIX):]] = v
        else:
            restored_slots[k] = v

    # NOTE: ok 자동 미러는 하지 않는다 (위 to_tool_result 와 동일 이유).
    # ok 가 stash 안에 있었다면 위 루프에서 이미 복원됨. 그게 source of truth.

    # meta dict (stash 제거 후 정상 slots 만)
    legacy["meta"] = {
        "outcome": result.meta.outcome.value
        if isinstance(result.meta.outcome, ToolOutcome)
        else str(result.meta.outcome),
        "reason": result.meta.reason,
        "kind": result.meta.kind,
        "retryable": result.meta.retryable,
        "user_action_required": result.meta.user_action_required,
        "alternatives": list(result.meta.alternatives),
        "slots_echo": restored_slots,
    }

    return legacy


def ensure_result_shape(legacy: dict[str, Any]) -> tuple[bool, list[str]]:
    """legacy tool 반환 dict 가 ToolResult 호환 *최소* 형태인지 검증 (테스트용).

    *fail-fast 검사용 — prod 경로 미사용*. 테스트가 이 helper 로 새 도구 합류 시
    contract 준수 여부 검사.

    Returns
    -------
    (is_valid, errors)
        is_valid=False 면 errors 에 누락 / 형식 오류 메시지.
    """
    errors: list[str] = []
    if not isinstance(legacy, dict):
        return False, ["not_a_dict"]

    if "success" not in legacy:
        errors.append("missing_success")
    elif not isinstance(legacy["success"], bool):
        errors.append("success_not_bool")

    # 상태변경 op_type 가 있으면 confirm_id 또는 evidence_id 필수 (success=True 시).
    op_type = (legacy.get("op_type") or "").lower()
    if op_type in _STATE_CHANGE_OPS and legacy.get("success") is True:
        if not (legacy.get("confirm_id") or legacy.get("evidence_id")):
            errors.append("state_change_without_evidence")

    return (not errors), errors


__all__ = [
    "to_tool_result",
    "to_legacy_dict",
    "ensure_result_shape",
]
