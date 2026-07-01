"""QAPairExtractor 단위 테스트.

LLM 은 AsyncMock 으로 — 실 호출 없음.
rule/regex 미사용 확인을 위해 본문/추출 결과의 직접 매칭 검증보다는
"LLM 이 반환한 JSON 을 신뢰성 있게 파싱하고 신뢰도/상한을 적용한다" 에 초점.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.pipeline.extractors.qa_pair_extractor import QAPair, QAPairExtractor


def _llm_returning(payload: dict | str) -> AsyncMock:
    """payload 를 그대로 (또는 JSON 직렬화해서) 반환하는 mock LLM callable."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return AsyncMock(return_value=text)


@pytest.mark.asyncio
async def test_explicit_qa_format_extracted():
    """명시적 Q:/A: 마커가 있는 본문 → 1쌍 추출."""
    mock_llm = _llm_returning(
        {
            "pairs": [
                {
                    "question": "결제일은 언제인가요?",
                    "answer": "매매 후 3영업일째 되는 날입니다.",
                    "confidence": 0.95,
                }
            ]
        }
    )
    extractor = QAPairExtractor(llm_client=mock_llm)
    result = await extractor.extract(text="Q: 결제일은 언제? A: 매매 후 3영업일째.", block_id="b1")

    assert len(result) == 1
    assert isinstance(result[0], QAPair)
    assert result[0].question == "결제일은 언제인가요?"
    assert "3영업일" in result[0].answer
    assert result[0].source_block_id == "b1"
    assert result[0].confidence == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_implicit_qa_flow_extracted():
    """본문 흐름상 질문-답 구조 (마커 없음) → LLM 이 추출하면 그대로 통과."""
    mock_llm = _llm_returning(
        {
            "pairs": [
                {
                    "question": "휴장일 다음날 결제는 어떻게 처리되나요?",
                    "answer": "다음 영업일로 이연됩니다.",
                    "confidence": 0.8,
                }
            ]
        }
    )
    extractor = QAPairExtractor(llm_client=mock_llm)
    text = (
        "휴장일이 결제일과 겹칠 경우 처리 방식이 궁금할 수 있습니다. "
        "이때는 다음 영업일로 이연되어 처리됩니다."
    )
    result = await extractor.extract(text=text)

    assert len(result) == 1
    assert "이연" in result[0].answer
    assert result[0].source_block_id is None


@pytest.mark.asyncio
async def test_variant_questions_merged_into_one():
    """변형 질문 ("결제일은?", "결제 시점이 궁금해요") 이 같은 의도면
    LLM 이 1개로 통합한다 — extractor 는 LLM 반환 그대로 신뢰."""
    mock_llm = _llm_returning(
        {
            "pairs": [
                {
                    "question": "결제일은 언제인가요?",
                    "answer": "매매 후 3영업일째 되는 날입니다.",
                    "confidence": 0.9,
                }
            ]
        }
    )
    extractor = QAPairExtractor(llm_client=mock_llm)
    text = "결제일은? 결제는 언제 됩니까? 결제 시점이 궁금해요. → 모두 매매 후 3영업일째."
    result = await extractor.extract(text=text)

    # 3개 변형이 1개로 통합되어야 함 — 프롬프트가 LLM 에 위임한 책임
    assert len(result) == 1


@pytest.mark.asyncio
async def test_low_confidence_when_unclear():
    """본문이 단순 설명/목록이면 LLM 이 빈 리스트 또는 낮은 confidence 반환.
    min_confidence 필터로 제외 가능."""
    mock_llm = _llm_returning(
        {
            "pairs": [
                {
                    "question": "이 표는 무엇인가요?",
                    "answer": "(불확실)",
                    "confidence": 0.2,
                }
            ]
        }
    )
    extractor = QAPairExtractor(llm_client=mock_llm, min_confidence=0.5)
    result = await extractor.extract(text="단순 통계 표 본문...")
    assert result == []


@pytest.mark.asyncio
async def test_empty_text_returns_empty():
    """빈 본문은 LLM 호출조차 안 함."""
    mock_llm = AsyncMock()
    extractor = QAPairExtractor(llm_client=mock_llm)
    assert await extractor.extract(text="") == []
    assert await extractor.extract(text="   \n\t  ") == []
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_json_fence_envelope_stripped():
    """```json ...``` 펜스가 들어와도 파싱 성공."""
    fenced = "```json\n" + json.dumps(
        {"pairs": [{"question": "Q1", "answer": "A1", "confidence": 0.7}]},
        ensure_ascii=False,
    ) + "\n```"
    mock_llm = _llm_returning(fenced)
    extractor = QAPairExtractor(llm_client=mock_llm)
    result = await extractor.extract(text="본문")
    assert len(result) == 1
    assert result[0].question == "Q1"


@pytest.mark.asyncio
async def test_malformed_json_returns_empty():
    """LLM 이 잘못된 JSON 반환해도 빈 리스트 (예외 안 던짐)."""
    mock_llm = _llm_returning("not a json at all")
    extractor = QAPairExtractor(llm_client=mock_llm)
    assert await extractor.extract(text="본문") == []


@pytest.mark.asyncio
async def test_max_pairs_cap_applied():
    """LLM 이 폭주해서 100개 반환해도 max_pairs 로 cap."""
    mock_llm = _llm_returning(
        {
            "pairs": [
                {"question": f"Q{i}", "answer": f"A{i}", "confidence": 0.9}
                for i in range(50)
            ]
        }
    )
    extractor = QAPairExtractor(llm_client=mock_llm, max_pairs=5)
    result = await extractor.extract(text="본문")
    assert len(result) == 5
