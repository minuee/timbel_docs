"""D40 Phase A — VLLMAdapter.generate() unit test + KC `_call_llm` 통합.

KnowledgeCompiler._call_llm 의 generic fallback 경로 (`hasattr(client,
"generate")`) 가 VLLMAdapter 와 호환되는지 검증.

배경: KC 는 AsyncOpenAI / OpenAI 인스턴스가 아니면 `client.generate(prompt)` 를
호출한다. VLLMAdapter 는 이 메서드가 없었기 때문에 KC 의 topic_tags / table_nl
/ search_summary 가 silently 실패 (RuntimeError) → topic_tags 0% 회귀.

이 테스트는 Phase A fix 가 그 결함을 차단함을 보장한다.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agent_framework.llm.vllm_adapter import VLLMAdapter


# ---------------------------------------------------------------------------
# A — .generate() 시그니처 + 반환 타입
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_text_only():
    """generate(prompt) 가 단순 str 을 반환 (KC `_call_llm` 호환)."""
    fake_resp = type(
        "LLMResponse",
        (),
        {
            "text": "토픽: 체결",
            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        },
    )()
    adapter = VLLMAdapter()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        result = await adapter.generate("KRX 체결 원칙 요약해줘")
    assert isinstance(result, str)
    assert result == "토픽: 체결"


@pytest.mark.asyncio
async def test_generate_uses_default_system_prompt():
    """system 미지정 시 기본 system prompt 가 주입된다."""
    fake_resp = type(
        "LLMResponse",
        (),
        {"text": "ok", "usage": {}},
    )()
    adapter = VLLMAdapter()
    captured = {}

    async def _capture_route(*, task, request):
        captured["system_prompt"] = request.system_prompt
        captured["prompt"] = request.prompt
        return fake_resp

    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(side_effect=_capture_route)
        await adapter.generate("hello")

    assert "Korean AI" in captured["system_prompt"]
    assert captured["prompt"] == "hello"


@pytest.mark.asyncio
async def test_generate_with_custom_system_prompt():
    """system 인자로 override 가능."""
    fake_resp = type("LLMResponse", (), {"text": "ok", "usage": {}})()
    adapter = VLLMAdapter()
    captured = {}

    async def _capture_route(*, task, request):
        captured["system_prompt"] = request.system_prompt
        return fake_resp

    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(side_effect=_capture_route)
        await adapter.generate("p", system="CUSTOM SYSTEM")

    assert captured["system_prompt"] == "CUSTOM SYSTEM"


# ---------------------------------------------------------------------------
# B — KnowledgeCompiler `_call_llm` 통합
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kc_call_llm_uses_vllm_adapter_generate():
    """KC `_call_llm` 의 generic fallback 이 VLLMAdapter.generate 를 사용한다.

    이 테스트는 fix 의 핵심 — Phase A 이전엔 `hasattr(adapter, "generate")` 가
    False 였기에 RuntimeError 가 났다.
    """
    from src.pipeline.enrichers.knowledge_compiler import KnowledgeCompiler
    from src.pipeline.models.document import ProcessingConfig

    adapter = VLLMAdapter()
    assert hasattr(adapter, "generate"), "VLLMAdapter must expose .generate() for KC compat"

    config = ProcessingConfig()
    kc = KnowledgeCompiler(config, llm_client=adapter)

    fake_resp = type(
        "LLMResponse",
        (),
        {"text": "체결, 우선순위, 호가", "usage": {}},
    )()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        # KC 의 generic fallback 경로 (`hasattr(client, "generate")`) 진입.
        # openai import 는 성공하지만 isinstance 체크 둘 다 False → fallthrough.
        result = await kc._call_llm("토픽 태그를 추출해줘")

    assert isinstance(result, str)
    assert "체결" in result


# ---------------------------------------------------------------------------
# C — 다른 enricher들도 VLLMAdapter `.generate()` 사용 (D40 Phase A 확장)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_extractor_call_llm_uses_generate():
    """MultilayerKeywordExtractor `_call_llm` 가 VLLMAdapter `.generate()` 사용 — topic_tags 핵심."""
    from src.pipeline.enrichers.metadata_extractor import MultilayerKeywordExtractor

    adapter = VLLMAdapter()
    extractor = MultilayerKeywordExtractor(llm_client=adapter)

    fake_resp = type(
        "LLMResponse",
        (),
        {
            "text": '{"query_keywords":["체결"],"synonyms":["매매"],"topic_tags":["체결"]}',
            "usage": {},
        },
    )()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        result = await extractor._call_llm("KRX 본문")

    assert isinstance(result, dict)
    assert "체결" in result.get("topic_tags", [])


@pytest.mark.asyncio
async def test_self_verifier_call_llm_uses_generate():
    """SelfVerifier `_call_llm` 가 VLLMAdapter `.generate()` 사용."""
    from src.pipeline.enrichers.self_verifier import SelfVerifier

    adapter = VLLMAdapter()
    verifier = SelfVerifier(llm_client=adapter)

    fake_resp = type(
        "LLMResponse",
        (),
        {"text": '{"verified":true}', "usage": {}},
    )()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        result = await verifier._call_llm("verify this")

    assert isinstance(result, str)
    assert "verified" in result


@pytest.mark.asyncio
async def test_ontology_classifier_call_llm_uses_generate():
    """OntologyClassifier `_call_llm` 가 VLLMAdapter `.generate()` 사용."""
    from src.pipeline.enrichers.ontology_classifier import OntologyClassifier

    adapter = VLLMAdapter()
    classifier = OntologyClassifier(llm_client=adapter)

    fake_resp = type(
        "LLMResponse",
        (),
        {"text": '{"category":"finance"}', "usage": {}},
    )()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        result = await classifier._call_llm("classify this")

    assert isinstance(result, str)
    assert "finance" in result


@pytest.mark.asyncio
async def test_search_summary_generator_call_llm_uses_generate():
    """SearchSummaryGenerator `_call_llm` 가 VLLMAdapter `.generate()` 사용."""
    from src.pipeline.enrichers.search_summary_generator import SearchSummaryGenerator

    adapter = VLLMAdapter()
    generator = SearchSummaryGenerator(llm_client=adapter)

    fake_resp = type(
        "LLMResponse",
        (),
        {"text": "요약문장입니다", "usage": {}},
    )()
    with patch("src.agent_framework.llm.vllm_adapter.llm_router") as mr:
        mr.route = AsyncMock(return_value=fake_resp)
        result = await generator._call_llm("summarize this")

    assert isinstance(result, str)
    assert "요약" in result
