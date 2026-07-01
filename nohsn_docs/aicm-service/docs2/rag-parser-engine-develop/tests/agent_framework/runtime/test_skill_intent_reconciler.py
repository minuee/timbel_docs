import pytest
from unittest.mock import AsyncMock
from src.agent_framework.runtime.reconcilers.skill_intent_reconciler import (
    reconcile,
    SkillIntentDecision,
)


@pytest.mark.asyncio
async def test_trace_c_memo_vs_schedule():
    """auto-loader=schedule_personal, intent=memo_capture, 발화는 메모 동사 명시.
    LLM 이 memo 를 선택하도록 mock."""
    fake_llm = AsyncMock()
    fake_llm.complete = AsyncMock(return_value={
        "choices": [{"message": {"content":
            '{"resolved_skill":"memo_capture","confidence":0.85,'
            '"reason":"발화 끝의 명시적 동사 메모해줘 가 dominant"}'
        }}],
    })
    decision = await reconcile(
        user_message="내일 병원 진료 예약을 꼭 할수 있게 메모 해줘",
        skill_v2_decision="schedule_personal",
        intent_label="memo_capture",
        available_skills=["schedule_personal", "memo_capture", "diary_save"],
        llm=fake_llm,
    )
    assert decision.conflict is True
    assert decision.resolved_skill == "memo_capture"
    assert decision.confidence >= 0.7


@pytest.mark.asyncio
async def test_no_conflict_passthrough():
    """양쪽이 동의 — LLM 호출 X."""
    fake_llm = AsyncMock()
    decision = await reconcile(
        user_message="내일 6시 약속",
        skill_v2_decision="schedule_personal",
        intent_label="schedule_personal",
        available_skills=["schedule_personal"],
        llm=fake_llm,
    )
    assert decision.conflict is False
    assert decision.resolved_skill == "schedule_personal"
    fake_llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_both_none():
    fake_llm = AsyncMock()
    decision = await reconcile(
        user_message="안녕",
        skill_v2_decision=None,
        intent_label=None,
        available_skills=[],
        llm=fake_llm,
    )
    assert decision.conflict is False
    assert decision.resolved_skill is None


@pytest.mark.asyncio
async def test_diary_vs_memo():
    fake_llm = AsyncMock()
    fake_llm.complete = AsyncMock(return_value={
        "choices": [{"message": {"content":
            '{"resolved_skill":"memo_capture","confidence":0.7,"reason":"메모 동사"}'
        }}],
    })
    decision = await reconcile(
        user_message="오늘 회의 내용 메모해줘",
        skill_v2_decision="diary_save",
        intent_label="memo_capture",
        available_skills=["memo_capture", "diary_save"],
        llm=fake_llm,
    )
    assert decision.conflict is True
    assert decision.resolved_skill == "memo_capture"


@pytest.mark.asyncio
async def test_low_confidence_returns_none_for_clarify():
    """LLM 이 자신 없으면 clarify 권장 (resolved_skill=None)."""
    fake_llm = AsyncMock()
    fake_llm.complete = AsyncMock(return_value={
        "choices": [{"message": {"content":
            '{"resolved_skill":null,"confidence":0.3,"reason":"양쪽 다 가능"}'
        }}],
    })
    decision = await reconcile(
        user_message="이거 처리해줘",
        skill_v2_decision="schedule_personal",
        intent_label="memo_capture",
        available_skills=["schedule_personal", "memo_capture"],
        llm=fake_llm,
    )
    assert decision.conflict is True
    assert decision.resolved_skill is None
    assert decision.confidence < 0.5


@pytest.mark.asyncio
async def test_llm_malformed_json_safe_fallback():
    """LLM 이 깨진 JSON 반환 시 — clarify 권장 + conflict 보존."""
    fake_llm = AsyncMock()
    fake_llm.complete = AsyncMock(return_value={
        "choices": [{"message": {"content": "이건 JSON 아니에요"}}],
    })
    decision = await reconcile(
        user_message="복잡한 발화",
        skill_v2_decision="schedule_personal",
        intent_label="memo_capture",
        available_skills=["schedule_personal", "memo_capture"],
        llm=fake_llm,
    )
    assert decision.conflict is True
    assert decision.resolved_skill is None
    assert "parse" in decision.reason.lower() or "fallback" in decision.reason.lower()


@pytest.mark.asyncio
async def test_llm_invents_unavailable_skill():
    """LLM 이 가용 skill 외 응답 시 — fallback to clarify."""
    fake_llm = AsyncMock()
    fake_llm.complete = AsyncMock(return_value={
        "choices": [{"message": {"content":
            '{"resolved_skill":"made_up_skill","confidence":0.9,"reason":"x"}'
        }}],
    })
    decision = await reconcile(
        user_message="x",
        skill_v2_decision="schedule_personal",
        intent_label="memo_capture",
        available_skills=["schedule_personal", "memo_capture"],
        llm=fake_llm,
    )
    assert decision.resolved_skill is None
    assert decision.confidence == 0.0


@pytest.mark.asyncio
async def test_llm_returns_array_not_dict():
    """LLM 이 JSON array 반환 — fallback to clarify."""
    fake_llm = AsyncMock()
    fake_llm.complete = AsyncMock(return_value={
        "choices": [{"message": {"content": "[1,2,3]"}}],
    })
    decision = await reconcile(
        user_message="x",
        skill_v2_decision="schedule_personal",
        intent_label="memo_capture",
        available_skills=["schedule_personal", "memo_capture"],
        llm=fake_llm,
    )
    assert decision.resolved_skill is None
    assert decision.confidence == 0.0


@pytest.mark.asyncio
async def test_llm_non_numeric_confidence():
    """LLM 이 confidence 를 문자열로 반환 — 0.0 폴백."""
    fake_llm = AsyncMock()
    fake_llm.complete = AsyncMock(return_value={
        "choices": [{"message": {"content":
            '{"resolved_skill":"memo_capture","confidence":"high","reason":"x"}'
        }}],
    })
    decision = await reconcile(
        user_message="x",
        skill_v2_decision="schedule_personal",
        intent_label="memo_capture",
        available_skills=["schedule_personal", "memo_capture"],
        llm=fake_llm,
    )
    # confidence parse 실패 → 0.0 → low confidence path → resolved=None
    assert decision.confidence == 0.0
    assert decision.resolved_skill is None
