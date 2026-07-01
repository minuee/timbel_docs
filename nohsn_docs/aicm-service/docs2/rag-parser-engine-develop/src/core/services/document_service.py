"""문서 CRUD 서비스 + 상태 전이 + 파이프라인 메타데이터 관리."""

from __future__ import annotations

import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants import (
    DOC_STATUS_ACTIVE,
    DOC_STATUS_ARCHIVED,
    DOC_STATUS_DRAFT,
    DOC_STATUS_FAILED,
    DOC_STATUS_PENDING_REVIEW,
    DOC_STATUS_PROCESSING,
)
from src.common.logging import get_logger
from src.core.exceptions import (
    DocumentNotFoundError,
    InvalidDocumentStatusTransitionError,
    RepositoryNotFoundError,
)
from src.core.models.category import Category
from src.core.models.document import Document, document_categories
from src.core.models.repository import Repository

logger = get_logger(__name__)


async def _sync_index_payload(db: AsyncSession, document_id: uuid.UUID, new_status: str) -> None:
    """인덱스 payload(Qdrant/ES) 의 document_status 를 새 상태로 동기화. 실패해도 무시."""
    try:
        from src.search.payload_sync import sync_document_status

        await sync_document_status(document_id, new_status, db)
    except Exception as exc:
        logger.warning(
            "document_service_payload_sync_failed",
            document_id=str(document_id),
            new_status=new_status,
            error=str(exc),
        )


# 허용되는 상태 전이 맵
# 정책: 파이프라인이 끝나 pending_review 가 되기 전까지는 active 로 전환 금지.
# 처리 중 활성화를 허용하면 embed_worker upsert 가 payload=processing 으로 덮어
# 결과적으로 검색 0건 되는 버그가 재현됨.
VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    DOC_STATUS_DRAFT: {DOC_STATUS_PROCESSING, DOC_STATUS_ARCHIVED},
    # processing 중에도 사용자가 취소/삭제할 수 있도록 archived 만 허용
    DOC_STATUS_PROCESSING: {DOC_STATUS_FAILED, DOC_STATUS_PENDING_REVIEW, DOC_STATUS_ARCHIVED},
    DOC_STATUS_PENDING_REVIEW: {DOC_STATUS_ACTIVE, DOC_STATUS_FAILED, DOC_STATUS_ARCHIVED, DOC_STATUS_PROCESSING},
    DOC_STATUS_ACTIVE: {DOC_STATUS_ARCHIVED, DOC_STATUS_PROCESSING, DOC_STATUS_PENDING_REVIEW},
    DOC_STATUS_FAILED: {DOC_STATUS_PROCESSING, DOC_STATUS_ARCHIVED},
    DOC_STATUS_ARCHIVED: {DOC_STATUS_DRAFT},
}


class DocumentService:
    """문서 CRUD + 상태 전이 + 파이프라인 메타데이터 관리 서비스."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _validate_repository(
        self,
        repository_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Repository:
        """저장소 존재 및 테넌트 소속 검증."""
        logger.debug(
            "validate_repository",
            repository_id=str(repository_id),
            tenant_id=str(tenant_id),
        )
        stmt = select(Repository).where(
            Repository.id == repository_id,
            Repository.tenant_id == tenant_id,
        )
        result = await self.db.execute(stmt)
        repo = result.scalar_one_or_none()
        if repo is None:
            logger.warning(
                "validate_repository_not_found",
                repository_id=str(repository_id),
                tenant_id=str(tenant_id),
            )
            raise RepositoryNotFoundError(str(repository_id))
        return repo

    def _validate_status_transition(self, current: str, target: str) -> None:
        """문서 상태 전이 유효성을 검증한다."""
        allowed = VALID_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidDocumentStatusTransitionError(current, target)

    async def create(
        self,
        *,
        repository_id: uuid.UUID,
        tenant_id: uuid.UUID,
        title: str,
        description: str | None = None,
        document_type_id: uuid.UUID | None = None,
        source_file: str | None = None,
        source_format: str | None = None,
        created_by: uuid.UUID | None = None,
        category_ids: list[uuid.UUID] | None = None,
        document_id: uuid.UUID | None = None,
    ) -> Document:
        """새 문서를 생성한다.

        Args:
            repository_id: 소속 저장소 ID
            tenant_id: 테넌트 ID (저장소 소속 검증용)
            title: 문서 제목
            description: 문서 설명
            document_type_id: 문서타입 ID
            source_file: 원본 파일 경로
            source_format: 원본 포맷
            created_by: 등록자 UUID
            category_ids: 연결할 카테고리 ID 목록
            document_id: 강제할 문서 ID(외부 id 통일용). None 이면 모델 기본 uuid4 생성.

        Returns:
            생성된 Document 객체
        """
        await self._validate_repository(repository_id, tenant_id)

        document = Document(
            **({"id": document_id} if document_id is not None else {}),
            repository_id=repository_id,
            tenant_id=tenant_id,
            document_type_id=document_type_id,
            title=title,
            description=description,
            source_file=source_file,
            source_format=source_format,
            created_by=created_by,
            status=DOC_STATUS_DRAFT,
        )

        # 카테고리 N:M 매핑
        if category_ids:
            stmt = select(Category).where(Category.id.in_(category_ids))
            result = await self.db.execute(stmt)
            categories = list(result.scalars().all())
            document.categories = categories

        self.db.add(document)
        await self.db.flush()

        logger.info(
            "document_created",
            document_id=str(document.id),
            title=title,
            repository_id=str(repository_id),
        )
        return document

    async def get_by_id(
        self,
        document_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> Document:
        """ID로 문서를 조회한다. tenant_id가 주어지면 저장소를 통해 격리 필터를 적용한다.

        Raises:
            DocumentNotFoundError: 문서가 존재하지 않을 때
        """
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Document)
            .options(selectinload(Document.repository))
            .where(Document.id == document_id)
        )

        if tenant_id is not None:
            stmt = stmt.join(Repository).where(Repository.tenant_id == tenant_id)

        result = await self.db.execute(stmt)
        document = result.scalar_one_or_none()
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        return document

    async def list_by_repository(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
        category_id: uuid.UUID | None = None,
        document_type_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Document]:
        """저장소의 문서 목록을 조회한다.

        Args:
            repository_id: 저장소 ID
            tenant_id: 테넌트 ID (격리 검증)
            status: 상태 필터
            category_id: 카테고리 필터
            document_type_id: 문서타입 필터
            offset: 페이지네이션 오프셋
            limit: 페이지네이션 크기
        """
        await self._validate_repository(repository_id, tenant_id)

        from sqlalchemy.orm import selectinload

        stmt = (
            select(Document)
            .options(selectinload(Document.repository))
            .where(Document.repository_id == repository_id)
            .order_by(Document.created_at.desc())
        )

        if status is not None:
            stmt = stmt.where(Document.status == status)
        else:
            # 기본값: archived(소프트 삭제) 제외
            stmt = stmt.where(Document.status != DOC_STATUS_ARCHIVED)
        if document_type_id is not None:
            stmt = stmt.where(Document.document_type_id == document_type_id)
        if category_id is not None:
            stmt = stmt.join(document_categories).where(
                document_categories.c.category_id == category_id
            )

        stmt = stmt.offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_repository(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
        category_id: uuid.UUID | None = None,
        document_type_id: uuid.UUID | None = None,
    ) -> int:
        """저장소의 문서 총 건수를 반환한다."""
        from sqlalchemy import func as sa_func

        await self._validate_repository(repository_id, tenant_id)

        stmt = select(sa_func.count()).select_from(Document).where(
            Document.repository_id == repository_id
        )
        if status is not None:
            stmt = stmt.where(Document.status == status)
        else:
            # 기본값: archived(소프트 삭제) 제외
            stmt = stmt.where(Document.status != DOC_STATUS_ARCHIVED)
        if document_type_id is not None:
            stmt = stmt.where(Document.document_type_id == document_type_id)
        if category_id is not None:
            stmt = stmt.join(document_categories).where(
                document_categories.c.category_id == category_id
            )

        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def update(
        self,
        document_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        title: str | None = None,
        description: str | None = None,
        document_type_id: uuid.UUID | None = None,
        category_ids: list[uuid.UUID] | None = None,
        is_sop: bool | None = None,
    ) -> Document:
        """문서 메타데이터를 수정한다.

        is_sop (alembic 068) — None 이면 변경 없음. True/False 변경 시 *즉시*
        kms_sop.search 의 SOP 풀에 반영 (벡터 인덱스 재빌드 불필요 — kms_sop 는
        SQL 직접 조회).

        Raises:
            DocumentNotFoundError: 문서가 존재하지 않을 때
        """
        document = await self.get_by_id(document_id, tenant_id=tenant_id)

        title_changed = title is not None and title != document.title

        if title is not None:
            document.title = title
        if description is not None:
            document.description = description
        if document_type_id is not None:
            document.document_type_id = document_type_id
        if is_sop is not None:
            document.is_sop = is_sop

        if category_ids is not None:
            stmt = select(Category).where(Category.id.in_(category_ids))
            result = await self.db.execute(stmt)
            categories = list(result.scalars().all())
            document.categories = categories

        await self.db.flush()

        # flush 직후 server_default + onupdate 컬럼 (updated_at) 은 만료 (expired)
        # 상태가 되어, 동기 컨텍스트(예: pydantic model_validate 의 from_attributes)
        # 에서 접근 시 MissingGreenlet 에러 발생. 명시적 refresh 로 attached
        # 상태에서 lazy load 처리. (alembic 068 — is_sop 토글 PR 발견 fix.)
        await self.db.refresh(document, attribute_names=["updated_at"])

        # 검색 인덱스(Qdrant/ES) payload 의 document_title 도 동기화.
        # status 와 달리 title 은 검색 결과 UI 에 노출되는 단순 표시 필드(필터 X)
        # 라서 실패해도 검색 자체엔 영향 없음. 실패 마킹 생략, 로그만.
        if title_changed and title is not None:
            try:
                from src.search.payload_sync import sync_document_title

                await sync_document_title(document_id, title, self.db)
            except Exception as exc:
                logger.warning(
                    "document_title_payload_sync_failed",
                    document_id=str(document_id),
                    error=str(exc),
                )

        logger.info("document_updated", document_id=str(document_id))
        return document

    async def transition_status(
        self,
        document_id: uuid.UUID,
        *,
        target_status: str,
        tenant_id: uuid.UUID | None = None,
        processing_meta: dict | None = None,
    ) -> Document:
        """문서 상태를 전이한다. 유효하지 않은 전이는 예외를 발생시킨다.

        Args:
            document_id: 문서 ID
            target_status: 목표 상태
            tenant_id: 테넌트 ID (격리 검증, 선택)
            processing_meta: 파이프라인 처리 메타 (병합)

        Returns:
            상태가 전이된 Document 객체

        Raises:
            DocumentNotFoundError: 문서가 존재하지 않을 때
            InvalidDocumentStatusTransitionError: 유효하지 않은 상태 전이
        """
        document = await self.get_by_id(document_id, tenant_id=tenant_id)
        self._validate_status_transition(document.status, target_status)

        document.status = target_status

        if processing_meta is not None:
            merged = {**document.processing_meta, **processing_meta}
            document.processing_meta = merged

        await self.db.flush()
        logger.info(
            "document_status_transitioned",
            document_id=str(document_id),
            new_status=target_status,
        )
        await _sync_index_payload(self.db, document_id, target_status)
        return document

    async def atomic_inc_retry_count(
        self,
        document_id: uuid.UUID,
        *,
        expected: int,
    ) -> int | None:
        """processing_meta.retry_count 를 expected 일 때만 +1 (CAS).

        spec §3.5 — DLQ auto-retry 의 publish 직전 원자적 선점. publish 성공
        후 worker crash 시 retry_count 가 inc 안 되어 무한 auto-retry 가 되는
        race window 차단. UPDATE ... RETURNING 한 statement 로 read+write+return
        을 묶어 두 시도가 동시에 expected=0 으로 들어와도 한쪽만 성공.

        Args:
            document_id: 대상 문서 UUID.
            expected: 현재 retry_count 가 이 값일 때만 +1.

        Returns:
            성공 시 새 retry_count (정수).
            CAS 실패 (다른 시도가 이미 inc) / 문서 부재 / status mismatch
            등으로 row 가 안 잡히면 ``None``.
        """
        from sqlalchemy import text as sa_text

        stmt = sa_text("""
            UPDATE documents
            SET processing_meta = jsonb_set(
                COALESCE(processing_meta, '{}'::jsonb),
                '{retry_count}',
                to_jsonb(COALESCE(
                    (processing_meta->>'retry_count')::int, 0
                ) + 1)
            ),
            updated_at = NOW()
            WHERE id = :doc_id
              AND COALESCE(
                  (processing_meta->>'retry_count')::int, 0
              ) = :expected
            RETURNING (processing_meta->>'retry_count')::int AS new_count
        """)
        result = await self.db.execute(
            stmt, {"doc_id": document_id, "expected": expected}
        )
        row = result.first()
        if row is None:
            return None
        await self.db.commit()
        return int(row[0])

    async def update_processing_meta(
        self,
        document_id: uuid.UUID,
        *,
        processing_meta: dict,
        tenant_id: uuid.UUID | None = None,
    ) -> Document:
        """파이프라인 처리 메타데이터를 업데이트한다 (기존 데이터와 병합).

        Args:
            document_id: 문서 ID
            processing_meta: 병합할 메타데이터
            tenant_id: 테넌트 ID (격리 검증, 선택)
        """
        document = await self.get_by_id(document_id, tenant_id=tenant_id)
        merged = {**document.processing_meta, **processing_meta}
        document.processing_meta = merged
        await self.db.flush()

        logger.info(
            "document_processing_meta_updated",
            document_id=str(document_id),
            keys=list(processing_meta.keys()),
        )
        return document

    async def delete(
        self,
        document_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
    ) -> None:
        """문서를 archived 상태로 전이한다 (소프트 삭제).

        Raises:
            DocumentNotFoundError: 문서가 존재하지 않을 때
        """
        document = await self.get_by_id(document_id, tenant_id=tenant_id)
        if document.status != DOC_STATUS_ARCHIVED:
            allowed = VALID_STATUS_TRANSITIONS.get(document.status, set())
            if DOC_STATUS_ARCHIVED in allowed:
                document.status = DOC_STATUS_ARCHIVED
                await self.db.flush()
                logger.info("document_archived", document_id=str(document_id))
                await _sync_index_payload(self.db, document_id, DOC_STATUS_ARCHIVED)
            else:
                raise InvalidDocumentStatusTransitionError(document.status, DOC_STATUS_ARCHIVED)

    async def count(
        self,
        repository_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
    ) -> int:
        """저장소 내 문서 수를 반환한다."""
        await self._validate_repository(repository_id, tenant_id)

        stmt = select(sa_func.count(Document.id)).where(
            Document.repository_id == repository_id
        )
        if status is not None:
            stmt = stmt.where(Document.status == status)
        result = await self.db.execute(stmt)
        return result.scalar_one()
