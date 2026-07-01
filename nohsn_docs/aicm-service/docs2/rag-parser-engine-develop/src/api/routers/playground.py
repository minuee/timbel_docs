"""Playground API 라우터 — 개발/디버깅용 트레이스 엔드포인트.

검색 품질 디버깅, 파이프라인 처리 추적, 성능 모니터링을 위한 전용 API.
"""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.api.schemas.document import SourceLocationSchema
from src.api.schemas.playground import (
    ChunkTraceItem,
    LLMModelPerformance,
    LLMPerformance,
    PerformanceMetricsResponse,
    PipelinePerformance,
    PipelineStageTrace,
    PipelineTraceData,
    PipelineTraceDocument,
    PipelineTraceResponse,
    SearchLatencyBreakdown,
    SearchPerformance,
    SearchTrace,
    SearchTraceRequest,
    SearchTraceResponse,
    TraceStep,
    TraceStepResult,
)
from src.api.schemas.search import SearchResult
from src.common.logging import get_logger
from src.core.database import get_db

logger = get_logger(__name__)

router = APIRouter()


async def _get_search_service():
    """Search Service 지연 로딩. LLM 쿼리 강화 기능 포함."""
    try:
        from src.search.factory import create_search_service

        return await create_search_service()
    except (ImportError, Exception):
        return None


@router.post(
    "/search-trace",
    response_model=ApiResponse[SearchTraceResponse],
    summary="검색 트레이스 (단계별 상세)",
)
async def search_with_trace(
    body: SearchTraceRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SearchTraceResponse]:
    """검색을 실행하고 각 단계별 상세 트레이스를 반환한다.

    반환되는 트레이스 단계:
    1. dense_search — Dense 벡터 검색 결과 + 스코어
    2. sparse_search — Sparse 벡터 검색 결과 + 스코어
    3. rrf_fusion — RRF 퓨전 결과 (Dense + Sparse 스코어 병합)
    4. rerank — Cross-encoder 리랭킹 결과 + 순위 변동
    5. rag_generation — (선택) LLM 응답 + 프롬프트 미리보기 + 토큰/비용 정보
    """
    overall_start = time.monotonic()

    search_svc = await _get_search_service()
    if search_svc is not None:
        try:
            from src.search.models import SearchRequest as SearchServiceRequest
            from src.search.models import SearchWeights as SvcSearchWeights

            # tenant_slug 조회
            from src.core.services.tenant_service import TenantService

            tenant_svc = TenantService(db)
            tenant = await tenant_svc.get_by_id(tenant_id)
            tenant_slug = tenant.slug

            svc_weights = None
            if body.weights:
                svc_weights = SvcSearchWeights(
                    dense=body.weights.dense,
                    sparse=body.weights.sparse,
                    keyword=body.weights.keyword,
                )

            svc_request = SearchServiceRequest(
                query=body.query,
                repository_id=body.repository_id,
                tenant_id=tenant_id,
                category_ids=body.category_ids,
                document_type_ids=body.document_type_ids,
                top_k=body.top_k,
                search_mode=body.mode,
                rerank=body.enable_rerank,
                include_content=True,
                weights=svc_weights,
            )

            svc_response, svc_trace = await search_svc.search_with_trace(
                request=svc_request,
                tenant_slug=tenant_slug,
            )

            total_ms = int((time.monotonic() - overall_start) * 1000)

            # SearchTraceStep -> TraceStep 변환
            steps = []
            for step in svc_trace.steps:
                steps.append(TraceStep(
                    name=step.step_name,
                    latency_ms=step.latency_ms,
                    input=step.details,
                    output={"candidate_count": step.candidate_count},
                    results=[],
                ))

            from src.api.routers.search import _hit_to_search_result

            final_results = [_hit_to_search_result(item) for item in svc_response.results]

            return ApiResponse(
                data=SearchTraceResponse(
                    final_results=final_results,
                    trace=SearchTrace(
                        total_latency_ms=total_ms,
                        steps=steps,
                    ),
                )
            )
        except AttributeError:
            logger.info("search_service_no_trace_support")
        except Exception as exc:
            logger.warning("search_trace_error", error=str(exc))

    # 서비스 미구현 시 스텁 트레이스 반환
    total_ms = int((time.monotonic() - overall_start) * 1000)
    return ApiResponse(
        data=SearchTraceResponse(
            final_results=[],
            trace=SearchTrace(
                total_latency_ms=total_ms,
                steps=[
                    TraceStep(
                        name="dense_search",
                        latency_ms=0,
                        input={"query_vector_dim": 1024},
                        output={"candidates": 0, "top_k": body.top_k},
                        results=[],
                    ),
                    TraceStep(
                        name="sparse_search",
                        latency_ms=0,
                        input={"query_tokens": {}},
                        output={"candidates": 0, "top_k": body.top_k},
                        results=[],
                    ),
                    TraceStep(
                        name="rrf_fusion",
                        latency_ms=0,
                        input={"dense_count": 0, "sparse_count": 0},
                        output={"merged": 0, "top_k": body.top_k},
                        results=[],
                    ),
                    TraceStep(
                        name="rerank",
                        latency_ms=0,
                        input={"candidates": 0},
                        output={"top_k": 0},
                        results=[],
                    ),
                ],
            ),
        )
    )


@router.get(
    "/pipeline-trace/{doc_id}",
    response_model=ApiResponse[PipelineTraceResponse],
    summary="파이프라인 처리 트레이스",
)
async def get_pipeline_trace(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PipelineTraceResponse]:
    """문서의 파이프라인 처리 상세 트레이스를 반환한다.

    각 스테이지(parse/chunk/embed/index)의 입출력, 소요 시간, 결과물을 포함한다.
    """
    from src.core.models.document import Chunk, Document
    from src.core.services.document_service import DocumentService

    doc_svc = DocumentService(db)
    doc = await doc_svc.get_by_id(doc_id, tenant_id=tenant_id)
    meta = doc.processing_meta or {}

    # 파이프라인 스테이지 트레이스 구성
    stages: list[PipelineStageTrace] = []

    # Parse 스테이지
    parse_meta = meta.get("parse", {})
    stages.append(PipelineStageTrace(
        name="parse",
        duration_ms=parse_meta.get("duration_ms", 0),
        output={
            "pages": parse_meta.get("pages", 0),
            "tables": parse_meta.get("tables", 0),
            "images": parse_meta.get("images", 0),
            "raw_text_length": parse_meta.get("raw_text_length", 0),
            "difficulty": meta.get("difficulty", {}),
        },
    ))

    # Chunk 스테이지
    chunk_meta = meta.get("chunk", {})
    stages.append(PipelineStageTrace(
        name="chunk",
        duration_ms=chunk_meta.get("duration_ms", 0),
        output={
            "total_chunks": chunk_meta.get("total_chunks", meta.get("chunk_count", 0)),
            "by_strategy": chunk_meta.get("by_strategy", {}),
            "avg_tokens": chunk_meta.get("avg_tokens", 0),
            "min_tokens": chunk_meta.get("min_tokens", 0),
            "max_tokens": chunk_meta.get("max_tokens", 0),
        },
    ))

    # Embed 스테이지
    embed_meta = meta.get("embed", {})
    stages.append(PipelineStageTrace(
        name="embed",
        duration_ms=embed_meta.get("duration_ms", 0),
        output={
            "embedded_count": embed_meta.get("embedded_count", 0),
            "dense_dim": embed_meta.get("dense_dim", 1024),
            "avg_sparse_tokens": embed_meta.get("avg_sparse_tokens", 0),
            "batch_size": embed_meta.get("batch_size", 32),
        },
    ))

    # Index 스테이지
    index_meta = meta.get("index", {})
    stages.append(PipelineStageTrace(
        name="index",
        duration_ms=index_meta.get("duration_ms", 0),
        output={
            "qdrant_upserted": index_meta.get("qdrant_upserted", 0),
            "elasticsearch_indexed": index_meta.get("elasticsearch_indexed", 0),
            "collection": index_meta.get("collection", ""),
        },
    ))

    total_duration = sum(s.duration_ms for s in stages)

    # 청크 목록 로딩
    chunks_list: list[ChunkTraceItem] = []
    try:
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == doc_id)
            .order_by(Chunk.chunk_index)
        )
        result = await db.execute(stmt)
        db_chunks = result.scalars().all()
        for chunk in db_chunks:
            chunks_list.append(ChunkTraceItem(
                id=str(chunk.id),
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
                strategy=chunk.metadata.get("strategy"),
                source_location=chunk.source_location or {},
                metadata=chunk.metadata or {},
                vector_preview=None,  # 벡터 미리보기는 Phase 2
            ))
    except Exception as exc:
        logger.warning("chunk_loading_failed", doc_id=str(doc_id), error=str(exc))

    return ApiResponse(
        data=PipelineTraceResponse(
            document=PipelineTraceDocument(
                id=str(doc.id),
                title=doc.title,
                format=doc.source_format,
            ),
            trace=PipelineTraceData(
                total_duration_ms=total_duration,
                stages=stages,
            ),
            chunks=chunks_list,
        )
    )


@router.get(
    "/performance",
    response_model=ApiResponse[PerformanceMetricsResponse],
    summary="성능 메트릭",
)
async def get_performance_metrics(
    period: str = Query("24h", pattern=r"^(1h|6h|24h|7d|30d)$", description="기간"),
    repository_id: UUID | None = Query(None),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PerformanceMetricsResponse]:
    """성능 메트릭을 조회한다.

    검색 레이턴시 분해, 파이프라인 처리량, LLM 사용량/비용을 포함한다.
    MetricsCollector를 통해 Redis 카운터 + DB 집계 기반 실 데이터를 반환한다.
    """
    from src.api.services.metrics_collector import MetricsCollector

    collector = MetricsCollector(db)

    # 검색 성능
    try:
        search_data = await collector.collect_search_performance(
            tenant_id=tenant_id, period=period, repository_id=repository_id
        )
        search_perf = SearchPerformance(
            total_queries=search_data["total_queries"],
            latency_p50_ms=search_data["latency_p50_ms"],
            latency_p95_ms=search_data["latency_p95_ms"],
            latency_breakdown=SearchLatencyBreakdown(**search_data["latency_breakdown"]),
            hourly_trend=search_data["hourly_trend"],
        )
    except Exception as exc:
        logger.warning("search_performance_collect_error", error=str(exc))
        search_perf = SearchPerformance()

    # 파이프라인 성능
    try:
        pipeline_data = await collector.collect_pipeline_performance(
            tenant_id=tenant_id, period=period, repository_id=repository_id
        )
        pipeline_perf = PipelinePerformance(**pipeline_data)
    except Exception as exc:
        logger.warning("pipeline_performance_collect_error", error=str(exc))
        pipeline_perf = PipelinePerformance()

    # LLM 사용량
    try:
        llm_data = await collector.collect_llm_performance(
            tenant_id=tenant_id, period=period
        )
        llm_perf = LLMPerformance(
            claude=LLMModelPerformance(**llm_data["claude"]),
            qwen=LLMModelPerformance(**llm_data["qwen"]),
            fallback_count=llm_data["fallback_count"],
        )
    except Exception as exc:
        logger.warning("llm_performance_collect_error", error=str(exc))
        llm_perf = LLMPerformance()

    return ApiResponse(
        data=PerformanceMetricsResponse(
            search=search_perf,
            pipeline=pipeline_perf,
            llm=llm_perf,
        )
    )
