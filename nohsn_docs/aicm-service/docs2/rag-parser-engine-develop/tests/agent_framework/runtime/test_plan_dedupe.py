import pytest
from src.agent_framework.runtime.plan_postprocess.plan_dedupe import (
    dedupe_plan,
    from_plan_step,
    DedupedStep,
    DedupeNote,
)


def _step(step, kind, tool=None, args=None, expr=None):
    return DedupedStep(step=step, kind=kind, tool=tool,
                       args=args or {}, expr=expr)


# D28 §2 — from_plan_step helper (DRY) tests
class _FakePlanStep:
    """PlanStep duck-type fixture — 실제 PlanStep import 회피 (단위 테스트 격리)."""

    def __init__(self, step, kind, raw):
        self.step = step
        self.kind = kind
        self.raw = raw


def test_from_plan_step_normal():
    """raw={...} 정상 케이스 — 모든 필드 정확히 추출."""
    ps = _FakePlanStep(
        step=3, kind="tool",
        raw={"tool": "kms_rag.search", "args": {"query": "x"}, "expr": None},
    )
    ds = from_plan_step(ps)
    assert ds.step == 3
    assert ds.kind == "tool"
    assert ds.tool == "kms_rag.search"
    assert ds.args == {"query": "x"}
    assert ds.expr is None


def test_from_plan_step_raw_none():
    """raw=None — args={}, tool=None, expr=None 안전 fallback."""
    ps = _FakePlanStep(step=1, kind="reasoning", raw=None)
    ds = from_plan_step(ps)
    assert ds.step == 1
    assert ds.kind == "reasoning"
    assert ds.tool is None
    assert ds.args == {}
    assert ds.expr is None


def test_from_plan_step_raw_non_dict():
    """raw=비-dict (list 등) — {} 로 정규화 (하드닝, GPT-5 권고)."""
    ps = _FakePlanStep(step=2, kind="tool", raw=[1, 2, 3])
    ds = from_plan_step(ps)
    assert ds.tool is None
    assert ds.args == {}
    assert ds.expr is None


def test_from_plan_step_raw_empty_dict():
    """raw={} — 모든 키 누락 → tool/expr=None, args={}."""
    ps = _FakePlanStep(step=4, kind="tool", raw={})
    ds = from_plan_step(ps)
    assert ds.tool is None
    assert ds.args == {}
    assert ds.expr is None


def test_from_plan_step_args_falsy_normalized():
    """raw.args 가 falsy (None/빈 dict) → {} 로 정규화."""
    for falsy in (None, {}, ""):
        ps = _FakePlanStep(step=5, kind="tool", raw={"tool": "t", "args": falsy})
        ds = from_plan_step(ps)
        assert ds.args == {}, f"args falsy={falsy!r} 정규화 실패"


def test_from_plan_step_args_dict_preserved():
    """raw.args 가 정상 dict — 그대로 보존."""
    ps = _FakePlanStep(
        step=6, kind="tool",
        raw={"tool": "t", "args": {"a": 1, "b": "two"}},
    )
    ds = from_plan_step(ps)
    assert ds.args == {"a": 1, "b": "two"}


def test_from_plan_step_step_kind_required():
    """step/kind 누락 시 AttributeError — 기존 동작과 byte-equal (GPT-5 권고)."""
    class _MissingFields:
        raw = {}
    with pytest.raises(AttributeError):
        from_plan_step(_MissingFields())


def test_trace_a_compression():
    """trace A 의 6 step plan 입력 → 중복 kms+web 제거 → 5 step (1 dedupe)."""
    plan = [
        _step(1, "tool", "kms_rag.search", {"query": "주식 매도 대금"}),
        _step(2, "tool", "web.search", {"query": "주식 매도 대금"}),
        _step(3, "reasoning", expr="KMS 결과 확인"),
        _step(4, "tool", "kms_rag.search", {"query": "주식 매도 대금"}),  # 중복
        _step(5, "tool", "web.search", {"query": "삼성전자 주식 매도 대금"}),  # 다른 query → 보존
        _step(6, "reasoning", expr="최종 합성"),
    ]
    deduped, notes = dedupe_plan(plan)
    # step 4 가 step 1 과 동일 signature → 제거
    assert len(deduped) == 5
    # 제거된 step 의 signature 가 note 에 기록
    assert any("kms_rag.search" in n.removed_signature for n in notes)


def test_no_dupes_passthrough():
    plan = [
        _step(1, "tool", "kms_rag.search", {"query": "휴가"}),
        _step(2, "tool", "web.search", {"query": "휴가"}),
        _step(3, "reasoning", expr="합성"),
    ]
    deduped, notes = dedupe_plan(plan)
    assert deduped == plan
    assert notes == []


def test_reasoning_steps_preserved():
    """reasoning 은 args/expr 가 같아도 보존 (expr 가 흐름 의미)."""
    plan = [
        _step(1, "reasoning", expr="check"),
        _step(2, "reasoning", expr="check"),  # expr 동일 — 그래도 보존
    ]
    deduped, notes = dedupe_plan(plan)
    assert len(deduped) == 2


def test_normalized_args_match():
    """공백/대소문자 차이는 동일 signature."""
    plan = [
        _step(1, "tool", "kms_rag.search", {"query": " 주식 매도 "}),
        _step(2, "tool", "kms_rag.search", {"query": "주식 매도"}),
    ]
    deduped, _ = dedupe_plan(plan)
    assert len(deduped) == 1


def test_empty_plan():
    deduped, notes = dedupe_plan([])
    assert deduped == []
    assert notes == []


def test_multiple_dupes():
    """3 개 동일 signature → 2 개 제거."""
    plan = [
        _step(1, "tool", "kms_rag.search", {"query": "x"}),
        _step(2, "tool", "kms_rag.search", {"query": "x"}),
        _step(3, "tool", "kms_rag.search", {"query": "x"}),
    ]
    deduped, notes = dedupe_plan(plan)
    assert len(deduped) == 1
    assert len(notes) == 2
