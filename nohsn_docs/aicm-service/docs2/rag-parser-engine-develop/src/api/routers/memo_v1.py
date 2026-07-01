"""``/api/v1/memo`` — Bearer 인증 기반 메모/할 일 CRUD.

schedule_v1 / diary_v1 과 동일 패턴.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from src.agent_framework.tools import memo_store
from src.api.routers.schedule_v1 import (
    _account_id_from_bearer,
    _resolve_args,
)
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/memo", tags=["메모/할일"])


class MemoCreateBody(BaseModel):
    title: str
    note: str | None = None
    deadline_at: str | None = None
    alarm_at: str | None = None
    raw_utterance: str | None = None
    scope_group: str | None = None


class MemoUpdateBody(BaseModel):
    title: str | None = None
    note: str | None = None
    deadline_at: str | None = None
    alarm_at: str | None = None
    status: str | None = None  # active | done | cancelled
    scope_group: str | None = None


@router.get("")
async def list_memos(
    authorization: str = Header(...),
    status: str | None = Query(None, description="active | done | cancelled"),
    scope_group: str | None = Query(None),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    if status:
        args["status"] = status
    if scope_group:
        args["scope_group"] = scope_group
    return await memo_store.list_all(args)


@router.post("")
async def create_memo(
    body: MemoCreateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await memo_store.create(args)


@router.patch("/{mid}")
async def update_memo(
    mid: str,
    body: MemoUpdateBody,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = mid
    args.update({k: v for k, v in body.model_dump().items() if v is not None})
    return await memo_store.update(args)


@router.post("/{mid}/complete")
async def complete_memo(
    mid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = mid
    return await memo_store.complete(args)


@router.delete("/{mid}")
async def delete_memo(
    mid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = mid
    return await memo_store.delete(args)


# ── 지식 등록 (P11-19: 메모를 documents 사본으로 복사) ─────────────────


from pydantic import BaseModel
from sqlalchemy import text as _sa_text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from src.common.config import settings
import json as _json
import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz


class MemoKnowledgeResult(BaseModel):
    memo_id: str
    document_id: str
    title: str


_memo_eng: AsyncEngine | None = None


def _eng() -> AsyncEngine:
    global _memo_eng
    if _memo_eng is None:
        _memo_eng = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _memo_eng


@router.post("/{mid}/register-knowledge")
async def register_memo_as_knowledge(
    mid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    """메모를 지식 문서로 *복사* — 메모는 그대로 유지, documents 에 sibling row.

    제목 = 메모 title, 본문 = "## 메모\n{title}\n\n{note}\n\n## 마감\n{deadline_at}"
    포맷의 markdown. status='active' 로 RAG 노출.
    """
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    args["id"] = mid

    items = await memo_store.list_all({**args, "status": None})
    target = next(
        (
            it
            for it in (items.get("items") or [])
            if str(it.get("id")) == str(mid)
        ),
        None,
    )
    if not target:
        raise HTTPException(404, "메모를 찾을 수 없습니다")

    title = (target.get("title") or "(제목 없음)").strip()
    body_lines = [f"# {title}"]
    if target.get("deadline_at"):
        body_lines.append(f"\n**마감**: {target['deadline_at']}")
    if target.get("alarm_at"):
        body_lines.append(f"**알람**: {target['alarm_at']}")
    if target.get("note"):
        body_lines.append("\n## 본문\n" + target["note"])
    if target.get("raw_utterance"):
        body_lines.append(f"\n*원 발화*: \"{target['raw_utterance']}\"")
    content = "\n".join(body_lines)

    tenant_id = args.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "personal_tenant_id 가 설정되지 않았습니다")

    doc_id = _uuid.uuid4()
    repo_id = await _get_or_create_memo_kb_repo(tenant_id)
    meta = {
        "source_type": "memo_register",
        "memo_id": str(mid),
        "title": title,
        "deadline_at": target.get("deadline_at"),
        "body": {"text": content, "format": "md"},
        "registered_at": _dt.now(_tz.utc).isoformat(),
    }
    async with _eng().begin() as conn:
        await conn.execute(
            _sa_text(
                """
                INSERT INTO documents
                  (id, tenant_id, repository_id, title, source_file, source_format,
                   processing_meta, status)
                VALUES
                  (:id, CAST(:tid AS uuid), CAST(:rid AS uuid), :title,
                   :sfile, 'md', CAST(:meta AS jsonb), 'active')
                """
            ),
            {
                "id": doc_id,
                "tid": tenant_id,
                "rid": repo_id,
                "title": title[:500],
                "sfile": f"memo/{doc_id.hex[:8]}.md",
                "meta": _json.dumps(meta, ensure_ascii=False),
            },
        )
    return {
        "memo_id": str(mid),
        "document_id": str(doc_id),
        "title": title,
        "status": "active",
    }


async def _get_or_create_memo_kb_repo(tenant_id: str) -> str:
    async with _eng().begin() as conn:
        row = (
            await conn.execute(
                _sa_text(
                    "SELECT id::text FROM repositories"
                    " WHERE tenant_id = CAST(:tid AS uuid) AND name = '__memo_register__' LIMIT 1"
                ),
                {"tid": tenant_id},
            )
        ).first()
        if row:
            return str(row[0])
        new_id = _uuid.uuid4()
        await conn.execute(
            _sa_text(
                """
                INSERT INTO repositories
                  (id, tenant_id, name, description, is_active, source_type)
                VALUES
                  (CAST(:id AS uuid), CAST(:tid AS uuid), '__memo_register__',
                   '메모 → 지식 등록', true, 'manual')
                """
            ),
            {"id": str(new_id), "tid": tenant_id},
        )
    return str(new_id)


@router.delete("/{mid}/register-knowledge")
async def unregister_memo_knowledge(
    mid: str,
    authorization: str = Header(...),
) -> dict[str, Any]:
    """메모 등록 취소 — documents 에서 archive (메모 row 무관).

    Cross-tenant 보호: token 에서 추출한 tenant_id 와 documents.tenant_id 가
    일치하는 row 만 archive. 불일치 시 404 (존재 여부 leak 없음).
    """
    aid = _account_id_from_bearer(authorization)
    args = await _resolve_args(aid)
    tenant_id = args.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "personal_tenant_id 가 설정되지 않았습니다")

    async with _eng().begin() as conn:
        result = await conn.execute(
            _sa_text(
                """
                UPDATE documents
                   SET status = 'archived', updated_at = NOW()
                 WHERE processing_meta->>'memo_id' = :mid
                   AND tenant_id = CAST(:tid AS uuid)
                   AND status = 'active'
                RETURNING id::text
                """
            ),
            {"mid": str(mid), "tid": tenant_id},
        )
        rows = result.all()
    if not rows:
        raise HTTPException(404, "memo not found")
    return {"unregistered_count": len(rows)}
