from unittest.mock import AsyncMock

import pytest

from src.agent_framework.llm.fallback_router import FallbackRouter


@pytest.mark.asyncio
async def test_fallback_chooses_next_state():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"next_state": "collect_date", "response": "언제로 예약해드릴까요?"}')
    router = FallbackRouter(llm_client=llm)

    got = await router.decide(
        current_state="greet",
        user_message="예약 좀 해줘",
        available_states=["greet", "collect_date", "collect_service"],
    )
    assert got.next_state == "collect_date"
    assert "언제" in got.response


@pytest.mark.asyncio
async def test_fallback_stay_in_place():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"next_state": "stay", "response": "다시 말씀해 주실래요?"}')
    router = FallbackRouter(llm_client=llm)

    got = await router.decide(
        current_state="greet",
        user_message="???",
        available_states=["greet", "collect_date"],
    )
    assert got.next_state == "stay"


@pytest.mark.asyncio
async def test_fallback_raises_on_bad_json():
    """Locks the 'propagate, don't catch' contract. Task 14 retry 변경 시 의도적 deviation 요구."""
    import json
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="not json at all")
    router = FallbackRouter(llm_client=llm)
    with pytest.raises(json.JSONDecodeError):
        await router.decide("greet", "x", ["greet"])


@pytest.mark.asyncio
async def test_fallback_rejects_hallucinated_state():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"next_state": "imaginary_state", "response": "xyz"}')
    router = FallbackRouter(llm_client=llm)
    got = await router.decide("greet", "msg", ["greet", "collect_date"])
    assert got.next_state == "stay"   # hallucinated → stay


@pytest.mark.asyncio
async def test_fallback_system_prompt_contains_no_action_promise_rule():
    """시스템 프롬프트에 행동 약속 금지 규칙이 포함되어야 함.

    회귀 방지 — 프롬프트 엔지니어링 변경 시 이 규칙이 의도적으로 제거되지 않는지 감시.
    """
    from src.agent_framework.llm.fallback_router import _SYSTEM
    assert "행동 약속 금지" in _SYSTEM
    assert "모르는 정보 생성 금지" in _SYSTEM
    assert "현재 단계 재확인" in _SYSTEM


@pytest.mark.asyncio
async def test_fallback_redirects_offtopic_to_current_step(monkeypatch):
    """off-topic 질문 시 current state 의 요청 정보로 되돌리는 응답 생성 검증.

    실제 LLM 호출 없이 Mock 이 '날짜 먼저' 응답 반환하는지 assertion.
    """
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"next_state": "stay", "response": "예약 날짜를 먼저 알려주세요. 방문하실 날짜가 언제인가요?"}')

    router = FallbackRouter(llm_client=llm)
    got = await router.decide(
        current_state="collect_date",
        user_message="선생님이 누구누구 있어?",
        available_states=["greet", "collect_date", "collect_service"],
    )
    assert got.next_state == "stay"
    # 응답에 행동 약속 키워드가 없어야 함
    forbidden = ["안내해 드릴게요", "기다려 주세요", "조회해 볼게요", "확인해 드릴게요", "처리해 드릴게요"]
    for phrase in forbidden:
        assert phrase not in got.response, f"금지된 약속 문구 '{phrase}' 감지됨"
