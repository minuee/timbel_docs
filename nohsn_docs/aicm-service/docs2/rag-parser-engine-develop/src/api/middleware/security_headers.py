"""Phase 13 — 보안 헤더 미들웨어.

매 응답에 다음 헤더를 부여:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: SAMEORIGIN
    - Referrer-Policy: strict-origin-when-cross-origin
    - Strict-Transport-Security (HTTPS 응답에 한해)
    - Content-Security-Policy (단순 default — 추후 강화)

CSP 의 connect-src 에 frontend dev origin (localhost:5101) 을 포함해 dev 환경
브라우저가 API 호출할 수 있게 둔다.  prod 에서는 KMS_CSP_CONNECT_SRC env 로
override 가능.
"""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_DEFAULT_CONNECT_SRC = os.environ.get(
    "KMS_CSP_CONNECT_SRC",
    "'self' http://localhost:5101 ws://localhost:5101",
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """프록시-친화적인 보안 헤더 부여."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        # HSTS — HTTPS 일 때만 (X-Forwarded-Proto 도 검사 — nginx terminate 환경)
        scheme = request.url.scheme
        proto_hdr = request.headers.get("x-forwarded-proto", "").lower()
        if scheme == "https" or proto_hdr == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        # /docs / /redoc 은 swagger-ui-dist (cdn.jsdelivr.net) 자원 로드 필요 — CSP 완화.
        path = request.url.path
        is_swagger_path = path in ("/docs", "/redoc") or path.startswith(("/docs/", "/redoc/"))
        if is_swagger_path:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                f"connect-src {_DEFAULT_CONNECT_SRC}"
            )
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data: https:; "
                    f"connect-src {_DEFAULT_CONNECT_SRC}"
                ),
            )
        return response


__all__ = ["SecurityHeadersMiddleware"]
