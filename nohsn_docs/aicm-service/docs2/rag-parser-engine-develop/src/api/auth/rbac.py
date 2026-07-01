"""RBAC — role hierarchy + ``require_role`` decorator.

Phase 9 (KMS-Plus).

Roles (rank 오름차순):
    viewer (0) → member (1) → admin (2) → owner (3)

높은 role 은 낮은 role 의 권한을 모두 포함한다 (linear hierarchy).

사용:
    @router.get("/admin/x")
    @require_role("admin")
    async def x(current_user: dict = Depends(get_current_principal)):
        ...

``current_user`` 는 ``get_current_principal`` (Auth v2) 가 반환하는 dict —
``{"user_id", "tenant_id", "role", "auth_v2"}`` 형식.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from fastapi import Depends, HTTPException


# 낮은 → 높은 순서. RANK 는 역순 매핑 (viewer=0, owner=3) 으로 비교 편의.
ROLES: list[str] = ["viewer", "member", "admin", "owner"]
RANK: dict[str, int] = {role: idx for idx, role in enumerate(ROLES)}


def _get_dependency():
    """``get_current_principal`` 을 lazy import — circular import 회피."""
    from src.api.dependencies import get_current_principal

    return get_current_principal


def require_role(min_role: str) -> Callable[..., Any]:
    """현재 user role 이 ``min_role`` 이상이어야 통과하는 decorator.

    ``min_role`` 미달은 403 ``requires {min_role}+`` 으로 응답.
    함수 인자에 ``current_user: dict = Depends(get_current_user_id)`` 가
    이미 있다면 그대로 사용, 없으면 자동 주입.
    """
    if min_role not in RANK:
        raise ValueError(f"unknown role {min_role!r} (allowed: {ROLES})")

    threshold = RANK[min_role]

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrap(
            *args: Any,
            current_user: dict = Depends(_get_dependency()),
            **kwargs: Any,
        ) -> Any:
            user_role = (current_user or {}).get("role", "viewer")
            if RANK.get(user_role, -1) < threshold:
                raise HTTPException(
                    status_code=403,
                    detail=f"requires {min_role}+",
                )
            return await func(*args, current_user=current_user, **kwargs)

        return wrap

    return deco


def require_role_dep(min_role: str) -> Callable[..., Any]:
    """Wave D (KMS-Plus, 2026-04-25) — FastAPI ``Depends(...)`` 친화 변형.

    ``router = APIRouter(dependencies=[Depends(require_role_dep("admin"))])``
    형태로 라우터/엔드포인트 레벨 가드에 직접 끼울 수 있다. 기존 decorator
    버전 (``require_role``) 은 wraps 한 함수가 ``current_user`` 키워드 인자를
    덧붙여 전달하므로 router-level dependencies 에는 부적합.

    Returns
    -------
    Callable
        ``Depends(...)`` 가 호출 가능한 비동기 함수 — current_user 는
        ``get_current_principal`` 으로 주입되며, 권한 미달 시 403 raise.
    """
    if min_role not in RANK:
        raise ValueError(f"unknown role {min_role!r} (allowed: {ROLES})")
    threshold = RANK[min_role]

    async def _checker(
        current_user: dict = Depends(_get_dependency()),
    ) -> dict:
        user_role = (current_user or {}).get("role", "viewer")
        if RANK.get(user_role, -1) < threshold:
            raise HTTPException(
                status_code=403,
                detail=f"requires {min_role}+",
            )
        return current_user

    return _checker
