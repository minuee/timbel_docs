"""문서 분석 관련 Pydantic 스키마."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class StructureAnalysisResponse(BaseModel):
    """구조 분석 응답."""

    has_toc: bool = False
    heading_count: int = 0
    max_depth: int = 0
    section_count: int = 0


class TableAnalysisResponse(BaseModel):
    """표 분석 응답."""

    table_count: int = 0
    total_rows: int = 0
    tables_with_headers: int = 0
    header_quality: str = "unknown"


class OCRAnalysisResponse(BaseModel):
    """OCR 분석 응답."""

    total_pages: int = 0
    low_confidence_pages: list[int] = Field(default_factory=list)
    suspected_garbled_pages: list[int] = Field(default_factory=list)
    average_confidence: float = 0.0


class DuplicateCheckResponse(BaseModel):
    """중복 검사 응답."""

    has_potential_duplicate: bool = False
    similar_documents: list[dict] = Field(default_factory=list)
    max_similarity: float = 0.0


class SearchPredictionResponse(BaseModel):
    """검색 예측 응답."""

    keyword: str
    relevance_score: float = 0.0


class ImprovementSuggestionResponse(BaseModel):
    """개선 제안 응답."""

    category: str
    severity: str
    message: str


class AnalysisReportResponse(BaseModel):
    """문서 분석 리포트 응답."""

    quality_score: int = Field(0, ge=0, le=100)
    structure_analysis: StructureAnalysisResponse = Field(
        default_factory=StructureAnalysisResponse
    )
    table_analysis: TableAnalysisResponse = Field(default_factory=TableAnalysisResponse)
    ocr_analysis: OCRAnalysisResponse = Field(default_factory=OCRAnalysisResponse)
    duplicate_check: DuplicateCheckResponse = Field(default_factory=DuplicateCheckResponse)
    search_predictions: list[SearchPredictionResponse] = Field(default_factory=list)
    improvement_suggestions: list[ImprovementSuggestionResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ai_analysis: dict = Field(default_factory=dict)
    analyzed_at: str = ""
