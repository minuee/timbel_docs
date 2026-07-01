"""대용량 문서 처리 결과 모델."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.pipeline.models.block import BlockObject


class ProcessingResult(BaseModel):
    """문서 처리 코디네이터 결과.

    Attributes:
        document_id: 처리된 문서 ID
        blocks: 생성된 블럭 목록
        total_pages: 전체 페이지 수
        processing_mode: 'single' (소규모) 또는 'batch' (대규모)
        errors: 처리 중 발생한 비치명적 오류 목록
        elapsed_ms: 총 처리 소요 시간 (밀리초)
    """

    document_id: UUID
    blocks: list[BlockObject] = Field(default_factory=list)
    total_pages: int = 0
    processing_mode: Literal["single", "batch"] = "single"
    errors: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0
