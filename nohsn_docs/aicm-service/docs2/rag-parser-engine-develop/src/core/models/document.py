"""Document, Section, Chunk ORM 모델 및 문서-카테고리 매핑 테이블."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.block import Block
    from src.core.models.category import Category
    from src.core.models.document_type import DocumentType
    from src.core.models.repository import Repository


# N:M 문서-카테고리 매핑 테이블
document_categories = Table(
    "document_categories",
    Base.metadata,
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """문서 모델.

    Attributes:
        repository_id: 소속 저장소 ID
        document_type_id: 문서타입 ID
        title: 문서 제목
        description: 문서 설명
        source_file: 원본 파일 경로
        source_format: 원본 포맷 (pdf, docx, hwp, xlsx, html, image)
        version: 문서 버전
        status: 문서 상태 (draft / processing / active / archived / failed)
        processing_meta: 파이프라인 처리 메타 (난이도, 청크 수, 처리 시간 등)
        created_by: 등록자 UUID
    """

    __tablename__ = "documents"

    __table_args__ = (
        # alembic 072 — owner_agent_id 부분/복합 인덱스 (마이그레이션 parity 위해
        # create_all 스키마에도 반영. 부재 시 fresh DB 가 perf 인덱스 누락).
        Index(
            "ix_documents_owner_agent_partial",
            "owner_agent_id",
            postgresql_where=text("owner_agent_id IS NOT NULL"),
        ),
        Index(
            "ix_documents_owner_agent_doctype",
            "document_type_id",
            "tenant_id",
            "owner_agent_id",
            "status",
            postgresql_where=text("owner_agent_id IS NOT NULL"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id"),
        nullable=False,
        index=True,
    )
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_types.id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", nullable=False, index=True
    )
    processing_meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    legal_hold: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="법적 보존 플래그 — true 시 삭제/비식별화 차단",
    )
    search_excluded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="true 이면 검색/RAG 에서 제외 (status 는 active 유지 — library 에 계속 표시)",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Phase 1.5A Task 4 — memo dedup. ``document_type='agent_memo'`` row 의 body
    # SHA-256 (앞 64자). 일반 문서는 NULL. ``ix_memos_body_hash_recent`` 부분
    # 인덱스가 (created_by, body_hash, created_at) 으로 좁혀 dedup 쿼리를 가속.
    body_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- alembic 067 — 라이브러리 트리 분류 ---
    # NULL = repo 의 root 직속. ON DELETE SET NULL — 폴더 삭제 시 자료 보존,
    # root 로 자동 회수. KMS 검색 무영향 (folder 는 분류 전용).
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("library_folders.id", ondelete="SET NULL"),
        nullable=True,
        comment="라이브러리 폴더 — NULL=repo root. 폴더 삭제 시 SET NULL.",
    )

    # --- alembic 068 — SOP 분리 ---
    # doc 자체가 SOP 인지 (folder.kind 와 독립적으로 LLM 보정). 기본 false.
    # kms_sop.search 는 (folder.kind='sop' OR documents.is_sop=true) 인 doc 만
    # 좁혀 진짜 SOP RAG 분리.
    is_sop: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        comment="이 doc 이 SOP 인지 — kms_sop.search 가 좁혀 매뉴얼 혼용 차단.",
    )

    # --- alembic 072 — agent 단위 write 격리 ---
    # 모델이 마이그레이션 072 와 drift 되어 create_all 스키마에 누락돼 있었음 →
    # init_db 의 RLS 정책(_apply_rls_policies)이 documents.owner_agent_id 를
    # 참조할 때 fresh DB 에서 'column owner_agent_id does not exist' 크래시.
    # FK ON DELETE SET NULL — agent 삭제 시 row 보존. 일반 KMS 문서는 NULL.
    owner_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        comment="agent 단위 write 격리 (alembic 072). 일반 KMS 문서는 NULL.",
    )

    # Relationships
    repository: Mapped[Repository] = relationship(
        "Repository",
        back_populates="documents",
    )
    document_type: Mapped[DocumentType | None] = relationship(
        "DocumentType",
        lazy="joined",
    )
    categories: Mapped[list[Category]] = relationship(
        "Category",
        secondary=document_categories,
        lazy="selectin",
    )
    sections: Mapped[list[Section]] = relationship(
        "Section",
        back_populates="document",
        lazy="noload",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk",
        back_populates="document",
        lazy="noload",
        cascade="all, delete-orphan",
        foreign_keys="[Chunk.document_id]",
    )
    blocks: Mapped[list[Block]] = relationship(
        "Block",
        back_populates="document",
        lazy="noload",
        cascade="all, delete-orphan",
        foreign_keys="[Block.document_id]",
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, title='{self.title}', status='{self.status}')>"


class Section(UUIDPrimaryKeyMixin, Base):
    """섹션 모델. 문서의 목차/단락 구조.

    Attributes:
        document_id: 소속 문서 ID
        parent_id: 상위 섹션 ID (계층적 목차)
        title: 섹션 제목
        content: 섹션 본문
        section_order: 섹션 순서
        level: 목차 깊이 (0=루트, 1=하위, ...)
        metadata: 표/이미지 등 부가 정보
    """

    __tablename__ = "sections"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    meta_info: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    document: Mapped[Document] = relationship(
        "Document",
        back_populates="sections",
    )
    parent: Mapped[Section | None] = relationship(
        "Section",
        remote_side="Section.id",
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<Section(id={self.id}, title='{self.title}', level={self.level})>"


class Chunk(UUIDPrimaryKeyMixin, Base):
    """청크 모델. 벡터화 단위.

    Attributes:
        section_id: 소속 섹션 ID
        document_id: 소속 문서 ID (비정규화, 검색 성능)
        repository_id: 소속 저장소 ID (비정규화, 격리 필터)
        content: 청크 텍스트
        chunk_index: 문서 내 청크 순서
        chunk_hash: SHA-256 해시 (중복 감지)
        token_count: 토큰 수
        source_location: 원본 문서 내 위치 정보 (JSONB)
        metadata: 청킹 전략, 표/이미지 여부 등
        vector_id: Qdrant point ID
        is_indexed: 벡터 인덱싱 완료 여부
    """

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_hash", name="uq_chunks_document_hash"),
    )

    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_location: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    meta_info: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}", nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_indexed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    document: Mapped[Document] = relationship(
        "Document",
        back_populates="chunks",
        foreign_keys=[document_id],
    )
    repository: Mapped[Repository] = relationship("Repository")

    def __repr__(self) -> str:
        return f"<Chunk(id={self.id}, document_id={self.document_id}, index={self.chunk_index})>"
