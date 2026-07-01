"""mail.search — 메일 검색 도구.

발신자 / 제목 키워드 / 첨부 여부 / 기간 / 메일 계정 필터로 email_processing_log
검색. inbox.summary 와 schema 호환 — frontend 가 동일 카드 컴포넌트로 렌더.

Args (engine 자동 주입 + LLM 명시):
- account_id: 사용자 account.id (engine 자동)
- query (str): 제목 + 분류 entity 부분 매칭 (ILIKE %q%)
- sender / from (str): 발신자 이름 또는 이메일 부분 매칭
- has_attachment (bool): 첨부 있는 메일만
- since / until (ISO datetime str | 자연어): 기간
- mail_account_id (UUID) 또는 mail_account_label (부분 매칭): 계정 필터
- limit (int, default 30, max 200)

반환: {success, total_count, items, summary}
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.config import settings
from src.common.logging import get_logger


log = get_logger(__name__)
_ENG: AsyncEngine | None = None


def _eng() -> AsyncEngine:
    global _ENG
    if _ENG is None:
        _ENG = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _ENG


def _parse_dt(value: Any, fallback: datetime | None = None) -> datetime | None:
    if not value:
        return fallback
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return fallback
    today_utc = datetime.now(timezone.utc)
    today_start = today_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    if s in ("today", "오늘"):
        return today_start
    if s in ("yesterday", "어제"):
        return today_start - timedelta(days=1)
    if s == "이번주":
        return today_start - timedelta(days=today_utc.weekday())
    if s in ("now", "지금"):
        return today_utc
    if s == "최근 7일" or s == "최근7일":
        return today_utc - timedelta(days=7)
    if s == "최근 30일" or s == "최근30일":
        return today_utc - timedelta(days=30)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return fallback


async def search(args: dict[str, Any]) -> dict[str, Any]:
    account_id = args.get("account_id")
    if not account_id:
        return {"success": False, "error": "account_id required (engine 자동 주입 미설정)"}

    query = (args.get("query") or "").strip()
    sender = (args.get("sender") or args.get("from") or "").strip()
    has_attachment_raw = args.get("has_attachment")
    has_attachment = (
        bool(has_attachment_raw)
        if isinstance(has_attachment_raw, bool)
        else (str(has_attachment_raw).lower() in ("true", "1", "yes"))
        if has_attachment_raw is not None
        else None
    )

    until_dt = _parse_dt(args.get("until"), fallback=datetime.now(timezone.utc))
    # 기본 검색 기간 — 최근 90일 (조회 도구라 넉넉히)
    since_dt = _parse_dt(
        args.get("since"),
        fallback=(until_dt or datetime.now(timezone.utc)) - timedelta(days=90),
    )

    try:
        limit = int(args.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 200))

    # 계정 필터
    mail_account_id = args.get("mail_account_id")
    label_query = (
        args.get("mail_account_label")
        or args.get("mail_account_query")
        or args.get("account_filter")
    )
    eng = _eng()
    if not mail_account_id and label_query:
        async with eng.connect() as conn:
            macc = (
                await conn.execute(
                    text(
                        """
                        SELECT id FROM user_mail_accounts
                         WHERE account_id = cast(:aid as uuid)
                           AND (
                                LOWER(label) LIKE :q
                             OR LOWER(username) LIKE :q
                             OR LOWER(host) LIKE :q
                           )
                         LIMIT 2
                        """
                    ),
                    {
                        "aid": str(account_id),
                        "q": f"%{str(label_query).strip().lower()}%",
                    },
                )
            ).all()
        if len(macc) == 1:
            mail_account_id = str(macc[0].id)

    where_parts = [
        "account_id = cast(:aid as uuid)",
        "processed_at BETWEEN :since AND :until",
    ]
    params: dict[str, Any] = {
        "aid": str(account_id),
        "since": since_dt,
        "until": until_dt,
        "lim": limit,
    }
    if mail_account_id:
        where_parts.append("mail_account_id = cast(:mid as uuid)")
        params["mid"] = str(mail_account_id)

    if query:
        where_parts.append(
            "(LOWER(subject) LIKE :q OR LOWER(classification::text) LIKE :q)"
        )
        params["q"] = f"%{query.lower()}%"

    if sender:
        # 발신자 — from_address 또는 분류 결과의 sender_name 부분 매칭.
        where_parts.append(
            "(LOWER(from_address) LIKE :sndr "
            "OR LOWER(coalesce(classification ->> 'sender_name', '')) LIKE :sndr "
            "OR LOWER(coalesce(classification ->> 'from_name', '')) LIKE :sndr)"
        )
        params["sndr"] = f"%{sender.lower()}%"

    if has_attachment is True:
        # documents.processing_meta.attachments_meta 길이 > 0
        where_parts.append(
            "EXISTS (SELECT 1 FROM documents d WHERE d.id = email_processing_log.document_id "
            "AND COALESCE(jsonb_array_length(d.processing_meta -> 'attachments_meta'), 0) > 0)"
        )

    where_sql = " AND ".join(where_parts)
    sql = f"""
        SELECT id, document_id, mail_account_id, from_address, from_domain,
               subject, received_at, processed_at, classification, trust_score
          FROM email_processing_log
         WHERE {where_sql}
         ORDER BY processed_at DESC
         LIMIT :lim
    """

    async with eng.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()

    # 검색 결과 ≤ 3건이면 본문까지 포함 — 사용자가 "상세 보여줘" 류 시 한 번에.
    # 4건 이상은 메타만 (본문은 한 건 클릭 시 별도 조회).
    include_body = len(rows) <= 3 or args.get("include_body") is True

    body_map: dict[str, dict[str, Any]] = {}
    if include_body:
        doc_ids = [str(r.document_id) for r in rows if r.document_id]
        if doc_ids:
            async with eng.connect() as conn:
                body_rows = (
                    await conn.execute(
                        text(
                            """
                            SELECT id::text AS doc_id,
                                   processing_meta->'body'->>'text' AS body_text,
                                   processing_meta->'body'->>'html' AS body_html
                              FROM documents
                             WHERE id = ANY(CAST(:dids AS uuid[]))
                            """
                        ),
                        {"dids": doc_ids},
                    )
                ).all()
            for br in body_rows:
                body_map[br.doc_id] = {
                    "body_text": (br.body_text or "")[:4000],
                    "body_html": (br.body_html or "")[:6000] if br.body_html else None,
                }

    items: list[dict[str, Any]] = []
    for r in rows:
        cls = r.classification or {}
        item = {
            "log_id": str(r.id),
            "document_id": str(r.document_id) if r.document_id else None,
            "mail_account_id": str(r.mail_account_id) if r.mail_account_id else None,
            "from_address": r.from_address,
            "from_domain": r.from_domain,
            "subject": r.subject,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "processed_at": r.processed_at.isoformat() if r.processed_at else None,
            "trust_score": float(r.trust_score) if r.trust_score is not None else None,
            "category": str(cls.get("category") or "uncertain"),
            "priority": str(cls.get("priority") or "normal"),
            "subject_summary": cls.get("extracted_entities", {}).get("subject_summary")
            if isinstance(cls.get("extracted_entities"), dict)
            else None,
        }
        if r.document_id and str(r.document_id) in body_map:
            b = body_map[str(r.document_id)]
            item["body_text"] = b.get("body_text")
            # html 은 길이 큼 — text 가 있으면 LLM 한테 text 우선 노출.
            if not b.get("body_text") and b.get("body_html"):
                item["body_html"] = b.get("body_html")
        items.append(item)

    if not items:
        echo_parts = []
        if query:
            echo_parts.append(f"키워드 '{query}'")
        if sender:
            echo_parts.append(f"발신자 '{sender}'")
        if has_attachment:
            echo_parts.append("첨부 있음")
        if mail_account_id:
            echo_parts.append("계정 필터")
        cond = ", ".join(echo_parts) or "조건"
        summary_text = f"{cond} 에 해당하는 메일을 찾지 못했습니다."
    else:
        # 검색 결과 전체를 본문 LLM 이 list 하도록 summary 에 미리 한 줄씩 정리.
        # compose LLM 이 'items' 안 보고 summary 를 본문 그대로 쓸 수도 있어 안전.
        bullet_lines = []
        for it in items[:30]:
            received = (it.get("received_at") or it.get("processed_at") or "")[:10]
            from_addr = it.get("from_address") or "?"
            subject = it.get("subject") or "(제목 없음)"
            line = f"- {received} · {from_addr} · {subject}"
            # 본문이 포함됐으면 (≤3 결과) summary 에도 짧은 본문 prefix.
            if include_body and it.get("body_text"):
                preview = it["body_text"].replace("\n", " ")[:200]
                line += f"\n  본문: {preview}…"
            bullet_lines.append(line)
        summary_text = (
            f"검색 결과 {len(items)}건"
            + (f" (발신자 '{sender}')" if sender else "")
            + (f" (키워드 '{query}')" if query else "")
            + ":\n"
            + "\n".join(bullet_lines)
        )

    return {
        "success": True,
        "total_count": len(items),
        "items": items,
        "include_body": include_body,
        # P11-19 — 전체 항목을 본문에 명시. 답변 LLM 이 *모든* item 을 본문에 list.
        "render_instruction": (
            f"items 배열의 모든 {len(items)}건을 본문에 한 줄씩 나열할 것. "
            "1건만 보여주고 '총 N건' 만 적는 응답 금지."
            + (
                " items[*].body_text 가 있으면 *전체 본문* 을 답변에 포함 — "
                "사용자가 '상세 내용' 을 요청한 것이므로 메타데이터 + 본문 둘 다 노출."
                if include_body
                else ""
            )
        ),
        "summary": summary_text,
    }
