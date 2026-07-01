"""저장소 관리 API 라우터."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_principal, get_current_tenant_id
from src.api.schemas.common import ApiResponse, PaginatedResponse
from src.api.schemas.repository import (
    RepositoryCreate,
    RepositoryKindSummary,
    RepositoryResponse,
    RepositoryUpdate,
)
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.services.repository_service import RepositoryService

logger = get_logger(__name__)

router = APIRouter()


def _assert_tenant_match(
    path_tenant_id: UUID, principal: dict[str, Any]
) -> None:
    """Path ``tenant_id`` 와 인증된 principal 의 ``tenant_id`` 일치 검증.

    Fix C (2026-05-19) — cross-tenant 접근 차단 일관화.

    Policy:
    - 무인증 모드 (``LUCAS_AUTH_DISABLED=true``): bypass — path tenant 자유 진입
      (principal["auth_disabled"] == True).
    - 인증된 tenant_id 가 None / 빈 문자열: bypass — 별도 dependency (RLS / legacy)
      가 강제하므로 여기서 추가 차단 없음 (회귀 0).
    - 인증된 tenant_id 가 path tenant_id 와 *불일치*: 403.
    - admin role 도 자기 tenant 만 — super admin 시나리오는 별도 endpoint 권장.

    Args:
        path_tenant_id: URL path 의 ``{tenant_id}`` (UUID).
        principal: ``get_current_principal`` dependency 의 dict.

    Raises:
        HTTPException(403): path tenant_id 와 인증된 tenant_id 불일치.
    """
    # 무인증 모드 — RBAC bypass 와 동일 정책으로 path 자유 진입.
    if principal.get("auth_disabled"):
        return
    authed_tid = principal.get("tenant_id")
    # 인증된 tenant_id 가 없으면 검증 skip — get_current_tenant_id 등 다른 dependency
    # 가 별도로 enforce. (해당 path 가 그 dependency 를 안 쓰는 경우는 기존 동작
    # 그대로 — 회귀 0 보장.)
    if not authed_tid:
        return
    if str(authed_tid) != str(path_tenant_id):
        raise HTTPException(
            status_code=403,
            detail=(
                f"path tenant_id ({path_tenant_id}) 가 인증된 "
                f"tenant_id ({authed_tid}) 와 불일치"
            ),
        )


def _to_response(
    repo: object,
    document_count: int = 0,
    chunk_count: int = 0,
    kind_summary: RepositoryKindSummary | None = None,
) -> RepositoryResponse:
    """ORM 객체를 응답 스키마로 변환."""
    resp = RepositoryResponse.model_validate(repo)
    resp.document_count = document_count
    resp.chunk_count = chunk_count
    if kind_summary is not None:
        resp.kind_summary = kind_summary
    return resp


# alembic 068 — repo 별 kind 분포 집계.
# is_sop=true OR folder.kind='sop' → sop, 그 외는 폴더 kind (NULL 이면 'manual').
# 한 번의 SQL 으로 모든 repo 의 분포를 동시 계산 (N+1 회피).
_KIND_SUMMARY_SQL = sa_text(
    """
    SELECT
      d.repository_id,
      CASE
        WHEN d.is_sop = true OR COALESCE(f.kind, 'manual') = 'sop' THEN 'sop'
        ELSE COALESCE(f.kind, 'manual')
      END AS effective_kind,
      COUNT(*) AS cnt
    FROM documents d
    LEFT JOIN library_folders f ON f.id = d.folder_id
    WHERE d.repository_id = ANY(:repo_ids)
      AND d.status NOT IN ('archived', 'failed')
    GROUP BY d.repository_id, effective_kind
    """
)


async def _load_kind_summaries(
    db: AsyncSession, repo_ids: list[UUID]
) -> dict[UUID, RepositoryKindSummary]:
    """주어진 repo id 목록의 kind 분포를 한 번의 쿼리로 집계."""
    out: dict[UUID, RepositoryKindSummary] = {
        rid: RepositoryKindSummary() for rid in repo_ids
    }
    if not repo_ids:
        return out
    rows = await db.execute(_KIND_SUMMARY_SQL, {"repo_ids": list(repo_ids)})
    for repo_id, kind, cnt in rows.all():
        s = out.setdefault(repo_id, RepositoryKindSummary())
        c = int(cnt or 0)
        if kind == "sop":
            s.sop_doc_count = c
        elif kind == "faq":
            s.faq_doc_count = c
        elif kind == "policy":
            s.policy_doc_count = c
        elif kind == "glossary":
            s.glossary_doc_count = c
        else:
            # manual 또는 알 수 없는 enum (방어) — manual 로 합산.
            s.manual_doc_count = c
    return out


@router.get(
    "/tenants/{tenant_id}/repositories",
    response_model=ApiResponse[PaginatedResponse[RepositoryResponse]],
    summary="저장소 목록 조회",
    description=(
        "특정 tenant 의 저장소 목록을 페이지네이션으로 반환한다. "
        "각 항목은 문서 수 (document_count), 청크 수 (chunk_count), "
        "alembic 068 의 kind 분포 (sop / manual / faq / policy / glossary) 동봉. "
        "is_active 로 활성/비활성 필터링."
    ),
    responses={
        200: {"description": "저장소 목록"},
        403: {"description": "path tenant_id 와 인증된 tenant_id 불일치"},
    },
)
async def list_repositories(
    tenant_id: UUID,
    is_active: bool | None = Query(None, description="활성 상태 필터"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    principal: dict[str, Any] = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaginatedResponse[RepositoryResponse]]:
    """테넌트의 저장소 목록을 조회한다."""
    # Fix C — path tenant_id 가 인증된 tenant_id 와 일치하는지 검증 (cross-tenant 차단).
    _assert_tenant_match(tenant_id, principal)
    svc = RepositoryService(db)
    repos = await svc.list_by_tenant(tenant_id, is_active=is_active, offset=offset, limit=limit)

    # 각 저장소의 문서·청크 수 집계
    from sqlalchemy import func as sa_func, select

    from src.core.models.document import Document
    from src.core.models.block import Block

    # alembic 068 — kind 분포 집계 (1 query 로 모든 repo).
    kind_map = await _load_kind_summaries(db, [r.id for r in repos])

    items = []
    for r in repos:
        doc_count_stmt = (
            select(sa_func.count())
            .select_from(Document)
            .where(Document.repository_id == r.id)
            .where(Document.status.notin_(["archived", "failed"]))
        )
        block_count_stmt = (
            select(sa_func.count())
            .select_from(Block)
            .where(Block.repository_id == r.id)
        )
        doc_count = (await db.execute(doc_count_stmt)).scalar() or 0
        block_count = (await db.execute(block_count_stmt)).scalar() or 0

        items.append(
            _to_response(
                r,
                document_count=doc_count,
                chunk_count=block_count,
                kind_summary=kind_map.get(r.id),
            )
        )

    return ApiResponse(
        data=PaginatedResponse(items=items, total_count=len(items))
    )


@router.post(
    "/tenants/{tenant_id}/repositories",
    response_model=ApiResponse[RepositoryResponse],
    status_code=201,
    summary="저장소 생성",
    description=(
        "신규 저장소를 생성한다. tenant 내 name unique 권장 (충돌 시 409 가능). "
        "라이센스 한도 초과 시 LICENSE_LIMIT_EXCEEDED 에러. "
        "생성 시 자동으로 Qdrant collection + ES index 가 함께 준비된다.\n\n"
        "**무인증 모드** (`LUCAS_AUTH_DISABLED=true`) 에서는 path tenant_id 자유. "
        "인증 모드에서는 인증된 tenant 와 path tenant_id 일치 필수."
    ),
    responses={
        201: {"description": "저장소 생성 성공"},
        403: {"description": "tenant_id 불일치 (cross-tenant 차단)"},
        409: {"description": "name 중복"},
        422: {"description": "validation 실패 (name 길이 등)"},
    },
)
async def create_repository(
    tenant_id: UUID,
    body: RepositoryCreate,
    principal: dict[str, Any] = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RepositoryResponse]:
    """새 저장소를 생성한다."""
    # Fix C — path tenant_id 가 인증된 tenant_id 와 일치하는지 검증 (cross-tenant 차단).
    _assert_tenant_match(tenant_id, principal)
    # 라이선스 한도 검증
    try:
        from src.core.services.license_enforcer import check_repository_limit, get_current_limits

        if not await check_repository_limit(tenant_id, db):
            usage = await get_current_limits(tenant_id, db)
            from src.common.exceptions import LicenseLimitExceededError

            raise LicenseLimitExceededError(
                resource="repositories",
                current=usage["repositories_used"],
                limit=usage["repositories_limit"],
                tier=usage["tier"],
            )
    except ImportError:
        pass

    svc = RepositoryService(db)
    repo = await svc.create(
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        config=body.config,
    )
    return ApiResponse(data=_to_response(repo))


@router.get(
    "/repositories/{repo_id}",
    response_model=ApiResponse[RepositoryResponse],
    summary="저장소 상세 조회",
    description=(
        "ID 로 저장소 상세를 조회한다. kind_summary 필드에 문서 종류별 분포 "
        "(sop / manual / faq / policy / glossary) 포함."
    ),
    responses={
        200: {"description": "저장소 상세"},
        404: {"description": "저장소를 찾을 수 없음"},
    },
)
async def get_repository(
    repo_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RepositoryResponse]:
    """ID로 저장소를 조회한다."""
    svc = RepositoryService(db)
    repo = await svc.get_by_id(repo_id)
    # alembic 068 — kind 분포 동봉 (단일 repo).
    kind_map = await _load_kind_summaries(db, [repo.id])
    return ApiResponse(data=_to_response(repo, kind_summary=kind_map.get(repo.id)))


@router.patch(
    "/repositories/{repo_id}",
    response_model=ApiResponse[RepositoryResponse],
    summary="저장소 수정",
    description=(
        "저장소의 name / description / config / is_active 를 부분 업데이트한다. "
        "None 으로 전달된 필드는 기존 값 유지. config 는 통째 교체 (부분 머지 X). "
        "본인 tenant 의 저장소만 수정 가능 (cross-tenant 차단)."
    ),
    responses={
        200: {"description": "수정된 저장소"},
        404: {"description": "저장소를 찾을 수 없음 (또는 cross-tenant)"},
        422: {"description": "validation 실패"},
    },
)
async def update_repository(
    repo_id: UUID,
    body: RepositoryUpdate,
    # Fix C 참고 — PATCH/DELETE 는 path 에 ``tenant_id`` 가 없고 dependency 가
    # 인증된 tenant_id 를 직접 주입. RepositoryService 가 (repo_id, tenant_id) 쌍으로
    # 권한 확인 → cross-tenant 접근 불가. GET/POST 와 일관 (별도 _assert 불필요).
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RepositoryResponse]:
    """저장소 정보를 수정한다."""
    svc = RepositoryService(db)
    repo = await svc.update(
        repo_id,
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        config=body.config,
        is_active=body.is_active,
    )
    return ApiResponse(data=_to_response(repo))


@router.delete(
    "/repositories/{repo_id}",
    response_model=ApiResponse[dict],
    summary="저장소 삭제",
    description=(
        "저장소를 소프트 삭제한다 (is_active=false). 실제 데이터 (documents/blocks) 와 "
        "벡터 인덱스 (Qdrant/ES) 는 보존 — 운영자가 별도 reprocess/admin_reset 으로 "
        "물리 삭제 필요. 본인 tenant 의 저장소만 삭제 가능."
    ),
    responses={
        200: {"description": "{deleted: true}"},
        404: {"description": "저장소를 찾을 수 없음"},
    },
)
async def delete_repository(
    repo_id: UUID,
    # Fix C 참고 — DELETE 도 dependency 로 tenant_id 주입 (PATCH 와 동일).
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """저장소를 소프트 삭제한다."""
    svc = RepositoryService(db)
    await svc.delete(repo_id, tenant_id=tenant_id)
    return ApiResponse(data={"deleted": True})
