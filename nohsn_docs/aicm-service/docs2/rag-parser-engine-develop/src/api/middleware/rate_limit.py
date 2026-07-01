"""Phase 13 — SlowAPI 기반 rate limit.

정책:
    - default: 분당 60/IP
    - /agent/chat: 분당 30/IP (decorator 로 별도 지정)
    - admin: 별도 무제한 (key_func 가 admin 토큰 검출 시 빈 키 반환 → bypass)

key_func 는 IP 기반.  X-Forwarded-For 헤더가 있으면 첫 번째 IP 사용 (proxy 환경).
admin 토큰은 ``Authorization: Bearer <KMS_ADMIN_TOKEN>`` 일치 시 limit bypass.

ENV:
    KMS_RATE_LIMIT_ENABLED  — "false" 면 setup_rate_limit() 가 no-op (테스트/개발용).
    KMS_RATE_LIMIT_DEFAULT  — default limit (default "60/minute")
    KMS_RATE_LIMIT_CHAT     — chat 전용 limit (default "30/minute")
    KMS_ADMIN_TOKEN         — 지정 시 일치하는 토큰은 limit bypass
"""
from __future__ import annotations

import os
from typing import Any

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def _key_func(request: Any) -> str:
    """admin 토큰 → "" (bypass), 그 외 → 원격 IP."""
    admin_token = os.environ.get("KMS_ADMIN_TOKEN")
    if admin_token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and auth[len("Bearer "):].strip() == admin_token:
            # 빈 문자열을 반환하면 slowapi 가 limit 자체를 적용하지 않는다.
            return ""

    # X-Forwarded-For 우선 (nginx/CDN proxy 뒤) → 없으면 remote_addr
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


_DEFAULT_LIMIT = os.environ.get("KMS_RATE_LIMIT_DEFAULT", "60/minute")
CHAT_LIMIT = os.environ.get("KMS_RATE_LIMIT_CHAT", "30/minute")

limiter = Limiter(
    key_func=_key_func,
    default_limits=[_DEFAULT_LIMIT],
    headers_enabled=False,   # FastAPI 가 dict 응답을 Response 로 wrap 하기 전에
                              # slowapi 가 inject 시도하다 실패함 — 비활성
)


def setup_rate_limit(app: Any) -> None:
    """FastAPI 앱에 limiter + RateLimitExceeded handler 등록.

    KMS_RATE_LIMIT_ENABLED=false 면 no-op.  테스트/개발 편의.
    """
    # 기본값 false — 운영에서만 명시적으로 KMS_RATE_LIMIT_ENABLED=true 로 활성화.
    # 테스트·개발 환경 호환성 우선.
    if os.environ.get("KMS_RATE_LIMIT_ENABLED", "false").lower() != "true":
        return

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


__all__ = ["limiter", "setup_rate_limit", "CHAT_LIMIT"]
