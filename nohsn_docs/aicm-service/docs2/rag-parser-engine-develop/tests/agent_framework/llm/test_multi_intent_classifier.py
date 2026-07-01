from unittest.mock import AsyncMock

import pytest

from src.agent_framework.llm.intent_classifier import MultiLabelIntentClassifier


@pytest.mark.asyncio
async def test_classifier_returns_matching_labels():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": ["book_appointment"]}')
    clf = MultiLabelIntentClassifier(
        llm_client=llm,
        labels=["book_appointment", "ask_treatment", "ask_hours"],
    )
    got = await clf.classify_multi("다음 주 월요일 레이저 예약하고 싶어요", history=[])
    assert got == ["book_appointment"]


@pytest.mark.asyncio
async def test_classifier_returns_empty_on_no_match():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": []}')
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["book_appointment"])
    got = await clf.classify_multi("날씨 좋네요", history=[])
    assert got == []


@pytest.mark.asyncio
async def test_classifier_filters_hallucinated_labels():
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"intents": ["book_appointment", "hallucinated_label"]}'
    )
    clf = MultiLabelIntentClassifier(
        llm_client=llm, labels=["book_appointment", "ask_treatment"]
    )
    got = await clf.classify_multi("예약", history=[])
    # 할루시네이션 라벨 제거
    assert got == ["book_appointment"]


@pytest.mark.asyncio
async def test_classifier_handles_bad_json_gracefully():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="this is not json")
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["book_appointment"])
    got = await clf.classify_multi("x", history=[])
    # bad JSON → empty list (fail-safe)
    assert got == []


# --- Stage B-Core-2: 가변 labels + unsupported sentinel ---


@pytest.mark.asyncio
async def test_classifier_uses_per_call_override_when_provided():
    """call-time available_labels 가 constructor labels 를 덮어씀."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": ["X"]}')
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["A", "B"])
    got = await clf.classify_multi(
        "무언가 요청", history=[], available_labels=["X", "Y"]
    )
    assert got == ["X"]


@pytest.mark.asyncio
async def test_classifier_returns_no_skills_sentinel_when_available_labels_empty():
    """available_labels=[] → LLM 호출 없이 즉시 _no_skills_available 반환."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": []}')
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["A"])
    got = await clf.classify_multi("아무거나", history=[], available_labels=[])
    assert got == ["_no_skills_available"]
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_classifier_returns_unsupported_when_llm_says_so():
    """LLM 이 'unsupported' 를 반환하면 candidate 에 없어도 통과."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": ["unsupported"]}')
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["ask_hours"])
    got = await clf.classify_multi("예약해줘", history=[])
    assert got == ["unsupported"]


@pytest.mark.asyncio
async def test_classifier_filters_unknown_labels_but_allows_unsupported():
    """할루시네이션은 제거하되 'unsupported' 는 항상 통과 (원래 순서 유지)."""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"intents": ["A", "B_hallucinated", "unsupported"]}'
    )
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["A"])
    got = await clf.classify_multi("x", history=[])
    assert got == ["A", "unsupported"]


@pytest.mark.asyncio
async def test_classifier_legacy_call_uses_constructor_labels():
    """available_labels 미지정 → self.labels 를 candidate 로 사용."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": ["A"]}')
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["A"])
    got = await clf.classify_multi("안녕 A", history=[])
    assert got == ["A"]
    # user prompt (2번째 인자) 에 "A" 가 포함되어야 함 (self.labels fallback 증명)
    assert llm.complete.call_args is not None
    args, kwargs = llm.complete.call_args
    # user prompt: positional[1] 또는 kwargs["user"]
    user_prompt = args[1] if len(args) >= 2 else kwargs.get("user", "")
    assert "A" in user_prompt


@pytest.mark.asyncio
async def test_classifier_empty_constructor_labels_and_no_override_returns_empty():
    """labels=[] + available_labels 미지정 → [] (sentinel 아님, 레거시 조용 모드)."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": []}')
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=[])
    got = await clf.classify_multi("아무거나", history=[])
    assert got == []


@pytest.mark.asyncio
async def test_classifier_returns_capability_query_sentinel():
    """LLM 이 '_capability_query' 를 반환하면 candidate 밖이어도 통과."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"intents": ["_capability_query"]}')
    clf = MultiLabelIntentClassifier(
        llm_client=llm, labels=["create_schedule", "log_diary"]
    )
    got = await clf.classify_multi("뭐 할 수 있어?", history=[])
    assert got == ["_capability_query"]


@pytest.mark.asyncio
async def test_classifier_capability_sentinel_passes_through_filter():
    """candidate 밖 라벨은 제거하되 _capability_query / unsupported 는 유지."""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"intents": ["hallucinated", "_capability_query"]}'
    )
    clf = MultiLabelIntentClassifier(llm_client=llm, labels=["create_schedule"])
    got = await clf.classify_multi("기능 뭐 있어?", history=[])
    assert got == ["_capability_query"]


@pytest.mark.asyncio
async def test_classifier_returns_skill_draft_request_sentinel():
    """Task 34-36: 사용자가 '이런 기능 만들어 줘' 요청 → _skill_draft_request sentinel.

    candidate 라벨에 없어도 통과해야 함 (passthrough).
    """
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"intents": ["_skill_draft_request"]}'
    )
    clf = MultiLabelIntentClassifier(
        llm_client=llm, labels=["create_schedule", "log_diary"]
    )
    got = await clf.classify_multi(
        "이런 기능 자동으로 해주는 거 만들어 줄 수 있어?", history=[]
    )
    assert got == ["_skill_draft_request"]
