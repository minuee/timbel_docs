"""검색 엔진 Pydantic 모델 정의."""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class SourceLocation(BaseModel):
    """원본 문서 내 위치 정보."""

    file_path: str | None = None
    file_url: str | None = None
    page_number: int | None = None
    page_range: list[int] | None = None
    start_char_offset: int | None = None
    end_char_offset: int | None = None
    bbox: list[float] | None = None
    heading_path: list[str] = Field(default_factory=list)
    sheet_name: str | None = None
    table_index: int | None = None
    paragraph_index: int | None = None


class SearchHit(BaseModel):
    """검색 결과 단일 항목."""

    chunk_id: UUID  # 레거시 호환 (블럭 파이프라인에서는 block_id 와 동일)
    document_id: UUID
    document_title: str
    section_title: str | None = None
    content: str
    document_type: str | None = None
    category_names: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    # 단계별 스코어 (트레이스용)
    dense_score: float | None = None
    sparse_score: float | None = None
    keyword_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    llm_rerank_score: float | None = None  # LLM 리랭킹 원본 스코어 (0.0~1.0)

    # 블럭 파이프라인 필드 (specs/06)
    block_id: UUID | None = None
    block_type: str | None = None
    block_index: int | None = None
    repository_id: UUID | None = None

    # 원본 문서 위치
    source_location: SourceLocation

    @property
    def score(self) -> float:
        """최종 스코어: rerank > fused > dense 순 우선."""
        return self.rerank_score or self.fused_score or self.dense_score or 0.0

    @model_validator(mode="after")
    def _fill_document_title_from_file(self) -> "SearchHit":
        """D85c-잔존 (2026-05-13) — document_title 빈 값 fallback.

        KMS ingest 시 parse_result.metadata.title 추출 실패 또는 업로드 시
        title 미지정으로 인해 ES/Qdrant payload 의 ``document_title`` 이 빈
        string 으로 저장된 chunk 가 존재. citation 빌드 단계에서 "(제목 없음)"
        로 표시되어 사용자 보고 "근거문서 제목 누락" 잔존.

        정도: source_location.file_path / file_url 의 stem (확장자 제외
        basename) 으로 fallback. KMS layer 내부 (변환 boundary) — 루카스
        재해석 X. 빈 chunk 만 영향, 정상 chunk 는 byte-equal 유지.

        GPT-5.5 D85c-잔존 P1 (2026-05-13) — path sanitization 강화:
        - URL 의 scheme/netloc 인식 (urlparse)
        - query string + fragment 둘 다 strip
        - Windows backslash 정규화
        - percent-encoded 한글/특수문자 unquote
        - try/except 로 corrupt data 도 안전 처리 (예외 -> 빈 stem)
        """
        if (self.document_title or "").strip():
            return self
        loc = self.source_location
        fp = (loc.file_path or "").strip() if loc else ""
        if not fp:
            fp = (loc.file_url or "").strip() if loc else ""
        if not fp:
            return self
        from pathlib import PurePosixPath
        from urllib.parse import unquote, urlparse

        stem = ""
        try:
            parsed = urlparse(fp)
            path = parsed.path if (parsed.scheme or parsed.netloc) else fp
            path = path.split("?", 1)[0].split("#", 1)[0]
            path = path.replace("\\", "/")
            base = PurePosixPath(path).name
            stem_raw = PurePosixPath(base).stem if base else ""
            stem = unquote(stem_raw or base or "")
        except Exception:  # noqa: BLE001
            stem = ""
        if stem:
            # Pydantic v2 — assign 가능 (non-frozen).
            self.document_title = stem
        return self


class ProcessedQuery(BaseModel):
    """전처리된 질의 객체."""

    original: str
    cleaned: str
    keywords: list[str] = Field(default_factory=list)
    for_dense: str
    for_sparse: str
    for_keyword: list[str] = Field(default_factory=list)


class SearchConfig(BaseModel):
    """검색 설정 (테넌트/저장소별 오버라이드 가능)."""

    # 검색 모드
    default_mode: str = "hybrid"

    # 검색 파라미터
    default_top_k: int = 5
    # candidate_pool_size: 각 백엔드(dense/sparse/keyword)가 반환할 후보 수. fusion 후 이 수까지
    # reranker 에 전달.
    # 이력:
    # - 30: 구어체 쿼리에서 정답이 rank 31 근처로 밀려 놓치는 케이스 있음 → 50 으로 상향.
    # - 50: reranker 호출당 50 pair scoring 으로 200~300ms 추가 비용.
    # - 20 (P0 latency, 2026-05-07): 5 role agent corpus 규모 (수십~수백 doc) 에서 20 으로도
    #   top-1 hit 동일 측정 통과. fusion top-20 (각 backend 도 20 씩 — top-50 은 BGE-M3
    #   recall 한계권 외) 이 reranker 핫스폿 외 영역의 cost 만 절감. 회귀 측정에서 5 봇 ×
    #   5 query top-1 hit 100% 동일이면 유지, 아니면 50 revert.
    candidate_pool_size: int = 20

    # RRF 가중치 — BGE-M3 dense/sparse 는 구어체 쿼리(e.g. "팔고 나면... 들어와?")를 엉뚱하게
    # 잡는 경향이 있어, 구체 키워드가 포함된 문서를 안정적으로 top 에 올리기 위해 keyword(BM25)
    # 비중을 0.5 로 상향. dense/sparse 각 0.25.
    dense_weight: float = 0.25
    sparse_weight: float = 0.25
    keyword_weight: float = 0.50
    rrf_k: int = 60

    # 리랭킹 (BGE-reranker-v2: GPU에서 ~100ms, CPU에서 ~20초)
    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # 임계값
    min_score_threshold: float = 0.15

    # RAG
    max_context_tokens: int = 2000
    organization_type: str = "고객서비스센터"


class SearchTraceStep(BaseModel):
    """검색 파이프라인 트레이스 단계."""

    step_name: str
    latency_ms: int
    candidate_count: int
    details: dict = Field(default_factory=dict)


class SearchTrace(BaseModel):
    """검색 파이프라인 전체 트레이스."""

    steps: list[SearchTraceStep] = Field(default_factory=list)
    total_latency_ms: int = 0


class SearchWeights(BaseModel):
    """API 요청에서 전달되는 가중치 오버라이드."""

    dense: float | None = None
    sparse: float | None = None
    keyword: float | None = None


class SearchRequest(BaseModel):
    """검색 API 요청."""

    query: str
    repository_ids: list[UUID] | None = None  # None = 전체 저장소 교차 검색
    tenant_id: UUID
    category_ids: list[UUID] | None = None
    document_type_ids: list[UUID] | None = None
    top_k: int = 5
    search_mode: str = "hybrid"
    rerank: bool = True
    include_content: bool = True
    highlight: bool = False
    weights: SearchWeights | None = None
    block_types: list[str] | None = None  # ["paragraph", "heading_1", "code"] — None=전체

    # HyDE (Hypothetical Document Embedding) 활성화
    use_hyde: bool = True

    # MMR (Maximum Marginal Relevance) 다양성 리랭킹
    use_mmr: bool = False
    mmr_lambda: float = 0.7  # 0=다양성 최대, 1=관련성 최대
    mmr_max_per_document: int = 3  # 같은 문서 최대 결과 수

    # 저장소별 Top-N 그룹핑
    group_by_repository: bool = False  # True면 저장소별 Top-N 반환
    results_per_repository: int = 3  # 저장소당 최대 결과 수

    # Intent-based filters (자동 설정 가능)
    time_filter: str = ""  # "recent", "last_month", "2024", etc.
    document_type_hint: str = ""  # "매뉴얼", "단가표", etc.
    auto_intent: bool = False  # 의도 분석 자동 적용 (block_types/repo/시간 자동 부여) — UI 토글로 노출

    # Ontology filters (Phase B)
    nature_filter: list[str] | None = None  # ["fact", "schedule"] — None=전체
    entity_filter: dict | None = None  # {"people": ["김팀장"], "orgs": ["KB금융"], "speakers": [...]}
    # validity_status 필드는 인덱싱 파이프라인이 채우기 전까지 모든 블럭에서 비어 있어
    # "active" 기본값을 두면 모든 결과가 필터링됨. 인덱싱이 필드를 채우기 시작하면 "active" 로 환원.
    validity_filter: str = "all"  # "active", "all", "historical"
    # 문서함 active/deactive 토글 필터 — "active" 만 검색 노출, "all" 이면 필터 없음
    document_status_filter: str = "active"

    # 최소 관련도 임계값 (이 값 미만 결과 제외, 프론트 슬라이더와 연동)
    min_score: float = 0.0  # 0이면 SearchConfig.min_score_threshold 사용

    # LLM 강화 (llm_query_rewriter, llm_reranker, sufficiency_evaluator)
    enable_llm_rewrite: bool = True  # 오타 교정 + 대화형 재구성
    enable_llm_rerank: bool = False  # BGE 이후 LLM 리랭킹 (GPU 필요, CPU에서 비활성)
    enable_sufficiency_check: bool = False  # 결과 충분성 평가 (비용 높음, 기본 비활성)
    conversation_history: list[dict] | None = None  # 대화형 재구성용 기록

    # 가중 컨텍스트 검색 (2026-06-16) — reformulate 대체.
    # 현재 발화 dense 벡터에 이전 맥락(conversation_history) 벡터를 저가중 융합.
    # sparse/ES/rerank 는 현재 발화만 사용. 설계: 2026-06-16-context-weighted-colbot-search-design.md
    context_weighted: bool = False
    w_c: float = 0.8  # 현재 발화 가중
    w_p: float = 0.2  # 이전 맥락 가중

    # Fallback strategy
    use_fallback: bool = True  # True면 4단계 폴백 전략 적용

    # 하위 호환: repository_id (단수) → repository_ids 변환
    repository_id: UUID | None = None

    # KMS-Plus 2026-05-07 — cross-industry isolation enforce.
    # True 면 fallback level 4 에서도 repository_ids 를 *제거하지 않음*. role agent
    # (knowledge_isolation='strict') 가 자기 산업 repo 외 chunk 를 절대 보지 않게
    # 보장하는 hard guard. 미설정(False) 시 기존 동작 — level 4 에서 모든 repo 로 확장.
    enforce_repository_ids: bool = False

    def model_post_init(self, __context: object) -> None:
        """repository_id → repository_ids 하위 호환 변환."""
        if self.repository_id is not None and self.repository_ids is None:
            self.repository_ids = [self.repository_id]


class SearchResultItem(BaseModel):
    """검색 응답 단일 항목."""

    chunk_id: UUID  # 레거시 호환
    document_id: UUID
    document_title: str
    section_title: str | None = None
    content: str | None = None
    highlighted_content: str | None = None
    score: float
    category_names: list[str] = Field(default_factory=list)
    document_type: str | None = None
    source_location: SourceLocation
    metadata: dict = Field(default_factory=dict)

    # 블럭 파이프라인 필드
    block_id: UUID | None = None
    block_type: str | None = None
    block_index: int | None = None
    repository_id: UUID | None = None


class QueryMetadata(BaseModel):
    """검색 응답 메타데이터."""

    latency_ms: int
    total_candidates: int
    strategy_used: str


class SearchResponse(BaseModel):
    """검색 API 응답."""

    results: list[SearchResultItem]
    query_metadata: QueryMetadata
    decomposed: dict | None = None
    keywords: list[str] = Field(default_factory=list)
    rewritten_query: str | None = None


class RAGContextRequest(BaseModel):
    """RAG 컨텍스트 API 요청."""

    query: str
    repository_ids: list[UUID] | None = None  # None = 전체 저장소 교차 검색
    tenant_id: UUID
    mode: str = "direct"  # direct | generation | auto
    top_k: int = 3
    max_context_tokens: int = 2000
    weights: SearchWeights | None = None
    organization_type: str | None = None

    # 하위 호환
    repository_id: UUID | None = None

    def model_post_init(self, __context: object) -> None:
        """repository_id → repository_ids 하위 호환 변환."""
        if self.repository_id is not None and self.repository_ids is None:
            self.repository_ids = [self.repository_id]


class RAGSource(BaseModel):
    """RAG 컨텍스트 출처 항목.

    ref_num은 프롬프트 내 인용 마커 [1], [2] 등에 대응한다.
    프론트엔드는 이 번호로 답변 내 인용과 근거 문서를 연결할 수 있다.
    """

    ref_num: int = 0
    doc_title: str
    section: str | None = None
    score: float
    source_location: SourceLocation
    page_info: str | None = None


class RAGContextResponse(BaseModel):
    """RAG 컨텍스트 API 응답."""

    context: str
    sources: list[RAGSource]
    prompt_template: str | None = None


class QueryAnalysis(TypedDict):
    """검색 파이프라인이 실제로 사용한 쿼리 해부 결과.

    _execute_pipeline 이 내부적으로 계산한 값을 외부(assist-stream 등)가
    재계산 없이 노출할 수 있도록 담는다.

    - rewritten_query: effective_query 최종값 (LLM rewrite/reformulate 적용 이후).
                       rewrite 가 꺼져 있거나 변화 없으면 원본 쿼리와 동일.
    - keywords: QueryPreprocessor 가 추출한 형태소 키워드 (Okt 없으면 정규식 fallback).
    """

    rewritten_query: str
    keywords: list[str]
