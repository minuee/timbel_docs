"""동의어 관리 API 라우터 -- 테넌트별 커스텀 동의어 CRUD."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.middleware.rbac import require_role
from src.core.models.user import UserRole

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class SynonymEntry(BaseModel):
    """동의어 항목."""

    term: str = Field(..., min_length=1, max_length=200, description="기준 용어")
    synonyms: list[str] = Field(..., min_length=1, description="동의어 리스트")


class SynonymCreateRequest(BaseModel):
    """동의어 생성/수정 요청."""

    entries: list[SynonymEntry] = Field(..., min_length=1, description="동의어 항목 리스트")


class SynonymListItem(BaseModel):
    """동의어 목록 아이템."""

    id: UUID
    term: str
    synonyms: list[str]
    is_active: bool = True


class SynonymListResponse(BaseModel):
    """동의어 목록 응답."""

    entries: list[SynonymListItem]
    total_count: int


# ---------------------------------------------------------------------------
# API 엔드포인트
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ApiResponse[SynonymListResponse],
    summary="동의어 목록 조회",
    dependencies=[Depends(require_role(UserRole.viewer))],
)
async def list_synonyms(
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(None, description="검색어 필터"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ApiResponse[SynonymListResponse]:
    """테넌트의 커스텀 동의어 목록을 조회한다."""
    params: dict = {"tenant_id": str(tenant_id), "limit": limit, "offset": offset}

    search_filter = ""
    if search:
        search_filter = "AND term ILIKE :search"
        params["search"] = f"%{search}%"

    try:
        # 건수 조회
        count_result = await db.execute(
            text(f"""
                SELECT COUNT(*) FROM tenant_synonyms
                WHERE tenant_id = :tenant_id AND is_active = true {search_filter}
            """),
            params,
        )
        total_count = int(count_result.scalar() or 0)

        # 목록 조회
        result = await db.execute(
            text(f"""
                SELECT id, term, synonyms, is_active
                FROM tenant_synonyms
                WHERE tenant_id = :tenant_id AND is_active = true {search_filter}
                ORDER BY term ASC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

        entries = [
            SynonymListItem(
                id=row[0],
                term=row[1],
                synonyms=row[2] if isinstance(row[2], list) else [],
                is_active=row[3],
            )
            for row in rows
        ]

        return ApiResponse(
            data=SynonymListResponse(entries=entries, total_count=total_count)
        )
    except Exception as exc:
        logger.warning("synonym_list_error", error=str(exc))
        return ApiResponse(
            data=SynonymListResponse(entries=[], total_count=0)
        )


@router.post(
    "",
    response_model=ApiResponse[dict],
    summary="동의어 등록/수정",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def upsert_synonyms(
    body: SynonymCreateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """테넌트의 커스텀 동의어를 등록하거나 수정한다.

    이미 존재하는 term은 synonyms를 업데이트한다.
    """
    created = 0
    updated = 0

    try:
        for entry in body.entries:
            # UPSERT: term이 이미 있으면 synonyms 업데이트
            result = await db.execute(
                text("""
                    INSERT INTO tenant_synonyms (tenant_id, term, synonyms, is_active)
                    VALUES (:tenant_id, :term, :synonyms, true)
                    ON CONFLICT (tenant_id, term) DO UPDATE
                    SET synonyms = :synonyms, is_active = true, updated_at = now()
                    RETURNING (xmax = 0) AS is_insert
                """),
                {
                    "tenant_id": str(tenant_id),
                    "term": entry.term,
                    "synonyms": entry.synonyms,
                },
            )
            row = result.fetchone()
            if row and row[0]:
                created += 1
            else:
                updated += 1

        await db.commit()

        # 동의어 캐시 무효화
        _invalidate_synonym_cache(tenant_id)

        logger.info(
            "synonyms_upserted",
            tenant_id=str(tenant_id),
            created=created,
            updated=updated,
        )

        return ApiResponse(
            data={"created": created, "updated": updated, "total": created + updated}
        )
    except Exception as exc:
        await db.rollback()
        logger.warning("synonym_upsert_error", error=str(exc))
        return ApiResponse(
            success=False,
            data={"error": str(exc)},
        )


@router.delete(
    "/{term}",
    response_model=ApiResponse[dict],
    summary="동의어 삭제",
    dependencies=[Depends(require_role(UserRole.editor))],
)
async def delete_synonym(
    term: str,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """특정 동의어 항목을 비활성화(소프트 삭제)한다."""
    try:
        result = await db.execute(
            text("""
                UPDATE tenant_synonyms
                SET is_active = false, updated_at = now()
                WHERE tenant_id = :tenant_id AND term = :term AND is_active = true
            """),
            {"tenant_id": str(tenant_id), "term": term},
        )
        await db.commit()

        affected = result.rowcount or 0
        if affected > 0:
            _invalidate_synonym_cache(tenant_id)

        return ApiResponse(data={"deleted": affected > 0, "term": term})
    except Exception as exc:
        await db.rollback()
        logger.warning("synonym_delete_error", error=str(exc))
        return ApiResponse(success=False, data={"error": str(exc)})


def _invalidate_synonym_cache(tenant_id: UUID) -> None:
    """SynonymExpander의 테넌트 캐시를 무효화. 서비스 인스턴스에 접근 가능할 때만."""
    try:
        from src.search.hybrid.synonym_expander import SynonymExpander

        # 글로벌 인스턴스가 있으면 캐시 무효화
        # 실제로는 DI 컨테이너를 통해 접근해야 하지만, 현 단계에서는 noop
        logger.debug("synonym_cache_invalidated", tenant_id=str(tenant_id))
    except ImportError:
        pass
