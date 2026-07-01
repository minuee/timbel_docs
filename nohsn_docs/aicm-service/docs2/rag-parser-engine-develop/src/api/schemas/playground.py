"""Playground 관련 Pydantic 스키마."""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.api.schemas.search import SearchResult, WeightsOverride


class SearchTraceRequest(BaseModel):
    """검색 트레이스 요청 — Search Playground에서 사용."""

    query: str = Field(..., min_length=1, max_length=1000)
    repository_id: UUID
    category_ids: Optional[list[UUID]] = None
    document_type_ids: Optional[list[UUID]] = None
    top_k: int = Field(default=10, ge=1, le=100)
    weights: Optional[WeightsOverride] = None
    enable_rerank: bool = True
    mode: str = Field(
        default="hybrid",
        pattern=r"^(hybrid|dense|sparse|keyword)$",
    )
    rag_mode: Optional[str] = Field(
        None,
        pattern=r"^(off|direct|generation)$",
        description="RAG 모드 (off/direct/generation)",
    )
    llm_model: Optional[str] = Field(None, description="LLM 모델 지정")


class TraceStepResult(BaseModel):
    """트레이스 개별 단계 결과 항목."""

    chunk_id: Optional[str] = None
    doc_title: Optional[str] = None
    score: Optional[float] = None
    content_preview: Optional[str] = None
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None
    rrf_score: Optional[float] = None
    pre_score: Optional[float] = None
    rerank_score: Optional[float] = None
    rank_change: Optional[int] = None


class TraceStep(BaseModel):
    """검색 트레이스 개별 단계."""

    name: str
    latency_ms: int
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    results: list[TraceStepResult] = Field(default_factory=list)
    prompt_preview: Optional[str] = None
    response: Optional[str] = None


class SearchTrace(BaseModel):
    """검색 전체 트레이스."""

    total_latency_ms: int
    steps: list[TraceStep]


class SearchTraceResponse(BaseModel):
    """검색 트레이스 응답."""

    final_results: list[SearchResult]
    trace: SearchTrace


class PipelineStageTrace(BaseModel):
    """파이프라인 개별 스테이지 트레이스."""

    name: str
    duration_ms: int
    output: dict = Field(default_factory=dict)


class PipelineTraceDocument(BaseModel):
    """파이프라인 트레이스 문서 요약."""

    id: str
    title: str
    format: Optional[str] = None


class PipelineTraceData(BaseModel):
    """파이프라인 전체 트레이스."""

    total_duration_ms: int
    stages: list[PipelineStageTrace]


class ChunkTraceItem(BaseModel):
    """청크 트레이스 항목 (Playground용)."""

    id: str
    chunk_index: int
    content: str
    token_count: Optional[int] = None
    strategy: Optional[str] = None
    source_location: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    vector_preview: Optional[list[float]] = None


class PipelineTraceResponse(BaseModel):
    """파이프라인 트레이스 응답."""

    document: PipelineTraceDocument
    trace: PipelineTraceData
    chunks: list[ChunkTraceItem] = Field(default_factory=list)


class SearchLatencyBreakdown(BaseModel):
    """검색 레이턴시 분해."""

    dense_avg_ms: float = 0
    sparse_avg_ms: float = 0
    fusion_avg_ms: float = 0
    rerank_avg_ms: float = 0
    rag_avg_ms: float = 0


class SearchPerformance(BaseModel):
    """검색 성능 메트릭."""

    total_queries: int = 0
    latency_p50_ms: float = 0
    latency_p95_ms: float = 0
    latency_breakdown: SearchLatencyBreakdown = Field(default_factory=SearchLatencyBreakdown)
    hourly_trend: list[dict] = Field(default_factory=list)


class PipelinePerformance(BaseModel):
    """파이프라인 성능 메트릭."""

    processed_today: int = 0
    processing_now: int = 0
    failure_rate: float = 0
    avg_duration_ms: float = 0
    by_format: dict[str, int] = Field(default_factory=dict)


class LLMModelPerformance(BaseModel):
    """개별 LLM 모델 성능."""

    requests: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0
    estimated_cost_usd: float = 0
    error_rate: float = 0


class LLMPerformance(BaseModel):
    """LLM 전체 성능 메트릭."""

    claude: LLMModelPerformance = Field(default_factory=LLMModelPerformance)
    qwen: LLMModelPerformance = Field(default_factory=LLMModelPerformance)
    fallback_count: int = 0


class PerformanceMetricsResponse(BaseModel):
    """성능 메트릭 응답."""

    search: SearchPerformance = Field(default_factory=SearchPerformance)
    pipeline: PipelinePerformance = Field(default_factory=PipelinePerformance)
    llm: LLMPerformance = Field(default_factory=LLMPerformance)
