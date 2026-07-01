"""PR-Z15 — chat 의 "오늘 메일 정리해줘" 같은 inbox 조회 도구.

plan_orchestrator 가 이 도구를 호출 → email_processing_log 를 카테고리별
그룹으로 묶은 dict 반환. 결과의 ``_structured_card`` 필드는 engine 의
tool-only plan 분기가 SSE event=structured_block 으로 frontend 에 흘려
rich card UI 를 렌더하게 한다.

원칙:
- DB 쿼리는 inbox.py 의 ``GET /api/v1/inbox/summary`` 와 *동일 schema 결과*.
  따라서 frontend 는 chat 의 structured_block 과 inbox 페이지의 fetch 결과를
  같은 컴포넌트로 렌더 가능.
- LLM 위임 원칙 준수 — 카테고리 그룹핑은 mechanical (count/sort 만), 분류
  자체는 이미 email_classifier 가 LLM 으로 했음. 이 도구는 *집계 reader*.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.common.config import settings


_SHARED_ENGINE: AsyncEngine | None = None


def _get_shared_engine() -> AsyncEngine:
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        _SHARED_ENGINE = create_async_engine(settings.DATABASE_URL)
    return _SHARED_ENGINE


def _parse_dt(value: Any, *, fallback: datetime | None = None) -> datetime | None:
    """자연어 / ISO → datetime. 빈값/실패는 fallback. LLM 위임 원칙상
    이 변환은 plan_generator 가 ISO 로 주는 게 정상이고, 여기는 graceful 안전망.
    """
    if not value:
        return fallback
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return fallback
    # 자연어 일부 — plan_generator 가 ISO 로 주는 게 우선이지만 fallback 으로
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
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return fallback


async def summary(args: dict[str, Any]) -> dict[str, Any]:
    """email_processing_log 을 카테고리 그룹으로 집계.

    Args (engine 자동 주입 + LLM 명시):
    - account_id (engine 자동 주입 from sess.account_id) — 필수
    - since (ISO datetime str | "today" | "yesterday" | "이번주") — default = today 00:00 UTC
    - until (ISO datetime str | "now") — default = now
    - limit_per_category (int, default 5) — 그룹별 head N건

    반환:
    - period: {start, end}
    - total_count
    - by_category: list[{category, count, head_items, has_more}]
    - _structured_card: {type, data} — engine 이 SSE structured_block 으로 emit
    """
    account_id = args.get("account_id")
    if not account_id:
        return {
            "success": False,
            "error": "account_id required (engine 자동 주입 미설정 또는 비인증)",
            "_structured_card": None,
        }

    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    since_dt = _parse_dt(args.get("since"), fallback=today_start) or today_start
    until_dt = _parse_dt(args.get("until"), fallback=now_utc) or now_utc

    try:
        limit_per = int(args.get("limit_per_category") or 5)
    except (TypeError, ValueError):
        limit_per = 5
    limit_per = max(1, min(limit_per, 20))

    # P11-19 — 메일 계정 필터: mail_account_id (UUID) 또는 mail_account_label/
    # mail_account_query (사용자 발화의 부분 문자열 — label/username/host 부분 매칭).
    mail_account_id = args.get("mail_account_id")
    label_query = (
        args.get("mail_account_label")
        or args.get("mail_account_query")
        or args.get("account_filter")
    )
    eng = _get_shared_engine()

    if not mail_account_id and label_query:
        # 부분 매칭으로 label/username/host 검색 — 단일 매칭이면 즉시 적용.
        async with eng.connect() as conn:
            macc_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT id, label, username
                          FROM user_mail_accounts
                         WHERE account_id = cast(:aid as uuid)
                           AND (
                                LOWER(label) LIKE :q
                             OR LOWER(username) LIKE :q
                             OR LOWER(host) LIKE :q
                           )
                        """
                    ),
                    {
                        "aid": str(account_id),
                        "q": f"%{str(label_query).strip().lower()}%",
                    },
                )
            ).all()
        if len(macc_rows) == 1:
            mail_account_id = str(macc_rows[0].id)
        elif len(macc_rows) > 1:
            return {
                "success": False,
                "error": (
                    f"'{label_query}' 와 매칭되는 메일 계정이 {len(macc_rows)}건입니다. "
                    "더 구체적인 라벨/주소로 알려 주세요."
                ),
                "candidates": [
                    {"id": str(r.id), "label": r.label, "username": r.username}
                    for r in macc_rows
                ],
                "_structured_card": None,
            }
        # 0건이면 fallthrough — 전체 inbox 로 검색 (보수적).

    rows: list[dict[str, Any]] = []
    macc_clause = " AND mail_account_id = cast(:mid as uuid)" if mail_account_id else ""
    params: dict[str, Any] = {
        "aid": str(account_id),
        "since": since_dt,
        "until": until_dt,
    }
    if mail_account_id:
        params["mid"] = str(mail_account_id)
    async with eng.connect() as conn:
        result = await conn.execute(
            text(
                f"""
                SELECT
                    id,
                    document_id,
                    mail_account_id,
                    from_address,
                    from_domain,
                    subject,
                    received_at,
                    processed_at,
                    classification,
                    trust_score,
                    actions_taken
                FROM email_processing_log
                WHERE account_id = cast(:aid as uuid)
                  AND processed_at BETWEEN :since AND :until
                  {macc_clause}
                ORDER BY processed_at DESC
                LIMIT 500
                """
            ),
            params,
        )
        for r in result.mappings():
            rows.append(dict(r))

    # 카테고리별 그룹핑 (mechanical — LLM 분류 결과 카운트만).
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        cls = r.get("classification") or {}
        cat = str(cls.get("category") or "uncertain")
        ee = cls.get("extracted_entities") or {}
        item = {
            "log_id": str(r["id"]),
            "document_id": str(r["document_id"]) if r.get("document_id") else None,
            "from_address": r.get("from_address"),
            "from_domain": r.get("from_domain"),
            "subject": r.get("subject"),
            "received_at": r["received_at"].isoformat() if r.get("received_at") else None,
            "processed_at": r["processed_at"].isoformat() if r.get("processed_at") else None,
            "trust_score": float(r["trust_score"]) if r.get("trust_score") is not None else None,
            "priority": str(cls.get("priority") or "normal"),
            "needs_user_attention": bool(cls.get("needs_user_attention", False)),
            "subject_summary": str(ee.get("subject_summary") or "") or None,
            "extracted_datetime": str(ee.get("datetime_iso") or "") or None,
            "extracted_location": str(ee.get("location") or "") or None,
            "action_count": len(r.get("actions_taken") or []),
        }
        groups.setdefault(cat, []).append(item)

    # 카테고리별 count desc 정렬, head N건 + has_more
    by_category: list[dict[str, Any]] = []
    for cat, items in groups.items():
        by_category.append(
            {
                "category": cat,
                "count": len(items),
                "head_items": items[:limit_per],
                "has_more": len(items) > limit_per,
            }
        )
    by_category.sort(key=lambda g: -g["count"])

    period = {
        "start": since_dt.isoformat(),
        "end": until_dt.isoformat(),
    }

    # 사용자 텍스트 응답 (LLM 합성 시 활용)
    if not rows:
        summary_text = (
            f"기간 {period['start'][:10]} ~ {period['end'][:10]} 처리된 메일 0건."
        )
    else:
        cat_summary = ", ".join(
            f"{g['category']} {g['count']}" for g in by_category[:5]
        )
        summary_text = (
            f"기간 {period['start'][:10]} ~ {period['end'][:10]} "
            f"총 {len(rows)}건 — {cat_summary}"
        )

    return {
        "success": True,
        "period": period,
        "total_count": len(rows),
        "by_category": by_category,
        "summary": summary_text,
        # 2026-05-06 — _structured_card 제거. frontend KIND_RENDERERS 에
        # email_summary 매핑 없어 '지원하지 않는 블록' 표시되던 문제.
    }
