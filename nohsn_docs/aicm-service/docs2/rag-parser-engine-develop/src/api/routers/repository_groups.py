"""Repository group router (Lucas-KMS only).

Endpoints:
- GET    /api/v1/tenants/{tenant_id}/repository-groups
- POST   /api/v1/tenants/{tenant_id}/repository-groups
- GET    /api/v1/repository-groups/{group_id}
- PATCH  /api/v1/repository-groups/{group_id}
- DELETE /api/v1/repository-groups/{group_id}
- POST   /api/v1/repository-groups/{group_id}/set-default

All operations are scoped to a tenant — same-tenant repositories only.
Setting is_default true (either via create/patch is_default or the
explicit set-default endpoint) resets the previous tenant default in the
same transaction.

Lucas-KMS only — not mounted in the unified solution.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_principal, get_current_tenant_id
from src.api.schemas.common import ApiResponse, PaginatedResponse
from src.api.schemas.repository_group import (
    RepositoryGroupCreate,
    RepositoryGroupResponse,
    RepositoryGroupUpdate,
    SetDefaultResponse,
)
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.models.repository import Repository
from src.core.models.repository_group import RepositoryGroup

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_tenant_match(path_tenant_id: UUID, principal: dict[str, Any]) -> None:
    """Same policy as repositories.py — block cross-tenant access in auth mode."""
    if principal.get("auth_disabled"):
        return
    authed_tid = principal.get("tenant_id")
    if not authed_tid:
        return
    if str(authed_tid) != str(path_tenant_id):
        raise HTTPException(
            status_code=403,
            detail=(
                f"path tenant_id ({path_tenant_id}) does not match authed "
                f"tenant_id ({authed_tid})"
            ),
        )


def _to_response(group: RepositoryGroup) -> RepositoryGroupResponse:
    """ORM -> response schema, with repository_count populated."""
    resp = RepositoryGroupResponse.model_validate(group)
    resp.repository_count = len(group.repository_ids or [])
    return resp


async def _validate_repository_ids(
    db: AsyncSession,
    tenant_id: UUID,
    repository_ids: list[UUID],
) -> None:
    """Ensure every repository_id belongs to the given tenant.

    Application-level FK enforcement (since postgres ARRAY does not carry
    FK constraints). Raises HTTPException(400) on mismatch.
    """
    if not repository_ids:
        return
    stmt = select(Repository.id).where(
        Repository.id.in_(repository_ids),
        Repository.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    valid_ids = {row[0] for row in result.fetchall()}
    missing = [str(rid) for rid in repository_ids if rid not in valid_ids]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "repository_ids contain ids not belonging to this tenant "
                f"or not found: {missing}"
            ),
        )


async def _reset_other_defaults(
    db: AsyncSession,
    tenant_id: UUID,
    keep_group_id: UUID | None,
) -> UUID | None:
    """Reset is_default=false for every other group in this tenant.

    Returns the previous default group id (if any) so the caller can
    report it in the response.
    """
    prev_stmt = select(RepositoryGroup.id).where(
        RepositoryGroup.tenant_id == tenant_id,
        RepositoryGroup.is_default.is_(True),
    )
    if keep_group_id is not None:
        prev_stmt = prev_stmt.where(RepositoryGroup.id != keep_group_id)
    prev_result = await db.execute(prev_stmt)
    previous = prev_result.scalar_one_or_none()

    upd = (
        update(RepositoryGroup)
        .where(
            RepositoryGroup.tenant_id == tenant_id,
            RepositoryGroup.is_default.is_(True),
        )
    )
    if keep_group_id is not None:
        upd = upd.where(RepositoryGroup.id != keep_group_id)
    upd = upd.values(is_default=False)
    await db.execute(upd)
    return previous


async def _get_group_or_404(
    db: AsyncSession,
    group_id: UUID,
    tenant_id: UUID | None = None,
) -> RepositoryGroup:
    """Fetch a group by id (optionally tenant-scoped). 404 on miss."""
    stmt = select(RepositoryGroup).where(RepositoryGroup.id == group_id)
    if tenant_id is not None:
        stmt = stmt.where(RepositoryGroup.tenant_id == tenant_id)
    result = await db.execute(stmt)
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=404,
            detail=f"repository group {group_id} not found",
        )
    return group


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/tenants/{tenant_id}/repository-groups",
    response_model=ApiResponse[PaginatedResponse[RepositoryGroupResponse]],
    summary="List repository groups",
    description=(
        "List repository groups owned by the given tenant. Filter by "
        "is_active or is_default. Each item carries repository_count "
        "(len(repository_ids)) and the full repository_ids array."
    ),
    responses={
        200: {"description": "Paginated repository groups."},
        403: {"description": "path tenant_id does not match authed tenant_id."},
    },
)
async def list_repository_groups(
    tenant_id: UUID,
    is_active: bool | None = Query(None, description="Active filter."),
    is_default: bool | None = Query(None, description="Default filter."),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    principal: dict[str, Any] = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaginatedResponse[RepositoryGroupResponse]]:
    _assert_tenant_match(tenant_id, principal)
    stmt = select(RepositoryGroup).where(RepositoryGroup.tenant_id == tenant_id)
    if is_active is not None:
        stmt = stmt.where(RepositoryGroup.is_active.is_(is_active))
    if is_default is not None:
        stmt = stmt.where(RepositoryGroup.is_default.is_(is_default))
    stmt = stmt.order_by(
        RepositoryGroup.is_default.desc(),
        RepositoryGroup.created_at.desc(),
    ).offset(offset).limit(limit)
    result = await db.execute(stmt)
    groups = result.scalars().all()
    items = [_to_response(g) for g in groups]
    return ApiResponse(data=PaginatedResponse(items=items, total_count=len(items)))


@router.post(
    "/tenants/{tenant_id}/repository-groups",
    response_model=ApiResponse[RepositoryGroupResponse],
    status_code=201,
    summary="Create a repository group",
    description=(
        "Create a new named multi-repository subset inside this tenant.\n\n"
        "- Every id in repository_ids must belong to the same tenant.\n"
        "- name must be unique within the tenant (409 otherwise).\n"
        "- is_default=true resets the previous default to false in the "
        "same transaction."
    ),
    responses={
        201: {"description": "Group created."},
        400: {"description": "repository_ids contain ids outside this tenant."},
        403: {"description": "path tenant_id mismatch."},
        409: {"description": "Group name already in use within this tenant."},
    },
)
async def create_repository_group(
    tenant_id: UUID,
    body: RepositoryGroupCreate,
    principal: dict[str, Any] = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RepositoryGroupResponse]:
    _assert_tenant_match(tenant_id, principal)
    await _validate_repository_ids(db, tenant_id, body.repository_ids)

    # Name uniqueness pre-check (race-safe rely on UniqueConstraint below).
    dup_stmt = select(RepositoryGroup.id).where(
        RepositoryGroup.tenant_id == tenant_id,
        RepositoryGroup.name == body.name,
    )
    dup = (await db.execute(dup_stmt)).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=f"repository group name '{body.name}' already exists in this tenant",
        )

    group = RepositoryGroup(
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        repository_ids=list(body.repository_ids),
        is_default=bool(body.is_default),
        is_active=True,
        config=dict(body.config or {}),
    )
    db.add(group)
    await db.flush()  # so we have group.id for default reset.

    if body.is_default:
        await _reset_other_defaults(db, tenant_id, keep_group_id=group.id)

    await db.commit()
    await db.refresh(group)
    logger.info(
        "repository_group_created",
        group_id=str(group.id),
        tenant_id=str(tenant_id),
        repo_count=len(group.repository_ids or []),
        is_default=group.is_default,
    )
    return ApiResponse(data=_to_response(group))


@router.get(
    "/repository-groups/{group_id}",
    response_model=ApiResponse[RepositoryGroupResponse],
    summary="Get a repository group",
    description=(
        "Fetch a single group by id. Scoped to the authed tenant; cross-tenant "
        "lookups return 404 (not 403, to avoid leaking existence)."
    ),
    responses={
        200: {"description": "Group detail."},
        404: {"description": "Not found (or owned by a different tenant)."},
    },
)
async def get_repository_group(
    group_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RepositoryGroupResponse]:
    group = await _get_group_or_404(db, group_id, tenant_id=tenant_id)
    return ApiResponse(data=_to_response(group))


@router.patch(
    "/repository-groups/{group_id}",
    response_model=ApiResponse[RepositoryGroupResponse],
    summary="Update a repository group",
    description=(
        "Partial update. None fields keep their previous value.\n\n"
        "- repository_ids replaces the array wholesale (no partial merge) "
        "and is validated against the tenant.\n"
        "- Setting is_default=true resets the previous default to false in "
        "the same transaction.\n"
        "- Cross-tenant updates return 404."
    ),
    responses={
        200: {"description": "Updated group."},
        400: {"description": "repository_ids contain ids outside this tenant."},
        404: {"description": "Not found (or owned by a different tenant)."},
        409: {"description": "Name collision with another group in this tenant."},
    },
)
async def update_repository_group(
    group_id: UUID,
    body: RepositoryGroupUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RepositoryGroupResponse]:
    group = await _get_group_or_404(db, group_id, tenant_id=tenant_id)

    if body.name is not None and body.name != group.name:
        dup_stmt = select(RepositoryGroup.id).where(
            RepositoryGroup.tenant_id == tenant_id,
            RepositoryGroup.name == body.name,
            RepositoryGroup.id != group.id,
        )
        dup = (await db.execute(dup_stmt)).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"repository group name '{body.name}' already exists in this tenant",
            )
        group.name = body.name

    if body.description is not None:
        group.description = body.description

    if body.repository_ids is not None:
        await _validate_repository_ids(db, tenant_id, body.repository_ids)
        group.repository_ids = list(body.repository_ids)

    if body.is_active is not None:
        group.is_active = bool(body.is_active)

    if body.config is not None:
        group.config = dict(body.config)

    if body.is_default is not None:
        if body.is_default and not group.is_default:
            await _reset_other_defaults(db, tenant_id, keep_group_id=group.id)
        group.is_default = bool(body.is_default)

    await db.commit()
    await db.refresh(group)
    logger.info(
        "repository_group_updated",
        group_id=str(group.id),
        tenant_id=str(tenant_id),
    )
    return ApiResponse(data=_to_response(group))


@router.delete(
    "/repository-groups/{group_id}",
    response_model=ApiResponse[dict],
    summary="Delete a repository group",
    description=(
        "Hard-delete the group row (the underlying repositories are untouched). "
        "Cross-tenant deletes return 404."
    ),
    responses={
        200: {"description": "{deleted: true}"},
        404: {"description": "Not found (or owned by a different tenant)."},
    },
)
async def delete_repository_group(
    group_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    group = await _get_group_or_404(db, group_id, tenant_id=tenant_id)
    await db.delete(group)
    await db.commit()
    logger.info(
        "repository_group_deleted",
        group_id=str(group_id),
        tenant_id=str(tenant_id),
    )
    return ApiResponse(data={"deleted": True})


@router.post(
    "/repository-groups/{group_id}/set-default",
    response_model=ApiResponse[SetDefaultResponse],
    summary="Set as tenant default group",
    description=(
        "Mark this group as the tenant default. Any other group in the same "
        "tenant that previously had is_default=true is reset to false in the "
        "same transaction. The response carries the previous default id "
        "(or null if none existed)."
    ),
    responses={
        200: {"description": "Default switched."},
        404: {"description": "Group not found in this tenant."},
    },
)
async def set_default_repository_group(
    group_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SetDefaultResponse]:
    group = await _get_group_or_404(db, group_id, tenant_id=tenant_id)
    previous = await _reset_other_defaults(db, tenant_id, keep_group_id=group.id)
    group.is_default = True
    await db.commit()
    await db.refresh(group)
    logger.info(
        "repository_group_set_default",
        group_id=str(group.id),
        tenant_id=str(tenant_id),
        previous_default_id=str(previous) if previous else None,
    )
    return ApiResponse(
        data=SetDefaultResponse(
            group_id=group.id,
            is_default=True,
            previous_default_group_id=previous,
        )
    )
