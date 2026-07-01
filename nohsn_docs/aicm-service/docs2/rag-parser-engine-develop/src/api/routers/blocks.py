"""Block API 라우터 — 블럭 목록 조회, 상세, 수정, 재인덱싱, 유사 블럭 검색, 유효성 관리.

specs/06 5A 참조.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.block import BlockDetailResponse, BlockResponse, BlockUpdateRequest
from src.api.schemas.common import ApiResponse, PaginatedResponse
from src.common.config import settings
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.middleware.rbac import require_role
from src.core.models.block import Block
from src.core.services.audit_service import record_action
from src.core.models.document import Document
from src.core.models.lifecycle_feedback import LifecycleFeedback
from src.core.models.user import UserRole
from src.search.cache_invalidator import invalidate_repository_cache

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 유효성 상태 관련 스키마
# ---------------------------------------------------------------------------

VALID_VALIDITY_STATUSES = {"active", "historical", "superseded", "archived", "purged", "disputed"}


class ValidityChangeRequest(BaseModel):
    """블럭 유효성 상태 변경 요청."""

    status: str = Field(..., description="active/historical/superseded/archived/purged/disputed")
    reason: str = Field("", description="변경 사유")
    successor_block_id: UUID | None = Field(None, description="대체 블럭 ID (superseded 시)")


class BatchValidityRequest(BaseModel):
    """블럭 일괄 유효성 변경 요청."""

    block_ids: list[UUID]
    status: str = Field(..., description="active/historical/superseded/archived/purged/disputed")
    reason: str = Field("", description="변경 사유")


class ClassificationFeedbackRequest(BaseModel):
    """분류 수정 피드백 요청."""

    field_name: str = Field(
        ..., description="수정 대상 필드 (nature, domain_category_ids, entities)"
    )
    new_value: Any = Field(..., description="수정된 값")
    reason: str = Field("", description="수정 사유")

ALLOWED_FEEDBACK_FIELDS = {"nature", "domain_category_ids", "entities"}

router = APIRouter()


# ---------------------------------------------------------------------------
# 요청 스키마 (프론트엔드 노션 에디터용)
# ---------------------------------------------------------------------------


class BlockCreateItem(BaseModel):
    """프론트엔드에서 전송하는 노션 스타일 블럭."""

    block_type: str  # paragraph, heading_1, bulleted_list, code, etc.
    content: str
    properties: dict = Field(default_factory=dict)  # code language, etc.
    children: list["BlockCreateItem"] = Field(default_factory=list)


class BlockBatchCreateRequest(BaseModel):
    """블럭 일괄 생성 요청 (프론트엔드 노션 에디터에서)."""

    document_id: UUID
    repository_id: UUID
    blocks: list[BlockCreateItem]
    replace_existing: bool = False  # True면 기존 블럭 교체, False면 추가


class BlockReplaceItem(BaseModel):
    """편집화면 저장 시 전송하는 블럭. 기존 블럭은 block_id 보유, 신규는 None."""

    block_id: uuid.UUID | None = None
    block_type: str
    content: str
    properties: dict = Field(default_factory=dict)
    metadata: dict | None = None


class BlockReplaceRequest(BaseModel):
    """문서 블럭 전체 교체 요청 (id-aware merge)."""

    repository_id: uuid.UUID
    blocks: list[BlockReplaceItem]


class BlockAppendRequest(BaseModel):
    """블럭 단건 추가 요청."""

    block_type: str
    content: str
    properties: dict = Field(default_factory=dict)
    parent_block_id: UUID | None = None


class BlockSplitRequest(BaseModel):
    """블럭 분할 요청."""

    at_offset: int = Field(..., description="분할 지점 문자 오프셋 (0 < at_offset < len(content))")


class BlockSplitResponse(BaseModel):
    """블럭 분할 응답."""

    original: BlockResponse
    new_block: BlockResponse


@router.get(
    "/documents/{document_id}/blocks",
    response_model=PaginatedResponse[BlockResponse],
    summary="문서 블럭 목록 조회",
)
async def list_document_blocks(
    document_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    block_type: Optional[str] = Query(None, description="블럭 타입 필터 (text/table/image/summary)"),
    include_noise: bool = Query(False, description="노이즈 블럭 포함 여부"),
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> PaginatedResponse[BlockResponse]:
    """문서의 블럭 목록을 순서대로 반환한다."""
    # 문서 존재 확인
    doc_stmt = select(Document).where(Document.id == document_id)
    doc_result = await db.execute(doc_stmt)
    doc = doc_result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    stmt = (
        select(Block)
        .where(Block.document_id == document_id)
        .order_by(Block.block_index)
    )
    if block_type:
        stmt = stmt.where(Block.block_type == block_type)
    if not include_noise:
        stmt = stmt.where(Block.is_noise == False)  # noqa: E712

    # 전체 개수
    count_stmt = select(func.count()).select_from(Block).where(Block.document_id == document_id)
    if block_type:
        count_stmt = count_stmt.where(Block.block_type == block_type)
    if not include_noise:
        count_stmt = count_stmt.where(Block.is_noise == False)  # noqa: E712
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    blocks = result.scalars().all()

    items = [_block_to_response(b) for b in blocks]
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/blocks/{block_id}",
    response_model=ApiResponse[BlockDetailResponse],
    summary="블럭 상세 조회",
)
async def get_block_detail(
    block_id: uuid.UUID,
    include_vector: bool = Query(False, description="벡터 프리뷰 포함 여부"),
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockDetailResponse]:
    """블럭 상세 정보를 반환한다."""
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

    resp = _block_to_detail_response(block, include_vector)
    return ApiResponse(data=resp)


# ---------------------------------------------------------------------------
# 노이즈 블럭 조회/복원/강등 엔드포인트
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}/noise-blocks",
    response_model=PaginatedResponse[BlockResponse],
    summary="노이즈 블럭 목록 조회",
)
async def list_noise_blocks(
    document_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> PaginatedResponse[BlockResponse]:
    """문서의 노이즈 블럭 목록을 반환한다."""
    doc_stmt = select(Document).where(Document.id == document_id)
    doc_result = await db.execute(doc_stmt)
    if doc_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    stmt = (
        select(Block)
        .where(Block.document_id == document_id, Block.is_noise == True)  # noqa: E712
        .order_by(Block.block_index)
    )
    count_stmt = (
        select(func.count())
        .select_from(Block)
        .where(Block.document_id == document_id, Block.is_noise == True)  # noqa: E712
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    blocks = result.scalars().all()

    items = [_block_to_response(b) for b in blocks]
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.post(
    "/blocks/{block_id}/promote",
    response_model=ApiResponse[BlockResponse],
    summary="노이즈 → 본문 복원",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def promote_block(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockResponse]:
    """노이즈 블럭을 본문으로 복원하고 재인덱싱을 트리거한다."""
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")
    if not block.is_noise:
        raise HTTPException(status_code=400, detail="이미 본문 블럭입니다")

    block.is_noise = False
    block.is_indexed = False  # 재인덱싱 필요 마킹
    block.vector_id = None

    # metadata에서 noise 플래그 제거
    meta = block.meta_info or {}
    meta.pop("is_noise", None)
    meta.pop("noise_reason", None)
    block.meta_info = meta

    await db.commit()
    await db.refresh(block)

    logger.info("block_promoted", block_id=str(block_id), document_id=str(block.document_id))

    # 비동기 재인덱싱 트리거
    try:
        await _trigger_single_block_reindex(block, db)
        # _trigger 내부의 commit 이 ORM 속성을 expire 시키므로 명시적으로 재수화.
        # (이걸 안 하면 뒤의 _block_to_response 에서 updated_at lazy-load → MissingGreenlet)
        await db.refresh(block)
    except Exception as exc:
        logger.warning("promote_reindex_failed", block_id=str(block_id), error=str(exc))
        # 실패해도 promote 자체는 성공했으므로 응답 이어가되, 속성 재수화는 보장.
        try:
            await db.refresh(block)
        except Exception:
            pass

    # 감사 로그
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="UPDATE",
        resource_type="block",
        resource_id=block_id,
        detail={"action": "promote", "document_id": str(block.document_id)},
    )

    return ApiResponse(data=_block_to_response(block))


@router.post(
    "/blocks/{block_id}/demote",
    response_model=ApiResponse[BlockResponse],
    summary="본문 → 노이즈 강등",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def demote_block(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockResponse]:
    """본문 블럭을 노이즈로 강등하고 검색 인덱스에서 제거한다."""
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")
    if block.is_noise:
        raise HTTPException(status_code=400, detail="이미 노이즈 블럭입니다")

    block.is_noise = True
    block.is_indexed = False

    # metadata에 noise 플래그 추가
    meta = block.meta_info or {}
    meta["is_noise"] = True
    meta["noise_reason"] = "사용자 수동 분류"
    block.meta_info = meta

    await db.commit()
    await db.refresh(block)

    logger.info("block_demoted", block_id=str(block_id), document_id=str(block.document_id))

    # Qdrant/ES 에서 해당 포인트 삭제
    try:
        await _remove_from_search_indexes(block, db)
    except Exception as exc:
        logger.warning("demote_index_removal_failed", block_id=str(block_id), error=str(exc))

    # 감사 로그
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="UPDATE",
        resource_type="block",
        resource_id=block_id,
        detail={"action": "demote", "document_id": str(block.document_id)},
    )

    return ApiResponse(data=_block_to_response(block))


# D54 §5 PR-B — EMBEDDING_PROXY_URL 직접 사용 (RERANKER_URL 에서 derive 폐지).
# 이전: RERANKER_URL=:7130/rerank → /embed 치환 = :7130/embed (embed proxy 와 우연 일치)
# 변경 후 RERANKER_URL=:7125/rerank → /embed 치환 시 :7125/embed (없는 endpoint)
# 따라서 EMBEDDING_PROXY_URL=:7130 을 직접 사용 — port 충돌/오타 위험 0.
_EMBEDDING_PROXY_URL = (os.environ.get("EMBEDDING_PROXY_URL", "") or "").strip()
_RERANKER_EMBED_URL = (
    f"{_EMBEDDING_PROXY_URL.rstrip('/')}/embed" if _EMBEDDING_PROXY_URL else ""
)


class _EmbedResult:
    def __init__(self, dense: list[float], sparse: dict[int, float]):
        self.dense = dense
        self.sparse = sparse


async def _get_embedding(text: str) -> _EmbedResult:
    """GPU sidecar /embed 호출. 실패 시 로컬 CPU 폴백."""
    if _RERANKER_EMBED_URL:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(_RERANKER_EMBED_URL, json={"text": text})
                resp.raise_for_status()
                data = resp.json()
                return _EmbedResult(
                    dense=data["dense"],
                    sparse={int(k): float(v) for k, v in data.get("sparse", {}).items()},
                )
        except Exception as exc:
            logger.warning("gpu_embed_failed_falling_back_to_cpu", error=str(exc)[:200])

    from src.pipeline.embedders.bge_m3 import BGEM3Embedder
    embedder = BGEM3Embedder()
    return await embedder.embed_single(text)


async def _trigger_single_block_reindex(block: Block, db: AsyncSession) -> None:
    """단일 블럭을 재임베딩하고 Qdrant/ES 에 upsert 한다.

    payload 는 `_qdrant_upsert_blocks` / `_es_index_blocks` 초기 인덱싱과 동일한
    필드 세트로 구성한다. document_status/category_ids 같은 검색 필터 키가 빠지면
    검색 파이프라인이 이 포인트를 걸러버리므로, 복원(promote) 후에도 반드시 동일한
    payload 로 upsert 해야 검색에 노출된다.

    GPU sidecar (reranker 서비스) 의 /embed 엔드포인트 사용 → ~20ms.
    사이드카 불가 시 로컬 CPU 폴백 → ~5-10s.
    """
    from src.pipeline.workers.embed_worker import (
        _get_document_category_ids,
        _get_document_meta,
        _get_document_status,
    )

    embedding_text = block.content
    meta_info = block.meta_info or {}
    ctx_prefix = meta_info.get("contextual_prefix")
    if ctx_prefix:
        embedding_text = f"{ctx_prefix}\n\n{block.content}"

    embed_result = await _get_embedding(embedding_text)

    tenant_slug = await _get_tenant_slug_for_block(block, db)
    collection_name = f"aicm_{tenant_slug}_blocks"

    # Lucas-KMS Phase 2 T2.5 — tenant_id 조회 (payload-level isolation 이중 안전망).
    from src.core.models.repository import Repository
    repo = (
        await db.execute(select(Repository).where(Repository.id == block.repository_id))
    ).scalar_one_or_none()
    tenant_id_str = str(repo.tenant_id) if repo and repo.tenant_id else ""
    if not tenant_id_str:
        logger.warning(
            "single_block_reindex_missing_tenant_id",
            block_id=str(block.id),
            repository_id=str(block.repository_id),
        )

    # 검색 필터에 필요한 문서/저장소 메타 조회
    category_ids = await _get_document_category_ids(block.document_id)
    document_title, repository_name = await _get_document_meta(
        block.document_id, block.repository_id
    )
    document_status = await _get_document_status(block.document_id)

    # 초기 인덱싱(_qdrant_upsert_blocks)과 동일한 payload 구성.
    # 누락 시 document_status=active 필터 등에서 걸러져 복원 후에도 검색에 안 뜬다.
    payload: dict[str, Any] = {
        # Lucas-KMS Phase 2 T2.5 — payload-level tenant isolation 이중 안전망.
        "tenant_id": tenant_id_str,
        "tenant_slug": tenant_slug,
        "document_id": str(block.document_id),
        "repository_id": str(block.repository_id),
        "document_title": document_title,
        "repository_name": repository_name,
        "block_type": block.block_type,
        "block_index": block.block_index,
        "content": block.content,
        "token_count": block.token_count,
        "source_location": block.source_location or {},
        "metadata": meta_info,
        "category_ids": category_ids or [],
        "document_status": document_status,
        # Ontology
        "nature": meta_info.get("nature", ""),
        "time_resolved": (meta_info.get("time_reference") or {}).get("resolved", ""),
        "speakers": (meta_info.get("entities") or {}).get("speakers", []),
        "entities_people": (meta_info.get("entities") or {}).get("people", []),
        "entities_orgs": (meta_info.get("entities") or {}).get("orgs", []),
        "validity_status": meta_info.get("validity_status", "active"),
        "domain_category_ids": [
            c.get("id", "") for c in (meta_info.get("domain_category_ids") or [])
        ],
        "classification_confidence": meta_info.get("classification_confidence", 0.0),
    }
    if ctx_prefix:
        payload["contextual_prefix"] = ctx_prefix
    # 풍부화 보강 필드
    extracted = meta_info.get("extracted_metadata")
    if extracted:
        payload["extracted_metadata"] = extracted
        if "keywords" in extracted:
            payload["keywords"] = extracted["keywords"]
        if "entities" in extracted:
            payload["entities"] = extracted["entities"]
        if "topic" in extracted:
            payload["topic"] = extracted["topic"]

    # Qdrant upsert (dense + sparse)
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct, SparseVector

        client = QdrantClient(
            url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None
        )
        vectors: dict[str, Any] = {"dense": embed_result.dense}
        if embed_result.sparse:
            vectors["sparse"] = SparseVector(
                indices=list(embed_result.sparse.keys()),
                values=list(embed_result.sparse.values()),
            )
        point = PointStruct(
            id=str(block.id),
            vector=vectors,
            payload=payload,
        )
        client.upsert(collection_name=collection_name, points=[point])
        block.vector_id = str(block.id)
        block.is_indexed = True
        await db.commit()
    except ImportError:
        logger.warning("qdrant_client_not_installed_skipping_reindex")

    # ES upsert — 초기 인덱싱과 동일한 필드 세트
    try:
        from src.search.hybrid.es_keyword import ESKeywordSearcher, build_block_es_index_name

        es_index = build_block_es_index_name(tenant_slug)
        searcher = ESKeywordSearcher()
        # Lucas-KMS Phase 2 T2.6 — tenant_id 조회 (block → repository → tenant).
        tenant_id_str = await _get_tenant_id_for_block(block, db)
        es_doc = {
            # Lucas-KMS Phase 2 T2.6 — payload tenant_id (이중 안전망).
            "tenant_id": tenant_id_str,
            "block_id": str(block.id),
            "document_id": str(block.document_id),
            "repository_id": str(block.repository_id),
            "document_title": document_title,
            "repository_name": repository_name,
            "block_type": block.block_type,
            "block_index": block.block_index,
            "content": block.content,
            "token_count": block.token_count,
            "source_location": block.source_location or {},
            "metadata": meta_info,
            "category_ids": category_ids or [],
            "document_status": document_status,
            "nature": meta_info.get("nature", ""),
            "validity_status": meta_info.get("validity_status", "active"),
        }
        if ctx_prefix:
            es_doc["contextual_prefix"] = ctx_prefix
        await searcher.index_blocks(
            es_index, [es_doc], expected_tenant_id=tenant_id_str
        )
    except Exception as exc:
        logger.warning("es_reindex_single_failed", error=str(exc))


def _deleted_block_ids(existing_ids: set[uuid.UUID], incoming: list[dict]) -> set[uuid.UUID]:
    """incoming 에 없는 기존 블럭 id(삭제 대상)를 반환한다.

    incoming.block_id 가 None 이거나 existing 에 없으면(신규/stale) incoming_ids 에서 제외 → 자연히 insert 로 처리된다.
    """
    incoming_ids = {item["block_id"] for item in incoming if item.get("block_id") is not None and item["block_id"] in existing_ids}
    return existing_ids - incoming_ids


async def _purge_document_search_indexes(
    document_id: uuid.UUID, repository_id: uuid.UUID, db: AsyncSession
) -> None:
    """문서의 모든 qdrant 포인트 + ES 문서를 document_id 로 일괄 삭제(고아 정리)."""
    from src.core.models.repository import Repository
    from src.core.models.tenant import Tenant

    repo = (await db.execute(select(Repository).where(Repository.id == repository_id))).scalar_one_or_none()
    tenant_slug = "unknown"
    tenant_id = ""
    if repo:
        tenant = (await db.execute(select(Tenant).where(Tenant.id == repo.tenant_id))).scalar_one_or_none()
        if tenant:
            tenant_slug = tenant.slug
            tenant_id = str(tenant.id)

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        client.delete(
            collection_name=f"aicm_{tenant_slug}_blocks",
            points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]),
        )
    except Exception as exc:
        logger.warning("replace_qdrant_purge_failed", document_id=str(document_id), error=str(exc))

    try:
        from elasticsearch import AsyncElasticsearch
        from src.search.es_wrapper import with_tenant_term
        from src.search.hybrid.es_keyword import build_block_es_index_name

        es = AsyncElasticsearch(hosts=[settings.ELASTICSEARCH_URL])
        body = with_tenant_term({"term": {"document_id": str(document_id)}}, tenant_id)
        await es.delete_by_query(index=build_block_es_index_name(tenant_slug), body={"query": body}, ignore=[404])
        await es.close()
    except Exception as exc:
        logger.warning("replace_es_purge_failed", document_id=str(document_id), error=str(exc))


async def _remove_from_search_indexes(block: Block, db: AsyncSession) -> None:
    """Qdrant 와 ES 에서 해당 블럭을 삭제한다.

    Lucas-KMS Phase 2 T2.6 — ES delete_by_query 에 tenant_id term filter 추가.
    index naming 만으로 부족, payload tenant_id 도 must filter (이중 안전망).
    """
    tenant_slug = await _get_tenant_slug_for_block(block, db)
    tenant_id_str = await _get_tenant_id_for_block(block, db)
    collection_name = f"aicm_{tenant_slug}_blocks"

    # Qdrant 삭제
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointIdsList

        client = QdrantClient(
            url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None
        )
        client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=[str(block.id)]),
        )
    except Exception as exc:
        logger.warning("qdrant_delete_failed", block_id=str(block.id), error=str(exc))

    # ES 삭제
    try:
        from src.search.es_wrapper import with_tenant_term
        from src.search.hybrid.es_keyword import build_block_es_index_name

        es_index = build_block_es_index_name(tenant_slug)
        from elasticsearch import AsyncElasticsearch

        es_client = AsyncElasticsearch()
        # Lucas-KMS Phase 2 T2.6 — block_id term + tenant_id term (이중 안전망).
        base_query = {"term": {"block_id": str(block.id)}}
        scoped_query = with_tenant_term(base_query, tenant_id_str)
        await es_client.delete_by_query(
            index=es_index,
            body={"query": scoped_query},
            ignore=[404],
        )
        await es_client.close()
    except Exception as exc:
        logger.warning("es_delete_failed", block_id=str(block.id), error=str(exc))


@router.put(
    "/blocks/{block_id}",
    response_model=ApiResponse[BlockResponse],
    summary="블럭 수정",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def update_block(
    block_id: uuid.UUID,
    body: BlockUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockResponse]:
    """블럭 내용을 수정하고 재벡터화를 트리거한다."""
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

    if body.content is not None:
        block.content = body.content
        block.block_hash = hashlib.sha256(body.content.encode("utf-8")).hexdigest()
        block.token_count = len(body.content)
        block.is_indexed = False  # 재벡터화 필요 마킹
        block.vector_id = None

    if body.block_type is not None:
        block.block_type = body.block_type

    if body.metadata is not None:
        block.meta_info = {**block.meta_info, **body.metadata}

    await db.commit()
    await db.refresh(block)

    logger.info("block_updated", block_id=str(block_id), re_index_needed=not block.is_indexed)

    # ES + Qdrant payload 동기 (재색인 X, dense vector 유지)
    if body.content is not None or body.block_type is not None:
        tenant_slug = await _get_tenant_slug_for_block(block, db)
        collection = f"aicm_{tenant_slug}_blocks"
        sync_payload: dict = {}
        if body.content is not None:
            sync_payload["content"] = block.content
        if body.block_type is not None:
            sync_payload["block_type"] = block.block_type
        await _sync_block_to_indexes(str(block_id), collection, sync_payload)

    # 감사 로그: 블럭 수정
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="UPDATE",
        resource_type="block",
        resource_id=block_id,
        detail={
            "document_id": str(block.document_id),
            "content_changed": body.content is not None,
            "metadata_changed": body.metadata is not None,
        },
    )

    await invalidate_repository_cache(block.repository_id)
    return ApiResponse(data=_block_to_response(block))


@router.patch(
    "/blocks/{block_id}",
    response_model=ApiResponse[BlockResponse],
    summary="블럭 수정 (PATCH)",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def patch_block(
    block_id: uuid.UUID,
    body: BlockUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockResponse]:
    """블럭 내용을 부분 수정한다. PUT과 동일 로직."""
    return await update_block(block_id, body, db, _tenant)


@router.delete(
    "/blocks/{block_id}",
    response_model=ApiResponse[dict],
    summary="블럭 삭제",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def delete_block(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    """블럭을 삭제한다.

    삭제 시: Qdrant/ES 검색 인덱스에서 해당 블럭 벡터 제거 → DB 행 삭제 →
    이후 블럭들의 block_index 를 1씩 감소(연속성 유지) → 저장소 검색 캐시 무효화.
    (merge 의 블럭 삭제 로직과 동일 패턴 — 편집 화면 단락 삭제용 단독 엔드포인트.)
    """
    try:
        block = (await db.execute(select(Block).where(Block.id == block_id))).scalar_one_or_none()
        if block is None:
            raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")
        doc_id = block.document_id
        repo_id = block.repository_id
        deleted_idx = block.block_index

        # 삭제 대상 블럭의 Qdrant/ES 벡터 먼저 제거
        try:
            await _remove_from_search_indexes(block, db)
        except Exception as exc:
            logger.warning("delete_block_index_cleanup_failed", block_id=str(block_id), error=str(exc))

        await db.delete(block)
        await db.flush()

        # 이후 블럭 block_index 1 감소(연속성 유지)
        await db.execute(
            update(Block)
            .where(Block.document_id == doc_id, Block.block_index > deleted_idx)
            .values(block_index=Block.block_index - 1)
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    try:
        await invalidate_repository_cache(repo_id)
    except Exception:  # noqa: BLE001 — 캐시 무효화 실패는 삭제를 막지 않음
        logger.warning("delete_block_cache_invalidate_failed", block_id=str(block_id))

    logger.info("block_deleted", block_id=str(block_id), document_id=str(doc_id))
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="DELETE",
        resource_type="block",
        resource_id=block_id,
        detail={"document_id": str(doc_id)},
    )
    return ApiResponse(data={"deleted": True, "block_id": str(block_id)})


@router.post(
    "/blocks/{block_id}/re-index",
    response_model=ApiResponse[BlockResponse],
    summary="블럭 재인덱싱",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def re_index_block(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockResponse]:
    """블럭을 재임베딩하고 Qdrant/ES 에 업데이트한다.

    실제 upsert 로직은 _trigger_single_block_reindex 에 위임 — 초기 인덱싱과
    동일한 payload 세트(document_status/category_ids 등) 를 보장해야 검색에 다시 노출.
    """
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")
    if block.is_noise:
        raise HTTPException(
            status_code=400,
            detail="노이즈 블럭은 재인덱싱할 수 없습니다. 먼저 본문으로 복원(promote)하세요.",
        )

    try:
        await _trigger_single_block_reindex(block, db)
        await db.refresh(block)
        logger.info("block_re_indexed", block_id=str(block_id))
    except ImportError:
        raise HTTPException(status_code=503, detail="임베딩 모듈을 사용할 수 없습니다")

    return ApiResponse(data=_block_to_response(block))


# ---------------------------------------------------------------------------
# 블럭 병합/분할 (프론트엔드 업로드 단계의 LLM 세그먼트 수동 정리용)
# ---------------------------------------------------------------------------

_MERGE_LIST_KEYS = ("keywords", "entities", "topic_tags", "query_keywords")
_SPLIT_POSITION_SENSITIVE_KEYS = (
    "table_analysis",
    "table_nl",
    "search_summary",
    "extracted_metadata",
)
_UNSPLITTABLE_BLOCK_TYPES = {"table", "image", "divider"}


def _merge_metadata(base: dict | None, other: dict | None) -> dict:
    """첫 번째 블럭 메타를 기본으로, 지정된 리스트 키만 중복 제거 병합."""
    merged: dict = dict(base or {})
    other = other or {}
    for key in _MERGE_LIST_KEYS:
        left = merged.get(key)
        right = other.get(key)
        if left is None and right is None:
            continue
        combined: list = []
        seen: set = set()
        for item in list(left or []) + list(right or []):
            marker = item if isinstance(item, (str, int, float, bool)) else repr(item)
            if marker in seen:
                continue
            seen.add(marker)
            combined.append(item)
        merged[key] = combined
    return merged


def _recompute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_METADATA_FIELDS = ("search_summary", "nature", "query_keywords", "topic_tags")

_GEN_META_MAX_PER_CALL = 10


def _merge_generated_metadata(existing: dict | None, generated: dict) -> dict:
    """기존 meta_info 에 생성된 메타(대상 4필드)를 병합. None 은 제외(기존 보존), 그 외 키 보존."""
    merged = dict(existing or {})
    for field in _METADATA_FIELDS:
        val = generated.get(field)
        if val is not None:
            merged[field] = val
    return merged


def _apply_editor_metadata(existing: dict | None, provided: dict | None) -> dict:
    """editor 가 보낸 표시 메타(search_summary/nature/query_keywords/topic_tags/hint)를 기존
    meta_info 에 병합한다. 비표시 enrichment(entities/contextual_prefix 등)는 보존한다.

    계약: provided 는 editor 의 *명시적 상태*다. 존재하는 키는 그 값으로 덮어쓴다(빈 값=[]/'' 도
    사용자가 의도적으로 비운 것으로 간주해 반영). editor 는 값이 없는 필드를 아예 보내지 않으므로
    (web `_make_typed_block` 가 None 필드를 제외) 누락 필드는 기존 값이 보존된다. 따라서 생성기
    결과를 병합하는 `_merge_generated_metadata`(None 스킵)와 의도적으로 다른 의미를 가진다."""
    merged = dict(existing or {})
    if provided:
        merged.update(provided)
    return merged


async def _generate_metadata_for_content(content: str, block_type: str, client, document_title: str = "") -> dict:
    """content+block_type 으로 enricher 3종 실행 → 4필드 dict 반환. DB 무관."""
    from src.pipeline.models.block import BlockObject, BlockType
    from src.pipeline.enrichers.search_summary_generator import SearchSummaryGenerator
    from src.pipeline.enrichers.ontology_classifier import OntologyClassifier
    from src.pipeline.enrichers.metadata_extractor import MultilayerKeywordExtractor

    try:
        btype = BlockType(block_type)
    except ValueError:
        btype = BlockType.PARAGRAPH
    if btype in (BlockType.SUMMARY, BlockType.DIVIDER):
        btype = BlockType.PARAGRAPH
    bo = BlockObject(document_id=uuid.uuid4(), block_type=btype, content=content, block_index=0, metadata={})
    # 수동 생성(사용자 명시 요청)이므로 길이 임계값을 우회한다(force=True).
    # 짧은 QnA 블록도 메타데이터를 생성한다. 자동 업로드 파이프라인은 영향 없음.
    try:
        await SearchSummaryGenerator(llm_client=client).generate_all([bo], force=True)
    except Exception as exc:
        logger.warning("genmeta_preview_summary_failed", error=str(exc))
    try:
        await OntologyClassifier(llm_client=client, document_type="other", document_title=document_title or "제목 없음").classify_all([bo], force=True)
    except Exception as exc:
        logger.warning("genmeta_preview_ontology_failed", error=str(exc))
    try:
        await MultilayerKeywordExtractor(llm_client=client).extract_all([bo], force=True)
    except Exception as exc:
        logger.warning("genmeta_preview_keywords_failed", error=str(exc))
    return {f: bo.metadata.get(f) for f in _METADATA_FIELDS}


async def _generate_block_metadata(block: Block, db: AsyncSession, client, document_title: str = "") -> dict:
    """단일 블록에 enricher 실행 → meta_info 병합 저장 → 재인덱싱 → 생성 메타 반환."""
    generated = await _generate_metadata_for_content(block.content, block.block_type, client, document_title)
    block.meta_info = _merge_generated_metadata(block.meta_info, generated)
    await db.flush()
    try:
        await _trigger_single_block_reindex(block, db)
    except Exception as exc:
        logger.warning("genmeta_reindex_failed", block_id=str(block.id), error=str(exc))
    return {f: block.meta_info.get(f) for f in _METADATA_FIELDS}


@router.post(
    "/blocks/{block_id}/merge-next",
    response_model=ApiResponse[BlockResponse],
    summary="다음 블럭과 병합",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def merge_block_with_next(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockResponse]:
    """현재 블럭을 다음 블럭(block_index + 1)과 병합한다.

    병합 후 다음 블럭은 삭제되고, 이후 블럭의 block_index 는 1씩 감소한다.
    """
    try:
        stmt = select(Block).where(Block.id == block_id)
        block = (await db.execute(stmt)).scalar_one_or_none()
        if block is None:
            raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

        next_stmt = select(Block).where(
            Block.document_id == block.document_id,
            Block.block_index == block.block_index + 1,
        )
        next_block = (await db.execute(next_stmt)).scalar_one_or_none()
        if next_block is None:
            raise HTTPException(status_code=400, detail="다음 블럭이 존재하지 않습니다")

        if next_block.block_type != block.block_type:
            logger.warning(
                "merge_next_type_mismatch",
                block_id=str(block.id),
                this_type=block.block_type,
                next_type=next_block.block_type,
            )

        new_content = f"{block.content}\n\n{next_block.content}"
        block.content = new_content
        block.meta_info = _merge_metadata(block.meta_info, next_block.meta_info)
        # TODO: 정확한 토크나이저 적용 필요 (현재는 단순 whitespace split 플레이스홀더)
        block.token_count = len(new_content.split())
        block.block_hash = _recompute_hash(new_content)
        block.is_indexed = False
        block.vector_id = None

        # 삭제 대상 블럭의 Qdrant/ES 벡터 먼저 제거
        try:
            await _remove_from_search_indexes(next_block, db)
        except Exception as exc:
            logger.warning("merge_next_index_cleanup_failed", error=str(exc))

        deleted_idx = next_block.block_index
        doc_id = block.document_id
        await db.delete(next_block)
        await db.flush()

        await db.execute(
            update(Block)
            .where(Block.document_id == doc_id, Block.block_index > deleted_idx)
            .values(block_index=Block.block_index - 1)
        )

        await db.commit()
        await db.refresh(block)
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    logger.info(
        "block_merged_next",
        block_id=str(block.id),
        document_id=str(block.document_id),
    )
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="UPDATE",
        resource_type="block",
        resource_id=block.id,
        detail={"action": "merge-next", "document_id": str(block.document_id)},
    )
    return ApiResponse(data=_block_to_response(block))


@router.post(
    "/blocks/{block_id}/merge-prev",
    response_model=ApiResponse[BlockResponse],
    summary="이전 블럭과 병합",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def merge_block_with_prev(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockResponse]:
    """현재 블럭을 이전 블럭(block_index - 1)과 병합한다.

    이전 블럭이 살아남고 현재 블럭은 삭제된다. 이후 블럭의 block_index 는 1씩 감소한다.
    """
    try:
        stmt = select(Block).where(Block.id == block_id)
        block = (await db.execute(stmt)).scalar_one_or_none()
        if block is None:
            raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

        if block.block_index <= 0:
            raise HTTPException(status_code=400, detail="이전 블럭이 존재하지 않습니다")

        prev_stmt = select(Block).where(
            Block.document_id == block.document_id,
            Block.block_index == block.block_index - 1,
        )
        prev_block = (await db.execute(prev_stmt)).scalar_one_or_none()
        if prev_block is None:
            raise HTTPException(status_code=400, detail="이전 블럭이 존재하지 않습니다")

        if prev_block.block_type != block.block_type:
            logger.warning(
                "merge_prev_type_mismatch",
                block_id=str(block.id),
                this_type=block.block_type,
                prev_type=prev_block.block_type,
            )

        new_content = f"{prev_block.content}\n\n{block.content}"
        prev_block.content = new_content
        prev_block.meta_info = _merge_metadata(prev_block.meta_info, block.meta_info)
        # TODO: 정확한 토크나이저 적용 필요 (현재는 단순 whitespace split 플레이스홀더)
        prev_block.token_count = len(new_content.split())
        prev_block.block_hash = _recompute_hash(new_content)
        prev_block.is_indexed = False
        prev_block.vector_id = None

        # 삭제 대상 블럭의 Qdrant/ES 벡터 먼저 제거
        try:
            await _remove_from_search_indexes(block, db)
        except Exception as exc:
            logger.warning("merge_prev_index_cleanup_failed", error=str(exc))

        deleted_idx = block.block_index
        doc_id = block.document_id
        prev_id = prev_block.id
        await db.delete(block)
        await db.flush()

        await db.execute(
            update(Block)
            .where(Block.document_id == doc_id, Block.block_index > deleted_idx)
            .values(block_index=Block.block_index - 1)
        )

        await db.commit()
        # prev_block 재조회 (벌크 업데이트 후 세션 일관성 확보)
        prev_block = (
            await db.execute(select(Block).where(Block.id == prev_id))
        ).scalar_one()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    logger.info(
        "block_merged_prev",
        block_id=str(prev_block.id),
        document_id=str(prev_block.document_id),
    )
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="UPDATE",
        resource_type="block",
        resource_id=prev_block.id,
        detail={"action": "merge-prev", "document_id": str(prev_block.document_id)},
    )
    return ApiResponse(data=_block_to_response(prev_block))


@router.post(
    "/blocks/{block_id}/split",
    response_model=ApiResponse[BlockSplitResponse],
    summary="블럭 분할",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def split_block(
    block_id: uuid.UUID,
    body: BlockSplitRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BlockSplitResponse]:
    """블럭 content 를 지정된 오프셋에서 두 개의 블럭으로 분할한다.

    원본 블럭은 앞부분을 유지하고, 뒷부분이 새 블럭으로 생성된다.
    이후 블럭의 block_index 는 1씩 증가한다.
    """
    try:
        stmt = select(Block).where(Block.id == block_id)
        block = (await db.execute(stmt)).scalar_one_or_none()
        if block is None:
            raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

        if block.block_type in _UNSPLITTABLE_BLOCK_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"{block.block_type} 블럭은 분할할 수 없습니다",
            )

        at_offset = body.at_offset
        if at_offset <= 0 or at_offset >= len(block.content):
            raise HTTPException(
                status_code=400,
                detail="at_offset 은 0 보다 크고 content 길이보다 작아야 합니다",
            )

        left_content = block.content[:at_offset].rstrip()
        right_content = block.content[at_offset:].lstrip()
        if not left_content or not right_content:
            raise HTTPException(
                status_code=400,
                detail="분할 결과 두 블럭 모두 비어있지 않아야 합니다",
            )

        original_idx = block.block_index
        doc_id = block.document_id

        # 이후 블럭 block_index +1 (원본 이후 블럭부터)
        await db.execute(
            update(Block)
            .where(Block.document_id == doc_id, Block.block_index > original_idx)
            .values(block_index=Block.block_index + 1)
        )
        await db.flush()

        # 메타 정리 (원본)
        base_meta = dict(block.meta_info or {})
        for key in _SPLIT_POSITION_SENSITIVE_KEYS:
            base_meta.pop(key, None)

        block.content = left_content
        block.block_hash = _recompute_hash(left_content)
        block.meta_info = base_meta
        block.is_indexed = False
        block.vector_id = None

        # 새 블럭 생성 (원본 이후 슬롯)
        new_meta = dict(block.meta_info or {})
        for key in _SPLIT_POSITION_SENSITIVE_KEYS:
            new_meta.pop(key, None)

        new_block = Block(
            id=uuid.uuid4(),
            document_id=block.document_id,
            repository_id=block.repository_id,
            block_type=block.block_type,
            content=right_content,
            block_index=original_idx + 1,
            block_hash=_recompute_hash(right_content),
            token_count=len(right_content.split()),
            source_location=block.source_location or {},
            properties=dict(block.properties) if block.properties else None,
            meta_info=new_meta,
            is_indexed=False,
            is_noise=block.is_noise,
        )
        db.add(new_block)

        await db.commit()
        await db.refresh(block)
        await db.refresh(new_block)
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    logger.info(
        "block_split",
        block_id=str(block.id),
        new_block_id=str(new_block.id),
        document_id=str(block.document_id),
        at_offset=body.at_offset,
    )
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="UPDATE",
        resource_type="block",
        resource_id=block.id,
        detail={
            "action": "split",
            "document_id": str(block.document_id),
            "new_block_id": str(new_block.id),
            "at_offset": body.at_offset,
        },
    )
    return ApiResponse(
        data=BlockSplitResponse(
            original=_block_to_response(block),
            new_block=_block_to_response(new_block),
        )
    )


@router.get(
    "/blocks/{block_id}/similar",
    response_model=ApiResponse[list[BlockResponse]],
    summary="유사 블럭 검색",
)
async def find_similar_blocks(
    block_id: uuid.UUID,
    top_k: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[list[BlockResponse]]:
    """벡터 유사도 기반으로 유사한 블럭을 검색한다."""
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

    if not block.vector_id or not block.is_indexed:
        raise HTTPException(status_code=400, detail="블럭이 아직 인덱싱되지 않았습니다")

    try:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.http.models import NamedVector

        from src.core.models.repository import Repository
        from src.core.models.tenant import Tenant

        repo_stmt = select(Repository).where(Repository.id == block.repository_id)
        repo = (await db.execute(repo_stmt)).scalar_one_or_none()
        tenant_slug = "unknown"
        if repo:
            tenant_stmt = select(Tenant).where(Tenant.id == repo.tenant_id)
            tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
            if tenant:
                tenant_slug = tenant.slug

        collection_name = f"aicm_{tenant_slug}_blocks"
        client = AsyncQdrantClient(
            url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None
        )

        # 소스 벡터로 유사 검색
        results = await client.recommend(
            collection_name=collection_name,
            positive=[str(block.id)],
            using="dense",
            limit=top_k + 1,  # 자기 자신 제외를 위해 +1
            with_payload=True,
        )

        # 유사 블럭 ID로 DB 조회
        similar_ids = [
            uuid.UUID(str(r.id)) for r in results if str(r.id) != str(block.id)
        ][:top_k]

        if not similar_ids:
            return ApiResponse(data=[])

        sim_stmt = select(Block).where(Block.id.in_(similar_ids))
        sim_result = await db.execute(sim_stmt)
        similar_blocks = sim_result.scalars().all()

        items = [_block_to_response(b) for b in similar_blocks]
        return ApiResponse(data=items)

    except ImportError:
        raise HTTPException(status_code=503, detail="Qdrant 클라이언트를 사용할 수 없습니다")


# ---------------------------------------------------------------------------
# 유효성 상태 관리 엔드포인트 (Phase B-4)
# ---------------------------------------------------------------------------


async def _es_update(es_index: str, block_id: str, doc: dict) -> None:
    """ES chunk payload 부분 업데이트. 실패는 경고만."""
    try:
        from elasticsearch import AsyncElasticsearch

        client = AsyncElasticsearch()
        await client.update(index=es_index, id=block_id, body={"doc": doc})
        await client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("block_es_sync_failed", block_id=block_id, error=str(exc))


async def _qdrant_set_payload(collection: str, block_id: str, payload: dict) -> None:
    """Qdrant payload set — block_id 로 단건. 실패는 경고만."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
            timeout=10,
        )
        client.set_payload(
            collection_name=collection,
            payload=payload,
            points=[block_id],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("block_qdrant_sync_failed", block_id=block_id, error=str(exc))


async def _sync_block_to_indexes(block_id: str, collection: str, payload: dict) -> None:
    """ES + Qdrant payload 동기 (재색인 X, dense vector 유지). 실패는 비치명."""
    from src.search.hybrid.es_keyword import build_block_es_index_name

    # collection 은 "aicm_{tenant_slug}_blocks" 형식 → slug 추출
    tenant_slug = collection.removeprefix("aicm_").removesuffix("_blocks")
    es_index = build_block_es_index_name(tenant_slug)
    await _es_update(es_index, block_id, payload)
    await _qdrant_set_payload(collection, block_id, payload)


async def _get_tenant_slug_for_block(
    block: Block, db: AsyncSession
) -> str:
    """블럭의 테넌트 slug를 조회한다."""
    from src.core.models.repository import Repository
    from src.core.models.tenant import Tenant

    repo_stmt = select(Repository).where(Repository.id == block.repository_id)
    repo = (await db.execute(repo_stmt)).scalar_one_or_none()
    if repo:
        tenant_stmt = select(Tenant).where(Tenant.id == repo.tenant_id)
        tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
        if tenant:
            return tenant.slug
    return "unknown"


async def _get_tenant_id_for_block(
    block: Block, db: AsyncSession
) -> str:
    """블럭의 테넌트 UUID 를 조회한다 (Lucas-KMS Phase 2 T2.6).

    repository.tenant_id 를 그대로 문자열로 반환. ES doc payload 의
    ``tenant_id`` 필드와 search/delete filter 에 사용.
    """
    from src.core.models.repository import Repository

    repo_stmt = select(Repository).where(Repository.id == block.repository_id)
    repo = (await db.execute(repo_stmt)).scalar_one_or_none()
    if repo:
        return str(repo.tenant_id)
    return ""


async def _update_qdrant_validity(
    block_id: uuid.UUID, new_status: str, collection_name: str
) -> None:
    """Qdrant의 블럭 payload에서 validity_status를 업데이트한다."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
            timeout=10,
        )
        client.set_payload(
            collection_name=collection_name,
            payload={"validity_status": new_status},
            points=[str(block_id)],
        )
    except Exception as exc:
        logger.warning(
            "qdrant_validity_update_failed",
            block_id=str(block_id),
            error=str(exc),
        )


@router.patch(
    "/blocks/{block_id}/validity",
    response_model=ApiResponse[dict],
    summary="블럭 유효성 상태 변경",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def change_block_validity(
    block_id: uuid.UUID,
    body: ValidityChangeRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    """블럭의 유효성 상태를 변경한다.

    상태: active, historical, superseded, archived, purged, disputed
    """
    if body.status not in VALID_VALIDITY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 상태입니다. 허용: {', '.join(sorted(VALID_VALIDITY_STATUSES))}",
        )

    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

    old_status = block.validity_status
    block.validity_status = body.status
    block.validity_reason = body.reason
    block.validity_changed_at = datetime.utcnow()

    if body.successor_block_id:
        block.successor_block_id = body.successor_block_id

    await db.commit()

    # Qdrant payload도 업데이트
    tenant_slug = await _get_tenant_slug_for_block(block, db)
    collection_name = f"aicm_{tenant_slug}_blocks"
    await _update_qdrant_validity(block_id, body.status, collection_name)

    logger.info(
        "block_validity_changed",
        block_id=str(block_id),
        old_status=old_status,
        new_status=body.status,
        reason=body.reason,
    )

    # 감사 로그: 블럭 유효성 변경
    record_action(
        tenant_id=_tenant,
        user_id=None,
        action="UPDATE",
        resource_type="block",
        resource_id=block_id,
        detail={
            "field": "validity_status",
            "old_status": old_status,
            "new_status": body.status,
            "reason": body.reason,
        },
    )

    return ApiResponse(data={"old_status": old_status, "new_status": body.status})


@router.post(
    "/blocks/batch-validity",
    response_model=ApiResponse[dict],
    summary="블럭 일괄 유효성 변경",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def batch_change_validity(
    body: BatchValidityRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    """여러 블럭의 유효성을 일괄 변경한다. Transition Event에서 사용."""
    if body.status not in VALID_VALIDITY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 상태입니다. 허용: {', '.join(sorted(VALID_VALIDITY_STATUSES))}",
        )

    if not body.block_ids:
        raise HTTPException(status_code=400, detail="block_ids가 비어있습니다")

    now = datetime.utcnow()

    # DB 일괄 업데이트
    stmt = (
        update(Block)
        .where(Block.id.in_(body.block_ids))
        .values(
            validity_status=body.status,
            validity_reason=body.reason,
            validity_changed_at=now,
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    updated_count = result.rowcount  # type: ignore[union-attr]

    # Qdrant 일괄 업데이트 — 블럭별 컬렉션 확인 필요
    # 성능을 위해 첫 번째 블럭의 컬렉션명을 기준으로 일괄 처리
    if body.block_ids:
        first_block_stmt = select(Block).where(Block.id == body.block_ids[0])
        first_block = (await db.execute(first_block_stmt)).scalar_one_or_none()
        if first_block:
            tenant_slug = await _get_tenant_slug_for_block(first_block, db)
            collection_name = f"aicm_{tenant_slug}_blocks"
            try:
                from qdrant_client import QdrantClient

                client = QdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY or None,
                    timeout=30,
                        )
                client.set_payload(
                    collection_name=collection_name,
                    payload={"validity_status": body.status},
                    points=[str(bid) for bid in body.block_ids],
                )
            except Exception as exc:
                logger.warning(
                    "qdrant_batch_validity_update_failed",
                    error=str(exc),
                    block_count=len(body.block_ids),
                )

    logger.info(
        "batch_validity_changed",
        block_count=len(body.block_ids),
        updated_count=updated_count,
        new_status=body.status,
    )

    return ApiResponse(
        data={
            "requested": len(body.block_ids),
            "updated": updated_count,
            "status": body.status,
        }
    )


# ---------------------------------------------------------------------------
# 분류 수정 피드백 엔드포인트 (Phase C-2)
# ---------------------------------------------------------------------------


async def _update_qdrant_classification(
    block_id: uuid.UUID,
    field_name: str,
    new_value: Any,
    collection_name: str,
) -> None:
    """Qdrant payload에서 분류 필드를 업데이트한다."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
            timeout=10,
        )
        payload_update: dict[str, Any] = {}
        if field_name == "nature":
            payload_update["nature"] = new_value
        elif field_name == "domain_category_ids":
            payload_update["domain_category_ids"] = new_value
        elif field_name == "entities":
            payload_update["entities"] = new_value

        if payload_update:
            client.set_payload(
                collection_name=collection_name,
                payload=payload_update,
                points=[str(block_id)],
            )
    except Exception as exc:
        logger.warning(
            "qdrant_classification_update_failed",
            block_id=str(block_id),
            field_name=field_name,
            error=str(exc),
        )


@router.post(
    "/blocks/{block_id}/classify-feedback",
    response_model=ApiResponse[dict],
    summary="분류 수정 피드백",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def submit_classification_feedback(
    block_id: uuid.UUID,
    body: ClassificationFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    """사용자가 블럭 분류를 수정한다. 피드백 로그에 기록하고 Qdrant도 갱신한다."""
    if body.field_name not in ALLOWED_FEEDBACK_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"수정 가능한 필드: {', '.join(sorted(ALLOWED_FEEDBACK_FIELDS))}",
        )

    # 1. 블럭 조회
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

    # 2. 이전 값 저장
    old_value = getattr(block, body.field_name, None)

    # 3. 새 값 적용
    setattr(block, body.field_name, body.new_value)

    # 4. classification_provenance에 user_corrected 표시
    provenance = block.classification_provenance or {}
    provenance["user_corrected"] = True
    provenance["corrected_field"] = body.field_name
    provenance["corrected_at"] = datetime.utcnow().isoformat()
    block.classification_provenance = provenance

    # 5. lifecycle_feedback 테이블에 기록
    feedback = LifecycleFeedback(
        tenant_id=_tenant,
        block_id=block_id,
        field_name=body.field_name,
        old_value={"value": old_value} if old_value is not None else None,
        new_value={"value": body.new_value},
        feedback_type="correction",
        reason=body.reason,
    )
    db.add(feedback)
    await db.commit()

    # 6. Qdrant payload 업데이트
    tenant_slug = await _get_tenant_slug_for_block(block, db)
    collection_name = f"aicm_{tenant_slug}_blocks"
    await _update_qdrant_classification(block_id, body.field_name, body.new_value, collection_name)

    logger.info(
        "classification_feedback_submitted",
        block_id=str(block_id),
        field_name=body.field_name,
        feedback_id=str(feedback.id),
    )

    return ApiResponse(
        data={
            "block_id": str(block_id),
            "field_name": body.field_name,
            "old_value": old_value,
            "new_value": body.new_value,
            "feedback_id": str(feedback.id),
        }
    )


# ---------------------------------------------------------------------------
# 블럭 생성 엔드포인트 (프론트엔드 노션 에디터)
# ---------------------------------------------------------------------------


def _flatten_block_items(
    items: list[BlockCreateItem],
    document_id: uuid.UUID,
    repository_id: uuid.UUID,
    start_index: int,
    parent_id: uuid.UUID | None = None,
) -> list[Block]:
    """재귀적으로 BlockCreateItem 트리를 평탄화하여 Block ORM 인스턴스 리스트로 변환한다."""
    result: list[Block] = []
    idx = start_index
    for item in items:
        block_id = uuid.uuid4()
        content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()
        block = Block(
            id=block_id,
            document_id=document_id,
            repository_id=repository_id,
            block_type=item.block_type,
            content=item.content,
            block_index=idx,
            block_hash=content_hash,
            token_count=len(item.content),
            source_location={},
            properties=item.properties or None,
            parent_block_id=parent_id,
            meta_info={"source": "frontend_editor"},
            is_indexed=False,
        )
        result.append(block)
        idx += 1
        # 자식 블럭 재귀 처리
        if item.children:
            children = _flatten_block_items(
                item.children, document_id, repository_id, idx, parent_id=block_id
            )
            result.extend(children)
            idx += len(children)
    return result


async def _clear_reembed_redis_state(document_id: uuid.UUID) -> None:
    """replace 재임베딩 발행 전에 Redis 블록 캐시 + embed dedup 잠금을 제거한다.

    - `aicm:blocks:{doc}`: blocking 단계가 30분 TTL 로 써두는 블록 캐시.
      embed 워커의 load_blocks_from_cache 가 DB 보다 *먼저* 읽으므로, 제거하지 않으면
      replace 로 DB 를 갱신해도 재임베딩이 stale 블록을 인덱싱한다(편집 미반영).
    - `aicm:processing:{doc}:embed:main`: 이전 임베딩이 실패하며 남긴 dedup 잠금이
      있으면 새 blocked 이벤트가 already_processing 으로 skip 되어 재임베딩이 누락된다.
    best-effort — 실패해도 경고만 남긴다.
    """
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        try:
            await r.delete(f"aicm:blocks:{document_id}")
            await r.delete(f"aicm:processing:{document_id}:embed:main")
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("replace_redis_clear_failed", document_id=str(document_id), error=str(exc))


async def _publish_blocked_event(
    document_id: uuid.UUID,
    block_count: int,
    tenant_id: uuid.UUID,
    repository_id: uuid.UUID,
    source_path: str,
    block_types: dict | None = None,
) -> None:
    """Kafka에 aicm.document.blocked 이벤트를 발행한다. 실패 시 경고만 남긴다.

    Phase 2.7 — tenant_id 가 envelope 에 *반드시* 포함되어야 consumer 가
    RLS context 를 설정할 수 있다.

    consumer 의 DocumentBlockedEvent 스키마는 event_id/repository_id/source_path 를
    *필수* 로 요구한다 — 누락 시 검증 실패로 재임베딩이 드롭된다(retry from_stage=embedding
    경로와 동일 페이로드 구성).
    """
    try:
        import json

        from aiokafka import AIOKafkaProducer

        from src.common.storage_tenant import kafka_envelope

        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await producer.start()
        try:
            event = kafka_envelope(
                tenant_id,
                {
                    "event_id": str(uuid.uuid4()),
                    "document_id": str(document_id),
                    "repository_id": str(repository_id),
                    "block_count": block_count,
                    "block_types": block_types or {},
                    "source_path": source_path or "",
                    "event": "blocked",
                },
            )
            await producer.send_and_wait(
                "aicm.document.blocked",
                value=json.dumps(event).encode("utf-8"),
            )
        finally:
            await producer.stop()
    except Exception as exc:
        logger.warning(
            "kafka_publish_failed",
            event="aicm.document.blocked",
            document_id=str(document_id),
            error=str(exc),
        )


@router.post(
    "/documents/{document_id}/blocks/from-editor",
    response_model=ApiResponse[dict],
    summary="에디터 콘텐츠 → PDF 변환 → 파이프라인 처리",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def submit_editor_content(
    document_id: uuid.UUID,
    body: BlockBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    """프론트엔드 에디터 콘텐츠를 PDF로 렌더링하여 파이프라인에 투입한다.

    모든 입력(노션 에디터 포함)은 PDF 변환 → 단일 파이프라인을 거친다.
    파이프라인 출력(블럭 배열) = 노션 스타일 문서.
    """
    import tempfile

    # 1. 문서 존재 확인
    doc_stmt = select(Document).where(Document.id == document_id)
    doc_result = await db.execute(doc_stmt)
    doc = doc_result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    if not body.blocks:
        raise HTTPException(status_code=400, detail="블럭 목록이 비어있습니다")

    # 2. 블럭 → HTML 렌더링
    html = _render_blocks_to_html(body.blocks)

    # 3. HTML → 임시 파일 저장 (파이프라인 입력용)
    with tempfile.NamedTemporaryFile(
        suffix=".html", prefix="aicm_editor_", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(html)
        html_path = f.name

    # 4. 파이프라인 트리거 (업로드 이벤트 발행)
    try:
        await _publish_upload_event(
            document_id=document_id,
            tenant_id=_tenant,
            repository_id=body.repository_id,
            source_path=html_path,
            source_format="html",
        )
    except Exception as exc:
        logger.warning("editor_pipeline_trigger_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="파이프라인 트리거 실패")

    logger.info(
        "editor_content_submitted_to_pipeline",
        document_id=str(document_id),
        block_count=len(body.blocks),
    )

    return ApiResponse(data={
        "message": "파이프라인에 투입되었습니다. 처리 완료 후 블럭이 갱신됩니다.",
        "document_id": str(document_id),
        "submitted_blocks": len(body.blocks),
    })


@router.post(
    "/documents/{document_id}/blocks/replace",
    response_model=ApiResponse[dict],
    summary="편집본 블럭 전체 교체 (id-aware merge) + 전체 재인덱싱",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def replace_document_blocks(
    document_id: uuid.UUID,
    body: BlockReplaceRequest,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    """편집화면 저장: 기존 블럭을 block_id 기준으로 병합(보존)하고 전체를 재임베딩·재인덱싱한다."""
    doc = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    if not body.blocks:
        raise HTTPException(status_code=400, detail="블럭 목록이 비어있습니다")

    try:
        existing_blocks = (
            await db.execute(select(Block).where(Block.document_id == document_id))
        ).scalars().all()
        existing_by_id = {b.id: b for b in existing_blocks}
        incoming = [b.model_dump() for b in body.blocks]
        to_delete = _deleted_block_ids(set(existing_by_id), incoming)

        # zero-diff 게이트: 삭제·추가 없고 순서·내용·타입이 기존과 완전히 동일하면 재인덱싱
        # (purge + blocked 이벤트) 없이 즉시 반환 — 수정 없이 '저장'만 눌렀을 때 불필요한 전체
        # 재임베딩(4스텝 파이프라인) 방지. (웹 게이트의 서버측 방어선)
        if not to_delete and all(it.get("block_id") in existing_by_id for it in incoming):
            _ex = sorted(existing_blocks, key=lambda b: b.block_index)
            _ex_sig = [(str(b.id), str(b.block_type), b.content) for b in _ex]
            _in_sig = [(str(it.get("block_id")), str(it["block_type"]), it["content"]) for it in incoming]
            if _ex_sig == _in_sig:
                logger.info("document_blocks_replace_noop", document_id=str(document_id), blocks=len(incoming))
                return ApiResponse(data={
                    "document_id": str(document_id),
                    "replaced": 0,
                    "deleted": 0,
                    "status": "unchanged",
                })

        # 1) delete prune — successor_block_id 참조 먼저 null 처리(RESTRICT 회피)
        if to_delete:
            await db.execute(
                update(Block)
                # 삭제 블럭을 successor 로 가리키던 모든 블럭(문서 무관)의 링크를 끊는다 — RESTRICT 회피 + stale 승계 링크 제거(의도된 동작).
                .where(Block.successor_block_id.in_(to_delete))
                .values(successor_block_id=None)
            )
            for bid in to_delete:
                blk = existing_by_id[bid]
                try:
                    await _remove_from_search_indexes(blk, db)
                except Exception as exc:
                    logger.warning("replace_remove_index_failed", block_id=str(bid), error=str(exc))
                await db.delete(blk)

        # 삭제 먼저 flush — 삭제 블럭 hash 를 update/insert 가 재사용할 때 제약 충돌 방지
        await db.flush()

        # 2) incoming 순서대로 1패스: 기존 id=update(enrichment 보존), 신규=insert.
        #    block_index 는 incoming 위치(idx)로 직접 부여 → 연속성·순서 보장.
        for idx, item in enumerate(incoming):
            bid = item.get("block_id")
            content = item["content"]
            if bid is not None and bid in existing_by_id:
                blk = existing_by_id[bid]
                if blk.content != content:
                    blk.is_indexed = False
                    blk.vector_id = None
                blk.content = content
                blk.block_type = item["block_type"]
                blk.properties = item.get("properties") or None
                # block_id 를 해시에 포함 — uq_blocks_document_hash 제약 하에서, 동일 content 블럭의
                # 재배열 시 발생하던 과도기 충돌(블럭 B가 A의 idx로 이동하며 동일 hash 를 잠시 공유)을
                # 원천 차단한다(블럭 id 는 고유·재배열 시 불변). content 변경 시 hash 도 바뀌어 변경 감지 유지.
                blk.block_hash = _recompute_hash(f"{blk.id}\n{content}")
                blk.block_index = idx
                if item.get("metadata"):
                    blk.meta_info = _apply_editor_metadata(blk.meta_info, item["metadata"])
            else:
                _new_id = uuid.uuid4()
                db.add(Block(
                    id=_new_id,
                    document_id=document_id,
                    repository_id=body.repository_id,
                    block_type=item["block_type"],
                    content=content,
                    block_index=idx,
                    # block_id 기반 hash — 고유 보장(위 update 동일 사유).
                    block_hash=_recompute_hash(f"{_new_id}\n{content}"),
                    token_count=len(content.split()),  # TODO: 정확한 토크나이저 적용 필요(merge_block 과 동일 플레이스홀더)
                    source_location={},
                    properties=item.get("properties") or None,
                    meta_info=_apply_editor_metadata({"source": "frontend_editor"}, item.get("metadata")),
                    is_indexed=False,
                ))

        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("replace_blocks_integrity_error", document_id=str(document_id), error=str(exc))
        raise HTTPException(status_code=409, detail="블럭 저장 중 제약 충돌이 발생했습니다.")
    except Exception:
        await db.rollback()
        raise

    # 인덱스 정리(document_id 일괄) + 재인덱싱 트리거
    await _purge_document_search_indexes(document_id, doc.repository_id, db)
    # 재임베딩이 stale Redis 블록 캐시/잠금이 아니라 방금 갱신한 DB 블록을 쓰도록 정리
    await _clear_reembed_redis_state(document_id)
    _block_types: dict = {}
    for _b in body.blocks:
        _block_types[_b.block_type] = _block_types.get(_b.block_type, 0) + 1
    await _publish_blocked_event(
        document_id,
        len(body.blocks),
        _tenant,
        repository_id=doc.repository_id,
        source_path=doc.source_file or "",
        block_types=_block_types,
    )
    await invalidate_repository_cache(doc.repository_id)
    logger.info("document_blocks_replaced", document_id=str(document_id),
                replaced=len(body.blocks), deleted=len(to_delete))
    return ApiResponse(data={
        "document_id": str(document_id),
        "replaced": len(body.blocks),
        "deleted": len(to_delete),
        "status": "processing",
    })


@router.post(
    "/blocks/{block_id}/generate-metadata",
    response_model=ApiResponse[dict],
    summary="단일 블록 메타데이터(요약/nature/키워드) 생성",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def generate_block_metadata(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    block = (await db.execute(select(Block).where(Block.id == block_id))).scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")
    doc = (await db.execute(select(Document).where(Document.id == block.document_id))).scalar_one_or_none()
    title = doc.title if doc else ""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=settings.VLLM_URL, api_key=settings.VLLM_API_KEY or "dummy")
    try:
        meta = await _generate_block_metadata(block, db, client, document_title=title)
        await db.commit()
    finally:
        await client.close()
    await invalidate_repository_cache(block.repository_id)
    return ApiResponse(data={"block_id": str(block_id), "metadata": meta})


class GenMetaPreviewRequest(BaseModel):
    content: str
    block_type: str = "paragraph"
    document_title: str = ""


@router.post(
    "/blocks/generate-metadata-preview",
    response_model=ApiResponse[dict],
    summary="content 기반 메타데이터 생성(미저장, block_id 불필요)",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def generate_metadata_preview(
    body: GenMetaPreviewRequest,
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    if not (body.content or "").strip():
        raise HTTPException(status_code=400, detail="content 가 비어 있습니다")
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=settings.VLLM_URL, api_key=settings.VLLM_API_KEY or "dummy")
    try:
        meta = await _generate_metadata_for_content(body.content, body.block_type, client, body.document_title)
    finally:
        await client.close()
    return ApiResponse(data={"metadata": meta})


@router.post(
    "/documents/{document_id}/generate-metadata",
    response_model=ApiResponse[dict],
    summary="문서 블록 메타데이터 생성(기본: 누락분만)",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def generate_document_metadata(
    document_id: uuid.UUID,
    only_missing: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict]:
    doc = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    blocks = (await db.execute(select(Block).where(Block.document_id == document_id).order_by(Block.block_index))).scalars().all()

    def _missing(b: Block) -> bool:
        m = b.meta_info or {}
        return not any(m.get(f) for f in _METADATA_FIELDS)

    targets = [b for b in blocks if (_missing(b) if only_missing else True)]
    batch = targets[:_GEN_META_MAX_PER_CALL]
    processed = 0
    failed = 0
    filled = 0  # 실제로 메타 1개 이상 생성된 블록
    empty = 0   # 시도했으나 생성 결과가 비어있는 블록(LLM이 추출 못함)
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=settings.VLLM_URL, api_key=settings.VLLM_API_KEY or "dummy")
    try:
        for b in batch:
            try:
                gen = await _generate_block_metadata(b, db, client, document_title=doc.title or "")
                processed += 1
                if any(gen.get(f) for f in _METADATA_FIELDS):
                    filled += 1
                else:
                    empty += 1
            except Exception as exc:
                failed += 1
                logger.warning("genmeta_doc_block_failed", block_id=str(b.id), error=str(exc))
        await db.commit()
    finally:
        await client.close()
    await invalidate_repository_cache(doc.repository_id)
    remaining = len(targets) - len(batch)
    # filled/empty 로 "시도했으나 생성 안 됨"을 클라이언트가 사용자에게 통보할 수 있게 한다.
    return ApiResponse(data={"document_id": str(document_id), "processed": processed, "filled": filled, "empty": empty, "failed": failed, "skipped": len(blocks) - len(targets), "remaining": remaining})


def _render_blocks_to_html(blocks: list["BlockCreateItem"]) -> str:
    """노션 블럭 배열을 HTML로 렌더링한다 (PDF 변환 또는 HTML 파서 입력용)."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="ko"><head><meta charset="utf-8"></head><body>',
    ]
    for block in blocks:
        tag = _block_type_to_html_tag(block.block_type, block.content, block.properties)
        parts.append(tag)
        # 자식 블럭 재귀 처리
        if block.children:
            parts.append("<div style='margin-left:24px'>")
            for child in block.children:
                parts.append(
                    _block_type_to_html_tag(child.block_type, child.content, child.properties)
                )
            parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _block_type_to_html_tag(block_type: str, content: str, props: dict) -> str:
    """블럭 타입을 HTML 태그로 변환한다."""
    import html as html_mod

    safe = html_mod.escape(content)
    match block_type:
        case "heading_1":
            return f"<h1>{safe}</h1>"
        case "heading_2":
            return f"<h2>{safe}</h2>"
        case "heading_3":
            return f"<h3>{safe}</h3>"
        case "bulleted_list":
            items = safe.split("\n")
            li = "".join(f"<li>{i}</li>" for i in items if i.strip())
            return f"<ul>{li}</ul>"
        case "numbered_list":
            items = safe.split("\n")
            li = "".join(f"<li>{i}</li>" for i in items if i.strip())
            return f"<ol>{li}</ol>"
        case "code":
            lang = props.get("language", "")
            return f"<pre><code class='{lang}'>{safe}</code></pre>"
        case "quote":
            return f"<blockquote>{safe}</blockquote>"
        case "callout":
            return f"<div class='callout'>{safe}</div>"
        case "divider":
            return "<hr>"
        case "table":
            return f"<div>{safe}</div>"  # markdown 표는 그대로 전달
        case "image":
            src = props.get("src", "")
            return f'<img src="{src}" alt="{safe}">' if src else f"<p>[이미지: {safe}]</p>"
        case "to_do":
            checked = "checked" if props.get("checked") else ""
            return f'<div><input type="checkbox" {checked}> {safe}</div>'
        case _:
            return f"<p>{safe}</p>"


async def _publish_upload_event(
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    repository_id: uuid.UUID,
    source_path: str,
    source_format: str,
) -> None:
    """파이프라인 업로드 이벤트를 발행한다."""
    import json

    try:
        from aiokafka import AIOKafkaProducer

        from src.common.storage_tenant import kafka_envelope

        producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        await producer.start()
        try:
            # Phase 2.7 — envelope helper 로 tenant_id 누락 방지.
            event = kafka_envelope(
                tenant_id,
                {
                    "document_id": str(document_id),
                    "repository_id": str(repository_id),
                    "source_path": source_path,
                    "source_format": source_format,
                },
            )
            await producer.send_and_wait(
                "aicm.document.uploaded",
                value=json.dumps(event).encode("utf-8"),
            )
        finally:
            await producer.stop()
    except Exception as exc:
        logger.warning("upload_event_publish_failed", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# 변환 헬퍼
# ---------------------------------------------------------------------------


def _block_to_response(block: Block) -> BlockResponse:
    """Block ORM → BlockResponse."""
    from src.pipeline.services.confidence import grade_confidence

    meta = block.meta_info or {}
    sl = block.source_location or {}

    # Provenance confidence badge (Phase C-2)
    provenance = block.classification_provenance or {}
    confidence_val = provenance.get("confidence", 0.0)
    confidence_grade = grade_confidence(confidence_val) if provenance else None

    return BlockResponse(
        id=block.id,
        document_id=block.document_id,
        repository_id=block.repository_id,
        block_type=block.block_type,
        content=block.content,
        block_index=block.block_index,
        block_hash=block.block_hash,
        token_count=block.token_count,
        source_location=sl,
        metadata=meta,
        is_indexed=block.is_indexed,
        is_noise=block.is_noise,
        created_at=block.created_at,
        updated_at=block.updated_at,
        table_headers=meta.get("table_headers"),
        table_markdown=meta.get("table_markdown"),
        image_description=meta.get("image_description"),
        ocr_text=meta.get("ocr_text"),
        confidence_grade=confidence_grade,
    )


def _block_to_detail_response(
    block: Block,
    include_vector: bool = False,
) -> BlockDetailResponse:
    """Block ORM → BlockDetailResponse (벡터 프리뷰 포함)."""
    base = _block_to_response(block)
    meta = block.meta_info or {}

    vector_preview = None
    if include_vector and block.vector_id:
        # 벡터 프리뷰는 Qdrant 에서 직접 조회해야 하므로 여기서는 None
        # 향후 Qdrant retrieve API 연동
        vector_preview = None

    return BlockDetailResponse(
        **base.model_dump(),
        vector_preview=vector_preview,
        vector_id=block.vector_id,
        contextual_prefix=meta.get("contextual_prefix"),
        extracted_metadata=meta.get("extracted_metadata"),
    )


# ---------------------------------------------------------------------------
# 블럭 이미지 파일 서빙
# ---------------------------------------------------------------------------

UPLOADS_ROOT = Path("/data/uploads")


@router.get(
    "/blocks/{block_id}/image",
    summary="이미지 블럭의 추출 이미지 파일 반환",
    responses={404: {"description": "블럭 없음 / 이미지 아님 / 파일 없음"}},
)
async def get_block_image(
    block_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _tenant: uuid.UUID = Depends(get_current_tenant_id),
) -> FileResponse:
    """이미지 타입 블럭의 추출된 이미지 파일을 반환한다."""
    stmt = select(Block).where(Block.id == block_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다")

    if block.block_type != "image":
        raise HTTPException(status_code=404, detail="이미지 타입 블럭이 아닙니다")

    meta = block.meta_info or {}
    image_path_str = meta.get("image_path")
    if not image_path_str:
        raise HTTPException(status_code=404, detail="이미지 경로가 메타데이터에 없습니다")

    image_path = Path(image_path_str)

    # Path traversal prevention: resolved path must be under UPLOADS_ROOT
    try:
        resolved = image_path.resolve(strict=False)
        if not str(resolved).startswith(str(UPLOADS_ROOT.resolve())):
            logger.warning(
                "path_traversal_attempt",
                block_id=str(block_id),
                image_path=image_path_str,
            )
            raise HTTPException(status_code=404, detail="잘못된 이미지 경로입니다")
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="잘못된 이미지 경로입니다")

    if not image_path.is_file():
        logger.warning(
            "block_image_file_not_found",
            block_id=str(block_id),
            image_path=image_path_str,
        )
        raise HTTPException(status_code=404, detail="이미지 파일을 찾을 수 없습니다")

    content_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"

    return FileResponse(
        path=str(image_path),
        media_type=content_type,
        filename=image_path.name,
    )
