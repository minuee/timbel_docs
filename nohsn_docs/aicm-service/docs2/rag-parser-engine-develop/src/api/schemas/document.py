"""문서 관련 Pydantic 스키마."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    """문서 생성 요청 (메타데이터만, 파일 없이)."""

    repository_id: UUID
    title: str = Field(..., min_length=1, max_length=500, description="문서 제목")
    description: Optional[str] = None
    document_type_id: Optional[UUID] = None
    category_ids: list[UUID] = Field(default_factory=list, description="카테고리 ID 목록 (N:M)")


class DocumentUpdate(BaseModel):
    """문서 수정 요청."""

    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    document_type_id: Optional[UUID] = None
    category_ids: Optional[list[UUID]] = None
    status: Optional[str] = Field(
        None,
        # VALID_STATUS_TRANSITIONS 에 정의된 모든 상태 허용.
        # 실제 전이 유효성은 DocumentService.transition_status 가 검증한다
        # (예: processing→active 는 여기 통과해도 400 거절).
        pattern=r"^(draft|processing|pending_review|active|archived|failed)$",
        description="문서 상태",
    )
    # alembic 068 — doc 레벨 SOP 플래그 토글. None = 변경 없음.
    # kms_sop.search 가 d.is_sop=true OR folder.kind='sop' 로 좁히므로,
    # 이 값을 바꾸면 *즉시* SOP 검색 풀이 변동. 검색 인덱스 재빌드 불필요
    # (kms_sop.py 가 SQL 직접 조회 — 벡터 payload 에 반영 X).
    is_sop: Optional[bool] = Field(
        None,
        description="True = SOP 문서로 분류, False = 일반 지식자료. None 이면 변경 없음.",
    )


class DocumentResponse(BaseModel):
    """문서 응답."""

    id: UUID
    repository_id: UUID
    repository_name: Optional[str] = None
    document_type_id: Optional[UUID]
    title: str
    description: Optional[str]
    source_file: Optional[str]
    source_format: Optional[str]
    version: int
    status: str
    search_excluded: bool = False
    folder_id: Optional[UUID] = None  # alembic 067 — 라이브러리 폴더 (NULL=root)
    # alembic 068 — doc 레벨 SOP 플래그. kms_sop.search 가 좁혀 매뉴얼 혼용 차단.
    # 기본 false. reseed 시 LLM 1-shot 분류로 채움.
    is_sop: bool = False
    processing_meta: dict = Field(default_factory=dict)
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    category_ids: list[UUID] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PipelineStageInfo(BaseModel):
    """파이프라인 개별 스테이지 정보."""

    name: str
    status: str = "pending"  # pending / in_progress / completed / failed
    elapsed_ms: Optional[int] = None
    detail: Optional[str] = None
    progress: Optional[int] = None


class PipelineStatusResponse(BaseModel):
    """문서 파이프라인 상태 응답."""

    document_id: UUID
    status: str
    stage: str
    current_stage: Optional[str] = None
    progress_pct: float = 0
    progress_percent: int = 0
    stage_detail: Optional[str] = None
    chunk_count: Optional[int] = None
    block_count: Optional[int] = None
    difficulty: Optional[str] = None
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    failed_stage: Optional[str] = None
    retry_count: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    stages: list[PipelineStageInfo] = Field(default_factory=list)
    control_signal: Optional[str] = None
    paused_before_stage: Optional[str] = None
    page_count: Optional[int] = None


class SourceLocationSchema(BaseModel):
    """청크의 원본 문서 내 위치 정보."""

    file_path: Optional[str] = None
    page_number: Optional[int] = None
    page_range: Optional[list[int]] = None
    start_char_offset: Optional[int] = None
    end_char_offset: Optional[int] = None
    bbox: Optional[list[float]] = None
    heading_path: list[str] = Field(default_factory=list)
    sheet_name: Optional[str] = None
    table_index: Optional[int] = None
    paragraph_index: Optional[int] = None


class StatusChangeRequest(BaseModel):
    """문서 상태 강제 변경 요청 (관리자용)."""

    status: str = Field(
        ...,
        pattern=r"^(active|failed|archived|processing|pending_review)$",
        description="변경할 상태 (active, failed, archived, processing, pending_review)",
    )
    reason: Optional[str] = Field(None, description="상태 변경 사유")


class SearchExclusionRequest(BaseModel):
    """문서 검색 제외 토글 요청."""

    excluded: bool = Field(..., description="True = 검색/RAG 에서 제외, False = 복원")


class ProcessingDocumentResponse(BaseModel):
    """처리중/실패 문서 응답."""

    id: UUID
    repository_id: UUID
    repository_name: Optional[str] = None
    title: str
    status: str
    source_format: Optional[str] = None
    # alembic 068 — doc 레벨 SOP 플래그.
    is_sop: bool = False
    processing_meta: dict = Field(default_factory=dict)
    current_stage: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChunkResponse(BaseModel):
    """청크 응답."""

    id: UUID
    document_id: UUID
    section_id: Optional[UUID] = None
    content: str
    chunk_index: int
    chunk_hash: str
    token_count: Optional[int] = None
    source_location: SourceLocationSchema = Field(default_factory=SourceLocationSchema)
    metadata: dict = Field(default_factory=dict)
    is_indexed: bool = False
