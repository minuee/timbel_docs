"""AICM 공통 환경 변수 설정."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """전체 서비스 공통 설정. .env 파일 또는 환경 변수로 오버라이드."""

    # === 공통 ===
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "change-this-to-random-secret-key-in-production"

    # === Lucas-KMS 무인증 모드 (2026-05-19 사용자 명시) ===
    # 키 없이 운영 가능 — JWT/X-API-Key/Swagger auth 모두 bypass.
    # *주의*: 운영 외부 노출 환경에서는 *반드시 False*. 내부 테스트 / 시연 / staging 용도.
    # True 시:
    #   - get_current_tenant_id → LUCAS_DEFAULT_TENANT_ID 자동 반환
    #   - get_current_user_id → LUCAS_DEFAULT_USER_ID (또는 None)
    #   - get_current_principal → role=admin (RBAC bypass)
    #   - Swagger auth 정책 비활성 (configure_swagger 의 SWAGGER_AUTH_MODE 무시)
    LUCAS_AUTH_DISABLED: bool = False
    LUCAS_DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"
    LUCAS_DEFAULT_USER_ID: str = "00000000-0000-0000-0000-000000000001"

    # === PostgreSQL ===
    DATABASE_URL: str = "postgresql+asyncpg://aicm:aicm_dev_password@localhost:5432/aicm"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_ECHO: bool = False

    # D32 §1 — KMS_DB_ROLE: app | migration | super
    # - app        : kms_app (NOBYPASSRLS NOSUPERUSER) — 운영 기본값.
    # - migration  : kms (BYPASSRLS) — alembic / break-glass 전용.
    # - super      : kms_superadmin (NOBYPASSRLS NOSUPERUSER, current_user 화이트리스트 매칭).
    # 부재 시 DATABASE_URL 그대로 사용 (legacy 호환).
    KMS_DB_ROLE: str = "migration"
    DATABASE_URL_APP: str = ""
    DATABASE_URL_MIGRATION: str = ""
    DATABASE_URL_SUPER: str = ""

    # D32 §1 — RLS rollback safety toggle. False 시 begin 훅 set_config 발행 X (RLS 정책 0 영향, BYPASSRLS role 운영 시).
    RLS_ENFORCE: bool = True

    # Phase 2 T2.4 (spec §8.1) — tenant_id 미설정 상태에서 명시 error.
    # default False — 회귀 0 (기존 silent 0-row 동작 유지).
    # True 일 때: begin 훅에서 tenant_val == '' AND scope != 'superadmin' → RuntimeError.
    # 운영 staging 에서 모든 path 의 set_rls_context 호출 확인 후 True 권장.
    RLS_STRICT_TENANT_REQUIRED: bool = False

    # === Qdrant ===
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_GRPC_PORT: int = 6334

    # === Elasticsearch ===
    ELASTICSEARCH_URL: str = "http://localhost:9200"

    # === Kafka ===
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9094"
    KAFKA_CONSUMER_GROUP: str = "aicm-pipeline"
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_CONSUMER_GROUP_MERGE_SUFFIX: str = "-merge"
    MERGE_CONSUMER_MAX_POLL_INTERVAL_MS: int = 600_000
    MERGE_CONSUMER_SESSION_TIMEOUT_MS: int = 30_000
    # main consumer: 단일 문서 처리(blocking+enriching+embedding)가 길어
    # 기본값(aiokafka 300_000=5분) 초과 시 rebalance → offset commit 실패 → 재처리 루프 발생.
    # 최장 처리시간보다 크게(대형 문서 ~50분+ 대비 1시간).
    MAIN_CONSUMER_MAX_POLL_INTERVAL_MS: int = 3_600_000
    MAIN_CONSUMER_SESSION_TIMEOUT_MS: int = 30_000
    PIPELINE_AUTO_RETRY_MAX: int = 1
    PIPELINE_MERGE_CONCURRENCY: int = 1
    PIPELINE_MERGE_READINESS_TIMEOUT_SEC: int = 30

    # === Redis ===
    REDIS_URL: str = "redis://localhost:6379/0"

    # === 임베딩 모델 ===
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cuda"
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_PROXY_URL: str = "http://localhost:3581"

    # === 리랭커 ===
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANKER_DEVICE: str = "cuda"

    # === LLM — 내부 vLLM 단일 경로 (로컬 5090 AWQ 또는 B200 FP16) ===
    LLM_ROUTING_MODE: str = "vllm"
    VLLM_URL: str = "http://vllm:8000/v1"
    VLLM_MODEL: str = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
    VLLM_API_KEY: str = ""
    SLLM_GEMMA_URL: str = "http://vllm:8000/v1"
    SLLM_GEMMA_MODEL: str = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"

    # === assist-stream 전용 B200 (GPU 부하 분리) ===
    ASSIST_VLLM_URL: str = ""
    ASSIST_VLLM_MODEL: str = ""
    ASSIST_RERANKER_URL: str = ""
    ASSIST_EMBEDDING_PROXY_URL: str = ""

    # Fallback vLLM endpoints (B200 장애 대비). 형식:
    # - "auto"  → 기본 GB10 3-tier (31b_dense → 26b_moe → e4b)
    # - ""      → 폴백 없음 (legacy)
    # - JSON 리스트: '[{"label":"...","url":"...","model":"..."}, ...]'
    VLLM_FALLBACKS: str = ""

    # === 파일 저장 ===
    UPLOAD_DIR: str = "/data/uploads"
    MAX_UPLOAD_SIZE_MB: int = 100

    # === 인증 ===
    AUTH_PROVIDER: str = "jwt"  # jwt / api_key
    JWT_SECRET: str = "change-this-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # === API 서버 ===
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 4

    # === Google OAuth (Calendar 연동) ===
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = ""  # 비어 있으면 자동 생성

    # === CORS ===
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://localhost:5173,"
        "http://localhost:5251,http://localhost:5101,http://localhost:5102"
    )

    # === Citation HMAC token (D41 — Telegram guest landing) ===
    # `/api/v1/citations/{block_id}` HTML preview 의 guest (JWT 미보유) 접근에
    # 사용. 32 byte 이상 권장 (startup hook 이 길이 검증, fail-fast).
    # 생성: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
    CITATION_HMAC_SECRET: str = ""
    # TTL 초 — default 43200 (12h). 가드: 300 (5m) ~ 2592000 (30d).
    # 운영자가 .env 로 override 가능 (하드코딩 회피, GPT-5 phase 0 권장).
    CITATION_HMAC_TTL_SECS: int = 43200

    # === External Agent — channel webhook base URL ===
    # admin 마법사 (POST /api/v1/agents/{id}/channels/connect) 의 default
    # webhook URL. 비어 있으면 admin 이 직접 입력해야 함.
    # 예: https://x-y-z.trycloudflare.com (cloudflared tunnel) 또는 운영 도메인.
    EXTERNAL_AGENT_WEBHOOK_BASE_URL: str = ""

    # === Assist Stream (외부 앱 전용 SSE) ===
    ASSIST_MAX_ANSWER_TOKENS: int = 1500
    ASSIST_INTENT_TIMEOUT_MS: int = 2000
    ASSIST_SEARCH_TIMEOUT_MS: int = 8000
    # D22 (2026-05-08) — 5000 → 8000. D20 측정: 큰 context 시 5s 빈번 timeout
    # (3건/15) → null 반환 → LLM raw context 재처리 +2-3s TTFS 손실. 8s 면
    # 성공률 +20% 추정. env override 가능 (.env 의 ASSIST_DISTILL_TIMEOUT_MS).
    # 후속 PR (P2): token-budget 가변화 + progressive 모드 (2초 초과 시 raw stream).
    ASSIST_DISTILL_TIMEOUT_MS: int = 8000
    ASSIST_GEN_FIRST_TOKEN_TIMEOUT_MS: int = 10000
    ASSIST_GEN_TOTAL_TIMEOUT_MS: int = 30000
    ASSIST_TOTAL_TIMEOUT_MS: int = 40000
    ASSIST_MAX_CONCURRENT_PER_TENANT: int = 8

    # === 업로드 파이프라인 최적화 (P11-19, 진단 결과 기반) ===
    # SKIP_KNOWLEDGE_COMPILER=true → entity_blocks (LLM-WIKI) skip.
    # medium.md 기준 181s → ~60s (3배). 대신 entity 검색 품질만 영향.
    SKIP_KNOWLEDGE_COMPILER: bool = False
    # BLOCK_COUNT_SOFT_CAP — segmentation 결과 N>cap 이면 인접 heading 머지.
    # markdown 의 작은 heading/list 마다 분할되어 50KB md 가 125블록 되던 회귀
    # 방지. 0 = 끔 (기존 동작).
    BLOCK_COUNT_SOFT_CAP: int = 0
    # EMBED_CACHE_ENABLED — 블록 텍스트 stable hash 로 임베딩 결과 재사용.
    # 동일 문서 재처리 시 28s → 1s. 미정합 시 옛 동작.
    EMBED_CACHE_ENABLED: bool = False

    # === 대화-컨텍스트 상품 앵커링 (resolve-then-scope, 2026-06-23) ===
    CONTEXT_ANCHOR_ENABLED: bool = True
    ANCHOR_ABS_MIN: float = 2.0        # ES title match 최소 스코어(timbel 캘리브레이션: 실상품언급 2.68~4.97, 타펀드노이즈 <=1.32, 펀드명없음 무매칭)
    ANCHOR_REL_RATIO: float = 0.8      # top1 대비 동률군 포함 비율
    ANCHOR_FALLBACK_MIN: int = 1       # 스코프 후 후보 < 이 값이면 unscoped 재시도

    # === Agent Delegation — T1 §3.2 ===
    # delegate_router 에서 LLM 선택 후보의 confidence threshold.
    # >= 0.6 → 위임 실행, < 0.6 → 위임 안 함 (거절).
    # env override 가능 (하드코딩 회피).
    DELEGATE_CONFIDENCE_THRESHOLD: float = 0.6

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def effective_database_url(self) -> str:
        """KMS_DB_ROLE 에 따라 DATABASE_URL_APP / _MIGRATION / _SUPER 분기.

        - 명시 값 부재 시 ``DATABASE_URL`` 그대로 fallback (legacy 호환). 단,
          KMS_DB_ROLE=app 또는 super 인데 대응 URL 이 비어 있으면 *경고 로그*
          후 fallback (GPT-5 §1 patch — silent BYPASSRLS 오용 방지).
        - app : kms_app (NOBYPASSRLS NOSUPERUSER) — 운영.
        - migration : kms (BYPASSRLS) — alembic / break-glass.
        - super : kms_superadmin — superadmin SELECT 정책 화이트리스트 매칭.
        """
        role = (self.KMS_DB_ROLE or "migration").strip().lower()
        if role not in ("app", "migration", "super"):
            # 허용 값 외 → migration 으로 강등 (안전 fallback) + warning.
            import warnings as _w
            _w.warn(
                f"KMS_DB_ROLE='{role}' 허용 외 값 — migration 으로 강등.",
                RuntimeWarning,
                stacklevel=2,
            )
            role = "migration"
        if role == "app":
            if not self.DATABASE_URL_APP:
                import warnings as _w
                _w.warn(
                    "KMS_DB_ROLE=app 인데 DATABASE_URL_APP 미설정 — DATABASE_URL "
                    "(BYPASSRLS) 폴백. RLS 강제 무력화 위험.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                return self.DATABASE_URL
            return self.DATABASE_URL_APP
        if role == "super":
            if not self.DATABASE_URL_SUPER:
                import warnings as _w
                _w.warn(
                    "KMS_DB_ROLE=super 인데 DATABASE_URL_SUPER 미설정 — DATABASE_URL "
                    "폴백.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                return self.DATABASE_URL
            return self.DATABASE_URL_SUPER
        # migration
        return self.DATABASE_URL_MIGRATION or self.DATABASE_URL


settings = Settings()
