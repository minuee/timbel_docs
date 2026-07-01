"""외부 검색 API — POST /api/v1/ext/search."""

from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from src.common.logging import get_logger
from src.integration.api_gateway.auth import verify_api_key
from src.integration.api_gateway.models import APIKeyRecord
from src.integration.api_gateway.response_cache import ResponseCache
from src.integration.metrics import EXTERNAL_API_DURATION_SECONDS, EXTERNAL_API_REQUESTS_TOTAL
from src.integration.rag_api.models import (
    ExternalSearchRequest,
    ExternalSearchResponse,
    QueryMetadata,
    SearchResultItem,
)

log = get_logger(__name__)

router = APIRouter()

# ResponseCache 인스턴스는 의존성 주입 또는 앱 startup에서 설정한다.
# 여기서는 None으로 초기화하고, 앱 startup에서 set_response_cache()로 주입.
_response_cache: ResponseCache | None = None


def set_response_cache(cache: ResponseCache) -> None:
    """앱 startup에서 ResponseCache 인스턴스를 주입한다."""
    global _response_cache
    _response_cache = cache


@router.post(
    "/ext/search",
    response_model=ExternalSearchResponse,
    summary="외부 시스템용 하이브리드 검색",
)
async def external_search(
    request: ExternalSearchRequest,
    api_key: APIKeyRecord = Depends(verify_api_key("search")),
    raw_request: Request = None,  # type: ignore[assignment]
) -> Response | ExternalSearchResponse:
    """외부 시스템용 검색 API.

    API Key 인증 + scope "search" 검증 후 하이브리드 검색을 실행한다.
    검색 결과에 source_location을 포함하여 반환한다.
    Redis 기반 응답 캐싱을 지원한다.
    """
    start_time = time.time()
    endpoint = "/ext/search"
    request_body = request.model_dump_json()
    request_dict = request.model_dump()

    EXTERNAL_API_REQUESTS_TOTAL.labels(endpoint=endpoint, api_key_name=api_key.name).inc()

    log.info(
        "external_search_start",
        tenant_id=str(api_key.tenant_id),
        key_id=str(api_key.id),
        query_len=len(request.query),
        repository_id=str(request.repository_id),
        top_k=request.top_k,
        search_mode=request.search_mode,
    )

    # 캐시 조회
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

    # Agent C의 SearchService 호출
    results, total_candidates, strategy = await _execute_search(
        request, tenant_id=api_key.tenant_id
    )

    elapsed_ms = int((time.time() - start_time) * 1000)

    response = ExternalSearchResponse(
        results=results,
        query_metadata=QueryMetadata(
            latency_ms=elapsed_ms,
            total_candidates=total_candidates,
            strategy_used=strategy,
        ),
    )

    # 캐시 저장
    if _response_cache and not ResponseCache.should_skip(request_dict, endpoint):
        response_body = response.model_dump_json()
        await _response_cache.put(
            api_key_id=api_key.id,
            endpoint=endpoint,
            request_body=request_body,
            response_body=response_body,
            repository_id=request.repository_id,
        )

    EXTERNAL_API_DURATION_SECONDS.labels(endpoint=endpoint).observe(
        time.time() - start_time
    )

    log.info(
        "external_search_complete",
        tenant_id=str(api_key.tenant_id),
        result_count=len(results),
        latency_ms=elapsed_ms,
    )

    return response


async def _execute_search(
    request: ExternalSearchRequest,
    tenant_id: UUID | None = None,
) -> tuple[list[SearchResultItem], int, str]:
    """SearchService에 검색을 위임한다.

    Args:
        request: 외부 검색 요청
        tenant_id: API Key 에서 추출한 테넌트 ID

    Agent C 구현 후 실제 SearchService를 호출하도록 교체한다.
    현재는 import를 시도하고, 없으면 빈 결과를 반환한다.
    """
    effective_tenant_id = tenant_id or request.repository_id

    try:
        from src.search.factory import create_search_service
        from src.search.models import SearchRequest as SearchServiceRequest
        from src.search.models import SearchWeights as SearchServiceWeights

        service = await create_search_service()

        svc_weights = None
        if request.weights:
            svc_weights = SearchServiceWeights(
                dense=request.weights.dense,
                sparse=request.weights.sparse,
                keyword=request.weights.keyword,
            )

        svc_request = SearchServiceRequest(
            query=request.query,
            repository_id=request.repository_id,
            tenant_id=effective_tenant_id,
            category_ids=list(request.category_ids) if request.category_ids else None,
            document_type_ids=(
                list(request.document_type_ids) if request.document_type_ids else None
            ),
            top_k=request.top_k,
            search_mode=request.search_mode,
            rerank=request.rerank,
            include_content=True,
            weights=svc_weights,
            block_types=request.block_types,
        )

        # tenant_slug를 DB에서 조회
        tenant_slug = await _resolve_tenant_slug(effective_tenant_id)
        svc_response = await service.search(
            request=svc_request,
            tenant_slug=tenant_slug,
        )

        results = [
            SearchResultItem(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_title=item.document_title,
                section_title=getattr(item, "section_title", None),
                content=item.content or "",
                score=item.score,
                source_location=(
                    item.source_location.model_dump()
                    if hasattr(item.source_location, "model_dump")
                    else {}
                ),
                metadata=getattr(item, "metadata", {}),
            )
            for item in svc_response.results
        ]

        total_candidates = svc_response.query_metadata.total_candidates
        strategy = request.search_mode

        return results, total_candidates, strategy

    except ImportError:
        log.warning("search_service_not_available", reason="Agent C SearchService not yet implemented")
        return [], 0, request.search_mode


async def _resolve_tenant_slug(tenant_id: UUID) -> str:
    """테넌트 ID로 slug를 조회한다."""
    try:
        from sqlalchemy import select

        from src.core.database import async_session_factory
        from src.core.models.tenant import Tenant

        async with async_session_factory() as session:
            stmt = select(Tenant.slug).where(Tenant.id == tenant_id)
            result = await session.execute(stmt)
            slug = result.scalar_one_or_none()
            if slug:
                return slug
    except Exception as exc:
        log.warning("tenant_slug_resolve_failed", tenant_id=str(tenant_id), error=str(exc))

    # Fallback: UUID에서 생성 (이건 안 맞을 수 있음)
    return str(tenant_id).replace("-", "")[:12]
