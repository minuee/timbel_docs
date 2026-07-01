"""SSE 스트리밍 RAG 답변 API — POST /api/v1/ext/ask/stream."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from src.common.llm.base import LLMRequest, LLMTask
from src.common.llm.router import llm_router
from src.common.logging import get_logger
from src.integration.api_gateway.auth import verify_api_key
from src.integration.api_gateway.models import APIKeyRecord
from src.integration.rag_api.answer_api import (
    CONFIDENCE_THRESHOLD,
    FALLBACK_ANSWER,
    RAG_SYSTEM_PROMPT,
    RAG_USER_PROMPT_TEMPLATE,
    _build_context,
    _execute_search_for_ask,
    _extract_sources,
)
from src.integration.rag_api.history import enrich_with_history
from src.integration.rag_api.models import (
    ExternalAskRequest,
    ExternalSearchRequest,
    SourceInfo,
)

log = get_logger(__name__)

router = APIRouter()


def _sse_event(data: dict) -> str:
    """SSE 형식의 이벤트 문자열 생성."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_ask(
    request: ExternalAskRequest,
    api_key: APIKeyRecord,
) -> AsyncIterator[str]:
    """검색 → RAG 컨텍스트 → LLM 스트리밍 응답을 SSE 이벤트로 생성."""
    start_time = time.time()

    try:
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
        search_results = await _execute_search_for_ask(
            search_request, tenant_id=api_key.tenant_id
        )

        # 3. 검색 완료 이벤트 + 출처 정보 전송
        sources = _extract_sources(search_results) if search_results else []
        sources_data = [s.model_dump(mode="json") for s in sources]
        yield _sse_event({
            "type": "search_complete",
            "sources": sources_data,
        })

        # 4. 검색 결과 없거나 신뢰도 낮으면 fallback
        if not search_results or search_results[0].score < CONFIDENCE_THRESHOLD:
            yield _sse_event({"type": "token", "text": FALLBACK_ANSWER})
            yield _sse_event({"type": "done"})
            return

        # 5. RAG 컨텍스트 조립
        context_text = _build_context(search_results, request.max_context_tokens)

        # 6. LLM 스트리밍 답변 생성
        prompt = RAG_USER_PROMPT_TEMPLATE.format(
            context=context_text,
            question=request.question,
        )

        llm_request = LLMRequest(
            prompt=prompt,
            system_prompt=RAG_SYSTEM_PROMPT,
            max_tokens=500,
            temperature=0.3,
        )

        async for chunk in llm_router.route_stream(
            task=LLMTask.RAG_GENERATION,
            request=llm_request,
        ):
            if chunk.text:
                yield _sse_event({"type": "token", "text": chunk.text})

            if chunk.finish_reason:
                break

        elapsed_ms = int((time.time() - start_time) * 1000)
        log.info(
            "stream_ask_complete",
            tenant_id=str(api_key.tenant_id),
            latency_ms=elapsed_ms,
            sources=len(sources),
        )
        yield _sse_event({"type": "done"})

    except Exception as e:
        log.error("stream_ask_error", error=str(e))
        yield _sse_event({"type": "error", "message": str(e)})


@router.post(
    "/ext/ask/stream",
    summary="SSE 스트리밍 RAG 답변 (외부 시스템 전용, API key 인증)",
    description=(
        "외부 시스템용 SSE 스트리밍 RAG 답변. `X-API-Key` 헤더의 API key 인증 필수 — "
        "JWT 와 별개 채널이며 ask scope 권한이 부여된 키만 호출 가능.\n\n"
        "**SSE 이벤트 순서**:\n"
        "1. `data: {\"type\": \"search_complete\", \"sources\": [...]}`\n"
        "2. `data: {\"type\": \"token\", \"text\": \"...\"}` (반복)\n"
        "3. `data: {\"type\": \"done\"}`\n\n"
        "**오류**: `data: {\"type\": \"error\", \"message\": \"...\"}` 후 종료."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE 스트림 (text/event-stream)",
            "content": {
                "text/event-stream": {
                    "example": (
                        "data: {\"type\": \"search_complete\", \"sources\": [...]}\n\n"
                        "data: {\"type\": \"token\", \"text\": \"연차는\"}\n\n"
                        "data: {\"type\": \"done\"}\n\n"
                    )
                }
            },
        },
        401: {"description": "API key 누락/만료/권한 부족"},
    },
)
async def external_ask_stream(
    request: ExternalAskRequest,
    api_key: APIKeyRecord = Depends(verify_api_key("ask")),
) -> StreamingResponse:
    """외부 시스템용 SSE 스트리밍 RAG 답변 API.

    SSE 이벤트 순서:
    1. data: {"type": "search_complete", "sources": [...]}
    2. data: {"type": "token", "text": "..."} (반복)
    3. data: {"type": "done"}

    오류 발생 시:
    - data: {"type": "error", "message": "..."}
    """
    log.info(
        "stream_ask_start",
        tenant_id=str(api_key.tenant_id),
        key_id=str(api_key.id),
        question_len=len(request.question),
    )

    return StreamingResponse(
        _stream_ask(request, api_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
