"""Auth v2 — JWT + bcrypt + RBAC.

Phase 9 (KMS-Plus). 기존 phone-only ``/auth/login`` (v1, opaque session_token) 와
공존하며 점진 마이그레이션. 새 엔드포인트는 ``/auth/v2/{signup,login,refresh,me}``.
"""
from src.api.auth.jwt_utils import (  # noqa: F401
    InvalidToken,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.api.auth.rbac import RANK, ROLES, require_role  # noqa: F401
