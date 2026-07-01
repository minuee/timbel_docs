"""카테고리 관리 API 라우터."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.services.category_service import CategoryService

logger = get_logger(__name__)

router = APIRouter()


def _to_response(cat: object) -> CategoryResponse:
    """ORM 객체를 응답 스키마로 변환."""
    return CategoryResponse.model_validate(cat)


@router.get(
    "/repositories/{repo_id}/categories",
    response_model=ApiResponse[list[CategoryResponse]],
    summary="카테고리 목록 (트리) 조회",
)
async def list_categories(
    repo_id: UUID,
    parent_id: UUID | None = Query(None, description="부모 카테고리 ID (미입력 시 루트)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[CategoryResponse]]:
    """저장소의 카테고리 목록을 트리 구조로 조회한다."""
    svc = CategoryService(db)
    categories = await svc.list_by_repository(
        repo_id, tenant_id=tenant_id, parent_id=parent_id
    )
    items = [_to_response(c) for c in categories]
    return ApiResponse(data=items)


@router.get(
    "/repositories/{repo_id}/categories/tree",
    response_model=ApiResponse[list[dict]],
    summary="카테고리 전체 트리 조회",
)
async def get_category_tree(
    repo_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[dict]]:
    """저장소의 전체 카테고리 트리를 반환한다."""
    svc = CategoryService(db)
    tree = await svc.get_tree(repo_id, tenant_id=tenant_id)
    return ApiResponse(data=tree)


@router.get(
    "/categories/{category_id}",
    response_model=ApiResponse[CategoryResponse],
    summary="카테고리 상세 조회",
)
async def get_category(
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CategoryResponse]:
    """ID로 카테고리를 조회한다."""
    # [수정 2026-06-10] get_with_subtree 로 활성 서브트리를 미리 적재(재귀 직렬화 500 방지).
    svc = CategoryService(db)
    cat = await svc.get_with_subtree(category_id)
    return ApiResponse(data=_to_response(cat))


@router.post(
    "/repositories/{repo_id}/categories",
    response_model=ApiResponse[CategoryResponse],
    status_code=201,
    summary="카테고리 생성",
)
async def create_category(
    repo_id: UUID,
    body: CategoryCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CategoryResponse]:
    """새 카테고리를 생성한다."""
    svc = CategoryService(db)
    cat = await svc.create(
        repository_id=repo_id,
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        parent_id=body.parent_id,
        sort_order=body.sort_order,
        icon=body.icon,
    )
    # [수정 2026-06-10] selectin lazy-load 는 동기 model_validate 안에서 못 돈다.
    # get_with_subtree 로 활성 서브트리를 미리 적재(손자까지)해 재귀 직렬화 500을 막는다.
    fresh = await svc.get_with_subtree(cat.id, repository_id=repo_id)
    return ApiResponse(data=_to_response(fresh))


@router.patch(
    "/categories/{category_id}",
    response_model=ApiResponse[CategoryResponse],
    summary="카테고리 수정",
)
async def update_category(
    category_id: UUID,
    body: CategoryUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CategoryResponse]:
    """카테고리 정보를 수정한다."""
    svc = CategoryService(db)
    # CategoryService.update requires repository_id; get category first to obtain it
    cat = await svc.get_by_id(category_id)
    # parent_id 가 요청 본문에 명시적으로 포함되었는지 확인 (null 값도 반영)
    parent_id_value = body.parent_id if "parent_id" in body.model_fields_set else ...
    await svc.update(
        category_id,
        repository_id=cat.repository_id,
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        parent_id=parent_id_value,
        sort_order=body.sort_order,
        is_active=body.is_active,
        icon=body.icon,
    )
    # [수정 2026-06-10] 갱신 후 활성 서브트리를 다시 eager-load 해 재귀 직렬화 500을 막는다.
    fresh = await svc.get_with_subtree(category_id, repository_id=cat.repository_id)
    return ApiResponse(data=_to_response(fresh))


@router.patch(
    "/repositories/{repo_id}/categories/{category_id}",
    response_model=ApiResponse[CategoryResponse],
    summary="카테고리 수정 (저장소 스코프)",
)
async def update_category_scoped(
    repo_id: UUID,
    category_id: UUID,
    body: CategoryUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CategoryResponse]:
    """저장소 스코프 카테고리 수정. 드래그-앤-드롭 이동/재정렬에 사용한다."""
    svc = CategoryService(db)
    parent_id_value = body.parent_id if "parent_id" in body.model_fields_set else ...
    await svc.update(
        category_id,
        repository_id=repo_id,
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        parent_id=parent_id_value,
        sort_order=body.sort_order,
        is_active=body.is_active,
        icon=body.icon,
    )
    # [수정 2026-06-10] 갱신 후 활성 서브트리를 다시 eager-load 해 재귀 직렬화 500을 막는다.
    fresh = await svc.get_with_subtree(category_id, repository_id=repo_id)
    return ApiResponse(data=_to_response(fresh))


@router.delete(
    "/categories/{category_id}",
    response_model=ApiResponse[dict],
    summary="카테고리 삭제",
)
async def delete_category(
    category_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """카테고리를 소프트 삭제한다."""
    svc = CategoryService(db)
    cat = await svc.get_by_id(category_id)
    await svc.delete(category_id, repository_id=cat.repository_id, tenant_id=tenant_id)
    return ApiResponse(data={"deleted": True})
