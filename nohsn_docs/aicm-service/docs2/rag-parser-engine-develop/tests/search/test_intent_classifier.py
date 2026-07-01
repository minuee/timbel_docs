"""Legacy Intent Gate 회귀 테스트.

프롬프트 문자열에 개인 KMS 규칙이 포함되어 있는지 + 대표적 query 에 대한
기대 분류를 고정. 실제 LLM 호출 없이 AsyncMock.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.search.intent_classifier import (
    _BASE_SYSTEM_PROMPT,
    _build_system_prompt,
    classify_intent,
)


def test_system_prompt_contains_personal_kms_rules():
    """2026-04-23 user 피드백 회귀 — 개인 문서·지인/가족·일정·일기 검색 포함 규칙."""
    assert "개인 문서" in _BASE_SYSTEM_PROMPT
    assert "지인" in _BASE_SYSTEM_PROMPT or "친구" in _BASE_SYSTEM_PROMPT
    assert "search=true" in _BASE_SYSTEM_PROMPT
    assert "내" in _BASE_SYSTEM_PROMPT  # 개인 소유 표현


def test_domain_description_still_appended():
    """기존 도메인 설명 appending 로직이 깨지지 않는지 확인."""
    sp = _build_system_prompt("피부과 예약 및 시술 안내")
    assert "피부과" in sp
    assert "개인 문서" in sp  # base 규칙도 유지
    assert "현재 시각:" in sp  # Task 25-A — time prefix 주입


def test_domain_description_none():
    """도메인 설명 없을 때도 base 프롬프트가 time prefix 와 함께 반환."""
    sp = _build_system_prompt(None)
    # Task 25-A — now_prefix() 가 앞에 붙고, 그 뒤에 _BASE_SYSTEM_PROMPT 그대로.
    assert sp.endswith(_BASE_SYSTEM_PROMPT)
    assert "현재 시각:" in sp


@pytest.mark.asyncio
async def test_classify_personal_query_returns_search_true():
    """'철수 생일 언제?' 같은 개인 사실 질의는 Mock LLM 이 search=true 반환하면 그대로 통과.

    프롬프트 변경이 파싱/캐시/재시도 로직을 깨지 않는지 확인용 end-to-end.
    """
    mock_resp = type(
        "R",
        (),
        {
            "text": json.dumps(
                {"search": True, "reason": "개인 지인 사실 질의"}, ensure_ascii=False
            ),
            "model": "gemma-4-31b",
        },
    )()

    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(return_value=mock_resp)
        # 캐시 회피: Redis 캐시 mock
        with patch(
            "src.search.intent_classifier._get_intent_cache",
            AsyncMock(return_value=None),
        ), patch(
            "src.search.intent_classifier._set_intent_cache", AsyncMock()
        ):
            result = await classify_intent("철수 생일 언제?")

    assert result.search is True
    assert "개인" in result.reason or "지인" in result.reason


@pytest.mark.asyncio
async def test_classify_casual_emotional_returns_search_false():
    """감정 호소 ('오늘 잠이 안 와') 는 여전히 search=false 유지."""
    mock_resp = type(
        "R",
        (),
        {
            "text": json.dumps(
                {"search": False, "reason": "감정 호소 잡담"}, ensure_ascii=False
            ),
            "model": "gemma-4-31b",
        },
    )()

    with patch("src.common.llm.router.llm_router") as mock_router:
        mock_router.route = AsyncMock(return_value=mock_resp)
        with patch(
            "src.search.intent_classifier._get_intent_cache",
            AsyncMock(return_value=None),
        ), patch(
            "src.search.intent_classifier._set_intent_cache", AsyncMock()
        ):
            result = await classify_intent("오늘 잠이 안 와")

    assert result.search is False
