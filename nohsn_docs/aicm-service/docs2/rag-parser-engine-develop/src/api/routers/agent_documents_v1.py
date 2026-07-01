"""``/api/v1/agents/{id}/documents`` — agent 전용 문서 등록 / 조회 라우터.

Phase 1.5E follow-up (2026-05-07). 기존 라이브러리 → 문서 탭 → "지식 작성" 은
tenant scope 공용 repo 에 저장된다. 이 라우터는 *agent 별 격리* 흐름:

- ``GET    /api/v1/agents/{id}/documents``        — 그 agent 의 전용 repo 문서 목록
- ``POST   /api/v1/agents/{id}/documents/upload`` — multipart 업로드 (자동 repo 생성)

자동 repo 생성 정책 (alembic 065 활용):
1. agent.id 의 *전용 repo* (``repositories.agent_id = aid``) 가 있으면 그 repo 에 저장.
2. 없으면 자동 생성:
   - name = ``agent_{slug(agent.name)}_repo`` — 동일 tenant 안 unique. 충돌 시 suffix.
   - tenant_id = agent.tenant_id
   - agent_id = agent.id
   - namespace = agent.repo_namespace (없으면 slug(agent.name))
   - description = "Auto-generated repo for agent {name}"
3. 생성 직후 ``agents.sop_repo_ids`` 와 ``agents.primary_repo_ids`` 자동 추가
   (admin 명시 변경 가능). 이후 SOP RAG / 검색 layer 가 자동 활용.

격리:
- alembic 065 의 partial index 와 ``Layer 2`` (knowledge_isolation) 가 자동 적용.
- baemin agent 가 등록한 문서는 musinsa agent 검색 시 0 hit (cross-leak 0).
- admin (Locus) 도 자기 admin agent 의 전용 repo 사용 가능.

설계 원칙 (사용자 통찰):
- 기존 흐름 보존 — tenant 공용 ``/agent/chat/upload`` 는 변경 0.
- agent scope 의 새 진입점 추가 only.
- 하드코딩 금지 — repo namespace 는 agent.repo_namespace 그대로 사용.
- DetachedInstanceError 패턴 — ORM session 안에서 attribute 추출 후 close.
"""
from __future__ import annotations

import json
import re
import uuid as _uuid
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.api.utils.upload import detect_format, save_upload, validate_file_size
from src.common.config import settings
from src.common.logging import get_logger
from src.core.database import get_db
from src.core.models.document import Document
from src.core.models.repository import Repository
from src.core.services.agent_document_service import AgentDocumentService
from src.core.services.document_service import DocumentService
from src.core.services.repository_service import RepositoryService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["agent-documents"])


# ---------------------------------------------------------------------------
# Auth helpers — agents_v1.py 와 동일 패턴 (cross-tenant 위장 방지).
# ---------------------------------------------------------------------------


def _account_from_token(authorization: str) -> tuple[UUID, str | None, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "empty token")
    try:
        payload = decode_token(token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    if payload.get("type") not in (None, "access"):
        raise HTTPException(401, "not an access token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    try:
        return UUID(str(sub)), payload.get("tenant_id"), payload.get("role") or "member"
    except ValueError as e:
        raise HTTPException(401, f"invalid subject: {e}") from e


def _resolve_tenant(token_tid: str | None, x_tenant_id: str | None) -> UUID:
    """JWT tenant claim authoritative — agents_v1 와 동일 (cross-tenant 위장 방지)."""
    if not token_tid:
        raise HTTPException(400, "tenant scope missing — supply X-Tenant-ID or relogin")
    if x_tenant_id is not None and x_tenant_id != "":
        if str(x_tenant_id) != str(token_tid):
            raise HTTPException(401, "tenant claim mismatch")
    try:
        return UUID(str(token_tid))
    except ValueError as e:
        raise HTTPException(400, f"invalid tenant_id: {e}") from e


async def _verify_membership_role(
    db: AsyncSession, account_id: UUID, tenant_id: UUID
) -> str:
    row = (
        await db.execute(
            text(
                "SELECT role FROM tenant_memberships "
                "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
            ),
            {"aid": account_id, "tid": tenant_id},
        )
    ).first()
    if not row:
        raise HTTPException(403, "not a member of this tenant")
    return row[0]


def _parse_uuid(raw: str, field: str = "id") -> UUID:
    try:
        return UUID(raw)
    except ValueError as e:
        raise HTTPException(400, f"invalid {field}: {e}") from e


# ---------------------------------------------------------------------------
# Auto repo creation
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _slugify(name: str) -> str:
    """Free-form 이름을 repo name 안전 슬러그로 변환."""
    s = _SLUG_RE.sub("_", (name or "").strip().lower())
    s = s.strip("_")
    return s or "agent"


async def _ensure_agent_repo(
    db: AsyncSession,
    *,
    agent_id: UUID,
    tenant_id: UUID,
) -> Repository:
    """agent 의 전용 repo 를 조회하거나 자동 생성한다.

    - ``repositories.agent_id == agent_id`` AND ``is_active == true`` 이면 그 row 반환.
    - 여러 개 있으면 가장 오래된 것 (created_at ASC) 한 개 — 일반 시연 시나리오는 1:1.
    - 없으면 새 repo 생성 + agents.sop_repo_ids/primary_repo_ids 에 자동 추가.

    repo name 충돌 시 ``_2``, ``_3`` 으로 증가.

    DetachedInstanceError 회피 — 호출 측 session 안에서 사용. flush 후 반환.
    """
    # 1. agent ORM fetch — namespace / name / sop_repo_ids 필요.
    agent_row = (
        await db.execute(
            text(
                """
                SELECT id, tenant_id, name, repo_namespace,
                       primary_repo_ids, sop_repo_ids, kind
                  FROM agents WHERE id = :aid
                """
            ),
            {"aid": agent_id},
        )
    ).first()
    if not agent_row:
        raise HTTPException(404, "agent not found")
    if agent_row[1] != tenant_id:
        raise HTTPException(403, "agent does not belong to current tenant")

    a_name = agent_row[2]
    a_namespace = agent_row[3]  # NULL 가능 — admin agent
    primary_ids = list(agent_row[4] or [])
    sop_ids = list(agent_row[5] or [])

    # 2. 기존 전용 repo 존재 검사.
    existing_stmt = (
        select(Repository)
        .where(Repository.agent_id == agent_id)
        .where(Repository.tenant_id == tenant_id)
        .where(Repository.is_active.is_(True))
        .order_by(Repository.created_at.asc())
        .limit(1)
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        return existing

    # 3. 신규 생성 — name 충돌 회피.
    base_slug = _slugify(a_namespace) if a_namespace else _slugify(a_name)
    base_name = f"agent_{base_slug}_repo"
    final_name = base_name
    suffix = 2
    while True:
        clash = (
            await db.execute(
                select(Repository.id).where(
                    Repository.tenant_id == tenant_id,
                    Repository.name == final_name,
                )
            )
        ).first()
        if not clash:
            break
        final_name = f"{base_name}_{suffix}"
        suffix += 1
        if suffix > 99:  # 안전망 — 무한 루프 방지.
            raise HTTPException(500, "failed to allocate unique repo name")

    svc = RepositoryService(db)
    new_repo = await svc.create(
        tenant_id=tenant_id,
        name=final_name,
        description=f"Auto-generated repo for agent {a_name}",
        config={},
    )

    # 4. agent_id + namespace 설정 — alembic 065 격리 layer 활성화.
    new_repo.agent_id = agent_id
    new_repo.namespace = a_namespace or base_slug
    await db.flush()

    # 5. agents.sop_repo_ids / primary_repo_ids 자동 추가 (이미 있으면 skip).
    new_id = new_repo.id
    if new_id not in primary_ids:
        primary_ids.append(new_id)
    if new_id not in sop_ids:
        sop_ids.append(new_id)

    await db.execute(
        text(
            """
            UPDATE agents
               SET primary_repo_ids = :primary,
                   sop_repo_ids = :sop,
                   updated_at = now()
             WHERE id = :aid
            """
        ),
        {
            "primary": primary_ids,
            "sop": sop_ids,
            "aid": agent_id,
        },
    )

    logger.info(
        "agent_repo_auto_created",
        agent_id=str(agent_id),
        repo_id=str(new_id),
        repo_name=final_name,
        namespace=new_repo.namespace,
    )
    return new_repo


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentDocumentItem(BaseModel):
    id: str
    title: str
    status: str
    source_format: str | None = None
    repository_id: str
    created_at: str | None = None
    created_by: str | None = None
    size_bytes: int | None = None
    description: str | None = None


class AgentDocumentsResponse(BaseModel):
    items: list[AgentDocumentItem] = Field(default_factory=list)
    repository_id: str | None = None
    repository_name: str | None = None
    namespace: str | None = None


class AgentUploadResponse(BaseModel):
    document_id: str
    repository_id: str
    status: str
    auto_created_repo: bool = False
    repository_name: str | None = None


# ---------------------------------------------------------------------------
# GET — list documents in agent's dedicated repo
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/documents", response_model=AgentDocumentsResponse)
async def list_agent_documents(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> AgentDocumentsResponse:
    """agent 의 전용 repo 안 문서 목록.

    전용 repo 가 아직 없으면 빈 응답 (auto-create 는 업로드 시점만).
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership_role(db, aid, tid)
    target_id = _parse_uuid(agent_id, "agent_id")

    # agent tenant 검증
    a_row = (
        await db.execute(
            text("SELECT tenant_id FROM agents WHERE id = :aid"),
            {"aid": target_id},
        )
    ).first()
    if not a_row:
        raise HTTPException(404, "agent not found")
    if a_row[0] != tid:
        raise HTTPException(403, "agent does not belong to current tenant")

    # 전용 repo (없을 수 있음 — 첫 업로드 전).
    repo_row = (
        await db.execute(
            select(Repository)
            .where(Repository.agent_id == target_id)
            .where(Repository.tenant_id == tid)
            .where(Repository.is_active.is_(True))
            .order_by(Repository.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if not repo_row:
        return AgentDocumentsResponse(items=[], repository_id=None, repository_name=None)

    docs_stmt = (
        select(Document)
        .where(Document.repository_id == repo_row.id)
        .where(Document.status.notin_(["archived"]))
        .order_by(Document.created_at.desc())
        .limit(limit)
    )
    docs = (await db.execute(docs_stmt)).scalars().all()

    items: list[AgentDocumentItem] = []
    for d in docs:
        size_bytes: int | None = None
        try:
            meta = d.processing_meta or {}
            if isinstance(meta, dict):
                size_bytes = meta.get("size_bytes") or meta.get("file_size")
        except Exception:
            size_bytes = None
        items.append(
            AgentDocumentItem(
                id=str(d.id),
                title=d.title,
                status=d.status,
                source_format=d.source_format,
                repository_id=str(d.repository_id),
                created_at=d.created_at.isoformat() if d.created_at else None,
                created_by=str(d.created_by) if d.created_by else None,
                size_bytes=size_bytes,
                description=d.description,
            )
        )

    return AgentDocumentsResponse(
        items=items,
        repository_id=str(repo_row.id),
        repository_name=repo_row.name,
        namespace=repo_row.namespace,
    )


# ---------------------------------------------------------------------------
# POST — upload to agent's dedicated repo (auto-create if missing)
# ---------------------------------------------------------------------------


async def _publish_upload_event_v2(
    document_id: UUID,
    tenant_id: UUID,
    repository_id: UUID,
    source_format: str,
    source_path: str,
) -> None:
    """KMS 파이프라인 Kafka 이벤트 발행 — documents.py 의 _publish_upload_event 와 동일.

    Kafka 가 없으면 silent. (개발/테스트 호환)
    """
    try:
        from datetime import datetime as _dt

        from aiokafka import AIOKafkaProducer

        from src.common.constants import TOPIC_DOCUMENT_UPLOADED

        event = {
            "event_id": str(uuid4()),
            "document_id": str(document_id),
            "tenant_id": str(tenant_id),
            "repository_id": str(repository_id),
            "source_format": source_format,
            "source_path": source_path,
            "config_override": None,
            "timestamp": _dt.utcnow().isoformat(),
        }
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await producer.start()
        try:
            await producer.send_and_wait(
                TOPIC_DOCUMENT_UPLOADED,
                value=json.dumps(event).encode("utf-8"),
            )
            logger.info(
                "agent_doc_kafka_event_published",
                doc_id=str(document_id),
                repo_id=str(repository_id),
            )
        finally:
            await producer.stop()
    except Exception as exc:
        logger.error(
            "agent_doc_kafka_publish_failed",
            doc_id=str(document_id),
            error=str(exc),
        )
        raise RuntimeError(
            f"파이프라인 큐(Kafka) 전송 실패: {exc}. 잠시 후 다시 시도하거나 재업로드 해주세요."
        ) from exc


@router.post(
    "/{agent_id}/documents/upload",
    response_model=AgentUploadResponse,
    status_code=201,
)
async def upload_agent_document(
    agent_id: str,
    file: UploadFile,
    title: str | None = Form(None),
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> AgentUploadResponse:
    """agent 의 전용 repo 에 문서 업로드.

    흐름:
      1. JWT + tenant_membership (admin/owner) 검증.
      2. agent 의 전용 repo 조회 — 없으면 자동 생성 (alembic 065 layer 자동 활성).
      3. 파일 검증 + ``/data/uploads/{tenant}/{repo}/`` 저장.
      4. ``documents`` INSERT (status=processing).
      5. Kafka ``aicm.document.uploaded`` 발행 → 기존 KMS 파이프라인 합류.
      6. 응답: ``{document_id, repository_id, status, auto_created_repo}``.

    포맷: PDF / docx / md / txt / html / xlsx — 기존 ``detect_format`` 화이트리스트.
    """
    aid, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership_role(db, aid, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")

    # 1-2. repo 조회 / 자동 생성.
    repo = await _ensure_agent_repo(db, agent_id=target_id, tenant_id=tid)
    auto_created = repo.created_at is None or (
        # heuristic — repo 가 방금 생성되었는가? (rolled-back 가능성 회피용 best-effort)
        False
    )
    # 더 정확한 auto_created flag — repo.id 가 documents 에 한 번도 안 쓰였는가?
    # 기존 repo 도 첫 업로드면 동일하므로 명시적 검사 X — 단순히 "있던 repo
    # 였는지 vs 새로 만든 repo 였는지"는 호출자에게 별 의미 없음.
    # 대신 namespace / agent_id 가 매칭되는지를 응답에 첨부.

    # 3. 파일 검증 + 디스크 저장.
    await validate_file_size(file)
    source_format = detect_format(file.filename or "unknown", file.content_type)
    file_path = await save_upload(file, tid, repo.id)

    # 3.5. (옵션 Y v2) agent default folder 자동 보장.
    ad_svc = AgentDocumentService(db)
    try:
        # agent 이름 확보 — folder 이름에 사용.
        agent_name_row = (
            await db.execute(
                text("SELECT name FROM agents WHERE id = :aid"),
                {"aid": target_id},
            )
        ).first()
        agent_name = agent_name_row[0] if agent_name_row else None
        default_folder_id = await ad_svc.ensure_default_folder(
            agent_id=target_id,
            tenant_id=tid,
            repository_id=repo.id,
            agent_name=agent_name,
        )
    except Exception as exc:
        logger.error(
            "agent_default_folder_ensure_failed",
            agent_id=str(target_id),
            error=str(exc),
        )
        default_folder_id = None

    # 4. Document INSERT (DocumentService).
    resolved_title = title or file.filename or "Untitled"
    svc = DocumentService(db)
    doc = await svc.create(
        repository_id=repo.id,
        tenant_id=tid,
        title=resolved_title,
        source_file=file_path,
        source_format=source_format,
        document_type_id=None,
        category_ids=[],
        created_by=aid,
    )
    await svc.transition_status(doc.id, target_status="processing")
    # default folder 채우기 (옵션 Y v2 — 자동 분류).
    if default_folder_id is not None:
        await db.execute(
            text("UPDATE documents SET folder_id = :fid WHERE id = :did"),
            {"fid": default_folder_id, "did": doc.id},
        )
    # agent_documents INSERT (mode='kms' default, source='uploaded').
    try:
        await ad_svc.link_bulk(
            agent_id=target_id,
            tenant_id=tid,
            document_ids=[doc.id],
            mode="kms",
            source="uploaded",
        )
    except Exception as exc:
        logger.error(
            "agent_doc_auto_link_failed",
            agent_id=str(target_id),
            doc_id=str(doc.id),
            error=str(exc),
        )
    await db.flush()

    # auto_created 판정 — 신규 repo (sop_repo_ids 갓 등록) 이면 documents 가
    # 1건만 (방금 INSERT 한 것) 일 것. 정확도가 절대치는 아니지만 UI hint 용.
    cnt_row = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM documents WHERE repository_id = :rid"
            ),
            {"rid": repo.id},
        )
    ).first()
    auto_created = bool(cnt_row and int(cnt_row[0]) == 1)

    # 5. Kafka 이벤트 발행 — best-effort (Kafka 없으면 RuntimeError).
    try:
        await _publish_upload_event_v2(
            document_id=doc.id,
            tenant_id=tid,
            repository_id=repo.id,
            source_format=source_format,
            source_path=file_path,
        )
    except RuntimeError as e:
        # 파이프라인 큐 전송 실패는 심각 — 504 로 변환 (호출 측 retry 유도).
        # 단, 문서 row 는 이미 INSERT 됨 — 운영자가 reprocess 로 회복 가능.
        logger.error(
            "agent_doc_kafka_failed_doc_orphan",
            doc_id=str(doc.id),
            repo_id=str(repo.id),
            error=str(e),
        )
        raise HTTPException(504, str(e)) from e

    return AgentUploadResponse(
        document_id=str(doc.id),
        repository_id=str(repo.id),
        status="processing",
        auto_created_repo=auto_created,
        repository_name=repo.name,
    )


# ---------------------------------------------------------------------------
# 옵션 Y v2 — agent_documents 매핑 endpoints (4 종)
# ---------------------------------------------------------------------------


class AgentDocumentMappingItem(BaseModel):
    """GET /agents/{id}/documents 의 단일 row.

    document 메타 + agent_documents.mode/source 결합. 기존 AgentDocumentItem 과
    별개 (mapping 테이블 권위).
    """

    document_id: str
    mode: str
    source: str
    title: str
    status: str
    source_format: str | None = None
    repository_id: str | None = None
    folder_id: str | None = None
    is_sop: bool = False
    size_bytes: int | None = None
    created_by: str | None = None
    doc_created_at: str | None = None
    mapping_created_at: str | None = None


class AgentDocumentMappingsResponse(BaseModel):
    items: list[AgentDocumentMappingItem] = Field(default_factory=list)


class AgentDocumentLinkBody(BaseModel):
    """POST /agents/{id}/documents — bulk link picker."""

    document_ids: list[str] = Field(default_factory=list, min_length=1)
    mode: str = Field(default="kms", pattern="^(sop|kms)$")
    source: str = Field(default="shared", pattern="^(shared|uploaded)$")


class AgentDocumentLinkResponse(BaseModel):
    linked: int = 0
    missing: int = 0
    attempted: int = 0


class AgentDocumentModePatch(BaseModel):
    mode: str = Field(pattern="^(sop|kms)$")


@router.get(
    "/{agent_id}/documents/mappings",
    response_model=AgentDocumentMappingsResponse,
)
async def list_agent_document_mappings(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    mode: str | None = Query(None, regex="^(sop|kms)$"),
    db: AsyncSession = Depends(get_db),
) -> AgentDocumentMappingsResponse:
    """옵션 Y v2 — agent_documents 매핑 (mode 별 SOP/지식자료) 목록.

    기존 ``GET /agents/{id}/documents`` 는 agent 전용 repo 의 *모든* 문서를
    그대로 반환 (옛 호환). 이 endpoint 는 agent_documents 테이블이 권위로 가진
    매핑만 반환 — Phase 4 RAG retrieval 의 정답 소스.
    """
    aid_caller, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership_role(db, aid_caller, tid)
    target_id = _parse_uuid(agent_id, "agent_id")

    svc = AgentDocumentService(db)
    try:
        rows = await svc.list_for_agent(
            agent_id=target_id, tenant_id=tid, mode=mode
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e

    items = [
        AgentDocumentMappingItem(
            document_id=r["document_id"],
            mode=r["mode"],
            source=r["source"],
            title=r["title"],
            status=r["status"],
            source_format=r["source_format"],
            repository_id=r["repository_id"],
            folder_id=r["folder_id"],
            is_sop=bool(r["is_sop"]),
            size_bytes=r["size_bytes"],
            created_by=r["created_by"],
            doc_created_at=r["doc_created_at"],
            mapping_created_at=r["created_at"],
        )
        for r in rows
    ]
    return AgentDocumentMappingsResponse(items=items)


class AgentDocumentsSummaryBySource(BaseModel):
    """OverviewTab chip 진실 source — by_source breakdown."""

    sop_mapping: int = 0
    sop_repo_inferred: int = 0
    kms_mapping: int = 0
    kms_repo_inferred: int = 0


class AgentDocumentsSummaryResponse(BaseModel):
    """GET /agents/{aid}/documents/summary 응답.

    UNION semantics — agent_documents.mode (mapping 권위) ∪ repo_inferred
    (sop_repo_ids / primary∪fallback_repo_ids 의 doc.is_sop OR folder.kind).
    mapping 우선 dedupe + sop/kms disjoint 보장 (GPT-5 P0).

    sop_rag_mode: 운영 가시성 — FEATURE_SOP_RAG flag 활성 상태.
        on  = SopInjectLayer 가 매 turn 동적 inject
        off = guidelines_md 정적 prepend (옛 동작)
    """

    sop: int = 0
    kms: int = 0
    total: int = 0
    by_source: AgentDocumentsSummaryBySource = Field(
        default_factory=AgentDocumentsSummaryBySource
    )
    sop_rag_mode: str = "off"


@router.get(
    "/{agent_id}/documents/summary",
    response_model=AgentDocumentsSummaryResponse,
)
async def get_agent_documents_summary(
    agent_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> AgentDocumentsSummaryResponse:
    """agent 단위 SOP/지식자료 doc count.

    OverviewTab chip "지식 분포" 의 진실 source. AgentDocumentsPanel 의
    KindBadge 분포와 동일 UNION semantics 로 view 일관성 보장.

    Spec: docs/superpowers/specs/2026-05-07-sop-kms-prompt-architecture.md
    (§4.3 SQL + §4.4 disjoint 보장)

    cross-tenant 격리: agent.tenant_id 와 호출자 tenant_id 일치 검증 +
    server 가 agent_id 로 sop_repo_ids/primary/fallback 직접 조회 (payload
    신뢰 X — GPT-5 P0).
    """
    aid_caller, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    await _verify_membership_role(db, aid_caller, tid)
    target_id = _parse_uuid(agent_id, "agent_id")

    svc = AgentDocumentService(db)
    try:
        result = await svc.count_summary(
            agent_id=target_id, tenant_id=tid
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e

    # FEATURE_SOP_RAG 운영 가시성 — tenant scope 활성 상태 반영.
    sop_rag_mode = "off"
    try:
        from src.common.feature_flags import FeatureFlag, is_enabled

        sop_rag_mode = "on" if is_enabled(
            FeatureFlag.SOP_RAG, tenant_id=str(tid)
        ) else "off"
    except Exception:  # noqa: BLE001
        sop_rag_mode = "off"

    return AgentDocumentsSummaryResponse(
        sop=result["sop"],
        kms=result["kms"],
        total=result["total"],
        by_source=AgentDocumentsSummaryBySource(**result["by_source"]),
        sop_rag_mode=sop_rag_mode,
    )


@router.post(
    "/{agent_id}/documents/mappings",
    response_model=AgentDocumentLinkResponse,
    status_code=200,
)
async def link_agent_documents(
    agent_id: str,
    body: AgentDocumentLinkBody,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> AgentDocumentLinkResponse:
    """옵션 Y v2 — 기존 문서를 agent 에 link (M-A picker 시나리오).

    - 다중 doc id 지원.
    - cross-tenant doc 은 missing (404 동등) — 정보 누출 차단.
    - ON CONFLICT DO NOTHING — 멱등.
    """
    aid_caller, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership_role(db, aid_caller, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")

    try:
        doc_uuids = [_parse_uuid(d, "document_id") for d in body.document_ids]
    except HTTPException:
        raise
    if not doc_uuids:
        raise HTTPException(400, "document_ids must not be empty")

    svc = AgentDocumentService(db)
    try:
        result = await svc.link_bulk(
            agent_id=target_id,
            tenant_id=tid,
            document_ids=doc_uuids,
            mode=body.mode,
            source=body.source,
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    return AgentDocumentLinkResponse(**result)


@router.delete(
    "/{agent_id}/documents/mappings/{document_id}",
    status_code=204,
)
async def unlink_agent_document(
    agent_id: str,
    document_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> None:
    aid_caller, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership_role(db, aid_caller, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")
    doc_uuid = _parse_uuid(document_id, "document_id")

    svc = AgentDocumentService(db)
    try:
        deleted = await svc.unlink(
            agent_id=target_id, tenant_id=tid, document_id=doc_uuid
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    if not deleted:
        raise HTTPException(404, "mapping not found")


@router.patch(
    "/{agent_id}/documents/mappings/{document_id}",
    status_code=200,
)
async def patch_agent_document_mode(
    agent_id: str,
    document_id: str,
    body: AgentDocumentModePatch,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """옵션 Y v2 — agent 단위 mode toggle (SOP ↔ 지식자료)."""
    aid_caller, token_tid, _ = _account_from_token(authorization)
    tid = _resolve_tenant(token_tid, x_tenant_id)
    role = await _verify_membership_role(db, aid_caller, tid)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "owner or admin role required")
    target_id = _parse_uuid(agent_id, "agent_id")
    doc_uuid = _parse_uuid(document_id, "document_id")

    svc = AgentDocumentService(db)
    try:
        updated = await svc.set_mode(
            agent_id=target_id,
            tenant_id=tid,
            document_id=doc_uuid,
            mode=body.mode,
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not updated:
        raise HTTPException(404, "mapping not found")
    return {"document_id": str(doc_uuid), "mode": body.mode}
