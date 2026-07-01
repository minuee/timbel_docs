"""Option beta Stage 7 — PLAN_PARALLEL_STEPS feature flag tests.

Coverage:
1. _all_independent helper — pure unit tests.
2. flag off: serial loop path (no asyncio.gather).
3. flag on + independent steps: asyncio.gather fires, wall-time compressed.
4. flag on + dependent steps (${step_*} marker): serial fallback.
5. reasoning step breaks batch boundary.
6. SSE plan_step yield order preserved (original step number) even when
   gather completes in reverse order.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal PlanStep stub — avoids importing the real plan_orchestrator which
# may pull in heavy dependencies unavailable in the test environment.
# ---------------------------------------------------------------------------

@dataclass
class _PlanStep:
    step: int
    kind: str
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# _all_independent — unit tests
# ---------------------------------------------------------------------------

class TestAllIndependent:
    def _step(self, tool: str, args: dict | None = None) -> _PlanStep:
        return _PlanStep(step=1, kind="tool", raw={"tool": tool, "args": args or {}})

    def test_empty_batch_is_independent(self):
        from src.agent_framework.runtime.engine import _all_independent
        assert _all_independent([]) is True

    def test_single_step_no_marker_is_independent(self):
        from src.agent_framework.runtime.engine import _all_independent
        s = self._step("kms_rag.search", {"query": "보험 약관"})
        assert _all_independent([s]) is True

    def test_step_ref_marker_detected(self):
        from src.agent_framework.runtime.engine import _all_independent
        s1 = self._step("kms_rag.search", {"query": "보험"})
        s2 = self._step("llm.summarize", {"text": "${step_1_result}"})
        assert _all_independent([s1, s2]) is False

    def test_prev_marker_detected(self):
        from src.agent_framework.runtime.engine import _all_independent
        s1 = self._step("web.search", {"query": "뉴스"})
        s2 = self._step("llm.format", {"content": "{prev_result}"})
        assert _all_independent([s1, s2]) is False

    def test_two_independent_tools_pass(self):
        from src.agent_framework.runtime.engine import _all_independent
        s1 = self._step("kms_rag.search", {"query": "보험"})
        s2 = self._step("web.search", {"query": "오늘 날씨"})
        assert _all_independent([s1, s2]) is True

    def test_none_args_treated_as_empty(self):
        from src.agent_framework.runtime.engine import _all_independent
        s = _PlanStep(step=1, kind="tool", raw={"tool": "reminder.list"})
        assert _all_independent([s]) is True

    def test_nested_marker_in_value(self):
        from src.agent_framework.runtime.engine import _all_independent
        s1 = self._step("tool_a", {"query": "ok"})
        s2 = self._step("tool_b", {"nested": {"key": "${step_1_result}"}})
        assert _all_independent([s1, s2]) is False


# ---------------------------------------------------------------------------
# Engine parallel execution tests — mock the plan executor section directly.
# We test _all_independent + flag behaviour via integration with a minimal
# mock AgentEngine that exercises the batch logic path.
# ---------------------------------------------------------------------------

def _make_mock_tools(call_side_effect=None, call_return_value=None):
    """Return a mock tools registry."""
    tools = MagicMock()
    if call_side_effect:
        tools.call = AsyncMock(side_effect=call_side_effect)
    else:
        tools.call = AsyncMock(return_value=call_return_value or {"success": True, "summary": "ok"})
    return tools


def _make_session(tenant_id: str = "test-tenant") -> MagicMock:
    sess = MagicMock()
    sess.tenant_id = tenant_id
    return sess


def _make_plan(*steps: tuple[str, str, dict]) -> list[_PlanStep]:
    """steps: (kind, tool_name_or_expr, args_dict)."""
    plan = []
    for i, (kind, name, args) in enumerate(steps, start=1):
        if kind == "tool":
            raw = {"step": i, "kind": "tool", "tool": name, "args": args}
        else:
            raw = {"step": i, "kind": kind, "expr": name, "args": args}
        plan.append(_PlanStep(step=i, kind=kind, raw=raw))
    return plan


# ---------------------------------------------------------------------------
# Helper: run the parallel-plan branch in isolation without a full engine.
# We extract the logic by calling _all_independent + asyncio.gather directly,
# mirroring what engine.py does, so tests are stable against engine internals.
# ---------------------------------------------------------------------------

async def _simulate_parallel_executor(
    plan: list[_PlanStep],
    tools_call,
    enrich_fn,
    *,
    parallel: bool,
) -> list[dict]:
    """Simulate the plan executor and return emitted plan_step events."""
    from src.agent_framework.runtime.engine import _all_independent

    events: list[dict] = []
    tool_results: list[dict] = []

    if not parallel:
        for s in plan:
            if not s.kind:
                continue
            if s.kind == "tool":
                tn = str(s.raw.get("tool") or "").strip()
                if not tn:
                    continue
                targs = enrich_fn(s.raw.get("args") or {})
                try:
                    tout = await tools_call(tn, targs)
                except Exception as e:
                    tout = {"success": False, "error": str(e)}
                events.append({"event": "plan_step", "step": s.step, "tool": tn, "parallel": False})
                tool_results.append({"tool": tn, "args": targs, "result": tout})
            elif s.kind == "reasoning":
                events.append({"event": "plan_step", "step": s.step, "kind": "reasoning"})
    else:
        plan_valid = [s for s in plan if s.kind]
        pi = 0
        while pi < len(plan_valid):
            ps = plan_valid[pi]
            if ps.kind != "tool":
                if ps.kind == "reasoning":
                    events.append({"event": "plan_step", "step": ps.step, "kind": "reasoning"})
                pi += 1
                continue
            batch_end = pi
            while batch_end < len(plan_valid) and plan_valid[batch_end].kind == "tool":
                batch_end += 1
            batch = plan_valid[pi:batch_end]
            if len(batch) >= 2 and _all_independent(batch):
                batch_tn = [str(s.raw.get("tool") or "").strip() for s in batch]
                batch_targs = [enrich_fn(s.raw.get("args") or {}) for s in batch]

                async def _safe(tn: str, ta: dict) -> dict:
                    try:
                        return await tools_call(tn, ta)
                    except Exception as e:
                        return {"success": False, "error": str(e)}

                outs = await asyncio.gather(*[_safe(batch_tn[i], batch_targs[i]) for i in range(len(batch))])
                for bi, bs in enumerate(batch):
                    events.append({
                        "event": "plan_step",
                        "step": bs.step,
                        "tool": batch_tn[bi],
                        "parallel": True,
                    })
                    tool_results.append({"tool": batch_tn[bi], "args": batch_targs[bi], "result": outs[bi]})
            else:
                for bs in batch:
                    tn = str(bs.raw.get("tool") or "").strip()
                    if not tn:
                        continue
                    ta = enrich_fn(bs.raw.get("args") or {})
                    try:
                        tout = await tools_call(tn, ta)
                    except Exception as e:
                        tout = {"success": False, "error": str(e)}
                    events.append({"event": "plan_step", "step": bs.step, "tool": tn, "parallel": False})
                    tool_results.append({"tool": tn, "args": ta, "result": tout})
            pi = batch_end

    return events


@pytest.mark.asyncio
async def test_flag_off_serial(monkeypatch):
    """flag off: serial loop, asyncio.gather never called."""
    monkeypatch.delenv("FEATURE_PLAN_PARALLEL_STEPS", raising=False)

    call_order: list[str] = []

    async def fake_call(tn: str, args: dict):
        call_order.append(tn)
        return {"success": True, "summary": tn}

    plan = _make_plan(
        ("tool", "kms_rag.search", {"query": "보험"}),
        ("tool", "web.search", {"query": "날씨"}),
    )

    events = await _simulate_parallel_executor(plan, fake_call, lambda a: a, parallel=False)

    assert len(events) == 2
    assert call_order == ["kms_rag.search", "web.search"], "flag off must be strictly serial"
    for ev in events:
        assert ev.get("parallel") is False


@pytest.mark.asyncio
async def test_flag_on_independent_steps_parallel(monkeypatch):
    """flag on + independent steps: asyncio.gather compresses wall-time."""
    monkeypatch.setenv("FEATURE_PLAN_PARALLEL_STEPS", "true")

    DELAY = 0.08  # 80 ms per call

    async def slow_call(tn: str, args: dict):
        await asyncio.sleep(DELAY)
        return {"success": True, "summary": tn}

    plan = _make_plan(
        ("tool", "kms_rag.search", {"query": "보험"}),
        ("tool", "web.search", {"query": "날씨"}),
    )

    t0 = time.monotonic()
    events = await _simulate_parallel_executor(plan, slow_call, lambda a: a, parallel=True)
    elapsed = time.monotonic() - t0

    assert len(events) == 2
    # parallel: should finish in ~1x delay, not 2x
    assert elapsed < DELAY * 1.8, f"parallel took {elapsed:.3f}s, expected < {DELAY * 1.8:.3f}s"
    # all events flagged as parallel
    assert all(ev.get("parallel") is True for ev in events)


@pytest.mark.asyncio
async def test_flag_on_dependent_steps_serial(monkeypatch):
    """flag on + ${step_1_result} marker: serial fallback."""
    monkeypatch.setenv("FEATURE_PLAN_PARALLEL_STEPS", "true")

    call_order: list[str] = []

    async def fake_call(tn: str, args: dict):
        call_order.append(tn)
        return {"success": True, "summary": tn}

    plan = _make_plan(
        ("tool", "kms_rag.search", {"query": "보험"}),
        ("tool", "llm.summarize", {"text": "${step_1_result}"}),
    )

    events = await _simulate_parallel_executor(plan, fake_call, lambda a: a, parallel=True)

    assert len(events) == 2
    # dependent: must remain serial (parallel=False)
    assert all(ev.get("parallel") is False for ev in events), (
        "dependent steps must not be gathered in parallel"
    )
    assert call_order == ["kms_rag.search", "llm.summarize"], "call order must be preserved"


@pytest.mark.asyncio
async def test_flag_on_reasoning_breaks_batch(monkeypatch):
    """reasoning step is a batch boundary — two parallel batches separated by reasoning."""
    monkeypatch.setenv("FEATURE_PLAN_PARALLEL_STEPS", "true")

    DELAY = 0.06  # 60 ms

    batch_starts: list[float] = []

    async def slow_call(tn: str, args: dict):
        batch_starts.append(time.monotonic())
        await asyncio.sleep(DELAY)
        return {"success": True, "summary": tn}

    # plan: tool / tool / reasoning / tool / tool
    plan = _make_plan(
        ("tool", "kms_rag.search", {"query": "보험"}),
        ("tool", "web.search", {"query": "날씨"}),
        ("reasoning", "결과를 종합하라", {}),
        ("tool", "reminder.list", {}),
        ("tool", "schedule.list", {}),
    )

    t0 = time.monotonic()
    events = await _simulate_parallel_executor(plan, slow_call, lambda a: a, parallel=True)
    total = time.monotonic() - t0

    step_kinds = [(ev["step"], ev.get("kind", "tool")) for ev in events]
    tool_events = [ev for ev in events if ev.get("kind") != "reasoning"]
    reasoning_events = [ev for ev in events if ev.get("kind") == "reasoning"]

    assert len(reasoning_events) == 1, "reasoning step must be emitted once"
    # reasoning step must appear in the middle (step 3)
    assert reasoning_events[0]["step"] == 3

    # 2 parallel batches x ~60ms each + reasoning overhead ~ 120ms, not 4x60ms=240ms
    # Allow generous margin for CI variability
    assert total < DELAY * 3.5, f"batched parallel should be faster: {total:.3f}s"

    # first two steps parallel, last two steps parallel
    first_batch = [ev for ev in tool_events if ev["step"] in (1, 2)]
    second_batch = [ev for ev in tool_events if ev["step"] in (4, 5)]
    assert all(ev.get("parallel") is True for ev in first_batch)
    assert all(ev.get("parallel") is True for ev in second_batch)


@pytest.mark.asyncio
async def test_yield_order_preserved(monkeypatch):
    """Even when step 2 finishes before step 1, SSE events are yielded in step order."""
    monkeypatch.setenv("FEATURE_PLAN_PARALLEL_STEPS", "true")

    async def delayed_call(tn: str, args: dict):
        # step 1 (kms_rag.search) takes 120ms, step 2 (web.search) takes 20ms
        # => step 2 finishes first
        delay = 0.12 if tn == "kms_rag.search" else 0.02
        await asyncio.sleep(delay)
        return {"success": True, "summary": tn, "tool_name": tn}

    plan = _make_plan(
        ("tool", "kms_rag.search", {"query": "보험"}),
        ("tool", "web.search", {"query": "날씨"}),
    )

    events = await _simulate_parallel_executor(plan, delayed_call, lambda a: a, parallel=True)

    assert len(events) == 2
    # yield order must be step 1 then step 2 regardless of completion order
    assert events[0]["step"] == 1, f"first event should be step 1, got {events[0]['step']}"
    assert events[1]["step"] == 2, f"second event should be step 2, got {events[1]['step']}"
    assert events[0]["tool"] == "kms_rag.search"
    assert events[1]["tool"] == "web.search"


@pytest.mark.asyncio
async def test_single_tool_step_not_gathered(monkeypatch):
    """A batch of 1 tool step is never sent to asyncio.gather (no overhead)."""
    monkeypatch.setenv("FEATURE_PLAN_PARALLEL_STEPS", "true")

    call_order: list[str] = []

    async def fake_call(tn: str, args: dict):
        call_order.append(tn)
        return {"success": True}

    plan = _make_plan(
        ("tool", "kms_rag.search", {"query": "보험"}),
    )

    events = await _simulate_parallel_executor(plan, fake_call, lambda a: a, parallel=True)

    assert len(events) == 1
    assert call_order == ["kms_rag.search"]
    # single-step batch falls into serial fallback
    assert events[0].get("parallel") is False
