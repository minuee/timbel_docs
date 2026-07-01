"""파이프라인 핵심 Pydantic 모델 — DEV_SPEC.md 2.2 기준."""

from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentFormat(str, Enum):
    """지원 문서 포맷."""

    PDF = "pdf"
    DOCX = "docx"
    HWP = "hwp"
    XLSX = "xlsx"
    HTML = "html"
    IMAGE = "image"
    TXT = "txt"
    PPTX = "pptx"
    MARKDOWN = "markdown"


class ProcessingDifficulty(str, Enum):
    """문서 처리 난이도."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChunkStrategy(str, Enum):
    """청킹 전략."""

    SEMANTIC = "semantic"
    HIERARCHICAL = "hierarchical"
    TABLE = "table"
    FIXED = "fixed"


class SourceLocation(BaseModel):
    """청크의 원본 문서 내 위치 정보 -- 검색 결과에서 원본 추적에 사용."""

    file_path: Optional[str] = None
    file_url: Optional[str] = None  # 영속 스토리지 URL (MinIO presigned / KMS deep link)
    page_number: Optional[int] = None
    page_range: Optional[list[int]] = None
    start_char_offset: Optional[int] = None
    end_char_offset: Optional[int] = None
    bbox: Optional[list[float]] = None
    heading_path: list[str] = Field(default_factory=list)
    sheet_name: Optional[str] = None
    table_index: Optional[int] = None
    paragraph_index: Optional[int] = None


class ChunkObject(BaseModel):
    """개별 청크 객체."""

    id: UUID
    document_id: UUID
    section_id: Optional[UUID] = None
    content: str
    chunk_index: int
    chunk_hash: str  # SHA-256
    token_count: int
    strategy: ChunkStrategy

    # 원본 위치
    source_location: SourceLocation

    # 벡터화 결과
    dense_vector: Optional[list[float]] = None  # 1024d
    sparse_vector: Optional[dict[int, float]] = None  # {token_id: weight}

    # 메타데이터
    metadata: dict = Field(default_factory=dict)
    parent_chunk_id: Optional[UUID] = None

    # Phase 2: Contextual Retrieval 프리픽스 (검색 품질 향상용)
    contextual_prefix: Optional[str] = None

    # Phase 2: 자동 추출 메타데이터
    extracted_metadata: Optional[dict] = None


class TableChunkConfig(BaseModel):
    """표 3중 청킹 설정 (ProcessingConfig에 포함)."""

    row_nl_enabled: bool = True
    row_nl_group_size: int = 1  # 1=행별, 5=5행 묶음
    markdown_rows_per_chunk: int = 10
    summary_enabled: bool = True
    max_rows_for_row_nl: int = 100  # 초과 시 group_size=5로 자동 전환


class ProcessingConfig(BaseModel):
    """파이프라인 설정 (테넌트/저장소별 오버라이드 가능)."""

    # 청킹
    chunk_size: int = Field(default=400, ge=100, le=2000)
    chunk_overlap: int = Field(default=50, ge=0, le=200)
    min_chunk_size: int = Field(default=50)

    # 임베딩
    embedding_model: str = "BAAI/bge-m3"
    embedding_batch_size: int = 32

    # OCR
    ocr_enabled: bool = True
    ocr_language: str = "kor+eng"
    ocr_llm_fallback: bool = True

    # 표 처리
    table_extraction_enabled: bool = True
    table_to_markdown: bool = True
    table_chunk: TableChunkConfig = Field(default_factory=TableChunkConfig)

    # LLM 보강
    contextual_retrieval: bool = False
    auto_metadata: bool = True
    enable_search_summary: bool = True
    enable_query_keywords: bool = True

    # 블럭 파이프라인 (specs/06)
    use_block_pipeline: bool = False
    block_boundary_model: str = ""  # 비어있으면 settings에서 결정
    block_max_tokens: int = Field(default=800, ge=200, le=4000)

    # LLM 자가 검증 (비판적 검토자 2차 리뷰)
    enable_self_verification: bool = False  # 기본 꺼짐 (블럭당 LLM 호출 추가 비용)

    # 난이도 자동 판정 임계값
    difficulty_thresholds: dict = Field(
        default_factory=lambda: {"low": 0.3, "medium": 0.6, "high": 0.8}
    )


class DocumentObject(BaseModel):
    """파이프라인 전체에서 사용하는 문서 객체."""

    id: UUID
    tenant_id: UUID
    repository_id: UUID
    title: str
    source_format: DocumentFormat
    source_path: str
    category_ids: list[UUID] = Field(default_factory=list)
    document_type_id: Optional[UUID] = None

    # 파서 결과
    raw_text: Optional[str] = None
    pages: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)

    # 난이도 평가
    difficulty: Optional[ProcessingDifficulty] = None
    difficulty_score: Optional[float] = None
    difficulty_factors: dict = Field(default_factory=dict)

    # 청킹 결과 (레거시)
    chunks: list[ChunkObject] = Field(default_factory=list)

    # 블럭 결과 (신규 파이프라인)
    blocks: list = Field(default_factory=list)  # list[BlockObject] — 순환참조 방지

    # 처리 설정
    config: ProcessingConfig = Field(default_factory=ProcessingConfig)
