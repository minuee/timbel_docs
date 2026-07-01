"""노트 직접 입력 API 라우터 — 노션 스타일 에디터 파이프라인.

사용자가 파일 업로드 없이 직접 텍스트를 작성/편집하여
지식베이스에 추가할 수 있는 API.

기존 documents + blocks 테이블을 재사용하며,
source_format='note' 로 구분한다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id, get_current_user_id
from src.api.schemas.block import BlockResponse
from src.api.schemas.common import ApiResponse, PaginatedResponse
from src.api.schemas.document import DocumentResponse
from src.common.config import settings
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.middleware.rbac import require_role
from src.core.models.block import Block
from src.core.models.document import Document
from src.core.models.repository import Repository
from src.core.models.user import UserRole
from src.core.services.audit_service import record_action
from src.core.services.document_service import DocumentService

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class NoteBlockItem(BaseModel):
    """프론트엔드 노션 에디터에서 전송하는 블럭 단위."""

    block_type: str = Field(
        ..., description="paragraph, heading_1, heading_2, heading_3, "
                         "bulleted_list, numbered_list, code, quote, "
                         "callout, to_do, divider, table, image"
    )
    content: str = Field(..., description="블럭 텍스트 내용")
    properties: dict = Field(
        default_factory=dict,
        description="블럭 속성 (code language, callout icon, checked 등)",
    )
    children: list["NoteBlockItem"] = Field(
        default_factory=list,
        description="중첩 자식 블럭 (toggle, callout 내부 등)",
    )


class NoteCreateRequest(BaseModel):
    """노트 생성 요청."""

    repository_id: UUID
    title: str = Field(..., min_length=1, max_length=500, description="노트 제목")
    blocks: list[NoteBlockItem] = Field(..., min_length=1, description="블럭 배열")
    description: str | None = Field(None, description="노트 설명")
    category_ids: list[UUID] = Field(default_factory=list, description="카테고리 ID 목록")


class NoteUpdateRequest(BaseModel):
    """노트 편집 요청. 블럭 전체 교체 방식."""

    title: str | None = Field(None, min_length=1, max_length=500)
    blocks: list[NoteBlockItem] | None = Field(None, description="블럭 배열 (전체 교체)")
    description: str | None = None


class NoteResponse(BaseModel):
    """노트 응답 (문서 + 블럭)."""

    document: DocumentResponse
    blocks: list[BlockResponse]
    block_count: int


class NoteListItem(BaseModel):
    """노트 목록 항목."""

    id: UUID
    title: str
    description: str | None
    status: str
    block_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# POST /api/v1/notes — 노트 생성
# ---------------------------------------------------------------------------


@router.post(
    "/notes",
    response_model=ApiResponse[NoteResponse],
    status_code=201,
    summary="노트 직접 입력 (노션 스타일 블럭 배열)",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def create_note(
    body: NoteCreateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
) -> ApiResponse[NoteResponse]:
    """직접 작성한 텍스트를 노트로 저장한다.

    처리 흐름:
    1. Document 레코드 생성 (source_format='note', status='active')
    2. Block 레코드 삽입 (프론트엔드 블럭 배열 → 평탄화)
    3. 임베딩 큐 발행 (Kafka aicm.document.blocked 이벤트)
    4. 즉시 응답 (document + blocks)
    """
    # 1. Document 생성
    svc = DocumentService(db)
    doc = await svc.create(
        repository_id=body.repository_id,
        tenant_id=tenant_id,
        title=body.title,
        description=body.description,
        source_format="note",
        created_by=user_id,
        category_ids=body.category_ids if body.category_ids else None,
    )

    # 노트는 파이프라인 불필요 — 바로 active 로 전이
    doc.status = "active"
    doc.processing_meta = {
        "source": "note_editor",
        "block_count": 0,  # 아래에서 갱신
        "created_via": "direct_input",
    }

    # 2. Block 레코드 삽입
    block_rows = _flatten_note_blocks(
        items=body.blocks,
        document_id=doc.id,
        repository_id=body.repository_id,
        start_index=0,
    )

    for blk in block_rows:
        db.add(blk)

    doc.processing_meta["block_count"] = len(block_rows)

    await db.commit()
    await db.refresh(doc)

    # 3. 임베딩 큐 발행 (best-effort) - block_type 분포 집계
    block_types_count: dict[str, int] = {}
    for blk in block_rows:
        bt = blk.block_type or "paragraph"
        block_types_count[bt] = block_types_count.get(bt, 0) + 1

    await _publish_note_event(
        document_id=doc.id,
        tenant_id=tenant_id,
        repository_id=body.repository_id,
        block_count=len(block_rows),
        block_types=block_types_count,
    )

    # 4. 응답 구성
    blocks_resp = [_block_to_response(b) for b in block_rows]

    # 감사 로그
    record_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action="CREATE",
        resource_type="note",
        resource_id=doc.id,
        detail={
            "title": body.title,
            "repository_id": str(body.repository_id),
            "block_count": len(block_rows),
        },
    )

    logger.info(
        "note_created",
        document_id=str(doc.id),
        title=body.title,
        block_count=len(block_rows),
    )

    return ApiResponse(
        data=NoteResponse(
            document=DocumentResponse.model_validate(doc),
            blocks=blocks_resp,
            block_count=len(blocks_resp),
        )
    )


# ---------------------------------------------------------------------------
# GET /api/v1/notes/{doc_id} — 노트 조회 (에디터 로드용)
# ---------------------------------------------------------------------------


@router.get(
    "/notes/{doc_id}",
    response_model=ApiResponse[NoteResponse],
    summary="노트 조회 (에디터 로드용)",
)
async def get_note(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[NoteResponse]:
    """노트 문서와 블럭 배열을 반환한다. 에디터 로드에 사용."""
    doc = await _get_note_document(doc_id, db)

    # 블럭 조회
    stmt = (
        select(Block)
        .where(Block.document_id == doc_id)
        .order_by(Block.block_index)
    )
    result = await db.execute(stmt)
    blocks = list(result.scalars().all())

    blocks_resp = [_block_to_response(b) for b in blocks]

    return ApiResponse(
        data=NoteResponse(
            document=DocumentResponse.model_validate(doc),
            blocks=blocks_resp,
            block_count=len(blocks_resp),
        )
    )


# ---------------------------------------------------------------------------
# GET /api/v1/notes — 노트 목록 조회
# ---------------------------------------------------------------------------


@router.get(
    "/notes",
    response_model=ApiResponse[PaginatedResponse[NoteListItem]],
    summary="노트 목록 조회",
)
async def list_notes(
    repository_id: UUID = Query(..., description="저장소 ID"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[PaginatedResponse[NoteListItem]]:
    """저장소 내 노트(source_format='note') 목록을 조회한다."""
    base_filter = (
        select(Document)
        .where(
            Document.repository_id == repository_id,
            Document.source_format == "note",
        )
    )

    # 총 개수
    count_stmt = select(func.count()).select_from(base_filter.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # 목록
    stmt = base_filter.order_by(Document.updated_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    docs = list(result.scalars().all())

    # 각 문서의 블럭 수 조회
    doc_ids = [d.id for d in docs]
    block_counts: dict[UUID, int] = {}
    if doc_ids:
        bc_stmt = (
            select(Block.document_id, func.count())
            .where(Block.document_id.in_(doc_ids))
            .group_by(Block.document_id)
        )
        bc_result = await db.execute(bc_stmt)
        block_counts = {row[0]: row[1] for row in bc_result.all()}

    items = [
        NoteListItem(
            id=d.id,
            title=d.title,
            description=d.description,
            status=d.status,
            block_count=block_counts.get(d.id, 0),
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in docs
    ]

    return ApiResponse(
        data=PaginatedResponse(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
        )
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/notes/{doc_id} — 노트 편집
# ---------------------------------------------------------------------------


@router.patch(
    "/notes/{doc_id}",
    response_model=ApiResponse[NoteResponse],
    summary="노트 편집 (블럭 전체 교체)",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def update_note(
    doc_id: UUID,
    body: NoteUpdateRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
) -> ApiResponse[NoteResponse]:
    """노트를 편집한다. 블럭이 제공되면 전체 교체."""
    doc = await _get_note_document(doc_id, db)

    # 제목/설명 변경
    if body.title is not None:
        doc.title = body.title
    if body.description is not None:
        doc.description = body.description

    # 블럭 전체 교체
    if body.blocks is not None:
        # 기존 블럭 삭제
        await db.execute(
            delete(Block).where(Block.document_id == doc_id)
        )
        await db.flush()

        # 새 블럭 삽입
        block_rows = _flatten_note_blocks(
            items=body.blocks,
            document_id=doc_id,
            repository_id=doc.repository_id,
            start_index=0,
        )
        for blk in block_rows:
            db.add(blk)

        # processing_meta 갱신
        meta = doc.processing_meta or {}
        meta["block_count"] = len(block_rows)
        meta["last_edited"] = datetime.utcnow().isoformat()
        doc.processing_meta = meta
    else:
        block_rows = None

    await db.commit()
    await db.refresh(doc)

    # 변경된 블럭이 있으면 재임베딩 이벤트 발행
    if block_rows is not None:
        block_types_count: dict[str, int] = {}
        for blk in block_rows:
            bt = blk.block_type or "paragraph"
            block_types_count[bt] = block_types_count.get(bt, 0) + 1
        await _publish_note_event(
            document_id=doc.id,
            tenant_id=tenant_id,
            repository_id=doc.repository_id,
            block_count=len(block_rows),
            block_types=block_types_count,
        )

    # 응답 위해 블럭 재조회
    stmt = (
        select(Block)
        .where(Block.document_id == doc_id)
        .order_by(Block.block_index)
    )
    result = await db.execute(stmt)
    all_blocks = list(result.scalars().all())

    blocks_resp = [_block_to_response(b) for b in all_blocks]

    # 감사 로그
    record_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action="UPDATE",
        resource_type="note",
        resource_id=doc_id,
        detail={
            "title_changed": body.title is not None,
            "blocks_replaced": body.blocks is not None,
            "block_count": len(blocks_resp),
        },
    )

    logger.info(
        "note_updated",
        document_id=str(doc_id),
        blocks_replaced=body.blocks is not None,
    )

    return ApiResponse(
        data=NoteResponse(
            document=DocumentResponse.model_validate(doc),
            blocks=blocks_resp,
            block_count=len(blocks_resp),
        )
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/notes/{doc_id} — 노트 삭제
# ---------------------------------------------------------------------------


@router.delete(
    "/notes/{doc_id}",
    response_model=ApiResponse[dict],
    summary="노트 삭제",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def delete_note(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
) -> ApiResponse[dict]:
    """노트와 관련 블럭을 삭제한다."""
    doc = await _get_note_document(doc_id, db)

    # 블럭 삭제 (CASCADE가 있지만 명시적으로)
    await db.execute(delete(Block).where(Block.document_id == doc_id))
    await db.delete(doc)
    await db.commit()

    record_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action="DELETE",
        resource_type="note",
        resource_id=doc_id,
        detail={"title": doc.title},
    )

    logger.info("note_deleted", document_id=str(doc_id))

    return ApiResponse(data={"deleted": True, "document_id": str(doc_id)})


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------


async def _get_note_document(doc_id: UUID, db: AsyncSession) -> Document:
    """노트 문서를 조회한다. 존재하지 않으면 404."""
    stmt = select(Document).where(Document.id == doc_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="노트를 찾을 수 없습니다")
    return doc


def _flatten_note_blocks(
    items: list[NoteBlockItem],
    document_id: uuid.UUID,
    repository_id: uuid.UUID,
    start_index: int,
    parent_id: uuid.UUID | None = None,
) -> list[Block]:
    """NoteBlockItem 트리를 평탄화하여 Block ORM 인스턴스 리스트로 변환한다."""
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
            meta_info={"source": "note_editor"},
            is_indexed=False,
        )
        result.append(block)
        idx += 1
        # 자식 블럭 재귀 처리
        if item.children:
            children = _flatten_note_blocks(
                item.children, document_id, repository_id, idx, parent_id=block_id
            )
            result.extend(children)
            idx += len(children)
    return result


async def _publish_note_event(
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    repository_id: uuid.UUID,
    block_count: int,
    block_types: dict[str, int],
) -> None:
    """Kafka에 DocumentBlockedEvent 형식으로 발행 (임베딩 워커가 즉시 처리).

    embed_worker는 Redis 캐시 미스 시 DB에서 블럭을 로드하므로
    노트(캐시 없음) 처리에도 호환된다.
    """
    try:
        from aiokafka import AIOKafkaProducer

        from src.common.storage_tenant import kafka_envelope

        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await producer.start()
        try:
            # Phase 2.7 — envelope helper 로 tenant_id 누락 방지.
            event = kafka_envelope(
                tenant_id,
                {
                    "event_id": str(uuid.uuid4()),
                    "document_id": str(document_id),
                    "repository_id": str(repository_id),
                    "block_count": block_count,
                    "block_types": block_types,
                    "source_path": f"note://{document_id}",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            await producer.send_and_wait(
                "aicm.document.blocked",
                value=json.dumps(event).encode("utf-8"),
            )
            logger.info(
                "note_blocked_event_published",
                document_id=str(document_id),
                block_count=block_count,
            )
        finally:
            await producer.stop()
    except Exception as exc:
        logger.warning(
            "note_blocked_event_failed",
            document_id=str(document_id),
            error=str(exc),
        )


def _block_to_response(block: Block) -> BlockResponse:
    """Block ORM -> BlockResponse (노트 전용 변환)."""
    try:
        from src.pipeline.services.confidence import grade_confidence
    except ImportError:
        grade_confidence = None

    meta = block.meta_info or {}
    sl = block.source_location or {}

    confidence_grade = None
    if grade_confidence is not None:
        provenance = block.classification_provenance or {}
        confidence_val = provenance.get("confidence", 0.0)
        if provenance:
            confidence_grade = grade_confidence(confidence_val)

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
        created_at=block.created_at,
        updated_at=block.updated_at,
        table_headers=meta.get("table_headers"),
        table_markdown=meta.get("table_markdown"),
        image_description=meta.get("image_description"),
        ocr_text=meta.get("ocr_text"),
        confidence_grade=confidence_grade,
    )
