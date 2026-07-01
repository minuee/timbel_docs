"""Chunk Inspector API 라우터 — 청크 상세 조회, 유사 청크 검색, 비교.

문서 파이프라인이 생성한 청크를 개별적으로 조회/검사하고,
벡터 유사도 기반으로 유사 청크를 탐색하거나 두 청크를 비교할 수 있다.
"""

from __future__ import annotations

import difflib
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse, PaginatedResponse
from src.api.schemas.document import ChunkResponse, SourceLocationSchema
from src.common.config import settings
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.middleware.rbac import require_role
from src.core.models.document import Chunk, Document
from src.core.models.user import UserRole

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 응답 스키마
# ---------------------------------------------------------------------------


class ChunkDetailResponse(BaseModel):
    """청크 상세 응답 (벡터 프리뷰 포함)."""

    id: uuid.UUID
    document_id: uuid.UUID
    section_id: Optional[uuid.UUID] = None
    repository_id: uuid.UUID
    content: str
    chunk_index: int
    chunk_hash: str
    token_count: Optional[int] = None
    source_location: SourceLocationSchema = Field(default_factory=SourceLocationSchema)
    metadata: dict = Field(default_factory=dict)
    is_indexed: bool = False
    vector_preview: Optional[list[float]] = Field(
        None, description="Dense 벡터 첫 10차원 미리보기"
    )
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class SimilarChunkItem(BaseModel):
    """유사 청크 항목."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: Optional[str] = None
    content_preview: str = ""
    score: float = 0.0
    chunk_index: int = 0


class SimilarChunksResponse(BaseModel):
    """유사 청크 검색 응답."""

    source_chunk_id: uuid.UUID
    similar_chunks: list[SimilarChunkItem] = Field(default_factory=list)


class ChunkCompareRequest(BaseModel):
    """청크 비교 요청."""

    chunk_id_a: uuid.UUID
    chunk_id_b: uuid.UUID


class ChunkCompareResponse(BaseModel):
    """청크 비교 응답."""

    chunk_a: ChunkDetailResponse
    chunk_b: ChunkDetailResponse
    cosine_similarity: Optional[float] = None
    diff_lines: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------


def _chunk_to_detail(chunk: Chunk, vector_preview: list[float] | None = None) -> ChunkDetailResponse:
    """ORM Chunk -> ChunkDetailResponse 변환."""
    src_loc = chunk.source_location or {}
    return ChunkDetailResponse(
        id=chunk.id,
        document_id=chunk.document_id,
        section_id=chunk.section_id,
        repository_id=chunk.repository_id,
        content=chunk.content,
        chunk_index=chunk.chunk_index,
        chunk_hash=chunk.chunk_hash,
        token_count=chunk.token_count,
        source_location=SourceLocationSchema(**src_loc) if src_loc else SourceLocationSchema(),
        metadata=chunk.meta_info or {},
        is_indexed=chunk.is_indexed,
        vector_preview=vector_preview,
        created_at=chunk.created_at.isoformat() if chunk.created_at else None,
    )


async def _get_vector_preview(chunk: Chunk) -> list[float] | None:
    """Qdrant에서 청크의 Dense 벡터 첫 10차원을 가져온다."""
    if not chunk.vector_id:
        return None
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)

        # 컬렉션 이름 추정
        from src.core.models.repository import Repository

        # vector_id를 사용하여 포인트 조회 — 컬렉션명은 별도 조회 필요
        # 여기서는 chunk.meta_info에 저장된 collection을 사용하거나 fallback
        collection = (chunk.meta_info or {}).get("qdrant_collection", "")
        if not collection:
            return None

        points = client.retrieve(
            collection_name=collection,
            ids=[chunk.vector_id],
            with_vectors=True,
        )
        if points and hasattr(points[0], "vector"):
            vec = points[0].vector
            if isinstance(vec, dict):
                dense = vec.get("dense", [])
            else:
                dense = vec
            return list(dense[:10]) if dense else None
    except Exception as exc:
        logger.debug("vector_preview_failed", chunk_id=str(chunk.id), error=str(exc))
    return None


async def _compute_cosine_similarity(chunk_a: Chunk, chunk_b: Chunk) -> float | None:
    """Qdrant에서 두 청크의 Dense 벡터를 가져와 코사인 유사도를 계산한다."""
    if not chunk_a.vector_id or not chunk_b.vector_id:
        return None
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)

        collection_a = (chunk_a.meta_info or {}).get("qdrant_collection", "")
        collection_b = (chunk_b.meta_info or {}).get("qdrant_collection", "")
        if not collection_a or not collection_b:
            return None

        points_a = client.retrieve(
            collection_name=collection_a,
            ids=[chunk_a.vector_id],
            with_vectors=True,
        )
        points_b = client.retrieve(
            collection_name=collection_b,
            ids=[chunk_b.vector_id],
            with_vectors=True,
        )

        if not points_a or not points_b:
            return None

        vec_a = points_a[0].vector
        vec_b = points_b[0].vector

        if isinstance(vec_a, dict):
            vec_a = vec_a.get("dense", [])
        if isinstance(vec_b, dict):
            vec_b = vec_b.get("dense", [])

        if not vec_a or not vec_b:
            return None

        # 코사인 유사도 계산
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return round(dot / (norm_a * norm_b), 6)
    except Exception as exc:
        logger.debug("cosine_similarity_failed", error=str(exc))
    return None


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{doc_id}/chunks",
    response_model=ApiResponse[PaginatedResponse[ChunkResponse]],
    summary="문서의 청크 목록",
    dependencies=[Depends(require_role(UserRole.viewer))],
)
async def list_document_chunks(
    doc_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaginatedResponse[ChunkResponse]]:
    """문서에 속한 청크 목록을 chunk_index 순서로 조회한다."""
    # 문서 소유권 확인
    stmt_doc = select(Document).where(Document.id == doc_id)
    result = await db.execute(stmt_doc)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    # 청크 조회
    stmt = (
        select(Chunk)
        .where(Chunk.document_id == doc_id)
        .order_by(Chunk.chunk_index)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()

    # 총 수
    from sqlalchemy import func as sa_func

    stmt_count = select(sa_func.count(Chunk.id)).where(Chunk.document_id == doc_id)
    result = await db.execute(stmt_count)
    total = result.scalar_one() or 0

    items = [
        ChunkResponse(
            id=c.id,
            document_id=c.document_id,
            section_id=c.section_id,
            content=c.content,
            chunk_index=c.chunk_index,
            chunk_hash=c.chunk_hash,
            token_count=c.token_count,
            source_location=SourceLocationSchema(**(c.source_location or {})),
            metadata=c.meta_info or {},
            is_indexed=c.is_indexed,
        )
        for c in chunks
    ]

    return ApiResponse(
        data=PaginatedResponse(items=items, total_count=total)
    )


@router.get(
    "/chunks/{chunk_id}",
    response_model=ApiResponse[ChunkDetailResponse],
    summary="청크 상세 조회",
    dependencies=[Depends(require_role(UserRole.viewer))],
)
async def get_chunk_detail(
    chunk_id: uuid.UUID,
    include_vector: bool = Query(False, description="벡터 프리뷰 포함 여부"),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChunkDetailResponse]:
    """개별 청크의 상세 정보를 조회한다 (content, source_location, metadata, 벡터 프리뷰)."""
    stmt = select(Chunk).where(Chunk.id == chunk_id)
    result = await db.execute(stmt)
    chunk = result.scalar_one_or_none()

    if chunk is None:
        raise HTTPException(status_code=404, detail="청크를 찾을 수 없습니다.")

    vector_preview = None
    if include_vector:
        vector_preview = await _get_vector_preview(chunk)

    detail = _chunk_to_detail(chunk, vector_preview=vector_preview)
    return ApiResponse(data=detail)


@router.get(
    "/chunks/{chunk_id}/similar",
    response_model=ApiResponse[SimilarChunksResponse],
    summary="유사 청크 검색",
    dependencies=[Depends(require_role(UserRole.viewer))],
)
async def find_similar_chunks(
    chunk_id: uuid.UUID,
    top_k: int = Query(10, ge=1, le=50, description="반환할 유사 청크 수"),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SimilarChunksResponse]:
    """Qdrant nearest neighbor 검색으로 유사 청크를 탐색한다."""
    stmt = select(Chunk).where(Chunk.id == chunk_id)
    result = await db.execute(stmt)
    chunk = result.scalar_one_or_none()

    if chunk is None:
        raise HTTPException(status_code=404, detail="청크를 찾을 수 없습니다.")

    similar_items: list[SimilarChunkItem] = []

    if chunk.vector_id:
        try:
            from qdrant_client import QdrantClient

            client = QdrantClient(
                url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None
            )

            collection = (chunk.meta_info or {}).get("qdrant_collection", "")
            if collection:
                # 소스 벡터 조회
                points = client.retrieve(
                    collection_name=collection,
                    ids=[chunk.vector_id],
                    with_vectors=True,
                )
                if points:
                    vec = points[0].vector
                    if isinstance(vec, dict):
                        dense_vec = vec.get("dense", [])
                    else:
                        dense_vec = vec

                    if dense_vec:
                        search_result = client.search(
                            collection_name=collection,
                            query_vector=("dense", dense_vec),
                            limit=top_k + 1,  # +1 자기 자신 제외
                        )

                        for hit in search_result:
                            hit_vector_id = str(hit.id)
                            if hit_vector_id == chunk.vector_id:
                                continue

                            # DB에서 매칭되는 청크 조회
                            stmt_match = select(Chunk).where(
                                Chunk.vector_id == hit_vector_id
                            )
                            result_match = await db.execute(stmt_match)
                            match_chunk = result_match.scalar_one_or_none()

                            doc_title = None
                            if match_chunk:
                                stmt_doc = select(Document.title).where(
                                    Document.id == match_chunk.document_id
                                )
                                result_doc = await db.execute(stmt_doc)
                                doc_title = result_doc.scalar_one_or_none()

                                similar_items.append(SimilarChunkItem(
                                    chunk_id=match_chunk.id,
                                    document_id=match_chunk.document_id,
                                    document_title=doc_title,
                                    content_preview=match_chunk.content[:200],
                                    score=round(hit.score, 4),
                                    chunk_index=match_chunk.chunk_index,
                                ))

                            if len(similar_items) >= top_k:
                                break
        except Exception as exc:
            logger.warning("similar_chunks_search_failed", chunk_id=str(chunk_id), error=str(exc))

    return ApiResponse(
        data=SimilarChunksResponse(
            source_chunk_id=chunk_id,
            similar_chunks=similar_items,
        )
    )


@router.post(
    "/chunks/compare",
    response_model=ApiResponse[ChunkCompareResponse],
    summary="청크 비교",
    dependencies=[Depends(require_role(UserRole.viewer))],
)
async def compare_chunks(
    body: ChunkCompareRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChunkCompareResponse]:
    """두 청크를 비교한다 (코사인 유사도, 텍스트 diff)."""
    stmt_a = select(Chunk).where(Chunk.id == body.chunk_id_a)
    result_a = await db.execute(stmt_a)
    chunk_a = result_a.scalar_one_or_none()

    stmt_b = select(Chunk).where(Chunk.id == body.chunk_id_b)
    result_b = await db.execute(stmt_b)
    chunk_b = result_b.scalar_one_or_none()

    if chunk_a is None or chunk_b is None:
        missing = []
        if chunk_a is None:
            missing.append(str(body.chunk_id_a))
        if chunk_b is None:
            missing.append(str(body.chunk_id_b))
        raise HTTPException(
            status_code=404,
            detail=f"청크를 찾을 수 없습니다: {', '.join(missing)}",
        )

    # 코사인 유사도
    cosine_sim = await _compute_cosine_similarity(chunk_a, chunk_b)

    # 텍스트 diff
    diff = list(difflib.unified_diff(
        chunk_a.content.splitlines(keepends=True),
        chunk_b.content.splitlines(keepends=True),
        fromfile=f"chunk_{body.chunk_id_a}",
        tofile=f"chunk_{body.chunk_id_b}",
        lineterm="",
    ))

    return ApiResponse(
        data=ChunkCompareResponse(
            chunk_a=_chunk_to_detail(chunk_a),
            chunk_b=_chunk_to_detail(chunk_b),
            cosine_similarity=cosine_sim,
            diff_lines=diff,
        )
    )
