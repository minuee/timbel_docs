"""/api/v1/inbox — 자비스 이메일 처리 시나리오 backend (Phase A).

frontend 호출:
- ``GET  /api/v1/inbox``                            — 메일함 list view
- ``GET  /api/v1/inbox/log``                        — 처리 로그 timeline (전체 보기)
- ``GET  /api/v1/inbox/summary``                    — chat 의 "오늘 메일 정리해줘" 응답 자료
- ``GET  /api/v1/inbox/{log_id}``                   — detail (원본 + 처리 결과 + 파생 액션)
- ``POST /api/v1/inbox/{log_id}/actions/create_schedule`` — 일정 자동 추가
- ``POST /api/v1/inbox/{log_id}/actions/create_todo``     — 할일/리마인더 자동 추가
- ``POST /api/v1/inbox/{log_id}/actions/draft_reply``     — LLM 답변 초안

원칙:
- 모든 endpoint 는 JWT sub 의 account_id 격리 — 사용자 자기 데이터만.
- POST /actions/* 는 ``confirmed=true`` 일 때만 실행 (frontend 사용자 클릭 후).
- ``actions_taken`` JSONB array append: ``actions_taken = actions_taken || '[<new>]'::jsonb``.
- engine 의 _build_engine 싱글턴 의존 X — schedule_store/reminder_store 직접 import.

mirror worker / classifier 는 별도 agent 가 담당. 본 라우터는 *읽기 + deterministic 액션*.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

# KMS-only image (.dockerignore drops src/agent_framework) - top-level imports lazy-guarded
# so module load succeeds. KMS endpoint hits that actually use these will fail with
# NoneType/AttributeError; KMS 운영에서 inbox endpoint 호출하지 않으면 무영향.
try:
    from src.agent_framework.llm.vllm_adapter import VLLMAdapter
    from src.agent_framework.tools import reminder_store, schedule_store
except ModuleNotFoundError:
    VLLMAdapter = None  # type: ignore[assignment]
    reminder_store = None  # type: ignore[assignment]
    schedule_store = None  # type: ignore[assignment]
from src.api.auth.jwt_utils import InvalidToken, decode_token


# chat_v1 module 의 top-level Depends(get_agent_engine) 가 KMS image 에서 모듈 로딩 시 폭발.
# wrapper 로 endpoint 호출 시점까지 chat_v1 import 를 미룸.
def _get_engine():
    from src.api.routers.chat_v1 import _get_engine as _impl
    return _impl()


from src.api.schemas.common import ApiResponse


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/inbox", tags=["Inbox"])


# ---------------------------------------------------------------------------
# auth helpers
# ---------------------------------------------------------------------------


def _scope(authorization: str, x_tenant_id: str | None) -> tuple[UUID, UUID | None]:
    """JWT sub → (account_id, tenant_id?). chat_v1 의 _scope 와 동일 패턴이지만
    tenant_id 가 없어도 inbox 는 account 격리만으로 충분 — Optional 로 둔다.

    Phase 1.5A Task 8c.2 (2026-05-07): JWT tenant claim authoritative 으로
    승격. 헤더 mismatch → 401. claim 부재 시 헤더 무시·None 폴백.
    """
    from src.api.routers._tenant_scope import resolve_tenant_id

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        payload = decode_token(authorization[7:].strip())
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "missing subject")
    if payload.get("tenant_id"):
        tid_str: str | None = resolve_tenant_id(payload, x_tenant_id)
    else:
        if x_tenant_id is not None and x_tenant_id != "":
            raise HTTPException(401, "tenant claim mismatch")
        tid_str = None
    try:
        aid = UUID(str(sub))
        tid = UUID(str(tid_str)) if tid_str else None
    except ValueError as e:
        raise HTTPException(400, f"invalid uuid: {e}") from e
    return aid, tid


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class InboxListItem(BaseModel):
    log_id: UUID
    document_id: UUID | None = None
    mail_account_id: UUID | None = None
    from_address: str | None = None
    from_domain: str | None = None
    subject: str | None = None
    received_at: datetime | None = None
    processed_at: datetime
    category: str
    trust_score: float | None = None
    priority: str | None = None
    needs_user_attention: bool = False
    action_count: int = 0
    extracted_entity_summary: str | None = None
    # 2026-05-06 — 지식 등록 여부. documents.status='active' 면 RAG 검색에 노출.
    # 메일은 기본 viewer-only 이고 사용자가 명시적으로 등록 체크 시에만 active 로 전환.
    knowledge_active: bool = False
    document_status: str | None = None


class InboxLogRow(InboxListItem):
    """list view + 액션 timeline 까지 포함."""

    actions_taken: list[dict[str, Any]] = Field(default_factory=list)


class InboxDetail(BaseModel):
    log_id: UUID
    # Layer 1 — 원본
    document_id: UUID | None = None
    from_address: str | None = None
    from_domain: str | None = None
    to_address: str | None = None
    subject: str | None = None
    received_at: datetime | None = None
    body_text: str = ""
    body_html: str | None = None
    headers: dict[str, Any] = Field(default_factory=dict)
    # Layer 1+ — 첨부 이미지 OCR 결과 (gemma-4-31b vision + sha256 cache)
    ocr_text: list[dict[str, Any]] = Field(default_factory=list)
    # Layer 2 — 처리 결과
    classification: dict[str, Any] = Field(default_factory=dict)
    trust_score: float | None = None
    # Layer 2+ — 정규화된 일정/엔티티 요약 (list 응답과 동일 source)
    extracted_entity_summary: str | None = None
    category: str | None = None
    priority: str | None = None
    needs_user_attention: bool = False
    # Layer 3 — 파생 액션
    actions_taken: list[dict[str, Any]] = Field(default_factory=list)


class CategoryGroup(BaseModel):
    category: str
    count: int
    items: list[InboxListItem]
    has_more: bool = False


class InboxSummary(BaseModel):
    period: dict[str, str]
    total_count: int
    by_category: list[CategoryGroup]


class CreateScheduleFromEmail(BaseModel):
    title_override: str | None = None
    when_override: str | None = None
    where_override: str | None = None
    confirmed: bool = True


class CreateTodoFromEmail(BaseModel):
    title_override: str | None = None
    when_override: str | None = None
    template_override: str | None = None
    confirmed: bool = True


class DraftReplyRequest(BaseModel):
    tone: str = Field(default="professional", pattern="^(professional|casual|brief)$")
    user_intent: str | None = None


class CreateScheduleResult(BaseModel):
    schedule_id: str | None = None
    summary: str
    duplicate: bool = False


class CreateTodoResult(BaseModel):
    summary: str
    at: str | None = None
    duplicate: bool = False


class DraftReplyResult(BaseModel):
    draft_subject: str
    draft_body: str
    send_endpoint_hint: str


# ---------------------------------------------------------------------------
# Helpers — row → schema 변환
# ---------------------------------------------------------------------------


def _classification_category(cls: dict[str, Any] | None) -> str:
    if not cls:
        return "unknown"
    return str(cls.get("category") or "unknown")


def _classification_priority(cls: dict[str, Any] | None) -> str | None:
    if not cls:
        return None
    p = cls.get("priority")
    return str(p) if p is not None else None


def _entity_summary(cls: dict[str, Any] | None) -> str | None:
    """frontend 목록용 한 줄 — datetime 정규화 결과 우선.

    우선순위:
    1. ``extracted_entities.entity_summary_iso`` (classifier v2 — '(2026-04-29 15:00 KST, 온라인)' 형식)
    2. legacy: ``subject_summary``
    """
    if not cls:
        return None
    ents = cls.get("extracted_entities") or {}
    if not isinstance(ents, dict):
        return None
    iso_summary = ents.get("entity_summary_iso")
    if iso_summary:
        return str(iso_summary)
    summary = ents.get("subject_summary")
    return str(summary) if summary else None


def _needs_attention(cls: dict[str, Any] | None) -> bool:
    if not cls:
        return False
    # classification 이 명시적으로 needs_user_attention 을 박았거나, priority=high.
    if cls.get("needs_user_attention") is True:
        return True
    return str(cls.get("priority") or "").lower() == "high"


def _row_to_list_item(row: Any) -> InboxListItem:
    cls = row.classification or {}
    actions = row.actions_taken or []
    doc_status = getattr(row, "document_status", None)
    return InboxListItem(
        log_id=row.id,
        document_id=row.document_id,
        mail_account_id=getattr(row, "mail_account_id", None),
        from_address=row.from_address,
        from_domain=row.from_domain,
        subject=row.subject,
        received_at=row.received_at,
        processed_at=row.processed_at,
        category=_classification_category(cls),
        trust_score=row.trust_score,
        priority=_classification_priority(cls),
        needs_user_attention=_needs_attention(cls),
        action_count=len(actions) if isinstance(actions, list) else 0,
        extracted_entity_summary=_entity_summary(cls),
        knowledge_active=(doc_status == "active"),
        document_status=doc_status,
    )


def _row_to_log_row(row: Any) -> InboxLogRow:
    base = _row_to_list_item(row)
    actions = row.actions_taken or []
    return InboxLogRow(
        **base.model_dump(),
        actions_taken=actions if isinstance(actions, list) else [],
    )


# ---------------------------------------------------------------------------
# 1. GET /api/v1/inbox
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ApiResponse[list[InboxListItem]],
    summary="메일함 list view",
    description=(
        "처리된 메일을 시간 역순으로 반환한다. since/until 로 기간 필터, "
        "classification 으로 카테고리 (meeting_request/notice 등) 필터, "
        "mail_account_id 로 특정 계정 한정. 기본 기간은 최근 30일."
    ),
    responses={200: {"description": "메일 list 항목 배열 (기본 30일치)"}},
    tags=["Inbox"],
)
async def list_inbox(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    since: datetime | None = Query(None, description="ISO datetime — 기본 30일 전"),
    until: datetime | None = Query(None, description="ISO datetime — 기본 now"),
    classification: str | None = Query(None, description="category 필터 (meeting_request 등)"),
    mail_account_id: UUID | None = Query(
        None, description="메일 계정 필터 (user_mail_accounts.id) — 미지정 시 전체"
    ),
    min_trust: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ApiResponse[list[InboxListItem]]:
    aid, _tid = _scope(authorization, x_tenant_id)
    now = datetime.now(timezone.utc)
    if until is None:
        until = now
    if since is None:
        since = until - timedelta(days=30)

    params: dict[str, Any] = {
        "aid": aid,
        "since": since,
        "until": until,
        "min_trust": min_trust,
        "limit": limit,
        "offset": offset,
    }
    cls_clause = ""
    if classification:
        cls_clause = " AND (classification ->> 'category') = :cls"
        params["cls"] = classification
    mail_clause = ""
    if mail_account_id:
        mail_clause = " AND l.mail_account_id = :mid"
        params["mid"] = mail_account_id

    sql = f"""
        SELECT l.id, l.document_id, l.from_address, l.from_domain, l.subject,
               l.received_at, l.processed_at, l.classification, l.trust_score, l.actions_taken,
               l.mail_account_id, d.status AS document_status
        FROM email_processing_log l
        LEFT JOIN documents d ON d.id = l.document_id
        WHERE l.account_id = :aid
          AND l.processed_at BETWEEN :since AND :until
          AND (l.trust_score IS NULL OR l.trust_score >= :min_trust)
          {cls_clause}
          {mail_clause}
        ORDER BY l.processed_at DESC
        LIMIT :limit OFFSET :offset
    """
    db = _get_engine()
    async with db.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()
    items = [_row_to_list_item(r) for r in rows]
    return ApiResponse(data=items)


# ---------------------------------------------------------------------------
# 2. GET /api/v1/inbox/log
# ---------------------------------------------------------------------------


@router.get(
    "/log",
    response_model=ApiResponse[list[InboxLogRow]],
    summary="처리 로그 timeline (전체)",
    description=(
        "메일 처리 로그를 시간 역순 timeline 으로 반환한다. "
        "list view 와 달리 분류 필터 없이 모든 처리 결과를 그대로 노출. "
        "디버깅/감사 용도. 기본 기간 최근 30일."
    ),
    responses={200: {"description": "처리 로그 행 배열"}},
    tags=["Inbox"],
)
async def list_inbox_log(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ApiResponse[list[InboxLogRow]]:
    aid, _tid = _scope(authorization, x_tenant_id)
    now = datetime.now(timezone.utc)
    if until is None:
        until = now
    if since is None:
        since = until - timedelta(days=30)
    params = {
        "aid": aid,
        "since": since,
        "until": until,
        "limit": limit,
        "offset": offset,
    }
    sql = """
        SELECT l.id, l.document_id, l.from_address, l.from_domain, l.subject,
               l.received_at, l.processed_at, l.classification, l.trust_score, l.actions_taken,
               d.status AS document_status
        FROM email_processing_log l
        LEFT JOIN documents d ON d.id = l.document_id
        WHERE l.account_id = :aid
          AND l.processed_at BETWEEN :since AND :until
        ORDER BY l.processed_at DESC
        LIMIT :limit OFFSET :offset
    """
    db = _get_engine()
    async with db.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()
    items = [_row_to_log_row(r) for r in rows]
    return ApiResponse(data=items)


# ---------------------------------------------------------------------------
# 3. GET /api/v1/inbox/summary
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=ApiResponse[InboxSummary],
    summary="분류별 그룹 요약 (chat 의 inbox.summary tool 응답)",
    description=(
        "메일을 LLM 분류 카테고리별로 그룹화하여 반환한다. 큰 그룹부터 정렬되며, "
        "각 그룹은 head 5건 + has_more flag 로 노출. 챗봇의 inbox.summary tool 이 "
        "이 endpoint 를 호출한다. 기본 기간은 오늘 00:00 ~ now."
    ),
    responses={200: {"description": "InboxSummary (period + total_count + by_category)"}},
    tags=["Inbox"],
)
async def inbox_summary(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
) -> ApiResponse[InboxSummary]:
    aid, _tid = _scope(authorization, x_tenant_id)
    now = datetime.now(timezone.utc)
    if until is None:
        until = now
    if since is None:
        # 기본 = 오늘 00:00 (서버 UTC 기준 — frontend 가 timezone 명시하면 since 직접 전달)
        since = until.replace(hour=0, minute=0, second=0, microsecond=0)

    db = _get_engine()
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, document_id, from_address, from_domain, subject,
                           received_at, processed_at, classification, trust_score, actions_taken
                    FROM email_processing_log
                    WHERE account_id = :aid
                      AND processed_at BETWEEN :since AND :until
                    ORDER BY processed_at DESC
                    """
                ),
                {"aid": aid, "since": since, "until": until},
            )
        ).all()

    # category 별 group
    groups: dict[str, list[InboxListItem]] = {}
    for r in rows:
        item = _row_to_list_item(r)
        groups.setdefault(item.category, []).append(item)

    by_category: list[CategoryGroup] = []
    # 큰 그룹 먼저 (descending count)
    for cat, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        head = items[:5]
        by_category.append(
            CategoryGroup(
                category=cat,
                count=len(items),
                items=head,
                has_more=len(items) > 5,
            )
        )

    summary = InboxSummary(
        period={"start": since.isoformat(), "end": until.isoformat()},
        total_count=len(rows),
        by_category=by_category,
    )
    return ApiResponse(data=summary)


# ---------------------------------------------------------------------------
# 4. GET /api/v1/inbox/{log_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{log_id}",
    response_model=ApiResponse[InboxDetail],
    summary="메일 detail (원본 + 처리 결과 + 액션)",
    description=(
        "단일 메일의 원본 메타데이터, LLM 분류 결과, 추출 entity, "
        "수행된 액션(일정/할일/초안) 이력을 모두 반환한다. "
        "본인 소유 계정의 메일만 조회 가능."
    ),
    responses={
        200: {"description": "InboxDetail"},
        404: {"description": "메일을 찾을 수 없음"},
    },
    tags=["Inbox"],
)
async def get_inbox_detail(
    log_id: UUID,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[InboxDetail]:
    aid, _tid = _scope(authorization, x_tenant_id)
    db = _get_engine()
    async with db.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT id, document_id, from_address, from_domain, subject,
                           received_at, processed_at, classification, trust_score,
                           actions_taken, message_id
                    FROM email_processing_log
                    WHERE id = :id AND account_id = :aid
                    """
                ),
                {"id": log_id, "aid": aid},
            )
        ).first()
        if row is None:
            raise HTTPException(404, "메일을 찾을 수 없습니다")

        # KMS document body fetch (Layer 1 원본)
        body_text = ""
        body_html: str | None = None
        headers: dict[str, Any] = {}
        to_address: str | None = None
        ocr_text_items: list[dict[str, Any]] = []
        if row.document_id is not None:
            # documents.processing_meta.body 에 mirror worker 가 박아둔 raw 메일
            doc = (
                await conn.execute(
                    text(
                        """
                        SELECT processing_meta
                        FROM documents
                        WHERE id = :doc_id
                        """
                    ),
                    {"doc_id": row.document_id},
                )
            ).first()
            if doc is not None:
                meta = doc.processing_meta or {}
                body = (meta.get("body") if isinstance(meta, dict) else None) or {}
                if isinstance(body, dict):
                    body_text = str(body.get("text") or body.get("body_text") or "")
                    bh = body.get("html") or body.get("body_html")
                    body_html = str(bh) if bh else None
                    h = body.get("headers") or {}
                    if isinstance(h, dict):
                        headers = h
                    to_address = body.get("to") or body.get("to_address")
                    # 첨부 이미지 OCR 결과 — webhook_inbound 가 OCR 후 박아둔다.
                    ocr = body.get("ocr_text")
                    if isinstance(ocr, list):
                        ocr_text_items = [
                            o for o in ocr if isinstance(o, dict)
                        ]

            # body_text 가 비었으면 sections.content concat (legacy/alt source)
            if not body_text:
                secs = (
                    await conn.execute(
                        text(
                            """
                            SELECT content FROM sections
                            WHERE document_id = :doc_id
                            ORDER BY section_order ASC
                            """
                        ),
                        {"doc_id": row.document_id},
                    )
                ).all()
                if secs:
                    body_text = "\n\n".join((s.content or "") for s in secs)

    actions = row.actions_taken or []
    cls = row.classification or {}
    detail = InboxDetail(
        log_id=row.id,
        document_id=row.document_id,
        from_address=row.from_address,
        from_domain=row.from_domain,
        to_address=to_address,
        subject=row.subject,
        received_at=row.received_at,
        body_text=body_text,
        body_html=body_html,
        headers=headers if isinstance(headers, dict) else {},
        ocr_text=ocr_text_items,
        classification=cls if isinstance(cls, dict) else {},
        trust_score=row.trust_score,
        extracted_entity_summary=_entity_summary(cls),
        category=_classification_category(cls),
        priority=_classification_priority(cls),
        needs_user_attention=_needs_attention(cls),
        actions_taken=actions if isinstance(actions, list) else [],
    )
    return ApiResponse(data=detail)


# ---------------------------------------------------------------------------
# 4. POST /api/v1/inbox/{log_id}/knowledge — 지식 등록 토글
# ---------------------------------------------------------------------------


class KnowledgeToggleBody(BaseModel):
    active: bool


class KnowledgeToggleResult(BaseModel):
    log_id: UUID
    document_id: UUID | None
    knowledge_active: bool
    document_status: str | None


@router.post(
    "/{log_id}/knowledge",
    response_model=ApiResponse[KnowledgeToggleResult],
    summary="메일을 지식 정보로 등록 / 등록 취소 (status active ↔ archived 토글)",
)
async def toggle_knowledge_registration(
    log_id: UUID,
    body: KnowledgeToggleBody,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[KnowledgeToggleResult]:
    """메일은 기본적으로 viewer-only — 사용자가 명시적으로 *지식 등록* 체크 시에만
    documents.status 를 'active' 로 올려 RAG 검색에 노출. 취소 시 'archived' 로
    내려 검색에서 제외하되 메일 자체는 그대로 보존 (email_processing_log row 무관).
    """
    aid, _tid = _scope(authorization, x_tenant_id)
    row = await _fetch_log_or_404(log_id, aid)
    doc_id = row.document_id
    if doc_id is None:
        raise HTTPException(
            400,
            "이 메일에는 연결된 지식 문서가 없습니다 (자동 저장 누락). 메일을 다시 불러와주세요.",
        )

    new_status = "active" if body.active else "archived"
    db = _get_engine()
    async with db.begin() as conn:
        result = await conn.execute(
            text(
                """
                UPDATE documents
                   SET status = :st, updated_at = NOW()
                 WHERE id = :did
                RETURNING status
                """
            ),
            {"st": new_status, "did": doc_id},
        )
        applied = result.scalar()
    if applied is None:
        raise HTTPException(404, "연결된 문서를 찾을 수 없습니다")

    await _append_action(
        log_id,
        aid,
        {
            "kind": "knowledge_toggle",
            "active": body.active,
            "document_id": str(doc_id),
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )

    return ApiResponse(
        data=KnowledgeToggleResult(
            log_id=log_id,
            document_id=doc_id,
            knowledge_active=(applied == "active"),
            document_status=str(applied) if applied else None,
        )
    )


# ---------------------------------------------------------------------------
# Helper — actions_taken JSONB append
# ---------------------------------------------------------------------------


async def _append_action(log_id: UUID, account_id: UUID, action: dict[str, Any]) -> None:
    """email_processing_log.actions_taken 에 JSONB append.

    `actions_taken = actions_taken || '[<new>]'::jsonb` — atomic.
    """
    db = _get_engine()
    async with db.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE email_processing_log
                   SET actions_taken = actions_taken || CAST(:new AS jsonb)
                 WHERE id = :id AND account_id = :aid
                """
            ),
            {
                "id": log_id,
                "aid": account_id,
                "new": json.dumps([action], ensure_ascii=False),
            },
        )


async def _fetch_log_or_404(log_id: UUID, account_id: UUID) -> Any:
    db = _get_engine()
    async with db.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT id, document_id, from_address, subject, received_at,
                           classification, actions_taken
                    FROM email_processing_log
                    WHERE id = :id AND account_id = :aid
                    """
                ),
                {"id": log_id, "aid": account_id},
            )
        ).first()
    if row is None:
        raise HTTPException(404, "메일을 찾을 수 없습니다")
    return row


# ---------------------------------------------------------------------------
# 5. POST /api/v1/inbox/{log_id}/actions/create_schedule
# ---------------------------------------------------------------------------


@router.post(
    "/{log_id}/actions/create_schedule",
    response_model=ApiResponse[CreateScheduleResult],
    summary="메일 → 일정 자동 추가",
    description=(
        "메일에서 LLM 이 추출한 일정 정보 (datetime_iso/location/attendees) 로 "
        "일정을 생성한다. 사용자 확인 의도 보호를 위해 `confirmed=true` 가 필수. "
        "datetime_iso 가 추출 안 되면 when_override 로 명시 지정 필요. "
        "결과는 메일의 actions_taken 에 append."
    ),
    responses={
        200: {"description": "일정 등록 결과 (id + duplicate flag + summary)"},
        400: {"description": "confirmed=false 또는 시각 추출 실패"},
        404: {"description": "메일 미발견"},
        500: {"description": "일정 store 실패"},
    },
    tags=["Inbox"],
)
async def create_schedule_from_email(
    log_id: UUID,
    body: CreateScheduleFromEmail,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[CreateScheduleResult]:
    if not body.confirmed:
        raise HTTPException(400, "confirmed=true 일 때만 실행됩니다")
    aid, tid = _scope(authorization, x_tenant_id)
    if tid is None:
        raise HTTPException(400, "tenant_id 가 필요합니다 (X-Tenant-ID 헤더 또는 토큰)")

    row = await _fetch_log_or_404(log_id, aid)
    cls = row.classification or {}
    ents = cls.get("extracted_entities") or {} if isinstance(cls, dict) else {}

    title = body.title_override or row.subject or (ents.get("subject_summary") if isinstance(ents, dict) else None) or "메일 일정"
    when = body.when_override or (ents.get("datetime_iso") if isinstance(ents, dict) else None)
    if not when:
        raise HTTPException(
            400, "일정 시각 (datetime_iso) 을 추출할 수 없습니다. when_override 로 지정하세요."
        )
    where = body.where_override or (ents.get("location") if isinstance(ents, dict) else None)
    who = ents.get("attendees") if isinstance(ents, dict) else None

    args: dict[str, Any] = {
        "tenant_id": str(tid),
        "title": str(title),
        "when": str(when),
        "where": str(where) if where else None,
        "who": who,
    }
    result = await schedule_store.create(args)
    if not result.get("success"):
        raise HTTPException(500, f"일정 등록 실패: {result.get('error')}")

    schedule_id = str(result.get("id") or "")
    duplicate = bool(result.get("duplicate"))
    summary_text = (
        result.get("summary")
        or (f"'{title}' 일정 등록 완료 ({when})" if not duplicate else "이미 등록된 일정")
    )

    action = {
        "type": "schedule_created",
        "schedule_id": schedule_id,
        "summary": summary_text,
        "title": str(title),
        "when": str(when),
        "where": str(where) if where else None,
        "duplicate": duplicate,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await _append_action(log_id, aid, action)
    logger.info(
        "inbox_schedule_created",
        log_id=str(log_id),
        account_id=str(aid),
        schedule_id=schedule_id,
        duplicate=duplicate,
    )
    return ApiResponse(
        data=CreateScheduleResult(
            schedule_id=schedule_id or None,
            summary=summary_text,
            duplicate=duplicate,
        )
    )


# ---------------------------------------------------------------------------
# 6. POST /api/v1/inbox/{log_id}/actions/create_todo
# ---------------------------------------------------------------------------


@router.post(
    "/{log_id}/actions/create_todo",
    response_model=ApiResponse[CreateTodoResult],
    summary="메일 → 할일/리마인더 자동 추가",
    description=(
        "메일에서 추출한 액션 요구사항을 기반으로 할일 (reminder) 를 등록한다. "
        "template = action_required / subject_summary / subject 순으로 fallback. "
        "트리거 시각 = datetime_iso / deadline / now+1h fallback. "
        "사용자 확인 의도 보호를 위해 `confirmed=true` 필수."
    ),
    responses={
        200: {"description": "할일 등록 결과"},
        400: {"description": "confirmed=false 또는 tenant_id 누락"},
        404: {"description": "메일 미발견"},
        500: {"description": "reminder store 실패"},
    },
    tags=["Inbox"],
)
async def create_todo_from_email(
    log_id: UUID,
    body: CreateTodoFromEmail,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[CreateTodoResult]:
    if not body.confirmed:
        raise HTTPException(400, "confirmed=true 일 때만 실행됩니다")
    aid, tid = _scope(authorization, x_tenant_id)
    if tid is None:
        raise HTTPException(400, "tenant_id 가 필요합니다 (X-Tenant-ID 헤더 또는 토큰)")

    row = await _fetch_log_or_404(log_id, aid)
    cls = row.classification or {}
    ents = cls.get("extracted_entities") or {} if isinstance(cls, dict) else {}

    # template = 사용자에게 알릴 메시지. action_required > subject_summary > subject 순서.
    template = (
        body.template_override
        or (ents.get("action_required") if isinstance(ents, dict) else None)
        or (ents.get("subject_summary") if isinstance(ents, dict) else None)
        or (body.title_override if body.title_override else None)
        or row.subject
        or "메일 관련 할 일"
    )
    # at = reminder 트리거 시각. when_override > datetime_iso > deadline > now+1h.
    at = (
        body.when_override
        or (ents.get("datetime_iso") if isinstance(ents, dict) else None)
        or (ents.get("deadline") if isinstance(ents, dict) else None)
    )
    if not at:
        # default fallback — 1시간 후 알림
        at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    args: dict[str, Any] = {
        "tenant_id": str(tid),
        "at": str(at),
        "channel": "inapp",
        "template": str(template),
    }
    result = await reminder_store.schedule(args)
    if not result.get("success"):
        raise HTTPException(500, f"할일 등록 실패: {result.get('error')}")

    duplicate = bool(result.get("duplicate"))
    summary_text = result.get("summary") or (
        f"'{str(template)[:60]}' 알림 예약 ({at})" if not duplicate else "이미 등록된 할 일"
    )

    action = {
        "type": "todo_created",
        "summary": summary_text,
        "at": str(at),
        "template": str(template),
        "duplicate": duplicate,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await _append_action(log_id, aid, action)
    logger.info(
        "inbox_todo_created",
        log_id=str(log_id),
        account_id=str(aid),
        at=str(at),
        duplicate=duplicate,
    )
    return ApiResponse(
        data=CreateTodoResult(
            summary=summary_text,
            at=str(at),
            duplicate=duplicate,
        )
    )


# ---------------------------------------------------------------------------
# 7. POST /api/v1/inbox/{log_id}/actions/draft_reply
# ---------------------------------------------------------------------------


_DRAFT_SYSTEM_PROMPT = (
    "당신은 사용자의 답변 초안 작성자입니다. 원 메일 본문과 사용자가 추가로 알린 의도를 보고 "
    "한국어로 정중한 답변 한 단락을 작성하세요. 절대 메일을 전송하지 않습니다 — 초안만 제공합니다.\n"
    "출력 형식:\n"
    "subject: <답신 제목 한 줄>\n"
    "body: <답신 본문 한 단락>\n"
    "톤이 'professional' 이면 격식체, 'casual' 이면 친근체, 'brief' 이면 3문장 이내."
)


def _parse_draft(raw: str, fallback_subject: str) -> tuple[str, str]:
    """LLM 출력에서 subject / body 분리. 형식 어긋나면 전체를 body 로."""
    subject = ""
    body_lines: list[str] = []
    in_body = False
    for line in (raw or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if not in_body and low.startswith("subject:"):
            subject = stripped.split(":", 1)[1].strip()
        elif not in_body and low.startswith("body:"):
            in_body = True
            after = stripped.split(":", 1)[1].strip()
            if after:
                body_lines.append(after)
        elif in_body:
            body_lines.append(line)
        else:
            # 형식 안 맞으면 그대로 누적
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    if not subject:
        subject = f"Re: {fallback_subject}" if fallback_subject else "Re:"
    if not body:
        body = (raw or "").strip()
    return subject, body


@router.post(
    "/{log_id}/actions/draft_reply",
    response_model=ApiResponse[DraftReplyResult],
    summary="LLM 답변 초안 생성 (전송 X)",
    description=(
        "원본 메일 + 사용자 의도 노트 (intent) 를 LLM 에 전달해 답신 초안을 생성한다. "
        "톤: professional (격식체) / casual (친근체) / brief (3문장 이내). "
        "결과는 subject/body 분리. 절대 발송하지 않으며 — 사용자가 검토 후 "
        "별도 mail 전송 endpoint 호출 필요."
    ),
    responses={
        200: {"description": "초안 (subject + body) + model_used"},
        404: {"description": "메일 미발견"},
        503: {"description": "LLM 서비스 미연결"},
    },
    tags=["Inbox"],
)
async def draft_reply(
    log_id: UUID,
    body: DraftReplyRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> ApiResponse[DraftReplyResult]:
    aid, _tid = _scope(authorization, x_tenant_id)

    # 원본 메일 fetch — get_inbox_detail 와 동일 로직 (간소화)
    db = _get_engine()
    async with db.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT id, document_id, from_address, subject, received_at,
                           classification
                    FROM email_processing_log
                    WHERE id = :id AND account_id = :aid
                    """
                ),
                {"id": log_id, "aid": aid},
            )
        ).first()
        if row is None:
            raise HTTPException(404, "메일을 찾을 수 없습니다")

        body_text = ""
        if row.document_id is not None:
            doc = (
                await conn.execute(
                    text(
                        "SELECT processing_meta FROM documents WHERE id = :id"
                    ),
                    {"id": row.document_id},
                )
            ).first()
            if doc is not None:
                meta = doc.processing_meta or {}
                src_body = (meta.get("body") if isinstance(meta, dict) else None) or {}
                if isinstance(src_body, dict):
                    body_text = str(src_body.get("text") or src_body.get("body_text") or "")
            if not body_text:
                secs = (
                    await conn.execute(
                        text(
                            """
                            SELECT content FROM sections
                            WHERE document_id = :id ORDER BY section_order ASC
                            """
                        ),
                        {"id": row.document_id},
                    )
                ).all()
                if secs:
                    body_text = "\n\n".join((s.content or "") for s in secs)

    # prompt 구성
    user_intent_block = (
        f"\n\n사용자 추가 의도:\n{body.user_intent}" if body.user_intent else ""
    )
    user_prompt = (
        f"톤: {body.tone}\n"
        f"보낸이: {row.from_address or '(미상)'}\n"
        f"제목: {row.subject or '(제목 없음)'}\n\n"
        f"원 메일 본문:\n{body_text or '(본문 없음)'}"
        f"{user_intent_block}\n\n"
        "위 정보를 바탕으로 답변 초안을 작성하세요."
    )

    llm = VLLMAdapter()
    try:
        raw = await llm.complete(_DRAFT_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("inbox_draft_reply_llm_failed")
        raise HTTPException(502, f"LLM 호출 실패: {exc}") from exc

    draft_subject, draft_body = _parse_draft(raw, fallback_subject=row.subject or "")

    # actions_taken 에 draft_generated 기록 (preview = 본문 첫 100자)
    preview = (draft_body or "")[:100]
    action = {
        "type": "draft_generated",
        "preview": preview,
        "subject": draft_subject,
        "tone": body.tone,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _append_action(log_id, aid, action)
    logger.info(
        "inbox_draft_generated",
        log_id=str(log_id),
        account_id=str(aid),
        tone=body.tone,
    )

    return ApiResponse(
        data=DraftReplyResult(
            draft_subject=draft_subject,
            draft_body=draft_body,
            send_endpoint_hint="별도 SMTP 등록 후 전송 가능",
        )
    )
