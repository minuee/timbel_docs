"""LLM fallback 메트릭 요약 API.

Task 31 — `/api/v1/metrics/llm` 엔드포인트.

Grafana / 수동 운영 용도로 Redis 에 누적된 최근 통계(24h 윈도우 내 incr)와
circuit breaker 상태를 JSON 으로 반환한다.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.schemas.common import ApiResponse
from src.common.llm.metrics import _compute_digest_payload
from src.common.llm.router import llm_router
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get(
    "/llm",
    response_model=ApiResponse[dict],
    summary="LLM 엔드포인트 상태 & 폴백 통계",
)
async def get_llm_metrics() -> ApiResponse[dict]:
    """LLM 엔드포인트별 success/fail, circuit breaker 상태, 폴백 digest 요약.

    - endpoints: 엔드포인트별 전체 누적 통계 (Redis 7일 TTL).
    - digest: primary_success_rate / fallbacks_served_count / endpoints_status.
    """
    stats = await llm_router.get_provider_stats()
    digest = await _compute_digest_payload()
    return ApiResponse(
        data={"endpoints": stats.get("endpoints", {}), "digest": digest},
    )
