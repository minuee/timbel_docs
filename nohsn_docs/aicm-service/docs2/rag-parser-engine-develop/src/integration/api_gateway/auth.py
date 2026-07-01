"""FastAPI 의존성: API Key 인증 + scope 검증 + rate limiting."""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Depends, Header, HTTPException, Request, status

from src.common.constants import API_KEY_HEADER, API_KEY_PREFIX
from src.common.logging import get_logger
from src.integration.api_gateway.dependencies import get_api_key_manager, get_rate_limiter, get_usage_tracker
from src.integration.api_gateway.models import APIKeyRecord

log = get_logger(__name__)


def verify_api_key(required_scope: str) -> Callable:
    """API Key 인증 FastAPI 의존성 팩토리.

    사용법:
        @router.post("/ext/search")
        async def search(api_key: APIKeyRecord = Depends(verify_api_key("search"))):
            ...

    검증 순서:
    1. X-API-Key 헤더 존재 확인
    2. 키 포맷 검증 (aicm_ 접두사)
    3. Redis/DB에서 키 검증
    4. scope 확인
    5. rate limit 확인
    """

    async def _dependency(
        request: Request,
        x_api_key: str = Header(..., alias=API_KEY_HEADER),
        api_key_manager=Depends(get_api_key_manager),
        rate_limiter=Depends(get_rate_limiter),
        usage_tracker=Depends(get_usage_tracker),
    ) -> APIKeyRecord:
        start_time = time.time()

        # 1. 포맷 검증
        if not x_api_key.startswith(API_KEY_PREFIX):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않은 API Key 형식입니다.",
            )

        # 2. 키 검증 (Redis 캐시 → DB)
        record = await api_key_manager.verify_key(x_api_key)
        if not record:
            log.warning("api_key_auth_failed", prefix=x_api_key[:16])
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않거나 만료된 API Key입니다.",
            )

        # 3. scope 검증
        if required_scope not in record.scopes:
            log.warning(
                "api_key_scope_denied",
                key_id=str(record.id),
                required=required_scope,
                available=record.scopes,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"이 API Key에는 '{required_scope}' 권한이 없습니다.",
            )

        # 4. rate limit 검증
        endpoint = request.url.path
        rl_result = await rate_limiter.check(
            key_id=record.id,
            endpoint=endpoint,
            limit=record.rate_limit,
        )
        if not rl_result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"API 호출 제한을 초과했습니다. 한도: {record.rate_limit} req/min",
                headers={
                    "Retry-After": str(rl_result.retry_after),
                    "X-RateLimit-Limit": str(record.rate_limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # 5. 사용량 추적 (비동기, 비차단)
        latency_ms = int((time.time() - start_time) * 1000)
        try:
            await usage_tracker.track(
                key_id=record.id,
                endpoint=endpoint,
                latency_ms=latency_ms,
            )
        except Exception as e:
            log.warning("usage_tracking_failed", key_id=str(record.id), error=str(e))

        # 5b. 라이선스 일별 API 호출 카운터 증가
        try:
            from src.core.services.license_enforcer import increment_daily_counter

            await increment_daily_counter(record.tenant_id, "api_calls_today")
        except Exception as e:
            log.debug("license_api_calls_counter_failed", error=str(e))

        # rate limit 헤더를 request.state에 저장 (미들웨어에서 응답 헤더로 추가 가능)
        request.state.rate_limit_remaining = rl_result.remaining
        request.state.rate_limit_limit = record.rate_limit

        # 6. user_id / allowed_repository_ids 정보를 request.state에 저장
        # 검색/RAG 라우터에서 이 정보를 참조하여 접근 제한을 적용한다.
        request.state.api_key_user_id = record.user_id
        request.state.api_key_allowed_repository_ids = record.allowed_repository_ids

        log.info(
            "api_key_authenticated",
            key_id=str(record.id),
            tenant_id=str(record.tenant_id),
            user_id=str(record.user_id) if record.user_id else None,
            scope=required_scope,
        )
        return record

    return _dependency
