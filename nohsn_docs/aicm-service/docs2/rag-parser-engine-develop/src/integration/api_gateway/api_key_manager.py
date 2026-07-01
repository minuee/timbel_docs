"""API Key 발급/검증/폐기/목록 관리."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.common.logging import get_logger
from src.integration.api_gateway.models import APIKeyCreateResponse, APIKeyListItem, APIKeyORM, APIKeyRecord

log = get_logger(__name__)


class APIKeyManager:
    """API Key 발급/검증/폐기/사용량 추적.

    키 구조: aicm_{tenant_slug}_{random_32chars}
    저장: PostgreSQL (SHA-256 해시) + Redis (캐시, TTL 5분)
    """

    CACHE_TTL = 300  # 5분
    CACHE_PREFIX = "aicm:apikey:"

    def __init__(self, session: AsyncSession, redis: aioredis.Redis) -> None:
        self._session = session
        self._redis = redis

    # ------------------------------------------------------------------
    # 발급
    # ------------------------------------------------------------------

    async def create_key(
        self,
        tenant_id: UUID,
        tenant_slug: str,
        name: str,
        scopes: list[str],
        rate_limit: int = 100,
        expires_at: datetime | None = None,
        user_id: UUID | None = None,
        allowed_repository_ids: list[UUID] | None = None,
    ) -> APIKeyCreateResponse:
        """API Key 발급. 원본 키는 이 시점에만 반환, 이후 해시만 저장."""
        random_part = secrets.token_urlsafe(32)
        raw_key = f"aicm_{tenant_slug}_{random_part}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:16] + "..."

        key_id = uuid4()
        orm = APIKeyORM(
            id=key_id,
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes=scopes,
            rate_limit=rate_limit,
            allowed_repository_ids=allowed_repository_ids,
            expires_at=expires_at,
        )
        self._session.add(orm)
        await self._session.flush()

        log.info("api_key_created", key_id=str(key_id), tenant_id=str(tenant_id), name=name)

        return APIKeyCreateResponse(
            api_key=raw_key,
            key_id=key_id,
            name=name,
            scopes=scopes,
            rate_limit=rate_limit,
            expires_at=expires_at,
        )

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------

    async def verify_key(self, raw_key: str) -> APIKeyRecord | None:
        """키 검증. Redis 캐시 우선, miss 시 DB 조회."""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        cache_key = f"{self.CACHE_PREFIX}{key_hash}"

        # Redis 캐시 확인
        cached = await self._redis.get(cache_key)
        if cached:
            record = APIKeyRecord.model_validate_json(cached)
        else:
            record = await self._find_by_hash(key_hash)
            if record:
                await self._redis.setex(cache_key, self.CACHE_TTL, record.model_dump_json())

        if not record or not record.is_active:
            return None

        now = datetime.now(timezone.utc)
        if record.expires_at and record.expires_at.replace(tzinfo=timezone.utc) < now:
            return None

        return record

    # ------------------------------------------------------------------
    # 폐기
    # ------------------------------------------------------------------

    async def revoke_key(self, key_id: UUID, tenant_id: UUID) -> bool:
        """키 비활성화 (소프트 삭제)."""
        stmt = (
            update(APIKeyORM)
            .where(APIKeyORM.id == key_id, APIKeyORM.tenant_id == tenant_id)
            .values(is_active=False)
            .returning(APIKeyORM.key_hash)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return False

        # 캐시 무효화
        await self._redis.delete(f"{self.CACHE_PREFIX}{row}")
        log.info("api_key_revoked", key_id=str(key_id))
        return True

    # ------------------------------------------------------------------
    # 목록
    # ------------------------------------------------------------------

    async def list_keys(self, tenant_id: UUID) -> list[APIKeyListItem]:
        """테넌트의 API Key 목록 조회."""
        stmt = (
            select(APIKeyORM)
            .where(APIKeyORM.tenant_id == tenant_id, APIKeyORM.is_active.is_(True))
            .order_by(APIKeyORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [
            APIKeyListItem(
                key_id=row.id,
                name=row.name,
                key_prefix=row.key_prefix,
                scopes=row.scopes,
                rate_limit=row.rate_limit,
                user_id=row.user_id,
                allowed_repository_ids=row.allowed_repository_ids,
                is_active=row.is_active,
                expires_at=row.expires_at,
                last_used_at=row.last_used_at,
                usage_count=row.usage_count,
                created_at=row.created_at,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 사용 시간 갱신
    # ------------------------------------------------------------------

    async def touch_last_used(self, key_id: UUID) -> None:
        """last_used_at, usage_count 갱신. Fire-and-forget으로 호출."""
        stmt = (
            update(APIKeyORM)
            .where(APIKeyORM.id == key_id)
            .values(
                last_used_at=datetime.now(timezone.utc),
                usage_count=APIKeyORM.usage_count + 1,
            )
        )
        await self._session.execute(stmt)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _find_by_hash(self, key_hash: str) -> APIKeyRecord | None:
        """DB에서 해시로 키 조회."""
        stmt = select(APIKeyORM).where(APIKeyORM.key_hash == key_hash)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return APIKeyRecord.model_validate(row)
