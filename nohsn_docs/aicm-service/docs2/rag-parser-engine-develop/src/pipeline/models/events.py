"""Kafka 이벤트 모델 — DEV_SPEC.md 3 기준."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.pipeline.models.document import (
    ChunkStrategy,
    DocumentFormat,
    ProcessingConfig,
    ProcessingDifficulty,
)


class DocumentUploadedEvent(BaseModel):
    """문서 업로드 이벤트 -- Parse Worker가 소비."""

    event_id: UUID
    tenant_id: UUID
    document_id: UUID
    repository_id: UUID
    source_format: DocumentFormat
    source_path: str
    title: str = ""
    category_ids: list[UUID] = Field(default_factory=list)
    document_type_id: Optional[UUID] = None
    config_override: Optional[ProcessingConfig] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("source_format", mode="before")
    @classmethod
    def _normalize_source_format(cls, v):
        """legacy producer (memo_v1.py 'md' literal 등) 정규화 → 'markdown'.

        D44 진단: documents.source_format='md' 가 recovery.py 통해 Kafka 재발행
        시 enum mismatch → DLQ. 단일 canonical value 유지로 회귀 위험 최소화.
        """
        if isinstance(v, str):
            s = v.strip().lower()
            if s == "md":
                return "markdown"
            return s
        return v


class DocumentParsedEvent(BaseModel):
    """파싱 완료 이벤트 -- Chunk Worker가 소비."""

    event_id: UUID
    document_id: UUID
    tenant_id: UUID
    repository_id: UUID
    difficulty: ProcessingDifficulty
    page_count: int
    table_count: int
    image_count: int
    raw_text_length: int
    source_path: str
    document_type: Optional[str] = None
    document_structure: Optional[dict] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DocumentChunkedEvent(BaseModel):
    """청킹 완료 이벤트 -- Embed Worker가 소비."""

    event_id: UUID
    document_id: UUID
    tenant_id: UUID
    repository_id: UUID
    chunk_count: int
    strategy_used: ChunkStrategy
    avg_token_count: float
    source_path: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DocumentBlockedEvent(BaseModel):
    """블럭 세그멘테이션 완료 이벤트 -- Embed Worker가 소비 (블럭 파이프라인)."""

    event_id: UUID
    document_id: UUID
    tenant_id: UUID
    repository_id: UUID
    block_count: int
    block_types: dict = Field(default_factory=dict)  # {"paragraph": 10, "table": 2, ...}
    source_path: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DocumentReviewRequiredEvent(BaseModel):
    """리뷰 필요 이벤트 — 블럭 세그멘테이션 후 사람 판단이 필요할 때 발행.

    프론트엔드는 이 이벤트를 받아 리뷰 대시보드에 문서를 표시한다.
    사용자가 승인하면 DocumentBlockedEvent로 이어져 임베딩이 진행된다.
    """

    event_id: UUID
    document_id: UUID
    tenant_id: UUID
    repository_id: UUID
    block_count: int
    review_required_blocks: int = Field(description="리뷰가 필요한 블럭 수")
    auto_approved_blocks: int = Field(description="자동 승인된 블럭 수")
    review_reasons: list[str] = Field(
        default_factory=list,
        description="리뷰 사유 (low_confidence, ambiguous_type, no_category_match 등)",
    )
    processing_report: dict = Field(
        default_factory=dict,
        description="파이프라인 처리 보고서 전체",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ProcessingStageReport(BaseModel):
    """파이프라인 단일 스테이지 처리 보고서."""

    stage: str = Field(description="parsing / segmentation / enrichment")
    status: str = Field(description="completed / partial / failed")
    duration_ms: int = Field(0, description="처리 소요 시간 (ms)")
    model_used: Optional[str] = Field(None, description="사용된 LLM 모델")
    input_summary: dict = Field(default_factory=dict, description="입력 요약 (페이지 수 등)")
    output_summary: dict = Field(default_factory=dict, description="출력 요약 (블럭 수 등)")
    warnings: list[str] = Field(default_factory=list, description="경고 사항")
    errors: list[str] = Field(default_factory=list, description="오류 사항")


class BlockReviewItem(BaseModel):
    """개별 블럭 리뷰 항목 — 사람이 확인/수정해야 하는 블럭 정보."""

    block_id: UUID
    block_type: str
    content_preview: str = Field(description="내용 앞 200자")
    confidence: float = Field(description="분류 신뢰도 (0.0~1.0)")
    nature: Optional[str] = None
    review_reason: str = Field(description="리뷰 사유")
    classification_reasoning: Optional[str] = Field(None, description="LLM의 분류 근거")
    suggested_alternatives: list[dict] = Field(
        default_factory=list,
        description="LLM이 제안하는 대안 (예: [{type: 'table', confidence: 0.6}])",
    )
    page_number: Optional[int] = None


class ProcessingReport(BaseModel):
    """문서 파이프라인 전체 처리 보고서.

    각 스테이지별 처리 결과, 블럭별 신뢰도, 리뷰 필요 항목을 포함한다.
    프론트엔드는 이 보고서를 기반으로 리뷰 UI를 렌더링한다.
    """

    document_id: UUID
    document_title: str = ""
    source_format: str = ""
    total_pages: int = 0

    # 각 스테이지별 보고서
    stages: list[ProcessingStageReport] = Field(default_factory=list)
    total_duration_ms: int = 0

    # 블럭 요약
    total_blocks: int = 0
    block_type_distribution: dict = Field(
        default_factory=dict,
        description="블럭 타입별 수 (예: {paragraph: 10, table: 2, heading_1: 3})",
    )
    nature_distribution: dict = Field(
        default_factory=dict,
        description="nature별 수 (예: {fact: 5, reference: 8, opinion: 2})",
    )

    # 신뢰도 분포
    confidence_distribution: dict = Field(
        default_factory=dict,
        description="신뢰도 등급별 수 (예: {solid: 5, good: 8, caution: 3, low: 1})",
    )
    avg_confidence: float = 0.0

    # 리뷰 필요 항목
    review_required: bool = False
    review_items: list[BlockReviewItem] = Field(default_factory=list)
    auto_approved_count: int = 0

    # 메타
    pipeline_version: str = "3-stage-v1"
    processed_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentIndexedEvent(BaseModel):
    """인덱싱 완료 이벤트 -- Core Service가 소비하여 상태 갱신."""

    event_id: UUID
    document_id: UUID
    tenant_id: UUID
    repository_id: UUID
    indexed_count: int
    collection_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ====================================================================
# 대용량 문서 분할 이벤트
# ====================================================================


class DocumentSplitEvent(BaseModel):
    """대용량 문서 분할 요청 이벤트 — split_worker가 소비.

    parse_worker가 >20 페이지 PDF를 감지하면 발행한다.
    """

    event_id: UUID
    document_id: UUID
    tenant_id: UUID
    repository_id: UUID
    total_pages: int
    total_parts: int
    page_ranges: list[list[int]] = Field(description="[[1,20],[21,40],...]")
    source_path: str
    minio_source_key: str = ""
    difficulty: ProcessingDifficulty = ProcessingDifficulty.LOW
    document_type: Optional[str] = None
    document_structure: Optional[dict] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DocumentPartReadyEvent(BaseModel):
    """분할된 파트 처리 준비 이벤트 — block_worker가 소비.

    split_worker가 각 sub-PDF를 MinIO에 업로드 후 발행한다.
    """

    event_id: UUID
    document_id: UUID
    part_id: UUID
    tenant_id: UUID
    repository_id: UUID
    part_index: int
    total_parts: int
    page_start: int  # 1-based inclusive
    page_end: int    # 1-based inclusive
    minio_part_key: str
    difficulty: ProcessingDifficulty = ProcessingDifficulty.LOW
    document_type: Optional[str] = None
    document_structure: Optional[dict] = None
    source_path: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DocumentPartBlockedEvent(BaseModel):
    """파트별 블럭 세그멘테이션 완료 이벤트 — merge_worker가 소비.

    block_worker가 하나의 sub-PDF 처리 완료 후 발행한다.
    """

    event_id: UUID
    document_id: UUID
    part_id: UUID
    tenant_id: UUID
    repository_id: UUID
    part_index: int
    total_parts: int
    block_count: int
    block_types: dict = Field(default_factory=dict)
    minio_blocks_key: str
    page_start: int
    page_end: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
