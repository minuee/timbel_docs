"""API 버전 관리 전략.

- URL 접두사 기반 버전 라우팅 (/api/v1/, /api/v2/)
- Sunset 헤더를 통한 버전 폐기 알림
- 버전 협상 미들웨어
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Request, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.common.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 버전 메타데이터
# ---------------------------------------------------------------------------


class APIVersionInfo(BaseModel):
    """API 버전 메타데이터."""

    version: str
    status: str  # "current" | "deprecated" | "sunset"
    sunset_date: datetime | None = None
    changelog_url: str = ""


# 버전 레지스트리: 어떤 버전이 현재 활성인지, 폐기 예정인지 관리
VERSION_REGISTRY: dict[str, APIVersionInfo] = {
    "v1": APIVersionInfo(
        version="v1",
        status="current",
        changelog_url="/api/changelog",
    ),
    "v2": APIVersionInfo(
        version="v2",
        status="current",
        changelog_url="/api/changelog",
    ),
}


def register_version(
    version: str,
    status: str = "current",
    sunset_date: datetime | None = None,
) -> None:
    """API 버전을 레지스트리에 등록한다."""
    VERSION_REGISTRY[version] = APIVersionInfo(
        version=version,
        status=status,
        sunset_date=sunset_date,
        changelog_url="/api/changelog",
    )


def deprecate_version(version: str, sunset_date: datetime) -> None:
    """특정 버전을 deprecated 상태로 전환한다."""
    if version in VERSION_REGISTRY:
        info = VERSION_REGISTRY[version]
        VERSION_REGISTRY[version] = info.model_copy(
            update={"status": "deprecated", "sunset_date": sunset_date}
        )
        logger.info(
            "api_version_deprecated",
            version=version,
            sunset_date=sunset_date.isoformat(),
        )


# ---------------------------------------------------------------------------
# 미들웨어
# ---------------------------------------------------------------------------


class APIVersionMiddleware(BaseHTTPMiddleware):
    """API 버전 협상 미들웨어.

    - 요청 경로에서 API 버전을 추출한다 (/api/v1/..., /api/v2/...).
    - deprecated 버전 접근 시 Sunset, Deprecation 헤더를 응답에 추가한다.
    - X-API-Version 응답 헤더로 현재 버전을 알려준다.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """버전 헤더를 응답에 추가한다."""
        path = request.url.path
        api_version: str | None = None

        # /api/vN/ 패턴에서 버전 추출
        if path.startswith("/api/"):
            parts = path.split("/")
            if len(parts) >= 3 and parts[2].startswith("v"):
                api_version = parts[2]

        response = await call_next(request)

        if api_version:
            response.headers["X-API-Version"] = api_version

            version_info = VERSION_REGISTRY.get(api_version)
            if version_info and version_info.status == "deprecated":
                if version_info.sunset_date:
                    response.headers["Sunset"] = version_info.sunset_date.strftime(
                        "%a, %d %b %Y %H:%M:%S GMT"
                    )
                response.headers["Deprecation"] = "true"
                response.headers["Link"] = (
                    f'</api/changelog>; rel="successor-version"'
                )

        return response


# ---------------------------------------------------------------------------
# 변경 로그 데이터
# ---------------------------------------------------------------------------


CHANGELOG: list[dict[str, Any]] = [
    {
        "version": "v1",
        "date": "2025-01-01",
        "changes": [
            "Initial API release",
            "Tenant/Repository/Document/Search CRUD",
            "Hybrid search with reranking",
            "RAG context builder (Direct + Generation mode)",
        ],
    },
    {
        "version": "v2",
        "date": "2026-04-01",
        "changes": [
            "API versioning with Sunset header support",
            "Prometheus metrics endpoint",
            "Enhanced health checks (liveness, readiness, detailed)",
            "A/B testing support",
            "Improved search with synonym expansion",
        ],
    },
]
