"""라이선스 no-op 스텁 — 모든 제한 검사 통과."""

from __future__ import annotations

from typing import Any
from uuid import UUID


async def check_document_limit(tenant_id: UUID, db=None, redis=None) -> bool:
    """No-op: 항상 제한 내."""
    return True


async def check_repository_limit(tenant_id: UUID, db=None, redis=None) -> bool:
    """No-op: 항상 제한 내."""
    return True


async def get_current_limits(tenant_id: UUID, db=None, redis=None) -> dict[str, Any]:
    """No-op: 무제한."""
    return {
        "tier": "unlimited",
        "documents_used": 0,
        "documents_limit": 999999,
        "repositories_used": 0,
        "repositories_limit": 999999,
        "warning_threshold_hit": False,
    }


async def increment_daily_counter(tenant_id: UUID, metric: str, redis=None) -> int:
    """No-op: 항상 0."""
    return 0
