"""외부 RAG API 요청/응답 Pydantic 모델."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

class SourceInfo(BaseModel):
    """검색 결과 출처 정보."""

    document_id: UUID
    document_title: str
    section_title: str | None = None
    score: float
    source_location: dict = Field(default_factory=dict)


class QueryMetadata(BaseModel):
    """검색 쿼리 메타데이터."""

    latency_ms: int
    total_candidates: int
    strategy_used: str


class ConversationTurn(BaseModel):
    """대화 히스토리 턴."""

    role: str  # "user" | "assistant"
    content: str


# ---------------------------------------------------------------------------
# External Search API
# ---------------------------------------------------------------------------

class SearchWeights(BaseModel):
    """검색 가중치."""

    dense: float | None = None
    sparse: float | None = None
    keyword: float | None = None


class ExternalSearchRequest(BaseModel):
    """POST /api/v1/ext/search 요청."""

    query: str = Field(..., min_length=1, max_length=2000)
    repository_id: UUID
    category_ids: list[UUID] = Field(default_factory=list)
    document_type_ids: list[UUID] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=50)
    search_mode: str = Field(default="hybrid")  # hybrid | dense | sparse | keyword
    rerank: bool = True
    block_types: list[str] | None = None  # ["paragraph", "heading_1", "code"] — None=전체
    weights: SearchWeights | None = None


class SearchResultItem(BaseModel):
    """개별 검색 결과 아이템."""

    chunk_id: UUID
    document_id: UUID
    document_title: str
    section_title: str | None = None
    content: str
    score: float
    source_location: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class ExternalSearchResponse(BaseModel):
    """POST /api/v1/ext/search 응답."""

    results: list[SearchResultItem]
    query_metadata: QueryMetadata


# ---------------------------------------------------------------------------
# External Ask API
# ---------------------------------------------------------------------------

class ExternalAskRequest(BaseModel):
    """POST /api/v1/ext/ask 요청."""

    question: str = Field(..., min_length=1, max_length=2000)
    repository_id: UUID
    category_ids: list[UUID] = Field(default_factory=list)
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    response_mode: str = Field(default="answer")  # "answer" | "context"
    max_context_tokens: int = Field(default=2000, ge=500, le=8000)


class ExternalAskResponse(BaseModel):
    """POST /api/v1/ext/ask 응답."""

    answer: str | None = None  # response_mode=answer
    context: str | None = None  # response_mode=context
    sources: list[SourceInfo]
    confidence: float
    model_used: str | None = None
