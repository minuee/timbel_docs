"""저장소 CRUD 서비스 + Qdrant 컬렉션 자동 생성/삭제."""

from __future__ import annotations

import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.common.constants import QDRANT_COLLECTION_PREFIX
from src.common.logging import get_logger
from src.core.exceptions import DuplicateNameError, RepositoryNotFoundError, TenantNotFoundError
from src.core.models.repository import Repository
from src.core.models.tenant import Tenant

logger = get_logger(__name__)


class RepositoryService:
    """저장소 CRUD + Qdrant 컬렉션 자동 관리 서비스."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _collection_name(tenant_slug: str, repository_id: uuid.UUID) -> str:
        """Qdrant 컬렉션 이름을 생성한다. 규칙: aicm_{tenant_slug}_{repo_id}_chunks"""
        return f"{QDRANT_COLLECTION_PREFIX}_{tenant_slug}_{repository_id}_chunks"

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        """테넌트를 조회한다."""
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.db.execute(stmt)
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise TenantNotFoundError(str(tenant_id))
        return tenant

    async def _create_qdrant_collection(self, collection_name: str) -> None:
        """Qdrant 컬렉션을 생성한다 (외부 호출, 실패 시 로그만 남김)."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import (
                Distance,
                SparseIndexParams,
                SparseVectorParams,
                VectorParams,
            )

            client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
            if not client.collection_exists(collection_name):
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        "dense": VectorParams(
                            size=1024,
                            distance=Distance.COSINE,
                            on_disk=True,
                        ),
                    },
                    sparse_vectors_config={
                        "sparse": SparseVectorParams(
                            index=SparseIndexParams(on_disk=True),
                        ),
                    },
                )
                logger.info("qdrant_collection_created", collection=collection_name)
            else:
                logger.info("qdrant_collection_exists", collection=collection_name)
        except Exception as exc:
            logger.warning(
                "qdrant_collection_create_failed",
                collection=collection_name,
                error=str(exc),
            )

    async def _delete_qdrant_collection(self, collection_name: str) -> None:
        """Qdrant 컬렉션을 삭제한다 (외부 호출, 실패 시 로그만 남김)."""
        try:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
            if client.collection_exists(collection_name):
                client.delete_collection(collection_name)
                logger.info("qdrant_collection_deleted", collection=collection_name)
        except Exception as exc:
            logger.warning(
                "qdrant_collection_delete_failed",
                collection=collection_name,
                error=str(exc),
            )

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        name: str,
        description: str | None = None,
        config: dict | None = None,
    ) -> Repository:
        """새 저장소를 생성하고 Qdrant 컬렉션을 자동 생성한다.

        Args:
            tenant_id: 소속 테넌트 ID
            name: 저장소 이름
            description: 저장소 설명
            config: 저장소별 설정 오버라이드

        Returns:
            생성된 Repository 객체

        Raises:
            TenantNotFoundError: 테넌트가 존재하지 않을 때
            DuplicateNameError: 같은 테넌트 내 동일 이름이 존재할 때
        """
        tenant = await self._get_tenant(tenant_id)

        repo = Repository(
            tenant_id=tenant_id,
            name=name,
            description=description,
            config=config or {},
        )
        self.db.add(repo)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateNameError("repository", name)

        # Qdrant 청크 컬렉션 자동 생성
        collection_name = self._collection_name(tenant.slug, repo.id)
        await self._create_qdrant_collection(collection_name)

        # Qdrant 블럭 컬렉션 자동 생성 (테넌트 단일)
        try:
            from src.core.services.qdrant_collection_manager import ensure_block_collection

            await ensure_block_collection(tenant.slug)
        except Exception as exc:
            logger.warning(
                "block_collection_auto_create_failed",
                tenant_slug=tenant.slug,
                error=str(exc),
            )

        logger.info("repository_created", repository_id=str(repo.id), name=name)
        return repo

    async def get_by_id(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> Repository:
        """ID로 저장소를 조회한다. tenant_id가 주어지면 격리 필터를 적용한다.

        Raises:
            RepositoryNotFoundError: 저장소가 존재하지 않을 때
        """
        stmt = select(Repository).where(Repository.id == repository_id)
        if tenant_id is not None:
            stmt = stmt.where(Repository.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        repo = result.scalar_one_or_none()
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))
        return repo

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Repository]:
        """테넌트의 저장소 목록을 조회한다."""
        stmt = (
            select(Repository)
            .where(Repository.tenant_id == tenant_id)
            .order_by(Repository.created_at.desc())
        )
        if is_active is not None:
            stmt = stmt.where(Repository.is_active == is_active)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        config: dict | None = None,
        is_active: bool | None = None,
    ) -> Repository:
        """저장소 정보를 수정한다.

        Raises:
            RepositoryNotFoundError: 저장소가 존재하지 않을 때
            DuplicateNameError: 같은 테넌트 내 동일 이름이 존재할 때
        """
        repo = await self.get_by_id(repository_id, tenant_id=tenant_id)

        if name is not None:
            repo.name = name
        if description is not None:
            repo.description = description
        if config is not None:
            repo.config = config
        if is_active is not None:
            repo.is_active = is_active

        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateNameError("repository", name or repo.name)

        logger.info("repository_updated", repository_id=str(repository_id))
        return repo

    async def delete(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        hard: bool = False,
    ) -> None:
        """저장소를 삭제한다 (기본 soft delete).

        hard=True 시 Qdrant 컬렉션도 삭제한다.

        Raises:
            RepositoryNotFoundError: 저장소가 존재하지 않을 때
        """
        repo = await self.get_by_id(repository_id, tenant_id=tenant_id)

        if hard:
            tenant = await self._get_tenant(tenant_id)
            collection_name = self._collection_name(tenant.slug, repo.id)
            await self._delete_qdrant_collection(collection_name)
            await self.db.delete(repo)
        else:
            repo.is_active = False

        await self.db.flush()
        logger.info(
            "repository_deleted",
            repository_id=str(repository_id),
            hard=hard,
        )

    async def count(self, tenant_id: uuid.UUID, *, is_active: bool | None = None) -> int:
        """테넌트 내 저장소 수를 반환한다."""
        stmt = select(sa_func.count(Repository.id)).where(Repository.tenant_id == tenant_id)
        if is_active is not None:
            stmt = stmt.where(Repository.is_active == is_active)
        result = await self.db.execute(stmt)
        return result.scalar_one()
