"""재처리 API -- 문서/저장소 단위 재처리 엔드포인트.

Phase 2 Task B-8.
POST /api/v1/documents/reprocess
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.common.logging import get_logger
from src.pipeline.models.document import ProcessingConfig

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["reprocess"])


class ReprocessRequest(BaseModel):
    """재처리 요청 모델."""

    document_ids: list[UUID] = Field(
        ..., description="재처리할 문서 ID 목록", min_length=1, max_length=100
    )
    tenant_id: UUID
    repository_id: UUID
    source_paths: dict[str, str] = Field(
        default_factory=dict,
        description="문서 ID -> 파일 경로 매핑 (선택, 없으면 DB에서 조회)",
    )
    config_override: Optional[ProcessingConfig] = None


class ReprocessResponse(BaseModel):
    """재처리 응답 모델."""

    accepted: int = Field(..., description="수락된 재처리 요청 수")
    document_ids: list[str] = Field(..., description="재처리 대상 문서 ID 목록")
    message: str = "재처리가 백그라운드에서 시작되었습니다."


class ReprocessStatusResponse(BaseModel):
    """재처리 상태 응답."""

    document_id: str
    status: str  # "pending" / "processing" / "completed" / "failed"
    deleted: int = 0
    indexed: int = 0
    elapsed_ms: int = 0
    error: Optional[str] = None


@router.post("/reprocess", response_model=ReprocessResponse)
async def reprocess_documents(
    request: ReprocessRequest,
    background_tasks: BackgroundTasks,
) -> ReprocessResponse:
    """문서 재처리를 요청한다.

    기존 청크를 삭제하고 새로 파이프라인을 실행한다.
    백그라운드 태스크로 처리하므로 즉시 응답한다.
    """
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="재처리할 문서 ID가 없습니다.")

    config = request.config_override or ProcessingConfig()

    for doc_id in request.document_ids:
        source_path = request.source_paths.get(str(doc_id), "")
        if not source_path:
            log.warning(
                "reprocess_missing_source_path",
                document_id=str(doc_id),
            )
            continue

        background_tasks.add_task(
            _run_reprocess,
            document_id=doc_id,
            tenant_id=request.tenant_id,
            repository_id=request.repository_id,
            source_path=source_path,
            config=config,
        )

    log.info(
        "reprocess_accepted",
        document_count=len(request.document_ids),
        tenant_id=str(request.tenant_id),
    )

    return ReprocessResponse(
        accepted=len(request.document_ids),
        document_ids=[str(d) for d in request.document_ids],
    )


async def _run_reprocess(
    document_id: UUID,
    tenant_id: UUID,
    repository_id: UUID,
    source_path: str,
    config: ProcessingConfig,
) -> None:
    """백그라운드에서 문서 재처리를 실행한다."""
    try:
        from src.pipeline.workers.reprocess_worker import handle_reprocess

        result = await handle_reprocess(
            document_id=document_id,
            tenant_id=tenant_id,
            repository_id=repository_id,
            source_path=source_path,
            config=config,
            qdrant_client=None,  # DI 로 주입 예정
            producer=None,
        )

        log.info(
            "reprocess_background_complete",
            document_id=str(document_id),
            result=result,
        )

    except Exception as exc:
        log.error(
            "reprocess_background_failed",
            document_id=str(document_id),
            error=str(exc),
        )
