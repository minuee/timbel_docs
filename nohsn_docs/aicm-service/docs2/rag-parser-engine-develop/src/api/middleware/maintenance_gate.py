"""D31d-E v2 §1 — 유지보수 게이트 (#218).

ASGI 레벨 미들웨어 — RAG 호출 path 를 *읽기 차단* 하는 안전 가드.

설계 (사전 GPT-5 phase 0 v1+v2+v3 GO 반영):
- Pure ASGI middleware — scope.type ∈ {http, websocket} 둘 다 차단.
  - http: 503 + body (`Cache-Control: no-store`, `Retry-After`).
  - websocket: close code `1013` (Try Again Later).
- env `MAINTENANCE_MODE`:
  - `off` (default): pass-through.
  - `on`: deny path prefix 매칭 시 차단.
- env `MAINTENANCE_GATE_PATHS` — comma 분리 prefix list (default 아래).
- env `MAINTENANCE_GATE_EXEMPT` — comma 분리 prefix list (default 아래).
  - exempt 가 deny 보다 우선.
- OPTIONS / HEAD 메서드는 통과 (CORS preflight 보호).

Metrics (kms_*):
- `kms_maintenance_gate_on` (Gauge, 0|1) — env on 일 때 1.
- `kms_maintenance_blocked_requests_total{path,proto,status_code}` (Counter).

비파괴 원칙: env off 시 미들웨어는 *완전 pass-through*. import 부작용 없음.
"""
from __future__ import annotations

import json
import os
from typing import Any

from src.common.logging import get_logger

logger = get_logger(__name__)

# 기본 deny prefix 리스트 — GPT-5 phase 0 v1 보완 반영 (확장 + 누락 방지).
_DEFAULT_DENY = (
    "/api/v1/search,"
    "/api/v1/search/,"
    "/api/v1/rag,"
    "/api/v1/rag/,"
    "/api/v1/answers,"
    "/api/v1/agents,"
    "/api/v1/agents/,"
    "/api/v1/external/agent,"
    "/api/v1/external/agent/,"
    "/api/v1/ask,"
    "/agent/chat"
)

# 기본 exempt prefix 리스트 — health/metrics/docs 항상 살아 있어야 함.
_DEFAULT_EXEMPT = "/health,/metrics,/docs,/openapi.json,/redoc"

# 차단 응답 body 한국어.
_MAINTENANCE_BODY = {
    "success": False,
    "data": None,
    "error": {
        "code": "MAINTENANCE",
        "message": "유지보수 중입니다. 잠시 후 다시 시도해 주세요.",
    },
}

# WebSocket close code: 1013 = Try Again Later (RFC 6455 정의 외 — IANA 등록).
_WS_CLOSE_CODE_TRY_AGAIN_LATER = 1013

# OPTIONS / HEAD 는 차단 X (CORS preflight + health probe 호환).
_PASS_METHODS: frozenset[str] = frozenset({"OPTIONS", "HEAD"})


def _split_csv(env_value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (env_value or "").split(",") if p.strip())


def _is_enabled() -> bool:
    return (os.environ.get("MAINTENANCE_MODE", "off") or "off").strip().lower() == "on"


def _get_deny_prefixes() -> tuple[str, ...]:
    return _split_csv(os.environ.get("MAINTENANCE_GATE_PATHS", _DEFAULT_DENY))


def _get_exempt_prefixes() -> tuple[str, ...]:
    return _split_csv(os.environ.get("MAINTENANCE_GATE_EXEMPT", _DEFAULT_EXEMPT))


def _path_matches(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(p) for p in prefixes)


def _is_deny_default() -> bool:
    """env MAINTENANCE_GATE_DENY_DEFAULT — true 시 'exempt 외 모두 차단'."""
    return (os.environ.get("MAINTENANCE_GATE_DENY_DEFAULT", "false") or "false").strip().lower() == "true"


def _should_block(path: str) -> bool:
    if not _is_enabled():
        return False
    # exempt 가 deny 보다 우선.
    if _path_matches(path, _get_exempt_prefixes()):
        return False
    if _is_deny_default():
        # exempt 미일치 → 차단 (모든 path).
        return True
    return _path_matches(path, _get_deny_prefixes())


def _emit_gate_state_metric() -> None:
    """env 상태 → Gauge 갱신 (best-effort)."""
    try:
        from src.common.metrics import set_maintenance_gate

        set_maintenance_gate(_is_enabled())
    except Exception:  # noqa: BLE001
        pass


def _inc_blocked_metric(path: str, proto: str, status_code: str) -> None:
    try:
        from src.common.metrics import inc_maintenance_blocked

        inc_maintenance_blocked(path=path, proto=proto, status_code=status_code)
    except Exception:  # noqa: BLE001
        pass


class MaintenanceGateMiddleware:
    """순수 ASGI middleware — env on 시 RAG 호출 경로 503/1013 차단.

    LIFO middleware 스택의 *가장 외곽* (첫 add) 으로 등록 권장 — 다른 미들웨어
    부작용 (RLS context, security headers 등) 발생 전에 차단.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        # import 시점 최초 한 번 gauge 등록 — 이후 toggle_gate.sh 가 process restart
        # 시점에 갱신.
        _emit_gate_state_metric()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        typ = scope.get("type")
        if typ not in ("http", "websocket"):
            # lifespan 등 — pass-through.
            await self.app(scope, receive, send)
            return

        # env off → 즉시 통과 (오버헤드 최소화).
        if not _is_enabled():
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        method = (scope.get("method") or "").upper()

        # CORS preflight / probe — 통과.
        if typ == "http" and method in _PASS_METHODS:
            await self.app(scope, receive, send)
            return

        if not _should_block(path):
            await self.app(scope, receive, send)
            return

        # 차단 경로 — proto 별 처리.
        if typ == "http":
            await self._send_503(send, path)
            _inc_blocked_metric(path=path, proto="http", status_code="503")
            try:
                logger.info("maintenance_gate_block_http", path=path)
            except Exception:  # noqa: BLE001
                pass
            return

        # websocket — GPT-5 phase 1 사후 v1 보완: 첫 이벤트 수신 후 close 전송.
        await self._close_ws(receive, send, path)
        _inc_blocked_metric(path=path, proto="ws", status_code="1013")
        try:
            logger.info("maintenance_gate_block_ws", path=path)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    async def _send_503(send: Any, path: str) -> None:
        body = json.dumps(_MAINTENANCE_BODY, ensure_ascii=False).encode("utf-8")
        retry_after = os.environ.get("MAINTENANCE_RETRY_AFTER", "600")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("latin-1")),
            (b"retry-after", retry_after.encode("latin-1")),
            (b"cache-control", b"no-store"),
        ]
        await send({"type": "http.response.start", "status": 503, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})

    @staticmethod
    async def _close_ws(receive: Any, send: Any, path: str) -> None:
        """WS 핸드셰이크 안정 처리 — 첫 connect 이벤트 수신 후 close.

        GPT-5 phase 1 사후 v1 보완 (2026-05-10):
        일부 ASGI 서버는 accept/close 수순 없이 즉시 send(websocket.close) 호출 시
        log noise 또는 protocol error 발생. 첫 이벤트 (websocket.connect) 를 수신
        한 후 close 로 통일. accept 는 하지 않음 (정책 차단 의도 분명).
        """
        try:
            event = await receive()
            if (event or {}).get("type") != "websocket.connect":
                # 비정상 — 그래도 close 시도.
                pass
        except Exception:  # noqa: BLE001
            # receive 실패해도 close 시도.
            pass
        await send(
            {
                "type": "websocket.close",
                "code": _WS_CLOSE_CODE_TRY_AGAIN_LATER,
                "reason": "maintenance",
            }
        )


__all__ = [
    "MaintenanceGateMiddleware",
    "_should_block",  # 테스트 도우미.
    "_is_enabled",
]
