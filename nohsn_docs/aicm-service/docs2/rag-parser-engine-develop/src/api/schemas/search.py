"""검색 관련 Pydantic 스키마."""

from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.api.schemas.document import SourceLocationSchema
from src.common.constants import (
    DEFAULT_DENSE_WEIGHT,
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_SPARSE_WEIGHT,
)


class SearchScope(str, Enum):
    """Search scope selector (Lucas-KMS multi-repo extension).

    - SPECIFIED: caller supplies repository_id / repository_ids — only those.
    - TENANT_ALL: every active repository in the tenant (minus exclude_repository_ids).
    - GROUP: expand repository_group_id into its repository_ids.
    - DEFAULT: use the tenant default group if any, otherwise behave like TENANT_ALL.
    """

    SPECIFIED = "specified"
    TENANT_ALL = "tenant_all"
    GROUP = "group"
    DEFAULT = "default"


class WeightsOverride(BaseModel):
    """검색 가중치 오버라이드."""

    dense: float = Field(default=DEFAULT_DENSE_WEIGHT, ge=0.0, le=1.0)
    sparse: float = Field(default=DEFAULT_SPARSE_WEIGHT, ge=0.0, le=1.0)
    keyword: float = Field(default=DEFAULT_KEYWORD_WEIGHT, ge=0.0, le=1.0)


class SearchRequest(BaseModel):
    """검색 요청.

    하이브리드 검색 (Dense + Sparse + Keyword) + RRF 퓨전 + Cross-encoder 리랭킹.
    Intent gate (`enable_intent_gate=true`) 가 켜져 있으면 일상 대화는 자동 skip.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="검색 쿼리. 자연어 그대로 (오타·동의어 처리는 LLM rewrite 옵션).",
        examples=["연차 신청 절차"],
    )
    repository_id: Optional[UUID] = Field(
        None,
        description="검색 대상 저장소 ID (단수). repository_ids 와 함께 쓸 수 없음.",
        examples=["00000000-0000-0000-0000-000000000001"],
    )
    repository_ids: Optional[list[UUID]] = Field(
        None, description="검색 대상 저장소 ID 목록 (복수, 자동 범위 조정 시 사용)"
    )
    repository_group_id: Optional[UUID] = Field(
        None,
        description=(
            "Lucas-KMS — 저장소 그룹 ID. 지정 시 group 의 repository_ids 가 자동 전개. "
            "repository_id / repository_ids 와 함께 쓰지 말 것 (지정값이 우선)."
        ),
    )
    scope: SearchScope = Field(
        default=SearchScope.DEFAULT,
        description=(
            "검색 범위. specified=명시 ids 만, tenant_all=tenant 전체 active, "
            "group=group_id 전개, default=tenant 의 default group 있으면 그것, 없으면 tenant_all."
        ),
    )
    exclude_repository_ids: list[UUID] = Field(
        default_factory=list,
        description="scope=tenant_all 또는 default(fallback) 시 제외할 repo id.",
    )
    category_ids: Optional[list[UUID]] = Field(None, description="카테고리 필터")
    document_type_ids: Optional[list[UUID]] = Field(None, description="문서타입 필터")
    top_k: int = Field(default=10, ge=1, le=100, description="반환 결과 수")
    weights: Optional[WeightsOverride] = Field(None, description="검색 가중치 오버라이드")
    block_types: Optional[list[str]] = Field(
        None, description="블럭 타입 필터 (e.g. ['paragraph', 'heading_1', 'code'])"
    )
    enable_rerank: bool = Field(default=True, description="Cross-encoder 리랭킹 활성화")
    mode: str = Field(
        default="hybrid",
        pattern=r"^(hybrid|dense|sparse|keyword)$",
        description="검색 모드",
    )
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="최소 관련도 임계값")
    nature_filter: Optional[list[str]] = Field(None, description="성격 필터")
    validity_filter: str = Field(default="all", description="유효성 필터 (active/all/historical)")
    use_hyde: bool = Field(default=False, description="HyDE 쿼리 확장")
    use_fallback: bool = Field(default=True, description="폴백 전략 사용")
    auto_intent: bool = Field(default=False, description="쿼리 의도 자동 분석 (block_types/repo/시간 자동 부여)")

    # LLM 쿼리 리라이팅
    enable_llm_rewrite: bool = Field(default=False, description="LLM 쿼리 리라이팅 (오타교정 + 동의어 확장 + 대화 재구성)")
    conversation_history: Optional[list[dict]] = Field(
        None,
        description="대화 기록. 상담 대화 컨텍스트를 넣으면 대명사/생략을 복원하여 검색. "
                    "[{\"role\": \"user\", \"content\": \"...\"}, {\"role\": \"assistant\", \"content\": \"...\"}]",
    )
    enable_sufficiency_check: bool = Field(default=False, description="검색 결과 충분성 평가 활성화")
    enable_intent_gate: bool = Field(
        default=True,
        description="LLM 기반 사전 검색 필요성 분류 — 일상 대화는 검색 skip + 빈 결과 반환. 상담사 보조 시나리오에서 소음 제거 목적.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "연차 신청 절차",
                    "top_k": 5,
                    "mode": "hybrid",
                    "enable_rerank": True,
                    "enable_intent_gate": True,
                },
                {
                    "query": "사내 보안 정책 핵심 내용",
                    "repository_id": "00000000-0000-0000-0000-000000000001",
                    "top_k": 10,
                    "mode": "hybrid",
                    "enable_llm_rewrite": True,
                    "weights": {"dense": 0.5, "sparse": 0.3, "keyword": 0.2},
                },
            ]
        }
    }


class IntentInfo(BaseModel):
    """검색 필요성 분류 결과."""

    search: bool = Field(..., description="검색 실행 여부")
    reason: str = Field("", description="분류 사유")
    latency_ms: int = Field(0, description="분류 LLM 소요 시간")
    skipped: bool = Field(False, description="True 면 intent gate 가 검색을 건너뛴 상태")


class SearchResult(BaseModel):
    """개별 검색 결과."""

    chunk_id: UUID
    document_id: UUID
    document_title: str
    section_title: Optional[str] = None
    content: str
    score: float
    source_location: SourceLocationSchema = Field(default_factory=SourceLocationSchema)
    metadata: dict = Field(default_factory=dict)
    block_type: Optional[str] = None
    block_index: Optional[int] = None
    repository_id: Optional[UUID] = None
    validity: Optional[str] = None
    nature: Optional[str] = None
    classification_confidence: Optional[float] = None
    token_count: Optional[int] = None
    fallback_level: Optional[int] = None


class SearchResponse(BaseModel):
    """검색 응답."""

    query: str
    results: list[SearchResult]
    total_candidates: int = 0
    latency_ms: int = 0
    decomposed: Optional[dict] = None
    intent: Optional[IntentInfo] = Field(
        None,
        description="Intent gate 결과. search=False 면 results 는 비어있고 검색이 스킵됨.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="검색에 사용된 형태소 키워드 (Okt 기반). 파이프라인 내부 preprocessor 산출.",
    )
    rewritten_query: str | None = Field(
        None,
        description="LLM 리라이팅/대화이력 재구성 후 실제 검색에 투입된 쿼리. "
                    "없거나 원본과 동일하면 리라이팅이 비활성이거나 변화 없었음을 의미.",
    )


class RAGContextRequest(BaseModel):
    """RAG 컨텍스트 요청."""

    query: str = Field(..., min_length=1, max_length=1000, description="사용자 질의")
    repository_id: UUID = Field(..., description="대상 저장소 ID")
    category_ids: Optional[list[UUID]] = None
    document_type_ids: Optional[list[UUID]] = None
    top_k: int = Field(default=5, ge=1, le=20)
    mode: str = Field(
        default="direct",
        pattern=r"^(direct|generation)$",
        description="RAG 모드 (direct=컨텍스트만, generation=LLM 답변 포함)",
    )
    llm_model: Optional[str] = Field(None, description="LLM 모델 지정 (auto/claude/qwen)")
    weights: Optional[WeightsOverride] = None


class RAGContextResponse(BaseModel):
    """RAG 컨텍스트 응답."""

    query: str
    context_chunks: list[SearchResult]
    generated_answer: Optional[str] = None
    model_used: Optional[str] = None
    context_tokens: int = 0
    latency_ms: int = 0
