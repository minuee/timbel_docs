"""KMS-only FastAPI 진입점 — Lucas-KMS 단독 배포용.

Phase 1 T1.4 (Lucas-KMS 분리):
- 통합 솔루션 (Locus) = src/api/main.py (기존, 그대로)
- KMS 단독 (LUCAS_PRODUCT=kms) = create_kms_app() factory
- agent / chat / skill / tool / external-agent / scheduler 라우터는 *0개*.
- 메모리 절칙: KMS (assist-stream RAG 완성품) + Lucas (KMS 위 agent layer)
  분리 철칙 (2026-05-13). KMS-only 배포는 agent layer 가 없어야 한다.

라우터 등록은 데이터 driven — 하단 KMS_ROUTERS / SHARED_ROUTERS 리스트가
single source. 새 KMS 라우터는 리스트에 한 줄 추가만 하면 됨 (하드코딩 회피).

검증:
    python3 -c "from src.api.main_kms import create_kms_app; \\
                a = create_kms_app(); print(len(a.routes))"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import APIRouter, FastAPI

from src.api import _common
from src.common.logging import get_logger
from src.common.swagger_policy import configure_swagger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lucas-KMS 전용 OpenAPI metadata
# ---------------------------------------------------------------------------
#
# 정책: KMS-only 진입점은 자체 info / tags description 을 가짐. 통합 솔루션
# (main.py) 가 사용하는 _common.OPENAPI_TAGS 와 별개 — 그러나 KMS 코어 태그
# 정의는 그대로 활용하면서 추가 태그(인증/Tenant/감사/시스템 등) 만 보강.

LUCAS_KMS_DESCRIPTION = """\
**Lucas-KMS** — Locus AI 의 Knowledge Management System (KMS) 분리 제품.

문서 업로드부터 RAG 답변 생성까지 단일 API 표면으로 제공한다. 외부 시스템은
이 API 만으로 자료 적재 → 정제 → 검색 → LLM 답변까지 수행할 수 있다.

## 주요 기능
- **자료 적재**: 파일 업로드 (PDF/DOCX/MD/HTML/TXT 최대 100MB), 노션 스타일 노트
- **자료화 파이프라인**: 파싱 → 블럭 추출 → 분류 → 임베딩 → 벡터 적재 (Qdrant + ES)
- **하이브리드 검색**: Dense (BGE-M3) + Sparse + Keyword + RRF 퓨전 + Cross-encoder 리랭킹
- **RAG 답변**: 정제(distill) → 생성(answer) 2단계 + 인용 마커 + 신뢰도 + 환각 감지
- **상담 보조 SSE**: `assist-stream` 으로 외부 웹프론트에 즉시 답변 스트리밍
- **Multi-tenant 격리**: tenant 단위 데이터 격리 (PostgreSQL RLS + Qdrant payload + ES filter)

## 인증
- 무인증 모드 (`LUCAS_AUTH_DISABLED=true`, default in dev): 헤더 없이 자유 호출.
  외부 노출 환경에서는 *반드시* false 로 전환할 것.
- JWT 모드 (`LUCAS_AUTH_DISABLED=false`):
  - `Authorization: Bearer <token>` 헤더 필수
  - tenant 선택은 `X-Tenant-Id` 또는 토큰의 `tenant_id` 클레임
  - 토큰은 `POST /auth/v2/login` 으로 발급

## 응답 wrapper
대부분의 endpoint 는 `ApiResponse[T]` wrapper 로 응답:
- 성공: `{"data": T}`
- 실패: `{"error": {"code": "...", "message": "..."}}`

## 에러 코드 (대표)
- `TENANT_ID_REQUIRED` — `X-Tenant-Id` 헤더 누락 (인증 모드)
- `NOT_FOUND` — 리소스 부재 (저장소/문서/블럭)
- `VALIDATION` — Pydantic 검증 실패 (필드 누락/형식 오류)
- `LICENSE_LIMIT_EXCEEDED` — 저장소/문서/검색 한도 초과
- `RATE_LIMITED` — 호출 빈도 초과

## SSE 스트리밍 endpoint
`POST /api/v1/rag/stream`, `POST /api/v1/rag/assist-stream`, `POST /api/v1/ext/ask/stream`
는 `text/event-stream` 으로 응답 — Swagger 의 “Try it out” 으로는 정확히 표시되지
않음. 클라이언트는 `EventSource` 또는 `fetch` + `ReadableStream` 으로 구독.

## SDK / 클라이언트
- OpenAPI schema: `/api/v1/openapi.json` (또는 `/openapi.json`)
- Swagger UI: `/api/v1/docs` (또는 `/docs`)
- ReDoc: `/redoc`
"""


def _lucas_kms_tags_metadata() -> list[dict[str, str]]:
    """Lucas-KMS Swagger tags 정의.

    `_common.OPENAPI_TAGS` 의 KMS 코어 태그에 인증/Tenant/관리/시스템 태그를
    추가 보강. 데이터 driven — 신규 라우터의 tag 도 여기에 한 줄 추가하면 됨.
    """
    extra: list[dict[str, str]] = [
        {
            "name": "저장소 그룹",
            "description": (
                "Lucas-KMS 전용 — tenant 안 named multi-repository subset. "
                "검색 시 group_id 또는 repository_ids array 로 multi-repo 검색."
            ),
        },
        {"name": "시스템", "description": "버전 정보, changelog, health-check"},
        {"name": "auth-v2", "description": "JWT 발급/갱신/로그아웃/회원가입"},
        {"name": "tenants-v1", "description": "Tenant CRUD, 전환, 멤버 조회"},
        {
            "name": "계정 설정",
            "description": "사용자 계정 환경설정 (테마/언어/onboarding 상태)",
        },
        {"name": "계정 그룹", "description": "기업/사업자 계정 그룹 활성화"},
        {"name": "admin-global-view", "description": "관리자 — cross-tenant 글로벌 뷰"},
        {"name": "admin-users", "description": "관리자 — 슈퍼 admin 권한 발급/관리"},
        {
            "name": "관리자 — Feature Flags",
            "description": "런타임 feature flag 토글 (admin 전용)",
        },
        {"name": "관리자 워커 트리거", "description": "백그라운드 워커 수동 트리거"},
        {"name": "관리자 초기화", "description": "테스트 환경 reset endpoint"},
        {"name": "감사", "description": "tool 호출/freshness 실행 audit log"},
        {"name": "인용 (citations)", "description": "답변 내 [N] 인용 마커 → 출처 popup"},
        {
            "name": "라이브러리 폴더",
            "description": "저장소 내부 트리 구조 폴더 (SOP/매뉴얼/FAQ/정책/용어집)",
        },
        {"name": "Mail Accounts", "description": "메일함 연동 (IMAP/POP3 + SMTP)"},
        {"name": "Inbox", "description": "메일함 list/요약/액션 (메일→일정/할일/초안)"},
        {"name": "Library Folders", "description": "저장소 내부 폴더 트리 + 문서 이동"},
        {"name": "RAG Assist", "description": "외부 웹프론트 상담 보조 SSE"},
        {"name": "LLM 메트릭", "description": "LLM 호출 latency/토큰 메트릭"},
    ]
    return _common.OPENAPI_TAGS + extra


# ---------------------------------------------------------------------------
# 라우터 spec — 데이터 driven (하드코딩 회피)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouterSpec:
    """단일 라우터 mount 명세.

    - loader: lazy import — KMS-only 배포라도 의존성 누락 시 graceful skip.
    - prefix / tags: include_router 인자.
    - allow_missing: True 면 ImportError 를 warning 으로 흘려보냄.
    """

    name: str
    loader: Callable[[], APIRouter]
    prefix: str | None = None
    tags: list[str] = field(default_factory=list)
    allow_missing: bool = False


def _spec(
    name: str,
    loader: Callable[[], APIRouter],
    prefix: str | None = None,
    tags: list[str] | None = None,
    allow_missing: bool = False,
) -> RouterSpec:
    return RouterSpec(
        name=name,
        loader=loader,
        prefix=prefix,
        tags=list(tags) if tags else [],
        allow_missing=allow_missing,
    )


def _build_kms_specs() -> list[RouterSpec]:
    """KMS 파이프라인 코어 라우터 spec.

    Lazy loader — 모든 import 는 factory 호출 시점.
    """
    # src.api.routers 의 __init__ 이 노출하는 라우터들 (eager import OK).
    from src.api import routers as r

    return [
        # 헬스체크 (/health/live, /health/ready)
        _spec("health", lambda: r.health_router),

        # 저장소 & 카테고리 & 문서타입
        _spec(
            "repositories",
            lambda: r.repositories_router,
            prefix="/api/v1",
            tags=["저장소"],
        ),
        _spec(
            "repository_groups",
            lambda: r.repository_groups_router,
            prefix="/api/v1",
            tags=["저장소 그룹"],
        ),
        _spec(
            "categories",
            lambda: r.categories_router,
            prefix="/api/v1",
            tags=["카테고리"],
        ),
        _spec(
            "document_types",
            lambda: r.document_types_router,
            prefix="/api/v1",
            tags=["문서타입"],
        ),

        # 문서 & 블럭 & 노트 & 청크 (파이프라인 코어)
        _spec(
            "documents",
            lambda: r.documents_router,
            prefix="/api/v1",
            tags=["문서"],
        ),
        _spec(
            "blocks",
            lambda: r.blocks_router,
            prefix="/api/v1",
            tags=["블럭"],
        ),
        _spec(
            "notes",
            lambda: r.notes_router,
            prefix="/api/v1",
            tags=["노트"],
        ),
        _spec(
            "chunks",
            lambda: r.chunks_router,
            prefix="/api/v1",
            tags=["청크"],
        ),
        _spec(
            "preview",
            lambda: r.preview_router,
            prefix="/api/v1",
            tags=["문서"],
        ),

        # 검색 & RAG
        _spec(
            "search",
            lambda: r.search_router,
            prefix="/api/v1/search",
            tags=["검색"],
        ),
        _spec(
            "rag",
            lambda: r.rag_router,
            prefix="/api/v1/rag",
            tags=["RAG"],
        ),
        _spec(
            "rag_assist",
            lambda: r.rag_assist_router,
            prefix="/api/v1/rag",
            tags=["RAG Assist"],
        ),
        _spec(
            "search_proxy",
            lambda: r.search_proxy_router,
            prefix="/api/v1",
            tags=["Search Proxy"],
        ),

        # 검색 튜닝
        _spec(
            "synonyms",
            lambda: r.synonyms_router,
            prefix="/api/v1/synonyms",
            tags=["동의어"],
        ),
        _spec(
            "ab_tests",
            lambda: r.ab_tests_router,
            prefix="/api/v1/search/ab-tests",
            tags=["A/B 테스트"],
        ),

        # 거버넌스 (파이프라인)
        _spec(
            "confidentiality",
            lambda: r.confidentiality_router,
            prefix="/api/v1",
            tags=["기밀 등급"],
        ),
        _spec(
            "pii",
            lambda: r.pii_router,
            prefix="/api/v1",
            tags=["PII"],
        ),
        _spec(
            "anonymization",
            lambda: r.anonymization_router,
            prefix="/api/v1/anonymization",
            tags=["익명화"],
        ),

        # 통계 & 분석
        _spec(
            "stats",
            lambda: r.stats_router,
            prefix="/api/v1/stats",
            tags=["통계"],
        ),
        _spec(
            "analytics",
            lambda: r.analytics_router,
            prefix="/api/v1/analytics",
            tags=["검색 분석"],
        ),
        _spec(
            "feedback_stats",
            lambda: r.feedback_stats_router,
            prefix="/api/v1/feedback-stats",
            tags=["피드백 통계"],
        ),
        _spec(
            "knowledge_gap",
            lambda: r.knowledge_gap_router,
            prefix="/api/v1/knowledge-gap",
            tags=["지식 갭"],
        ),
        _spec(
            "classification_quality",
            lambda: r.classification_quality_router,
            prefix="/api/v1/quality",
            tags=["분류 품질"],
        ),
        _spec(
            "llm_metrics",
            lambda: r.llm_metrics_router,
            prefix="/api/v1/metrics",
            tags=["LLM 메트릭"],
        ),

        # 운영 도구
        _spec(
            "playground",
            lambda: r.playground_router,
            prefix="/api/v1/playground",
            tags=["Playground"],
        ),
        _spec("reprocess", lambda: r.reprocess_router, tags=["재처리"]),
        _spec(
            "pipeline_admin",
            lambda: r.pipeline_admin_router,
            tags=["파이프라인 관리"],
        ),
        _spec("admin_reset", lambda: r.admin_reset_router),
        _spec("workers_admin", lambda: r.workers_admin_router),
        _spec(
            "webhook_inbound",
            lambda: r.webhook_inbound_router,
            prefix="/api/v1",
            tags=["Webhook"],
        ),
        _spec(
            "mail_accounts",
            lambda: r.mail_accounts_router,
            prefix="/api/v1",
            tags=["Mail Accounts"],
        ),
        _spec("inbox", lambda: r.inbox_router),

        # 라이브러리 폴더 트리 (alembic 067) — repo 안 트리 분류 + 문서 이동
        _spec(
            "library_folders",
            lambda: r.library_folders_router,
            prefix="/api/v1",
            tags=["Library Folders"],
        ),
    ]


def _load_admin_settings() -> APIRouter:
    from src.api.routers.admin_settings_v1 import router as _router
    return _router


def _load_citations_v1() -> APIRouter:
    from src.api.routers.citations_v1 import router as _router
    return _router


def _load_knowledge_v1() -> APIRouter:
    from src.api.routers.knowledge_v1 import router as _router
    return _router


def _load_url_preview_v1() -> APIRouter:
    from src.api.routers.url_preview_v1 import router as _router
    return _router


def _load_auth_v2() -> APIRouter:
    from src.api.routers.auth_v2 import router as _router
    return _router


def _load_account_settings() -> APIRouter:
    from src.api.routers.account_settings import router as _router
    return _router


def _load_tenants_v1() -> APIRouter:
    from src.api.routers.tenants_v1 import router as _router
    return _router


def _load_audit() -> APIRouter:
    from src.api.routers.audit import router as _router
    return _router


def _load_admin_global_view_v1() -> APIRouter:
    from src.api.routers.admin_global_view_v1 import router as _router
    return _router


def _load_admin_users() -> APIRouter:
    from src.api.routers.admin_users import router as _router
    return _router


def _load_account_groups() -> APIRouter:
    from src.api.routers.account_groups import router as _router
    return _router


def _build_shared_specs() -> list[RouterSpec]:
    """공유 라우터 spec (auth / tenant / admin / audit).

    KMS-only 배포에서도 인증 / 테넌트 관리 / 감사 / admin 글로벌 뷰는 필요.
    agent layer 와 무관한 shared 평면.
    """
    return [
        # KMS-Plus admin feature flag runtime 토글 (alembic 073).
        _spec("admin_settings_v1", _load_admin_settings),

        # citation [N] popup endpoint (Web/Telegram/OpenAI compatible 공용).
        _spec(
            "citations_v1",
            _load_citations_v1,
            prefix="/api/v1",
        ),

        # knowledge v1 — KMS 표면 (RAG/검색 외 knowledge entity 등).
        _spec(
            "knowledge_v1",
            _load_knowledge_v1,
            prefix="/api/v1",
        ),

        # url preview stub.
        _spec("url_preview_v1", _load_url_preview_v1),

        # Auth v2 (JWT + email/password) — root + /api/v1 양쪽.
        _spec("auth_v2_root", _load_auth_v2),
        _spec("auth_v2_apiv1", _load_auth_v2, prefix="/api/v1"),

        # /api/v1/account/settings.
        _spec(
            "account_settings",
            _load_account_settings,
            prefix="/api/v1",
        ),

        # /api/v1/tenants — list/get/patch/switch/members.
        _spec("tenants_v1", _load_tenants_v1),

        # admin audit — tool_invocations / freshness_runs 조회.
        _spec("audit", _load_audit),

        # admin global view (admin/owner cross-agent).
        _spec("admin_global_view_v1", _load_admin_global_view_v1),

        # super-admin role 발급/관리 (cross-tenant).
        _spec("admin_users", _load_admin_users),

        # /api/v1/account/groups — company/business 활성화.
        _spec(
            "account_groups",
            _load_account_groups,
            prefix="/api/v1",
        ),
    ]


# ---------------------------------------------------------------------------
# Integration router (KMS scope — webhook/search/RAG/sync 외부 인터페이스)
# ---------------------------------------------------------------------------

def _try_mount_integration(app: FastAPI) -> None:
    """integration_router — 외부 검색/RAG/Webhook/Sync.

    KMS 가 외부 시스템과 정합 시 필요. import 실패는 warning.
    """
    try:
        from src.integration.router import integration_router

        app.include_router(integration_router)
    except ImportError as exc:
        logger.warning("kms_integration_router_unavailable", error=str(exc))


# ---------------------------------------------------------------------------
# API versioning endpoints (공유)
# ---------------------------------------------------------------------------

def _register_version_endpoints(app: FastAPI) -> None:
    from src.api.versioning import CHANGELOG, VERSION_REGISTRY

    @app.get(
        "/api/versions",
        tags=["시스템"],
        summary="API 버전 목록",
        description=(
            "현재 노출 중인 API 버전들의 메타데이터를 반환한다. "
            "각 항목은 `version`, `status` (current/deprecated/sunset), "
            "`released_at`, `deprecated_at` 등을 포함."
        ),
        responses={200: {"description": "버전 목록"}},
    )
    async def list_api_versions() -> dict[str, Any]:
        return {"versions": [v.model_dump() for v in VERSION_REGISTRY.values()]}

    @app.get(
        "/api/changelog",
        tags=["시스템"],
        summary="API 변경 이력",
        description=(
            "API 변경 이력 (changelog) 을 시간 역순으로 반환한다. "
            "신규 endpoint, breaking change, deprecation 일정 등을 포함."
        ),
        responses={200: {"description": "changelog 리스트"}},
    )
    async def api_changelog() -> dict[str, Any]:
        return {"changelog": CHANGELOG}

    @app.get(
        "/health",
        tags=["시스템"],
        summary="간이 헬스체크",
        description=(
            "프로세스가 살아있는지 확인하는 경량 endpoint. "
            "DB/vLLM/외부 의존성은 체크하지 않음 — 자세한 점검은 "
            "`/health/live` 와 `/health/ready` 를 사용할 것."
        ),
        responses={200: {"description": "프로세스 정상", "content": {
            "application/json": {"example": {"status": "ok"}}
        }}},
    )
    async def health() -> dict[str, str]:
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_kms_app() -> FastAPI:
    """KMS-only FastAPI 앱 — agent 라우터 0개.

    Lucas-KMS 단독 배포 (LUCAS_PRODUCT=kms) 진입점.
    통합 솔루션은 src/api/main.py 의 module-level `app` 그대로 사용.
    """
    app = FastAPI(
        title="Lucas-KMS API",
        version="1.0.0",
        summary=(
            "Locus AI 의 Knowledge Management System 분리 제품 — "
            "자료화 → 검색 → RAG 답변까지 단일 API 표면"
        ),
        description=LUCAS_KMS_DESCRIPTION,
        lifespan=_common.shared_lifespan,
        openapi_tags=_lucas_kms_tags_metadata(),
        docs_url="/docs",
        redoc_url="/redoc",
        contact={
            "name": "Lucas-KMS",
            "url": "https://github.com/RickySonYH/Lucas-KMS",
        },
        license_info={"name": "TBD"},
    )

    # Prometheus / CORS / 보안 middleware — 공유 helper.
    _common.setup_prometheus(app)
    _common.setup_cors(app)
    _common.setup_security_middleware(app)

    # Phase 4 T4.6 — Swagger 운영 보안 정책.
    # ENABLE_SWAGGER=false / SWAGGER_AUTH_MODE / SWAGGER_IP_ALLOWLIST 적용.
    configure_swagger(app, product="kms")

    # 에러 핸들러.
    _common.register_error_handlers(app)

    # health + version endpoints.
    _register_version_endpoints(app)

    # KMS 파이프라인 코어 라우터.
    _mount_specs(app, _build_kms_specs(), context="kms_core")

    # 공유 라우터 (auth / tenant / audit / admin).
    _mount_specs(app, _build_shared_specs(), context="shared")

    # integration (외부 검색/RAG/Webhook/Sync) — best-effort.
    _try_mount_integration(app)

    logger.info(
        "kms_app_created",
        total_routes=len(app.routes),
        product="kms",
    )
    return app


def _mount_specs(
    app: FastAPI,
    specs: list[RouterSpec],
    context: str,
) -> None:
    """RouterSpec 리스트 → include_router 일괄 등록."""
    for spec in specs:
        try:
            router = spec.loader()
        except ImportError as exc:
            # KMS-only image 는 .dockerignore 로 src/agent_framework 가 stripped — 그 의존
            # router 의 ImportError 는 *격리 의도*. spec.allow_missing 표시가 없어도 항상
            # graceful skip. 통합 솔루션 측은 agent_framework 존재 → ImportError 자체 안남.
            exc_name = getattr(exc, "name", None) or ""
            if "agent_framework" in str(exc) or "agent_framework" in exc_name:
                logger.warning(
                    "kms_router_agent_framework_dep_skipped",
                    name=spec.name,
                    context=context,
                    error=str(exc),
                )
                continue
            if spec.allow_missing:
                logger.warning(
                    "kms_router_optional_missing",
                    name=spec.name,
                    context=context,
                    error=str(exc),
                )
                continue
            raise
        kwargs: dict[str, Any] = {}
        if spec.prefix:
            kwargs["prefix"] = spec.prefix
        if spec.tags:
            kwargs["tags"] = spec.tags
        app.include_router(router, **kwargs)


__all__ = ["create_kms_app", "RouterSpec"]
