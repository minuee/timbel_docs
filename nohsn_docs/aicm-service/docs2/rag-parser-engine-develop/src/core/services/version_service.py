"""문서 버전 관리 서비스 — 소프트 교체 전략.

기존 문서를 archived로 전환하고 새 버전을 생성하는 방식으로
문서 이력을 관리한다. Qdrant 벡터도 버전에 맞게 제거/복원한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants import (
    DOC_STATUS_ACTIVE,
    DOC_STATUS_ARCHIVED,
    DOC_STATUS_PROCESSING,
)
from src.common.logging import get_logger
from src.core.exceptions import DocumentNotFoundError
from src.core.models.document import Chunk, Document
from src.core.models.repository import Repository
from src.core.services.document_service import DocumentService

logger = get_logger(__name__)


class DocumentVersion:
    """버전 이력 항목."""

    def __init__(
        self,
        document_id: uuid.UUID,
        version: int,
        status: str,
        title: str,
        created_at: datetime,
        created_by: uuid.UUID | None,
        chunk_count: int,
        source_file: str | None,
    ) -> None:
        self.document_id = document_id
        self.version = version
        self.status = status
        self.title = title
        self.created_at = created_at
        self.created_by = created_by
        self.chunk_count = chunk_count
        self.source_file = source_file


class DocumentVersionService:
    """문서 버전 관리 — 소프트 교체 전략.

    동일 제목(또는 원본 document_id 기반)으로 버전을 추적한다.
    version 컬럼과 status 컬럼을 조합하여 활성 버전을 관리한다.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._doc_svc = DocumentService(db)

    async def upload_new_version(
        self,
        doc_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        source_file: str,
        source_format: str,
        title: str | None = None,
        created_by: uuid.UUID | None = None,
        config_override: dict | None = None,
    ) -> tuple[Document, Document]:
        """새 버전을 업로드한다.

        1. 기존 문서 → status='archived', Qdrant 벡터 제거 마킹
        2. 새 문서 생성 → version=기존+1, status='processing'
        3. 파이프라인 트리거 준비 (Kafka 이벤트는 라우터에서 발행)

        Args:
            doc_id: 기존 문서 ID
            tenant_id: 테넌트 ID
            source_file: 새 파일 경로
            source_format: 파일 포맷
            title: 새 제목 (None이면 기존 제목 유지)
            created_by: 등록자 UUID
            config_override: 파이프라인 설정 오버라이드

        Returns:
            (archived_doc, new_doc) 튜플
        """
        # 기존 문서 조회
        old_doc = await self._doc_svc.get_by_id(doc_id, tenant_id=tenant_id)

        # 기존 문서 archived 전환
        old_doc.status = DOC_STATUS_ARCHIVED
        old_doc.processing_meta = {
            **old_doc.processing_meta,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "archived_reason": "new_version_uploaded",
        }

        # 기존 청크 인덱스 플래그 해제 (Qdrant 정리 대상 마킹)
        await self._mark_chunks_for_removal(old_doc.id)

        # 새 문서 생성
        new_doc = Document(
            repository_id=old_doc.repository_id,
            document_type_id=old_doc.document_type_id,
            title=title or old_doc.title,
            description=old_doc.description,
            source_file=source_file,
            source_format=source_format,
            version=old_doc.version + 1,
            status=DOC_STATUS_PROCESSING,
            processing_meta={
                "previous_version_id": str(old_doc.id),
                "previous_version": old_doc.version,
                "config_override": config_override,
            },
            created_by=created_by,
        )

        # 카테고리 복사
        if old_doc.categories:
            new_doc.categories = list(old_doc.categories)

        self.db.add(new_doc)
        await self.db.flush()

        logger.info(
            "document_new_version_created",
            old_doc_id=str(old_doc.id),
            new_doc_id=str(new_doc.id),
            old_version=old_doc.version,
            new_version=new_doc.version,
        )

        return old_doc, new_doc

    async def rollback(
        self,
        doc_id: uuid.UUID,
        target_version: int,
        *,
        tenant_id: uuid.UUID,
    ) -> tuple[Document, Document]:
        """특정 버전으로 롤백한다.

        1. 현재 active 문서 → archived
        2. target_version 문서 → active + Qdrant 벡터 재적재 마킹

        Args:
            doc_id: 현재 활성 문서 ID (또는 버전 체인의 아무 문서)
            target_version: 목표 버전 번호
            tenant_id: 테넌트 ID

        Returns:
            (archived_current, restored_doc) 튜플

        Raises:
            DocumentNotFoundError: 문서 또는 대상 버전을 찾을 수 없음
        """
        # 현재 문서 조회
        current_doc = await self._doc_svc.get_by_id(doc_id, tenant_id=tenant_id)

        # 같은 저장소, 같은 제목의 target_version 문서 찾기
        target_doc = await self._find_version(
            repository_id=current_doc.repository_id,
            title=current_doc.title,
            version=target_version,
            tenant_id=tenant_id,
        )

        if target_doc is None:
            raise DocumentNotFoundError(
                f"version={target_version} of '{current_doc.title}'"
            )

        # 현재 문서 archived
        if current_doc.status == DOC_STATUS_ACTIVE:
            current_doc.status = DOC_STATUS_ARCHIVED
            current_doc.processing_meta = {
                **current_doc.processing_meta,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "archived_reason": f"rollback_to_v{target_version}",
            }
            await self._mark_chunks_for_removal(current_doc.id)

        # 대상 문서 active 복원
        target_doc.status = DOC_STATUS_ACTIVE
        target_doc.processing_meta = {
            **target_doc.processing_meta,
            "restored_at": datetime.now(timezone.utc).isoformat(),
            "restored_from": str(current_doc.id),
        }

        # 대상 문서 청크 인덱스 복원 마킹
        await self._mark_chunks_for_reindex(target_doc.id)

        await self.db.flush()

        logger.info(
            "document_rollback",
            current_doc_id=str(current_doc.id),
            target_doc_id=str(target_doc.id),
            target_version=target_version,
        )

        return current_doc, target_doc

    async def get_version_history(
        self,
        doc_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
    ) -> list[DocumentVersion]:
        """문서의 모든 버전 이력을 반환한다.

        같은 저장소 + 같은 제목으로 그룹핑하여 버전 체인을 추적한다.

        Args:
            doc_id: 문서 ID (버전 체인의 아무 문서)
            tenant_id: 테넌트 ID

        Returns:
            버전 이력 리스트 (version 내림차순)
        """
        # 기준 문서 조회
        doc = await self._doc_svc.get_by_id(doc_id, tenant_id=tenant_id)

        # 같은 저장소 + 같은 제목의 모든 문서 조회
        stmt = (
            select(Document)
            .join(Repository)
            .where(
                Document.repository_id == doc.repository_id,
                Document.title == doc.title,
                Repository.tenant_id == tenant_id,
            )
            .order_by(Document.version.desc())
        )
        result = await self.db.execute(stmt)
        docs = list(result.scalars().all())

        # processing_meta 체인으로도 추적 (제목이 변경된 경우)
        chain_ids = {doc.id}
        for d in docs:
            prev_id = d.processing_meta.get("previous_version_id")
            if prev_id:
                chain_ids.add(uuid.UUID(prev_id))

        # 체인에 포함되지만 제목이 다른 문서도 조회
        if chain_ids - {d.id for d in docs}:
            extra_stmt = (
                select(Document)
                .where(Document.id.in_(chain_ids - {d.id for d in docs}))
            )
            extra_result = await self.db.execute(extra_stmt)
            docs.extend(extra_result.scalars().all())

        # 청크 수 조회
        chunk_counts: dict[uuid.UUID, int] = {}
        for d in docs:
            count_stmt = (
                select(Chunk.id)
                .where(Chunk.document_id == d.id)
            )
            count_result = await self.db.execute(count_stmt)
            chunk_counts[d.id] = len(list(count_result.scalars().all()))

        # 버전 이력 생성
        versions = [
            DocumentVersion(
                document_id=d.id,
                version=d.version,
                status=d.status,
                title=d.title,
                created_at=d.created_at,
                created_by=d.created_by,
                chunk_count=chunk_counts.get(d.id, 0),
                source_file=d.source_file,
            )
            for d in docs
        ]

        # 버전 내림차순 정렬 (중복 제거)
        seen: set[uuid.UUID] = set()
        unique_versions: list[DocumentVersion] = []
        for v in sorted(versions, key=lambda x: x.version, reverse=True):
            if v.document_id not in seen:
                seen.add(v.document_id)
                unique_versions.append(v)

        return unique_versions

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _find_version(
        self,
        repository_id: uuid.UUID,
        title: str,
        version: int,
        tenant_id: uuid.UUID,
    ) -> Document | None:
        """저장소/제목/버전으로 문서를 조회한다."""
        stmt = (
            select(Document)
            .join(Repository)
            .where(
                Document.repository_id == repository_id,
                Document.title == title,
                Document.version == version,
                Repository.tenant_id == tenant_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _mark_chunks_for_removal(self, document_id: uuid.UUID) -> None:
        """문서의 청크를 Qdrant 제거 대상으로 마킹한다."""
        stmt = select(Chunk).where(Chunk.document_id == document_id)
        result = await self.db.execute(stmt)
        chunks = list(result.scalars().all())

        for chunk in chunks:
            chunk.is_indexed = False

        logger.info(
            "chunks_marked_for_removal",
            document_id=str(document_id),
            chunk_count=len(chunks),
        )

    async def _mark_chunks_for_reindex(self, document_id: uuid.UUID) -> None:
        """문서의 청크를 Qdrant 재인덱싱 대상으로 마킹한다."""
        stmt = select(Chunk).where(Chunk.document_id == document_id)
        result = await self.db.execute(stmt)
        chunks = list(result.scalars().all())

        for chunk in chunks:
            chunk.is_indexed = False  # 워커가 재인덱싱 대상으로 인식

        logger.info(
            "chunks_marked_for_reindex",
            document_id=str(document_id),
            chunk_count=len(chunks),
        )
