"""검색 API 라우터.

Agent C의 Search Service를 호출하는 프록시 계층.
서비스가 아직 구현되지 않았다면 스터브 응답을 반환한다.
"""

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.api.schemas.search import (
    RAGContextRequest,
    RAGContextResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchScope,
)
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.services.audit_service import record_action

logger = get_logger(__name__)

router = APIRouter()


async def _get_search_service():
    """Search Service를 지연 로딩한다. LLM 쿼리 강화 기능 포함."""
    try:
        from src.search.factory import create_search_service

        return await create_search_service()
    except (ImportError, Exception):
        return None


def _build_search_weights(weights_override):
    """API WeightsOverride를 search.models.SearchWeights로 변환한다."""
    if weights_override is None:
        return None
    try:
        from src.search.models import SearchWeights

        return SearchWeights(
            dense=weights_override.dense,
            sparse=weights_override.sparse,
            keyword=weights_override.keyword,
        )
    except ImportError:
        return None


async def resolve_search_repos(
    body: SearchRequest,
    tenant_id: UUID,
    db: AsyncSession,
) -> list[UUID] | None:
    """Resolve the effective repository_ids for a search request.

    Lucas-KMS multi-repo scope expansion (search scope enum + group_id).
    Returns None to mean "no restriction" (search service decides scope).
    Returns a list (possibly empty) to mean explicit restriction.

    Precedence (highest first):
    1. body.repository_id (legacy single).
    2. body.repository_ids (explicit array).
    3. body.repository_group_id (group expansion).
    4. body.scope == TENANT_ALL  -> active repos for tenant minus excludes.
    5. body.scope == DEFAULT     -> tenant default group if any, else TENANT_ALL.
    6. body.scope == SPECIFIED with no ids -> empty list (yields no results).
    """
    from src.core.models.repository import Repository
    from src.core.models.repository_group import RepositoryGroup

    if body.repository_id is not None:
        return [body.repository_id]
    if body.repository_ids:
        return list(body.repository_ids)

    if body.repository_group_id is not None:
        stmt = sa_select(RepositoryGroup).where(
            RepositoryGroup.id == body.repository_group_id,
            RepositoryGroup.tenant_id == tenant_id,
        )
        group = (await db.execute(stmt)).scalar_one_or_none()
        if group is None:
            logger.warning(
                "search_repository_group_not_found",
                group_id=str(body.repository_group_id),
                tenant_id=str(tenant_id),
            )
            return []
        return list(group.repository_ids or [])

    async def _active_repos() -> list[UUID]:
        stmt = sa_select(Repository.id).where(
            Repository.tenant_id == tenant_id,
            Repository.is_active.is_(True),
        )
        rows = (await db.execute(stmt)).fetchall()
        all_ids = [r[0] for r in rows]
        if body.exclude_repository_ids:
            excludes = {rid for rid in body.exclude_repository_ids}
            all_ids = [rid for rid in all_ids if rid not in excludes]
        return all_ids

    if body.scope == SearchScope.TENANT_ALL:
        return await _active_repos()

    if body.scope == SearchScope.DEFAULT:
        default_stmt = sa_select(RepositoryGroup).where(
            RepositoryGroup.tenant_id == tenant_id,
            RepositoryGroup.is_default.is_(True),
            RepositoryGroup.is_active.is_(True),
        )
        default_group = (await db.execute(default_stmt)).scalar_one_or_none()
        if default_group and default_group.repository_ids:
            return list(default_group.repository_ids)
        return await _active_repos()

    if body.scope == SearchScope.SPECIFIED:
        return []

    if body.scope == SearchScope.GROUP:
        # group scope without a group_id is a misconfiguration; return empty.
        return []

    return None


def _hit_to_search_result(item) -> SearchResult:
    """SearchResultItem을 API SearchResult로 변환한다."""
    from src.api.schemas.document import SourceLocationSchema

    # source_location 변환: search 모델은 SourceLocation, API는 SourceLocationSchema
    sl = getattr(item, "source_location", None)
    if sl is not None and not isinstance(sl, dict):
        sl_dict = sl.model_dump() if hasattr(sl, "model_dump") else {}
        # tuple -> list 변환 (page_range, bbox)
        if "page_range" in sl_dict and isinstance(sl_dict["page_range"], tuple):
            sl_dict["page_range"] = list(sl_dict["page_range"])
        if "bbox" in sl_dict and isinstance(sl_dict["bbox"], tuple):
            sl_dict["bbox"] = list(sl_dict["bbox"])
        source_loc = SourceLocationSchema(**sl_dict)
    else:
        source_loc = SourceLocationSchema()

    meta = getattr(item, "metadata", {}) or {}
    return SearchResult(
        chunk_id=item.chunk_id,
        document_id=item.document_id,
        document_title=item.document_title,
        section_title=getattr(item, "section_title", None),
        content=item.content or "",
        score=item.score,
        source_location=source_loc,
        metadata=meta,
        block_type=getattr(item, "block_type", None),
        block_index=getattr(item, "block_index", None),
        repository_id=getattr(item, "repository_id", None),
        validity=meta.get("validity_status"),
        nature=meta.get("nature"),
        classification_confidence=meta.get("classification_confidence"),
        token_count=getattr(item, "token_count", None),
        fallback_level=getattr(item, "fallback_level", None),
    )


@router.post(
    "",
    response_model=ApiResponse[SearchResponse],
    summary="하이브리드 검색",
)
async def search(
    body: SearchRequest,
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SearchResponse]:
    """하이브리드 검색을 수행한다.

    Dense + Sparse + Keyword 검색 → RRF 퓨전 → 리랭킹 파이프라인.
    사용자에게 repository_access가 설정된 경우, 검색 범위를 자동 조정한다.
    """
    start = time.monotonic()

    # 일별 검색 카운터 증가
    try:
        from src.core.services.license_enforcer import increment_daily_counter

        await increment_daily_counter(tenant_id, "searches_today")
    except Exception as exc:
        logger.debug("search_daily_counter_increment_failed", error=str(exc))

    # --- 검색 범위 자동 조정 (Item 8) ---
    effective_repository_id = body.repository_id
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None and effective_repository_id is None:
        try:
            from sqlalchemy import select as sa_select
            from src.core.models.user import User, UserRepositoryAccess, UserRole

            user_stmt = sa_select(User).where(User.id == user_id, User.tenant_id == tenant_id)
            user_result = await db.execute(user_stmt)
            user_obj = user_result.scalar_one_or_none()

            if user_obj and user_obj.role != UserRole.tenant_admin:
                # tenant_admin이 아니면 접근 가능한 저장소로 제한
                access_stmt = sa_select(UserRepositoryAccess.repository_id).where(
                    UserRepositoryAccess.user_id == user_id
                )
                access_result = await db.execute(access_stmt)
                allowed_repo_ids = [row[0] for row in access_result.fetchall()]
                if allowed_repo_ids:
                    # body.repository_id가 None이면 허용된 저장소로 제한
                    # SearchServiceRequest에서 repository_ids로 전달됨
                    body.repository_ids = allowed_repo_ids
        except Exception as exc:
            logger.warning("search_scope_auto_restrict_failed", error=str(exc))

    # --- Lucas-KMS multi-repo scope resolution ---
    # If the user-access auto-restrict above already set repository_ids, keep
    # those (more restrictive). Otherwise expand scope / group / default.
    if (
        body.repository_id is None
        and not body.repository_ids
        and (
            body.repository_group_id is not None
            or body.scope != SearchScope.SPECIFIED
        )
    ):
        try:
            resolved = await resolve_search_repos(body, tenant_id, db)
            if resolved is not None:
                body.repository_ids = resolved
        except Exception as exc:
            logger.warning("search_scope_resolve_failed", error=str(exc))

    search_svc = await _get_search_service()
    if search_svc is not None:
        try:
            import asyncio
            from src.search.models import SearchRequest as SearchServiceRequest
            from src.search.intent_classifier import classify_intent, log_intent_decision
            from src.api.schemas.search import IntentInfo

            # tenant_slug 조회
            from src.core.services.tenant_service import TenantService

            tenant_svc = TenantService(db)
            tenant = await tenant_svc.get_by_id(tenant_id)
            tenant_slug = tenant.slug

            svc_request = SearchServiceRequest(
                query=body.query,
                repository_id=body.repository_id,
                repository_ids=getattr(body, "repository_ids", None),
                tenant_id=tenant_id,
                category_ids=body.category_ids,
                document_type_ids=body.document_type_ids,
                top_k=body.top_k,
                search_mode=body.mode,
                rerank=body.enable_rerank,
                include_content=True,
                weights=_build_search_weights(body.weights),
                block_types=body.block_types,
                min_score=body.min_score,
                nature_filter=body.nature_filter,
                validity_filter=body.validity_filter,
                use_hyde=body.use_hyde,
                use_fallback=body.use_fallback,
                auto_intent=body.auto_intent,
                enable_llm_rewrite=body.enable_llm_rewrite,
                conversation_history=body.conversation_history,
                enable_sufficiency_check=body.enable_sufficiency_check,
            )

            # ── Intent gate + 검색 병렬 실행 ──
            # 검색이 불필요한 일상 대화를 조기에 차단하여 상담사 보조 UI 의 소음 제거.
            # 병렬 실행으로 지식 질의 latency 증가를 최소화 (classifier 가 보통 400-900ms).
            intent_result = None
            if body.enable_intent_gate:
                # 도메인 인식용 repository description 로드 (있으면 분류기에 주입)
                domain_description = None
                try:
                    from src.core.models.repository import Repository

                    if body.repository_id:
                        repo = await db.get(Repository, body.repository_id)
                        if repo and repo.description:
                            domain_description = repo.description
                    elif getattr(body, "repository_ids", None):
                        descs = []
                        for rid in body.repository_ids:
                            r = await db.get(Repository, rid)
                            if r and r.description:
                                descs.append(f"- {r.name}: {r.description}")
                        if descs:
                            domain_description = "\n".join(descs)
                except Exception as exc:
                    logger.debug("repo_description_load_failed", error=str(exc))

                intent_task = asyncio.create_task(
                    classify_intent(body.query, body.conversation_history, domain_description)
                )
                search_task = asyncio.create_task(
                    search_svc.search(request=svc_request, tenant_slug=tenant_slug)
                )
                intent_result = await intent_task

                # 분류 결과 로깅 (실패해도 요청은 진행)
                await log_intent_decision(
                    db=db,
                    query=body.query,
                    conversation_history=body.conversation_history,
                    result=intent_result,
                    tenant_id=tenant_id,
                )

                if not intent_result.search:
                    # 일상 대화 / 도메인 외 — 검색 결과 버리고 빈 응답
                    search_task.cancel()
                    try:
                        await search_task
                    except (asyncio.CancelledError, Exception):
                        pass  # 취소/에러 모두 흡수 — skip 응답이 목표
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    return ApiResponse(data=SearchResponse(
                        query=body.query,
                        results=[],
                        total_candidates=0,
                        latency_ms=elapsed_ms,
                        intent=IntentInfo(
                            search=False,
                            reason=intent_result.reason,
                            latency_ms=intent_result.latency_ms,
                            skipped=True,
                        ),
                    ))

                # 검색 필요 — 검색 완료 대기
                svc_response = await search_task
            else:
                svc_response = await search_svc.search(
                    request=svc_request,
                    tenant_slug=tenant_slug,
                )

            # ── Post-search 점수 gate (2안) ──
            # intent 은 통과했지만 실제 검색 결과 점수가 매우 낮으면 (관련 문서 없음)
            # 상담사 UI 에 노이즈 전달되지 않도록 빈 결과로 전환.
            # 임계값 0.02: bge-reranker-base 기준 선명한 관련성 하한 (실측 일반매치 0.03-0.07,
            # 노이즈/무관련 쿼리는 <0.02). 데이터 누적 후 유저피드백(intent_logs.user_feedback)
            # 기반으로 튜닝 가능.
            SCORE_GATE_THRESHOLD = 0.02
            results_hits = list(svc_response.results)
            if results_hits and body.enable_intent_gate:
                top_score = results_hits[0].score or 0.0
                if top_score < SCORE_GATE_THRESHOLD:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    gate_reason = f"검색 수행됐으나 최고 관련도({top_score:.3f}) 가 임계값({SCORE_GATE_THRESHOLD}) 미달 — 관련 문서 없음"
                    return ApiResponse(data=SearchResponse(
                        query=body.query,
                        results=[],
                        total_candidates=svc_response.query_metadata.total_candidates,
                        latency_ms=elapsed_ms,
                        intent=IntentInfo(
                            search=False,
                            reason=gate_reason,
                            latency_ms=intent_result.latency_ms if intent_result else 0,
                            skipped=True,
                        ),
                        keywords=getattr(svc_response, "keywords", []),
                        rewritten_query=getattr(svc_response, "rewritten_query", None),
                    ))

            elapsed_ms = int((time.monotonic() - start) * 1000)
            results = [_hit_to_search_result(item) for item in svc_response.results]

            # 감사 로그: 검색 실행
            record_action(
                tenant_id=tenant_id,
                user_id=user_id,
                action="SEARCH",
                resource_type="document",
                detail={
                    "query": body.query,
                    "result_count": len(results),
                    "total_candidates": svc_response.query_metadata.total_candidates,
                    "latency_ms": elapsed_ms,
                    "intent_gate_passed": intent_result.search if intent_result else None,
                },
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("User-Agent"),
            )

            intent_info = None
            if intent_result:
                intent_info = IntentInfo(
                    search=intent_result.search,
                    reason=intent_result.reason,
                    latency_ms=intent_result.latency_ms,
                    skipped=False,
                )
            return ApiResponse(data=SearchResponse(
                query=body.query,
                results=results,
                total_candidates=svc_response.query_metadata.total_candidates,
                latency_ms=elapsed_ms,
                decomposed=getattr(svc_response, "decomposed", None),
                intent=intent_info,
                keywords=getattr(svc_response, "keywords", []),
                rewritten_query=getattr(svc_response, "rewritten_query", None),
            ))
        except Exception as exc:
            logger.warning("search_service_error", error=str(exc))

    # 서비스 미구현 시 빈 응답
    elapsed_ms = int((time.monotonic() - start) * 1000)

    # 감사 로그: 검색 (서비스 미구현 / 빈 결과)
    record_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action="SEARCH",
        resource_type="document",
        detail={
            "query": body.query,
            "result_count": 0,
            "total_candidates": 0,
            "latency_ms": elapsed_ms,
        },
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )

    return ApiResponse(
        data=SearchResponse(
            query=body.query,
            results=[],
            total_candidates=0,
            latency_ms=elapsed_ms,
        )
    )


@router.post(
    "/rag-context",
    response_model=ApiResponse[RAGContextResponse],
    summary="[DEPRECATED] RAG 컨텍스트 조회 — /api/v1/rag/retrieve 또는 /api/v1/rag/answer 사용 권장",
    deprecated=True,
)
async def get_rag_context(
    body: RAGContextRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RAGContextResponse]:
    """[DEPRECATED] 검색 + RAG 컨텍스트를 반환한다.

    이 엔드포인트는 레거시 호환용으로만 유지됩니다.
    새로운 클라이언트는 다음을 사용하세요:
    - POST /api/v1/rag/retrieve — 컨텍스트만 필요할 때
    - POST /api/v1/rag/answer — LLM 답변 생성이 필요할 때
    """
    start = time.monotonic()

    search_svc = await _get_search_service()
    if search_svc is not None:
        try:
            from src.search.models import RAGContextRequest as RAGServiceRequest

            # tenant_slug 조회
            from src.core.services.tenant_service import TenantService

            tenant_svc = TenantService(db)
            tenant = await tenant_svc.get_by_id(tenant_id)
            tenant_slug = tenant.slug

            svc_request = RAGServiceRequest(
                query=body.query,
                repository_id=body.repository_id,
                tenant_id=tenant_id,
                mode=body.mode,
                top_k=body.top_k,
                weights=_build_search_weights(body.weights),
            )

            rag_response = await search_svc.build_rag_context(
                request=svc_request,
                tenant_slug=tenant_slug,
            )

            elapsed_ms = int((time.monotonic() - start) * 1000)

            # rag_response.sources -> SearchResult 변환
            context_chunks: list[SearchResult] = []
            for src_item in rag_response.sources:
                from src.api.schemas.document import SourceLocationSchema

                sl = src_item.source_location
                if sl is not None and not isinstance(sl, dict):
                    sl_dict = sl.model_dump() if hasattr(sl, "model_dump") else {}
                    if "page_range" in sl_dict and isinstance(sl_dict["page_range"], tuple):
                        sl_dict["page_range"] = list(sl_dict["page_range"])
                    if "bbox" in sl_dict and isinstance(sl_dict["bbox"], tuple):
                        sl_dict["bbox"] = list(sl_dict["bbox"])
                    source_loc = SourceLocationSchema(**sl_dict)
                else:
                    source_loc = SourceLocationSchema()

                context_chunks.append(SearchResult(
                    chunk_id=UUID("00000000-0000-0000-0000-000000000000"),
                    document_id=UUID("00000000-0000-0000-0000-000000000000"),
                    document_title=src_item.doc_title,
                    section_title=src_item.section,
                    content="",
                    score=src_item.score,
                    source_location=source_loc,
                ))

            return ApiResponse(data=RAGContextResponse(
                query=body.query,
                context_chunks=context_chunks,
                generated_answer=rag_response.prompt_template,
                model_used=None,
                context_tokens=0,
                latency_ms=elapsed_ms,
            ))
        except Exception as exc:
            logger.warning("rag_context_error", error=str(exc))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return ApiResponse(
        data=RAGContextResponse(
            query=body.query,
            context_chunks=[],
            latency_ms=elapsed_ms,
        )
    )
