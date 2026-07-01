"""SynonymNormalizer 단위 테스트.

LLM 은 AsyncMock — rule/regex 미사용 검증을 위해 LLM JSON 응답 → 파싱
경로만 확인. 도메인 특화 정답 매핑은 prompt 가 책임지므로 본 테스트 범위 X.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.search.synonym_normalizer import (
    ConflictReport,
    SynonymNormalizer,
    SynonymResult,
)


def _llm(payload: dict | str) -> AsyncMock:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return AsyncMock(return_value=text)


@pytest.mark.asyncio
async def test_abbreviation_to_full_name():
    """KYC → 본인확인 같은 약어 ↔ 풀네임 정규화 — LLM 응답 그대로 통과."""
    mock = _llm(
        {
            "canonical": "본인확인",
            "variants": ["KYC", "Know Your Customer", "고객확인"],
            "domain": "finance",
        }
    )
    norm = SynonymNormalizer(llm_client=mock)
    res = await norm.normalize(query="KYC")

    assert isinstance(res, SynonymResult)
    assert res.canonical == "본인확인"
    assert "KYC" in res.variants
    assert res.domain == "finance"


@pytest.mark.asyncio
async def test_variant_to_canonical():
    """T+3 → 결제일 정규화. LLM 이 같은 의미 변형들을 variants 에 모음."""
    mock = _llm(
        {
            "canonical": "결제일",
            "variants": ["T+3", "정산일", "settlement date"],
            "domain": "finance",
        }
    )
    norm = SynonymNormalizer(llm_client=mock)
    res = await norm.normalize(query="T+3", domain_hint="finance")

    assert res.canonical == "결제일"
    assert "T+3" in res.variants
    assert "정산일" in res.variants


@pytest.mark.asyncio
async def test_domain_hint_passed_to_prompt():
    """domain_hint 가 LLM 호출 prompt 에 실려서 전달되는지 확인."""
    mock = _llm(
        {"canonical": "결제", "variants": [], "domain": "finance"}
    )
    norm = SynonymNormalizer(llm_client=mock)
    await norm.normalize(query="settlement", domain_hint="finance")

    # mock 이 호출된 prompt 안에 domain_hint 가 포함됐는지
    call_args = mock.call_args
    prompt_arg = call_args[0][0] if call_args[0] else call_args[1]["prompt"]
    assert "finance" in prompt_arg
    assert "settlement" in prompt_arg


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_llm_call():
    """같은 (query, domain) 으로 두 번 호출 → 두 번째는 캐시에서 반환."""
    mock = _llm(
        {"canonical": "결제일", "variants": ["T+3"], "domain": "finance"}
    )
    norm = SynonymNormalizer(llm_client=mock, cache_size=10)
    r1 = await norm.normalize(query="T+3", domain_hint="finance")
    r2 = await norm.normalize(query="T+3", domain_hint="finance")

    assert r1 == r2
    # mock 한 번만 호출
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_detect_conflicts_finds_t3_vs_t2():
    """T+3 vs T+2 같은 숫자 모순을 LLM 이 감지해 conflict 반환."""
    mock = _llm(
        {
            "has_conflict": True,
            "conflicts": [
                {
                    "term_a": "T+3",
                    "term_b": "T+2",
                    "reason": "결제 영업일 수 불일치",
                }
            ],
        }
    )
    norm = SynonymNormalizer(llm_client=mock)
    rep = await norm.detect_conflicts(
        doc_a_text="결제일은 T+3 입니다.",
        doc_b_text="결제일은 T+2 입니다.",
    )

    assert isinstance(rep, ConflictReport)
    assert rep.has_conflict is True
    assert len(rep.conflicts) == 1
    assert rep.conflicts[0]["term_a"] == "T+3"
    assert rep.conflicts[0]["term_b"] == "T+2"
    assert "불일치" in rep.conflicts[0]["reason"]


@pytest.mark.asyncio
async def test_normalize_empty_query():
    """빈 쿼리 → LLM 호출 없이 빈 결과."""
    mock = AsyncMock()
    norm = SynonymNormalizer(llm_client=mock)
    res = await norm.normalize(query="")
    assert res.canonical == ""
    assert res.variants == ()
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_returns_safe_fallback():
    """LLM 호출이 예외 던지면 query 자체를 canonical 로 fallback."""
    failing_mock = AsyncMock(side_effect=RuntimeError("LLM down"))
    norm = SynonymNormalizer(llm_client=failing_mock)
    res = await norm.normalize(query="알수없는용어")
    assert res.canonical == "알수없는용어"
    assert res.variants == ()
    assert res.domain == "general"


@pytest.mark.asyncio
async def test_malformed_json_falls_back():
    """LLM 이 JSON 이 아닌 응답 반환해도 fallback."""
    mock = _llm("이건 JSON 이 아닙니다")
    norm = SynonymNormalizer(llm_client=mock)
    res = await norm.normalize(query="결제일")
    assert res.canonical == "결제일"
    assert res.variants == ()
