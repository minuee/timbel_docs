"""최소 User/UserRole 스텁 — 파이프라인 FK 참조 및 RBAC 호환용."""

import enum
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(str, enum.Enum):
    platform_admin = "platform_admin"
    tenant_admin = "tenant_admin"
    repo_admin = "repo_admin"
    editor = "editor"
    viewer = "viewer"
    api_consumer = "api_consumer"


ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.platform_admin: 100,
    UserRole.tenant_admin: 50,
    UserRole.repo_admin: 40,
    UserRole.editor: 30,
    UserRole.viewer: 20,
    UserRole.api_consumer: 10,
}


def role_gte(role: UserRole, min_role: UserRole) -> bool:
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(min_role, 0)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserRepositoryAccess(Base):
    __tablename__ = "user_repository_access"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id"), primary_key=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
