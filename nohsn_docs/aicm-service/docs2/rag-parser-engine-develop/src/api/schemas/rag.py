"""RAG 전용 Pydantic 스키마 — Knowledge Search와 분리된 LLM용 RAG Retrieval/Answer."""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.api.schemas.search import IntentInfo, WeightsOverride


# ---------------------------------------------------------------------------
# Token Usage
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    """토큰 사용량 상세."""

    context_tokens: int = Field(0, description="RAG 컨텍스트에 사용된 토큰 수")
    prompt_tokens: int = Field(0, description="전체 프롬프트 토큰 수 (system + context + query)")
    completion_tokens: int = Field(0, description="LLM 생성 토큰 수")
    total_tokens: int = Field(0, description="총 토큰 수")


# ---------------------------------------------------------------------------
# Conversation Turn (RAG Answer에서 사용)
# ---------------------------------------------------------------------------


class ConversationTurn(BaseModel):
    """대화 히스토리 턴."""

    role: str = Field(..., pattern=r"^(user|assistant)$", description="역할 (user/assistant)")
    content: str = Field(..., min_length=1, description="대화 내용")


# ---------------------------------------------------------------------------
# Source (RAG 결과 출처)
# ---------------------------------------------------------------------------


class RAGSource(BaseModel):
    """RAG 컨텍스트에 포함된 청크의 출처 정보.

    ref_num은 답변 내 인라인 인용 마커 [1], [2] 등에 대응한다.
    프론트엔드는 이 번호로 답변 텍스트의 인용과 근거 문서를 연결한다.
    """

    ref_num: int = Field(0, description="인용 마커 번호 (답변 내 [1], [2] 등에 대응)")
    chunk_id: UUID
    document_id: UUID
    document_title: str
    section_title: Optional[str] = None
    content: Optional[str] = Field(None, description="원문 내용 미리보기 (최대 200자)")
    score: float
    token_count: int = Field(0, description="이 청크가 차지하는 토큰 수")
    compressed: bool = Field(False, description="압축 적용 여부")
    source_location: dict = Field(default_factory=dict)
    page_info: Optional[str] = Field(None, description="페이지/시트 위치 (예: p.3, 시트: Sheet1)")
    # 서버 내부 전용 — answer LLM 에 table raw 를 distill 우회로 전달하기 위함
    # ([[feedback_kms_lukas_separation]] 절칙: KMS retrieval 결과 재해석/후가공 금지).
    # exclude=True 로 SSE/JSON 직렬화에서 제외 — frontend 노출 금지.
    block_type: Optional[str] = Field(None, exclude=True)
    full_content: Optional[str] = Field(None, exclude=True)


# ---------------------------------------------------------------------------
# RAG Retrieve
# ---------------------------------------------------------------------------


class RAGRetrieveRequest(BaseModel):
    """POST /api/v1/rag/retrieve 요청.

    LLM 프롬프트에 주입하기 위한 토큰 예산 기반 컨텍스트 검색.
    Knowledge Search와 달리 결과 수가 적고 (3-5건), 토큰 예산을 엄격히 준수한다.
    """

    query: str = Field(..., min_length=1, max_length=2000, description="사용자 질의")
    repository_id: Optional[UUID] = Field(None, description="검색 대상 저장소 ID (미지정 시 테넌트 전체 검색)")
    category_ids: Optional[list[UUID]] = Field(None, description="카테고리 필터")
    document_type_ids: Optional[list[UUID]] = Field(None, description="문서타입 필터")
    top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="최대 반환 청크 수 (RAG는 3-5 권장, 최대 10)",
    )
    max_context_tokens: int = Field(
        default=2000,
        ge=200,
        le=8000,
        description="컨텍스트 토큰 예산 (기본 2000, 최대 8000)",
    )
    compress: bool = Field(
        default=False,
        description="500 토큰 초과 청크를 LLM으로 요약 압축할지 여부",
    )
    weights: Optional[WeightsOverride] = Field(None, description="검색 가중치 오버라이드")
    enable_rerank: bool = Field(default=True, description="Cross-encoder 리랭킹 활성화")
    include_linked_tenants: bool = Field(
        default=False,
        description="TenantLink 기반 교차 테넌트 검색 포함 여부",
    )
    enable_intent_gate: bool = Field(
        default=True,
        description="LLM 기반 사전 검색 필요성 분류 — 일상 대화는 검색 skip + 빈 결과 반환.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "연차 신청은 며칠 전까지?",
                    "top_k": 3,
                    "max_context_tokens": 2000,
                    "compress": False,
                    "enable_rerank": True,
                }
            ]
        }
    }


class RAGRetrieveResponse(BaseModel):
    """POST /api/v1/rag/retrieve 응답.

    토큰 예산 내에서 조립된 RAG 컨텍스트.
    pagination 없음 — 항상 예산 내 결과만 반환.
    """

    context: str = Field(..., description="LLM 프롬프트에 주입할 조립된 컨텍스트 문자열")
    sources: list[RAGSource] = Field(default_factory=list, description="컨텍스트에 포함된 출처 목록")
    token_count: int = Field(0, description="실제 사용된 컨텍스트 토큰 수")
    max_context_tokens: int = Field(0, description="요청된 토큰 예산")
    prompt_template: Optional[str] = Field(
        None,
        description="완성된 프롬프트 템플릿 (system prompt + context + query 포함)",
    )
    latency_ms: int = Field(0, description="처리 소요 시간 (ms)")
    intent: Optional[IntentInfo] = Field(
        None,
        description="Intent gate 결과. skipped=True 면 일상 대화로 판정되어 검색 skip.",
    )


# ---------------------------------------------------------------------------
# RAG Answer
# ---------------------------------------------------------------------------


class RAGAnswerRequest(BaseModel):
    """POST /api/v1/rag/answer 요청.

    RAG Retrieve + LLM 답변 생성을 한 번에 수행.
    """

    query: str = Field(..., min_length=1, max_length=2000, description="사용자 질의")
    repository_id: Optional[UUID] = Field(None, description="검색 대상 저장소 ID (미지정 시 테넌트 전체 검색)")
    category_ids: Optional[list[UUID]] = Field(None, description="카테고리 필터")
    document_type_ids: Optional[list[UUID]] = Field(None, description="문서타입 필터")
    top_k: int = Field(default=3, ge=1, le=10, description="최대 반환 청크 수")
    max_context_tokens: int = Field(
        default=2000,
        ge=200,
        le=8000,
        description="컨텍스트 토큰 예산",
    )
    compress: bool = Field(default=False, description="청크 압축 여부")
    weights: Optional[WeightsOverride] = Field(None, description="검색 가중치 오버라이드")
    enable_rerank: bool = Field(default=True, description="Cross-encoder 리랭킹 활성화")
    include_linked_tenants: bool = Field(
        default=False,
        description="TenantLink 기반 교차 테넌트 검색 포함 여부",
    )
    conversation_history: list[ConversationTurn] = Field(
        default_factory=list,
        description="이전 대화 히스토리 (멀티턴 지원)",
    )
    llm_model: Optional[str] = Field(
        None,
        description="LLM 모델 지정 (auto/claude/qwen, 미지정 시 auto)",
    )
    temperature: float = Field(default=0.3, ge=0.0, le=1.0, description="LLM 생성 온도")
    max_answer_tokens: int = Field(default=500, ge=50, le=2000, description="답변 최대 토큰 수")
    verify_facts: bool = Field(
        default=False,
        description=(
            "LLM 기반 환각 감지 명시적 활성화 여부 (True 시 추가 LLM 호출 발생). "
            "명시 False 더라도 신뢰도 0.55 미만이면 서버가 자동으로 검증을 수행."
        ),
    )
    enable_llm_rewrite: bool = Field(default=False, description="LLM 쿼리 리라이팅")
    use_hyde: bool = Field(default=False, description="HyDE 가상문서 확장")
    auto_intent: bool = Field(default=False, description="쿼리 의도 자동 분석")
    distill: bool = Field(
        default=True,
        description="LLM 정제 단계 (후보들 중 답변 관련 청크 선택+요약). RAG API 핵심 산출물.",
    )
    distill_pool_size: int = Field(
        default=10,
        ge=3,
        le=30,
        description="정제 단계 입력 후보 수 (top_k 보다 큼, 더 많이 보고 선택)",
    )
    with_answer: bool = Field(
        default=True,
        description="최종 LLM 답변 생성 여부. False 면 정제 결과만 반환 (외부 LLM 사용 시 토큰 절약).",
    )
    enable_intent_gate: bool = Field(
        default=True,
        description="LLM 기반 사전 검색 필요성 분류 — 일상 대화는 검색/LLM 생성 skip + 빈 결과 반환.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "연차 신청은 며칠 전까지?",
                    "top_k": 3,
                    "max_context_tokens": 2000,
                    "temperature": 0.3,
                    "max_answer_tokens": 500,
                    "distill": True,
                    "with_answer": True,
                },
                {
                    "query": "이전 답변에서 말한 절차를 더 자세히 설명해줘",
                    "top_k": 5,
                    "conversation_history": [
                        {"role": "user", "content": "연차 신청 절차?"},
                        {
                            "role": "assistant",
                            "content": "1주일 전까지 인사팀 시스템 등록 ...",
                        },
                    ],
                    "verify_facts": True,
                },
            ]
        }
    }


class UnsupportedClaimResponse(BaseModel):
    """출처에서 뒷받침되지 않는 주장."""

    claim: str = Field(..., description="출처에 없는 주장")
    reason: str = Field(..., description="해당 주장이 추측인 이유")


class DistilledContext(BaseModel):
    """LLM 이 후보 청크들에서 선택+요약한 정제 결과 (RAG API 핵심 산출물)."""

    selected_refs: list[int] = Field(default_factory=list, description="선택된 sources 의 ref_num 목록")
    summary: str = Field("", description="질문 관점에서 정제·재구성된 핵심 컨텍스트 텍스트")
    rationale: str = Field("", description="왜 이 청크들을 골랐는지 한 줄 사유")


class RAGGenerateRequest(BaseModel):
    """POST /api/v1/rag/generate 요청. 정제된 컨텍스트로 답변만 생성 (점진 표시 2단계용)."""

    query: str = Field(..., min_length=1, max_length=2000)
    context: str = Field(..., description="LLM 에 그대로 전달할 컨텍스트 텍스트 (보통 distilled.summary)")
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    llm_model: Optional[str] = Field(None)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    max_answer_tokens: int = Field(default=500, ge=50, le=2000)


class RAGGenerateResponse(BaseModel):
    """POST /api/v1/rag/generate 응답. 답변 + 생성 latency 만 반환."""

    answer: str = Field(...)
    model_used: Optional[str] = Field(None)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    generation_latency_ms: int = Field(0)


class RAGAnswerResponse(BaseModel):
    """POST /api/v1/rag/answer 응답."""

    answer: str = Field(..., description="LLM이 생성한 최종 답변 (with_answer=True 일 때만 채워짐)")
    distilled: Optional[DistilledContext] = Field(
        None,
        description="LLM 정제 단계 산출물. distill=True 일 때 채워지며, 외부 시스템이 그대로 사용 가능한 컨텍스트.",
    )
    sources: list[RAGSource] = Field(default_factory=list, description="실제로 LLM 에 전달된 sources (정제 후)")
    sources_all: list[RAGSource] = Field(
        default_factory=list,
        description="정제 전 후보 전체 (distill_pool_size 개). UI/디버깅용.",
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="답변 신뢰도 (top 검색 스코어)")
    model_used: Optional[str] = Field(None, description="사용된 LLM 모델명")
    token_usage: TokenUsage = Field(default_factory=TokenUsage, description="토큰 사용량 상세")
    latency_ms: int = Field(0, description="총 처리 소요 시간 (ms)")
    retrieval_latency_ms: int = Field(0, description="컨텍스트 검색 소요 시간 (ms)")
    selection_latency_ms: int = Field(0, description="LLM 정제 단계 소요 시간 (ms)")
    generation_latency_ms: int = Field(0, description="LLM 최종 답변 생성 소요 시간 (ms)")
    fact_check_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="사실 검증 점수 (1.0 = 완전 뒷받침, verify_facts=True 시에만 반환)",
    )
    verdict: Optional[str] = Field(
        None,
        description="검증 판정: supported / partial / hallucinated (verify_facts=True 시에만 반환)",
    )
    unsupported_claims: Optional[list[UnsupportedClaimResponse]] = Field(
        None,
        description="출처에서 뒷받침되지 않는 주장 목록 (verdict != supported 일 때만 반환)",
    )
    intent: Optional[IntentInfo] = Field(
        None,
        description="Intent gate 결과. skipped=True 면 일상 대화로 판정되어 검색/LLM 생성 skip.",
    )


# ---------------------------------------------------------------------------
# Assist Stream (외부 앱 전용 SSE — 파라미터 잠금)
# ---------------------------------------------------------------------------


class AssistStreamRequest(BaseModel):
    """외부 웹프론트 상담 보조 SSE 요청.

    서버 내부에서 top_k=5, mode=hybrid, intent_gate=on, with_answer=on 등
    대부분 파라미터가 잠겨 있다. 성능 튜닝·테스트 용으로 `enable_distill` 하나만 노출.
    conversation_history 는 서버가 최근 2턴(4메시지)으로 강제 truncate 한다.
    """

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="현재 발화",
        examples=["연차 신청 절차 알려줘"],
    )
    conversation_history: list[ConversationTurn] = Field(
        default_factory=list,
        description="이전 대화. 서버가 최근 2턴(4메시지)으로 truncate 한다.",
    )
    repository_id: UUID = Field(
        ...,
        description="고객사 저장소 ID (필수)",
        examples=["00000000-0000-0000-0000-000000000001"],
    )
    category_ids: Optional[list[UUID]] = Field(
        None,
        description="조회 허용 분류 ID 목록(권한 스코프). 미지정 시 전체 분류 검색. AICM 이 사용자 viewable 분류로 전달.",
    )
    enable_distill: bool = Field(
        default=True,
        description=(
            "정제 단계(distill) 실행 여부. True(기본): candidate 를 LLM 으로 선별·요약해 "
            "답변 컨텍스트로 주입 (품질 우선). False: 정제 생략, 검색 결과를 그대로 답변 "
            "LLM 에 투입 (속도 우선, 통상 2~3초 단축). 인용 마커([1],[2])는 양쪽 모두 그대로 "
            "생성된다."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "연차 신청 절차 알려줘",
                    "repository_id": "00000000-0000-0000-0000-000000000001",
                    "enable_distill": True,
                    "conversation_history": [],
                }
            ]
        }
    }
