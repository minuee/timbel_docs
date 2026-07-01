"""문서 CRUD + 업로드 + 파이프라인 상태 + 분석 + 버전 관리 API 라우터."""

import json
import mimetypes
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id, get_current_user_id
from src.api.schemas.analysis import AnalysisReportResponse
from src.api.schemas.common import ApiResponse, PaginatedResponse
from src.api.schemas.document import (
    DocumentCreate,
    DocumentResponse,
    DocumentUpdate,
    PipelineStageInfo,
    PipelineStatusResponse,
    ProcessingDocumentResponse,
    SearchExclusionRequest,
    StatusChangeRequest,
)
from src.api.schemas.version import RollbackResponse, VersionHistoryItem, VersionUploadResponse
from src.api.utils.upload import compute_file_sha256, detect_format, validate_file_size
from src.pipeline.storage.source_files import (
    ext_from as _src_ext_from,
    materialize_source as _materialize_source,
    cleanup_temp as _cleanup_src_temp,
    store_source_bytes as _store_source_bytes,
)
from src.common.constants import (
    TOPIC_DOCUMENT_BLOCKED,
    TOPIC_DOCUMENT_PARSED,
    TOPIC_DOCUMENT_UPLOADED,
)
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.models.document import Chunk, Document
from src.core.models.repository import Repository
from src.core.services.audit_service import record_action
from src.core.exceptions import InvalidDocumentStatusTransitionError
from src.core.services.document_service import DocumentService
from src.search.cache_invalidator import invalidate_repository_cache
from src.search.payload_sync import sync_document_status, sync_search_excluded
from src.core.services.version_service import DocumentVersionService
from src.pipeline.analyzers.document_analyzer import DocumentAnalyzer

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Batch 8 Task 21: legacy apply/reject_classification → activation service shim
# ---------------------------------------------------------------------------


def _activation_shim(method: str, doc_id: str, *, user_id: str, **kwargs) -> None:
    """sync ActivationService 를 새 connection 으로 호출. 실패는 삼킴 (레거시 경로 보호).

    KMS-only 배포 (Lucas-KMS 단독, agent_framework 미설치) 에서는 ImportError
    발생 → 본 함수는 즉시 return 으로 graceful no-op. 통합 배포 (Locus) 에서만
    실제 ActivationService 호출.

    Phase 3 (packaging) 시점에 본 함수는 src/common/agent_hook.py 의
    AgentClassificationHook 인터페이스로 전환 예정. 현재는 호환성 보존.
    """
    import os
    from sqlalchemy import create_engine

    try:
        from src.agent_framework.activation.service import (
            ActivationService,
            ArtifactNotFound,
            UnknownArtifactType,
        )
        from src.agent_framework.activation.state import InvalidTransition
    except Exception:
        # KMS-only 배포 — agent_framework 미존재 → no-op
        return

    sync_url = (
        os.environ.get("DATABASE_URL", "")
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
    )
    if not sync_url:
        return

    try:
        eng = create_engine(sync_url)
        conn = eng.connect()
        try:
            svc = ActivationService(db_session=conn)
            try:
                getattr(svc, method)("document", str(doc_id), user_id=user_id, **kwargs)
            except (UnknownArtifactType, ArtifactNotFound, InvalidTransition):
                # 이미 active 이거나 전이 불가 — 레거시 테스트 깨지 않게 silent
                pass
        finally:
            conn.close()
    except Exception as e:
        logger.warning("activation_shim_failed", method=method, doc_id=str(doc_id), error=str(e))


def _to_response(doc: object) -> DocumentResponse:
    """ORM 객체를 응답 스키마로 변환."""
    resp = DocumentResponse.model_validate(doc)
    # category_ids 추출 (ORM 관계에서)
    categories = getattr(doc, "categories", None)
    if categories:
        resp.category_ids = [c.id for c in categories]
    # repository_name 주입 (ORM 관계에서)
    repo = getattr(doc, "repository", None)
    if repo:
        resp.repository_name = getattr(repo, "name", None)
    return resp


async def _find_in_flight_duplicates(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    repository_id: UUID,
    title: str,
) -> list[Document]:
    """동일 repo/title 로 처리 중이거나 이미 활성인 문서 목록을 반환.

    Document 에는 tenant_id 가 없고 repository 에 tenant 가 귀속됨. 상위 라우터에서 repo 의
    tenant 소속을 이미 검증하므로 여기선 repo+title 만 체크해도 테넌트 경계가 새지 않는다.

    [수정 2026-06-08]
    이슈 내용: AICM 업로드 후 KMS 직접 업로드로 같은 문서가 동일 저장소에 중복 적재됨
    원인: 기존 검사가 processing/pending_review(처리중)만 봐서, 첫 문서가 active 완료된 뒤
          도착한 동일 제목 업로드는 검사를 빠져나가 중복 생성됨
    수정 내용: active 도 검사 대상에 포함(동일 제목 활성 문서가 있으면 force_new 없이는 차단).
              버전 업로드는 별도 엔드포인트(upload_new_version)를 사용하므로 영향 없음.
    """
    result = await db.execute(
        select(Document).where(
            Document.repository_id == repository_id,
            Document.title == title,
            Document.status.in_(("processing", "pending_review", "active")),
        )
    )
    return list(result.scalars().all())


async def _find_document_by_source_hash(
    db: AsyncSession,
    *,
    repository_id: UUID,
    source_hash: str,
) -> Document | None:
    """동일 repo 안에서 같은 원본 파일 해시(source_sha256)를 가진 비-archived 문서를 반환.

    동일 내용(바이트 동일) 파일의 중복 적재를 멱등 처리하기 위한 조회. 해시는 업로드 시
    processing_meta.source_sha256 에 기록된다(별도 컬럼/마이그레이션 불필요).
    """
    result = await db.execute(
        select(Document).where(
            Document.repository_id == repository_id,
            Document.status != "archived",
            Document.processing_meta["source_sha256"].astext == source_hash,
        )
    )
    return result.scalars().first()


async def _archive_in_flight_duplicates(
    db: AsyncSession,
    *,
    docs: list[Document],
    reason: str,
) -> None:
    """중복 업로드 시 기존 in-flight 문서들을 archived 로 전환하고 pause/resume 상태를 정리."""
    now = datetime.utcnow().isoformat()
    for doc in docs:
        doc.status = "archived"
        await sync_document_status(doc.id, "archived", db)
        meta = {**(doc.processing_meta or {})}
        for key in (
            "control_signal",
            "paused_before_stage",
            "paused_event_topic",
            "paused_event_data",
            "step_by_step_resume_pending",
        ):
            meta.pop(key, None)
        meta["archived_at"] = now
        meta["archive_reason"] = reason
        doc.processing_meta = meta
    await db.flush()
    logger.info(
        "in_flight_duplicates_archived",
        count=len(docs),
        reason=reason,
        document_ids=[str(d.id) for d in docs],
    )


@router.get(
    "/repositories/{repo_id}/documents",
    response_model=ApiResponse[PaginatedResponse[DocumentResponse]],
    summary="문서 목록 조회",
)
async def list_documents(
    repo_id: UUID,
    status: str | None = Query(None, description="상태 필터"),
    category_id: UUID | None = Query(None, description="카테고리 필터"),
    document_type_id: UUID | None = Query(None, description="문서타입 필터"),
    offset: int = Query(0, ge=0),
    # 2026-05-07 — DocsTab 가 cross-tenant 단일 fetch 라 le=100 cap 으로 큰 repo
    # (samchully_sop 123 doc 등) 의 51~ 번째 doc 이 라이브러리에서 안 보였음.
    # le=500 으로 완화 (응답 size 는 메타만이라 부담 적음).
    limit: int = Query(50, ge=1, le=500),
    page: int | None = Query(None, ge=1, description="페이지 번호 (1-based, offset 대체)"),
    page_size: int | None = Query(
        None, ge=1, le=500, description="페이지 크기 (limit 대체)"
    ),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaginatedResponse[DocumentResponse]]:
    """저장소의 문서 목록을 조회한다."""
    # page/page_size → offset/limit 변환 (프론트엔드 호환)
    if page is not None and page >= 1:
        effective_limit = page_size if page_size and page_size >= 1 else limit
        effective_offset = (page - 1) * effective_limit
    else:
        effective_offset = offset
        effective_limit = page_size if page_size and page_size >= 1 else limit

    svc = DocumentService(db)
    docs = await svc.list_by_repository(
        repo_id,
        tenant_id=tenant_id,
        status=status,
        category_id=category_id,
        document_type_id=document_type_id,
        offset=effective_offset,
        limit=effective_limit,
    )
    # 전체 건수 조회
    total = await svc.count_by_repository(
        repo_id,
        tenant_id=tenant_id,
        status=status,
        category_id=category_id,
        document_type_id=document_type_id,
    )
    items = [_to_response(d) for d in docs]
    return ApiResponse(
        data=PaginatedResponse(items=items, total_count=total)
    )


# ---------------------------------------------------------------------------
# 문서 처리 상태 관리 — 조회
# /documents/{doc_id} 와 경로 충돌 방지를 위해 /pipeline/documents 로 분리
# ---------------------------------------------------------------------------


@router.get(
    "/pipeline/documents",
    response_model=ApiResponse[list[ProcessingDocumentResponse]],
    summary="처리중/실패 문서 목록",
)
async def list_processing_documents(
    status: str = Query("processing", description="processing 또는 failed"),
    limit: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ProcessingDocumentResponse]]:
    """처리 중이거나 실패한 문서 목록을 반환한다.

    테넌트 소속 모든 저장소의 문서를 대상으로 조회한다.
    """
    if status not in ("processing", "failed"):
        raise HTTPException(status_code=400, detail="status는 processing 또는 failed만 가능합니다.")

    from sqlalchemy.orm import selectinload

    stmt = (
        select(Document)
        .join(Repository)
        .options(selectinload(Document.repository))
        .where(Repository.tenant_id == tenant_id)
        .where(Document.status == status)
        .order_by(Document.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()

    items = []
    for doc in docs:
        meta = doc.processing_meta or {}
        items.append(
            ProcessingDocumentResponse(
                id=doc.id,
                repository_id=doc.repository_id,
                repository_name=getattr(doc.repository, "name", None) if doc.repository else None,
                title=doc.title,
                status=doc.status,
                source_format=doc.source_format,
                processing_meta=meta,
                current_stage=meta.get("current_stage"),
                error_message=meta.get("error") or meta.get("error_message"),
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
        )

    return ApiResponse(data=items)


@router.get(
    "/documents/failed",
    response_model=ApiResponse[list[ProcessingDocumentResponse]],
    summary="실패 문서 목록",
)
async def list_failed_documents(
    limit: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ProcessingDocumentResponse]]:
    """실패한 문서 목록을 반환한다. /pipeline/documents?status=failed 의 alias."""
    return await list_processing_documents(
        status="failed", limit=limit, tenant_id=tenant_id, db=db
    )


@router.get(
    "/documents/{doc_id}",
    response_model=ApiResponse[DocumentResponse],
    summary="문서 상세 조회",
)
async def get_document(
    doc_id: UUID,
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DocumentResponse]:
    """ID로 문서를 조회한다. platform_admin은 모든 테넌트 문서 접근 가능."""
    svc = DocumentService(db)
    # platform_admin이면 테넌트 필터 우회
    user_role = getattr(request.state, "user_role", None)
    effective_tid = None if user_role == "platform_admin" else tenant_id
    doc = await svc.get_by_id(doc_id, tenant_id=effective_tid)

    # 감사 로그: 문서 열람
    user_id = getattr(request.state, "user_id", None)
    record_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action="VIEW",
        resource_type="document",
        resource_id=doc_id,
        detail={"title": doc.title},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )

    return ApiResponse(data=_to_response(doc))


@router.get(
    "/documents/{doc_id}/auto_classification",
    response_model=ApiResponse[dict],
    summary="문서 자동 분류 결과 조회 (Stage B-Core-4)",
)
async def get_document_auto_classification(
    doc_id: UUID,
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """processing_meta.auto_classification 을 반환한다.

    classify_worker 가 아직 완료하지 않았거나 feature flag off 인 경우 404.
    """
    svc = DocumentService(db)
    user_role = getattr(request.state, "user_role", None)
    effective_tid = None if user_role == "platform_admin" else tenant_id
    doc = await svc.get_by_id(doc_id, tenant_id=effective_tid)

    meta = doc.processing_meta or {}
    classification = meta.get("auto_classification")
    if not classification:
        raise HTTPException(
            status_code=404,
            detail="auto_classification not available yet — classifier 미완료 또는 비활성.",
        )

    return ApiResponse(data=classification)


# ---------------------------------------------------------------------------
# auto_classification — 적용(accept) / 무시(reject)  [Phase B-2]
# ---------------------------------------------------------------------------


class ApplyClassificationRequest(BaseModel):
    """apply_classification 요청. 둘 다 None 이면 suggested_* 값을 사용."""

    repository_name: str | None = None
    document_type: str | None = None


async def _get_or_create_repository(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
) -> Repository:
    """tenant 내 repository 를 name 으로 조회. 없으면 기본 설정으로 생성."""
    stmt = select(Repository).where(
        Repository.tenant_id == tenant_id,
        Repository.name == name,
    )
    result = await db.execute(stmt)
    repo = result.scalar_one_or_none()
    if repo is not None:
        return repo
    repo = Repository(
        tenant_id=tenant_id,
        name=name,
        description="auto_classification 에 의해 자동 생성",
        config={},
        search_mode="hybrid",
        display_config={},
        llm_config={},
        is_active=True,
    )
    db.add(repo)
    await db.flush()
    logger.info(
        "repository_auto_created_for_classification",
        tenant_id=str(tenant_id),
        name=name,
        repository_id=str(repo.id),
    )
    return repo


async def _get_or_create_document_type(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
) -> UUID:
    """tenant 내 document_type 을 name 으로 조회. 없으면 생성해 id 반환."""
    from src.core.models.document_type import DocumentType

    stmt = select(DocumentType).where(
        DocumentType.tenant_id == tenant_id,
        DocumentType.name == name,
    )
    result = await db.execute(stmt)
    dt = result.scalar_one_or_none()
    if dt is not None:
        return dt.id
    dt = DocumentType(
        tenant_id=tenant_id,
        name=name,
        description="auto_classification 에 의해 자동 생성",
        is_system=False,
    )
    db.add(dt)
    await db.flush()
    logger.info(
        "document_type_auto_created_for_classification",
        tenant_id=str(tenant_id),
        name=name,
        document_type_id=str(dt.id),
    )
    return dt.id


@router.post(
    "/documents/{doc_id}/apply_classification",
    response_model=ApiResponse[dict],
    summary="문서 자동 분류 결과를 실제 저장소/문서타입으로 적용",
)
async def apply_classification(
    doc_id: UUID,
    body: ApplyClassificationRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> ApiResponse[dict]:
    """auto_classification.suggested_* 를 실제 repository_id / document_type_id 로 반영한다.

    - body.repository_name / body.document_type 이 주어지면 override,
      없으면 processing_meta.auto_classification 의 suggested_* 값을 사용.
    - repository 또는 document_type 이 tenant 에 존재하지 않으면 자동 생성한다.
    - 적용 후 processing_meta.auto_classification.applied=true, applied_at 기록.
    """
    svc = DocumentService(db)
    # tenant 경계 — 다른 tenant 의 문서면 DocumentNotFound 로 403 효과.
    try:
        doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)
    except Exception:
        raise HTTPException(status_code=404, detail="document not found or tenant mismatch")

    meta = dict(doc.processing_meta or {})
    classification = meta.get("auto_classification") or {}
    if not classification:
        raise HTTPException(
            status_code=400,
            detail="auto_classification not available — 적용할 분류 결과가 없습니다.",
        )

    repo_name = body.repository_name or classification.get("suggested_repository_name")
    doctype_name = body.document_type or classification.get("suggested_document_type")
    if not repo_name and not doctype_name:
        raise HTTPException(
            status_code=400,
            detail="repository_name / document_type 중 하나라도 결정할 수 없습니다.",
        )

    changed: dict[str, object] = {}

    # repository 재배치
    if repo_name:
        target_repo = await _get_or_create_repository(
            db, tenant_id=tenant_id, name=repo_name
        )
        if target_repo.id != doc.repository_id:
            doc.repository_id = target_repo.id
        changed["repository_id"] = str(target_repo.id)
        changed["repository_name"] = target_repo.name

    # document_type 설정
    if doctype_name:
        dt_id = await _get_or_create_document_type(
            db, tenant_id=tenant_id, name=doctype_name
        )
        doc.document_type_id = dt_id
        changed["document_type_id"] = str(dt_id)
        changed["document_type"] = doctype_name

    # processing_meta 갱신 — applied 플래그 + timestamp
    from datetime import datetime as _dt, timezone as _tz

    applied_class = dict(classification)
    applied_class["applied"] = True
    applied_class["applied_at"] = _dt.now(_tz.utc).isoformat()
    applied_class["applied_repository_name"] = changed.get("repository_name")
    applied_class["applied_document_type"] = changed.get("document_type")
    meta["auto_classification"] = applied_class
    doc.processing_meta = meta

    await db.flush()

    logger.info(
        "auto_classification_applied",
        document_id=str(doc_id),
        tenant_id=str(tenant_id),
        changed=changed,
    )

    # 감사 로그
    record_action(
        tenant_id=tenant_id,
        user_id=None,
        action="UPDATE",
        resource_type="document",
        resource_id=doc_id,
        detail={"apply_classification": changed},
    )

    # Batch 8 Task 21: activation service shim — apply_classification 은 의미상 approve
    # 와 동격. 기존 DB flush 가 커밋된 뒤 별도 connection 으로 상태 전이를 기록한다.
    import asyncio as _asyncio

    shim_user = x_user_id or "legacy_shim"
    try:
        await db.commit()  # 먼저 레거시 변경 커밋 (shim 이 별도 connection 이므로 가시성 확보)
    except Exception:
        # AsyncSession 이 autocommit 이거나 dependency override 라면 commit 불필요
        pass
    await _asyncio.to_thread(
        _activation_shim, "approve", str(doc_id), user_id=shim_user, action="add"
    )

    return ApiResponse(
        data={
            "document_id": str(doc_id),
            "applied": True,
            **changed,
        }
    )


@router.post(
    "/documents/{doc_id}/reject_classification",
    response_model=ApiResponse[dict],
    summary="문서 자동 분류 결과 무시 (UI 에 배너 숨김)",
)
async def reject_classification(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> ApiResponse[dict]:
    """processing_meta.auto_classification.applied=false 로 마킹.

    파괴적이지 않은 soft flag — 원본 suggested_* 는 유지하되 UI 에서 배너가
    더 이상 나타나지 않도록 한다.
    """
    svc = DocumentService(db)
    try:
        doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)
    except Exception:
        raise HTTPException(status_code=404, detail="document not found or tenant mismatch")

    meta = dict(doc.processing_meta or {})
    classification = meta.get("auto_classification") or {}
    if not classification:
        raise HTTPException(
            status_code=400,
            detail="auto_classification not available — 무시할 분류 결과가 없습니다.",
        )

    from datetime import datetime as _dt, timezone as _tz

    rejected_class = dict(classification)
    rejected_class["applied"] = False
    rejected_class["rejected_at"] = _dt.now(_tz.utc).isoformat()
    meta["auto_classification"] = rejected_class
    doc.processing_meta = meta

    await db.flush()

    logger.info(
        "auto_classification_rejected",
        document_id=str(doc_id),
        tenant_id=str(tenant_id),
    )

    record_action(
        tenant_id=tenant_id,
        user_id=None,
        action="UPDATE",
        resource_type="document",
        resource_id=doc_id,
        detail={"reject_classification": True},
    )

    # Batch 8 Task 21: activation service shim — reject_classification → svc.reject
    import asyncio as _asyncio

    shim_user = x_user_id or "legacy_shim"
    try:
        await db.commit()
    except Exception:
        pass
    await _asyncio.to_thread(
        _activation_shim,
        "reject",
        str(doc_id),
        user_id=shim_user,
        reason="rejected via legacy apply_classification endpoint",
    )

    return ApiResponse(
        data={
            "document_id": str(doc_id),
            "applied": False,
        }
    )


@router.post(
    "/documents",
    response_model=ApiResponse[DocumentResponse],
    status_code=201,
    summary="문서 생성 (메타데이터만)",
)
async def create_document(
    body: DocumentCreate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DocumentResponse]:
    """메타데이터만으로 문서를 생성한다 (파일 없이)."""
    # 라이선스 한도 검증
    try:
        from src.core.services.license_enforcer import check_document_limit, get_current_limits

        if not await check_document_limit(tenant_id, db):
            usage = await get_current_limits(tenant_id, db)
            from src.common.exceptions import LicenseLimitExceededError

            raise LicenseLimitExceededError(
                resource="documents",
                current=usage["documents_used"],
                limit=usage["documents_limit"],
                tier=usage["tier"],
            )
    except ImportError:
        pass

    svc = DocumentService(db)
    doc = await svc.create(
        repository_id=body.repository_id,
        tenant_id=tenant_id,
        title=body.title,
        description=body.description,
        document_type_id=body.document_type_id,
        category_ids=body.category_ids,
        created_by=user_id,
    )

    # 감사 로그: 문서 생성
    record_action(
        tenant_id=tenant_id,
        user_id=user_id,
        action="CREATE",
        resource_type="document",
        resource_id=doc.id,
        detail={"title": body.title, "repository_id": str(body.repository_id)},
    )

    return ApiResponse(data=_to_response(doc))


@router.post(
    "/documents/upload",
    response_model=ApiResponse[dict],
    status_code=201,
    summary="문서 업로드 (multipart/form-data)",
)
async def upload_document(
    file: UploadFile,
    repository_id: UUID = Form(...),
    title: str | None = Form(None),
    category_ids: str = Form("[]"),
    document_type_id: UUID | None = Form(None),
    config_override: str | None = Form(None),
    step_by_step: bool = Form(False, description="단계별 확인 모드 — 각 단계 완료 후 자동 일시정지"),
    force_new: bool = Form(False, description="동일 제목의 진행 중 문서가 있을 때 기존 것을 archived 처리하고 새로 시작"),
    document_id: UUID | None = Form(None, description="강제할 문서 ID. 제공 시 동일 id 기존 문서를 교체하고 dedup 검사를 건너뛴다(외부 id 통일·재업로드 시 동일 id 재사용)."),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """문서 파일을 업로드하고 파이프라인을 자동 트리거한다.

    처리 순서:
    0. 라이선스 한도 검증
    1. 파일 검증 (크기, 포맷)
    2. 중복 업로드 검사 (동일 tenant/repo/title 의 processing 문서)
    3. 파일 저장 (/data/uploads/{tenant_id}/{repo_id}/)
    4. Document 레코드 생성 (status=processing)
    5. Kafka 이벤트 발행 (aicm.document.uploaded)
    6. 즉시 응답 (document_id + status)
    """
    # 0. 라이선스 한도 검증
    try:
        from src.core.services.license_enforcer import check_document_limit, get_current_limits

        if not await check_document_limit(tenant_id, db):
            usage = await get_current_limits(tenant_id, db)
            from src.common.exceptions import LicenseLimitExceededError

            raise LicenseLimitExceededError(
                resource="documents",
                current=usage["documents_used"],
                limit=usage["documents_limit"],
                tier=usage["tier"],
            )
    except ImportError:
        pass  # license_enforcer 모듈 미설치 시 무시

    # 1. 파일 검증
    await validate_file_size(file)
    source_format = detect_format(file.filename or "unknown", file.content_type)

    # 2. 중복 적재 검사
    resolved_title = title or file.filename or "Untitled"

    # 2-z. document_id 강제(외부 id 통일 / 재업로드 시 동일 id 재사용): dedup 우회 + 동일 id 기존 문서 교체.
    #      수동입력 문서 수정이 매번 새 KMS doc(새 rag_doc_id)을 만들어 어드바이저/콜봇 참조가 흔들리던 문제를
    #      막기 위해, AICM 문서 id 를 강제하면 같은 id 로 재생성한다(블록/벡터 정리는 호출측 delete_document 가 선행).
    if document_id is not None:
        # 동일 id 기존 문서 교체 — 대상 저장소로 스코프(다른 repo 의 동일 id 문서는 건드리지 않음).
        # 블록/벡터(Qdrant/ES) 정리는 호출측 _rag_reindex 의 delete_document 가 선행 처리한다(여기선 행 안전망).
        _existing_forced = (
            await db.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.repository_id == repository_id,
                )
            )
        ).scalar_one_or_none()
        if _existing_forced is not None:
            await db.delete(_existing_forced)
            await db.flush()
            logger.info("upload_forced_id_replaced_existing", document_id=str(document_id))

    # 2-a. 동일 내용(파일 해시) 중복 — 같은 바이트 파일이 이미 있으면 신규 생성 없이 기존 문서 반환(멱등).
    #      AICM 업로드 후 KMS 직접 업로드로 같은 파일이 두 번 적재되던 중복을 원천 차단한다.
    source_sha256 = await compute_file_sha256(file)
    if document_id is None and not force_new:
        dup = await _find_document_by_source_hash(
            db, repository_id=repository_id, source_hash=source_sha256
        )
        if dup is not None:
            return ApiResponse(
                data={
                    "document_id": str(dup.id),
                    "status": dup.status,
                    "deduplicated": True,
                    "message": "동일 내용의 문서가 이미 존재하여 기존 문서를 반환합니다.",
                }
            )

    # 2-b. 동일 제목(처리중/활성) 중복 — 내용이 달라도 같은 제목이면 force_new 없이는 차단.
    in_flight = await _find_in_flight_duplicates(
        db, tenant_id=tenant_id, repository_id=repository_id, title=resolved_title
    ) if document_id is None else []
    if in_flight:
        if not force_new:
            existing_ids = [str(d.id) for d in in_flight]
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "duplicate_title_upload",
                    "message": (
                        f"동일 제목 '{resolved_title}' 의 문서가 이미 존재합니다(처리 중이거나 활성). "
                        "기존 문서를 이어서 진행/사용하거나, 새 버전이면 버전 업로드를 사용하세요. "
                        "강제로 새로 시작하려면 force_new=true 를 지정하세요."
                    ),
                    "existing_document_ids": existing_ids,
                },
            )
        # force_new=true: 기존 processing/active 문서들을 archived 로 정리
        await _archive_in_flight_duplicates(
            db, docs=in_flight, reason="replaced_by_new_upload"
        )

    # 3. DB 레코드 생성 (source_file 은 MinIO 저장 후 채운다)
    svc = DocumentService(db)
    parsed_category_ids = json.loads(category_ids) if category_ids else []
    doc = await svc.create(
        repository_id=repository_id,
        tenant_id=tenant_id,
        title=resolved_title,
        source_file=None,
        source_format=source_format,
        document_type_id=document_type_id,
        # force-id 는 dormant: document_id 가 있을 때만 create 로 전달(원본 create 는 이 인자 미지원).
        # repo 경로는 document_id=None 이라 전달되지 않아 원본과 호환된다.
        **({"document_id": document_id} if document_id is not None else {}),
        category_ids=[UUID(cid) if isinstance(cid, str) else cid for cid in parsed_category_ids],
        created_by=user_id,
    )

    # 3-b. 원본을 MinIO 단일 원천에 저장 → object key 를 source_file 로 기록한다.
    #      로컬 FS(/data/uploads) 미사용 — EKS 에서 api·worker pod 가 볼륨을 공유하지 않아
    #      parsing 단계가 "원본 파일 없음"으로 실패하던 문제를 근본 해소한다.
    await file.seek(0)
    _contents = await file.read()
    file_path = await _store_source_bytes(
        str(tenant_id), str(doc.id), _contents,
        ext=_src_ext_from(file.filename, source_format),
        content_type=file.content_type or "",
    )
    doc.source_file = file_path

    # 상태를 processing 으로 전이
    await svc.transition_status(doc.id, target_status="processing")

    # 원본 파일 해시 기록 — 이후 동일 내용 업로드의 dedup 키로 사용(2-a 참고).
    meta = {**(doc.processing_meta or {})}
    meta["source_sha256"] = source_sha256
    # step_by_step 모드: processing_meta에 저장 → 워커가 각 단계 완료 후 자동 pause
    if step_by_step:
        meta["step_by_step"] = True
    doc.processing_meta = meta
    await db.flush()

    # 4. Kafka 이벤트 발행 (best-effort, 실패해도 문서는 생성됨)
    await _publish_upload_event(
        document_id=doc.id,
        tenant_id=tenant_id,
        repository_id=repository_id,
        source_format=source_format,
        source_path=file_path,
        config_override=json.loads(config_override) if config_override else None,
        file_size_bytes=len(_contents),
    )

    return ApiResponse(
        data={
            "document_id": str(doc.id),
            "status": "processing",
            "step_by_step": step_by_step,
            "message": "문서가 업로드되었습니다." + (
                " 단계별 확인 모드: 각 단계 완료 후 자동 정지됩니다. resume으로 다음 단계를 진행하세요."
                if step_by_step else " 처리가 완료되면 검색 가능합니다."
            ),
        }
    )


@router.post(
    "/repositories/{repo_id}/documents/upload",
    response_model=ApiResponse[dict],
    status_code=201,
    summary="저장소별 문서 업로드 (V2 alias)",
)
async def upload_to_repository(
    repo_id: UUID,
    file: UploadFile,
    title: str | None = Form(None),
    category_ids: str = Form("[]"),
    document_type_id: UUID | None = Form(None),
    config_override: str | None = Form(None),
    step_by_step: bool = Form(False),
    force_new: bool = Form(False),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """저장소 경로 기반 문서 업로드. /documents/upload 의 alias."""
    return await upload_document(
        file=file,
        repository_id=repo_id,
        title=title,
        category_ids=category_ids,
        document_type_id=document_type_id,
        config_override=config_override,
        step_by_step=step_by_step,
        force_new=force_new,
        # 함수 직접 호출이라 FastAPI Form 기본값(Form(None) 객체)이 누수되지 않도록 명시 전달.
        # force-id 는 의도적 dormant — repo 경로에서는 None 으로 비활성 유지.
        document_id=None,
        tenant_id=tenant_id,
        user_id=user_id,
        db=db,
    )


@router.get(
    "/documents/{doc_id}/preview",
    response_model=ApiResponse[dict],
    summary="문서 블럭 프리뷰",
)
async def get_document_preview(
    doc_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """문서의 블럭 목록을 프리뷰 형태로 반환한다."""
    from src.core.models.block import Block

    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    stmt = (
        select(Block)
        .where(Block.document_id == doc_id)
        .order_by(Block.block_index)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    blocks = result.scalars().all()

    from sqlalchemy import func as sa_func

    count_stmt = (
        select(sa_func.count())
        .select_from(Block)
        .where(Block.document_id == doc_id)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    block_data = []
    for b in blocks:
        source_loc = b.source_location or {}
        if hasattr(source_loc, "model_dump"):
            source_loc = source_loc.model_dump()
        block_data.append(
            {
                "id": str(b.id),
                "index": b.block_index,
                "type": b.block_type,
                "content": b.content,
                "page": source_loc.get("page_number") if isinstance(source_loc, dict) else None,
                "token_count": b.token_count,
                "metadata": b.meta_info if hasattr(b, "meta_info") else {},
            }
        )

    return ApiResponse(
        data={
            "document_id": str(doc.id),
            "title": doc.title,
            "total_blocks": total,
            "blocks": block_data,
        }
    )


@router.patch(
    "/documents/{doc_id}",
    response_model=ApiResponse[DocumentResponse],
    summary="문서 수정",
)
async def update_document(
    doc_id: UUID,
    body: DocumentUpdate,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[DocumentResponse]:
    """문서 메타데이터를 수정한다.

    status 가 함께 전달되면 transition_status 로 상태 전이까지 수행한다
    (예: pending_review → active 활성화).
    """
    svc = DocumentService(db)
    if body.status is not None:
        try:
            await svc.transition_status(
                doc_id,
                target_status=body.status,
                tenant_id=tenant_id,
            )
        except InvalidDocumentStatusTransitionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    doc = await svc.update(
        doc_id,
        tenant_id=tenant_id,
        title=body.title,
        description=body.description,
        document_type_id=body.document_type_id,
        category_ids=body.category_ids,
        is_sop=body.is_sop,
    )

    # 감사 로그: 문서 수정
    record_action(
        tenant_id=tenant_id,
        user_id=None,
        action="UPDATE",
        resource_type="document",
        resource_id=doc_id,
        detail={"updated_fields": body.model_dump(exclude_unset=True)},
    )

    await invalidate_repository_cache(doc.repository_id)
    return ApiResponse(data=_to_response(doc))


async def _reset_blocks_and_indexes_for_reprocess(
    *,
    doc_id: UUID,
    tenant_id: UUID,
    repository_id: UUID,
    db: AsyncSession,
) -> dict[str, object]:
    """retry from_stage='parsing' 의 사전 정리 — 기존 blocks (DB) + ES /
    Qdrant chunks 의 해당 document 항목을 모두 삭제.

    D85c-잔존 reprocess (2026-05-14, GPT-5.5 verdict #6) — retry endpoint 가
    publish-only 였던 결함 직접 fix. worker 가 새 blocks INSERT 시 *duplicate
    누적* 차단.

    GPT-5.5 verdict v1 보강 (2026-05-14):
    - 반환 shape: {"ok": bool, "errors": list[str], "counts": {db_blocks, es, qdrant}}
    - DB cleanup 실패 시 ok=False — caller 가 publish skip 결정 가능.
    - tenant slug lookup 실패 시 진행 거부 (ES/Qdrant index name 계산 불가).
    - Qdrant sync client 호출은 asyncio.to_thread 로 격리.

    *ES filter 의 tenant_id*: Lucas-KMS Phase 2 T2.6 부터 ES mapping 에
    ``tenant_id`` keyword field 추가. tenant 격리는 *index name* +
    ``tenant_id`` term filter 의 *이중 안전망*. 본 cleanup 도 함수 인자의
    ``tenant_id`` 를 명시적으로 must filter 에 포함시킨다.
    """
    import asyncio as _asyncio

    from sqlalchemy import delete as _sa_delete
    from sqlalchemy import text as _sa_text

    from src.common.config import settings as _settings
    from src.core.models.block import Block as _Block
    from src.core.models.repository import Repository as _Repository
    from src.core.models.tenant import Tenant as _Tenant

    counts: dict[str, int] = {"db_blocks": 0, "es": 0, "qdrant": 0}
    errors: list[str] = []

    # 0) Pre-check (GPT-5.5 v2 #2) — repository/tenant 검증을 DB delete 전에.
    # repository 가 *tenant_id 와 매칭* 안 하면 cross-tenant 호출 — 거부.
    tenant_slug: str | None = None
    try:
        repo_stmt = (
            select(_Repository)
            .where(_Repository.id == repository_id)
            .where(_Repository.tenant_id == tenant_id)
        )
        repo = (await db.execute(repo_stmt)).scalar_one_or_none()
        if repo:
            tenant_stmt = select(_Tenant).where(_Tenant.id == repo.tenant_id)
            tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
            if tenant:
                tenant_slug = tenant.slug
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reprocess_cleanup_tenant_lookup_failed",
            doc_id=str(doc_id),
            error=str(exc),
        )
        errors.append(f"tenant_lookup: {exc}")

    if not tenant_slug:
        # cleanup prerequisite 실패 — DB / ES / Qdrant 모두 손대지 않음.
        errors.append("tenant_slug_unresolved_pre_cleanup")
        return {"ok": False, "errors": errors, "counts": counts}

    # 1) DB blocks DELETE (cascade FK 영향 — block-owned child rows)
    try:
        result = await db.execute(
            _sa_delete(_Block).where(_Block.document_id == doc_id)
        )
        counts["db_blocks"] = int(result.rowcount or 0)
        # additional safety — chunks 테이블 (legacy) 도 정리.
        # chunks 는 documents 의 FK 라 blocks DELETE 만으로는 정리 안 됨.
        await db.execute(
            _sa_text("DELETE FROM chunks WHERE document_id = :did"),
            {"did": str(doc_id)},
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning(
            "reprocess_cleanup_db_blocks_failed",
            doc_id=str(doc_id),
            error=str(exc),
        )
        errors.append(f"db_blocks: {exc}")
        # DB cleanup 실패는 critical — caller 가 publish skip 결정.
        return {"ok": False, "errors": errors, "counts": counts}

    # 3) ES delete_by_query — tenant_id + repository_id + document_id guard
    # Lucas-KMS Phase 2 T2.6 — payload-level tenant_id must filter (이중 안전망).
    try:
        from elasticsearch import AsyncElasticsearch

        from src.search.hybrid.es_keyword import build_block_es_index_name

        es_index = build_block_es_index_name(tenant_slug)
        es_client = AsyncElasticsearch(hosts=[_settings.ELASTICSEARCH_URL])
        try:
            resp = await es_client.delete_by_query(
                index=es_index,
                body={
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"tenant_id": str(tenant_id)}},
                                {"term": {"repository_id": str(repository_id)}},
                                {"term": {"document_id": str(doc_id)}},
                            ]
                        }
                    }
                },
                refresh=True,
                conflicts="proceed",
                ignore=[404],
            )
            counts["es"] = int((resp or {}).get("deleted", 0))
        finally:
            await es_client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reprocess_cleanup_es_failed",
            doc_id=str(doc_id),
            error=str(exc),
        )
        errors.append(f"es: {exc}")

    # 4) Qdrant delete (block collection) — best effort, async-safe wrap.
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        def _qdrant_delete_sync() -> None:
            q_client = QdrantClient(
                url=_settings.QDRANT_URL,
                api_key=_settings.QDRANT_API_KEY or None,
            )
            collection_name = f"aicm_{tenant_slug}_blocks"
            q_client.delete(
                collection_name=collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="repository_id",
                            match=MatchValue(value=str(repository_id)),
                        ),
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=str(doc_id)),
                        ),
                    ]
                ),
            )

        await _asyncio.to_thread(_qdrant_delete_sync)
        # qdrant_client.delete 는 count 직접 미반환 — 호출 자체 성공만 sentinel.
        counts["qdrant"] = -1
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reprocess_cleanup_qdrant_failed",
            doc_id=str(doc_id),
            error=str(exc),
        )
        errors.append(f"qdrant: {exc}")

    # GPT-5.5 v2 #3 — partial fail policy: ES 또는 Qdrant 정리 실패하면
    # *retrieval duplicate 차단 보장 X* (worker re-INSERT 가 기존 stale 항목과
    # 공존). 따라서 ES/Qdrant 한쪽이라도 실패하면 ok=False — caller 가 publish
    # skip 결정. counts/errors 는 그대로 반환하여 외부 audit 가능.
    cleanup_ok = "es:" not in " ".join(errors) and "qdrant:" not in " ".join(errors)
    return {"ok": cleanup_ok, "errors": errors, "counts": counts}


@router.delete(
    "/documents/{doc_id}",
    response_model=ApiResponse[dict],
    summary="문서 삭제 (archived)",
)
async def delete_document(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """문서를 archived 상태로 전이한다 (소프트 삭제).

    legal_hold=True 인 문서는 삭제할 수 없다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)
    if getattr(doc, "legal_hold", False):
        raise HTTPException(
            status_code=409,
            detail="법적 보존(legal_hold) 상태인 문서는 삭제할 수 없습니다.",
        )
    await svc.delete(doc_id, tenant_id=tenant_id)

    # 벡터/ES 일괄 삭제 (문서의 모든 블럭)
    try:
        from src.common.config import settings
        from src.core.models.tenant import Tenant
        from src.core.models.repository import Repository

        repo_stmt = select(Repository).where(Repository.id == doc.repository_id)
        repo = (await db.execute(repo_stmt)).scalar_one_or_none()
        tenant_slug = "unknown"
        if repo:
            tenant_stmt = select(Tenant).where(Tenant.id == repo.tenant_id)
            tenant = (await db.execute(tenant_stmt)).scalar_one_or_none()
            if tenant:
                tenant_slug = tenant.slug

        # Qdrant: document_id 필터로 일괄 삭제
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            q_client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
            collection_name = f"aicm_{tenant_slug}_blocks"
            q_client.delete(
                collection_name=collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key="document_id", match=MatchValue(value=str(doc_id)))]
                ),
            )
            logger.info("document_vectors_deleted", doc_id=str(doc_id), collection=collection_name)
        except Exception as exc:
            logger.warning("document_qdrant_cleanup_failed", doc_id=str(doc_id), error=str(exc))

        # ES: document_id + tenant_id 필터로 일괄 삭제
        # Lucas-KMS Phase 2 T2.6 — index name 격리 + payload tenant_id 이중 안전망.
        try:
            from elasticsearch import AsyncElasticsearch
            from src.search.es_wrapper import with_tenant_term
            from src.search.hybrid.es_keyword import build_block_es_index_name

            es_index = build_block_es_index_name(tenant_slug)
            es_client = AsyncElasticsearch(hosts=[settings.ELASTICSEARCH_URL])
            base_q = {"term": {"document_id": str(doc_id)}}
            scoped_q = with_tenant_term(base_q, str(tenant_id))
            await es_client.delete_by_query(
                index=es_index,
                body={"query": scoped_q},
                ignore=[404],
            )
            await es_client.close()
            logger.info("document_es_deleted", doc_id=str(doc_id), index=es_index)
        except Exception as exc:
            logger.warning("document_es_cleanup_failed", doc_id=str(doc_id), error=str(exc))

        # MinIO: 원본+이미지+중간물 완전 삭제 (복원 UI 없음 → hard delete, 2026-06-16)
        # 누락 시 object 가 무한 누적되므로 삭제 라이프사이클에서 함께 정리한다.
        try:
            from src.pipeline.storage.object_store import ObjectStore
            from src.pipeline.storage.config import StorageConfig

            _cfg = StorageConfig()
            _store = ObjectStore(
                endpoint=_cfg.MINIO_ENDPOINT,
                access_key=_cfg.MINIO_ACCESS_KEY,
                secret_key=_cfg.MINIO_SECRET_KEY,
                secure=_cfg.MINIO_SECURE,
            )
            await _store.init()
            await _store.delete_document_objects(str(doc_id), tenant_id=str(tenant_id))
            logger.info("document_minio_deleted", doc_id=str(doc_id))
        except Exception as exc:
            logger.warning("document_minio_cleanup_failed", doc_id=str(doc_id), error=str(exc))

    except Exception as exc:
        logger.warning("document_index_cleanup_failed", doc_id=str(doc_id), error=str(exc))

    # 감사 로그: 문서 삭제
    record_action(
        tenant_id=tenant_id,
        user_id=None,
        action="DELETE",
        resource_type="document",
        resource_id=doc_id,
        detail={"title": doc.title},
    )

    await invalidate_repository_cache(doc.repository_id)
    return ApiResponse(data={"deleted": True, "vectors_cleaned": True})


@router.get(
    "/documents/{doc_id}/pipeline-status",
    response_model=ApiResponse[PipelineStatusResponse],
    summary="파이프라인 처리 상세",
)
async def get_pipeline_status(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PipelineStatusResponse]:
    """문서의 파이프라인 처리 상세 상태를 반환한다.

    stages: uploaded -> parsing -> blocking -> enriching -> embedding -> indexing
    processing/active/failed 모든 상태의 문서에 대해 동작한다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    meta = doc.processing_meta or {}
    current_stage = meta.get("current_stage", "unknown")

    # 진행률 계산
    progress_percent = meta.get("progress_percent", 0)
    if doc.status == "active":
        progress_percent = 100
    elif doc.status == "pending_review":
        progress_percent = 95
    elif doc.status == "failed":
        progress_percent = meta.get("progress_percent", 0)

    # 경과 시간 계산
    import time as _time

    started_at_ts = meta.get("started_at")
    elapsed_seconds: float | None = None
    if started_at_ts:
        if doc.status in ("active", "failed"):
            total_ms = meta.get("total_time_ms")
            elapsed_seconds = total_ms / 1000.0 if total_ms else None
        else:
            elapsed_seconds = round(_time.time() - started_at_ts, 1)

    # 스테이지 목록 구성 — 여러 메타데이터 소스에서 완료 여부를 판단
    stage_names = ["parsing", "blocking", "enriching", "embedding"]

    # 1) stages_completed (신형 포맷)
    stages_completed_list: list[dict] = meta.get("stages_completed", [])
    completed_map = {s["name"]: s for s in stages_completed_list}

    # 2) 개별 플래그에서 완료 판단
    _parsing_done = bool(
        meta.get("parsing_complete")
        or meta.get("stage_parsing_at")
        or "parsing" in completed_map
    )
    # blocking = segmentation in pipeline stages array
    _pipeline_stages = meta.get("stages", [])
    _seg_done = any(
        s.get("status") == "completed"
        for s in _pipeline_stages
        if s.get("stage") in ("segmentation", "blocking", "block_segment")
    )
    _blocking_done = bool(
        _seg_done
        or meta.get("blocking_complete")
        or "blocking" in completed_map
        or (meta.get("total_blocks") and meta.get("total_blocks") > 0)
    )
    # enriching 은 blocking 과 함께 처리됨 (merge worker)
    _enriching_done = bool(
        _blocking_done
        or meta.get("enriching_complete")
        or "enriching" in completed_map
    )
    _embedding_done = bool(
        meta.get("embedding_complete")
        or meta.get("stage_embedding_at")
        or meta.get("indexed_count")
        or "embedding" in completed_map
    )

    _stage_done = {
        "parsing": _parsing_done,
        "blocking": _blocking_done,
        "enriching": _enriching_done,
        "embedding": _embedding_done,
    }

    # [수정 2026-06-09]
    # 이슈 내용: 임베딩 전 검토 체크포인트(no_category_match)로 pending_review가 된 문서가
    #       스텝퍼에는 임베딩까지 완료로 표시되나 상태 텍스트는 "메타데이터 보강중"으로 모순.
    # 원인: pending_review/active 를 일괄 "전부 done"으로 강제 → 검토 체크포인트가 임베딩 '전'인
    #       경우(indexed_count·embedding_complete 미기록)에도 임베딩 단계를 거짓 done 처리.
    # 수정 내용: active 는 완전 인덱싱 완료이므로 전부 done 유지. pending_review 는 parsing/blocking/
    #       enriching 만 done 처리하고 embedding 은 실제 완료 플래그(_embedding_done)에 맡김
    #       (검토가 임베딩 후면 _embedding_done=True 라 자연히 done, 임베딩 전이면 pending 유지).
    if doc.status == "active":
        for k in _stage_done:
            _stage_done[k] = True
    elif doc.status == "pending_review":
        for k in ("parsing", "blocking", "enriching"):
            _stage_done[k] = True

    # [수정 2026-06-09]
    # 이슈 내용: 처리중 진행률이 내내 0%였다가 완료 시점에 급증(블록·페이지 수는 정상 표시).
    # 원인: 워커가 update_progress()를 한 번도 호출하지 않아 processing_meta['progress_percent']가
    #       기록되지 않음(데드 필드). 엔드포인트는 meta 값을 그대로 읽어 0 반환 → active=100/
    #       pending_review=95 로만 점프.
    # 수정 내용: processing 중 meta에 progress_percent가 없으면, 신뢰성 있게 기록되는 스테이지
    #       완료 플래그(_stage_done)에서 도출(완료 단계당 25% + 진행중 단계 부분 가산, 상한 90).
    if doc.status == "processing" and not meta.get("progress_percent"):
        _done_cnt = sum(1 for _v in _stage_done.values() if _v)
        progress_percent = min(_done_cnt * 25 + (12 if _done_cnt < 4 else 0), 90)

    # elapsed_ms: pipeline stages 배열에서 추출
    _stage_elapsed = {}
    for s in _pipeline_stages:
        sname = s.get("stage", "")
        if sname in ("segmentation", "blocking", "block_segment"):
            _stage_elapsed["blocking"] = s.get("duration_ms")
            # segmentation 에 enriching 도 포함
            _stage_elapsed["enriching"] = s.get("duration_ms")
        elif sname == "parsing":
            _stage_elapsed["parsing"] = s.get("duration_ms")
        elif sname == "embedding":
            _stage_elapsed["embedding"] = s.get("duration_ms")

    effective_stage = current_stage
    if effective_stage == "chunking":
        effective_stage = "blocking"

    stages: list[PipelineStageInfo] = []
    for name in stage_names:
        if _stage_done.get(name):
            elapsed_ms = None
            if name in completed_map:
                elapsed_ms = completed_map[name].get("elapsed_ms")
            elif name in _stage_elapsed:
                elapsed_ms = _stage_elapsed[name]
            detail = None
            if name == "blocking" and _pipeline_stages:
                seg = next((s for s in _pipeline_stages if s.get("stage") in ("segmentation", "blocking")), None)
                if seg and seg.get("output_summary"):
                    detail = str(seg["output_summary"].get("block_count", "")) + " blocks"
            stages.append(PipelineStageInfo(
                name=name,
                status="completed",
                elapsed_ms=elapsed_ms,
                detail=detail,
            ))
        elif name == effective_stage and doc.status == "processing":
            stages.append(PipelineStageInfo(
                name=name,
                status="in_progress",
                detail=meta.get("stage_detail"),
                progress=progress_percent,
            ))
        elif doc.status == "failed" and meta.get("failed_stage") == name:
            stages.append(PipelineStageInfo(
                name=name,
                status="failed",
                detail=meta.get("error_message"),
            ))
        else:
            stages.append(PipelineStageInfo(name=name, status="pending"))

    # started_at 를 ISO 문자열로 변환
    started_at_str: str | None = None
    if started_at_ts:
        from datetime import datetime as _dt, timezone as _tz

        started_at_str = _dt.fromtimestamp(started_at_ts, tz=_tz.utc).isoformat()

    status_resp = PipelineStatusResponse(
        document_id=doc.id,
        status=doc.status,
        stage=current_stage,
        current_stage=current_stage if doc.status == "processing" else None,
        progress_pct=progress_percent,
        progress_percent=progress_percent,
        stage_detail=meta.get("stage_detail"),
        chunk_count=meta.get("chunk_count") or meta.get("total_blocks"),
        block_count=meta.get("total_blocks") or meta.get("chunk_count") or meta.get("indexed_count"),
        difficulty=meta.get("difficulty"),
        error_message=meta.get("error") or meta.get("error_message"),
        error_traceback=meta.get("error_traceback"),
        failed_stage=meta.get("failed_stage"),
        retry_count=meta.get("retry_count"),
        started_at=started_at_str,
        completed_at=meta.get("completed_at"),
        elapsed_seconds=elapsed_seconds,
        stages=stages,
        control_signal=meta.get("control_signal"),
        paused_before_stage=meta.get("paused_before_stage") or meta.get("step_by_step_paused_at"),
        page_count=meta.get("page_count") or meta.get("total_pages"),
    )
    return ApiResponse(data=status_resp)


@router.post(
    "/documents/{doc_id}/retry",
    response_model=ApiResponse[dict],
    summary="문서 재처리 (단계별 선택 가능)",
)
async def retry_document(
    doc_id: UUID,
    from_stage: str | None = Query(
        None,
        description=(
            "재처리 시작 단계. "
            "auto=실패 단계(processing_meta.failed_stage)에서 자동 재개, "
            "parsing=전체 재처리, blocking=블로킹부터, "
            "enriching=메타데이터 재생성, embedding=임베딩/인덱싱만 재실행. "
            "미지정 시 전체 재처리(parsing)."
        ),
        pattern=r"^(auto|parsing|blocking|enriching|embedding)$",
    ),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """문서를 파이프라인에 다시 넣는다 (단계별 재처리 지원).

    from_stage 쿼리 파라미터로 재처리 시작 단계를 지정할 수 있다.

    - **auto**: processing_meta.failed_stage 를 읽어 실패한 단계부터 자동 재개.
      알 수 없거나 누락 시 parsing 전체 재처리로 폴백. (호출자가 매핑을 복제하지 않도록)
    - **parsing** (기본값): 전체 재처리. blocks 전부 삭제 후 파싱부터 재생성.
    - **blocking**: 이미 파싱된 결과(parsed.json) 재사용. blocks 삭제 후 블로킹부터 재생성.
    - **enriching**: 기존 블럭 유지. metadata 필드만 초기화 후 enrichment 재실행.
    - **embedding**: 기존 블럭 + 메타 유지. Qdrant/ES 인덱스 제거 후 임베딩/인덱싱만 재실행.

    허용 상태: failed, pending_review, active.
    processing 상태에서는 이미 진행 중이므로 거부한다.
    """
    _VALID_STAGES = {"parsing", "blocking", "enriching", "embedding"}

    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    # from_stage=auto: 서버측에서 processing_meta.failed_stage 를 from_stage 로 매핑한다.
    # 워커별 failed_stage 문자열(parsing/block_segmentation/block/enriching/embedding/
    # block_embedding/chunking)이 파편화되어 있으므로 매핑 지식을 KMS 한 곳에 둔다
    # (호출자가 복제하면 문자열 드리프트에 취약). 알 수 없거나 누락 시 전체 재처리(parsing)로 폴백.
    if (from_stage or "parsing") == "auto":
        _FAILED_STAGE_TO_FROM = {
            "parsing": "parsing",
            "parse": "parsing",
            "block_segmentation": "blocking",
            "block": "blocking",
            "blocking": "blocking",
            "enriching": "enriching",
            "enrich": "enriching",
            "embedding": "embedding",
            "block_embedding": "embedding",
        }
        _failed_stage = (doc.processing_meta or {}).get("failed_stage") or ""
        effective_stage = _FAILED_STAGE_TO_FROM.get(_failed_stage, "parsing")
        logger.info(
            "retry_auto_resolved",
            document_id=str(doc.id),
            failed_stage=_failed_stage,
            resolved_from_stage=effective_stage,
        )
    else:
        effective_stage = from_stage or "parsing"

    if effective_stage not in _VALID_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"유효하지 않은 from_stage 값입니다: {effective_stage}. "
                   f"허용 값: {', '.join(sorted(_VALID_STAGES))}",
        )

    # processing 상태면 거부 (이미 진행 중)
    _ALLOWED_STATUSES = {"failed", "pending_review", "active"}
    if doc.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="문서가 이미 처리 중입니다. 완료 후 다시 시도하세요.",
        )
    if doc.status not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"재처리는 failed, pending_review, active 상태의 문서만 가능합니다. "
                   f"현재 상태: {doc.status}",
        )

    # blocking/enriching 재처리 시 파싱 결과가 있는지 검증
    if effective_stage in ("blocking", "enriching"):
        meta = doc.processing_meta or {}
        if not meta.get("parsing_complete"):
            raise HTTPException(
                status_code=400,
                detail=f"from_stage={effective_stage} 재처리를 위해서는 파싱이 완료된 "
                       "문서여야 합니다. parsing부터 재처리하세요.",
            )

    # embedding 재처리 시 블럭이 존재하는지 검증
    # pending_review/active 상태면 이미 블로킹이 완료된 것이므로 통과
    if effective_stage == "embedding" and doc.status == "failed":
        meta = doc.processing_meta or {}
        failed_at = meta.get("failed_stage", "")
        # 파싱이나 블로킹 단계에서 실패한 경우 임베딩만 재실행은 불가
        if failed_at in ("parsing", "block_segmentation", "block"):
            raise HTTPException(
                status_code=400,
                detail=f"from_stage=embedding 재처리를 위해서는 블로킹이 완료된 "
                       f"문서여야 합니다. 현재 실패 단계: {failed_at}. "
                       "blocking부터 재처리하세요.",
            )

    # 상태를 processing으로 전이
    if doc.status != "processing":
        await svc.transition_status(doc.id, target_status="processing", tenant_id=tenant_id)

    # processing_meta에 재시도 기록 추가
    retry_count = (doc.processing_meta or {}).get("retry_count", 0) + 1
    retry_meta: dict = {
        "retry_count": retry_count,
        "last_retry_at": datetime.utcnow().isoformat(),
        "retry_from_stage": effective_stage,
        "error": None,
        "error_message": None,
        "failed_stage": None,
    }

    await svc.update_processing_meta(
        doc.id,
        processing_meta=retry_meta,
        tenant_id=tenant_id,
    )

    # D85c-잔존 reprocess (2026-05-14) — retry from_stage='parsing' 시 기존
    # blocks + ES/Qdrant chunks 정리. retry 가 publish-only 인 채 진행되면 worker
    # 가 새 blocks INSERT 하면서 *기존 blocks 와 duplicate* 가 누적되는 사고
    # (실 사례: 같은 PDF 3 document 가 모두 ES indexed → 3x duplicate retrieval).
    # GPT-5.5 D85c-잔존 reprocess verdict v1 #2 (cleanup 실패 시 publish skip) 반영.
    if effective_stage == "parsing":
        cleanup = await _reset_blocks_and_indexes_for_reprocess(
            doc_id=doc.id,
            tenant_id=tenant_id,
            repository_id=doc.repository_id,
            db=db,
        )
        counts = cleanup.get("counts") or {}
        errors = cleanup.get("errors") or []
        if not cleanup.get("ok"):
            # cleanup critical 실패 (DB blocks DELETE 또는 tenant slug 실패) —
            # publish skip. document 상태 'failed' 로 기록하여 후속 retry 가능.
            try:
                await svc.transition_status(
                    doc.id, target_status="failed", tenant_id=tenant_id
                )
                await svc.update_processing_meta(
                    doc.id,
                    processing_meta={
                        "failed_stage": "reprocess_cleanup",
                        "error": "cleanup_failed_before_publish",
                        "error_message": "; ".join(errors)[:500],
                    },
                    tenant_id=tenant_id,
                )
            except Exception as _se:  # noqa: BLE001
                logger.warning(
                    "retry_reprocess_failed_status_record_failed",
                    document_id=str(doc.id), error=str(_se),
                )
            logger.error(
                "retry_reprocess_cleanup_failed",
                document_id=str(doc.id),
                errors=errors,
                counts=counts,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "재처리 사전 정리 실패. 문서 상태 'failed' 로 기록. "
                    f"errors: {errors[:3]}"
                ),
            )
        logger.info(
            "retry_reprocess_cleanup_done",
            document_id=str(doc.id),
            db_blocks_deleted=counts.get("db_blocks", 0),
            es_deleted=counts.get("es", 0),
            qdrant_deleted=counts.get("qdrant", 0),
            partial_errors=errors,
        )
    # 단계별 Kafka 이벤트 재발행 (GPT-5.5 v2 #1 — publish 실패 try/except 보호)
    if effective_stage == "parsing":
        try:
            # 전체 재처리: aicm.document.uploaded 재발행 (기존 동작)
            await _publish_upload_event(
                document_id=doc.id,
                tenant_id=tenant_id,
                repository_id=doc.repository_id,
                source_format=doc.source_format or "unknown",
                source_path=doc.source_file or "",
            )
        except Exception as _pe:  # noqa: BLE001
            # publish 실패 — 이미 cleanup 으로 blocks/ES/Qdrant 비워진 상태.
            # status='failed' 기록 + 500 반환으로 사용자에게 명시.
            try:
                await svc.transition_status(
                    doc.id, target_status="failed", tenant_id=tenant_id
                )
                await svc.update_processing_meta(
                    doc.id,
                    processing_meta={
                        "failed_stage": "reprocess_publish",
                        "error": "publish_failed_after_cleanup",
                        "error_message": str(_pe)[:500],
                    },
                    tenant_id=tenant_id,
                )
            except Exception as _se:  # noqa: BLE001
                logger.warning(
                    "retry_reprocess_publish_failure_status_record_failed",
                    document_id=str(doc.id), error=str(_se),
                )
            logger.error(
                "retry_reprocess_publish_failed",
                document_id=str(doc.id),
                error=str(_pe),
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "재처리 publish 실패 — cleanup 후 worker trigger 실패. "
                    "문서 상태 'failed' 기록. 재시도 가능."
                ),
            )
    elif effective_stage in ("blocking", "enriching"):
        # 파싱 결과 재사용하여 블로킹(+enrichment)부터 재처리
        # aicm.document.parsed 이벤트 재발행
        await _publish_stage_event(
            topic=TOPIC_DOCUMENT_PARSED,
            event_data={
                "event_id": str(uuid4()),
                "document_id": str(doc.id),
                "tenant_id": str(tenant_id),
                "repository_id": str(doc.repository_id),
                "difficulty": (doc.processing_meta or {}).get("difficulty", "low"),
                "page_count": (doc.processing_meta or {}).get("page_count", 0),
                "table_count": (doc.processing_meta or {}).get("table_count", 0),
                "image_count": (doc.processing_meta or {}).get("image_count", 0),
                "raw_text_length": (doc.processing_meta or {}).get("raw_text_length", 0),
                "source_path": doc.source_file or "",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    elif effective_stage == "embedding":
        # 기존 블럭 + 메타 유지, 임베딩/인덱싱만 재실행
        # aicm.document.blocked 이벤트 재발행
        await _publish_stage_event(
            topic=TOPIC_DOCUMENT_BLOCKED,
            event_data={
                "event_id": str(uuid4()),
                "document_id": str(doc.id),
                "tenant_id": str(tenant_id),
                "repository_id": str(doc.repository_id),
                "block_count": (doc.processing_meta or {}).get("block_count", 0),
                "block_types": (doc.processing_meta or {}).get("block_types", {}),
                "source_path": doc.source_file or "",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    stage_labels = {
        "parsing": "전체 재처리 (파싱부터)",
        "blocking": "블로킹부터 재처리",
        "enriching": "메타데이터/enrichment 재생성",
        "embedding": "임베딩/인덱싱만 재실행",
    }

    logger.info(
        "document_retry_triggered",
        document_id=str(doc_id),
        retry_count=retry_count,
        from_stage=effective_stage,
    )

    return ApiResponse(
        data={
            "document_id": str(doc.id),
            "status": "processing",
            "retry_count": retry_count,
            "from_stage": effective_stage,
            "message": f"문서 재처리가 트리거되었습니다. ({stage_labels[effective_stage]})",
        }
    )


# ---------------------------------------------------------------------------
# 파이프라인 제어 (취소 / 일시정지 / 재개)
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{doc_id}/pipeline/cancel",
    response_model=ApiResponse[dict],
    summary="파이프라인 취소",
)
async def cancel_pipeline(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """처리 중인 문서의 파이프라인을 취소한다.

    processing_meta.control_signal 을 'cancel' 로 설정하고,
    워커가 다음 스테이지 진입 전에 이를 감지하여 중단한다.
    즉시 상태를 failed 로 변경한다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    if doc.status != "processing":
        raise HTTPException(
            status_code=400,
            detail=f"취소는 processing 상태의 문서만 가능합니다. 현재 상태: {doc.status}",
        )

    # control_signal 설정 + 상태를 failed 로 변경
    meta = {**(doc.processing_meta or {})}
    meta["control_signal"] = "cancel"
    meta["error_message"] = "사용자에 의해 취소됨"
    meta["cancelled_at"] = datetime.utcnow().isoformat()
    doc.processing_meta = meta
    doc.status = "failed"
    await db.flush()
    await sync_document_status(doc.id, "failed", db)

    logger.info("pipeline_cancelled", document_id=str(doc_id))

    return ApiResponse(
        data={
            "document_id": str(doc.id),
            "status": "failed",
            "message": "파이프라인이 취소되었습니다.",
        }
    )


@router.post(
    "/documents/{doc_id}/pipeline/pause",
    response_model=ApiResponse[dict],
    summary="파이프라인 일시정지",
)
async def pause_pipeline(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """파이프라인을 일시정지한다.

    processing_meta.control_signal 을 'pause' 로 설정한다.
    현재 진행 중인 스테이지가 완료된 후 다음 스테이지 진입 전에 멈춘다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    if doc.status != "processing":
        raise HTTPException(
            status_code=400,
            detail=f"일시정지는 processing 상태의 문서만 가능합니다. 현재 상태: {doc.status}",
        )

    meta = {**(doc.processing_meta or {})}
    if meta.get("control_signal") == "pause":
        raise HTTPException(status_code=400, detail="이미 일시정지 상태입니다.")

    meta["control_signal"] = "pause"
    meta["paused_at"] = datetime.utcnow().isoformat()
    doc.processing_meta = meta
    await db.flush()

    logger.info("pipeline_paused", document_id=str(doc_id))

    return ApiResponse(
        data={
            "document_id": str(doc.id),
            "status": "processing",
            "control_signal": "pause",
            "message": "파이프라인이 일시정지되었습니다. 현재 스테이지 완료 후 멈춥니다.",
        }
    )


@router.post(
    "/documents/{doc_id}/pipeline/resume",
    response_model=ApiResponse[dict],
    summary="파이프라인 재개",
)
async def resume_pipeline(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """일시정지된 파이프라인을 재개한다.

    control_signal 을 해제하고, 현재 스테이지에 맞는 Kafka 이벤트를 재발행한다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    if doc.status != "processing":
        raise HTTPException(
            status_code=400,
            detail=f"재개는 processing 상태의 문서만 가능합니다. 현재 상태: {doc.status}",
        )

    meta = {**(doc.processing_meta or {})}
    if meta.get("control_signal") != "pause":
        raise HTTPException(status_code=400, detail="일시정지 상태가 아닙니다.")

    # step_by_step 일시정지에서 재개: 저장된 이벤트를 해당 토픽으로 재발행
    paused_topic = meta.get("paused_event_topic")
    paused_data = meta.get("paused_event_data")
    paused_before = meta.get("paused_before_stage", "")

    # control_signal 해제 + 일시정지 관련 필드 정리
    meta["control_signal"] = None
    meta["resumed_at"] = datetime.utcnow().isoformat()
    meta["step_by_step_resume_pending"] = True
    meta.pop("paused_event_topic", None)
    meta.pop("paused_event_data", None)
    meta.pop("paused_before_stage", None)
    doc.processing_meta = meta
    await db.commit()

    if paused_topic and paused_data:
        # 저장된 이벤트를 원래 토픽으로 재발행
        await _publish_raw_kafka_event(paused_topic, paused_data)
        logger.info(
            "pipeline_resumed_step_by_step",
            document_id=str(doc_id),
            resumed_topic=paused_topic,
            next_stage=paused_before,
        )
    else:
        # 기존 방식: upload 이벤트 재발행
        await _publish_upload_event(
            document_id=doc.id,
            tenant_id=tenant_id,
            repository_id=doc.repository_id,
            source_format=doc.source_format or "unknown",
            source_path=doc.source_file or "",
        )
        logger.info(
            "pipeline_resumed",
            document_id=str(doc_id),
        )

    return ApiResponse(
        data={
            "document_id": str(doc.id),
            "status": "processing",
            "message": f"파이프라인이 재개되었습니다.{f' 다음 단계: {paused_before}' if paused_before else ''}",
        }
    )


@router.patch(
    "/documents/{doc_id}/status",
    response_model=ApiResponse[dict],
    summary="문서 상태 강제 변경",
)
async def change_document_status(
    doc_id: UUID,
    body: StatusChangeRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """문서 상태를 강제 변경한다.

    관리자용 엔드포인트로, 정상적인 상태 전이 규칙을 무시하고
    강제로 상태를 변경할 수 있다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    old_status = doc.status

    # 강제 변경이므로 transition_status의 유효성 검증을 우회한다
    doc.status = body.status

    # processing_meta에 강제 변경 기록
    meta_update: dict = {
        "force_status_change": {
            "from": old_status,
            "to": body.status,
            "reason": body.reason,
            "changed_at": datetime.utcnow().isoformat(),
        },
    }
    if body.status == "failed" and body.reason:
        meta_update["error_message"] = body.reason

    merged = {**(doc.processing_meta or {}), **meta_update}
    doc.processing_meta = merged

    await db.flush()
    await sync_document_status(doc.id, body.status, db)

    logger.info(
        "document_status_force_changed",
        document_id=str(doc_id),
        old_status=old_status,
        new_status=body.status,
        reason=body.reason,
    )

    return ApiResponse(
        data={
            "document_id": str(doc.id),
            "old_status": old_status,
            "new_status": body.status,
            "message": f"문서 상태가 {old_status} → {body.status}로 변경되었습니다.",
        }
    )


class PromoteRequest(BaseModel):
    reason: Optional[str] = Field(None, description="승격 사유")


@router.post(
    "/documents/{doc_id}/promote",
    response_model=ApiResponse[dict],
    summary="문서를 active 로 승격 (pending_review → active)",
)
async def promote_document(
    doc_id: UUID,
    body: PromoteRequest = PromoteRequest(),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """pending_review 상태 문서를 검토 완료로 active 승격.
    ES + Qdrant payload 의 document_status 도 동기.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)
    if doc.status != "pending_review":
        raise HTTPException(
            status_code=400,
            detail=f"pending_review 상태만 승격 가능합니다. 현재: {doc.status}",
        )
    old_status = doc.status
    # [수정 2026-06-09]
    # 이슈 내용: AICM 승인(promote 경유)으로 active가 됐는데 검색 안 됨(벡터 0).
    # 원인: 검토 체크포인트가 임베딩 前이라 pending_review 문서는 미임베딩 상태인데,
    #       promote 가 status만 active로 바꾸고 임베딩을 트리거하지 않음(approve_review 옛 버그와 동일).
    #       AICM 승인은 /review/approve 가 아니라 이 /promote 를 호출하므로 별도 수정 필요.
    # 수정 내용: 미임베딩 문서면 DocumentBlockedEvent 발행해 임베딩 진행(완료 시 preserve_active 로 active 유지).
    _meta = doc.processing_meta or {}
    _already_embedded = bool(_meta.get("embedding_complete") or _meta.get("indexed_count"))
    doc.status = "active"
    meta_update = {
        "force_status_change": {
            "from": old_status,
            "to": "active",
            "reason": body.reason or "검토 완료 — active 승격",
            "changed_at": datetime.utcnow().isoformat(),
        },
    }
    doc.processing_meta = {**_meta, **meta_update}
    await db.flush()
    await sync_document_status(doc.id, "active", db)

    if not _already_embedded:
        try:
            import json as _json
            from uuid import uuid4 as _uuid4

            from aiokafka import AIOKafkaProducer

            from src.common.config import settings as _settings

            blocked_payload = {
                "event_id": str(_uuid4()),
                "document_id": str(doc.id),
                "tenant_id": str(tenant_id),
                "repository_id": str(doc.repository_id),
                "block_count": int(_meta.get("total_blocks") or _meta.get("chunk_count") or 0),
                "block_types": _meta.get("block_types") or {},
                "source_path": doc.source_file or "",
            }
            producer = AIOKafkaProducer(bootstrap_servers=_settings.KAFKA_BOOTSTRAP_SERVERS)
            await producer.start()
            try:
                await producer.send_and_wait(
                    "aicm.document.blocked",
                    value=_json.dumps(blocked_payload).encode("utf-8"),
                )
            finally:
                await producer.stop()
            logger.info("promote_embedding_triggered", document_id=str(doc_id))
        except Exception as exc:
            logger.warning(
                "promote_embedding_trigger_failed",
                document_id=str(doc_id),
                error=str(exc),
            )

    logger.info("document_promoted", document_id=str(doc_id))
    return ApiResponse(data={"old_status": old_status, "new_status": "active"})


@router.patch(
    "/documents/{doc_id}/search-exclusion",
    response_model=ApiResponse[dict],
    summary="문서 검색 제외 토글",
)
async def set_document_search_exclusion(
    doc_id: UUID,
    body: SearchExclusionRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """문서의 검색 제외 여부를 토글한다.

    - excluded=True : 문서가 라이브러리에는 표시되지만 검색/RAG 결과에서 제외된다.
      status 는 active 그대로 유지된다.
    - excluded=False : 검색/RAG 에 재포함된다.

    archived(소프트 삭제) 문서는 이미 라이브러리에서 숨겨지므로 이 엔드포인트
    대상에서 제외한다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    if doc.status == "archived":
        raise HTTPException(
            status_code=400,
            detail="archived 문서는 검색 제외 토글 대상이 아닙니다. 복원 후 사용하세요.",
        )

    old_excluded = bool(getattr(doc, "search_excluded", False))
    doc.search_excluded = body.excluded
    await db.flush()

    # Qdrant/ES 인덱스에 search_excluded payload 동기화
    await sync_search_excluded(doc_id, body.excluded, db)

    # 저장소 검색 캐시 무효화 — 즉시 반영
    await invalidate_repository_cache(doc.repository_id)

    logger.info(
        "document_search_exclusion_changed",
        document_id=str(doc_id),
        old_excluded=old_excluded,
        new_excluded=body.excluded,
    )

    return ApiResponse(
        data={
            "document_id": str(doc_id),
            "search_excluded": body.excluded,
            "message": "검색 제외로 변경되었습니다." if body.excluded else "검색 포함으로 복원되었습니다.",
        }
    )


@router.post(
    "/documents/batch-upload",
    response_model=ApiResponse[dict],
    status_code=201,
    summary="문서 일괄 업로드 (ZIP)",
)
async def batch_upload_documents(
    file: UploadFile,
    repository_id: UUID = Form(...),
    document_type_id: UUID | None = Form(None),
    config_override: str | None = Form(None),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """ZIP 파일을 업로드하여 내부 문서들을 일괄 처리한다.

    ZIP 파일을 서버에서 해제하고, 각 파일을 개별 문서로 등록하여
    파이프라인을 트리거한다.

    지원하지 않는 포맷의 파일은 건너뛰고 결과에 skipped로 보고한다.
    """
    import io
    import zipfile
    from pathlib import Path as FilePath

    # ZIP 파일 검증
    contents = await file.read()
    await file.seek(0)

    if not zipfile.is_zipfile(io.BytesIO(contents)):
        from src.common.exceptions import AICMError

        raise AICMError(
            code="INVALID_FILE_FORMAT",
            message="ZIP 파일이 아닙니다.",
        )

    uploaded: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    override_dict = json.loads(config_override) if config_override else None

    with zipfile.ZipFile(io.BytesIO(contents)) as zf:
        for entry in zf.namelist():
            # 디렉토리 건너뛰기
            if entry.endswith("/"):
                continue

            # 숨김 파일, __MACOSX 건너뛰기
            basename = FilePath(entry).name
            if basename.startswith(".") or "__MACOSX" in entry:
                continue

            # 포맷 감지
            try:
                source_format = detect_format(basename)
            except Exception:
                skipped.append({"file": basename, "reason": "unsupported_format"})
                continue

            # 파일 추출 및 저장
            try:
                file_bytes = zf.read(entry)

                # DB 레코드 생성 (source_file 은 MinIO 저장 후 채움)
                svc = DocumentService(db)
                doc = await svc.create(
                    repository_id=repository_id,
                    tenant_id=tenant_id,
                    title=basename,
                    source_file=None,
                    source_format=source_format,
                    document_type_id=document_type_id,
                    category_ids=[],
                    created_by=user_id,
                )

                # 원본을 MinIO 단일 원천에 저장 → object key 를 source_file 로 기록.
                file_path = await _store_source_bytes(
                    str(tenant_id), str(doc.id), file_bytes,
                    ext=_src_ext_from(basename, source_format),
                )
                doc.source_file = file_path
                await svc.transition_status(doc.id, target_status="processing")

                # Kafka 이벤트
                await _publish_upload_event(
                    document_id=doc.id,
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    source_format=source_format,
                    source_path=file_path,
                    config_override=override_dict,
                    file_size_bytes=len(file_bytes),
                )

                uploaded.append({
                    "document_id": str(doc.id),
                    "file": basename,
                    "format": source_format,
                })
            except Exception as exc:
                logger.warning(
                    "batch_upload_file_error",
                    file=basename,
                    error=str(exc),
                )
                errors.append({"file": basename, "error": str(exc)})

    return ApiResponse(
        data={
            "total_files": len(uploaded) + len(skipped) + len(errors),
            "uploaded": len(uploaded),
            "skipped": len(skipped),
            "errors": len(errors),
            "details": {
                "uploaded": uploaded,
                "skipped": skipped,
                "errors": errors,
            },
        }
    )


@router.post(
    "/documents/batch-upload-files",
    response_model=ApiResponse[dict],
    status_code=201,
    summary="복수 파일 일괄 업로드",
)
async def batch_upload_files(
    files: list[UploadFile],
    repository_id: UUID = Form(...),
    category_ids: str = Form("[]"),
    document_type_id: UUID | None = Form(None),
    config_override: str | None = Form(None),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """여러 파일을 한번에 업로드한다. 각 파일별로 파이프라인 이벤트 발행.

    multipart/form-data 로 여러 파일을 동시에 전송하면
    각 파일에 대해 개별 문서 레코드를 생성하고 파이프라인을 트리거한다.
    개별 파일 실패 시 해당 파일만 에러로 기록하고 나머지는 계속 처리한다.
    """
    parsed_category_ids = json.loads(category_ids) if category_ids else []
    override_dict = json.loads(config_override) if config_override else None

    results: list[dict] = []
    for file in files:
        try:
            await validate_file_size(file)
            source_format = detect_format(file.filename or "unknown", file.content_type)

            svc = DocumentService(db)
            doc = await svc.create(
                repository_id=repository_id,
                tenant_id=tenant_id,
                title=file.filename or "Untitled",
                source_file=None,
                source_format=source_format,
                document_type_id=document_type_id,
                category_ids=[
                    UUID(cid) if isinstance(cid, str) else cid for cid in parsed_category_ids
                ],
                created_by=user_id,
            )

            # 원본을 MinIO 단일 원천에 저장 → object key 를 source_file 로 기록.
            await file.seek(0)
            _contents = await file.read()
            file_path = await _store_source_bytes(
                str(tenant_id), str(doc.id), _contents,
                ext=_src_ext_from(file.filename, source_format),
                content_type=file.content_type or "",
            )
            doc.source_file = file_path
            await svc.transition_status(doc.id, target_status="processing")

            await _publish_upload_event(
                document_id=doc.id,
                tenant_id=tenant_id,
                repository_id=repository_id,
                source_format=source_format,
                source_path=file_path,
                config_override=override_dict,
                file_size_bytes=len(_contents),
            )

            results.append({
                "filename": file.filename,
                "status": "accepted",
                "document_id": str(doc.id),
            })
        except Exception as e:
            logger.warning(
                "batch_upload_file_error",
                filename=file.filename,
                error=str(e),
            )
            results.append({
                "filename": file.filename,
                "status": "failed",
                "error": str(e),
            })

    accepted_count = len([r for r in results if r["status"] == "accepted"])
    return ApiResponse(
        data={
            "uploaded": accepted_count,
            "failed": len(results) - accepted_count,
            "total": len(results),
            "results": results,
        }
    )


# ---------------------------------------------------------------------------
# 자동 분류 프리뷰 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{doc_id}/classify-preview",
    response_model=ApiResponse[dict],
    summary="자동 분류 프리뷰",
)
async def classify_preview(
    doc_id: UUID,
    max_blocks: int = Query(5, ge=1, le=20, description="프리뷰 대상 블럭 수"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    """문서의 처음 N개 블럭에 대해 Stage 3 분류를 실행하고 프리뷰 결과를 반환한다.

    결과는 DB에 저장되지 않으며, 분류 결과만 미리 확인하는 용도이다.
    """
    from src.core.models.block import Block

    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    # 블럭 조회
    stmt = (
        select(Block)
        .where(Block.document_id == doc_id)
        .order_by(Block.block_index)
        .limit(max_blocks)
    )
    result = await db.execute(stmt)
    blocks = list(result.scalars().all())

    if not blocks:
        return ApiResponse(
            data={
                "document_id": str(doc_id),
                "title": doc.title,
                "preview_blocks": [],
                "message": "분류할 블럭이 없습니다.",
            }
        )

    # Stage 3 분류기 실행 (저장 없이 프리뷰만)
    try:
        from src.common.config import settings as app_settings
        from src.pipeline.stages.llm_client import VisionLLMClient
        from src.pipeline.stages.models import DocumentContext, RawBlock
        from src.pipeline.stages.stage3_enrich import BlockEnrichment

        llm_client = VisionLLMClient(
            api_key=app_settings.LLM_API_KEY,
            model=app_settings.LLM_MODEL,
        )
        enricher = BlockEnrichment(llm_client)

        context = DocumentContext(
            document_type=doc.processing_meta.get("document_type", ""),
            title=doc.title,
        )

        # ORM Block -> RawBlock 변환 (분류용)
        raw_blocks = [
            RawBlock(
                type=b.block_type,
                content=b.content,
                page=b.source_location.get("page_number", 0) if b.source_location else 0,
            )
            for b in blocks
        ]

        # classify_block만 실행 (table/image enrich 제외)
        import asyncio

        classify_tasks = [
            enricher._classify_block(rb, context)
            for rb in raw_blocks
            if rb.type not in ("noise", "divider")
        ]
        if classify_tasks:
            await asyncio.gather(*classify_tasks, return_exceptions=True)

        preview_results = []
        for b_orm, rb in zip(blocks, raw_blocks):
            preview_results.append({
                "block_id": str(b_orm.id),
                "block_index": b_orm.block_index,
                "block_type": b_orm.block_type,
                "content_preview": b_orm.content[:200],
                "classification": {
                    "nature": rb.nature,
                    "time_reference": rb.time_reference,
                    "entities": rb.entities,
                    "confidence": rb.classification_confidence,
                    "reasoning": rb.classification_reasoning,
                },
            })

        return ApiResponse(
            data={
                "document_id": str(doc_id),
                "title": doc.title,
                "preview_blocks": preview_results,
            }
        )
    except Exception as e:
        logger.warning("classify_preview_error", document_id=str(doc_id), error=str(e))
        return ApiResponse(
            data={
                "document_id": str(doc_id),
                "title": doc.title,
                "preview_blocks": [],
                "error": str(e),
                "message": "분류 프리뷰 실행 중 오류가 발생했습니다.",
            }
        )


# ---------------------------------------------------------------------------
# 문서 분석 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{doc_id}/analyze",
    response_model=ApiResponse[AnalysisReportResponse],
    summary="문서 AI 분석",
)
async def analyze_document(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AnalysisReportResponse]:
    """문서를 AI로 분석하여 품질 점수, 구조 분석, 검색 예측, 개선 제안을 반환한다.

    파싱/청킹이 완료된 문서에 대해 분석을 수행한다.
    결과는 processing_meta.analysis_report에도 저장된다.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    # 청크 조회
    chunk_stmt = (
        select(Chunk)
        .where(Chunk.document_id == doc_id)
        .order_by(Chunk.chunk_index)
    )
    chunk_result = await db.execute(chunk_stmt)
    chunks = list(chunk_result.scalars().all())

    chunk_dicts = [
        {
            "content": c.content,
            "metadata": c.meta_info,
            "chunk_index": c.chunk_index,
        }
        for c in chunks
    ]

    # 기존 문서 조회 (중복 검사용 — 같은 저장소의 active 문서)
    existing_stmt = (
        select(Document)
        .where(
            Document.repository_id == doc.repository_id,
            Document.status == "active",
            Document.id != doc_id,
        )
        .limit(50)
    )
    existing_result = await db.execute(existing_stmt)
    existing_docs_raw = list(existing_result.scalars().all())

    existing_docs = []
    for ed in existing_docs_raw:
        # 각 기존 문서의 첫 청크 내용을 가져와 content_preview로 사용
        first_chunk_stmt = (
            select(Chunk.content)
            .where(Chunk.document_id == ed.id)
            .order_by(Chunk.chunk_index)
            .limit(1)
        )
        first_chunk_result = await db.execute(first_chunk_stmt)
        preview = first_chunk_result.scalar_one_or_none() or ""
        existing_docs.append({
            "document_id": str(ed.id),
            "title": ed.title,
            "content_preview": preview[:500],
        })

    # 파싱 메타에서 parse_result 추출
    parse_result = doc.processing_meta.get("parse_result", {})

    # AI 분석 수행
    analyzer = DocumentAnalyzer()
    report = await analyzer.analyze(
        parse_result=parse_result,
        chunks=chunk_dicts,
        doc_title=doc.title,
        existing_docs=existing_docs,
    )

    # processing_meta에 분석 결과 저장
    await svc.update_processing_meta(
        doc_id,
        processing_meta={"analysis_report": report.model_dump()},
        tenant_id=tenant_id,
    )

    return ApiResponse(data=AnalysisReportResponse(**report.model_dump()))


# ---------------------------------------------------------------------------
# 문서 버전 관리 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{doc_id}/new-version",
    response_model=ApiResponse[VersionUploadResponse],
    status_code=201,
    summary="문서 새 버전 업로드",
)
async def upload_new_version(
    doc_id: UUID,
    file: UploadFile,
    title: str | None = Form(None),
    config_override: str | None = Form(None),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[VersionUploadResponse]:
    """기존 문서의 새 버전을 업로드한다.

    1. 기존 문서 → archived + Qdrant 벡터 제거 마킹
    2. 새 문서 생성 → version+1, status=processing
    3. 파이프라인 트리거 (Kafka 이벤트)
    """
    # 파일 검증
    await validate_file_size(file)
    source_format = detect_format(file.filename or "unknown", file.content_type)

    # 기존 문서의 저장소 ID 조회
    doc_svc = DocumentService(db)
    old_doc = await doc_svc.get_by_id(doc_id, tenant_id=tenant_id)

    # 버전 서비스로 새 버전 생성 (source_file 은 MinIO 저장 후 채움)
    version_svc = DocumentVersionService(db)
    override_dict = json.loads(config_override) if config_override else None

    archived_doc, new_doc = await version_svc.upload_new_version(
        doc_id,
        tenant_id=tenant_id,
        source_file=None,
        source_format=source_format,
        title=title,
        created_by=user_id,
        config_override=override_dict,
    )

    # 원본을 MinIO 단일 원천에 저장 → object key 를 새 버전 문서의 source_file 로 기록.
    await file.seek(0)
    _contents = await file.read()
    file_path = await _store_source_bytes(
        str(tenant_id), str(new_doc.id), _contents,
        ext=_src_ext_from(file.filename, source_format),
        content_type=file.content_type or "",
    )
    new_doc.source_file = file_path
    await db.flush()

    # Kafka 이벤트 발행
    await _publish_upload_event(
        document_id=new_doc.id,
        tenant_id=tenant_id,
        repository_id=new_doc.repository_id,
        source_format=source_format,
        source_path=file_path,
        config_override=override_dict,
        file_size_bytes=len(_contents),
    )

    return ApiResponse(
        data=VersionUploadResponse(
            archived_document_id=archived_doc.id,
            new_document_id=new_doc.id,
            old_version=archived_doc.version,
            new_version=new_doc.version,
        )
    )


@router.post(
    "/documents/{doc_id}/rollback/{version}",
    response_model=ApiResponse[RollbackResponse],
    summary="문서 버전 롤백",
)
async def rollback_version(
    doc_id: UUID,
    version: int,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RollbackResponse]:
    """문서를 특정 버전으로 롤백한다.

    1. 현재 active 문서 → archived
    2. 대상 버전 문서 → active + Qdrant 벡터 재적재 마킹
    """
    version_svc = DocumentVersionService(db)
    archived_doc, restored_doc = await version_svc.rollback(
        doc_id, version, tenant_id=tenant_id,
    )

    return ApiResponse(
        data=RollbackResponse(
            archived_document_id=archived_doc.id,
            restored_document_id=restored_doc.id,
            restored_version=restored_doc.version,
        )
    )


@router.get(
    "/documents/{doc_id}/versions",
    response_model=ApiResponse[list[VersionHistoryItem]],
    summary="문서 버전 이력 조회",
)
async def get_version_history(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[VersionHistoryItem]]:
    """문서의 모든 버전 이력을 반환한다."""
    version_svc = DocumentVersionService(db)
    versions = await version_svc.get_version_history(doc_id, tenant_id=tenant_id)

    items = [
        VersionHistoryItem(
            document_id=v.document_id,
            version=v.version,
            status=v.status,
            title=v.title,
            created_at=v.created_at,
            created_by=v.created_by,
            chunk_count=v.chunk_count,
            source_file=v.source_file,
        )
        for v in versions
    ]

    return ApiResponse(data=items)


async def _publish_upload_event(
    document_id: UUID,
    tenant_id: UUID,
    repository_id: UUID,
    source_format: str,
    source_path: str,
    config_override: dict | None = None,
    file_size_bytes: int | None = None,
) -> None:
    """Kafka에 문서 업로드 이벤트를 발행한다.

    D48 §1 — file_size + format 기반으로 small/large 토픽 분류.
    legacy `aicm.document.uploaded` 토픽은 rollback path 로 유지 (env 토글).

    Kafka 클라이언트가 없는 경우 로그만 남긴다 (개발 환경 호환).

    Args:
        file_size_bytes: 원본 바이트 크기. source_path 가 MinIO object key 라
            로컬 stat 이 불가하므로 호출측이 이미 읽은 바이트 길이를 넘긴다.
            None 이면(레거시 로컬경로 호출) source_path 로 stat 시도.
    """
    # D48 §1 — 업로드 시점 분류 (file_size + format 우선 규칙)
    from src.pipeline.services.upload_topic_classifier import classify_upload_topic

    if file_size_bytes is None:
        # source_path 가 로컬 경로인 레거시 호출에 한해 stat (object key 면 실패→None).
        try:
            import os as _os
            file_size_bytes = _os.path.getsize(source_path)
        except (OSError, TypeError):
            file_size_bytes = None

    decision = classify_upload_topic(
        file_size_bytes=file_size_bytes,
        source_path=source_path,
        source_format=source_format,
    )

    # Phase 2.7 — envelope helper 로 tenant_id 누락 방지 (consumer 측 RLS context 보장).
    from src.common.storage_tenant import kafka_envelope

    event = kafka_envelope(
        tenant_id,
        {
            "event_id": str(uuid4()),
            "document_id": str(document_id),
            "repository_id": str(repository_id),
            "source_format": source_format,
            "source_path": source_path,
            "config_override": config_override,
            "timestamp": datetime.utcnow().isoformat(),
            # D48 §1 — idempotency_key + 분류 메타. early divert / large 워커가 활용.
            "idempotency_key": str(document_id),
            "upload_classification": {
                "profile": decision.profile,
                "reason": decision.reason,
                "threshold_mib": decision.threshold_mib,
                "file_size_bytes": decision.file_size_bytes,
            },
        },
    )
    try:
        from aiokafka import AIOKafkaProducer

        from src.common.config import settings

        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            enable_idempotence=True,
            acks="all",
        )
        await producer.start()
        try:
            await producer.send_and_wait(
                decision.topic,
                value=json.dumps(event).encode("utf-8"),
            )
            logger.info(
                "kafka_event_published",
                topic=decision.topic,
                profile=decision.profile,
                reason=decision.reason,
                file_size_bytes=decision.file_size_bytes,
                doc_id=str(document_id),
            )
        finally:
            await producer.stop()
    except Exception as exc:
        logger.error(
            "kafka_event_publish_failed",
            topic=decision.topic,
            doc_id=str(document_id),
            error=str(exc),
        )
        # Silent fail 금지 — upstream 에서 HTTPException 으로 변환 가능하도록 raise
        raise RuntimeError(
            f"파이프라인 큐(Kafka) 전송 실패: {exc}. 잠시 후 다시 시도하거나 재업로드 해주세요."
        ) from exc


async def _publish_raw_kafka_event(topic: str, event_data: str) -> None:
    """저장된 Kafka 이벤트 원본을 지정된 토픽으로 재발행한다 (step_by_step resume용)."""
    try:
        from aiokafka import AIOKafkaProducer

        from src.common.config import settings

        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await producer.start()
        try:
            await producer.send_and_wait(
                topic,
                value=event_data.encode("utf-8"),
            )
            logger.info("kafka_raw_event_republished", topic=topic)
        finally:
            await producer.stop()
    except Exception as exc:
        logger.warning(
            "kafka_raw_event_republish_failed",
            topic=topic,
            error=str(exc),
        )


async def _publish_stage_event(topic: str, event_data: dict) -> None:
    """특정 파이프라인 단계의 Kafka 이벤트를 발행한다 (단계별 재처리용).

    Parameters
    ----------
    topic : str
        Kafka 토픽 (예: aicm.document.parsed, aicm.document.blocked)
    event_data : dict
        이벤트 페이로드 딕셔너리. JSON으로 직렬화하여 전송한다.
    """
    try:
        from aiokafka import AIOKafkaProducer

        from src.common.config import settings

        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await producer.start()
        try:
            await producer.send_and_wait(
                topic,
                value=json.dumps(event_data).encode("utf-8"),
            )
            logger.info(
                "kafka_stage_event_published",
                topic=topic,
                doc_id=event_data.get("document_id", ""),
            )
        finally:
            await producer.stop()
    except Exception as exc:
        logger.warning(
            "kafka_stage_event_publish_failed",
            topic=topic,
            doc_id=event_data.get("document_id", ""),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# 파이프라인 리뷰 체크포인트 API
# ---------------------------------------------------------------------------


@router.get(
    "/repositories/{repository_id}/documents/{document_id}/processing-report",
    response_model=ApiResponse,
    summary="파이프라인 처리 보고서 조회",
)
async def get_processing_report(
    repository_id: UUID,
    document_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """문서의 파이프라인 처리 보고서를 조회한다.

    각 스테이지별 처리 결과, 블럭별 신뢰도, 리뷰 필요 항목을 포함.
    """
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    meta = doc.processing_meta or {}

    # FE가 기대하는 형태로 정규화 — 두 가지 처리 경로 지원:
    # 1) 3-stage pipeline → meta["stages"] 배열에 상세 기록 (소규모 문서)
    # 2) DocumentProcessor (대용량 분할) → 평탄한 stage_*_at 타임스탬프만 기록
    raw_stages = meta.get("stages") or []

    if raw_stages:
        # 경로 1: 상세 stages 가 있으면 그대로 정규화
        stages_normalized = [
            {
                "name": s.get("stage") or s.get("name"),
                "status": s.get("status") or "completed",
                "elapsed_ms": s.get("duration_ms") or s.get("elapsed_ms"),
                "model_used": s.get("model_used"),
                "errors": s.get("errors") or [],
                "warnings": s.get("warnings") or [],
                "output_summary": s.get("output_summary") or {},
            }
            for s in raw_stages
        ]
    else:
        # 경로 2: 타임스탬프 기반으로 stages 합성
        # 단계 순서: parsing → blocking → enrichment → embedding → indexing → pending_review
        _STAGE_KEYS = [
            ("parsing", "stage_parsing_at"),
            ("blocking", "stage_blocking_at"),
            ("chunking", "stage_chunking_at"),
            ("enrichment", "stage_enrichment_at"),
            ("embedding", "stage_embedding_at"),
            ("indexing", "stage_indexing_at"),
            ("pending_review", "stage_pending_review_at"),
        ]
        prev_ts = meta.get("started_at")
        synthesized: list[dict] = []
        for stage_name, ts_key in _STAGE_KEYS:
            ts = meta.get(ts_key)
            if ts is None:
                continue
            elapsed_ms = None
            if prev_ts is not None:
                try:
                    elapsed_ms = max(0, int((float(ts) - float(prev_ts)) * 1000))
                except (TypeError, ValueError):
                    elapsed_ms = None
            synthesized.append({
                "name": stage_name,
                "status": "completed",
                "elapsed_ms": elapsed_ms,
                "model_used": None,
                "errors": [],
                "warnings": [],
                "output_summary": {},
            })
            prev_ts = ts
        stages_normalized = synthesized

    # block_count 우선순위: total_blocks > block_count > indexed_count
    block_count = (
        meta.get("total_blocks")
        or meta.get("block_count")
        or meta.get("indexed_count")
        or 0
    )

    # output_summary 보강 (대용량 경로 보강 정보)
    overall_summary = {
        "page_count": meta.get("page_count") or meta.get("total_pages"),
        "image_count": meta.get("image_count"),
        "table_count": meta.get("table_count"),
        "indexed_count": meta.get("indexed_count"),
        "difficulty": meta.get("difficulty"),
        "collection_name": meta.get("collection_name"),
    }

    return ApiResponse(data={
        "document_id": str(document_id),
        "status": doc.status,
        "stages": stages_normalized,
        "block_count": block_count,
        "review_blocks": meta.get("review_items") or meta.get("review_blocks") or [],
        "total_duration_ms": meta.get("total_duration_ms"),
        "avg_confidence": meta.get("avg_confidence"),
        "block_type_distribution": meta.get("block_type_distribution") or {},
        "nature_distribution": meta.get("nature_distribution") or {},
        "confidence_distribution": meta.get("confidence_distribution") or {},
        "review_required": meta.get("review_required", False),
        "current_stage": meta.get("current_stage"),
        "processed_at": meta.get("processed_at"),
        "summary": overall_summary,
    })


@router.post(
    "/repositories/{repository_id}/documents/{document_id}/review/approve",
    response_model=ApiResponse,
    summary="리뷰 승인 — 문서 활성화",
)
async def approve_review(
    repository_id: UUID,
    document_id: UUID,
    review_notes: str = Form(default=""),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """pending_review 문서를 승인하여 active(검색 가능) 상태로 전환한다.

    모든 파이프라인 처리가 완료된 후의 최종 승인이므로 바로 활성화된다.
    """
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"리뷰 대상이 아닙니다. 현재 상태: {doc.status}")

    # [수정 2026-06-09]
    # 이슈 내용: (1) 카테고리 없는 문서가 승인돼 검색 불가, (2) 검토 체크포인트가 임베딩 前이라
    #            승인이 active만 찍고 임베딩을 건너뛰면 벡터 0개 → active인데 검색 안 됨.
    # 원인: approve_review가 "모든 처리 완료 후 승인"을 가정 → 임베딩 트리거 없이 active 전환.
    # 수정: 카테고리 필수 검증(AICM 규칙 일치) + 미임베딩 문서면 DocumentBlockedEvent 발행해
    #       임베딩 진행(완료 시 mark_embedding_complete preserve_active=True 로 active 유지).
    from sqlalchemy import text as _cat_text

    _cat = await db.execute(
        _cat_text("SELECT 1 FROM document_categories WHERE document_id = :did LIMIT 1"),
        {"did": str(document_id)},
    )
    if _cat.first() is None:
        raise HTTPException(status_code=400, detail="카테고리를 먼저 지정한 후 승인해주세요.")

    meta = doc.processing_meta or {}
    _already_embedded = bool(meta.get("embedding_complete") or meta.get("indexed_count"))

    # 미임베딩 문서(무카테고리로 검토 대기했던 경우)는 active 확정 *전에* 임베딩을 트리거한다.
    # 과거 버그: active commit + payload sync 후 비동기 발행 + 실패 silent swallow →
    #           active 인데 벡터 0개로 영구 검색불가(롤백 없음).
    # 수정: 발행을 먼저 하고 실패 시 승인 중단(active 미전환, 검토대기 유지) → 재승인 가능.
    if not _already_embedded:
        try:
            import json as _json
            from uuid import uuid4 as _uuid4

            from aiokafka import AIOKafkaProducer

            from src.common.config import settings as _settings

            blocked_payload = {
                "event_id": str(_uuid4()),
                "document_id": str(doc.id),
                "tenant_id": str(tenant_id),
                "repository_id": str(doc.repository_id),
                "block_count": int(meta.get("total_blocks") or meta.get("chunk_count") or 0),
                "block_types": meta.get("block_types") or {},
                "source_path": doc.source_file or "",
            }
            producer = AIOKafkaProducer(bootstrap_servers=_settings.KAFKA_BOOTSTRAP_SERVERS)
            await producer.start()
            try:
                await producer.send_and_wait(
                    "aicm.document.blocked",
                    value=_json.dumps(blocked_payload).encode("utf-8"),
                )
            finally:
                await producer.stop()
            logger.info("approve_review_embedding_triggered", document_id=str(document_id))
        except Exception as exc:
            logger.error(
                "approve_review_embedding_trigger_failed",
                document_id=str(document_id),
                error=str(exc),
            )
            raise HTTPException(
                status_code=503,
                detail="임베딩 트리거 실패 — 잠시 후 다시 승인해주세요. (문서는 검토대기 상태 유지)",
            )

    doc.status = "active"
    meta["review_decision"] = "approved"
    meta["reviewed_by"] = str(user_id)
    meta["reviewed_at"] = datetime.utcnow().isoformat()
    meta["review_notes"] = review_notes
    meta["current_stage"] = "completed"
    doc.processing_meta = meta
    await db.commit()
    await sync_document_status(doc.id, "active", db)

    logger.info(
        "review_approved_document_active",
        document_id=str(document_id),
        reviewed_by=str(user_id),
    )

    await invalidate_repository_cache(doc.repository_id)
    return ApiResponse(data={
        "document_id": str(document_id),
        "status": "active",
        "message": "리뷰 승인 완료. 문서가 활성화되어 검색이 가능합니다.",
    })


@router.post(
    "/repositories/{repository_id}/documents/{document_id}/review/reject",
    response_model=ApiResponse,
    summary="리뷰 거부 — 문서 반려",
)
async def reject_review(
    repository_id: UUID,
    document_id: UUID,
    reason: str = Form(...),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """pending_review 문서를 거부한다. 재업로드 또는 수정이 필요."""
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"리뷰 대상이 아닙니다. 현재 상태: {doc.status}")

    doc.status = "failed"
    meta = doc.processing_meta or {}
    meta["review_decision"] = "rejected"
    meta["reviewed_by"] = str(user_id)
    meta["reviewed_at"] = datetime.utcnow().isoformat()
    meta["reject_reason"] = reason
    doc.processing_meta = meta
    await db.commit()
    await sync_document_status(doc.id, "failed", db)

    logger.info(
        "review_rejected",
        document_id=str(document_id),
        reason=reason,
        reviewed_by=str(user_id),
    )

    return ApiResponse(data={
        "document_id": str(document_id),
        "status": "failed",
        "message": f"리뷰 거부: {reason}",
    })


@router.get(
    "/repositories/{repository_id}/documents/pending-review",
    response_model=ApiResponse,
    summary="리뷰 대기 문서 목록",
)
async def list_pending_review(
    repository_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """pending_review 상태인 문서 목록을 조회한다."""
    stmt = (
        select(Document)
        .where(
            Document.repository_id == repository_id,
            Document.status == "pending_review",
        )
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()

    items = []
    for doc in docs:
        meta = doc.processing_meta or {}
        items.append({
            "document_id": str(doc.id),
            "title": doc.title,
            "source_format": doc.source_format,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "total_blocks": meta.get("total_blocks", 0),
            "review_required_blocks": len(meta.get("review_items", [])),
            "avg_confidence": meta.get("avg_confidence", 0),
            "review_reasons": list({
                item.get("review_reason", "")
                for item in meta.get("review_items", [])
            }),
        })

    return ApiResponse(data={"count": len(items), "documents": items})


# ---------------------------------------------------------------------------
# PDF 바이너리 스트리밍 — PDF 뷰어용
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{doc_id}/pdf",
    summary="PDF 원본 다운로드",
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_document_pdf(
    doc_id: UUID,
    token: str | None = Query(None, description="Bearer 토큰 (쿼리 파라미터 방식, iframe/pdf.js용)"),
    tenant_id_param: str | None = Query(None, alias="tenant_id", description="테넌트 ID (쿼리 파라미터 방식)"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """문서의 원본 PDF 파일을 스트리밍한다.

    인증: Authorization 헤더 또는 ?token= 쿼리 파라미터.
    테넌트: X-Tenant-Id 헤더 또는 ?tenant_id= 쿼리 파라미터.

    1. DB에서 문서 조회 (테넌트 격리)
    2. source_file 경로에서 파일 읽기
    3. 바이너리 스트리밍 응답
    """
    from pathlib import Path as _Path
    from fastapi.responses import FileResponse, StreamingResponse

    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    # 원본 파일 경로 확인
    source_path = doc.source_file
    if not source_path:
        raise HTTPException(status_code=404, detail="PDF 원본 파일 경로를 찾을 수 없습니다.")

    # MinIO 단일 원천에서 임시파일로 구체화(로컬 존재 시 그대로).
    try:
        _local, _is_temp = await _materialize_source(
            source_path,
            tenant_id=str(tenant_id),
            document_id=str(doc_id),
            ext=_src_ext_from(None, doc.source_format),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"PDF 파일을 찾을 수 없습니다: {source_path}")
    file_path = _Path(_local)
    _bg = BackgroundTask(_cleanup_src_temp, _local, _is_temp)

    # PDF 형식 확인 — 비 PDF 면 (docker/legacy 한정) 같은 디렉토리 변환본 확인.
    #      MinIO 단일 원천에는 아직 변환/프리뷰 PDF 를 보관하지 않으므로 비 PDF 는 400.
    if not file_path.suffix.lower() == ".pdf":
        pdf_variant = file_path.with_suffix(".pdf")
        if not _is_temp and pdf_variant.exists():
            file_path = pdf_variant
        else:
            _cleanup_src_temp(_local, _is_temp)
            raise HTTPException(
                status_code=400,
                detail="PDF 형식이 아닌 문서입니다. PDF 변환본이 없습니다.",
            )

    # RFC 5987 — 비-ASCII 파일명을 Content-Disposition 에 담기 위해
    # ASCII fallback + filename* (UTF-8 percent-encoded) 둘 다 제공.
    # FileResponse 가 내부적으로 headers 를 latin-1 로 인코딩하므로,
    # 원본 한글 제목을 바로 filename 파라미터에 주면 500 에러 발생.
    from urllib.parse import quote as _quote

    raw_title = (doc.title or "document").replace('"', "'")
    ascii_fallback = raw_title.encode("ascii", errors="ignore").decode("ascii").strip()
    if not ascii_fallback:
        ascii_fallback = f"document-{doc.id}"
    ascii_filename = f"{ascii_fallback}.pdf"
    utf8_filename = f"{raw_title}.pdf"

    content_disposition = (
        f'inline; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{_quote(utf8_filename)}"
    )

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        # filename 파라미터는 넘기지 않음 — starlette 가 latin-1 로 인코딩 시도해 충돌
        headers={
            "Content-Disposition": content_disposition,
            "Cache-Control": "private, max-age=3600",
        },
        background=_bg,
    )


# ---------------------------------------------------------------------------
# bbox 복구 — 단일 블럭 / 전체 미매핑 블럭
# ---------------------------------------------------------------------------


@router.post(
    "/documents/{doc_id}/blocks/{block_id}/recover-bbox",
    response_model=ApiResponse,
    summary="블럭 PDF bbox LLM 복구",
)
async def recover_block_bbox(
    doc_id: UUID,
    block_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """단일 블럭의 PDF bbox를 LLM으로 복구한다.

    1. 블럭 내용 + 해당 페이지의 word-level bbox 정보 조합
    2. LLM에게 매칭 요청 / fuzzy fallback
    3. block.source_location.bbox 업데이트
    """
    from src.core.models.block import Block as BlockModel
    from src.pipeline.enrichers.bbox_mapper import BboxMapper

    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    # 블럭 조회
    stmt = select(BlockModel).where(BlockModel.id == block_id, BlockModel.document_id == doc_id)
    result = await db.execute(stmt)
    block = result.scalar_one_or_none()
    if not block:
        raise HTTPException(status_code=404, detail="블럭을 찾을 수 없습니다.")

    # bbox 매퍼 실행
    mapper = BboxMapper()
    try:
        updated_block = await mapper.recover_bbox(block=block, document=doc, db=db)
    finally:
        mapper.close()

    return ApiResponse(data={
        "block_id": str(updated_block.id),
        "source_location": updated_block.source_location,
        "recovered": bool(updated_block.source_location.get("bbox")),
    })


@router.post(
    "/documents/{doc_id}/recover-all-bbox",
    response_model=ApiResponse,
    summary="전체 미매핑 블럭 bbox 복구",
)
async def recover_all_bbox(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """문서 내 bbox 없는 모든 블럭에 대해 LLM bbox 복구를 실행한다."""
    from sqlalchemy import func as sa_func
    from src.core.models.block import Block as BlockModel
    from src.pipeline.enrichers.bbox_mapper import BboxMapper

    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    # bbox 없는 블럭 조회
    stmt = (
        select(BlockModel)
        .where(BlockModel.document_id == doc_id)
        .order_by(BlockModel.block_index)
    )
    result = await db.execute(stmt)
    all_blocks = result.scalars().all()

    unmapped = [
        b for b in all_blocks
        if not (b.source_location or {}).get("bbox")
    ]

    if not unmapped:
        return ApiResponse(data={"recovered": 0, "failed": 0, "total": 0})

    mapper = BboxMapper()
    recovered = 0
    failed = 0

    try:
        for block in unmapped:
            try:
                updated = await mapper.recover_bbox(block=block, document=doc, db=db)
                if (updated.source_location or {}).get("bbox"):
                    recovered += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.warning(
                    "bbox_recovery_failed",
                    block_id=str(block.id),
                    error=str(exc),
                )
                failed += 1
    finally:
        mapper.close()

    return ApiResponse(data={
        "recovered": recovered,
        "failed": failed,
        "total": len(unmapped),
    })


# ---------------------------------------------------------------------------
# 문서 원본 파일 다운로드
# ---------------------------------------------------------------------------

_UPLOADS_ROOT = Path("/data/uploads")

# PDF는 인라인으로 표시, 나머지는 다운로드 첨부
_INLINE_EXTENSIONS = {".pdf"}


@router.get(
    "/documents/{doc_id}/original",
    summary="문서 원본 파일 반환",
    responses={404: {"description": "문서 없음 / 원본 파일 없음"}},
)
async def get_document_original(
    doc_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """문서의 원본 업로드 파일(PDF, DOCX 등)을 반환한다.

    Raises DocumentNotFoundError (→ 404) if document does not exist.
    """
    svc = DocumentService(db)
    doc = await svc.get_by_id(doc_id, tenant_id=tenant_id)

    processing_meta = doc.processing_meta or {}

    # 1) source_file(=MinIO object key 또는 로컬경로)을 MinIO 단일 원천에서 구체화.
    local_path: str | None = None
    is_temp = False
    if doc.source_file:
        try:
            local_path, is_temp = await _materialize_source(
                doc.source_file,
                tenant_id=str(tenant_id),
                document_id=str(doc_id),
                ext=_src_ext_from(None, doc.source_format),
            )
        except FileNotFoundError:
            local_path = None

    # 2) legacy 로컬 후보 fallback (docker/구버전) — traversal 가드 유지.
    if local_path is None:
        for candidate in [
            getattr(doc, "original_path", None),
            processing_meta.get("original_file_path"),
            processing_meta.get("file_path"),
        ]:
            if not candidate:
                continue
            p = Path(candidate)
            if not p.is_absolute():
                p = _UPLOADS_ROOT / p
            try:
                resolved = p.resolve(strict=False)
            except (OSError, ValueError):
                continue
            if not str(resolved).startswith(str(_UPLOADS_ROOT.resolve())):
                logger.warning("path_traversal_attempt", doc_id=str(doc_id), file_path=candidate)
                continue
            if p.is_file():
                local_path = str(p)
                is_temp = False
                break

    if not local_path or not Path(local_path).is_file():
        logger.warning("document_original_file_not_found", doc_id=str(doc_id))
        raise HTTPException(status_code=404, detail="원본 파일을 찾을 수 없습니다")

    file_path = Path(local_path)
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    suffix = file_path.suffix.lower()

    # Content-Disposition: inline for PDFs (browser preview), attachment for others.
    # 임시파일명(aicm_xxx) 대신 문서 제목 기반 파일명을 RFC5987 로 제공(비-ASCII 안전).
    from urllib.parse import quote as _quote

    disposition_type = "inline" if suffix in _INLINE_EXTENSIONS else "attachment"
    raw_title = (doc.title or f"document-{doc.id}").replace('"', "'")
    if not raw_title.lower().endswith(suffix):
        raw_title = f"{raw_title}{suffix}"
    ascii_fallback = raw_title.encode("ascii", errors="ignore").decode("ascii").strip() or f"document-{doc.id}{suffix}"
    content_disposition = (
        f'{disposition_type}; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{_quote(raw_title)}"
    )

    return FileResponse(
        path=str(file_path),
        media_type=content_type,
        headers={"Content-Disposition": content_disposition},
        background=BackgroundTask(_cleanup_src_temp, local_path, is_temp),
    )
