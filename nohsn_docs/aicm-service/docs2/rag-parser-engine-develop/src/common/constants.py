"""AICM 공통 상수."""

# Kafka 토픽
TOPIC_DOCUMENT_UPLOADED = "aicm.document.uploaded"
# D48 §1 — 큐 분리: 작은/큰 문서를 다른 토픽으로 라우팅. 기존 TOPIC_DOCUMENT_UPLOADED 는
# legacy 호환 (rollback path) 으로 유지 — small 워커가 흡수 + early divert 로 large 재발행.
TOPIC_DOCUMENT_UPLOADED_SMALL = "aicm.document.uploaded.small"
TOPIC_DOCUMENT_UPLOADED_LARGE = "aicm.document.uploaded.large"
TOPIC_DOCUMENT_PARSED = "aicm.document.parsed"
TOPIC_DOCUMENT_CHUNKED = "aicm.document.chunked"
TOPIC_DOCUMENT_INDEXED = "aicm.document.indexed"
TOPIC_DOCUMENT_BLOCKED = "aicm.document.blocked"
TOPIC_DOCUMENT_FAILED = "aicm.document.failed"
TOPIC_DOCUMENT_DLQ = "aicm.document.dlq"
TOPIC_DOCUMENT_REVIEW_REQUIRED = "aicm.document.review_required"
TOPIC_DOCUMENT_REVIEW_APPROVED = "aicm.document.review_approved"
TOPIC_DOCUMENT_SPLIT = "aicm.document.split"
TOPIC_DOCUMENT_PART_READY = "aicm.document.part_ready"
TOPIC_DOCUMENT_PART_BLOCKED = "aicm.document.part_blocked"
TOPIC_DOCUMENT_ALERT = "aicm.document.alert"
TOPIC_SEARCH_QUERY = "aicm.search.query"
TOPIC_INTEGRATION_EVENT = "aicm.integration.event"

# 문서 상태
DOC_STATUS_DRAFT = "draft"
DOC_STATUS_PROCESSING = "processing"
DOC_STATUS_PENDING_REVIEW = "pending_review"
DOC_STATUS_ACTIVE = "active"
DOC_STATUS_ARCHIVED = "archived"
DOC_STATUS_FAILED = "failed"

# 파이프라인 스테이지
STAGE_UPLOADED = "uploaded"
STAGE_PARSING = "parsing"
STAGE_CHUNKING = "chunking"
STAGE_REVIEW = "review"
STAGE_EMBEDDING = "embedding"
STAGE_INDEXING = "indexing"
STAGE_COMPLETED = "completed"
STAGE_SPLITTING = "splitting"
STAGE_MERGING = "merging"
STAGE_FAILED = "failed"

# 리뷰 신뢰도 임계값
REVIEW_CONFIDENCE_THRESHOLD = 0.75  # 이 값 미만의 블럭은 사람 리뷰 필요

# Qdrant 컬렉션 네이밍 규칙
QDRANT_COLLECTION_PREFIX = "aicm"

# 기본 검색 가중치
DEFAULT_DENSE_WEIGHT = 0.25
DEFAULT_SPARSE_WEIGHT = 0.25
DEFAULT_KEYWORD_WEIGHT = 0.50
DEFAULT_RRF_K = 60

# API 인증
API_KEY_PREFIX = "aicm_"
API_KEY_HEADER = "X-API-Key"

# ── 라이선스 티어 정의 ──
# -1 = 무제한
LICENSE_TIERS: dict[str, dict[str, int]] = {
    "personal": {"documents": 500, "repositories": 5, "users": 1},
    "personal_pro": {"documents": 5000, "repositories": -1, "users": 1},
    "team": {"documents": 10000, "repositories": -1, "users": 10},
    "business": {"documents": 100000, "repositories": -1, "users": 100},
    "enterprise": {"documents": -1, "repositories": -1, "users": -1},
}

# 티어별 기능 접근 제어 — 기업 전용 기능은 team 이상에서만 사용 가능
# personal/personal_pro: 개인 기능만
# team/business/enterprise: 개인 + 기업 기능 전체
CORPORATE_FEATURES: set[str] = {
    "team_briefing", "handover_query", "series_team",
    "cdc_corporate", "transition_event",
}
CORPORATE_MIN_TIER: str = "team"  # 이 티어 이상만 기업 기능 사용 가능
_TIER_RANK: dict[str, int] = {
    "personal": 0, "personal_pro": 1, "team": 2, "business": 3, "enterprise": 4,
}


def is_corporate_feature_allowed(tier: str) -> bool:
    """해당 티어에서 기업 기능 사용이 가능한지 확인한다."""
    return _TIER_RANK.get(tier, 0) >= _TIER_RANK.get(CORPORATE_MIN_TIER, 2)


# 사용량 경고 임계값 (80%)
LICENSE_WARNING_THRESHOLD = 0.8

# Redis 키 접두사 — 라이선스 사용량 추적
REDIS_USAGE_PREFIX = "aicm:usage"
