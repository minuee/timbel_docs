from unittest.mock import AsyncMock
import asyncio
import pytest
from src.agent_framework.runtime.execution_policy_guard import (
    ExecutionPolicyGuard, GuardDecision,
)


def _inv_stub():
    rec = {"status": None, "resume_token": None, "confirmed": None}
    class Store:
        async def insert_pending(self, *, tenant_id, session_id, turn_id, skill_id,
                                  cc_pair_id, tool_name, input_args):
            rec["status"] = "pending_confirm"
            rec["resume_token"] = "token-123"
            return "inv_1", "token-123"
        async def confirm_result(self, invocation_id, *, status, output=None, error=None, duration_ms=0):
            rec["status"] = status
        async def get_usage_today(self, skill_id): return 0
        async def get_last_invocation(self, skill_id, input_hash): return None
    return Store(), rec


def test_read_only_passes_through():
    guard = ExecutionPolicyGuard(inv_store=_inv_stub()[0])
    dec = asyncio.run(guard.gate(
        skill={"side_effect_level": "read_only", "consequential": False},
        policy={"confirm_before_run": False},
        context={"tenant_id":"t1","session_id":"s1","turn_id":"tn1","skill_id":"sk1"},
        tool_name="x", input_args={"a":1},
    ))
    assert dec.action == "run"


def test_consequential_triggers_interrupt():
    store, rec = _inv_stub()
    guard = ExecutionPolicyGuard(inv_store=store)
    dec = asyncio.run(guard.gate(
        skill={"side_effect_level": "write_external", "consequential": True},
        policy={"confirm_before_run": True},
        context={"tenant_id":"t1","session_id":"s1","turn_id":"tn1","skill_id":"sk1"},
        tool_name="x", input_args={"a":1},
    ))
    assert dec.action == "interrupt"
    assert dec.invocation_id == "inv_1"
    assert dec.resume_token == "token-123"
    assert rec["status"] == "pending_confirm"


def test_dry_run_skips_external():
    guard = ExecutionPolicyGuard(inv_store=_inv_stub()[0])
    dec = asyncio.run(guard.gate(
        skill={"side_effect_level": "write_external", "consequential": False},
        policy={"dry_run_only": True, "confirm_before_run": False},
        context={"tenant_id":"t1","session_id":"s1","turn_id":"tn1","skill_id":"sk1"},
        tool_name="x", input_args={"a":1},
    ))
    assert dec.action == "dry_run"


def test_daily_limit_denies():
    class LimitStore:
        async def insert_pending(self, **k): return "i","t"
        async def confirm_result(self, *a, **k): pass
        async def get_usage_today(self, skill_id): return 100
        async def get_last_invocation(self, *a, **k): return None
    guard = ExecutionPolicyGuard(inv_store=LimitStore())
    dec = asyncio.run(guard.gate(
        skill={"side_effect_level": "write_external", "consequential": False},
        policy={"max_runs_per_day": 10, "confirm_before_run": False},
        context={"tenant_id":"t1","session_id":"s1","turn_id":"tn1","skill_id":"sk1"},
        tool_name="x", input_args={"a":1},
    ))
    assert dec.action == "deny"
    assert "limit" in dec.reason.lower()
