"""ExecutionPolicyGuard (델타 #5) — tool_loop 앞단 게이트.

결정 종류:
- run       : 그냥 실행
- interrupt : pending_confirm 레코드 작성, engine 은 turn yield + resume 대기
- dry_run   : 외부 API 미호출, 모의 응답
- deny      : 정책 위반 (한도/시간대/cooldown)
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from datetime import datetime, timezone


@dataclass
class GuardDecision:
    action: str
    invocation_id: str | None = None
    resume_token: str | None = None
    reason: str | None = None
    dry_run_stub_response: dict | None = None


class ExecutionPolicyGuard:
    def __init__(self, inv_store):
        self.store = inv_store

    async def gate(
        self, *, skill: dict, policy: dict | None, context: dict,
        tool_name: str, input_args: dict,
    ) -> GuardDecision:
        policy = policy or {}
        side_level = skill.get("side_effect_level", "read_only")
        consequential = bool(skill.get("consequential", side_level != "read_only"))

        # 1) dry_run wins
        if policy.get("dry_run_only"):
            return GuardDecision(action="dry_run",
                                 dry_run_stub_response={"dry_run": True,
                                                        "would_call": tool_name,
                                                        "with": input_args})

        # 2) daily limit
        max_per_day = policy.get("max_runs_per_day")
        if max_per_day is not None:
            used = await self.store.get_usage_today(context["skill_id"])
            if used >= max_per_day:
                return GuardDecision(action="deny",
                                     reason=f"daily limit reached ({used}/{max_per_day})")

        # 3) cooldown
        cooldown = policy.get("cooldown_seconds")
        if cooldown:
            h = _hash_args(input_args)
            last = await self.store.get_last_invocation(context["skill_id"], h)
            if last:
                elapsed = (datetime.now(timezone.utc) - last["executed_at"]).total_seconds()
                if elapsed < cooldown:
                    return GuardDecision(
                        action="deny",
                        reason=f"cooldown {cooldown}s, elapsed {elapsed:.0f}s")

        # 4) read_only + no confirm flag → run
        if side_level == "read_only" and not policy.get("confirm_before_run"):
            return GuardDecision(action="run")

        # 5) consequential or confirm_before_run → interrupt
        if consequential or policy.get("confirm_before_run"):
            inv_id, token = await self.store.insert_pending(
                tenant_id=context["tenant_id"],
                session_id=context.get("session_id"),
                turn_id=context.get("turn_id"),
                skill_id=context["skill_id"],
                cc_pair_id=context.get("cc_pair_id"),
                tool_name=tool_name,
                input_args=input_args,
            )
            return GuardDecision(action="interrupt", invocation_id=inv_id, resume_token=token)

        return GuardDecision(action="run")


def _hash_args(args: dict) -> str:
    s = json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode()).hexdigest()[:16]
