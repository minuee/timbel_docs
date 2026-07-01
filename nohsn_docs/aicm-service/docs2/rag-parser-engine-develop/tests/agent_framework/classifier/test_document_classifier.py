"""DocumentClassifier 테스트 — Stage B-Core-4 (KMS-Plus).

스키마 정규화, fallback, 언어, list tags, confidence clamping 커버.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.agent_framework.classifier.document_classifier import DocumentClassifier


def _fake_llm(raw_json: str) -> AsyncMock:
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(return_value=raw_json)
    return llm


@pytest.mark.asyncio
async def test_classify_valid_korean_manual():
    """한국어 매뉴얼 초록 → 필드 정확 파싱, 스키마 7 키 모두 존재."""
    llm = _fake_llm(
        json.dumps(
            {
                "category_guess": "상담 매뉴얼",
                "domain": "customer_support",
                "tags": ["상담", "매뉴얼", "응대"],
                "suggested_repository_name": "상담 매뉴얼",
                "suggested_document_type": "manual",
                "confidence": 0.82,
                "rationale": "응대 절차와 고객 응답 스크립트가 기술되어 있다.",
            },
            ensure_ascii=False,
        )
    )
    clf = DocumentClassifier(llm)
    got = await clf.classify(
        title="고객센터 상담 매뉴얼 v3.2",
        text_sample="본 매뉴얼은 상담사가 따라야 할 응대 절차를 정의한다...",
    )
    assert got["category_guess"] == "상담 매뉴얼"
    assert got["domain"] == "customer_support"
    assert got["tags"] == ["상담", "매뉴얼", "응대"]
    assert got["suggested_document_type"] == "manual"
    assert got["confidence"] == pytest.approx(0.82)
    assert "응대" in got["rationale"]


@pytest.mark.asyncio
async def test_classify_english_title_valid():
    """영어 제목도 그대로 처리되고, domain enum 정규화 (대소문자 무시)."""
    llm = _fake_llm(
        json.dumps(
            {
                "category_guess": "API Reference",
                "domain": "SOFTWARE",  # uppercase — should normalize
                "tags": ["api", "reference"],
                "suggested_repository_name": "Engineering Docs",
                "suggested_document_type": "specification",
                "confidence": 0.9,
                "rationale": "기술 레퍼런스 포맷이다.",
            }
        )
    )
    clf = DocumentClassifier(llm)
    got = await clf.classify(
        title="Widget API Reference",
        text_sample="Endpoints: GET /widgets ...",
    )
    assert got["domain"] == "software"
    assert got["suggested_document_type"] == "specification"
    assert got["tags"] == ["api", "reference"]


@pytest.mark.asyncio
async def test_classify_malformed_returns_fallback():
    """JSON 파싱 실패 → fallback dict, confidence=0, rationale 표시."""
    llm = _fake_llm("이건 JSON 이 아닙니다.")
    clf = DocumentClassifier(llm)
    got = await clf.classify(title="broken", text_sample="...")
    assert got["confidence"] == 0.0
    assert got["domain"] == "general"
    assert got["suggested_document_type"] == "other"
    assert got["tags"] == []
    assert "파싱 실패" in got["rationale"]


@pytest.mark.asyncio
async def test_classify_llm_exception_returns_fallback():
    """LLM 호출 자체가 예외 → fallback dict."""
    llm = AsyncMock()
    llm.chat_completion_json = AsyncMock(side_effect=RuntimeError("vLLM down"))
    clf = DocumentClassifier(llm)
    got = await clf.classify(title="x", text_sample="y")
    assert got["confidence"] == 0.0
    assert got["rationale"] == "LLM 실패로 분류 생략"


@pytest.mark.asyncio
async def test_classify_tags_as_string_split():
    """tags 가 str 이면 split 되어 list 로 정규화."""
    llm = _fake_llm(
        json.dumps(
            {
                "category_guess": "계약서",
                "domain": "legal",
                "tags": "계약, 갑, 을",  # comma-separated string
                "suggested_document_type": "contract",
                "confidence": 1.5,  # over 1 — should clamp
                "rationale": "계약 조항 포맷.",
            },
            ensure_ascii=False,
        )
    )
    clf = DocumentClassifier(llm)
    got = await clf.classify(title="임대차 계약서", text_sample="제1조 ...")
    assert isinstance(got["tags"], list)
    assert "계약" in got["tags"]
    assert got["confidence"] == 1.0  # clamped


@pytest.mark.asyncio
async def test_classify_unknown_domain_falls_back_to_general():
    """허용 도메인 밖 값 → general 로 정규화."""
    llm = _fake_llm(
        json.dumps(
            {
                "category_guess": "사내 공지",
                "domain": "aerospace",  # not in enum
                "tags": ["공지"],
                "suggested_document_type": "wall_poster",  # not in enum
                "confidence": 0.4,
                "rationale": "공지 포맷.",
            },
            ensure_ascii=False,
        )
    )
    clf = DocumentClassifier(llm)
    got = await clf.classify(title="4월 공지", text_sample="...")
    assert got["domain"] == "general"
    assert got["suggested_document_type"] == "other"
