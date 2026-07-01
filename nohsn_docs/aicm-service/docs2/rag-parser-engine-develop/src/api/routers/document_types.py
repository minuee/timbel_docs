"""문서타입 관리 API 라우터."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.common import ApiResponse
from src.api.schemas.document_type import DocumentTypeCreate, DocumentTypeResponse
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.services.document_type_service import DocumentTypeService

logger = get_logger(__name__)

router = APIRouter()


def _to_response(dt: object) -> DocumentTypeResponse:
    """ORM 객체를 응답 스키마로 변환."""
    return DocumentTypeResponse.model_validate(dt)


@router.get(
    "/tenants/{tenant_id}/document-types",
    response_model=ApiResponse[list[DocumentTypeResponse]],
    summary="문서타입 목록 조회",
)
async def list_document_types(
    tenant_id: UUID,
    is_system: bool | None = Query(None, description="시스템 타입 필터"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[DocumentTypeResponse]]:
    """테넌트의 문서타입 목록을 조회한다."""
    svc = DocumentTypeService(db)
    doc_types = await svc.list_by_tenant(tenant_id, is_system=is_system)
    items = [_to_response(dt) for dt in doc_types]
    return ApiResponse(data=items)


@router.get(
    "/document-types/{doc_type_id}",
    response_model=ApiResponse[DocumentTypeResponse],
    summary="문서타입 상세 조회",
)
async def get_document_type(
    doc_type_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DocumentTypeResponse]:
    """ID로 문서타입을 조회한다."""
    svc = DocumentTypeService(db)
    dt = await svc.get_by_id(doc_type_id)
    return ApiResponse(data=_to_response(dt))


@router.post(
    "/tenants/{tenant_id}/document-types",
    response_model=ApiResponse[DocumentTypeResponse],
    status_code=201,
    summary="문서타입 생성",
)
async def create_document_type(
    tenant_id: UUID,
    body: DocumentTypeCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DocumentTypeResponse]:
    """새 문서타입을 생성한다."""
    svc = DocumentTypeService(db)
    dt = await svc.create(
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        icon=body.icon,
    )
    return ApiResponse(data=_to_response(dt))
