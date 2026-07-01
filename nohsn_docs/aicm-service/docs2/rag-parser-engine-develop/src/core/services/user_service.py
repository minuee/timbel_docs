"""최소 UserService 스텁 — core/services/__init__ 호환용."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
