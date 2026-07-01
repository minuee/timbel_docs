"""RAG 전용 API 라우터 — Knowledge Search와 분리된 LLM용 RAG Retrieval/Answer.

Knowledge Search (POST /api/v1/search):
  - 사람이 직접 읽는 검색 결과 (10-50건, 페이지네이션, 하이라이팅)
  - 토큰 제약 없음

RAG Retrieval (POST /api/v1/rag/retrieve):
  - LLM 프롬프트에 주입하는 컨텍스트 (3-5건, 토큰 예산 엄격 준수)
  - 압축, 프롬프트 템플릿 제공

RAG Answer (POST /api/v1/rag/answer):
  - RAG Retrieve + LLM 답변 생성을 한 번에 수행
"""

from __future__ import annotations

import json
import time
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id, get_current_user_id
from src.api.schemas.common import ApiResponse
from src.api.schemas.rag import (
    DistilledContext,
    RAGAnswerRequest,
    RAGAnswerResponse,
    RAGGenerateRequest,
    RAGGenerateResponse,
    RAGRetrieveRequest,
    RAGRetrieveResponse,
    RAGSource,
    TokenUsage,
    UnsupportedClaimResponse,
)
from src.api.schemas.search import IntentInfo
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.services.audit_service import record_action

logger = get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Token counting (한국어 기준 3.5 chars/token, 영문 4 chars/token)
# ---------------------------------------------------------------------------

CHUNK_COMPRESS_THRESHOLD = 500  # 이 토큰 수 초과 시 압축 대상

# table raw pass-through (메모리 [[feedback_kms_lukas_separation]]) 의 budget cap.
# gemma-31b 32k context 의 약 1/3 보호. 운영 튜닝 필요 시 env override 도입 권장.
TABLE_RAW_MAX_CHARS_PER = 4000
TABLE_RAW_MAX_CHARS_TOTAL = 12000
# separator cell 검증: ':---', '---', ':---:' 등 정규 markdown table 패턴.
import re as _re
_TABLE_SEP_CELL_RE = _re.compile(r"^:?-{3,}:?$")


def _count_tokens(text: str) -> int:
    """간이 토큰 수 추정. 한국어 ~3.5자/토큰, 영문 ~4자/토큰."""
    if not text:
        return 0
    korean_chars = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    total_chars = len(text)
    if total_chars == 0:
        return 0
    korean_ratio = korean_chars / total_chars
    avg_chars_per_token = 3.5 * korean_ratio + 4.0 * (1 - korean_ratio)
    return max(1, int(total_chars / avg_chars_per_token))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_search_service():
    """Search Service를 지연 로딩한다. LLM 쿼리 강화 기능 포함."""
    try:
        from src.search.factory import create_search_service

        return await create_search_service()
    except (ImportError, Exception):
        return None


async def _compress_chunk(content: str) -> str:
    """LLM을 사용해 긴 청크를 압축 요약한다.

    500 토큰 초과 청크를 ~200 토큰으로 압축.
    LLM 사용 불가 시 단순 truncation으로 fallback.
    """
    try:
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        response = await llm_router.route(
            task=LLMTask.RAG_GENERATION,
            request=LLMRequest(
                prompt=(
                    "다음 텍스트를 핵심 정보만 보존하여 200 토큰 이내로 압축 요약하세요. "
                    "원문의 사실 관계를 변경하지 마세요.\n\n"
                    f"원문:\n{content}"
                ),
                system_prompt="당신은 텍스트 압축 전문가입니다. 핵심만 간결하게 요약하세요.",
                max_tokens=300,
                temperature=0.1,
            ),
        )
        return response.text
    except Exception:
        logger.warning("chunk_compression_fallback", reason="LLM unavailable, using truncation")
        # Fallback: 앞부분 ~500자 + 뒷부분 ~200자
        if len(content) > 700:
            return content[:500] + "\n...\n" + content[-200:]
        return content


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


async def _resolve_linked_repositories(
    user_id: UUID | None,
    tenant_id: UUID,
    db: AsyncSession,
) -> list[UUID]:
    """TenantLink 기반으로 접근 가능한 linked repository ID 목록을 반환한다.

    Args:
        user_id: 현재 사용자 ID (None이면 빈 목록 반환)
        tenant_id: 현재 테넌트 ID
        db: DB 세션

    Returns:
        접근 가능한 linked tenant의 repository ID 목록
    """
    if user_id is None:
        return []

    try:
        from sqlalchemy import select as sa_select

        from src.core.models.repository import Repository
        from src.core.models.tenant_link import TenantLink

        stmt = sa_select(TenantLink).where(
            TenantLink.user_id == user_id,
            TenantLink.status == "active",
            TenantLink.user_consent.is_(True),
            TenantLink.corporate_consent.is_(True),
            (
                (TenantLink.personal_tenant_id == tenant_id)
                | (TenantLink.corporate_tenant_id == tenant_id)
            ),
        )
        result = await db.execute(stmt)
        links = result.scalars().all()

        linked_repo_ids: list[UUID] = []
        for link in links:
            # 상대방 테넌트 ID 결정
            other_tenant_id = (
                link.corporate_tenant_id
                if link.personal_tenant_id == tenant_id
                else link.personal_tenant_id
            )
            # 상대방 테넌트의 활성 저장소 조회
            repo_stmt = sa_select(Repository.id).where(
                Repository.tenant_id == other_tenant_id,
                Repository.is_active.is_(True),
            )
            repo_result = await db.execute(repo_stmt)
            linked_repo_ids.extend(repo_result.scalars().all())

        return linked_repo_ids
    except ImportError:
        logger.warning("resolve_linked_repos_import_error", reason="TenantLink or Repository model not available")
        return []
    except Exception as exc:
        logger.warning("resolve_linked_repos_error", error=str(exc))
        return []


# ---------------------------------------------------------------------------
# RAG 컨텍스트 조립 (토큰 예산 엄격 준수)
# ---------------------------------------------------------------------------


async def _assemble_rag_context(
    hits: list,
    max_context_tokens: int,
    compress: bool,
    db: "AsyncSession | None" = None,
) -> tuple[str, list[RAGSource], int]:
    """검색 결과를 토큰 예산 내에서 RAG 컨텍스트로 조립한다.

    Args:
        hits: 검색 결과 (SearchHit 또는 SearchResultItem)
        max_context_tokens: 토큰 예산
        compress: 긴 청크 압축 여부
        db: DB 세션 (document_title 조회용, 선택)

    Returns:
        (context_str, sources, total_tokens)
    """
    context_parts: list[str] = []
    sources: list[RAGSource] = []
    total_tokens = 0

    doc_title_cache: dict[str, str] = {}
    async def _resolve_doc_title(document_id) -> str:
        """document_title이 비어있으면 DB에서 조회."""
        did = str(document_id)
        if did in doc_title_cache:
            return doc_title_cache[did]
        if db is not None:
            try:
                from src.core.models.document import Document
                doc = await db.get(Document, document_id)
                if doc and doc.title:
                    doc_title_cache[did] = doc.title
                    return doc.title
            except Exception:
                pass
        doc_title_cache[did] = ""
        return ""

    for rank, hit in enumerate(hits, 1):
        content = hit.content or ""
        chunk_tokens = _count_tokens(content)

        # 압축 옵션: 500 토큰 초과 청크를 요약
        compressed = False
        if compress and chunk_tokens > CHUNK_COMPRESS_THRESHOLD:
            content = await _compress_chunk(content)
            chunk_tokens = _count_tokens(content)
            compressed = True

        doc_title = getattr(hit, "document_title", "") or ""
        if not doc_title:
            doc_title = await _resolve_doc_title(hit.document_id)
        section_title = getattr(hit, "section_title", None) or ""
        source_tag = f"[{rank}] {doc_title}"
        if section_title:
            source_tag += f" > {section_title}"

        block = f"{source_tag}\n{content}"
        block_tokens = _count_tokens(block)

        # 토큰 예산 초과 시 중단
        if total_tokens + block_tokens > max_context_tokens:
            # 남은 공간이 있으면 일부라도 포함
            remaining_tokens = max_context_tokens - total_tokens
            if remaining_tokens > 50:
                # 남은 토큰에 맞게 문자 수 계산 (대략 3.5 chars/token)
                remaining_chars = int(remaining_tokens * 3.5)
                truncated_content = content[:remaining_chars] + "..."
                block = f"{source_tag}\n{truncated_content}"
                block_tokens = _count_tokens(block)
            else:
                break

        context_parts.append(block)
        total_tokens += block_tokens

        # source_location 추출
        sl = getattr(hit, "source_location", None)
        if sl is not None and hasattr(sl, "model_dump"):
            sl_dict = sl.model_dump()
        elif isinstance(sl, dict):
            sl_dict = sl
        else:
            sl_dict = {}

        # 페이지 정보 추출
        page_info = None
        if sl_dict:
            if sl_dict.get("page_range"):
                pr = sl_dict["page_range"]
                page_info = f"p.{pr[0]}-{pr[1]}"
            elif sl_dict.get("page_number"):
                page_info = f"p.{sl_dict['page_number']}"
            if sl_dict.get("sheet_name"):
                sheet = f"시트: {sl_dict['sheet_name']}"
                page_info = f"{page_info}, {sheet}" if page_info else sheet

        content_preview = (hit.content or "")[:200]
        sources.append(
            RAGSource(
                ref_num=rank,
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_title=doc_title,
                section_title=section_title or None,
                content=content_preview if content_preview else None,
                score=round(getattr(hit, "score", 0.0), 4),
                token_count=block_tokens,
                compressed=compressed,
                source_location=sl_dict,
                page_info=page_info,
                block_type=getattr(hit, "block_type", None),
                full_content=hit.content or None,
            )
        )

        # 예산 가득 찼으면 중단
        if total_tokens >= max_context_tokens:
            break

    context = "\n\n".join(context_parts)
    return context, sources, total_tokens


# ---------------------------------------------------------------------------
# LLM 정제 (선택 + 요약) — 후보들에서 답변 관련 청크만 골라 핵심 컨텍스트로 압축
# ---------------------------------------------------------------------------

DISTILL_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "selected": {
            "type": "array",
            "description": "답변에 실제로 사용할 청크의 ref_num 목록 (1-indexed). 빈 배열 가능.",
            "items": {"type": "integer", "minimum": 1},
        },
        "summary": {
            "type": "string",
            "description": "선택된 청크들에서 사용자 질문에 답하는 데 필요한 사실만 추출해 한국어로 정제한 핵심 컨텍스트. 인용은 [1], [4] 형태로.",
        },
        "rationale": {
            "type": "string",
            "description": "왜 그 청크들을 선택했는지 한 문장 사유.",
        },
    },
    "required": ["selected", "summary", "rationale"],
    "additionalProperties": False,
}


async def _distill_context(
    query: str,
    candidates: list[RAGSource],
    full_contents: dict[int, str],
) -> tuple[DistilledContext | None, int, int]:
    """후보 청크들에서 LLM 으로 답변 관련 청크 선택 + 핵심 컨텍스트 요약.

    Returns:
        (distilled, completion_tokens, latency_ms). 실패 시 distilled=None.
    """
    if not candidates:
        return None, 0, 0

    from src.common.llm.base import LLMRequest, LLMTask
    from src.common.llm.router import llm_router

    # 후보 직렬화 — full content (RAGSource.content 는 200자 컷이므로 별도 dict)
    parts: list[str] = []
    for s in candidates:
        body = full_contents.get(s.ref_num, s.content or "")
        head = f"[{s.ref_num}] {s.document_title or 'doc'}"
        if s.section_title:
            head += f" > {s.section_title}"
        parts.append(f"{head}\n{body}")
    candidates_text = "\n\n".join(parts)

    system_prompt = (
        "당신은 RAG 컨텍스트 정제기입니다. 사용자 질문과 후보 청크들을 받고, "
        "답변 생성에 도움이 될 수 있는 청크를 선택해 핵심 사실을 한국어로 정제·요약합니다.\n"
        "\n"
        "선택 기준 (포용적으로):\n"
        "- **주제·도메인·대상이 일치**하면 선택하라. literal 단어 매칭이 아니라 의미 일치가 판단 기준.\n"
        "- 예: 질문 'HTS 단축번호' 와 청크 '크레온 HTS: #0835 메뉴' → 선택 (단축번호 = 단축키 = 화면번호 = #NNNN 메뉴번호).\n"
        "- 예: 질문 '증명서 수수료' 와 청크 '잔고증명서 발급 시 2,000원' → 선택 (증명서 = 잔고증명서, 하위 개념 포함).\n"
        "- 절차·수치·규정·메뉴경로 중 하나라도 답변에 **부분적으로라도** 쓰일 수 있으면 선택.\n"
        "- 완전 다른 도메인만 제외 (예: '수수료' 질문 + '공모주 청약 절차' 청크 → 제외).\n"
        "\n"
        "selected 가 빈 배열 허용 조건 (보수적으로):\n"
        "- 후보 청크 전체가 질문의 주제와 완전히 다른 영역인 경우에만.\n"
        "- 조금이라도 관련 있는 청크가 하나라도 있으면 selected 에 포함하고, summary 에 한정 범위 명시.\n"
        "- 확실하지 않으면 **포함** 쪽으로. 최종 답변 생성은 다음 LLM 이 하므로, 여기서 과도하게 걸러내면 답변 LLM 이 '참고자료에 없다' 로 회피하게 된다.\n"
        "\n"
        "작성 규칙:\n"
        "- 후보에 없는 내용은 절대 추가하지 말 것.\n"
        "- summary 는 핵심 사실만 한국어로 (최대 400자, 불필요한 도입/맺음 문장 금지).\n"
        "- 청크 인용은 [ref_num] 형태로 summary 안에 명시.\n"
        "- rationale 은 한 문장 (최대 80자)."
    )
    user_prompt = (
        f"## 사용자 질문\n{query}\n\n"
        f"## 후보 청크 ({len(candidates)}개)\n{candidates_text}\n\n"
        "위 후보 중 질문에 답하는 데 실제로 필요한 청크만 선택하고, 그 청크들의 핵심 사실을 정제해 summary 로 작성하시오."
    )

    start = time.monotonic()
    try:
        resp = await llm_router.route(
            task=LLMTask.RAG_GENERATION,
            request=LLMRequest(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=1500,  # 한국어 summary + JSON overhead 충분히
                temperature=0.1,
                guided_json=DISTILL_JSON_SCHEMA,
            ),
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            logger.warning("distill_json_parse_failed", text_preview=resp.text[:200])
            return None, _count_tokens(resp.text), latency_ms

        distilled = DistilledContext(
            selected_refs=[int(x) for x in data.get("selected", []) if isinstance(x, (int, float))],
            summary=str(data.get("summary", "")).strip(),
            rationale=str(data.get("rationale", "")).strip(),
        )
        return distilled, _count_tokens(resp.text), latency_ms
    except Exception as exc:
        logger.warning("distill_step_failed", error=str(exc))
        return None, 0, int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# GET /rag/models — 사용 가능한 LLM 모델 목록
# ---------------------------------------------------------------------------


@router.get("/models", summary="사용 가능한 LLM 모델 목록")
async def list_rag_models() -> ApiResponse[dict]:
    """RAG 답변 생성에 사용할 수 있는 LLM 모델 목록을 반환한다."""
    models = [
        {"id": "auto", "name": "Auto (기본)", "provider": "auto"},
    ]

    # LLM 라우터에서 실제 사용 가능한 모델 목록을 가져온다
    try:
        from src.common.llm.router import llm_router

        if hasattr(llm_router, "available_providers"):
            for provider in llm_router.available_providers():
                models.append(
                    {
                        "id": provider.model_id,
                        "name": provider.display_name,
                        "provider": provider.provider_name,
                    }
                )
    except (ImportError, Exception):
        pass

    # 기본 모델 목록 (LLM 라우터 미구동 시 fallback)
    if len(models) == 1:
        models.extend(
            [
                {
                    "id": "gemma-4-26b-a4b",
                    "name": "Gemma 4 26B MoE (AWQ-4bit)",
                    "provider": "vllm",
                },
            ]
        )

    return ApiResponse(data={"models": models})


# ---------------------------------------------------------------------------
# POST /rag/context — RAG 컨텍스트 검색 (alias for /rag/retrieve)
# ---------------------------------------------------------------------------


@router.post(
    "/context",
    response_model=ApiResponse[RAGRetrieveResponse],
    summary="RAG 컨텍스트 검색 (alias)",
)
async def rag_context(
    body: RAGRetrieveRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RAGRetrieveResponse]:
    """POST /rag/retrieve의 alias. V2 프론트엔드 호환용."""
    return await rag_retrieve(body=body, tenant_id=tenant_id, user_id=user_id, db=db)


# ---------------------------------------------------------------------------
# POST /rag/retrieve
# ---------------------------------------------------------------------------


@router.post(
    "/retrieve",
    response_model=ApiResponse[RAGRetrieveResponse],
    summary="RAG 컨텍스트 검색 (토큰 예산 기반)",
)
async def rag_retrieve(
    body: RAGRetrieveRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RAGRetrieveResponse]:
    """토큰 예산 내에서 RAG 컨텍스트를 검색하여 반환한다.

    Knowledge Search와 달리:
    - 결과 수가 적다 (3-5건, 최대 10건)
    - 토큰 예산을 엄격히 준수한다 (기본 2000, 최대 8000)
    - pagination 없음 — 항상 예산 내 결과만 반환
    - 선택적 청크 압축으로 더 많은 맥락을 포함 가능

    호출측이 자체 LLM을 사용할 때 이 API로 컨텍스트만 가져간다.
    """
    start = time.monotonic()
    intent_info: IntentInfo | None = None

    search_svc = await _get_search_service()
    if search_svc is not None:
        try:
            from src.search.intent_classifier import classify_intent, log_intent_decision
            from src.search.models import SearchRequest as SearchServiceRequest

            # tenant_slug 조회
            from src.core.services.tenant_service import TenantService

            tenant_svc = TenantService(db)
            tenant = await tenant_svc.get_by_id(tenant_id)
            tenant_slug = tenant.slug

            svc_request = SearchServiceRequest(
                query=body.query,
                repository_id=body.repository_id,
                tenant_id=tenant_id,
                category_ids=body.category_ids,
                document_type_ids=body.document_type_ids,
                top_k=body.top_k,
                search_mode="hybrid",
                rerank=body.enable_rerank,
                include_content=True,
                weights=_build_search_weights(body.weights),
                use_hyde=getattr(body, "use_hyde", False),
                auto_intent=getattr(body, "auto_intent", False),
                enable_llm_rewrite=getattr(body, "enable_llm_rewrite", False),
            )

            # Cross-tenant: linked tenant 저장소 포함
            if body.include_linked_tenants:
                linked_repos = await _resolve_linked_repositories(user_id, tenant_id, db)
                if linked_repos:
                    base_repos = [body.repository_id] if body.repository_id else []
                    svc_request.repository_ids = base_repos + linked_repos
                    svc_request.repository_id = None  # repository_ids 우선
                    logger.info(
                        "rag_retrieve_cross_tenant",
                        linked_repo_count=len(linked_repos),
                        total_repos=len(svc_request.repository_ids),
                    )

            # Intent gate — 일상 대화는 검색 skip
            if body.enable_intent_gate:
                domain_description = None
                try:
                    from src.core.models.repository import Repository

                    if body.repository_id:
                        repo = await db.get(Repository, body.repository_id)
                        if repo and repo.description:
                            domain_description = repo.description
                except Exception:
                    pass
                intent_result = await classify_intent(body.query, None, domain_description)
                await log_intent_decision(
                    db=db,
                    query=body.query,
                    conversation_history=None,
                    result=intent_result,
                    tenant_id=tenant_id,
                )
                if not intent_result.search:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    return ApiResponse(
                        data=RAGRetrieveResponse(
                            context="",
                            sources=[],
                            token_count=0,
                            max_context_tokens=body.max_context_tokens,
                            latency_ms=elapsed_ms,
                            intent=IntentInfo(
                                search=False,
                                reason=intent_result.reason,
                                latency_ms=intent_result.latency_ms,
                                skipped=True,
                            ),
                        )
                    )
                intent_info = IntentInfo(
                    search=True,
                    reason=intent_result.reason,
                    latency_ms=intent_result.latency_ms,
                    skipped=False,
                )

            svc_response = await search_svc.search(
                request=svc_request,
                tenant_slug=tenant_slug,
            )

            context, sources, token_count = await _assemble_rag_context(
                hits=svc_response.results,
                max_context_tokens=body.max_context_tokens,
                compress=body.compress,
                db=db,
            )

            # 프롬프트 템플릿 생성
            prompt_template = (
                "다음 참고자료를 기반으로 질문에 답변하세요.\n"
                "참고자료에 없는 내용은 생성하지 마세요.\n\n"
                f"## 참고자료\n\n{context}\n\n"
                f"## 질문\n\n{body.query}\n\n"
                "위 참고자료만을 근거로 답변하세요."
            )

            elapsed_ms = int((time.monotonic() - start) * 1000)

            return ApiResponse(
                data=RAGRetrieveResponse(
                    context=context,
                    sources=sources,
                    token_count=token_count,
                    max_context_tokens=body.max_context_tokens,
                    prompt_template=prompt_template,
                    latency_ms=elapsed_ms,
                    intent=intent_info,
                )
            )
        except Exception as exc:
            logger.warning("rag_retrieve_service_error", error=str(exc))

    # 서비스 미구현 시 빈 응답
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return ApiResponse(
        data=RAGRetrieveResponse(
            context="",
            sources=[],
            token_count=0,
            max_context_tokens=body.max_context_tokens,
            latency_ms=elapsed_ms,
        )
    )


# ---------------------------------------------------------------------------
# POST /rag/answer
# ---------------------------------------------------------------------------


@router.post(
    "/answer",
    response_model=ApiResponse[RAGAnswerResponse],
    summary="RAG 답변 생성 (컨텍스트 검색 + LLM 답변)",
)
async def rag_answer(
    body: RAGAnswerRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RAGAnswerResponse]:
    """RAG 컨텍스트 검색 + LLM 답변 생성을 한 번에 수행한다.

    1. 토큰 예산 기반 컨텍스트 검색 (rag_retrieve와 동일)
    2. 대화 히스토리 반영
    3. LLM을 통한 답변 생성
    4. 토큰 사용량 상세 반환
    """
    start = time.monotonic()
    retrieval_latency_ms = 0
    selection_latency_ms = 0
    generation_latency_ms = 0
    distilled: DistilledContext | None = None
    sources_all: list[RAGSource] = []
    distill_completion_tokens = 0
    intent_info: IntentInfo | None = None

    # 1. 컨텍스트 검색
    search_svc = await _get_search_service()
    context = ""
    sources: list[RAGSource] = []
    context_tokens = 0
    confidence = 0.0

    if search_svc is not None:
        try:
            import asyncio

            from src.search.intent_classifier import classify_intent, log_intent_decision
            from src.search.models import SearchRequest as SearchServiceRequest

            from src.core.services.tenant_service import TenantService

            tenant_svc = TenantService(db)
            tenant = await tenant_svc.get_by_id(tenant_id)
            tenant_slug = tenant.slug

            # distill 활성 시 더 넓은 후보 풀에서 LLM 이 선택하도록 top_k 확장
            effective_top_k = max(body.top_k, body.distill_pool_size) if body.distill else body.top_k
            # 대화 히스토리를 검색 단계에도 전달 — enable_llm_rewrite=True 시 쿼리 재작성에 사용됨
            history_for_search = (
                [{"role": t.role, "content": t.content} for t in body.conversation_history]
                if body.conversation_history else None
            )
            svc_request = SearchServiceRequest(
                query=body.query,
                repository_id=body.repository_id,
                tenant_id=tenant_id,
                category_ids=body.category_ids,
                document_type_ids=body.document_type_ids,
                top_k=effective_top_k,
                search_mode="hybrid",
                rerank=body.enable_rerank,
                include_content=True,
                weights=_build_search_weights(body.weights),
                use_hyde=getattr(body, "use_hyde", False),
                auto_intent=getattr(body, "auto_intent", False),
                enable_llm_rewrite=getattr(body, "enable_llm_rewrite", False),
                conversation_history=history_for_search,
            )

            # Cross-tenant: linked tenant 저장소 포함
            if body.include_linked_tenants:
                linked_repos = await _resolve_linked_repositories(user_id, tenant_id, db)
                if linked_repos:
                    base_repos = [body.repository_id] if body.repository_id else []
                    svc_request.repository_ids = base_repos + linked_repos
                    svc_request.repository_id = None
                    logger.info(
                        "rag_answer_cross_tenant",
                        linked_repo_count=len(linked_repos),
                        total_repos=len(svc_request.repository_ids),
                    )

            retrieval_start = time.monotonic()

            # ── Intent gate + 검색 병렬 실행 ──
            # 일상 대화(인사/날씨/감정)는 검색+LLM 생성 모두 건너뛰어 소음 제거.
            # 병렬 실행으로 지식 질의 latency 증가 최소화 (classifier 400-900ms).
            if body.enable_intent_gate:
                domain_description = None
                try:
                    from src.core.models.repository import Repository

                    if body.repository_id:
                        repo = await db.get(Repository, body.repository_id)
                        if repo and repo.description:
                            domain_description = repo.description
                    elif getattr(svc_request, "repository_ids", None):
                        descs = []
                        for rid in svc_request.repository_ids:
                            r = await db.get(Repository, rid)
                            if r and r.description:
                                descs.append(f"- {r.name}: {r.description}")
                        if descs:
                            domain_description = "\n".join(descs)
                except Exception as exc:
                    logger.debug("rag_answer_repo_desc_load_failed", error=str(exc))

                history_for_intent = history_for_search
                intent_task = asyncio.create_task(
                    classify_intent(body.query, history_for_intent, domain_description)
                )
                search_task = asyncio.create_task(
                    search_svc.search(request=svc_request, tenant_slug=tenant_slug)
                )
                intent_result = await intent_task
                await log_intent_decision(
                    db=db,
                    query=body.query,
                    conversation_history=history_for_intent,
                    result=intent_result,
                    tenant_id=tenant_id,
                )

                if not intent_result.search:
                    # 일상 대화/도메인 외 — 검색/LLM 생성 skip, 안내 문구 반환
                    search_task.cancel()
                    try:
                        await search_task
                    except (asyncio.CancelledError, Exception):
                        pass  # 취소/에러 모두 흡수 — skip 응답이 목표
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    return ApiResponse(data=RAGAnswerResponse(
                        answer="일상 대화입니다.",
                        sources=[],
                        sources_all=[],
                        confidence=0.0,
                        token_usage=TokenUsage(),
                        latency_ms=elapsed_ms,
                        intent=IntentInfo(
                            search=False,
                            reason=intent_result.reason,
                            latency_ms=intent_result.latency_ms,
                            skipped=True,
                        ),
                    ))

                intent_info = IntentInfo(
                    search=True,
                    reason=intent_result.reason,
                    latency_ms=intent_result.latency_ms,
                    skipped=False,
                )
                svc_response = await search_task
            else:
                svc_response = await search_svc.search(
                    request=svc_request,
                    tenant_slug=tenant_slug,
                )

            # 후보 전체 (sources_all) — 토큰 예산 크게 잡아서 풀 보존
            pool_budget = max(body.max_context_tokens * 4, 8000) if body.distill else body.max_context_tokens
            _ctx_pool, sources_all, _tok_pool = await _assemble_rag_context(
                hits=svc_response.results,
                max_context_tokens=pool_budget,
                compress=False,  # 정제 LLM 이 직접 요약하므로 사전 압축 불필요
                db=db,
            )
            retrieval_latency_ms = int((time.monotonic() - retrieval_start) * 1000)

            if svc_response.results:
                confidence = svc_response.results[0].score

            # 기본 sources 는 전체 후보 — distill 에서 좁혀짐
            sources = sources_all
            context = _ctx_pool
            context_tokens = _tok_pool

        except Exception as exc:
            logger.warning("rag_answer_search_error", error=str(exc))

    # 2. 검색 결과 없으면 fallback
    if not sources:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ApiResponse(
            data=RAGAnswerResponse(
                answer="해당 내용에 대한 정보를 찾을 수 없습니다. 다른 키워드로 검색하거나 질문을 구체적으로 해 주세요.",
                sources=[],
                sources_all=[],
                confidence=0.0,
                token_usage=TokenUsage(),
                latency_ms=elapsed_ms,
                intent=intent_info,
            )
        )

    # 2.5 LLM 정제 단계 (distill=True 시): 후보들에서 답변 관련 청크 선택+요약
    if body.distill and sources_all and search_svc is not None:
        # 풀 컨텍스트 (full content) 사전 구축 — RAGSource.content 는 200자 컷
        full_contents: dict[int, str] = {}
        for hit in svc_response.results:
            # ref_num 은 _assemble_rag_context 에서 1-indexed 로 부여됨
            pass
        # rank 와 sources_all 를 1:1 매핑 (assemble 도 동일 enumerate(start=1))
        for idx, hit in enumerate(svc_response.results, 1):
            full_contents[idx] = hit.content or ""

        distilled, distill_completion_tokens, selection_latency_ms = await _distill_context(
            query=body.query,
            candidates=sources_all,
            full_contents=full_contents,
        )

        # 정제 성공 → sources 를 선택된 것만으로 좁힘
        if distilled and distilled.selected_refs:
            selected_set = set(distilled.selected_refs)
            sources = [s for s in sources_all if s.ref_num in selected_set]
            if not sources:
                # 선택이 sources_all 범위 밖이면 fallback: 전체 사용
                sources = sources_all
        # 정제 실패 / 빈 선택 → sources_all 그대로 사용

    # 2.7 with_answer=False: 정제 결과만 반환하고 종료 (외부 LLM 사용 시)
    if not body.with_answer:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ApiResponse(
            data=RAGAnswerResponse(
                answer="",
                distilled=distilled,
                sources=sources,
                sources_all=sources_all,
                confidence=round(confidence, 4),
                token_usage=TokenUsage(
                    context_tokens=context_tokens,
                    prompt_tokens=0,
                    completion_tokens=distill_completion_tokens,
                    total_tokens=distill_completion_tokens,
                ),
                latency_ms=elapsed_ms,
                retrieval_latency_ms=retrieval_latency_ms,
                selection_latency_ms=selection_latency_ms,
                generation_latency_ms=0,
                intent=intent_info,
            )
        )

    # 3. 대화 히스토리 반영 프롬프트 구성
    system_prompt = (
        "당신은 AICM 지식관리 플랫폼의 AI 어시스턴트입니다.\n"
        "아래 제공된 참고자료를 바탕으로 사용자의 질문에 정확하고 유용하게 답변하세요.\n\n"
        "규칙:\n"
        "1. 참고자료에 없는 내용을 임의로 생성하지 마세요.\n"
        "2. 답변의 근거가 되는 문서를 [1], [2] 형태로 인용하세요.\n"
        "3. 정보가 불충분하면 솔직하게 알려주세요.\n"
        "4. 간결하고 명확하게 답변하세요.\n"
        "5. '## 원본 표' 섹션이 제공된 경우 표의 모든 관련 행을 빠짐없이 검토하고, "
        "질문에 해당하는 행을 *하나도 누락하지 않고* 답변에 반영하세요. "
        "표를 자의로 요약하거나 일부 행만 발췌하지 마세요."
    )

    # 대화 히스토리 포맷
    history_text = ""
    if body.conversation_history:
        history_parts = []
        for turn in body.conversation_history:
            role_label = "사용자" if turn.role == "user" else "AI"
            history_parts.append(f"[{role_label}] {turn.content}")
        history_text = "\n\n이전 대화:\n" + "\n".join(history_parts) + "\n"

    # 정제 결과가 있으면 정제된 summary 를 컨텍스트로 사용 (좁고 정확).
    # 단 table block_type 인 sources 는 distill 우회 — 원본 markdown 표를 그대로
    # answer LLM 에 전달. 메모리 [[feedback_kms_lukas_separation]] 절칙:
    # KMS retrieval 결과 *재해석/후가공 금지*. distill 의 400자 요약이 표 행을
    # 누락시키는 사고 (사용자 검증 2026-05-18 — p.143 표 4행 중 2행만 답변) 직접 fix.
    # GPT-5.5 적대 리뷰 보강 (2026-05-18):
    # - selected_refs 교차 가드 (line 881 이 이미 selected 만 남기지만 idempotent 가드)
    # - budget cap (표별 / 총 char 상한 — gemma-31b 32k context 의 ~1/3 한계)
    # - dedup 강화 (chunk_id + normalized content hash — 중복 색인 docs 의 동일 표 차단)
    # - markdown table validation (|--- separator + |-cell 헤더)
    # - observability (rag_table_raw_injected structured log)
    def _is_markdown_table(text: str) -> bool:
        # 검증 — 헤더 + separator + column count 일치 + 각 separator cell 이
        # 정규 markdown 패턴 (:---/---/:---:) 와 fullmatch (빈 cell 도 거부).
        lines = [ln for ln in (text or "").split("\n") if ln.strip()]
        if len(lines) < 2:
            return False
        header_cells = [c.strip() for c in lines[0].strip().strip("|").split("|")]
        sep_cells = [c.strip() for c in lines[1].strip().strip("|").split("|")]
        if len(header_cells) < 2 or len(sep_cells) != len(header_cells):
            return False
        return all(_TABLE_SEP_CELL_RE.fullmatch(c) for c in sep_cells)

    def _truncate_table_by_rows(text: str, max_chars: int) -> tuple[str | None, bool]:
        # 행 단위 truncate — 행 중간 절단 방지. 헤더 + separator 보존.
        # 헤더+sep 만으로 cap 초과면 (None, True) — caller 가 표 자체 skip.
        if len(text) <= max_chars:
            return text, False
        lines = text.split("\n")
        if len(lines) < 2:
            return None, True
        header_sep_len = len(lines[0]) + len(lines[1]) + 1
        if header_sep_len > max_chars:
            return None, True
        kept: list[str] = [lines[0], lines[1]]
        kept_chars = header_sep_len
        for ln in lines[2:]:
            if kept_chars + len(ln) + 1 > max_chars:
                break
            kept.append(ln)
            kept_chars += len(ln) + 1
        return "\n".join(kept), True

    def _norm_hash(text: str) -> str:
        import hashlib
        norm = " ".join((text or "").split())
        return hashlib.sha1(norm.encode("utf-8", "ignore")).hexdigest()

    if distilled and distilled.summary:
        parts = [distilled.summary]
        # distiller selected_refs 가 비어 있으면 table raw injection 자체 비활성
        # — distiller 가 관련 표를 찾지 못한 경우 무차별 주입 방지.
        selected_refs_set: set = {
            str(x) for x in (distilled.selected_refs or [])
        }
        seen_keys: set = set()
        seen_hashes: set = set()
        table_blocks: list[str] = []
        any_truncated = False
        any_oversized_skip = False
        table_chars_total = 0
        skipped_nontable = 0
        skipped_empty = 0
        skipped_not_selected = 0
        skipped_invalid_md = 0
        skipped_dedup = 0
        skipped_budget = 0
        # selected_refs 비었으면 진입 자체 안 함 (불필요 메모리 복제도 회피)
        for src in (sources if selected_refs_set else ()):
            if (src.block_type or "").strip().lower() != "table":
                skipped_nontable += 1
                continue
            if not src.full_content:
                skipped_empty += 1
                continue
            if str(src.ref_num) not in selected_refs_set:
                skipped_not_selected += 1
                continue
            if not _is_markdown_table(src.full_content):
                skipped_invalid_md += 1
                continue
            # dedup: (document_id, chunk_id) 조합 + normalized content hash.
            # chunk_id 가 None 이 아닐 때만 doc_chunk key 사용 (0/빈문자열도 valid key).
            doc_chunk_key = (
                f"{src.document_id}:{src.chunk_id}"
                if src.chunk_id is not None
                else None
            )
            content_key = _norm_hash(src.full_content)
            if doc_chunk_key is not None and doc_chunk_key in seen_keys:
                skipped_dedup += 1
                continue
            if content_key in seen_hashes:
                skipped_dedup += 1
                continue
            body_text, truncated_per = _truncate_table_by_rows(
                src.full_content, TABLE_RAW_MAX_CHARS_PER
            )
            # 헤더+sep 만으로 cap 초과한 극단 케이스 — 명시 로깅 + 그대로 진행
            if truncated_per and len(body_text) > TABLE_RAW_MAX_CHARS_PER:
                any_oversized_skip = True
            label = f"[{src.ref_num}] {src.document_title}"
            if src.section_title:
                label += f" > {src.section_title}"
            if src.page_info:
                label += f" ({src.page_info})"
            if truncated_per:
                label += " (일부 행만 포함 — 표가 큼)"
                any_truncated = True
            # budget cap — 최종 block string 길이 (label + body) 기준
            block_text = f"{label}\n{body_text}"
            if table_chars_total + len(block_text) > TABLE_RAW_MAX_CHARS_TOTAL:
                skipped_budget += 1
                continue
            if doc_chunk_key is not None:
                seen_keys.add(doc_chunk_key)
            seen_hashes.add(content_key)
            table_blocks.append(block_text)
            table_chars_total += len(block_text)
        if table_blocks:
            header = (
                "## 원본 표 (행 단위 전부 포함 — 빠짐없이 인용할 것)"
                if not any_truncated
                else "## 원본 표 (일부 표는 행 일부만 포함됨 — 포함된 행은 빠짐없이 인용할 것)"
            )
            parts.append("\n\n" + header + "\n\n" + "\n\n---\n\n".join(table_blocks))
        logger.info(
            "rag_table_raw_injected",
            included=len(table_blocks),
            total_chars=table_chars_total,
            any_truncated=any_truncated,
            any_oversized_skip=any_oversized_skip,
            skipped_nontable=skipped_nontable,
            skipped_empty=skipped_empty,
            skipped_not_selected=skipped_not_selected,
            skipped_invalid_md=skipped_invalid_md,
            skipped_dedup=skipped_dedup,
            skipped_budget=skipped_budget,
            selected_refs_count=len(selected_refs_set),
        )
        answer_context = "\n".join(parts)
    else:
        answer_context = context

    user_prompt = (
        f"## 참고자료\n\n{answer_context}\n\n"
        f"{history_text}"
        f"## 질문\n\n{body.query}\n\n"
        "위 참고자료만을 근거로 답변하세요."
    )

    prompt_tokens = _count_tokens(system_prompt) + _count_tokens(user_prompt)

    # 4. LLM 답변 생성
    answer = ""
    model_used = None
    completion_tokens = 0

    generation_start = time.monotonic()
    try:
        from src.common.llm.base import LLMRequest, LLMTask
        from src.common.llm.router import llm_router

        llm_response = await llm_router.route(
            task=LLMTask.RAG_GENERATION,
            request=LLMRequest(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=body.max_answer_tokens,
                temperature=body.temperature,
            ),
        )
        answer = llm_response.text
        model_used = llm_response.model
        completion_tokens = _count_tokens(answer)
        generation_latency_ms = int((time.monotonic() - generation_start) * 1000)
    except Exception as exc:
        logger.error("rag_answer_llm_error", error=str(exc))
        # LLM 실패 시 context-only fallback: 근거 문서를 직접 제시
        fallback_parts = ["LLM 답변 생성에 실패하여 검색된 근거 문서를 직접 제공합니다.\n"]
        for src in sources:
            label = f"[{src.ref_num}] {src.document_title}"
            if src.section_title:
                label += f" > {src.section_title}"
            fallback_parts.append(label)
        answer = "\n".join(fallback_parts)
        model_used = "fallback (context-only)"

    # 5. 환각 감지 (verify_facts=True일 때만)
    fact_check_score = None
    verdict = None
    unsupported_claims = None

    # 환각 감지: 명시 요청 OR 신뢰도 0.55 미만이면 자동 수행
    _HALLUC_AUTO_THRESHOLD = 0.55
    _need_fact_check = (
        (body.verify_facts or confidence < _HALLUC_AUTO_THRESHOLD)
        and answer
        and model_used != "fallback (context-only)"
    )
    if _need_fact_check:
        try:
            from src.api.services.hallucination_detector import hallucination_detector

            # sources를 dict 목록으로 변환
            sources_dicts = [
                {
                    "document_title": s.document_title,
                    "section_title": s.section_title,
                    "content": s.content or "",
                }
                for s in sources
            ]

            hallucination_result = await hallucination_detector.detect(
                answer=answer,
                sources=sources_dicts,
                query=body.query,
            )

            fact_check_score = hallucination_result.fact_check_score
            verdict = hallucination_result.verdict

            # verdict != "supported"일 때만 unsupported_claims 포함
            if verdict != "supported" and hallucination_result.unsupported_claims:
                unsupported_claims = [
                    UnsupportedClaimResponse(claim=c.claim, reason=c.reason)
                    for c in hallucination_result.unsupported_claims
                ]

            # hallucinated 판정 시 답변에 경고 추가
            if verdict == "hallucinated":
                answer = await hallucination_detector.get_safe_answer(
                    answer, hallucination_result
                )

            logger.info(
                "rag_fact_check_complete",
                query=body.query[:50],
                verdict=verdict,
                fact_check_score=fact_check_score,
            )
        except Exception as exc:
            logger.warning("rag_fact_check_error", error=str(exc))
            # 환각 감지 실패 시 결과 없이 진행

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # 감사 로그: RAG 답변 생성
    record_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action="SEARCH",
        resource_type="document",
        detail={
            "query": body.query,
            "source_count": len(sources),
            "model_used": model_used,
            "confidence": round(confidence, 4),
            "latency_ms": elapsed_ms,
            "rag_mode": "answer",
            "fact_check_score": fact_check_score,
            "verdict": verdict,
        },
    )

    return ApiResponse(
        data=RAGAnswerResponse(
            answer=answer,
            distilled=distilled,
            sources=sources,
            sources_all=sources_all,
            confidence=round(confidence, 4),
            model_used=model_used,
            token_usage=TokenUsage(
                context_tokens=context_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens + distill_completion_tokens,
                total_tokens=prompt_tokens + completion_tokens + distill_completion_tokens,
            ),
            latency_ms=elapsed_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            selection_latency_ms=selection_latency_ms,
            generation_latency_ms=generation_latency_ms,
            fact_check_score=fact_check_score,
            verdict=verdict,
            unsupported_claims=unsupported_claims,
            intent=intent_info,
        )
    )


# ---------------------------------------------------------------------------
# POST /rag/stream — SSE 기반 RAG 스트리밍
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    response_model=ApiResponse[RAGGenerateResponse],
    summary="RAG 답변 생성 (정제된 컨텍스트로 LLM 호출만 수행)",
)
async def rag_generate(
    body: RAGGenerateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[RAGGenerateResponse]:
    """미리 정제/요약된 컨텍스트만 받아 LLM 답변 생성.

    프론트의 점진 표시 패턴에 사용:
    1) /rag/answer with_answer=false → distilled.summary 받기
    2) /rag/generate context=distilled.summary → 답변만 빠르게 받기
    """
    from src.common.llm.base import LLMRequest, LLMTask
    from src.common.llm.router import llm_router

    system_prompt = (
        "당신은 AICM 지식관리 플랫폼의 AI 어시스턴트입니다.\n"
        "아래 제공된 정제된 참고자료를 바탕으로 사용자의 질문에 정확하고 간결하게 답변하세요.\n\n"
        "규칙:\n"
        "1. 참고자료에 없는 내용을 임의로 생성하지 마세요.\n"
        "2. 답변의 근거가 되는 청크를 [1], [2] 형태로 인용하세요.\n"
        "3. 정보가 불충분하면 솔직하게 알려주세요.\n"
        "4. 간결하고 명확하게 답변하세요."
    )

    history_text = ""
    if body.conversation_history:
        parts = [f"[{('사용자' if t.role == 'user' else 'AI')}] {t.content}" for t in body.conversation_history]
        history_text = "\n\n이전 대화:\n" + "\n".join(parts) + "\n"

    user_prompt = (
        f"## 참고자료\n\n{body.context}\n\n"
        f"{history_text}"
        f"## 질문\n\n{body.query}\n\n"
        "위 참고자료만을 근거로 답변하세요."
    )

    start = time.monotonic()
    try:
        resp = await llm_router.route(
            task=LLMTask.RAG_GENERATION,
            request=LLMRequest(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=body.max_answer_tokens,
                temperature=body.temperature,
            ),
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        prompt_tokens = _count_tokens(system_prompt) + _count_tokens(user_prompt)
        completion_tokens = _count_tokens(resp.text)
        return ApiResponse(
            data=RAGGenerateResponse(
                answer=resp.text,
                model_used=resp.model,
                token_usage=TokenUsage(
                    context_tokens=_count_tokens(body.context),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
                generation_latency_ms=latency_ms,
            )
        )
    except Exception as exc:
        logger.error("rag_generate_llm_error", error=str(exc))
        return ApiResponse(
            data=RAGGenerateResponse(
                answer=f"LLM 답변 생성에 실패했습니다: {exc}",
                model_used="error",
                generation_latency_ms=int((time.monotonic() - start) * 1000),
            )
        )


@router.post(
    "/stream",
    summary="RAG 답변 스트리밍 (SSE)",
    description=(
        "Server-Sent Events 로 RAG 답변을 토큰 단위 스트리밍한다. "
        "응답은 `text/event-stream` — Swagger 의 'Try it out' 으로는 정확히 표시되지 "
        "않을 수 있다. 클라이언트는 `EventSource` 또는 `fetch` + `ReadableStream` 사용.\n\n"
        "이벤트 종류:\n"
        "- `retrieval` — 검색 완료, sources 동봉\n"
        "- `distill` — 정제 결과 (distill=True 시)\n"
        "- `token` — 답변 토큰 chunk\n"
        "- `done` — 종료 + 최종 메트릭"
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE 스트림 (text/event-stream)",
            "content": {
                "text/event-stream": {
                    "example": (
                        "event: retrieval\ndata: {\"sources\": [...]}\n\n"
                        "event: token\ndata: {\"delta\": \"연차는 \"}\n\n"
                        "event: done\ndata: {\"latency_ms\": 1842}\n\n"
                    )
                }
            },
        }
    },
)
async def rag_stream(
    body: RAGAnswerRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """RAG 답변을 Server-Sent Events로 스트리밍한다.

    이벤트 순서:
    1. event: sources — 근거 문서 목록 (검색 즉시)
    2. event: token — 답변 토큰 (LLM 생성 중)
    3. event: done — 최종 메타데이터 (token_usage, model_used, confidence)
    4. event: error — 오류 발생 시
    """
    async def event_generator():
        start = time.monotonic()

        # 0. Intent gate — 일상 대화면 LLM/검색 호출 없이 안내 문구만 내려보냄
        if body.enable_intent_gate:
            try:
                from src.search.intent_classifier import classify_intent, log_intent_decision

                history_for_intent = (
                    [{"role": t.role, "content": t.content} for t in body.conversation_history]
                    if body.conversation_history else None
                )
                domain_description = None
                try:
                    from src.core.models.repository import Repository

                    if body.repository_id:
                        repo = await db.get(Repository, body.repository_id)
                        if repo and repo.description:
                            domain_description = repo.description
                except Exception:
                    pass

                intent_result = await classify_intent(
                    body.query, history_for_intent, domain_description
                )
                await log_intent_decision(
                    db=db,
                    query=body.query,
                    conversation_history=history_for_intent,
                    result=intent_result,
                    tenant_id=tenant_id,
                )

                if not intent_result.search:
                    yield _sse("intent", {
                        "search": False,
                        "reason": intent_result.reason,
                        "latency_ms": intent_result.latency_ms,
                        "skipped": True,
                    })
                    yield _sse("sources", {"sources": [], "confidence": 0.0})
                    yield _sse("token", {"text": "일상 대화입니다."})
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    yield _sse("done", {
                        "model_used": None,
                        "confidence": 0.0,
                        "token_usage": {
                            "context_tokens": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                        "latency_ms": elapsed_ms,
                    })
                    return
            except Exception as exc:
                # 분류기 실패해도 스트리밍 진행 — search.py 와 동일한 보수적 정책
                logger.warning("rag_stream_intent_gate_failed", error=str(exc))

        # 1. 검색 + 컨텍스트 조립
        try:
            search_svc = await _get_search_service()
            if search_svc is None:
                yield _sse("error", {"message": "검색 서비스를 사용할 수 없습니다."})
                return

            from src.search.models import SearchRequest

            search_request = SearchRequest(
                query=body.query,
                repository_id=body.repository_id,
                tenant_id=tenant_id,
                top_k=body.top_k,
                search_mode="hybrid",
                rerank=body.enable_rerank,
                include_content=True,
                weights=_build_search_weights(body.weights),
            )

            # Cross-tenant: linked tenant 저장소 포함
            if body.include_linked_tenants:
                linked_repos = await _resolve_linked_repositories(user_id, tenant_id, db)
                if linked_repos:
                    base_repos = [body.repository_id] if body.repository_id else []
                    search_request.repository_ids = base_repos + linked_repos
                    search_request.repository_id = None
                    logger.info(
                        "rag_stream_cross_tenant",
                        linked_repo_count=len(linked_repos),
                        total_repos=len(search_request.repository_ids),
                    )

            # tenant_slug 조회 (UUID → slug 변환)
            _stream_slug = str(tenant_id)
            try:
                from sqlalchemy import text as _text
                _slug_r = await db.execute(
                    _text("SELECT slug FROM tenants WHERE id = :tid"),
                    {"tid": str(tenant_id)},
                )
                _slug_row = _slug_r.fetchone()
                if _slug_row:
                    _stream_slug = _slug_row[0]
            except Exception:
                pass

            results, _, _, _, _ = await search_svc._execute_pipeline(
                request=search_request,
                tenant_slug=_stream_slug,
            )

            # 저장소 한정으로 결과 부족 → 테넌트 전체로 확장 (폴백)
            if len(results) < 3 and search_request.repository_id is not None:
                logger.info(
                    "rag_stream_repo_fallback",
                    initial_results=len(results),
                    repository_id=str(search_request.repository_id),
                )
                expanded_request = search_request.model_copy(
                    update={"repository_id": None, "repository_ids": None}
                )
                expanded_results, _, _, _, _ = await search_svc._execute_pipeline(
                    request=expanded_request,
                    tenant_slug=_stream_slug,
                )
                if len(expanded_results) > len(results):
                    results = expanded_results
                    logger.info(
                        "rag_stream_repo_fallback_expanded",
                        expanded_results=len(results),
                    )

            if not results:
                yield _sse("sources", {"sources": []})
                yield _sse("token", {"text": "검색 결과가 없어 답변을 생성할 수 없습니다."})
                yield _sse("done", {"confidence": 0.0, "model_used": None})
                return

            context, sources, context_tokens = await _assemble_rag_context(
                hits=results,
                max_context_tokens=body.max_context_tokens,
                compress=body.compress,
                db=db,
            )
            confidence = results[0].score if results else 0.0

        except Exception as exc:
            logger.error("rag_stream_search_error", error=str(exc))
            yield _sse("error", {"message": f"검색 실패: {str(exc)}"})
            return

        # 2. sources 이벤트 즉시 전송 — 프론트가 근거 문서 패널을 먼저 렌더링
        sources_data = []
        for s in sources:
            sources_data.append({
                "ref_num": s.ref_num,
                "document_id": str(s.document_id),
                "chunk_id": str(s.chunk_id),
                "document_title": s.document_title,
                "section_title": s.section_title,
                "content": s.content,
                "score": s.score,
                "token_count": s.token_count,
                "page_info": s.page_info,
                "source_location": s.source_location,
            })
        yield _sse("sources", {"sources": sources_data, "confidence": round(confidence, 4)})

        # 3. LLM 스트리밍 (route_stream → 실제 토큰 단위 SSE)
        system_prompt = (
            "당신은 지식관리 플랫폼의 AI 어시스턴트입니다.\n"
            "참고자료에 [1], [2] 등의 번호가 부여되어 있습니다.\n"
            "답변 내에서 해당 내용의 근거를 인라인 인용 마커 [1], [2] 등으로 표시하세요.\n"
            "\n"
            "규칙:\n"
            "- 참고자료에 명시된 내용만 사용하여 답변하세요.\n"
            "- 참고자료에 없는 내용은 추측하지 말고, '참고자료에 명시되어 있지 않습니다'라고 답변하세요.\n"
            "- 확실하지 않은 경우 '참고자료에 따르면'으로 시작하여 인용 근거를 분명히 하세요."
        )
        user_prompt = f"## 참고자료\n\n{context}\n\n## 질문\n\n{body.query}"
        prompt_tokens = _count_tokens(system_prompt) + _count_tokens(user_prompt)
        completion_tokens = 0
        model_used = None
        full_answer_text = ""  # 환각 감지용 전체 답변 텍스트 누적

        try:
            from src.common.llm.base import LLMRequest, LLMTask
            from src.common.llm.router import llm_router

            req = LLMRequest(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=body.max_answer_tokens,
                temperature=body.temperature,
            )

            # route_stream: AsyncIterator[LLMStreamChunk] 반환 — 각 청크는 .text, .model 포함
            async for chunk in llm_router.route_stream(
                task=LLMTask.RAG_GENERATION,
                request=req,
            ):
                text = getattr(chunk, "text", "") or ""
                if text:
                    yield _sse("token", {"text": text})
                    full_answer_text += text
                    completion_tokens += _count_tokens(text)
                if model_used is None:
                    model_used = getattr(chunk, "model", None)

        except Exception as exc:
            logger.error("rag_stream_llm_error", error=str(exc))
            yield _sse("token", {
                "text": "LLM 답변 생성에 실패했습니다. 위 근거 문서를 직접 참고해 주세요.",
            })
            model_used = "fallback"

        # 4. 완료 이벤트
        elapsed_ms = int((time.monotonic() - start) * 1000)
        yield _sse("done", {
            "model_used": model_used,
            "confidence": round(confidence, 4),
            "token_usage": {
                "context_tokens": context_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "latency_ms": elapsed_ms,
        })

        # 5. 환각 감지 (조건부 실행)
        #   - verify_facts=True 로 명시 요청되었거나
        #   - 신뢰도(confidence)가 0.55 미만이어서 자동 검증이 필요한 경우
        _HALLUC_AUTO_THRESHOLD = 0.55
        need_fact_check = (
            (body.verify_facts or confidence < _HALLUC_AUTO_THRESHOLD)
            and full_answer_text
            and model_used != "fallback"
        )
        if need_fact_check:
            logger.info(
                "rag_stream_fact_check_triggered",
                confidence=round(confidence, 3),
                verify_facts_requested=body.verify_facts,
                auto_triggered=not body.verify_facts,
            )
        if need_fact_check:
            try:
                from src.api.services.hallucination_detector import hallucination_detector

                sources_dicts = [
                    {
                        "document_title": s.get("document_title", ""),
                        "section_title": s.get("section_title"),
                        "content": s.get("content", ""),
                    }
                    for s in sources_data
                ]

                h_result = await hallucination_detector.detect(
                    answer=full_answer_text,
                    sources=sources_dicts,
                    query=body.query,
                )

                fc_data: dict = {
                    "fact_check_score": h_result.fact_check_score,
                    "verdict": h_result.verdict,
                }
                if h_result.verdict != "supported" and h_result.unsupported_claims:
                    fc_data["unsupported_claims"] = [
                        {"claim": c.claim, "reason": c.reason}
                        for c in h_result.unsupported_claims
                    ]
                yield _sse("fact_check", fc_data)
            except Exception as exc:
                logger.warning("rag_stream_fact_check_error", error=str(exc))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict) -> str:
    """SSE 이벤트 포맷으로 변환.

    event 필드를 data JSON 내부에도 포함하여, raw fetch 기반 SSE 파서에서
    이벤트 타입을 식별할 수 있도록 한다.
    """
    payload = {**data, "event": event}
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
