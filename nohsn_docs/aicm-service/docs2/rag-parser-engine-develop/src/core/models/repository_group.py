"""RepositoryGroup ORM 모델 — Lucas-KMS 전용 (multi-repository named subset).

본 모델은 *통합 솔루션 (Locus monorepo)* 에는 존재하지 않는다.
Lucas-KMS 분리 제품에서만 사용되는 신규 entity 로서, tenant 안에 *복수* 저장소를
하나의 named subset 으로 묶어 search 시 group_id 또는 repository_ids array 로
한 번에 검색할 수 있게 한다.

설계 결정:
- ``repository_ids`` 는 ``ARRAY(UUID)`` 컬럼 — postgres native array. JOIN 테이블
  대비 단순/빠름. 단점은 FK 미강제 (group 안 repo 가 사라지면 cleanup 필요) —
  application layer 에서 resolve 시 active 필터로 흡수.
- ``is_default`` 는 tenant 안에서 *최대 1개* 만 true 가 되도록 set-default
  endpoint 에서 트랜잭션 강제. 부분 index 로 enforce 도 가능하지만 본 phase 는
  application-level enforcement.
- ``config`` JSONB — 향후 group 별 검색 가중치 / rerank policy override 등 확장용.
- ``UniqueConstraint(tenant_id, name)`` — 같은 tenant 안 group 이름 중복 차단.

메모리 절칙:
- 본체 (AICM-APIs) 미수정 — 본 파일은 Lucas-KMS 폴더 안에만 존재해야 함.
- 하드코딩 X — repository_ids 는 array 컬럼이며 enum 화 금지.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.core.models.tenant import Tenant


class RepositoryGroup(UUIDPrimaryKeyMixin, Base):
    """저장소 그룹 — tenant 안 named multi-repository subset.

    Lucas-KMS 전용. 검색 호출 시 ``repository_group_id`` 를 넘기면 본 그룹의
    ``repository_ids`` 가 자동 펼쳐져 multi-repo 하이브리드 검색이 수행된다.

    Attributes:
        tenant_id: 소속 tenant ID (모든 group 은 단일 tenant 안).
        name: group 이름 — tenant 내 unique.
        description: 사용자 설명 (선택).
        repository_ids: 본 그룹에 묶인 repository UUID 목록. 빈 리스트 허용
            (검색 시 빈 결과). FK 미강제 — application 에서 active 필터로 처리.
        config: 향후 확장용 JSONB (e.g. group 단위 검색 가중치, rerank policy 등).
        is_default: tenant 의 기본 group 표시. 최대 1개 / tenant (set-default
            endpoint 가 다른 group 의 is_default 를 false 로 reset).
        is_active: 소프트 비활성 (검색에서 제외).
    """

    __tablename__ = "repository_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_repo_group_tenant_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    repository_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'::uuid[]"),
    )
    config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        foreign_keys=[tenant_id],
        lazy="noload",
    )

    def __repr__(self) -> str:
        return (
            f"<RepositoryGroup(id={self.id}, name='{self.name}', "
            f"repos={len(self.repository_ids or [])}, default={self.is_default})>"
        )
