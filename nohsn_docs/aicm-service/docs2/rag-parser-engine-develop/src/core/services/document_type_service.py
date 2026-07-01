"""문서타입 CRUD 서비스 + 시스템 기본 타입 시드."""

from __future__ import annotations

import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.core.exceptions import DocumentTypeNotFoundError, DuplicateNameError
from src.core.models.document_type import SYSTEM_DOCUMENT_TYPES, DocumentType

logger = get_logger(__name__)


class DocumentTypeService:
    """문서타입 CRUD + 시스템 기본 타입 시드 서비스."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def seed_system_types(self, tenant_id: uuid.UUID) -> list[DocumentType]:
        """테넌트에 시스템 기본 문서타입을 시드한다.

        이미 존재하는 타입은 건너뛴다.

        Args:
            tenant_id: 대상 테넌트 ID

        Returns:
            생성된 (또는 기존) DocumentType 목록
        """
        created: list[DocumentType] = []

        for seed in SYSTEM_DOCUMENT_TYPES:
            stmt = select(DocumentType).where(
                DocumentType.tenant_id == tenant_id,
                DocumentType.name == seed["name"],
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is not None:
                created.append(existing)
                continue

            doc_type = DocumentType(
                tenant_id=tenant_id,
                name=str(seed["name"]),
                description=str(seed.get("description", "")),
                icon=str(seed.get("icon", "")),
                is_system=bool(seed.get("is_system", True)),
            )
            self.db.add(doc_type)
            created.append(doc_type)

        await self.db.flush()
        logger.info(
            "system_document_types_seeded",
            tenant_id=str(tenant_id),
            count=len(created),
        )
        return created

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        name: str,
        description: str | None = None,
        icon: str | None = None,
        is_system: bool = False,
    ) -> DocumentType:
        """새 문서타입을 생성한다.

        Raises:
            DuplicateNameError: 같은 테넌트 내 동일 이름이 존재할 때
        """
        doc_type = DocumentType(
            tenant_id=tenant_id,
            name=name,
            description=description,
            icon=icon,
            is_system=is_system,
        )
        self.db.add(doc_type)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateNameError("document_type", name)

        logger.info("document_type_created", document_type_id=str(doc_type.id), name=name)
        return doc_type

    async def get_by_id(
        self,
        document_type_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> DocumentType:
        """ID로 문서타입을 조회한다.

        Raises:
            DocumentTypeNotFoundError: 문서타입이 존재하지 않을 때
        """
        stmt = select(DocumentType).where(DocumentType.id == document_type_id)
        if tenant_id is not None:
            stmt = stmt.where(DocumentType.tenant_id == tenant_id)
        result = await self.db.execute(stmt)
        doc_type = result.scalar_one_or_none()
        if doc_type is None:
            raise DocumentTypeNotFoundError(str(document_type_id))
        return doc_type

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        is_system: bool | None = None,
    ) -> list[DocumentType]:
        """테넌트의 문서타입 목록을 조회한다.

        Args:
            tenant_id: 테넌트 ID
            is_system: 시스템 타입 필터 (None이면 전체)
        """
        stmt = (
            select(DocumentType)
            .where(DocumentType.tenant_id == tenant_id)
            .order_by(DocumentType.is_system.desc(), DocumentType.name)
        )
        if is_system is not None:
            stmt = stmt.where(DocumentType.is_system == is_system)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        document_type_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
    ) -> DocumentType:
        """문서타입 정보를 수정한다. 시스템 타입의 이름은 변경할 수 없다.

        Raises:
            DocumentTypeNotFoundError: 문서타입이 존재하지 않을 때
            DuplicateNameError: 동일 이름이 존재할 때
        """
        doc_type = await self.get_by_id(document_type_id, tenant_id=tenant_id)

        if name is not None and not doc_type.is_system:
            doc_type.name = name
        if description is not None:
            doc_type.description = description
        if icon is not None:
            doc_type.icon = icon

        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateNameError("document_type", name or doc_type.name)

        logger.info("document_type_updated", document_type_id=str(document_type_id))
        return doc_type

    async def delete(
        self,
        document_type_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
    ) -> None:
        """문서타입을 삭제한다. 시스템 타입은 삭제할 수 없다.

        Raises:
            DocumentTypeNotFoundError: 문서타입이 존재하지 않을 때
        """
        doc_type = await self.get_by_id(document_type_id, tenant_id=tenant_id)

        if doc_type.is_system:
            logger.warning(
                "system_document_type_delete_blocked",
                document_type_id=str(document_type_id),
            )
            return

        await self.db.delete(doc_type)
        await self.db.flush()
        logger.info("document_type_deleted", document_type_id=str(document_type_id))
