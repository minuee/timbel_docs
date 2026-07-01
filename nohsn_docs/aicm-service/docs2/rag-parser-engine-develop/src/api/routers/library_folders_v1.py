"""Library Folders API — repo 안 트리(디렉터리) 분류 + 문서 이동.

라이브러리 UI 트리 개선 (alembic 067). repo 별 self-referential 트리 + 문서
folder_id 이동을 제공한다.

Endpoints:
    GET    /api/v1/repos/{repo_id}/folders          폴더 트리 (재귀)
    POST   /api/v1/repos/{repo_id}/folders          신규 폴더
    PATCH  /api/v1/folders/{folder_id}              이름/부모 변경
    DELETE /api/v1/folders/{folder_id}              폴더 삭제 (?cascade=true)
    PATCH  /api/v1/documents/{doc_id}/move          문서 1건 이동
    POST   /api/v1/documents/bulk-move              문서 N건 일괄 이동

설계 원칙:
- folder 는 분류 전용 — KMS 검색 무영향 (repo_id/agent_id 격리 유지).
- 파일 충돌 방지 — documents 라우터 (documents.py) 와 path 분리:
  여기 ``/documents/{id}/move`` 와 ``/documents/bulk-move`` 는 documents.py 에 없는 신규 path.
- tenant 격리 — 모든 endpoint 에서 ``tenant_id == X-Tenant-Id`` 강제.
- 안전 삭제 — 안에 doc / sub-folder 가 있으면 ``cascade=false`` (default) 일 때 409.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_tenant_id, get_current_user_id
from src.api.schemas.common import ApiResponse
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.models.document import Document
from src.core.models.library_folder import LibraryFolder
from src.core.models.repository import Repository

logger = get_logger(__name__)

router = APIRouter(tags=["라이브러리 폴더"])


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------


class FolderNode(BaseModel):
    """폴더 트리 노드 (재귀).

    alembic 068 — ``kind`` 추가. 폴더 자체의 분류 (sop/manual/glossary/faq/policy).
    기본 'manual'. 5 봇 reseed 시 LLM 분류로 채움.
    """

    id: str
    name: str
    parent_folder_id: str | None = None
    repository_id: str
    # alembic 068 — 폴더 분류. 기본 'manual'.
    kind: str = "manual"
    children: list["FolderNode"] = Field(default_factory=list)
    document_count: int = 0


FolderNode.model_rebuild()


class FolderCreate(BaseModel):
    """폴더 신규 요청."""

    name: str = Field(..., min_length=1, max_length=200)
    parent_folder_id: UUID | None = None
    # alembic 068 — 폴더 분류. enum 값 (sop/manual/glossary/faq/policy).
    # 명시 X 면 'manual' (DB server_default).
    kind: str | None = Field(
        None,
        description="폴더 분류: sop / manual / glossary / faq / policy. 기본 'manual'.",
    )


class FolderUpdate(BaseModel):
    """폴더 이름 변경 / 부모 이동 / kind 변경."""

    name: str | None = Field(None, min_length=1, max_length=200)
    parent_folder_id: UUID | None = None
    # 명시적 root 이동을 위한 sentinel — JSON 에서 ``"parent_folder_id": null`` 보내면
    # pydantic 은 None 으로 받고, 미지정과 구분 X. 이 플래그가 true 면 강제 root.
    move_to_root: bool = False
    # alembic 068 — 폴더 분류 변경. None 이면 미변경.
    kind: str | None = Field(
        None,
        description="폴더 분류 변경: sop / manual / glossary / faq / policy.",
    )


# alembic 068 — kind 화이트리스트 (CHECK constraint 와 동일). 라우터에서 사전 검증.
ALLOWED_FOLDER_KINDS = {"sop", "manual", "glossary", "faq", "policy"}


class DocumentMoveRequest(BaseModel):
    """문서 1건 이동."""

    folder_id: UUID | None = None  # None = root


class BulkMoveRequest(BaseModel):
    """문서 N건 일괄 이동."""

    document_ids: list[UUID] = Field(..., min_length=1)
    folder_id: UUID | None = None


class BulkMoveResponse(BaseModel):
    """일괄 이동 결과."""

    moved: int
    skipped: int


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


async def _ensure_repo_owned(
    db: AsyncSession, repo_id: UUID, tenant_id: UUID
) -> Repository:
    """repo 가 이 tenant 소속인지 확인."""
    row = await db.execute(
        select(Repository).where(
            Repository.id == repo_id,
            Repository.tenant_id == tenant_id,
        )
    )
    repo = row.scalar_one_or_none()
    if not repo:
        raise HTTPException(404, "repository not found")
    return repo


async def _ensure_folder_owned(
    db: AsyncSession, folder_id: UUID, tenant_id: UUID
) -> LibraryFolder:
    """폴더가 이 tenant 소속인지 확인."""
    row = await db.execute(
        select(LibraryFolder).where(
            LibraryFolder.id == folder_id,
            LibraryFolder.tenant_id == tenant_id,
        )
    )
    folder = row.scalar_one_or_none()
    if not folder:
        raise HTTPException(404, "folder not found")
    return folder


async def _build_tree(
    db: AsyncSession, repo_id: UUID, tenant_id: UUID
) -> list[FolderNode]:
    """repo 안 모든 폴더를 한 번에 가져와 트리로 재구성. 폴더별 doc count 포함."""

    # 1) 모든 폴더 (single query).
    folders_result = await db.execute(
        select(LibraryFolder)
        .where(
            LibraryFolder.repository_id == repo_id,
            LibraryFolder.tenant_id == tenant_id,
        )
        .order_by(LibraryFolder.name)
    )
    folders = list(folders_result.scalars().all())

    # 2) 폴더별 doc count (single aggregate query).
    counts_result = await db.execute(
        select(Document.folder_id, func.count(Document.id))
        .where(
            Document.repository_id == repo_id,
            Document.tenant_id == tenant_id,
            Document.folder_id.isnot(None),
        )
        .group_by(Document.folder_id)
    )
    counts: dict[UUID, int] = {fid: int(cnt) for fid, cnt in counts_result.all()}

    # 3) FolderNode dict 작성.
    nodes: dict[UUID, FolderNode] = {}
    for f in folders:
        nodes[f.id] = FolderNode(
            id=str(f.id),
            name=f.name,
            parent_folder_id=str(f.parent_folder_id) if f.parent_folder_id else None,
            repository_id=str(f.repository_id),
            # alembic 068 — 폴더 분류 (default 'manual').
            kind=getattr(f, "kind", "manual") or "manual",
            children=[],
            document_count=counts.get(f.id, 0),
        )

    # 4) 부모 - 자식 연결.
    roots: list[FolderNode] = []
    for f in folders:
        node = nodes[f.id]
        if f.parent_folder_id and f.parent_folder_id in nodes:
            nodes[f.parent_folder_id].children.append(node)
        else:
            roots.append(node)

    # 자식들도 정렬 (안정성).
    def _sort_recursive(items: list[FolderNode]) -> None:
        items.sort(key=lambda n: n.name.lower())
        for it in items:
            _sort_recursive(it.children)

    _sort_recursive(roots)
    return roots


async def _is_descendant(
    db: AsyncSession, candidate_parent_id: UUID, target_folder_id: UUID
) -> bool:
    """candidate_parent_id 가 target_folder_id 의 하위 후손인지 확인 (cycle 방지).

    target 을 candidate 안으로 옮기면 cycle 이 생기는지를 체크한다.
    """
    if candidate_parent_id == target_folder_id:
        return True
    # 부모 체인을 root 까지 따라 올라가면서 target 마주치면 cycle.
    cur: UUID | None = candidate_parent_id
    visited: set[UUID] = set()
    while cur is not None:
        if cur in visited:
            return False  # 방어 — 정상적이면 발생 X
        visited.add(cur)
        row = await db.execute(
            select(LibraryFolder.parent_folder_id).where(LibraryFolder.id == cur)
        )
        parent = row.scalar_one_or_none()
        if parent is None:
            return False
        if parent == target_folder_id:
            return True
        cur = parent
    return False


# ---------------------------------------------------------------------------
# Endpoints — 폴더
# ---------------------------------------------------------------------------


@router.get(
    "/repos/{repo_id}/folders",
    response_model=ApiResponse[list[FolderNode]],
    summary="repo 안 폴더 트리",
)
async def list_folders(
    repo_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[list[FolderNode]]:
    """repo 안 모든 폴더를 트리(재귀)로 반환."""
    await _ensure_repo_owned(db, repo_id, tenant_id)
    tree = await _build_tree(db, repo_id, tenant_id)
    return ApiResponse(success=True, data=tree)


@router.post(
    "/repos/{repo_id}/folders",
    response_model=ApiResponse[FolderNode],
    summary="폴더 신규 생성",
)
async def create_folder(
    repo_id: UUID,
    payload: FolderCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
    user_id: UUID | None = Depends(get_current_user_id),
) -> ApiResponse[FolderNode]:
    """repo 안에 폴더 신규 생성. parent_folder_id NULL = root."""
    await _ensure_repo_owned(db, repo_id, tenant_id)

    # parent 가 같은 repo 의 폴더인지 검증.
    if payload.parent_folder_id is not None:
        parent = await _ensure_folder_owned(db, payload.parent_folder_id, tenant_id)
        if parent.repository_id != repo_id:
            raise HTTPException(400, "parent folder not in same repository")

    # 같은 부모 안 이름 중복 차단 (DB unique 가 잡지만, 친절 메시지).
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "name required")

    existing = await db.execute(
        select(LibraryFolder.id).where(
            LibraryFolder.repository_id == repo_id,
            LibraryFolder.parent_folder_id == payload.parent_folder_id,
            func.lower(LibraryFolder.name) == name.lower(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "folder with same name already exists in this parent")

    # alembic 068 — kind 검증 (None 이면 default 'manual' 채택).
    folder_kind = (payload.kind or "manual").lower()
    if folder_kind not in ALLOWED_FOLDER_KINDS:
        raise HTTPException(
            400,
            f"invalid kind '{folder_kind}' — allowed: {sorted(ALLOWED_FOLDER_KINDS)}",
        )

    folder = LibraryFolder(
        tenant_id=tenant_id,
        repository_id=repo_id,
        parent_folder_id=payload.parent_folder_id,
        name=name,
        kind=folder_kind,
        created_by=user_id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    return ApiResponse(
        success=True,
        data=FolderNode(
            id=str(folder.id),
            name=folder.name,
            parent_folder_id=(
                str(folder.parent_folder_id) if folder.parent_folder_id else None
            ),
            repository_id=str(folder.repository_id),
            kind=folder.kind or "manual",
            children=[],
            document_count=0,
        ),
    )


@router.patch(
    "/folders/{folder_id}",
    response_model=ApiResponse[FolderNode],
    summary="폴더 이름 변경 / 부모 이동",
)
async def update_folder(
    folder_id: UUID,
    payload: FolderUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[FolderNode]:
    """폴더 이름 변경 또는 다른 폴더로 이동 (move).

    - ``name`` 만 변경 — 같은 부모 안 이름 중복 차단.
    - ``parent_folder_id`` 변경 (move) — cycle 방지 (자기 후손으로 이동 차단).
    - ``move_to_root: true`` — 명시적 root 이동.
    """
    folder = await _ensure_folder_owned(db, folder_id, tenant_id)

    # 부모 변경 처리.
    new_parent_id: UUID | None = folder.parent_folder_id
    parent_changed = False
    if payload.move_to_root:
        new_parent_id = None
        parent_changed = folder.parent_folder_id is not None
    elif payload.parent_folder_id is not None:
        if payload.parent_folder_id == folder.id:
            raise HTTPException(400, "cannot move folder into itself")
        # 같은 repo 안 폴더인지 + cycle 검증.
        target_parent = await _ensure_folder_owned(db, payload.parent_folder_id, tenant_id)
        if target_parent.repository_id != folder.repository_id:
            raise HTTPException(400, "cannot move folder across repositories")
        if await _is_descendant(db, payload.parent_folder_id, folder.id):
            raise HTTPException(400, "cannot move folder into its descendant (cycle)")
        new_parent_id = payload.parent_folder_id
        parent_changed = new_parent_id != folder.parent_folder_id

    # 이름 변경 처리.
    new_name = folder.name
    name_changed = False
    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(400, "name cannot be empty")
        name_changed = new_name != folder.name

    # alembic 068 — kind 변경 처리.
    new_kind = folder.kind or "manual"
    kind_changed = False
    if payload.kind is not None:
        candidate = payload.kind.lower()
        if candidate not in ALLOWED_FOLDER_KINDS:
            raise HTTPException(
                400,
                f"invalid kind '{candidate}' — allowed: {sorted(ALLOWED_FOLDER_KINDS)}",
            )
        kind_changed = candidate != (folder.kind or "manual")
        new_kind = candidate

    if not parent_changed and not name_changed and not kind_changed:
        # no-op 이지만 200 + 현재 상태 반환 (idempotent).
        pass
    else:
        # 이름 중복 검증 (이동 + 이름변경 후 새 위치 기준).
        dup = await db.execute(
            select(LibraryFolder.id).where(
                LibraryFolder.repository_id == folder.repository_id,
                LibraryFolder.parent_folder_id == new_parent_id,
                func.lower(LibraryFolder.name) == new_name.lower(),
                LibraryFolder.id != folder.id,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(409, "folder with same name already exists in target parent")

        folder.name = new_name
        folder.parent_folder_id = new_parent_id
        folder.kind = new_kind
        await db.commit()
        await db.refresh(folder)

    # doc count 다시 계산 (단일 폴더만).
    cnt = await db.execute(
        select(func.count(Document.id)).where(
            Document.folder_id == folder.id,
            Document.tenant_id == tenant_id,
        )
    )
    doc_count = int(cnt.scalar_one() or 0)

    return ApiResponse(
        success=True,
        data=FolderNode(
            id=str(folder.id),
            name=folder.name,
            parent_folder_id=(
                str(folder.parent_folder_id) if folder.parent_folder_id else None
            ),
            repository_id=str(folder.repository_id),
            kind=folder.kind or "manual",
            children=[],
            document_count=doc_count,
        ),
    )


@router.delete(
    "/folders/{folder_id}",
    response_model=ApiResponse[dict[str, Any]],
    summary="폴더 삭제",
)
async def delete_folder(
    folder_id: UUID,
    cascade: bool = Query(False, description="true 면 자식 폴더 + 문서 회수 강제"),
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict[str, Any]]:
    """폴더 삭제.

    - ``cascade=false`` (default): 안에 자식 폴더 / 문서가 있으면 409.
    - ``cascade=true``: 자식 폴더는 DB CASCADE 로 삭제, 문서는 SET NULL 로 root 회수.
    """
    folder = await _ensure_folder_owned(db, folder_id, tenant_id)

    # 자식 폴더 / 문서 카운트.
    child_cnt = await db.execute(
        select(func.count(LibraryFolder.id)).where(
            LibraryFolder.parent_folder_id == folder.id
        )
    )
    doc_cnt = await db.execute(
        select(func.count(Document.id)).where(Document.folder_id == folder.id)
    )
    n_children = int(child_cnt.scalar_one() or 0)
    n_docs = int(doc_cnt.scalar_one() or 0)

    if not cascade and (n_children > 0 or n_docs > 0):
        raise HTTPException(
            409,
            f"folder not empty: {n_children} sub-folders, {n_docs} documents — "
            f"add ?cascade=true to force",
        )

    # 삭제 — CASCADE 가 자식 폴더 정리, SET NULL 이 doc.folder_id 정리.
    await db.execute(delete(LibraryFolder).where(LibraryFolder.id == folder.id))
    await db.commit()

    return ApiResponse(
        success=True,
        data={
            "deleted_folder_id": str(folder.id),
            "released_documents": n_docs,
            "deleted_subfolders": n_children,
        },
    )


# ---------------------------------------------------------------------------
# Endpoints — 문서 이동
# ---------------------------------------------------------------------------


@router.patch(
    "/documents/{doc_id}/move",
    response_model=ApiResponse[dict[str, Any]],
    summary="문서 1건을 다른 폴더로 이동",
)
async def move_document(
    doc_id: UUID,
    payload: DocumentMoveRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[dict[str, Any]]:
    """문서를 다른 폴더 (또는 root) 로 이동. folder 는 같은 repo 여야 함."""
    doc_row = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == tenant_id,
        )
    )
    doc = doc_row.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "document not found")

    # 폴더 검증 — 같은 repo 의 폴더만 허용.
    if payload.folder_id is not None:
        folder = await _ensure_folder_owned(db, payload.folder_id, tenant_id)
        if folder.repository_id != doc.repository_id:
            raise HTTPException(400, "folder must belong to same repository as document")

    doc.folder_id = payload.folder_id
    await db.commit()

    return ApiResponse(
        success=True,
        data={
            "document_id": str(doc.id),
            "folder_id": str(payload.folder_id) if payload.folder_id else None,
        },
    )


@router.post(
    "/documents/bulk-move",
    response_model=ApiResponse[BulkMoveResponse],
    summary="문서 N건 일괄 이동",
)
async def bulk_move_documents(
    payload: BulkMoveRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant_id),
) -> ApiResponse[BulkMoveResponse]:
    """문서 여러 건을 같은 폴더 (또는 root) 로 이동.

    skipped — repo 가 다른 문서 / 미존재 문서 / 이 tenant 소속 아닌 문서.
    """
    if not payload.document_ids:
        raise HTTPException(400, "document_ids required")

    # 대상 문서들 조회.
    docs_result = await db.execute(
        select(Document).where(
            Document.id.in_(payload.document_ids),
            Document.tenant_id == tenant_id,
        )
    )
    docs = list(docs_result.scalars().all())
    if not docs:
        return ApiResponse(success=True, data=BulkMoveResponse(moved=0, skipped=len(payload.document_ids)))

    # 폴더 검증.
    target_repo_id: UUID | None = None
    if payload.folder_id is not None:
        folder = await _ensure_folder_owned(db, payload.folder_id, tenant_id)
        target_repo_id = folder.repository_id

    moved_ids: list[UUID] = []
    skipped = 0
    for doc in docs:
        if target_repo_id is not None and doc.repository_id != target_repo_id:
            skipped += 1
            continue
        moved_ids.append(doc.id)

    skipped += len(payload.document_ids) - len(docs)

    if moved_ids:
        await db.execute(
            update(Document)
            .where(Document.id.in_(moved_ids))
            .values(folder_id=payload.folder_id)
        )
        await db.commit()

    return ApiResponse(
        success=True,
        data=BulkMoveResponse(moved=len(moved_ids), skipped=skipped),
    )
