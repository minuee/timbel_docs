"""KMS Pipeline FastAPI 애플리케이션.

문서 업로드 → 파싱 → 청킹 → 인덱싱 → 벡터 적재 → 검색/RAG 파이프라인 API.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from src.common.config import settings
from src.common.exceptions import AICMError
from src.common.logging import get_logger, setup_logging

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """애플리케이션 시작/종료."""
    setup_logging()
    logger.info("app_starting", env=settings.APP_ENV, port=settings.API_PORT)

    try:
        from src.core.database import init_db
        await init_db()
    except Exception as exc:
        logger.warning("db_init_skipped", error=str(exc))

    # D41 Phase 1 — citation HMAC secret fail-fast 검증 (GPT-5 phase 0 v3 P0).
    # CITATION_HMAC_SECRET 누락 또는 < 32 byte 면 startup 시점에서 즉시 RuntimeError —
    # 운영 실수 (Telegram guest landing 비활성화 채로 운영) 조기 탐지.
    # GPT-5 phase 1 pre P2 — APP_ENV 가 "development"/"test" *명시적으로* 일 때만
    # warning 으로 다운그레이드. production 또는 알 수 없는 값은 fail-fast.
    try:
        from src.common.security.citation_token import _ensure_secret
        _ensure_secret()
        logger.info("citation_hmac_secret_ok")
    except RuntimeError as _exc:
        _app_env = (settings.APP_ENV or "").strip().lower()
        if _app_env in ("development", "test"):
            logger.warning(
                "citation_hmac_secret_dev_warning",
                env=_app_env,
                hint=str(_exc),
            )
        else:
            logger.error(
                "citation_hmac_secret_FAIL",
                env=_app_env or "(unset)",
                hint=str(_exc),
            )
            raise

    # D33 §1 — RLS 운영 전환 self-check (사전 GPT-5 §1 보완 권고).
    # API 컨테이너가 `kms_app` (NOBYPASSRLS) 로 connect 됐는지 1 회 확인.
    # KMS_DB_ROLE=app + RLS_ENFORCE=true 인데 current_user 가 슈퍼유저 (BYPASSRLS)
    # 면 RLS 가 *런타임 무력화* — 기동 시 즉시 ERROR 로그.
    try:
        from sqlalchemy import text as _sql_text
        from src.core.database import engine as _db_engine_check

        async with _db_engine_check.connect() as _conn:
            _row = (
                await _conn.execute(
                    _sql_text(
                        "SELECT current_user, "
                        "       (SELECT rolbypassrls FROM pg_roles "
                        "        WHERE rolname = current_user) AS bypass_rls"
                    )
                )
            ).first()
        if _row is not None:
            _curr_user = _row[0]
            _bypass = bool(_row[1]) if _row[1] is not None else None
            _role_setting = (settings.KMS_DB_ROLE or "").strip().lower()
            _enforce = bool(settings.RLS_ENFORCE)
            # 이상 케이스 1: KMS_DB_ROLE=app + RLS_ENFORCE=true 인데 bypass_rls=True.
            if _role_setting == "app" and _enforce and _bypass:
                logger.error(
                    "rls_self_check_FAIL_bypass_rls_active",
                    current_user=_curr_user,
                    bypass_rls=_bypass,
                    role_setting=_role_setting,
                    rls_enforce=_enforce,
                    hint="DATABASE_URL_APP 가 kms_app 가 아닌 슈퍼유저로 connect — "
                    "RLS 정책 무력화. .env / docker-compose 확인 필요.",
                )
            else:
                logger.info(
                    "rls_self_check_ok",
                    current_user=_curr_user,
                    bypass_rls=_bypass,
                    role_setting=_role_setting,
                    rls_enforce=_enforce,
                )
    except Exception as _self_check_exc:  # noqa: BLE001
        # self-check 실패는 기동 막지 않음. health check 가 이후 처리.
        logger.warning("rls_self_check_skipped", error=str(_self_check_exc))

    # Okt 형태소 분석기 warmup — 최초 호출 시 JVM 로드로 ~250ms 지연 발생.
    # 기동 시점에 더미 텍스트 한 번 돌려 lazy init 유발. 실패해도 fallback 정규식
    # 이 있으므로 전체 기동 실패로 이어지지 않음.
    try:
        from src.search.hybrid.preprocessor import QueryPreprocessor, _HAS_OKT

        if _HAS_OKT:
            _warmup_pp = QueryPreprocessor()
            # 간단한 한글 쿼리 하나로 Okt JVM + 사전 로드 유발.
            await _warmup_pp.preprocess("검색 워밍업 더미")
            logger.info("okt_warmup_done")
        else:
            logger.info("okt_warmup_skipped_no_konlpy")
    except Exception as exc:
        logger.warning("okt_warmup_failed", error=str(exc))

    # Task 19: AgentEngine 의 CronRunner 스케줄러 기동.
    # 엔진 싱글턴 빌드는 첫 호출 시점이므로 여기서 의도적으로 깨워 cron 등록·start 를 수행.
    try:
        from src.agent_framework.api.dependencies import get_agent_engine

        _agent_engine = await get_agent_engine()
        _agent_engine.cron.start()
        logger.info("agent_scheduler_started")
    except Exception as exc:
        logger.warning("agent_scheduler_start_failed", error=str(exc))

    # 델타 #5 (KMS-Plus): framework-level cron — freshness cross-scan / cc-pair reprobe.
    # KMS_SCHEDULER_ENABLED=true 일 때만 자동 활성화 (안전 기본값 false).
    # Phase 8: placeholder no-op → 실 freshness/probe runner 연결.
    import os as _os
    if _os.environ.get("KMS_SCHEDULER_ENABLED") == "true":
        try:
            from src.agent_framework.scheduler.jobs import (
                _run_ccpair_reprobe,
                _run_freshness_all_tenants,
                register_default_jobs,
                start_scheduler,
            )

            register_default_jobs(
                freshness_runner=_run_freshness_all_tenants,
                probe_runner=_run_ccpair_reprobe,
            )
            start_scheduler()
            logger.info("kms_default_scheduler_started")
        except Exception as exc:
            logger.warning("kms_default_scheduler_start_failed", error=str(exc))

    # Task 31: LLM fallback digest 주기 로그 태스크 기동.
    try:
        from src.common.llm.metrics import start_digest_task

        start_digest_task()
    except Exception as exc:
        logger.warning("llm_fallback_digest_start_failed", error=str(exc))

    # PR-Z11A (KMS-Plus): 메일 미러링 worker — MAIL_CRED_KEY 있을 때만 실제 polling.
    # 키 없으면 worker 는 idle 모드 (graceful no-op) 로 살아있음.
    try:
        from src.integration.mail import credentials as _mail_creds
        from src.integration.mail.mirror_worker import MailMirrorWorker
        from src.core.database import engine as _db_engine

        # LLM 주입 — classifier 가 LLMRouter.route(task=..., request=...) 인터페이스 사용.
        _llm_for_classifier: Any | None = None
        try:
            from src.common.llm.router import llm_router as _llm_router
            _llm_for_classifier = _llm_router
        except Exception as _llm_exc:  # noqa: BLE001
            logger.warning("mail_mirror_llm_router_import_failed", error=str(_llm_exc))

        app.state.mail_mirror_worker = MailMirrorWorker(
            db_engine=_db_engine,
            llm=_llm_for_classifier,
        )
        await app.state.mail_mirror_worker.start()
        logger.info(
            "mail_mirror_worker_lifespan_started",
            creds_available=_mail_creds.is_available(),
        )
    except Exception as exc:
        logger.warning("mail_mirror_worker_start_failed", error=str(exc))

    yield

    # Task 19: 스케줄러 종료
    try:
        from src.agent_framework.api.dependencies import get_agent_engine

        _agent_engine = await get_agent_engine()
        _agent_engine.cron.shutdown()
        logger.info("agent_scheduler_shutdown")
    except Exception:
        pass

    # 델타 #5: KMS-Plus default scheduler 종료.
    try:
        from src.agent_framework.scheduler.jobs import stop_scheduler

        stop_scheduler()
    except Exception:
        pass

    # Task 31: digest 태스크 종료
    try:
        from src.common.llm.metrics import stop_digest_task

        stop_digest_task()
    except Exception:
        pass

    # PR-Z11A: 메일 미러링 worker 종료
    try:
        worker = getattr(app.state, "mail_mirror_worker", None)
        if worker is not None:
            await worker.stop()
    except Exception:
        pass

    try:
        from src.core.database import close_db
        await close_db()
    except Exception:
        pass

    try:
        from src.api.routers.search_proxy import close_proxy_client
        await close_proxy_client()
    except Exception:
        pass

    logger.info("app_shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

OPENAPI_TAGS = [
    {"name": "저장소", "description": "지식 저장소(Repository) 관리"},
    {"name": "카테고리", "description": "문서 분류 카테고리 관리"},
    {"name": "문서타입", "description": "문서 유형 정의"},
    {"name": "문서", "description": "문서 업로드, 조회, 파이프라인 상태"},
    {"name": "블럭", "description": "블럭 CRUD 및 분할/병합"},
    {"name": "노트", "description": "노션 스타일 직접 입력/편집 (파일 업로드 없이 지식 추가)"},
    {"name": "청크", "description": "청크 조회 및 검사"},
    {"name": "검색", "description": "하이브리드 검색 (Dense + Sparse + Keyword)"},
    {"name": "RAG", "description": "RAG Retrieval / Answer 생성"},
    {"name": "통계", "description": "파이프라인/검색 통계"},
    {"name": "검색 분석", "description": "검색 트렌드, 미응답 쿼리, 인기 검색어"},
    {"name": "피드백 통계", "description": "분류 수정 피드백 통계"},
    {"name": "지식 갭", "description": "미응답 클러스터, 카테고리 커버리지, 문서 사용률"},
    {"name": "분류 품질", "description": "Precision/Recall, 혼동 행렬, 신뢰도"},
    {"name": "Playground", "description": "검색/RAG 테스트"},
    {"name": "동의어", "description": "검색 동의어 관리"},
    {"name": "A/B 테스트", "description": "검색 파라미터 A/B 테스트"},
    {"name": "재처리", "description": "문서 재파싱/재청킹/재임베딩"},
    {"name": "파이프라인 관리", "description": "DLQ, 파이프라인 모니터링"},
    {"name": "기밀 등급", "description": "문서 기밀 등급 관리"},
    {"name": "PII", "description": "PII 탐지/해결"},
    {"name": "익명화", "description": "블럭 비식별화"},
    {"name": "Webhook", "description": "외부 문서 수신"},
    {"name": "Search Proxy", "description": "검색 프록시 패스스루"},
]

app = FastAPI(
    title="KMS Pipeline API",
    version="1.0.0",
    description="문서 업로드 → 파싱 → 청킹 → 인덱싱 → 벡터 적재 → 하이브리드 검색 + RAG",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------

from src.api.metrics import REGISTRY, PrometheusMiddleware  # noqa: E402

metrics_app = make_asgi_app(registry=REGISTRY)
app.mount("/metrics", metrics_app)

# D78 — src/common/metrics.py 의 kms_* counter 들은 default REGISTRY 사용.
# /metrics-kms endpoint 로 별도 expose (mixed REGISTRY 회피).
# prometheus.yml 의 별도 job 으로 scrape: /metrics-kms.
# 사전 GPT-5 GO_WITH_CHANGES 권고 반영 — counter 가시성 확보.
import src.common.metrics  # noqa: F401, E402  — eager-load 로 counter 등록.
_kms_metrics_app = make_asgi_app()  # default REGISTRY (kms_* counters)
app.mount("/metrics-kms", _kms_metrics_app)

app.add_middleware(PrometheusMiddleware)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Phase 13 — Security middleware (rate limit + security headers)
# ---------------------------------------------------------------------------

from src.api.middleware.maintenance_gate import MaintenanceGateMiddleware  # noqa: E402
from src.api.middleware.rate_limit import setup_rate_limit  # noqa: E402
from src.api.middleware.rls_context_middleware import RLSContextMiddleware  # noqa: E402
from src.api.middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402

setup_rate_limit(app)
app.add_middleware(SecurityHeadersMiddleware)
# D32 §2 — 모든 request 의 RLSContext 자동 등록 (ASGI middleware).
# add_middleware 는 LIFO — 가장 마지막 add 가 가장 먼저 실행됨. RLS 는 endpoint
# 직전 (DB 접근 시점) 에 set 되어야 하므로 마지막에 추가.
app.add_middleware(RLSContextMiddleware)
# D31d-E v2 §1 (#218) — 유지보수 게이트 (HTTP+WS 503/1013).
# LIFO 의 *가장 마지막* add → *가장 먼저* 실행됨 → 다른 middleware 부작용 발생 전
# 차단. env MAINTENANCE_MODE=on 일 때만 작동 (default off — pass-through).
app.add_middleware(MaintenanceGateMiddleware)


# ---------------------------------------------------------------------------
# Phase 4 T4.6 — Swagger 운영 보안 정책 (env-driven).
# ENABLE_SWAGGER=false / SWAGGER_AUTH_MODE / SWAGGER_IP_ALLOWLIST 적용.
# ---------------------------------------------------------------------------

from src.common.swagger_policy import configure_swagger  # noqa: E402

configure_swagger(app, product="full")


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@app.exception_handler(AICMError)
async def aicm_error_handler(request: Request, exc: AICMError) -> JSONResponse:
    status_map = {
        "NOT_FOUND": 404, "REPOSITORY_NOT_FOUND": 404, "DOCUMENT_NOT_FOUND": 404,
        "CATEGORY_NOT_FOUND": 404, "DOCUMENT_TYPE_NOT_FOUND": 404,
        "DUPLICATE_SLUG": 409, "DUPLICATE_NAME": 409,
        "UNSUPPORTED_FORMAT": 400, "FILE_TOO_LARGE": 413,
        "TENANT_ID_REQUIRED": 400, "INVALID_STATUS_TRANSITION": 400,
    }
    status_code = status_map.get(exc.code, 400)
    logger.warning("aicm_error", path=request.url.path, code=exc.code, message=exc.message)
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(Exception)
async def general_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"success": False, "data": None, "error": {"code": "INTERNAL_SERVER_ERROR", "message": "내부 서버 오류"}},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["시스템"])
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routers — Pipeline Core
# ---------------------------------------------------------------------------

from src.api.routers import (  # noqa: E402
    ab_tests_router,
    admin_reset_router,
    workers_admin_router,
    analytics_router,
    anonymization_router,
    blocks_router,
    categories_router,
    chunks_router,
    classification_quality_router,
    confidentiality_router,
    document_types_router,
    documents_router,
    feedback_stats_router,
    health_router,
    knowledge_gap_router,
    llm_metrics_router,
    notes_router,
    pii_router,
    pipeline_admin_router,
    playground_router,
    preview_router,
    rag_assist_router,
    rag_router,
    reprocess_router,
    repositories_router,
    search_proxy_router,
    search_router,
    stats_router,
    synonyms_router,
    webhook_inbound_router,
    mail_accounts_router,
    inbox_router,
)

# 헬스체크 (/health/live, /health/ready)
app.include_router(health_router)

# 저장소 & 카테고리 & 문서타입
app.include_router(repositories_router, prefix="/api/v1", tags=["저장소"])
app.include_router(categories_router, prefix="/api/v1", tags=["카테고리"])
app.include_router(document_types_router, prefix="/api/v1", tags=["문서타입"])

# 문서 & 블럭 & 청크 (파이프라인 코어)
app.include_router(documents_router, prefix="/api/v1", tags=["문서"])
app.include_router(blocks_router, prefix="/api/v1", tags=["블럭"])
app.include_router(notes_router, prefix="/api/v1", tags=["노트"])
app.include_router(chunks_router, prefix="/api/v1", tags=["청크"])
app.include_router(preview_router, prefix="/api/v1", tags=["문서"])

# 검색 & RAG
app.include_router(search_router, prefix="/api/v1/search", tags=["검색"])
app.include_router(rag_router, prefix="/api/v1/rag", tags=["RAG"])
app.include_router(rag_assist_router, prefix="/api/v1/rag", tags=["RAG Assist"])
app.include_router(search_proxy_router, prefix="/api/v1", tags=["Search Proxy"])

# 검색 튜닝
app.include_router(synonyms_router, prefix="/api/v1/synonyms", tags=["동의어"])
app.include_router(ab_tests_router, prefix="/api/v1/search/ab-tests", tags=["A/B 테스트"])

# 거버넌스 (파이프라인)
app.include_router(confidentiality_router, prefix="/api/v1", tags=["기밀 등급"])
app.include_router(pii_router, prefix="/api/v1", tags=["PII"])
app.include_router(anonymization_router, prefix="/api/v1/anonymization", tags=["익명화"])

# 통계 & 분석
app.include_router(stats_router, prefix="/api/v1/stats", tags=["통계"])
app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["검색 분석"])
app.include_router(feedback_stats_router, prefix="/api/v1/feedback-stats", tags=["피드백 통계"])
app.include_router(knowledge_gap_router, prefix="/api/v1/knowledge-gap", tags=["지식 갭"])
app.include_router(classification_quality_router, prefix="/api/v1/quality", tags=["분류 품질"])
app.include_router(llm_metrics_router, prefix="/api/v1/metrics", tags=["LLM 메트릭"])

# 운영 도구
app.include_router(playground_router, prefix="/api/v1/playground", tags=["Playground"])
app.include_router(reprocess_router, tags=["재처리"])
app.include_router(pipeline_admin_router, tags=["파이프라인 관리"])
app.include_router(admin_reset_router)
app.include_router(workers_admin_router)
app.include_router(webhook_inbound_router, prefix="/api/v1", tags=["Webhook"])
app.include_router(mail_accounts_router, prefix="/api/v1", tags=["Mail Accounts"])
app.include_router(inbox_router)

# 라이브러리 폴더 트리 (alembic 067) — repo 안 트리 분류 + 문서 이동
from src.api.routers.library_folders_v1 import router as library_folders_router  # noqa: E402
app.include_router(library_folders_router, prefix="/api/v1", tags=["Library Folders"])

# 2026-05-07 — admin feature flag runtime 토글 (alembic 073, tenants.feature_flags JSONB).
# Spec: docs/superpowers/specs/2026-05-07-feature-flags-runtime-toggle.md
from src.api.routers.admin_settings_v1 import router as admin_settings_router  # noqa: E402
app.include_router(admin_settings_router)

# Integration (외부 검색/RAG, Webhook, Sync)
try:
    from src.integration.router import integration_router
    app.include_router(integration_router)
except ImportError:
    pass

# Agent Framework (KMS-Plus) — /agent/chat SSE
from src.agent_framework.api.chat_session import router as agent_chat_router  # noqa: E402
app.include_router(agent_chat_router)

# Task 20: Agent data API (schedules/diaries/news CRUD for side panels)
from src.agent_framework.api.data_api import router as agent_data_router  # noqa: E402
app.include_router(agent_data_router)

# Task 24: Agent skills admin API (list + YAML viewer)
from src.agent_framework.api.skill_admin import router as agent_skills_router  # noqa: E402
app.include_router(agent_skills_router)

# Task 34-36 Phase A: Skill drafts API ("대화로 스킬 추가" 검토/승인)
from src.agent_framework.api.skill_drafts import router as agent_skill_drafts_router  # noqa: E402
app.include_router(agent_skill_drafts_router)

# Stage B-1: Agent identity API (account 자동 생성 / tenant memberships)
from src.agent_framework.api.identity_api import router as agent_identity_router  # noqa: E402
app.include_router(agent_identity_router)

# 2026-04-24: 로그인 페이지 shim — /login.html 에서 호출, personal_tenant_id 반환
from src.agent_framework.api.auth import router as agent_auth_router  # noqa: E402
app.include_router(agent_auth_router)
app.include_router(agent_auth_router, prefix="/api/v1")

# Phase 9 (KMS-Plus): Auth v2 — JWT + email/password (기존 /auth/login 와 공존)
from src.api.routers.auth_v2 import router as auth_v2_router  # noqa: E402
app.include_router(auth_v2_router)
app.include_router(auth_v2_router, prefix="/api/v1")

# Phase F10 (KMS-Plus): /api/v1/account/settings — display_name + preferences
from src.api.routers.account_settings import router as account_settings_router  # noqa: E402
app.include_router(account_settings_router, prefix="/api/v1")

# Phase P1.1 (KMS-Plus): /api/v1/tenants — list/get/patch/switch/members
from src.api.routers.tenants_v1 import router as tenants_v1_router  # noqa: E402
app.include_router(tenants_v1_router)

# Phase P1.2 (KMS-Plus): /api/v1/chat/sessions/* — frontend ChatEngine 호환
from src.api.routers.chat_sessions_v1 import router as chat_sessions_v1_router  # noqa: E402
app.include_router(chat_sessions_v1_router)

# Phase P1.3-P1.4 (KMS-Plus): /api/v1/chat — message/briefing/onboarding/confirm-capture
from src.api.routers.chat_v1 import router as chat_v1_router  # noqa: E402
app.include_router(chat_v1_router)

# Phase P1.5 (KMS-Plus): /api/v1/context — life/corporate CRUD
from src.api.routers.context_v1 import router as context_v1_router  # noqa: E402
app.include_router(context_v1_router)

# P0.2 (KMS-Plus): /api/v1/feed — feed_events list / mark_read.
from src.api.routers.feed_v1 import router as feed_v1_router  # noqa: E402
app.include_router(feed_v1_router)

# P0.2 (KMS-Plus): /api/v1/chat/url_preview — stub (P6 에서 SSRF guard 등 본 구현).
from src.api.routers.url_preview_v1 import router as url_preview_v1_router  # noqa: E402
app.include_router(url_preview_v1_router)

# P0.2 (KMS-Plus): /api/v1/verification — admin scenarios/runs/proposals stub.
from src.api.routers.verification_v1 import router as verification_v1_router  # noqa: E402
app.include_router(verification_v1_router)

# 2026-04-24: 챗 첨부 파일 (문서) → KMS 파이프라인 shim
from src.agent_framework.api.chat_upload import router as agent_chat_upload_router  # noqa: E402
app.include_router(agent_chat_upload_router)

# Batch 8 Task 20: /agent/activation/* 통합 라우터 (pending/approve/reject/defer/deactivate/reactivate/verify/stats)
from src.api.routers.activation import router as activation_router  # noqa: E402
app.include_router(activation_router)

# Phase 8 (KMS-Plus): admin audit 라우터 — tool_invocations / freshness_runs 조회.
from src.api.routers.audit import router as audit_router  # noqa: E402
app.include_router(audit_router)

# Phase 1.5D — agent management (templates / dashboard / billing / insights / graph / audit / alerts)
# 반드시 agents_v1 *이전* 등록 — /api/v1/agents/graph 가 /api/v1/agents/{agent_id} 보다
# 먼저 매칭되어야 함 (FastAPI 는 첫 매칭 라우트를 사용).
from src.api.routers.agent_management import router as agent_management_router  # noqa: E402
app.include_router(agent_management_router)
# External Agent (KMS-Plus 후속): /api/v1/agents/* (JWT) + /api/v1/external/agent/{id}/* (API key)
from src.api.routers.agents_v1 import router as agents_v1_router  # noqa: E402
app.include_router(agents_v1_router)
# D29 §2 (#156) — admin global view (admin/owner 전용 cross-agent 통합 view).
from src.api.routers.admin_global_view_v1 import router as admin_global_view_v1_router  # noqa: E402
app.include_router(admin_global_view_v1_router)
# D36 (#216) — super-admin role 발급/관리 (cross-tenant, JWT.role gate).
from src.api.routers.admin_users import router as admin_users_router  # noqa: E402
app.include_router(admin_users_router)
# Phase 1.5E follow-up — agent 전용 문서 등록 (자동 repo 생성 + 격리).
# /api/v1/agents/{id}/documents + /upload — agents_v1 와 prefix 동일하지만 sub-path.
from src.api.routers.agent_documents_v1 import router as agent_documents_v1_router  # noqa: E402
app.include_router(agent_documents_v1_router)
# 2026-05-07 — SOP 양식 가이드 + 19 카테고리 sample 다운로드 (공개 자료, 무인증).
from src.api.routers.sop_samples_v1 import router as sop_samples_v1_router  # noqa: E402
app.include_router(sop_samples_v1_router)
from src.api.routers.external_agent_v1 import router as external_agent_v1_router  # noqa: E402
app.include_router(external_agent_v1_router)
# Phase 1 Task 6: webhook router — /api/v1/external-agent/{kind}/{external_id}/webhook
from src.api.routers.external_agent_v1 import webhook_router as external_agent_webhook_router  # noqa: E402
app.include_router(external_agent_webhook_router)

# Wave 3-2 (KMS-Plus): /api/v1/manifest — frontend schema-driven UI 카탈로그.
# 신규 도메인은 manifest/domains/<id>.yaml 한 파일만 추가하면 frontend 자동 렌더.
from src.api.routers.manifest import router as manifest_router  # noqa: E402
app.include_router(manifest_router, prefix="/api/v1", tags=["Manifest"])

# T3 (KMS-Plus 오픈 준비): /api/v1/account/groups — company/business 활성화.
from src.api.routers.account_groups import router as account_groups_router  # noqa: E402
app.include_router(account_groups_router, prefix="/api/v1")

# manifest list_endpoint 가 명시한 일정/일기/가계부 페이지 라우터 — Bearer
# 인증 + scope_group 인지. (2026-04-28: frontend 빈 화면 버그 fix)
from src.api.routers.schedule_v1 import router as schedule_v1_router  # noqa: E402
from src.api.routers.diary_v1 import router as diary_v1_router  # noqa: E402
from src.api.routers.expense_v1 import router as expense_v1_router  # noqa: E402
from src.api.routers.stock_v1 import router as stock_v1_router  # noqa: E402
from src.api.routers.memo_v1 import router as memo_v1_router  # noqa: E402
from src.api.routers.doc_draft_v1 import router as doc_draft_v1_router  # noqa: E402
from src.api.routers.knowledge_v1 import router as knowledge_v1_router  # noqa: E402
# 2026-05-08 — citation [N] popup endpoint (Web/Telegram/OpenAI compatible 공용).
from src.api.routers.citations_v1 import router as citations_v1_router  # noqa: E402
app.include_router(schedule_v1_router, prefix="/api/v1")
app.include_router(diary_v1_router, prefix="/api/v1")
app.include_router(expense_v1_router, prefix="/api/v1")
app.include_router(stock_v1_router, prefix="/api/v1")
app.include_router(memo_v1_router, prefix="/api/v1")
app.include_router(doc_draft_v1_router, prefix="/api/v1")
app.include_router(knowledge_v1_router, prefix="/api/v1")
app.include_router(citations_v1_router, prefix="/api/v1")

# Tool catalog — agent 빌더 UI 가 사용.
from src.api.routers.tools_v1 import router as tools_v1_router  # noqa: E402
app.include_router(tools_v1_router)

# Level 1 Custom Webhook Tools — /api/v1/custom-tools (별도, tools_v1 미침범)
from src.api.routers.custom_tools_v1 import router as custom_tools_v1_router  # noqa: E402
app.include_router(custom_tools_v1_router)

# Skills Catalog — read-only yaml metadata. 커스텀 도구 관리 UI 의 "스킬 셋" 탭.
from src.api.routers.skills_catalog_v1 import router as skills_catalog_v1_router  # noqa: E402
app.include_router(skills_catalog_v1_router)


# ---------------------------------------------------------------------------
# API Version Info
# ---------------------------------------------------------------------------

from src.api.versioning import CHANGELOG, VERSION_REGISTRY  # noqa: E402


@app.get("/api/versions", tags=["시스템"])
async def list_api_versions() -> dict[str, Any]:
    return {"versions": [v.model_dump() for v in VERSION_REGISTRY.values()]}


@app.get("/api/changelog", tags=["시스템"])
async def api_changelog() -> dict[str, Any]:
    return {"changelog": CHANGELOG}
