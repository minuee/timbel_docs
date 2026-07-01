"""Engine ↔ ExecutionPolicyGuard 통합 helper (델타 #5).

engine.turn() tool_loop 에서 tool 호출 직전에 apply_guard() 호출하면
ExecutionPolicyGuard.gate() 결과에 따라 4분기로 라우팅된다:

- run       : tool_callable 실행 → executed outcome
- dry_run   : guard 가 만든 stub_response 반환 (tool 미실행)
- interrupt : invocation_id + resume_token 만 반환 (tool 미실행).
              엔진은 SSE `tool.confirm` 이벤트 발사 후 turn 종료.
              다음 turn 에서 별도 resume 흐름으로 재개.
- deny      : reason 반환 (tool 미실행).

엔진 본체에 침투하지 않도록 helper 만으로 분기 책임을 모두 흡수한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class GuardOutcome:
    """apply_guard() 결과 — engine 측 분기에 필요한 최소 메타."""

    kind: str  # "executed" | "dry_run" | "interrupt" | "denied"
    output: dict | None = None
    invocation_id: str | None = None
    resume_token: str | None = None
    reason: str | None = None
    duration_ms: int = 0


async def apply_guard(
    *,
    guard,
    skill: dict,
    policy: dict | None,
    context: dict,
    tool_name: str,
    input_args: dict,
    tool_callable,
    inv_store=None,
) -> GuardOutcome:
    """Guard.gate() → 분기 → outcome 반환.

    Parameters
    ----------
    guard : ExecutionPolicyGuard 인스턴스 (gate(...) async).
    skill : {"side_effect_level": ..., "consequential": ...}
    policy : execution_policy dict 또는 None.
    context : {tenant_id, skill_id, session_id?, turn_id?, cc_pair_id?}
    tool_name : 호출 대상 tool 이름 (감사 로그/pending row 용).
    input_args : tool 인자 dict.
    tool_callable : `await tool_callable(**input_args)` 또는 `await tool_callable(input_args)`
                    형태로 호출 가능한 async callable. dict 가 아닌 경우 단일 인자로 전달.
    inv_store : 옵션 — run 경로에서 succeeded 기록을 위한 ToolInvocationStore.
                None 이면 감사 기록 생략 (테스트/legacy 환경).

    Returns
    -------
    GuardOutcome — kind 에 따라 추가 필드 채워짐.
    """
    decision = await guard.gate(
        skill=skill,
        policy=policy,
        context=context,
        tool_name=tool_name,
        input_args=input_args,
    )

    if decision.action == "dry_run":
        return GuardOutcome(kind="dry_run", output=decision.dry_run_stub_response)

    if decision.action == "deny":
        return GuardOutcome(kind="denied", reason=decision.reason)

    if decision.action == "interrupt":
        return GuardOutcome(
            kind="interrupt",
            invocation_id=decision.invocation_id,
            resume_token=decision.resume_token,
        )

    # action == "run"
    started = time.monotonic()
    try:
        if isinstance(input_args, dict):
            output = await tool_callable(**input_args)
        else:
            output = await tool_callable(input_args)
        duration_ms = int((time.monotonic() - started) * 1000)
        normalized = output if isinstance(output, dict) else {"value": output}
        if inv_store is not None:
            # 성공 감사 기록 — pending 진입 안 한 read_only run 도 추적용으로 남길 수 있게.
            try:
                inv_id, _ = await inv_store.insert_pending(
                    tenant_id=context["tenant_id"],
                    session_id=context.get("session_id"),
                    turn_id=context.get("turn_id"),
                    skill_id=context["skill_id"],
                    cc_pair_id=context.get("cc_pair_id"),
                    tool_name=tool_name,
                    input_args=input_args,
                )
                await inv_store.confirm_result(
                    inv_id,
                    status="succeeded",
                    output=normalized,
                    duration_ms=duration_ms,
                )
            except Exception:
                # 감사 기록 실패는 실행 자체를 실패시키지 않는다.
                pass
        return GuardOutcome(
            kind="executed", output=normalized, duration_ms=duration_ms
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        return GuardOutcome(
            kind="executed",
            output={"error": str(e)},
            duration_ms=duration_ms,
        )
