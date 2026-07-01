"""``/api/v1/doc-draft`` — gemma-4-31b 기반 문서 초안 생성 + 지식 등록.

UI: chat-style 프롬프트 + 포맷 선택 (md / docx / pptx). 답변은 Markdown 본문으로
스트림. 사용자 승인 시 documents 테이블에 INSERT (status='active').

PPT/DOCX 변환은 backend 에서 markdown → 단순 변환 또는 frontend download.
시연 시점엔 Markdown 본문 자체를 지식 등록 + format 메타로 기록.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from starlette.responses import StreamingResponse

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/doc-draft", tags=["문서생성"])

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


def _account_id_from_bearer(authorization: str) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization[7:].strip()
    try:
        payload = decode_token(token)
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "token missing subject")
    return str(sub)


async def _resolve_personal_tenant_id(account_id: str) -> str | None:
    eng = _get_engine()
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT personal_tenant_id::text FROM accounts WHERE id = :a LIMIT 1"),
                {"a": account_id},
            )
        ).first()
    return str(row[0]) if row and row[0] else None


# ── Format → system prompt ────────────────────────────────────────────

# 2026-05-06 — 포맷별 출력 분기 제거. 단일 Markdown 출력. DOCX/PPTX/Excel 변환은
# 다음 페이즈에서 *첨부 참고* 용도로만 사용 (입력 ingest, 출력 변환 X).
_BASE_SYSTEM = (
    "당신은 한국어 문서 초안 작성자다. 사용자의 요청을 받아 *Markdown* 형식으로\n"
    "문서를 작성한다.\n"
    "- 제목은 # 한 줄, 섹션은 ## / ### 활용. 단락·글머리 기호·표를 가독성 위주로 구성.\n"
    "- 사용자가 톤·길이를 명시하지 않으면 비즈니스 격식 + A4 1~2 페이지 분량.\n"
    "- 한국어 존댓말 기본.\n"
    "- 코드 블록은 필요한 경우만, ```언어 표기.\n"
    "\n"
    "## 자료 우선 원칙 (P11-19z)\n"
    "사용자 메시지 앞에 *자동 수집된 참고 자료* (등록된 일정/메모/가계부/일기/지식\n"
    "문서 + 필요 시 웹 검색) 가 주입될 수 있다. 자료가 있으면:\n"
    "- 자료에 **있는 사실만** 본문 근거로 사용. 없는 수치·고유명사 추측 X.\n"
    "- 자료에 답이 충분하면 **사용자에게 추가 입력을 묻지 말고 바로 작성** —\n"
    "  '데이터를 입력해 주세요' 류 응답 X.\n"
    "- 자료가 부족한 부분만 명시 ('해당 정보 자료에 없음') 후 가능한 범위로 작성.\n"
    "- 작성 끝에 *참고 자료 출처* 섹션을 짧게 (어떤 카테고리에서 N건 참고했는지)."
)


def _system_prompt_for_format(fmt: str) -> str:
    """포맷 인자는 호환성 위해 받지만 출력은 단일 Markdown."""
    return _BASE_SYSTEM


# ── Streaming generator ───────────────────────────────────────────────


class DraftMessage(BaseModel):
    role: str  # user | assistant
    content: str


class DraftStreamRequest(BaseModel):
    format: str = "md"  # md | docx | pptx
    title: str | None = None
    history: list[DraftMessage] = []
    prompt: str  # 현재 사용자 발화


async def _stream_vllm(system: str, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
    """gemma-4-31b 직접 스트림. vllm chat/completions endpoint."""
    base = (
        getattr(settings, "VLLM_URL", None)
        or getattr(settings, "SLLM_GEMMA_URL", "http://vllm:8000/v1")
    )
    model = (
        getattr(settings, "VLLM_MODEL", None)
        or getattr(settings, "SLLM_GEMMA_MODEL", "gemma-4-31b")
    )
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "max_tokens": 4096,
        "temperature": 0.4,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", json=payload
        ) as r:
            if r.status_code >= 400:
                body = await r.aread()
                raise HTTPException(502, f"vllm error {r.status_code}: {body[:200]!r}")
            async for line in r.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[len("data: "):]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except Exception:  # noqa: BLE001
                        continue
                    delta = (
                        ((obj.get("choices") or [{}])[0])
                        .get("delta", {})
                        .get("content")
                    )
                    if delta:
                        yield delta


# ── 컨텍스트 수집 (등록 자료 + 웹 보강) ─────────────────────────────


_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    # 발화에 이 키워드들이 포함되면 해당 store 자동 pull.
    "schedule": ("일정", "스케줄", "약속", "회의", "미팅", "캘린더", "달력"),
    "memo": ("메모", "할 일", "할일", "todo", "마감", "보고서", "제출"),
    "expense": ("지출", "가계부", "비용", "예산", "결제", "송금"),
    "diary": ("일기", "회고", "기록", "느낀점", "감정"),
    "stock": ("주식", "종목", "포트폴리오", "수익률", "평단", "주가"),
    "doc": ("자료", "문서", "지식", "약관", "규정", "보고서", "논문", "정책"),
    "web": ("최근", "동향", "트렌드", "뉴스", "외부", "업계", "시장", "통계"),
}


def _domain_signals(prompt: str) -> dict[str, bool]:
    p = (prompt or "").lower()
    out: dict[str, bool] = {}
    for k, kws in _DOMAIN_KEYWORDS.items():
        out[k] = any(kw in p for kw in kws)
    # 기본 — 사용자가 "내", "등록된", "기반" 류면 모든 내부 자료 pull.
    if any(s in p for s in ("내 ", "등록", "기반", "참고", "있는", "보유")):
        for k in ("schedule", "memo", "expense", "diary", "doc"):
            out.setdefault(k, True)
            out[k] = True
    return out


async def _gather_context(
    *, account_id: str, prompt: str, max_chars: int = 8000
) -> tuple[str, list[dict[str, Any]]]:
    """등록된 자료 + 웹 검색을 자동 수집해 LLM 컨텍스트 텍스트로 조립.

    Returns: (context_text, sources_meta).
    sources_meta = [{kind, count, sample_titles?}, ...] — frontend 표시용.
    """
    from src.api.routers.schedule_v1 import _resolve_args as _resolve_account_args
    args = await _resolve_account_args(account_id)
    tenant_id = args.get("tenant_id")
    phone = args.get("phone")

    signals = _domain_signals(prompt)
    sources: list[dict[str, Any]] = []
    sections: list[str] = []
    accumulated = 0

    def _append(section_label: str, body: str) -> None:
        nonlocal accumulated
        if not body.strip():
            return
        block = f"\n## {section_label}\n{body}\n"
        if accumulated + len(block) > max_chars:
            block = block[: max(0, max_chars - accumulated)]
        sections.append(block)
        accumulated += len(block)

    # 1) schedule
    if signals.get("schedule"):
        try:
            from src.agent_framework.tools import schedule_store

            r = await schedule_store.list_all(args)
            items = (r.get("items") or [])[:30]
            if items:
                lines = []
                for it in items:
                    when = (it.get("when") or "")[:16]
                    title = it.get("title") or ""
                    where = it.get("where") or ""
                    who = it.get("who") or ""
                    parts = [when, title]
                    if where:
                        parts.append(f"@{where}")
                    if who:
                        parts.append(f"({who})")
                    lines.append("- " + " · ".join([p for p in parts if p]))
                _append("등록된 일정", "\n".join(lines))
                sources.append(
                    {"kind": "schedule", "count": len(r.get("items") or []), "shown": len(items)}
                )
        except Exception as e:  # noqa: BLE001
            log.debug("doc_draft_ctx_schedule_failed", error=str(e))

    # 2) memo
    if signals.get("memo"):
        try:
            from src.agent_framework.tools import memo_store

            r = await memo_store.list_all({**args, "status": "active"})
            items = (r.get("items") or [])[:20]
            if items:
                lines = []
                for it in items:
                    deadline = it.get("deadline_at") or "(마감 미정)"
                    lines.append(
                        f"- {it.get('title')} · 마감 {deadline}"
                        + (f" · {it.get('note')}" if it.get("note") else "")
                    )
                _append("진행 중 메모/할 일", "\n".join(lines))
                sources.append(
                    {"kind": "memo", "count": len(r.get("items") or []), "shown": len(items)}
                )
        except Exception as e:  # noqa: BLE001
            log.debug("doc_draft_ctx_memo_failed", error=str(e))

    # 3) expense
    if signals.get("expense"):
        try:
            from src.agent_framework.tools import expense_store

            r = await expense_store.list_all(args)
            items = (r.get("items") or [])[:30]
            if items:
                lines = []
                total = 0
                by_cat: dict[str, int] = {}
                for it in items:
                    body = it.get("body") if isinstance(it, dict) and "body" in it else it
                    amt = int(body.get("amount") or 0)
                    total += amt
                    cat = body.get("category") or "기타"
                    by_cat[cat] = by_cat.get(cat, 0) + amt
                    when = (body.get("spent_at") or "")[:10]
                    lines.append(
                        f"- {when} {cat} {amt:,}원"
                        + (f" · {body.get('description')}" if body.get("description") else "")
                    )
                _append(
                    "최근 지출",
                    "\n".join(lines)
                    + f"\n합계: {total:,}원"
                    + (
                        " · 카테고리별: "
                        + ", ".join(f"{k} {v:,}원" for k, v in sorted(by_cat.items(), key=lambda x: -x[1]))
                        if by_cat
                        else ""
                    ),
                )
                sources.append(
                    {"kind": "expense", "count": len(r.get("items") or []), "shown": len(items)}
                )
        except Exception as e:  # noqa: BLE001
            log.debug("doc_draft_ctx_expense_failed", error=str(e))

    # 4) diary (선택적)
    if signals.get("diary"):
        try:
            from src.agent_framework.tools import diary_store

            r = await diary_store.search({**args, "query": "", "top_k": 10})
            hits = (r.get("hits") or [])[:10]
            if hits:
                lines = []
                for h in hits:
                    body = h.get("body") if isinstance(h, dict) and "body" in h else h
                    lines.append(
                        f"- {body.get('date') or '?'} ({body.get('emotion') or '-'}): "
                        + (str(body.get('entry_text') or "")[:120])
                    )
                _append("최근 일기", "\n".join(lines))
                sources.append({"kind": "diary", "count": len(hits)})
        except Exception as e:  # noqa: BLE001
            log.debug("doc_draft_ctx_diary_failed", error=str(e))

    # 5) KMS docs — list + RAG 검색 (등록된 지식 자료)
    if signals.get("doc") and tenant_id:
        try:
            from src.agent_framework.tools import kms_inventory
            from sqlalchemy import create_engine

            sync_url = (
                settings.DATABASE_URL.replace("+asyncpg", "").replace(
                    "postgresql+asyncpg", "postgresql"
                )
            )
            eng = create_engine(sync_url)
            with eng.connect() as conn:
                docs = kms_inventory.list_documents(
                    db_conn=conn, personal_tenant_id=tenant_id, status="active", limit=15
                )
            eng.dispose()
            items = docs.get("items") or []
            if items:
                lines = [
                    f"- {it.get('title')} ({it.get('repository_name') or '?'}, {(it.get('updated_at') or '')[:10]})"
                    for it in items[:15]
                ]
                _append("등록된 지식 문서", "\n".join(lines))
                sources.append(
                    {"kind": "doc", "count": docs.get("total", len(items)), "shown": len(items[:15])}
                )
        except Exception as e:  # noqa: BLE001
            log.debug("doc_draft_ctx_doc_failed", error=str(e))

    # 6) 웹 검색 보강 — 키워드가 외부 정보 시그널을 포함하면.
    if signals.get("web"):
        try:
            from src.agent_framework.tools import web_search

            r = await web_search.search({"query": prompt, "top_k": 5})
            hits = (r.get("results") or r.get("hits") or [])[:5]
            if hits:
                lines = []
                for h in hits:
                    title = h.get("title") or h.get("name") or ""
                    snippet = (h.get("snippet") or h.get("description") or "")[:200]
                    url = h.get("url") or ""
                    lines.append(f"- {title} — {snippet} ({url})")
                _append("웹 검색 결과 (외부 보강)", "\n".join(lines))
                sources.append({"kind": "web", "count": len(hits)})
        except Exception as e:  # noqa: BLE001
            log.debug("doc_draft_ctx_web_failed", error=str(e))

    if not sections:
        return "", sources
    header = (
        "# 자동 수집된 참고 자료\n"
        "아래 자료는 사용자의 KMS 워크스페이스에 *실제 등록된* 데이터와 (필요 시) 웹\n"
        "검색 결과다. 문서 작성 시 이 자료를 *우선 근거*로 사용하고, 자료에 없는\n"
        "수치·고유명사는 추측하지 말 것. 사용자가 별도 입력 없이 자료 기반으로 바로\n"
        "초안을 만들 수 있도록 *되묻기 X*."
    )
    return header + "\n" + "\n".join(sections), sources


@router.post("/stream")
async def stream_draft(
    body: DraftStreamRequest,
    authorization: str = Header(...),
) -> StreamingResponse:
    """문서 초안 생성 SSE 스트림 — 등록 자료 + 웹 보강 컨텍스트 자동 주입.

    Returns: text/event-stream — 각 라인 ``data: {"token": "..."}\\n\\n``,
    컨텍스트 수집 직후 ``data: {"sources": [...]}`` 한 번 송출,
    종료 시 ``data: {"done": true}``.
    """
    aid = _account_id_from_bearer(authorization)
    system = _system_prompt_for_format(body.format)
    if body.title:
        system = f"{system}\n\n현재 작업 제목: {body.title}"

    history_msgs: list[dict[str, Any]] = []
    for h in body.history:
        if h.role in ("user", "assistant") and h.content.strip():
            history_msgs.append({"role": h.role, "content": h.content})

    async def _gen() -> AsyncIterator[bytes]:
        # 1) 컨텍스트 수집 (등록 자료 + 웹).
        context_text = ""
        sources: list[dict[str, Any]] = []
        try:
            context_text, sources = await _gather_context(
                account_id=aid, prompt=body.prompt
            )
        except Exception as e:  # noqa: BLE001
            log.warning("doc_draft_gather_context_failed", error=str(e))

        # 2) sources 이벤트 먼저 송출 — 프런트에서 "참고 자료 N건" 라벨로 표시.
        if sources:
            yield (
                f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
            ).encode("utf-8")

        # 3) user 메시지에 컨텍스트 prefix 후 LLM 호출.
        user_content = body.prompt
        if context_text:
            user_content = (
                f"{context_text}\n\n---\n\n## 사용자 요청\n{body.prompt}"
            )
        messages: list[dict[str, Any]] = [
            *history_msgs,
            {"role": "user", "content": user_content},
        ]

        try:
            async for tok in _stream_vllm(system, messages):
                yield (
                    f"data: {json.dumps({'token': tok}, ensure_ascii=False)}\n\n"
                ).encode("utf-8")
        except HTTPException as e:
            yield (
                f"data: {json.dumps({'error': str(e.detail)}, ensure_ascii=False)}\n\n"
            ).encode("utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("doc_draft_stream_failed", error=str(e))
            yield (
                f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            ).encode("utf-8")
        yield b"data: {\"done\": true}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Knowledge register (승인 → documents INSERT) ─────────────────────


class RegisterKnowledgeBody(BaseModel):
    title: str
    content: str
    format: str = "md"  # md | docx | pptx


class RegisterKnowledgeResult(BaseModel):
    document_id: str
    title: str
    status: str


@router.post("/register-knowledge", response_model=RegisterKnowledgeResult)
async def register_as_knowledge(
    body: RegisterKnowledgeBody,
    authorization: str = Header(...),
) -> RegisterKnowledgeResult:
    """문서 초안을 승인하여 documents 테이블에 active 로 등록.

    documents.processing_meta.body 에 정규화 본문 저장. 최소 schema 만 — 본격 검색
    인덱싱 (blocks/chunks/embedding) 은 별도 파이프라인 worker 가 status='active'
    감지 후 비동기 처리하도록 둔다.
    """
    aid = _account_id_from_bearer(authorization)
    tid = await _resolve_personal_tenant_id(aid)
    if not tid:
        raise HTTPException(400, "personal_tenant_id 가 설정되지 않았습니다")

    title = (body.title or "").strip() or "(제목 없음)"
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, "content 가 비어있습니다")

    fmt = body.format if body.format in ("md", "docx", "pptx") else "md"
    source_format = {"md": "md", "docx": "docx", "pptx": "pptx"}[fmt]

    eng = _get_engine()
    doc_id = uuid.uuid4()
    repo_id = await _get_or_create_drafts_repo(tid)

    meta = {
        "source_type": "doc_draft",
        "inbound": False,
        "content_length": len(content),
        "body": {
            "text": content,
            "format": fmt,
        },
        "title": title,
        "format": fmt,
        "generated_by": "gemma-4-31b",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    async with eng.begin() as conn:
        # repo 보장은 _get_or_create_drafts_repo 가 이미 처리.
        await conn.execute(
            text(
                """
                INSERT INTO documents
                  (id, tenant_id, repository_id, title, source_file, source_format,
                   processing_meta, status)
                VALUES
                  (:id, CAST(:tid AS uuid), CAST(:rid AS uuid), :title,
                   :sfile, :sformat, CAST(:meta AS jsonb), 'active')
                """
            ),
            {
                "id": doc_id,
                "tid": tid,
                "rid": repo_id,
                "title": title[:500],
                "sfile": f"draft/{doc_id.hex[:8]}.{fmt}",
                "sformat": source_format,
                "meta": json.dumps(meta, ensure_ascii=False),
            },
        )

    log.info(
        "doc_draft_registered_as_knowledge",
        document_id=str(doc_id),
        tenant_id=tid,
        title=title[:60],
        format=fmt,
    )
    return RegisterKnowledgeResult(
        document_id=str(doc_id),
        title=title,
        status="active",
    )


async def _get_or_create_drafts_repo(tenant_id: str) -> str:
    """문서 초안 전용 repository 보장. 없으면 생성."""
    eng = _get_engine()
    async with eng.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT id::text FROM repositories
                     WHERE tenant_id = CAST(:tid AS uuid)
                       AND name = '__doc_drafts__'
                     LIMIT 1
                    """
                ),
                {"tid": tenant_id},
            )
        ).first()
        if row:
            return str(row[0])
        new_id = uuid.uuid4()
        await conn.execute(
            text(
                """
                INSERT INTO repositories
                  (id, tenant_id, name, description, is_active, source_type)
                VALUES
                  (CAST(:id AS uuid), CAST(:tid AS uuid), '__doc_drafts__',
                   '문서생성 메뉴로 등록된 초안', true, 'manual')
                """
            ),
            {"id": str(new_id), "tid": tenant_id},
        )
    return str(new_id)
