"""ParseResult 캐시 -- 다운스트림 워커의 재파싱을 방지한다.

저장 계층:
1. Redis (PARSE_RESULT_TTL=600초) -- 빠른 접근
2. MinIO intermediate -- 내구성 (Redis 미스 시)
3. 재파싱 fallback -- 캐시 전체 미스 시
"""

from __future__ import annotations

from uuid import UUID

from src.common.logging import get_logger
from src.pipeline.models.parse_result import ParseResult

log = get_logger(__name__)

# Redis TTL (초)
_PARSE_RESULT_TTL = 600  # 10분 -- 파이프라인 처리 완료에 충분


async def cache_parse_result(document_id: UUID, parse_result: ParseResult) -> None:
    """ParseResult를 캐시에 저장한다."""
    data = parse_result.model_dump_json()

    # 1. Redis
    try:
        import redis.asyncio as aioredis

        from src.common.config import settings

        r = aioredis.from_url(settings.REDIS_URL)
        key = f"aicm:parse_result:{document_id}"
        await r.set(key, data, ex=_PARSE_RESULT_TTL)
        await r.aclose()
        log.debug("parse_result_cached_redis", document_id=str(document_id))
        return
    except Exception as exc:
        log.debug("redis_cache_failed", error=str(exc))

    # 2. MinIO fallback
    try:
        from src.pipeline.storage.config import StorageConfig
        from src.pipeline.storage.object_store import ObjectStore

        config = StorageConfig()
        store = ObjectStore(
            endpoint=config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
        )
        await store.init()
        await store.save_intermediate(str(document_id), "parsed", parse_result.model_dump())
        log.debug("parse_result_cached_minio", document_id=str(document_id))
    except Exception as exc:
        log.debug("minio_cache_failed", error=str(exc))


async def load_parse_result(document_id: UUID) -> ParseResult | None:
    """캐시에서 ParseResult를 로드한다. 없으면 None."""
    # 1. Redis
    try:
        import redis.asyncio as aioredis

        from src.common.config import settings

        r = aioredis.from_url(settings.REDIS_URL)
        key = f"aicm:parse_result:{document_id}"
        data = await r.get(key)
        await r.aclose()
        if data:
            result = ParseResult.model_validate_json(data)
            log.debug("parse_result_loaded_redis", document_id=str(document_id))
            return result
    except Exception as exc:
        log.debug("redis_load_failed", error=str(exc))

    # 2. MinIO fallback
    try:
        from src.pipeline.storage.config import StorageConfig
        from src.pipeline.storage.object_store import ObjectStore

        config = StorageConfig()
        store = ObjectStore(
            endpoint=config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
        )
        await store.init()
        data = await store.load_intermediate(str(document_id), "parsed")
        if data:
            result = ParseResult.model_validate(data)
            log.debug("parse_result_loaded_minio", document_id=str(document_id))
            return result
    except Exception as exc:
        log.debug("minio_load_failed", error=str(exc))

    return None
