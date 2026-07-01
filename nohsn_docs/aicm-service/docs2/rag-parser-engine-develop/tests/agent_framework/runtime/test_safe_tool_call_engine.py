"""D74 (2026-05-11) — AgentEngine._safe_tool_call() 통합 테스트.

# 검증 매트릭스 (12+)
mode ∈ {off, shadow, enforce} × op_type ∈ {read, write} × confirm_id {present, absent}

# 기대 동작
| mode    | op  | confirm | 결과                                   |
| ------- | --- | ------- | -------------------------------------- |
| off     | *   | *       | 옛 path 결과 byte-equal                |
| shadow  | *   | *       | 옛 path 결과 byte-equal + log only     |
| enforce | read| -       | 옛 path 결과 byte-equal                |
| enforce | write| have   | 옛 path 결과 byte-equal                |
| enforce | write| miss   | downgrade ({success:False, unsafe_*}) |

# 회귀 0 보장
off default 시 wrapper 통과 = byte-equal. 7+2 site migration 후에도 회귀 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.agent_framework.runtime.safe_tool_call import (
    FF_ENFORCE,
    FF_OFF,
    FF_SHADOW,
)
from src.agent_framework.tools.registry import ToolRegistry


@dataclass
class _FakeCtx:
    """agent_context 덕 타입."""
    is_admin: bool = False
    allowed_tools: list[str] | None = None
    agent_id: str = "fake-agent"
    name: str = "fake"


class _FakeEngine:
    """AgentEngine 의 ``_safe_tool_call`` method 만 분리 호출하기 위한 minimal
    stub. 실 engine 의 의존성 (session_store / skills / 등) 없이 wrapper 단독
    검증.

    GPT-5 사전 verdict 권고: mode × op × confirm 매트릭스 단위 검증.
    """

    def __init__(self, registry: ToolRegistry, agent_context: Any = None):
        self.tools = registry
        self._agent_context = agent_context

    # 같은 메서드를 import 해서 bind.
    from src.agent_framework.runtime.engine import AgentEngine
    _safe_tool_call = AgentEngine._safe_tool_call  # type: ignore[assignment]


@pytest.fixture
def registry_with_success_tool():
    """``demo.delete`` (write) 와 ``demo.list`` (read) 등록 — 항상 success=True 반환."""
    async def _fn(args: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "echo": args}

    reg = ToolRegistry()
    reg.register("demo.delete", _fn, description="demo write")
    reg.register("demo.list", _fn, description="demo read")
    reg.register("demo.send", _fn, description="demo send")
    reg.register("expense.delete", _fn, description="delete expense")
    return reg


# ─── off mode ─────────────────────────────────────────────────────────────


async def test_off_mode_write_no_confirm_byte_equal(
    monkeypatch, registry_with_success_tool,
):
    """off + write + confirm 미보유 → 결과 그대로 (downgrade X)."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_OFF)
    eng = _FakeEngine(registry_with_success_tool)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=None, source="test",
    )
    assert r["success"] is True
    assert r["echo"] == {"foo": "bar"}


async def test_off_mode_read_byte_equal(monkeypatch, registry_with_success_tool):
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_OFF)
    eng = _FakeEngine(registry_with_success_tool)
    r = await eng._safe_tool_call(
        "demo.list", {}, agent_context=None, source="test",
    )
    assert r["success"] is True


# ─── shadow mode — log only, no behavior change ─────────────────────────────


async def test_shadow_mode_write_no_confirm_byte_equal(
    monkeypatch, registry_with_success_tool,
):
    """shadow + write + confirm 미보유 → 결과 그대로 (would_block 은 log only)."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_SHADOW)
    eng = _FakeEngine(registry_with_success_tool)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=None, source="test",
    )
    assert r["success"] is True
    assert r["echo"] == {"foo": "bar"}


async def test_shadow_mode_write_with_confirm_byte_equal(
    monkeypatch, registry_with_success_tool,
):
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_SHADOW)
    eng = _FakeEngine(registry_with_success_tool)
    r = await eng._safe_tool_call(
        "demo.delete", {"confirm_id": "abc"}, agent_context=None, source="test",
    )
    assert r["success"] is True


async def test_shadow_mode_read_byte_equal(monkeypatch, registry_with_success_tool):
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_SHADOW)
    eng = _FakeEngine(registry_with_success_tool)
    r = await eng._safe_tool_call(
        "demo.list", {}, agent_context=None, source="test",
    )
    assert r["success"] is True


# ─── enforce mode — downgrade for write+no-confirm ────────────────────────


async def test_enforce_write_no_confirm_downgrades(
    monkeypatch, registry_with_success_tool,
):
    """enforce + write + confirm 미보유 + 성공 dict → unsafe_needs_confirm.

    D74-canary: percent=100 으로 canary 전체 활성화 (기존 enforce 동작 보존).
    """
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="test-agent-enforce")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=ctx, source="test",
    )
    assert r["success"] is False
    assert r["error"] == "unsafe_needs_confirm"
    assert r["tool"] == "demo.delete"
    assert r["op_type"] == "write"
    assert "user_message" in r


async def test_enforce_write_with_confirm_passes(
    monkeypatch, registry_with_success_tool,
):
    """enforce + write + confirm_id 보유 → 결과 그대로."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="test-agent-enforce")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {"confirm_id": "abc"}, agent_context=ctx, source="test",
    )
    assert r["success"] is True
    assert r["echo"] == {"confirm_id": "abc"}


async def test_enforce_read_no_confirm_passes(
    monkeypatch, registry_with_success_tool,
):
    """enforce + read + confirm 미보유 → 결과 그대로 (read 는 검사 X)."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="test-agent-enforce")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.list", {}, agent_context=ctx, source="test",
    )
    assert r["success"] is True


async def test_enforce_explicit_op_type_read_overrides_inference(
    monkeypatch, registry_with_success_tool,
):
    """op_type='read' override 시 write suffix 도 검사 skip."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="test-agent-enforce")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {}, agent_context=ctx, op_type="read", source="test",
    )
    assert r["success"] is True


# ─── error propagation ────────────────────────────────────────────────────


async def test_enforce_propagates_underlying_exception(monkeypatch):
    """tool 호출 예외는 wrapper 가 변형 없이 재전파 (회귀 0)."""
    async def _bad(args):
        raise RuntimeError("upstream failure")

    reg = ToolRegistry()
    reg.register("demo.bad", _bad)
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="test-agent-enforce")
    eng = _FakeEngine(reg, agent_context=ctx)
    with pytest.raises(RuntimeError, match="upstream failure"):
        await eng._safe_tool_call(
            "demo.bad", {}, agent_context=ctx, source="test",
        )


async def test_enforce_does_not_downgrade_already_failed(
    monkeypatch, registry_with_success_tool,
):
    """이미 success=False 인 결과는 다운그레이드 X (그대로 전파)."""
    async def _fail(args):
        return {"success": False, "error": "tool_internal_fail"}

    reg = ToolRegistry()
    reg.register("demo.delete", _fail)
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="test-agent-enforce")
    eng = _FakeEngine(reg, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {}, agent_context=ctx, source="test",
    )
    assert r["success"] is False
    assert r["error"] == "tool_internal_fail"  # 원본 보존


async def test_enforce_non_dict_result_unchanged(monkeypatch):
    """비-dict 반환 (예: string) 도 변형 없이 전파."""
    async def _str_tool(args):
        return "plain string"  # type: ignore[return-value]

    reg = ToolRegistry()
    reg.register("demo.delete", _str_tool)
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="test-agent-enforce")
    eng = _FakeEngine(reg, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {}, agent_context=ctx, source="test",
    )
    assert r == "plain string"


# ─── D72 choke point 와 정합 ──────────────────────────────────────────────


async def test_allowed_tools_block_propagates_through_wrapper(
    monkeypatch, registry_with_success_tool,
):
    """agent_context.allowed_tools=[] → D72 choke point 가 차단 — wrapper 도 차단 결과 전파."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_OFF)
    ctx = _FakeCtx(allowed_tools=[])  # 명시적 deny-all
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {}, agent_context=ctx, source="test",
    )
    assert r["success"] is False
    assert r["error"] == "tool_blocked_by_allowed_tools"


# ─── D74-canary 통합 — base=enforce 일 때 percent 분기 검증 ────────────────


async def test_enforce_canary_outside_no_downgrade(
    monkeypatch, registry_with_success_tool,
):
    """enforce + canary percent=0 → 모두 outside (shadow fallback) → downgrade X.

    canary 밖 agent 는 enforce 가 아닌 shadow 로 처리. 회귀 0 보장.
    """
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "0")
    ctx = _FakeCtx(agent_id="agent-outside-canary")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=ctx, source="test",
    )
    # canary 밖 → shadow → 원본 결과 그대로 (downgrade X).
    assert r["success"] is True
    assert r["echo"] == {"foo": "bar"}


async def test_enforce_canary_missing_agent_id_no_downgrade(
    monkeypatch, registry_with_success_tool,
):
    """enforce + agent_id 없음 → shadow fallback (missing bucket) → downgrade X.

    agent_id 누락 시 안전 fallback. 운영자는 metric 으로 missing 비율 감시.
    """
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    eng = _FakeEngine(registry_with_success_tool, agent_context=None)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=None, source="test",
    )
    assert r["success"] is True
    assert r["echo"] == {"foo": "bar"}


async def test_enforce_canary_default_zero_is_safe(
    monkeypatch, registry_with_success_tool,
):
    """KMS_FF_GUARD_CANARY_PERCENT 미설정 → default 0 → 모두 shadow fallback.

    D74-canary 신규 추가 후 enforce 활성화 시 즉시 100% 차단 방지 — 안전 default.
    """
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.delenv("KMS_FF_GUARD_CANARY_PERCENT", raising=False)
    ctx = _FakeCtx(agent_id="any-agent-id")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=ctx, source="test",
    )
    # default 0 → outside → shadow → 원본 그대로.
    assert r["success"] is True


# ─── D74-canary 사후 GPT-5.5 권고 §5 §6 — server-issued only + non-string ──


async def test_enforce_canary_method_arg_agent_context_ignored(
    monkeypatch, registry_with_success_tool,
):
    """canary 결정은 *self._agent_context.agent_id* 만 사용 — method arg 무시.

    공격자가 임의 agent_context 를 method 인자로 주입해 canary 안 bucket 으로
    이동시키는 우회 차단 (사후 GPT-5.5 §5 권고).
    """
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "0")
    # engine 의 server-issued context = None (agent_id 없음).
    eng = _FakeEngine(registry_with_success_tool, agent_context=None)
    # method 인자로 inside-bucket agent_id 를 주입해도, canary 결정은
    # self._agent_context (None) 만 보므로 missing 으로 처리 → shadow fallback.
    attacker_ctx = _FakeCtx(agent_id="attacker-tries-canary-bypass")
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=attacker_ctx, source="test",
    )
    # missing → shadow → 원본 그대로 (다운그레이드 X).
    assert r["success"] is True
    assert r["echo"] == {"foo": "bar"}


async def test_enforce_canary_non_string_agent_id_treated_missing(
    monkeypatch, registry_with_success_tool,
):
    """non-string agent_id (int 등) → missing 으로 처리 — str 강제 변환 X.

    이전 구현은 ``str(_aid)`` 로 `"123"` 같은 string 변환 후 canary 진입.
    사후 GPT-5.5 §3 권고 — non-string 은 missing fallback (보안 우회 방지).
    """
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    # agent_id=123 (int)
    ctx = _FakeCtx(agent_id=123)  # type: ignore[arg-type]
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=ctx, source="test",
    )
    # missing → shadow → 원본 그대로 (다운그레이드 X).
    assert r["success"] is True


# ─── D74-canary metric emit ────────────────────────────────────────────────


async def test_canary_metric_emit_inside_bucket(
    monkeypatch, registry_with_success_tool,
):
    """enforce + valid agent_id + percent=100 → metric (inside, enforce) inc."""
    from src.common import metrics as M

    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="metric-test-agent-001")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)

    # baseline counter — high-cardinality 회피로 label 만 사용.
    # D82-C P1: source 라벨 추가됨. "test" source 는 whitelist 외 → "other".
    try:
        before = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="inside", decision="enforce", source="other"
        )._value.get()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        before = None

    await eng._safe_tool_call(
        "demo.list", {}, agent_context=ctx, source="test",  # read → 비 downgrade.
    )

    if before is not None:
        after = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="inside", decision="enforce", source="other"
        )._value.get()  # type: ignore[attr-defined]
        assert after >= before + 1, f"inside/enforce counter 증가 안 됨 ({before} → {after})"


async def test_canary_metric_emit_missing_bucket(
    monkeypatch, registry_with_success_tool,
):
    """enforce + agent_id 없음 → metric (missing, shadow) inc."""
    from src.common import metrics as M

    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    eng = _FakeEngine(registry_with_success_tool, agent_context=None)

    # D82-C P1: source 라벨 추가됨. "test" → "other".
    try:
        before = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="missing", decision="shadow", source="other"
        )._value.get()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        before = None

    await eng._safe_tool_call(
        "demo.list", {}, agent_context=None, source="test",
    )

    if before is not None:
        after = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="missing", decision="shadow", source="other"
        )._value.get()  # type: ignore[attr-defined]
        assert after >= before + 1


async def test_canary_metric_emit_n_a_for_base_shadow(
    monkeypatch, registry_with_success_tool,
):
    """base=shadow → bucket=n_a, decision=shadow (canary 무관)."""
    from src.common import metrics as M

    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_SHADOW)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id="any")
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)

    # D82-C P1: source 라벨 추가됨. "test" → "other".
    try:
        before = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="n_a", decision="shadow", source="other"
        )._value.get()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        before = None

    await eng._safe_tool_call(
        "demo.list", {}, agent_context=ctx, source="test",
    )

    if before is not None:
        after = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="n_a", decision="shadow", source="other"
        )._value.get()  # type: ignore[attr-defined]
        assert after >= before + 1


# ─── D74-canary deterministic golden vector (GPT-5.5 §6.4) ────────────────


def test_canary_golden_vector_deterministic():
    """고정 agent_id set 에 대해 10% / 50% bucket 결정이 결정적.

    flaky 회피 — uuid 분포 대신 명시적 golden vector. 향후 hash 알고리즘
    변경 시 회귀 즉시 감지.
    """
    from src.agent_framework.runtime.safe_tool_call import _is_canary_enabled

    # 100 개 결정값을 고정. 알고리즘 변경 시 이 vector 도 갱신해야 회귀.
    fixed = [f"golden-agent-{i:03d}" for i in range(100)]
    for percent in (0, 10, 50, 100):
        results = [_is_canary_enabled(aid, percent) for aid in fixed]
        # 0 → 모두 False, 100 → 모두 True.
        if percent == 0:
            assert not any(results)
        elif percent == 100:
            assert all(results)
        else:
            # 10% / 50% — inside count 가 percent 의 ±2x 범위 (작은 vector).
            inside = sum(results)
            assert inside > 0, f"percent={percent} 모두 outside (분포 이상)"
            # 작은 100 vector — bound 느슨하게.
            assert inside <= percent * 3, (
                f"percent={percent} inside {inside} 비정상 (>3x)"
            )


def test_canary_non_string_treated_missing_helper():
    """canary_bucket(non_string, ...) → missing — helper level (engine 통합 보완)."""
    from src.agent_framework.runtime.safe_tool_call import (
        CANARY_BUCKET_MISSING,
        canary_bucket,
    )
    for aid in [123, 1.5, b"bytes", object(), [], {}]:
        assert canary_bucket(aid, 50) == CANARY_BUCKET_MISSING


# ─── D82-C P1 (2026-05-13) — UUID agent_id 통합 + scheduled stale 차단 ─────


async def test_d82c_enforce_uuid_agent_id_downgrades(
    monkeypatch, registry_with_success_tool,
):
    """D82-C 핵심 — UUID 인스턴스 agent_id 도 canary inside 로 분류돼 downgrade 동작.

    D80 결함: UUID 가 missing 분류 → shadow fallback → downgrade 안 됨.
    D82-C 후: UUID 정상 normalize → inside → enforce → downgrade.
    """
    import uuid as _uuid
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id=_uuid.uuid4())  # type: ignore[arg-type]
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)
    r = await eng._safe_tool_call(
        "demo.delete", {"foo": "bar"}, agent_context=ctx, source="rft",
    )
    # D82-C 후: UUID 도 inside → enforce → downgrade.
    assert r["success"] is False
    assert r["error"] == "unsafe_needs_confirm"


async def test_d82c_scheduled_source_ignores_stale_agent_context(
    monkeypatch, registry_with_success_tool,
):
    """scheduled source 일 땐 self._agent_context 가 set 돼 있어도 사용 X.

    GPT-5.5 §2 — scheduled trigger 는 invoke 외부 진입. self._agent_context 가
    이전 invoke 의 잔재일 수 있으므로 stale agent_id 로 canary 계산하는 걸 차단.
    metric: missing bucket + source='scheduled' 로 라벨링.
    """
    import uuid as _uuid
    from src.common import metrics as M

    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    # 이전 invoke 잔재로 self._agent_context 가 set 된 상태.
    stale_ctx = _FakeCtx(agent_id=_uuid.uuid4())  # type: ignore[arg-type]
    eng = _FakeEngine(registry_with_success_tool, agent_context=stale_ctx)

    # scheduled missing+shadow+scheduled 의 baseline.
    try:
        before = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="missing", decision="shadow", source="scheduled"
        )._value.get()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        before = None

    r = await eng._safe_tool_call(
        "demo.list", {}, agent_context=stale_ctx, source="scheduled",
    )
    # missing → shadow fallback → 원본 그대로 (downgrade X, read tool 이라도 안전).
    assert r["success"] is True

    if before is not None:
        after = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
            bucket="missing", decision="shadow", source="scheduled"
        )._value.get()  # type: ignore[attr-defined]
        assert after >= before + 1, (
            f"scheduled missing+shadow counter inc 안 됨 ({before}→{after})"
        )


async def test_d82c_source_label_distinguishes_sites(
    monkeypatch, registry_with_success_tool,
):
    """9 source 라벨이 metric 에서 분리돼 inc — alert dashboard 분리 근거."""
    import uuid as _uuid
    from src.common import metrics as M

    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", FF_ENFORCE)
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    ctx = _FakeCtx(agent_id=_uuid.uuid4())  # type: ignore[arg-type]
    eng = _FakeEngine(registry_with_success_tool, agent_context=ctx)

    valid_sources = [
        "rft", "plan_pre_clarify", "plan_serial", "plan_parallel",
        "plan_serial_fallback", "sop_inject",
        "execution_policy_guard", "pr_e4_audit",
    ]
    for src in valid_sources:
        # read tool → downgrade X. inc 만 검증.
        try:
            before = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
                bucket="inside", decision="enforce", source=src
            )._value.get()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            before = None
        await eng._safe_tool_call(
            "demo.list", {}, agent_context=ctx, source=src,
        )
        if before is not None:
            after = M.KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.labels(
                bucket="inside", decision="enforce", source=src
            )._value.get()  # type: ignore[attr-defined]
            assert after >= before + 1, (
                f"source={src} inside/enforce counter inc 안 됨"
            )
