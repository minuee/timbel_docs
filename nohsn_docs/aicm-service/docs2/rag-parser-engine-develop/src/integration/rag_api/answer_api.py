"""외부 RAG 답변 API — POST /api/v1/ext/ask."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.common.llm.base import LLMRequest, LLMTask
from src.common.llm.router import llm_router
from src.common.logging import get_logger
from src.integration.api_gateway.auth import verify_api_key
from src.integration.api_gateway.models import APIKeyRecord
from src.integration.api_gateway.response_cache import ResponseCache
from src.integration.metrics import EXTERNAL_API_DURATION_SECONDS, EXTERNAL_API_REQUESTS_TOTAL
from src.integration.rag_api.history import enrich_with_history
from src.integration.rag_api.models import (
    ExternalAskRequest,
    ExternalAskResponse,
    ExternalSearchRequest,
    SearchResultItem,
    SourceInfo,
)

log = get_logger(__name__)

router = APIRouter()

# 신뢰도 임계값 (이 이하면 fallback 응답)
CONFIDENCE_THRESHOLD = 0.3

# RAG 프롬프트 템플릿
RAG_SYSTEM_PROMPT = """당신은 AICM 지식관리 플랫폼의 AI 어시스턴트입니다.
아래 제공된 검색 결과를 바탕으로 사용자의 질문에 정확하고 유용하게 답변하세요.

규칙:
1. 검색 결과에 없는 내용을 임의로 생성하지 마세요.
2. 답변의 근거가 되는 문서를 언급하세요.
3. 정보가 불충분하면 솔직하게 알려주세요.
4. 간결하고 명확하게 답변하세요."""

RAG_USER_PROMPT_TEMPLATE = """## 검색 결과

{context}

## 질문

{question}

위 검색 결과를 바탕으로 질문에 답변해 주세요."""

FALLBACK_ANSWER = "해당 내용에 대한 정보를 찾을 수 없습니다. 다른 키워드로 검색하거나 질문을 구체적으로 해 주세요."

# ResponseCache는 search_api 모듈에서 공유
_response_cache: ResponseCache | None = None


def set_response_cache(cache: ResponseCache) -> None:
    """앱 startup에서 ResponseCache 인스턴스를 주입한다."""
    global _response_cache
    _response_cache = cache


@router.post(
    "/ext/ask",
    response_model=ExternalAskResponse,
    summary="외부 시스템용 RAG 답변",
)
async def external_ask(
    request: ExternalAskRequest,
    api_key: APIKeyRecord = Depends(verify_api_key("ask")),
) -> Response | ExternalAskResponse:
    """외부 시스템용 RAG 답변 API.

    response_mode:
    - "answer": 검색 + LLM 답변 생성 + 출처 반환
    - "context": 검색 + RAG 컨텍스트만 반환 (호출측이 자체 LLM 사용)

    멀티턴 대화를 지원하며, 검색 결과가 없거나 신뢰도가 낮으면 fallback 응답을 반환한다.
    """
    if request.response_mode not in ("answer", "context"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="response_mode는 'answer' 또는 'context' 이어야 합니다.",
        )

    start_time = time.time()
    endpoint = "/ext/ask"
    request_body = request.model_dump_json()
    request_dict = request.model_dump()

    EXTERNAL_API_REQUESTS_TOTAL.labels(endpoint=endpoint, api_key_name=api_key.name).inc()

    log.info(
        "external_ask_start",
        tenant_id=str(api_key.tenant_id),
        key_id=str(api_key.id),
        question_len=len(request.question),
        response_mode=request.response_mode,
        history_turns=len(request.conversation_history),
    )

    # 캐시 조회 (context 모드에서만, answer 모드는 LLM 비결정성으로 스킵)
    if _response_cache and not ResponseCache.should_skip(request_dict, endpoint):
        cached = await _response_cache.get(api_key.id, endpoint, request_body)
        if cached:
            EXTERNAL_API_DURATION_SECONDS.labels(endpoint=endpoint).observe(
                time.time() - start_time
            )
            return Response(
                content=cached.body,
                media_type="application/json",
                headers={
                    "X-Cache-Hit": "true",
                    "X-Cache-TTL": str(cached.ttl_remaining),
                },
            )

    # 1. 대화 히스토리 기반 질의 보강
    enriched_query = enrich_with_history(
        question=request.question,
        conversation_history=request.conversation_history,
    )

    # 2. 검색 실행
    search_request = ExternalSearchRequest(
        query=enriched_query,
        repository_id=request.repository_id,
        category_ids=request.category_ids,
        top_k=5,
        search_mode="hybrid",
        rerank=True,
    )
    search_results = await _execute_search_for_ask(search_request, tenant_id=api_key.tenant_id)

    # 3. 검색 결과 없거나 신뢰도 낮으면 fallback
    if not search_results or search_results[0].score < CONFIDENCE_THRESHOLD:
        log.info(
            "external_ask_fallback",
            reason="no_results" if not search_results else "low_confidence",
            top_score=search_results[0].score if search_results else 0.0,
        )
        return ExternalAskResponse(
            answer=FALLBACK_ANSWER if request.response_mode == "answer" else None,
            context="" if request.response_mode == "context" else None,
            sources=[],
            confidence=search_results[0].score if search_results else 0.0,
        )

    # 4. RAG 컨텍스트 조립
    context_text = _build_context(search_results, request.max_context_tokens)
    sources = _extract_sources(search_results)
    confidence = search_results[0].score

    # 5-a. context 모드: 컨텍스트만 반환
    if request.response_mode == "context":
        elapsed_ms = int((time.time() - start_time) * 1000)
        log.info("external_ask_context_mode", latency_ms=elapsed_ms, sources=len(sources))
        resp = ExternalAskResponse(
            context=context_text,
            sources=sources,
            confidence=confidence,
        )
        # 캐시 저장 (context 모드만)
        if _response_cache and not ResponseCache.should_skip(request_dict, endpoint):
            await _response_cache.put(
                api_key_id=api_key.id,
                endpoint=endpoint,
                request_body=request_body,
                response_body=resp.model_dump_json(),
                repository_id=request.repository_id,
            )
        EXTERNAL_API_DURATION_SECONDS.labels(endpoint=endpoint).observe(
            time.time() - start_time
        )
        return resp

    # 5-b. answer 모드: LLM 답변 생성
    prompt = RAG_USER_PROMPT_TEMPLATE.format(
        context=context_text,
        question=request.question,
    )

    try:
        llm_response = await llm_router.route(
            task=LLMTask.RAG_GENERATION,
            request=LLMRequest(
                prompt=prompt,
                system_prompt=RAG_SYSTEM_PROMPT,
                max_tokens=500,
                temperature=0.3,
            ),
        )
        answer = llm_response.text
        model_used = llm_response.model
    except Exception as e:
        log.error("llm_generation_failed", error=str(e))
        answer = (
            "답변 생성 중 오류가 발생했습니다. "
            "검색 결과를 직접 참고해 주세요."
        )
        model_used = None

    elapsed_ms = int((time.time() - start_time) * 1000)

    EXTERNAL_API_DURATION_SECONDS.labels(endpoint=endpoint).observe(
        time.time() - start_time
    )

    log.info(
        "external_ask_complete",
        tenant_id=str(api_key.tenant_id),
        response_mode=request.response_mode,
        latency_ms=elapsed_ms,
        sources=len(sources),
        model_used=model_used,
    )

    return ExternalAskResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
        model_used=model_used,
    )


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _build_context(
    results: list[SearchResultItem],
    max_tokens: int,
) -> str:
    """검색 결과를 RAG 컨텍스트 문자열로 조립.

    토큰 수를 대략적으로 제한한다 (1 token ~ 3 한글 글자).
    """
    max_chars = max_tokens * 3  # 한국어 근사
    parts: list[str] = []
    total_chars = 0

    for i, hit in enumerate(results, 1):
        entry = (
            f"[문서 {i}] {hit.document_title}"
            + (f" > {hit.section_title}" if hit.section_title else "")
            + f" (신뢰도: {hit.score:.2f})\n{hit.content}"
        )

        if total_chars + len(entry) > max_chars:
            # 남은 공간이 있으면 일부라도 포함
            remaining = max_chars - total_chars
            if remaining > 100:
                parts.append(entry[:remaining] + "...")
            break

        parts.append(entry)
        total_chars += len(entry)

    return "\n\n".join(parts)


def _extract_sources(results: list[SearchResultItem]) -> list[SourceInfo]:
    """검색 결과에서 출처 정보 추출."""
    return [
        SourceInfo(
            document_id=hit.document_id,
            document_title=hit.document_title,
            section_title=hit.section_title,
            score=hit.score,
            source_location=hit.source_location,
        )
        for hit in results
    ]


async def _execute_search_for_ask(
    request: ExternalSearchRequest,
    tenant_id: object = None,
) -> list[SearchResultItem]:
    """Ask API용 검색 실행. search_api와 동일한 로직을 재사용."""
    from src.integration.rag_api.search_api import _execute_search

    results, _, _ = await _execute_search(request, tenant_id=tenant_id)
    return results
