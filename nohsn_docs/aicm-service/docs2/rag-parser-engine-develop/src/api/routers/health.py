"""헬스체크 엔드포인트 — liveness & readiness probes.

- GET /health/live  — 프로세스가 살아있으면 200 (즉시 응답)
- GET /health/ready — DB, Redis, Qdrant, Elasticsearch 연결 확인 후 200 (실패 시 503)
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.common.config import settings
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["시스템"])


# ---------------------------------------------------------------------------
# Liveness — 프로세스 살아있는지만 확인
# ---------------------------------------------------------------------------

@router.get("/live")
async def liveness() -> dict[str, str]:
    """프로세스 생존 확인. 항상 200."""
    return {"status": "alive"}


# ---------------------------------------------------------------------------
# Readiness — 외부 의존성 연결 상태 확인
# ---------------------------------------------------------------------------

async def _check_postgres() -> dict[str, Any]:
    """PostgreSQL 연결 확인."""
    try:
        from src.core.database import engine
        from sqlalchemy import text

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_redis() -> dict[str, Any]:
    """Redis 연결 확인."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
        try:
            await client.ping()
            return {"status": "ok"}
        finally:
            await client.aclose()
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_qdrant() -> dict[str, Any]:
    """Qdrant 연결 확인."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.QDRANT_URL}/collections")
            if resp.status_code == 200:
                return {"status": "ok"}
            return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_elasticsearch() -> dict[str, Any]:
    """Elasticsearch 연결 확인."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ELASTICSEARCH_URL}/_cluster/health")
            if resp.status_code == 200:
                return {"status": "ok"}
            return {"status": "error", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@router.get("/ready")
async def readiness() -> JSONResponse:
    """외부 의존성 연결 확인. 모두 정상이면 200, 하나라도 실패하면 503."""
    checks = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_qdrant(),
        _check_elasticsearch(),
        return_exceptions=True,
    )

    names = ["postgres", "redis", "qdrant", "elasticsearch"]
    results: dict[str, Any] = {}
    all_ok = True

    for name, result in zip(names, checks):
        if isinstance(result, Exception):
            results[name] = {"status": "error", "detail": str(result)}
            all_ok = False
        else:
            results[name] = result
            if result.get("status") != "ok":
                all_ok = False

    status_code = 200 if all_ok else 503
    body = {
        "status": "ready" if all_ok else "not_ready",
        "checks": results,
    }

    if not all_ok:
        logger.warning("readiness_check_failed", checks=results)

    return JSONResponse(status_code=status_code, content=body)
