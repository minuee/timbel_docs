"""AgentDocument ORM 모델 — agent x document 매핑 (옵션 Y v2).

agent 별 SOP / 지식자료 분류를 *문서 단위* 로 관리한다 (alembic 070, 2026-05-07).

설계:
- agent_id × document_id 합성 unique — 한 agent 가 같은 doc 을 2 mode 로 못 가짐.
- mode = 'sop' / 'kms' — agent 의 검색 소스 분류.
- source = 'shared' / 'uploaded' — picker 로 link 했는지 직접 업로드인지.
- tenant_id + DB 트리거로 cross-tenant 누수 차단 (GPT-5 P0).

KMS retrieval 영향:
- 빈 테이블 → 옛 repo_ids fallback (회귀 0).
- 채워진 후 → agent_documents UNION repo_ids (Phase 4 partial backfill 회귀 차단).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.agent import Agent
    from src.core.models.document import Document


class AgentDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """agent x document 매핑.

    Attributes:
        tenant_id: 소속 테넌트 (트리거가 agent.tenant_id == document.tenant_id 강제)
        agent_id: 매핑되는 agent
        document_id: 매핑되는 document
        mode: 'sop' (SOP) / 'kms' (지식자료)
        source: 'shared' (picker 로 link) / 'uploaded' (직접 업로드)
    """

    __tablename__ = "agent_documents"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "document_id", name="uq_agent_documents_agent_doc"
        ),
        CheckConstraint(
            "mode IN ('sop','kms')", name="ck_agent_documents_mode"
        ),
        CheckConstraint(
            "source IN ('shared','uploaded')",
            name="ck_agent_documents_source",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="shared",
        server_default="shared",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentDocument(agent={self.agent_id}, doc={self.document_id}, "
            f"mode='{self.mode}', source='{self.source}')>"
        )
