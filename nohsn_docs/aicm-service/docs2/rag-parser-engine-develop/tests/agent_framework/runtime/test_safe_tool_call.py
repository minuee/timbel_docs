"""D74 (2026-05-11) — safe_tool_call.py 단위 테스트.

# 검증 영역
- ``get_ff_mode()`` env tristate + 안전 fallback.
- ``infer_op_type()`` 휴리스틱 — write/read.
- ``has_confirm_evidence()`` confirm_id 동의어.
- ``downgrade_to_unsafe()`` schema 정합.

D72 의 단위 테스트 패턴 (tests/agent_framework/runtime/test_tool_guard.py) 과
동일 스타일.
"""
from __future__ import annotations

import os

import pytest

from src.agent_framework.runtime.safe_tool_call import (
    FF_ENFORCE,
    FF_OFF,
    FF_SHADOW,
    downgrade_to_unsafe,
    get_ff_mode,
    has_confirm_evidence,
    infer_op_type,
)


# ─── get_ff_mode ──────────────────────────────────────────────────────────


def test_ff_mode_default_off(monkeypatch):
    """env 미설정 → off."""
    monkeypatch.delenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", raising=False)
    assert get_ff_mode() == FF_OFF


def test_ff_mode_shadow(monkeypatch):
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "shadow")
    assert get_ff_mode() == FF_SHADOW


def test_ff_mode_enforce(monkeypatch):
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    assert get_ff_mode() == FF_ENFORCE


def test_ff_mode_invalid_falls_back_to_off(monkeypatch):
    """잘못된 값 → off (안전 fallback)."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "garbage")
    assert get_ff_mode() == FF_OFF


def test_ff_mode_case_insensitive(monkeypatch):
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "SHADOW")
    assert get_ff_mode() == FF_SHADOW


# ─── infer_op_type ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool,expected",
    [
        ("expense.delete", "write"),
        ("memo.delete", "write"),
        ("schedule.delete", "write"),
        ("schedule.delete_all", "write"),
        ("schedule.delete_duplicates", "write"),
        ("mail.send", "write"),
        ("stock.add_watch", "write"),
        ("memo.create", "write"),
        ("schedule.update", "write"),
        ("reminder.cancel", "write"),
        ("kms_rag.search", "read"),
        ("kms_sop.search", "read"),
        ("schedule.list", "read"),
        ("expense.list", "read"),
        ("memo.get", "read"),
        ("mail.list", "read"),
        ("", "read"),
    ],
)
def test_infer_op_type(tool, expected):
    assert infer_op_type(tool) == expected


# ─── has_confirm_evidence ──────────────────────────────────────────────────


def test_confirm_evidence_canonical_id():
    assert has_confirm_evidence({"confirm_id": "abc"}) is True


def test_confirm_evidence_synonym_confirmation_id():
    assert has_confirm_evidence({"confirmation_id": "xyz"}) is True


def test_confirm_evidence_synonym_token():
    assert has_confirm_evidence({"confirm_token": "tok"}) is True


def test_confirm_evidence_missing():
    assert has_confirm_evidence({"foo": "bar"}) is False


def test_confirm_evidence_empty_string_is_false():
    """빈 문자열 → falsy → 미보유 취급."""
    assert has_confirm_evidence({"confirm_id": ""}) is False


def test_confirm_evidence_non_dict():
    assert has_confirm_evidence("not a dict") is False
    assert has_confirm_evidence(None) is False
    assert has_confirm_evidence([]) is False


# ─── downgrade_to_unsafe ──────────────────────────────────────────────────


def test_downgrade_schema():
    r = downgrade_to_unsafe(tool="memo.delete", op_type="write")
    assert r["success"] is False
    assert r["error"] == "unsafe_needs_confirm"
    assert r["tool"] == "memo.delete"
    assert r["op_type"] == "write"
    assert isinstance(r["user_message"], str) and len(r["user_message"]) > 0


# ─── D74-canary — get_canary_percent / _is_canary_enabled / get_ff_mode_for_agent ─


from src.agent_framework.runtime.safe_tool_call import (  # noqa: E402
    CANARY_BUCKET_INSIDE,
    CANARY_BUCKET_MISSING,
    CANARY_BUCKET_N_A,
    CANARY_BUCKET_OUTSIDE,
    _is_canary_enabled,
    canary_bucket,
    get_canary_percent,
    get_ff_mode_for_agent,
)


# get_canary_percent


def test_canary_percent_default(monkeypatch):
    monkeypatch.delenv("KMS_FF_GUARD_CANARY_PERCENT", raising=False)
    assert get_canary_percent() == 0


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", 0),
        ("10", 10),
        ("50", 50),
        ("100", 100),
        ("-5", 0),   # clamp
        ("150", 100),  # clamp
        ("abc", 0),  # invalid → 0
        ("", 0),
        ("  25  ", 25),
    ],
)
def test_canary_percent_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", raw)
    assert get_canary_percent() == expected


# _is_canary_enabled


def test_canary_zero_percent_all_outside():
    """percent=0 → 어떤 agent_id 도 outside."""
    for aid in ["a", "b", "ricky", "agent-xyz", "00000"]:
        assert _is_canary_enabled(aid, 0) is False


def test_canary_full_percent_all_inside():
    """percent=100 → 모두 inside."""
    for aid in ["a", "b", "ricky", "agent-xyz", "00000"]:
        assert _is_canary_enabled(aid, 100) is True


def test_canary_consistent_hashing_stable():
    """동일 agent_id → 동일 결과 (재호출/재시작 후 안정성)."""
    aid = "agent-consistent-001"
    first = _is_canary_enabled(aid, 10)
    for _ in range(20):
        assert _is_canary_enabled(aid, 10) is first


def test_canary_10_percent_distribution_approx():
    """100 agent 중 10% canary inside (분포 ±5% 허용)."""
    import uuid
    inside = sum(
        1 for _ in range(1000)
        if _is_canary_enabled(str(uuid.uuid4()), 10)
    )
    # binomial std ~ sqrt(1000*0.1*0.9) ≈ 9.5 → ±30 (3σ).
    assert 50 <= inside <= 150, f"inside={inside} 10% 분포 이탈 (1000 중 50-150 기대)"


def test_canary_50_percent_distribution_approx():
    import uuid
    inside = sum(
        1 for _ in range(1000)
        if _is_canary_enabled(str(uuid.uuid4()), 50)
    )
    assert 400 <= inside <= 600, f"inside={inside} 50% 분포 이탈"


# canary_bucket


def test_canary_bucket_missing_agent_id():
    """agent_id None / '' / whitespace / non-str → missing."""
    for aid in [None, "", "   ", 0, 123, [], {}, object()]:
        assert canary_bucket(aid, 10) == CANARY_BUCKET_MISSING


def test_canary_bucket_inside_outside():
    """inside / outside 라벨."""
    # percent=100 — 모두 inside.
    assert canary_bucket("any-agent", 100) == CANARY_BUCKET_INSIDE
    # percent=0 — 모두 outside.
    assert canary_bucket("any-agent", 0) == CANARY_BUCKET_OUTSIDE


# get_ff_mode_for_agent — 통합 분기


def test_mode_for_agent_off_passthrough(monkeypatch):
    """base=off → ('off', 'n_a'). canary 무관."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "off")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    mode, bucket = get_ff_mode_for_agent("any")
    assert mode == "off"
    assert bucket == CANARY_BUCKET_N_A


def test_mode_for_agent_shadow_passthrough(monkeypatch):
    """base=shadow → ('shadow', 'n_a'). canary 무관."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "shadow")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "0")
    mode, bucket = get_ff_mode_for_agent("any")
    assert mode == "shadow"
    assert bucket == CANARY_BUCKET_N_A


def test_mode_for_agent_enforce_canary_100(monkeypatch):
    """base=enforce + canary=100 → ('enforce', 'inside')."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    mode, bucket = get_ff_mode_for_agent("agent-001")
    assert mode == "enforce"
    assert bucket == CANARY_BUCKET_INSIDE


def test_mode_for_agent_enforce_canary_0(monkeypatch):
    """base=enforce + canary=0 → ('shadow', 'outside'). fallback."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "0")
    mode, bucket = get_ff_mode_for_agent("agent-001")
    assert mode == "shadow"
    assert bucket == CANARY_BUCKET_OUTSIDE


def test_mode_for_agent_enforce_missing_agent_id(monkeypatch):
    """base=enforce + agent_id 누락 → ('shadow', 'missing'). 안전 fallback."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    for aid in [None, "", "  "]:
        mode, bucket = get_ff_mode_for_agent(aid)
        assert mode == "shadow"
        assert bucket == CANARY_BUCKET_MISSING


def test_mode_for_agent_enforce_partial_canary_stability(monkeypatch):
    """동일 agent_id 가 enforce/shadow 사이를 *왔다갔다 X* — stable."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "50")
    aid = "stable-agent-12345"
    first_mode, first_bucket = get_ff_mode_for_agent(aid)
    for _ in range(20):
        m, b = get_ff_mode_for_agent(aid)
        assert m == first_mode
        assert b == first_bucket
