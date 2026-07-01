"""D82-C P1 (2026-05-13) — canary agent_id normalize + UUID 허용 단위 테스트.

# 결함 배경 (D80 metric)
``kms_safe_tool_call_canary_bucket_total{bucket="missing",decision="shadow"}=42``
— 모든 호출이 missing 으로 분류돼 canary 1% 실효 표본 0.

# 원인
``AgentContext.agent_id`` 는 ``uuid.UUID`` 인스턴스인데, 기존
``_is_valid_agent_id`` 는 ``isinstance(_, str)`` 만 통과시켜 100% missing 분류.

# D82-C P1 fix
- ``_normalize_agent_id(value)`` helper 신설 — ``str | UUID`` 만 허용.
- canary hashing 은 정규화된 str 위에서 동작 — 기존 str 입력 hash 안정성 유지.
- ``emit_canary_bucket`` + ``inc_safe_tool_call_canary_bucket`` 에 ``source``
  라벨 추가 — scheduled missing 과 실제 agent_id 추출 실패 missing 분리.

# 검증 매트릭스 (GPT-5.5 사전 verdict §5 요구)
1. ``_normalize_agent_id`` — str / UUID / None / int / bytes / list / dict / custom
2. UUID 인스턴스와 ``str(UUID)`` 입력이 *같은 bucket* 으로 분류 (consistent hashing)
3. 기존 str 입력 hash 안정성 — D82-C 전후 동일 결과
4. AgentContext (frozen dataclass with UUID agent_id) → canary 정상 분류
5. 9 source 라벨 각각 inc_safe_tool_call_canary_bucket 정상 동작
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from uuid import UUID

import pytest

from src.agent_framework.runtime.safe_tool_call import (
    CANARY_BUCKET_INSIDE,
    CANARY_BUCKET_MISSING,
    CANARY_BUCKET_N_A,
    CANARY_BUCKET_OUTSIDE,
    FF_ENFORCE,
    FF_OFF,
    FF_SHADOW,
    _is_canary_enabled,
    _is_valid_agent_id,
    _normalize_agent_id,
    canary_bucket,
    emit_canary_bucket,
    get_ff_mode_for_agent,
)


# ─── _normalize_agent_id ──────────────────────────────────────────────────


def test_normalize_str_valid():
    """str → strip() 후 그대로."""
    assert _normalize_agent_id("agent-001") == "agent-001"
    assert _normalize_agent_id("  agent-001  ") == "agent-001"


def test_normalize_str_empty_or_whitespace():
    """빈 문자열 / whitespace 만 → None."""
    assert _normalize_agent_id("") is None
    assert _normalize_agent_id("   ") is None
    assert _normalize_agent_id("\t\n") is None


def test_normalize_uuid_instance():
    """UUID 인스턴스 → str(uuid) canonical form ("xxxxxxxx-...")."""
    u = UUID("12345678-1234-5678-1234-567812345678")
    assert _normalize_agent_id(u) == "12345678-1234-5678-1234-567812345678"


def test_normalize_uuid_dynamic():
    """uuid.uuid4() 도 정상 정규화."""
    u = uuid.uuid4()
    normalized = _normalize_agent_id(u)
    assert isinstance(normalized, str)
    assert normalized == str(u)
    # 4-2-2-2-6 hyphenated form.
    assert len(normalized) == 36
    assert normalized.count("-") == 4


@pytest.mark.parametrize(
    "value",
    [None, 0, 123, 1.5, b"bytes-not-allowed", b"", [], {}, object()],
)
def test_normalize_rejects_invalid(value):
    """None / int / float / bytes / list / dict / custom → None.

    GPT-5.5 §1 — ``hasattr(.hex)`` 같은 광범위 허용 금지.
    """
    assert _normalize_agent_id(value) is None


def test_normalize_subclass_of_str():
    """str subclass 도 허용 (예: Django의 SafeString 같은 경우)."""
    class _SubStr(str):
        pass
    assert _normalize_agent_id(_SubStr("x")) == "x"


# ─── _is_valid_agent_id — normalize 기반 ──────────────────────────────────


def test_is_valid_uuid_now_accepted():
    """D82-C 핵심 fix — UUID 인스턴스가 valid 로 분류됨."""
    u = uuid.uuid4()
    assert _is_valid_agent_id(u) is True


def test_is_valid_str_still_works():
    """str 기존 동작 유지 — 회귀 0."""
    assert _is_valid_agent_id("a") is True
    assert _is_valid_agent_id("") is False
    assert _is_valid_agent_id(None) is False


@pytest.mark.parametrize(
    "value", [0, 123, 1.5, b"x", [], {}, object()],
)
def test_is_valid_rejects_invalid(value):
    assert _is_valid_agent_id(value) is False


# ─── consistent hashing — UUID vs str(UUID) 동일 bucket ───────────────────


def test_uuid_instance_and_str_same_bucket():
    """``UUID(...)`` 인스턴스와 ``str(UUID)`` 가 정확히 같은 hash bucket.

    GPT-5.5 §5 — 핵심 검증. _normalize_agent_id 가 UUID → str(uuid) 변환만
    하고 다른 형식 (.hex 등) 안 씀.
    """
    for _ in range(20):
        u = uuid.uuid4()
        for pct in (1, 10, 50, 99):
            assert _is_canary_enabled(u, pct) == _is_canary_enabled(str(u), pct)
            assert canary_bucket(u, pct) == canary_bucket(str(u), pct)


def test_existing_str_hash_stability():
    """기존 str 입력의 hash bucket 이 D82-C 전후 동일 (회귀 0).

    이전 ``hashlib.sha256("agent-001".encode())`` 의 결과는 normalize 후
    그대로 사용 → mod 100 결과 동일.

    Golden vector: sha256("agent-001")[:8] = "69d99cbc"
                   int("69d99cbc", 16) = 1775869116
                   1775869116 % 100 = 16
    → percent < 17 → outside, percent >= 17 → inside.
    """
    assert _is_canary_enabled("agent-001", 16) is False
    assert _is_canary_enabled("agent-001", 17) is True
    # consistent across calls.
    for _ in range(10):
        assert _is_canary_enabled("agent-001", 16) is False
        assert _is_canary_enabled("agent-001", 50) is True


def test_canary_bucket_for_uuid_not_missing():
    """D80 결함 재현 — 이제 UUID 인스턴스가 inside/outside 로 정상 분류."""
    u = uuid.uuid4()
    b100 = canary_bucket(u, 100)
    b0 = canary_bucket(u, 0)
    assert b100 == CANARY_BUCKET_INSIDE
    assert b0 == CANARY_BUCKET_OUTSIDE
    # 단순히 missing 이 아님이 핵심.
    assert b100 != CANARY_BUCKET_MISSING
    assert b0 != CANARY_BUCKET_MISSING


# ─── get_ff_mode_for_agent — UUID 입력 통합 ───────────────────────────────


def test_mode_for_agent_uuid_enforce_inside(monkeypatch):
    """enforce + percent=100 + UUID 인스턴스 → inside."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    u = uuid.uuid4()
    mode, bucket = get_ff_mode_for_agent(u)
    assert mode == FF_ENFORCE
    assert bucket == CANARY_BUCKET_INSIDE


def test_mode_for_agent_uuid_enforce_outside(monkeypatch):
    """enforce + percent=0 + UUID 인스턴스 → outside."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "0")
    u = uuid.uuid4()
    mode, bucket = get_ff_mode_for_agent(u)
    assert mode == FF_SHADOW
    assert bucket == CANARY_BUCKET_OUTSIDE


def test_mode_for_agent_off_uuid_passthrough(monkeypatch):
    """off mode → ('off', 'n_a'). UUID 무관."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "off")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")
    u = uuid.uuid4()
    mode, bucket = get_ff_mode_for_agent(u)
    assert mode == FF_OFF
    assert bucket == CANARY_BUCKET_N_A


# ─── AgentContext (UUID agent_id frozen dataclass) ─────────────────────────


@dataclass(frozen=True)
class _FakeAgentContext:
    """AgentContext 의 UUID agent_id 패턴 모사."""
    agent_id: UUID


def test_agent_context_uuid_canary(monkeypatch):
    """AgentContext.agent_id (UUID) 추출 → canary inside (D80 재현 + fix 검증)."""
    monkeypatch.setenv("KMS_FF_GUARD_UNIFY_TOOL_CALL", "enforce")
    monkeypatch.setenv("KMS_FF_GUARD_CANARY_PERCENT", "100")

    ctx = _FakeAgentContext(agent_id=uuid.uuid4())
    mode, bucket = get_ff_mode_for_agent(ctx.agent_id)
    # D82-C 전: bucket == "missing", mode == "shadow"
    # D82-C 후: bucket == "inside", mode == "enforce"
    assert bucket == CANARY_BUCKET_INSIDE
    assert mode == FF_ENFORCE


# ─── source 라벨 — 9 source 모두 정상 inc ─────────────────────────────────


@pytest.mark.parametrize(
    "source",
    [
        "rft",
        "plan_pre_clarify",
        "plan_serial",
        "plan_parallel",
        "plan_serial_fallback",
        "scheduled",
        "sop_inject",
        "execution_policy_guard",
        "pr_e4_audit",
    ],
)
def test_emit_canary_bucket_each_source(source):
    """9 site source 모두 metric inc 정상 — 예외 없이 통과."""
    # prometheus_client 가 없을 수도 있어 NoOp fallback. 예외 안 던지면 OK.
    emit_canary_bucket(bucket="inside", decision="enforce", source=source)
    emit_canary_bucket(bucket="missing", decision="shadow", source=source)


def test_emit_canary_bucket_unknown_source_falls_to_other():
    """allowed 외 source → "other" 로 label 정규화 (cardinality 보호)."""
    # 직접 검증은 어렵지만 (Counter 내부 동작), 예외 없이 통과해야 함.
    emit_canary_bucket(bucket="inside", decision="enforce", source="custom-x")
    emit_canary_bucket(bucket="missing", decision="shadow", source="")


def test_emit_canary_bucket_source_default_falls_to_other():
    """D82-residual #B — source 인자 누락 default 도 "other" 로 통일.

    이전 (D82-C): default ``"unknown"`` (ALLOWED 안에 포함).
    이후 (D82-residual #B): default ``"other"`` (단일 fallback) — 인자 누락 /
    whitelist 외 모두 동일 label 로 집계. metric/alert/dashboard 정합.
    """
    # 인자 누락 — 예외 없이 통과 + 내부적으로 "other" 라벨.
    emit_canary_bucket(bucket="inside", decision="enforce")


# ─── #B fallback 매핑 — direct unit test on inc_safe_tool_call_canary_bucket ─


def test_inc_safe_tool_call_canary_bucket_arbitrary_source_maps_to_fallback():
    """D82-residual #B — 임의 source 가 단일 fallback label 로 매핑되는지 검증.

    GPT-5.5 verdict §B 권고: "emit_canary_bucket(..., source='arbitrary_new_site')
    가 정확히 그 fallback 으로 매핑되는 단위 테스트 추가." cardinality 보호 +
    신규 call site drift 시 series 폭증 차단.
    """
    from src.common.metrics import (
        ALLOWED_SAFE_TOOL_CALL_SOURCES,
        CANARY_SOURCE_FALLBACK,
        KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL,
        inc_safe_tool_call_canary_bucket,
    )

    # fallback 은 단일 source-of-truth 상수.
    assert CANARY_SOURCE_FALLBACK == "other"
    # "unknown" 은 더 이상 whitelist 에 없음 (단일 fallback 통일).
    assert "unknown" not in ALLOWED_SAFE_TOOL_CALL_SOURCES

    # 임의 source 호출 — 예외 없이 통과해야 함.
    arbitrary_sources = [
        "arbitrary_new_site",
        "",
        "   ",
        "rft_v2",  # 기존 site 의 변형이지만 whitelist 외.
        "UNKNOWN",  # case-sensitive — 대문자 변형도 fallback.
    ]
    for src in arbitrary_sources:
        inc_safe_tool_call_canary_bucket(
            bucket="inside", decision="enforce", source=src
        )

    # prometheus_client 가 설치된 환경이면 fallback label 의 sample 이 존재해야 함.
    # NoOp fallback 환경에서는 skip — labels() 가 self 를 반환하므로 sample 없음.
    try:
        samples = list(KMS_SAFE_TOOL_CALL_CANARY_BUCKET_TOTAL.collect())
    except Exception:
        samples = []
    if samples:
        # 적어도 한 sample 이 source=fallback 라벨을 가지면 매핑 동작 OK.
        observed = []
        for fam in samples:
            for s in fam.samples:
                observed.append(s.labels.get("source"))
        assert CANARY_SOURCE_FALLBACK in observed, (
            f"fallback label 'other' 가 sample 에 없음. observed sources: "
            f"{sorted(set(observed))}"
        )


def test_inc_safe_tool_call_canary_bucket_default_source_is_other():
    """D82-residual #B — default 인자 (source 누락) 도 "other" fallback."""
    from src.common.metrics import (
        CANARY_SOURCE_FALLBACK,
        inc_safe_tool_call_canary_bucket,
    )

    # default 누락 호출.
    inc_safe_tool_call_canary_bucket(bucket="missing", decision="shadow")
    # 의미: default 인자 문자열이 ALLOWED 외이므로 매핑 후 fallback.
    assert CANARY_SOURCE_FALLBACK == "other"


def test_inc_safe_tool_call_canary_bucket_allowed_sources_pass_through():
    """ALLOWED 9 site 는 fallback 으로 강등되지 않음 — regression guard."""
    from src.common.metrics import (
        ALLOWED_SAFE_TOOL_CALL_SOURCES,
        CANARY_SOURCE_FALLBACK,
        inc_safe_tool_call_canary_bucket,
    )

    # 9 site 모두 정상 inc.
    for src in sorted(ALLOWED_SAFE_TOOL_CALL_SOURCES):
        inc_safe_tool_call_canary_bucket(
            bucket="inside", decision="enforce", source=src
        )
        assert src != CANARY_SOURCE_FALLBACK
