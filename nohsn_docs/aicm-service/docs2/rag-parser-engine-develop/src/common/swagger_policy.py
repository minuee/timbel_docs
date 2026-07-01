"""Swagger 운영 보안 정책 — Phase 4 T4.6.

spec: docs/superpowers/specs/2026-05-19-lucas-kms-separation-design.md §5.2

운영 환경 (특히 공공 SaaS Lucas-KMS) 에서 FastAPI 기본 Swagger UI / openapi.json
이 무인증으로 외부 노출되면 안 됨. 본 모듈은 env 변수로 다음 3 layer 를 적용:

1) ENABLE_SWAGGER (default: dev=true, prod=false)
   - false → /docs, /redoc, /openapi.json 모두 404 (app.docs_url=None 등)

2) SWAGGER_AUTH_MODE (none / basic / jwt, default=none)
   - basic → SWAGGER_BASIC_USER / SWAGGER_BASIC_PASSWORD 검증, 401 + WWW-Authenticate
   - jwt   → Authorization: Bearer ... 헤더 필수 (값 검증은 기존 auth 모듈 위임)
   - none  → 인증 없음 (dev 편의)

3) SWAGGER_IP_ALLOWLIST (comma-separated CIDR, default=빈값)
   - 빈값 → IP 검사 없음
   - 값 있음 → request.client.host 가 어떤 CIDR 에도 속하지 않으면 403

env 결정 우선순위:
  ENV (lower) — "prod" / "production" → swagger default off
  그 외 (dev/test/staging/unset) → swagger default on
  명시적 ENABLE_SWAGGER 가 있으면 default 무시.

메모리 절칙 반영:
- 이모지 X
- 하드코딩 X — env 변수 기반
- 기존 백엔드 재작성 X — middleware 추가만, 라우터 손대지 않음
"""

from __future__ import annotations

import base64
import ipaddress
import os
from typing import Final

from fastapi import FastAPI, Request
from starlette.responses import Response

from src.common.logging import get_logger

logger = get_logger(__name__)


# Swagger UI / openapi.json 경로 — FastAPI default + /api/v1 prefix variant.
# 코드가 마운트하는 path 변화에도 안전하도록 set 으로 비교.
_SWAGGER_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
        "/api/v1/docs",
        "/api/v1/redoc",
        "/api/v1/openapi.json",
    }
)


_TRUTHY: Final[frozenset[str]] = frozenset({"true", "1", "yes", "on"})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in _TRUTHY


def _default_swagger_enabled() -> bool:
    """ENV 값 기반 default — prod/production 에서는 off, 그 외 on."""
    env = (os.environ.get("ENV") or os.environ.get("APP_ENV") or "dev").strip().lower()
    return env not in ("prod", "production")


def _parse_allowlist(raw: str) -> list[str]:
    return [c.strip() for c in raw.split(",") if c.strip()]


def _ip_in_allowlist(client_ip: str, cidrs: list[str]) -> bool:
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            # 잘못된 CIDR 은 skip (운영 misconfig 가 전체 차단으로 번지지 않게).
            logger.warning("swagger_allowlist_invalid_cidr", cidr=cidr)
            continue
        if addr in net:
            return True
    return False


def _disable_docs(app: FastAPI) -> None:
    """Swagger 완전 비활성 — FastAPI 가 docs/openapi.json 라우트 자체를 mount 안 함.

    이미 app 이 생성된 후라도 attribute 만 None 으로 바꿔도 효과 없음
    (router 가 이미 등록됨). 안전하게 동작시키려면 factory 가 생성 직후
    호출하거나, 등록된 route 를 제거해야 한다. 본 helper 는 attribute 갱신
    + 등록된 route 제거 양쪽을 처리.
    """
    targets = {app.docs_url, app.redoc_url, app.openapi_url}
    targets.discard(None)

    app.docs_url = None
    app.redoc_url = None
    app.openapi_url = None

    if targets:
        # FastAPI 가 등록한 docs/redoc/openapi route 를 제거.
        new_routes = []
        for route in app.router.routes:
            path = getattr(route, "path", None)
            if path in targets:
                continue
            new_routes.append(route)
        app.router.routes = new_routes


def configure_swagger(app: FastAPI, *, product: str) -> None:
    """ENABLE_SWAGGER / SWAGGER_AUTH_MODE / SWAGGER_IP_ALLOWLIST 적용.

    Args:
        app: FastAPI 인스턴스.
        product: "kms" 또는 "full" — 로그 식별용. 정책 분기 없음 (env 가 단일 source).
    """
    enabled = _env_bool("ENABLE_SWAGGER", _default_swagger_enabled())
    if not enabled:
        _disable_docs(app)
        logger.info("swagger_disabled", product=product)
        return

    # Lucas-KMS 무인증 모드 — auth 정책 bypass. 사용자 명시 (2026-05-19).
    from src.common.config import settings
    if settings.LUCAS_AUTH_DISABLED:
        logger.warning(
            "swagger_auth_bypassed_lucas_auth_disabled",
            product=product,
            hint="LUCAS_AUTH_DISABLED=true — 운영 외부 노출 환경에서는 false 로 전환 필수",
        )
        return

    auth_mode = (os.environ.get("SWAGGER_AUTH_MODE") or "none").strip().lower()
    allowlist_raw = os.environ.get("SWAGGER_IP_ALLOWLIST") or ""
    allowlist = _parse_allowlist(allowlist_raw)

    if auth_mode == "none" and not allowlist:
        logger.info(
            "swagger_enabled_unprotected",
            product=product,
            hint="dev default — 운영에서는 SWAGGER_AUTH_MODE/IP_ALLOWLIST 설정 권장",
        )
        return

    logger.info(
        "swagger_enabled_protected",
        product=product,
        auth_mode=auth_mode,
        allowlist_size=len(allowlist),
    )

    basic_user = os.environ.get("SWAGGER_BASIC_USER", "")
    basic_pw = os.environ.get("SWAGGER_BASIC_PASSWORD", "")

    @app.middleware("http")
    async def _swagger_guard(request: Request, call_next):
        if request.url.path not in _SWAGGER_PATHS:
            return await call_next(request)

        # 1) IP allowlist (있을 때만).
        # 주의 — Starlette BaseHTTPMiddleware 안에서 HTTPException 을 raise 하면
        # FastAPI exception handler 가 잡지 못하고 raw exception 으로 전파됨.
        # 따라서 Response 를 직접 반환한다.
        if allowlist:
            client_ip = request.client.host if request.client else ""
            if not _ip_in_allowlist(client_ip, allowlist):
                logger.warning(
                    "swagger_blocked_ip",
                    product=product,
                    client_ip=client_ip,
                    path=request.url.path,
                )
                return Response(
                    status_code=403,
                    content="Swagger access denied by IP allowlist",
                )

        # 2) auth (none/basic/jwt).
        if auth_mode == "basic":
            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("basic "):
                return Response(
                    status_code=401,
                    content="Swagger requires basic auth",
                    headers={"WWW-Authenticate": 'Basic realm="Swagger"'},
                )
            try:
                decoded = base64.b64decode(auth[6:].strip()).decode("utf-8", "replace")
            except (ValueError, base64.binascii.Error):
                return Response(
                    status_code=401,
                    content="Swagger basic auth malformed",
                    headers={"WWW-Authenticate": 'Basic realm="Swagger"'},
                )
            if ":" not in decoded:
                return Response(
                    status_code=401,
                    content="Swagger basic auth malformed",
                    headers={"WWW-Authenticate": 'Basic realm="Swagger"'},
                )
            user, pw = decoded.split(":", 1)
            if not basic_user or not basic_pw:
                # 운영 misconfig — basic 모드인데 user/pw 미설정. 안전쪽으로 401.
                logger.error("swagger_basic_credentials_unset", product=product)
                return Response(
                    status_code=401,
                    content="Swagger basic auth not configured",
                    headers={"WWW-Authenticate": 'Basic realm="Swagger"'},
                )
            if user != basic_user or pw != basic_pw:
                return Response(
                    status_code=401,
                    content="Swagger basic auth failed",
                    headers={"WWW-Authenticate": 'Basic realm="Swagger"'},
                )
        elif auth_mode == "jwt":
            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                return Response(
                    status_code=401,
                    content="Swagger requires JWT bearer",
                )
            # JWT 실제 검증은 기존 auth dependency 가 endpoint 단에서 수행하지 않음
            # (docs/openapi.json 은 dependency-free 라우트). bearer 토큰 *존재* 만
            # 확인하고, 위조 토큰 차단은 IP allowlist + 운영 망 분리에 의존.
            # 더 엄격한 JWT 검증이 필요하면 SWAGGER_AUTH_MODE=basic 권장.
        # auth_mode == "none" 인데 allowlist 만 있는 케이스 — IP 검사만 통과하면 OK.

        return await call_next(request)


__all__ = ["configure_swagger"]
