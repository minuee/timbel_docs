"""공통 FastAPI 컴포넌트 — main.py / main_kms.py 공유.

Phase 1 T1.4 (Lucas-KMS 분리):
- 통합 솔루션 (Locus) 진입점 = src/api/main.py
- KMS-only 진입점 = src/api/main_kms.py (create_kms_app factory)
- 두 진입점이 공유하는 lifespan / 에러 핸들러 / metrics / middleware
  setup 을 이 모듈로 추출. 기존 main.py 동작은 그대로 유지 (helper 가
  동일 동작을 캡슐화). 양쪽이 동일한 lifecycle 을 갖도록 단일 source.

설계 원칙:
- lifespan / 에러 핸들러 본문은 main.py 의 기존 코드를 그대로 옮겨옴
  (동작 보존). 회귀 0.
- helper 는 app 인자를 받아 mutate. import side-effect 는 helper 내부에
  국한 (top-level import 시점 부작용 최소화).
- 라우터 등록은 product (locus / kms) 별로 다르므로 *이 모듈에 두지 않음*.
  각 main_* 가 자체 책임.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
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
# OpenAPI tags (공유)
# ---------------------------------------------------------------------------

OPENAPI_TAGS: list[dict[str, str]] = [
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


# ---------------------------------------------------------------------------
# Lifespan (공유) — main.py 본문과 동일.
# ---------------------------------------------------------------------------

@asynccontextmanager
async def shared_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """공유 lifespan — main.py 의 기존 lifespan 본문을 그대로 옮겨옴.

    KMS-only 배포라도 lifespan 자체는 동일 (DB init / RLS self-check / okt
    warmup / mail mirror / scheduler 등). agent scheduler 는 framework
    dependency 가 lazy 로드되므로 KMS-only 배포에서도 try/except 로 안전.
    필요 시 future PR 에서 product flag 로 selective 비활성화.
    """
    setup_logging()
    logger.info("app_starting", env=settings.APP_ENV, port=settings.API_PORT)

    try:
        from src.core.database import init_db
        await init_db()
    except Exception as exc:
        logger.warning("db_init_skipped", error=str(exc))

    # D41 Phase 1 — citation HMAC secret fail-fast 검증.
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

    # D33 §1 — RLS 운영 전환 self-check.
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
        logger.warning("rls_self_check_skipped", error=str(_self_check_exc))

    # Okt 형태소 분석기 warmup.
    try:
        from src.search.hybrid.preprocessor import QueryPreprocessor, _HAS_OKT

        if _HAS_OKT:
            _warmup_pp = QueryPreprocessor()
            await _warmup_pp.preprocess("검색 워밍업 더미")
            logger.info("okt_warmup_done")
        else:
            logger.info("okt_warmup_skipped_no_konlpy")
    except Exception as exc:
        logger.warning("okt_warmup_failed", error=str(exc))

    # Task 19: AgentEngine 의 CronRunner 스케줄러 기동.
    # KMS-only 배포에서는 agent_framework dependency 가 lazy 로드.
    # import 실패 / 초기화 실패는 warning 으로 흘려보내 KMS 단독 운영 보장.
    try:
        from src.agent_framework.api.dependencies import get_agent_engine

        _agent_engine = await get_agent_engine()
        _agent_engine.cron.start()
        logger.info("agent_scheduler_started")
    except Exception as exc:
        logger.warning("agent_scheduler_start_failed", error=str(exc))

    # 델타 #5 (KMS-Plus): framework-level cron — freshness cross-scan / cc-pair reprobe.
    if os.environ.get("KMS_SCHEDULER_ENABLED") == "true":
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

    # PR-Z11A (KMS-Plus): 메일 미러링 worker.
    try:
        from src.integration.mail import credentials as _mail_creds
        from src.integration.mail.mirror_worker import MailMirrorWorker
        from src.core.database import engine as _db_engine

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
# 에러 핸들러 (공유)
# ---------------------------------------------------------------------------

_AICM_STATUS_MAP: dict[str, int] = {
    "NOT_FOUND": 404,
    "REPOSITORY_NOT_FOUND": 404,
    "DOCUMENT_NOT_FOUND": 404,
    "CATEGORY_NOT_FOUND": 404,
    "DOCUMENT_TYPE_NOT_FOUND": 404,
    "DUPLICATE_SLUG": 409,
    "DUPLICATE_NAME": 409,
    "UNSUPPORTED_FORMAT": 400,
    "FILE_TOO_LARGE": 413,
    "TENANT_ID_REQUIRED": 400,
    "INVALID_STATUS_TRANSITION": 400,
}


async def aicm_error_handler(request: Request, exc: AICMError) -> JSONResponse:
    status_code = _AICM_STATUS_MAP.get(exc.code, 400)
    logger.warning(
        "aicm_error",
        path=request.url.path,
        code=exc.code,
        message=exc.message,
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        },
    )


async def general_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception", path=request.url.path, error=str(exc)
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "내부 서버 오류",
            },
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """공유 에러 핸들러 등록."""
    app.add_exception_handler(AICMError, aicm_error_handler)
    app.add_exception_handler(Exception, general_error_handler)


# ---------------------------------------------------------------------------
# Prometheus metrics mount (공유)
# ---------------------------------------------------------------------------

def setup_prometheus(app: FastAPI) -> None:
    """Prometheus /metrics + /metrics-kms 마운트 + middleware 등록.

    D78: kms_* counter 는 default REGISTRY 사용 → /metrics-kms 로 별도 expose.
    """
    from src.api.metrics import REGISTRY, PrometheusMiddleware

    metrics_app = make_asgi_app(registry=REGISTRY)
    app.mount("/metrics", metrics_app)

    # D78 — kms_* counter eager-load (default REGISTRY).
    import src.common.metrics  # noqa: F401

    _kms_metrics_app = make_asgi_app()
    app.mount("/metrics-kms", _kms_metrics_app)

    app.add_middleware(PrometheusMiddleware)


# ---------------------------------------------------------------------------
# CORS (공유)
# ---------------------------------------------------------------------------

def setup_cors(app: FastAPI) -> None:
    """CORS middleware 등록."""
    cors_origins = [
        o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# Security / maintenance / RLS middleware (공유)
# ---------------------------------------------------------------------------

def setup_security_middleware(app: FastAPI) -> None:
    """Rate limit + security headers + RLS context + maintenance gate.

    LIFO 순서 주의 — 가장 마지막 add 가 가장 먼저 실행.
    1. rate limit (setup_rate_limit 내부 add)
    2. SecurityHeadersMiddleware
    3. RLSContextMiddleware (endpoint 직전 RLS set)
    4. MaintenanceGateMiddleware (가장 먼저 실행 — 다른 middleware 부작용 차단)
    """
    from src.api.middleware.maintenance_gate import MaintenanceGateMiddleware
    from src.api.middleware.rate_limit import setup_rate_limit
    from src.api.middleware.rls_context_middleware import RLSContextMiddleware
    from src.api.middleware.security_headers import SecurityHeadersMiddleware

    setup_rate_limit(app)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RLSContextMiddleware)
    app.add_middleware(MaintenanceGateMiddleware)
