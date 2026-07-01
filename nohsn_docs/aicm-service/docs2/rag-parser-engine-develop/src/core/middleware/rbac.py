"""RBAC no-op 스텁 — 인증 분리 전까지 모든 요청 통과."""

from src.core.models.user import UserRole  # noqa: F401


def require_role(min_role: UserRole = UserRole.viewer):
    """인증 제거 상태: 항상 통과하는 no-op dependency."""

    async def _noop():
        return None

    return _noop
