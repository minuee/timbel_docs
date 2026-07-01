"""블럭 관련 Pydantic 스키마 — specs/06 5A."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.api.schemas.document import SourceLocationSchema


class BlockResponse(BaseModel):
    """블럭 응답."""

    id: UUID
    document_id: UUID
    repository_id: UUID
    block_type: str
    content: str
    block_index: int
    block_hash: str
    token_count: Optional[int] = None
    source_location: SourceLocationSchema = Field(default_factory=SourceLocationSchema)
    metadata: dict = Field(default_factory=dict)
    is_indexed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # 표 전용
    table_headers: Optional[list[str]] = None
    table_markdown: Optional[str] = None

    # 이미지 전용
    image_description: Optional[str] = None
    ocr_text: Optional[str] = None

    # Noise flag
    is_noise: bool = Field(False, description="노이즈 블럭 여부 (true면 검색 인덱스에서 제외)")

    # Provenance — confidence badge (Phase C-2)
    confidence_grade: Optional[dict] = Field(
        None, description="확신도 등급 (grade, icon, label, expanded, show_edit)"
    )

    model_config = {"from_attributes": True}


class BlockDetailResponse(BlockResponse):
    """블럭 상세 응답 (벡터 프리뷰 포함)."""

    vector_preview: Optional[list[float]] = None
    vector_id: Optional[str] = None
    contextual_prefix: Optional[str] = None
    extracted_metadata: Optional[dict] = None


class BlockUpdateRequest(BaseModel):
    """블럭 수정 요청. content 수정 시 자동 재벡터화."""

    content: Optional[str] = Field(None, min_length=1)
    block_type: Optional[str] = Field(None, description="블럭 타입 변경 (paragraph, heading_1, ...)")
    metadata: Optional[dict] = None
