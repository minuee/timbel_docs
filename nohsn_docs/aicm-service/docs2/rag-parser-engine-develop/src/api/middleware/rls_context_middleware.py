"""D32 §2 — ASGI middleware: 모든 request 에 RLSContext 주입.

사용자 절칙 (2026-05-08): set_rls_context 호출 site 0 누락. middleware 가 모든
운영 path 에 RLSContext (scope/agent_id/tenant_id) 자동 등록 → SQLAlchemy
``begin`` event 가 ``SET LOCAL app.current_*`` 발행 → RLS 정책 작동.

설계 (사전 GPT-5 phase 0 GO_WITH_CHANGES R2 + 사후 GPT-5 §2 GO_WITH_CHANGES 반영):
- ``BaseHTTPMiddleware`` 대신 *순수 ASGI middleware* — 스트리밍/예외 경계에서
  contextvars 누수 방지 (BaseHTTPMiddleware 는 starlette 의 또 다른 task 로
  request 를 forwarding 하므로 contextvar set 한 task 와 endpoint 실행 task 가
  분리될 수 있음).
- 매핑 규칙 (sender → RLSScope):
  - JWT role ∈ {owner, admin, member, viewer, user} + tenant_id 유효 → scope=admin
    (JWT 의 tenant_id 강제 — cross-tenant pivot 차단).
  - 미인증 → scope='' (default-deny).
  - X-Tenant-Id 헤더 fallback: *비프로덕션 + 화이트리스트 path* 에서만 허용
    (사후 GPT-5 §2 MUST — pivoting 위험 차단).
- WebSocket 도 동일하게 RLSContext 적용 (사후 GPT-5 §2 MUST).
- coverage instrumentation: 응답 헤더 ``X-RLS-Scope`` (개발/스테이징 only).
  http.response.start 시점에 *현재* contextvar 를 읽어 dispatcher 가 agent scope 로
  전환한 경우도 헤더에 반영 (사후 GPT-5 §2 SHOULD).

contextvar reset 은 ASGI scope 종료 시 try/finally 로 보장.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.api.middleware.rls_context import (
    RLSContext,
    RLSScope,
    get_rls_context,
    reset_rls_context,
    set_rls_context,
)
from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

# 비인증 + X-Tenant-Id 헤더 fallback 허용 path (사후 GPT-5 §2 MUST).
# 운영 endpoint 는 모두 JWT 강제 — pivot 위험 0.
_HEADER_FALLBACK_WHITELIST: frozenset[str] = frozenset({"/health", "/health/ready", "/health/live"})


def _decode_jwt_payload(authorization: str | None) -> dict[str, Any] | None:
    """``Authorization: Bearer <jwt>`` 디코드. 실패 시 None."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    try:
        from src.api.auth.jwt_utils import InvalidToken, decode_token

        try:
            payload = decode_token(token)
        except InvalidToken:
            return None
    except Exception:  # noqa: BLE001 — 의존성 미설치 등.
        return None
    if payload.get("type") not in (None, "access"):
        return None
    return payload


def _safe_uuid_str(value: Any) -> str:
    """UUID 변환 가능하면 str(UUID), 아니면 빈 문자열."""
    if not value:
        return ""
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        return ""


def _build_rls_context(
    headers: dict[bytes, bytes],
    allow_header_fallback: bool = False,
) -> RLSContext:
    """ASGI scope 의 raw headers 로부터 RLSContext 빌드.

    매핑 규칙:
    - JWT 가 유효 + role ∈ {owner, admin, member, viewer, user} + tenant_id 유효 →
      admin scope (JWT.tenant_id 강제 — cross-tenant pivot 차단).
    - JWT 부재/무효:
      - allow_header_fallback=True (비프로덕션 + 화이트리스트 path) 일 때만
        X-Tenant-Id 헤더 fallback 으로 admin scope.
      - 그 외 → 빈 scope (default-deny).

    Note: agent scope 는 본 middleware 에서 *등록 X*. dispatcher (engine.turn)
    가 sender_context 기반으로 ``bind_agent_scope()`` 컨텍스트매니저로 재바인딩.
    """
    auth_header = headers.get(b"authorization", b"").decode("latin-1") or None
    tenant_header = (
        headers.get(b"x-tenant-id", b"").decode("latin-1")
        or headers.get(b"x-tenant-id".lower(), b"").decode("latin-1")
        or ""
    )

    payload = _decode_jwt_payload(auth_header)
    scope: RLSScope = ""
    agent_id: str | None = None
    tenant_id: str | None = None

    if payload:
        role_raw = (payload.get("role") or "").lower()
        tenant_id = _safe_uuid_str(payload.get("tenant_id")) or None
        # D34 §5 — JWT role=super_admin (또는 superadmin) → cross-tenant scope.
        # tenant_id 무관 (Locus 운영자 전용). 077 의 superadmin SELECT 정책 통과.
        if role_raw in ("super_admin", "superadmin"):
            scope = "superadmin"
            tenant_id = None  # cross-tenant scope — tenant 무관.
            try:
                logger.info(
                    "rls_context_superadmin_scope_assigned",
                    subject=str(payload.get("sub") or ""),
                )
            except Exception:  # noqa: BLE001
                pass
        # JWT 의 모든 정상 role 은 admin scope (tenant 자기 안 모든 row + NULL owner).
        # agent scope 는 dispatcher 가 sender_context 기반으로 별도 wrap.
        elif role_raw in ("owner", "admin", "member", "viewer", "user"):
            scope = "admin" if tenant_id else ""
    elif allow_header_fallback and tenant_header:
        # X-Tenant-Id 헤더 fallback — *비프로덕션 + 화이트리스트 path only*
        # (사후 GPT-5 §2 MUST — cross-tenant pivot 위험 차단).
        tenant_id = _safe_uuid_str(tenant_header) or None
        if tenant_id:
            scope = "admin"

    return RLSContext(agent_id=agent_id, scope=scope, tenant_id=tenant_id)


class RLSContextMiddleware:
    """순수 ASGI middleware — 매 request 에 RLSContext 등록 + 응답 헤더 instrumentation.

    개발/스테이징 (APP_ENV != 'production') 에서만 응답 헤더 ``X-RLS-Scope`` /
    ``X-RLS-Tenant-Id`` 노출. 프로덕션은 비노출 (정보 누출 방지).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        typ = scope.get("type")
        if typ not in ("http", "websocket"):
            # lifespan 등 — RLSContext 미적용 (DB 접근 없음 가정).
            await self.app(scope, receive, send)
            return

        # raw headers — list[(bytes, bytes)] → dict (lowercase key).
        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", []) or []
        header_map: dict[bytes, bytes] = {k.lower(): v for k, v in raw_headers}

        path = scope.get("path") or ""
        is_prod = (settings.APP_ENV or "").lower() == "production"
        # LUCAS_AUTH_DISABLED=True 인 dev 모드에서는 모든 경로에서 X-Tenant-Id fallback 허용.
        # 운영(prod)에서는 JWT 강제 — whitelist path 만 허용.
        allow_header_fallback = (
            settings.LUCAS_AUTH_DISABLED
            or ((not is_prod) and (path in _HEADER_FALLBACK_WHITELIST))
        )

        ctx = _build_rls_context(header_map, allow_header_fallback=allow_header_fallback)
        token = set_rls_context(ctx)

        if typ == "websocket":
            # WebSocket 도 동일 RLSContext 적용 (헤더 주입 X — WS 는 라이프사이클이
            # 다름). 사후 GPT-5 §2 MUST.
            try:
                await self.app(scope, receive, send)
            finally:
                reset_rls_context(token)
            return

        # http — 응답 헤더 instrumentation (non-prod only). dispatcher 가 agent
        # scope 로 전환한 경우도 반영하기 위해 http.response.start 시점에 *현재*
        # contextvar 를 다시 읽음 (사후 GPT-5 §2 SHOULD).
        async def _send_with_headers(message: dict) -> None:
            if not is_prod and message.get("type") == "http.response.start":
                ctx_now = get_rls_context() or ctx
                hdrs = list(message.get("headers", []) or [])
                hdrs.append((b"x-rls-scope", (ctx_now.scope or "").encode("latin-1")))
                if ctx_now.tenant_id:
                    hdrs.append(
                        (b"x-rls-tenant-id", ctx_now.tenant_id.encode("latin-1"))
                    )
                if ctx_now.agent_id:
                    hdrs.append(
                        (b"x-rls-agent-id", ctx_now.agent_id.encode("latin-1"))
                    )
                message = dict(message)
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, _send_with_headers)
        finally:
            reset_rls_context(token)


__all__ = ["RLSContextMiddleware", "_build_rls_context"]
