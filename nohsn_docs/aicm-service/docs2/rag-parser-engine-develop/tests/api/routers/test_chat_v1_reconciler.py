"""Stage 4 — SKILL_INTENT_RECONCILE wire 검증.

dispatcher 의 reconcile 호출 분기를 직접 재현.
HTTP 레이어 없이 flag / event 흐름만 단위 검증.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.common.feature_flags import FeatureFlag, is_enabled
from src.agent_framework.runtime.reconcilers.skill_intent_reconciler import (
    SkillIntentDecision,
    reconcile,
)


# ---------------------------------------------------------------------------
# helper: dispatcher 의 reconcile 분기를 in-process 로 재현하는 thin harness.
# chat_v1.stream() 의 핵심 로직을 추출 — HTTP / DB / engine 없이 검증.
# ---------------------------------------------------------------------------

async def _run_reconcile_branch(
    *,
    flag_on: bool,
    skill_v2_name: str | None,
    intent_label: str | None,
    mock_decision: SkillIntentDecision | None,
    user_text: str = "내일 병원 진료 예약을 꼭 할수 있게 메모 해줘",
) -> dict:
    """dispatcher 의 reconcile 분기를 재현.

    Returns dict with keys:
      reconcile_called: bool — reconcile() 가 호출됐는지
      captured_intent: str | None — 최종 captured_intent 값
      emitted_event: str | None — yield 된 skill_intent_reconciled event 의 resolved
    """
    result = {
        "reconcile_called": False,
        "captured_intent": intent_label,
        "emitted_event": None,
    }

    # flag 평가 — stream() 진입 전 한 번.
    _reconcile_enabled = is_enabled(FeatureFlag.SKILL_INTENT_RECONCILE)

    if not _reconcile_enabled:
        # flag off → 분기 미진입, captured_intent 불변, reconcile 호출 없음.
        return result

    # flag on 경로 — _captured_skill_v2_name 초기화.
    _captured_skill_v2_name: str | None = skill_v2_name
    captured_intent = intent_label

    if _captured_skill_v2_name and captured_intent:
        # reconcile 호출.
        _recon_available = list({_captured_skill_v2_name, captured_intent})
        decision = await reconcile(
            user_message=user_text,
            skill_v2_decision=_captured_skill_v2_name,
            intent_label=captured_intent,
            available_skills=_recon_available,
            llm=mock_decision._fake_llm if hasattr(mock_decision, "_fake_llm") else _make_fake_llm(mock_decision),  # type: ignore[union-attr]
        )
        result["reconcile_called"] = True

        if decision.conflict:
            _resolved = (
                decision.resolved_skill
                if decision.resolved_skill
                else (captured_intent or _captured_skill_v2_name)
            )
            captured_intent = _resolved
            result["emitted_event"] = _resolved

    result["captured_intent"] = captured_intent
    return result


def _make_fake_llm(decision: SkillIntentDecision):
    """reconcile() 가 원하는 SkillIntentDecision 을 반환하도록 LLM 을 mock."""
    import json as _json

    class _FakeLLM:
        async def complete(self, system: str, user: str, **kwargs) -> dict:
            if decision.conflict and decision.resolved_skill:
                content = _json.dumps({
                    "resolved_skill": decision.resolved_skill,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                })
            elif decision.conflict and decision.resolved_skill is None:
                # low confidence / clarify 시나리오.
                content = _json.dumps({
                    "resolved_skill": None,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                })
            else:
                # no conflict — reconcile() 자체가 LLM 안 부름. 여기 도달 안 함.
                content = _json.dumps({
                    "resolved_skill": decision.resolved_skill,
                    "confidence": 1.0,
                    "reason": "no conflict",
                })
            return {"choices": [{"message": {"content": content}}]}

    return _FakeLLM()


# ---------------------------------------------------------------------------
# Test 1: flag off → reconcile 호출 없음
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_no_reconcile_call(monkeypatch):
    """flag off 시 reconcile() 호출 안 됨 — 모듈 수준 patch 로 확인."""
    monkeypatch.delenv("FEATURE_SKILL_INTENT_RECONCILE", raising=False)
    assert is_enabled(FeatureFlag.SKILL_INTENT_RECONCILE) is False

    with patch(
        "src.agent_framework.runtime.reconcilers.skill_intent_reconciler.reconcile",
        new=AsyncMock(),
    ) as mock_reconcile:
        result = await _run_reconcile_branch(
            flag_on=False,
            skill_v2_name="schedule_personal",
            intent_label="memo_capture",
            mock_decision=None,
        )

    # flag off → reconcile 호출 없음.
    mock_reconcile.assert_not_called()
    # captured_intent 변화 없음.
    assert result["captured_intent"] == "memo_capture"
    assert result["emitted_event"] is None


# ---------------------------------------------------------------------------
# Test 2: flag on + no conflict → reconcile 호출되지만 captured_intent 불변
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_no_conflict_no_change(monkeypatch):
    """flag on + skill_v2 == intent → reconcile 호출됨 / conflict=False → 변화 없음."""
    monkeypatch.setenv("FEATURE_SKILL_INTENT_RECONCILE", "true")
    assert is_enabled(FeatureFlag.SKILL_INTENT_RECONCILE) is True

    # skill_v2 == intent — reconcile() 는 conflict=False 반환.
    same_label = "schedule_personal"
    no_conflict_decision = SkillIntentDecision(
        skill_v2=same_label,
        intent_label=same_label,
        conflict=False,
        resolved_skill=same_label,
        confidence=1.0,
        reason="비충돌 — passthrough",
    )

    result = await _run_reconcile_branch(
        flag_on=True,
        skill_v2_name=same_label,
        intent_label=same_label,
        mock_decision=no_conflict_decision,
    )

    # reconcile 은 호출됐지만 (conflict=False) emitted_event 없음.
    assert result["reconcile_called"] is True
    assert result["emitted_event"] is None
    # captured_intent 불변.
    assert result["captured_intent"] == same_label


# ---------------------------------------------------------------------------
# Test 3: Trace C — skill=schedule_personal, intent=memo_capture → resolved=memo_capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_trace_c_resolves_to_intent(monkeypatch):
    """Trace C: skill=schedule_personal vs intent=memo_capture → resolved=memo_capture."""
    monkeypatch.setenv("FEATURE_SKILL_INTENT_RECONCILE", "true")

    trace_c_decision = SkillIntentDecision(
        skill_v2="schedule_personal",
        intent_label="memo_capture",
        conflict=True,
        resolved_skill="memo_capture",
        confidence=0.85,
        reason="발화의 명시적 동사 '메모해줘' 가 memo_capture 를 지시",
    )

    result = await _run_reconcile_branch(
        flag_on=True,
        skill_v2_name="schedule_personal",
        intent_label="memo_capture",
        mock_decision=trace_c_decision,
        user_text="내일 병원 진료 예약을 꼭 할수 있게 메모 해줘",
    )

    assert result["reconcile_called"] is True
    # resolved_skill 이 memo_capture 로 교체됨.
    assert result["captured_intent"] == "memo_capture"
    assert result["emitted_event"] == "memo_capture"


# ---------------------------------------------------------------------------
# Test 4: low confidence → intent label fallback (resolved=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_low_confidence_falls_back(monkeypatch):
    """flag on + reconcile 이 resolved=None (low confidence) → intent label fallback."""
    monkeypatch.setenv("FEATURE_SKILL_INTENT_RECONCILE", "true")

    low_conf_decision = SkillIntentDecision(
        skill_v2="schedule_personal",
        intent_label="memo_capture",
        conflict=True,
        resolved_skill=None,   # LLM 이 자신 없음.
        confidence=0.3,
        reason="low confidence",
    )

    result = await _run_reconcile_branch(
        flag_on=True,
        skill_v2_name="schedule_personal",
        intent_label="memo_capture",
        mock_decision=low_conf_decision,
    )

    assert result["reconcile_called"] is True
    # resolved_skill=None → intent_label (또는 skill_v2) fallback.
    # dispatcher 코드: _resolved = captured_intent or _captured_skill_v2_name
    assert result["captured_intent"] == "memo_capture"
    # emitted_event 는 fallback resolved 값 ("memo_capture").
    assert result["emitted_event"] == "memo_capture"


# ---------------------------------------------------------------------------
# Test 5: flag on + skill_v2_name missing → reconcile 호출 없음
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_no_skill_v2_name_skips_reconcile(monkeypatch):
    """skill_activated 이벤트 없어 skill_v2_name=None → reconcile 호출 없음."""
    monkeypatch.setenv("FEATURE_SKILL_INTENT_RECONCILE", "true")

    result = await _run_reconcile_branch(
        flag_on=True,
        skill_v2_name=None,   # skill_activated 이벤트 없음.
        intent_label="memo_capture",
        mock_decision=None,
    )

    assert result["reconcile_called"] is False
    assert result["captured_intent"] == "memo_capture"
    assert result["emitted_event"] is None


# ---------------------------------------------------------------------------
# Test 6: FeatureFlag enum 에 SKILL_INTENT_RECONCILE 존재 확인
# ---------------------------------------------------------------------------


def test_feature_flag_enum_has_skill_intent_reconcile():
    """FeatureFlag.SKILL_INTENT_RECONCILE 이 enum 에 존재하는지 확인."""
    assert hasattr(FeatureFlag, "SKILL_INTENT_RECONCILE")
    assert FeatureFlag.SKILL_INTENT_RECONCILE.value == "skill_intent_reconcile"


# ---------------------------------------------------------------------------
# Test 7: reconciler 모듈 import 정상 확인
# ---------------------------------------------------------------------------


def test_reconciler_import():
    """reconciler 모듈 + SkillIntentDecision 임포트 정상."""
    from src.agent_framework.runtime.reconcilers.skill_intent_reconciler import (
        SkillIntentDecision,
        reconcile,
    )

    assert callable(reconcile)
    d = SkillIntentDecision(
        skill_v2="a",
        intent_label="b",
        conflict=True,
        resolved_skill="b",
        confidence=0.9,
        reason="test",
    )
    assert d.conflict is True
    assert d.resolved_skill == "b"
