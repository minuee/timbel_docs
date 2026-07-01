"""tool_guard_hook 분기 검증 (델타 #5).

ExecutionPolicyGuard.gate() 결과별로 apply_guard() 가
- run       → tool 실행 + executed outcome
- dry_run   → tool 미실행 + stub 반환
- interrupt → tool 미실행 + invocation_id/resume_token 전달
- deny      → tool 미실행 + reason 전달
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.agent_framework.runtime.tool_guard_hook import GuardOutcome, apply_guard


def test_run_action_executes_tool():
    guard = MagicMock()
    guard.gate = AsyncMock(return_value=MagicMock(action="run"))
    tool = AsyncMock(return_value={"result": "ok"})
    outcome = asyncio.run(
        apply_guard(
            guard=guard,
            skill={"side_effect_level": "read_only", "consequential": False},
            policy={},
            context={"tenant_id": "t", "skill_id": "s", "turn_id": "tn"},
            tool_name="x",
            input_args={},
            tool_callable=tool,
        )
    )
    assert outcome.kind == "executed"
    assert outcome.output == {"result": "ok"}
    tool.assert_awaited_once()


def test_dry_run_returns_stub():
    guard = MagicMock()
    guard.gate = AsyncMock(
        return_value=MagicMock(
            action="dry_run",
            dry_run_stub_response={"dry_run": True, "would_call": "x", "with": {}},
        )
    )
    tool = AsyncMock()
    outcome = asyncio.run(
        apply_guard(
            guard=guard,
            skill={"side_effect_level": "write_external", "consequential": True},
            policy={"dry_run_only": True},
            context={"tenant_id": "t", "skill_id": "s", "turn_id": "tn"},
            tool_name="x",
            input_args={},
            tool_callable=tool,
        )
    )
    assert outcome.kind == "dry_run"
    assert outcome.output == {"dry_run": True, "would_call": "x", "with": {}}
    tool.assert_not_awaited()


def test_interrupt_yields_pending():
    guard = MagicMock()
    guard.gate = AsyncMock(
        return_value=MagicMock(
            action="interrupt", invocation_id="inv1", resume_token="tok"
        )
    )
    tool = AsyncMock()
    outcome = asyncio.run(
        apply_guard(
            guard=guard,
            skill={"side_effect_level": "write_external", "consequential": True},
            policy={"confirm_before_run": True},
            context={"tenant_id": "t", "skill_id": "s", "turn_id": "tn"},
            tool_name="x",
            input_args={},
            tool_callable=tool,
        )
    )
    assert outcome.kind == "interrupt"
    assert outcome.invocation_id == "inv1"
    assert outcome.resume_token == "tok"
    tool.assert_not_awaited()


def test_deny_returns_reason():
    guard = MagicMock()
    guard.gate = AsyncMock(return_value=MagicMock(action="deny", reason="quota"))
    tool = AsyncMock()
    outcome = asyncio.run(
        apply_guard(
            guard=guard,
            skill={"side_effect_level": "read_only", "consequential": False},
            policy={"max_runs_per_day": 10},
            context={"tenant_id": "t", "skill_id": "s", "turn_id": "tn"},
            tool_name="x",
            input_args={},
            tool_callable=tool,
        )
    )
    assert outcome.kind == "denied"
    assert outcome.reason == "quota"
    tool.assert_not_awaited()
