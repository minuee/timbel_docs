"""LibraryFolder ORM 모델 — repo 안 디렉터리 트리 분류.

라이브러리 UI 트리 개선 (alembic 067). repo 별로 self-referential 트리를
구성한다. ``parent_folder_id IS NULL`` 이면 repo 의 root 직속 폴더.

설계:
- ON DELETE CASCADE (parent → child) — 부모 폴더 삭제 시 자식까지 자동 정리.
- ON DELETE CASCADE (repository → folder) — repo 삭제 시 폴더 트리도 정리.
- documents.folder_id 는 ON DELETE SET NULL — 폴더 삭제 시 자료 보존, root 회수.
- 같은 부모 안 같은 이름 차단 — UNIQUE (repository_id, parent_folder_id, name)
  + repo root 부분 unique index (alembic 067 에 정의).

KMS 검색 무영향:
- folder 는 분류 전용. 검색은 repo_id / agent_id 격리 그대로.
- payload_sync / chunks / blocks 는 folder 무관.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.repository import Repository
    from src.core.models.tenant import Tenant


class LibraryFolder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """라이브러리 폴더 — repo 안 디렉터리 트리.

    Attributes:
        tenant_id: 소속 테넌트 ID
        repository_id: 소속 repo ID (repo 안 트리)
        parent_folder_id: 상위 폴더 ID (NULL = repo root 직속)
        name: 폴더 이름 (같은 부모 안 unique)
        created_by: 생성자 user UUID
    """

    __tablename__ = "library_folders"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "parent_folder_id", "name",
            name="uq_library_folders_parent_name",
        ),
        # alembic 068 — kind enum CHECK.
        CheckConstraint(
            "kind IN ('sop','manual','glossary','faq','policy')",
            name="ck_library_folders_kind",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("library_folders.id", ondelete="CASCADE"),
        nullable=True,
    )
    # alembic 071 (옵션 Y v2) — 이 폴더가 어느 agent 의 자동 default 폴더인지.
    # NULL = 사람 분류용 일반 폴더. NOT NULL = agent 자동 폴더.
    # UNIQUE(owner_agent_id) WHERE NOT NULL — 한 agent 가 default folder 2개 못
    # 가짐 (race 차단). FK ON DELETE SET NULL — agent 삭제 시 폴더 보존.
    owner_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # alembic 068 — 폴더 분류 (sop/manual/glossary/faq/policy). 기본 'manual'.
    # 재처리 (5 봇 reseed) 시 LLM 1-shot 으로 채움. SOP 폴더만 kms_sop.search 가
    # 좁혀 매뉴얼 매뉴얼 혼용을 차단한다.
    kind: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="manual",
        default="manual",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Self-ref relationships (lazy=noload — 트리 walk 는 명시 쿼리로).
    parent: Mapped[LibraryFolder | None] = relationship(
        "LibraryFolder",
        remote_side="LibraryFolder.id",
        back_populates="children",
        lazy="noload",
    )
    children: Mapped[list[LibraryFolder]] = relationship(
        "LibraryFolder",
        back_populates="parent",
        lazy="noload",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<LibraryFolder(id={self.id}, name='{self.name}', "
            f"repo={self.repository_id}, parent={self.parent_folder_id})>"
        )
