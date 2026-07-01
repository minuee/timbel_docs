"""Conflict check registry + 4 표준 checker — Phase 1.5A Task 4.

write 도구의 *추가* 방어 layer. tool 호출 직전 (Task 8 hook) 실행.
tier/scope 검사 통과 후, side-effect 직전. 충돌 시
``ToolResult.meta.outcome = CONFLICT/DUPLICATE/COOLDOWN`` + ``alternatives``
에 대안을 채워 페르소나 LLM 이 사용자에게 어떻게 안내할지 결정하게 함.

ORM 모델 (Schedule / Expense / Memo) 이 아직 별도로 분리돼 있지 않은 단계
이므로, 모두 ``documents`` 테이블 (JSONB ``payload``) 위로 raw SQL 작성.
실제 데이터 매핑은 store layer 와 동일한 ``kind`` / ``created_by`` /
``payload->>start_at`` 등을 사용.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent_framework.runtime.sender_context import SenderContext
from src.agent_framework.tools.outcomes import ToolOutcome


@dataclass
class ConflictResult:
    has_conflict: bool
    outcome: ToolOutcome
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)
    alternatives: list[Any] = field(default_factory=list)


class ConflictCheck(Protocol):
    name: str

    async def check(
        self,
        tool: str,
        args: dict,
        sender: SenderContext,
        db: AsyncSession,
        **extra: Any,
    ) -> ConflictResult: ...


_REGISTRY: dict[str, ConflictCheck] = {}


def register(name: str, check: ConflictCheck) -> None:
    _REGISTRY[name] = check


def get(name: str) -> ConflictCheck | None:
    return _REGISTRY.get(name)


def _coerce_dt(v: Any) -> datetime | None:
    """datetime 또는 ISO-8601 문자열 → tz-aware datetime (UTC fallback)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


# ── 1. schedule_overlap ────────────────────────────────────────────
class ScheduleOverlapCheck:
    """동일 사용자의 active 일정과 시간 overlap 검사.

    documents 테이블 ``kind='agent_schedule'`` 위에서 작동. payload 내
    ``start_at`` / ``end_at`` / ``is_active`` 를 JSONB 추출.
    """

    name = "schedule_overlap"

    async def check(
        self,
        tool: str,
        args: dict,
        sender: SenderContext,
        db: AsyncSession,
        **extra: Any,
    ) -> ConflictResult:
        start = _coerce_dt(args.get("start_at"))
        end = _coerce_dt(args.get("end_at"))
        if start is None or end is None:
            return ConflictResult(False, ToolOutcome.OK, "")

        stmt = text(
            """
            SELECT id, payload->>'title' AS title,
                   payload->>'start_at' AS start_at,
                   payload->>'end_at'   AS end_at
              FROM documents
             WHERE tenant_id = :tenant_id
               AND created_by = :user_id
               AND kind = 'agent_schedule'
               AND COALESCE((payload->>'is_active')::boolean, TRUE) = TRUE
               AND (payload->>'start_at')::timestamptz < :end_at
               AND (payload->>'end_at')::timestamptz   > :start_at
            """
        )
        params = {
            "tenant_id": str(sender.tenant_id) if sender.tenant_id else None,
            "user_id": str(sender.internal_user_id)
            if sender.internal_user_id
            else None,
            "start_at": start,
            "end_at": end,
        }
        rows = (await db.execute(stmt, params)).all()
        if not rows:
            return ConflictResult(False, ToolOutcome.OK, "")
        return ConflictResult(
            has_conflict=True,
            outcome=ToolOutcome.CONFLICT,
            reason="schedule_overlap",
            detail={"existing_count": len(rows)},
            alternatives=[],  # caller 가 suggest_slots 도구로 후속 호출
        )


schedule_overlap_check = ScheduleOverlapCheck()
register("schedule_overlap", schedule_overlap_check)


# ── 2. mail_recent_duplicate ────────────────────────────────────────
class MailRecentDuplicateCheck:
    """Redis 캐시 기반 — 60s 내 동일 sender×recipient×subject 차단.

    redis 는 ``extra['redis']`` 로 주입. 미가용 / 예외 시 best-effort
    silent pass (block 하지 않음).
    """

    name = "mail_recent_duplicate"
    COOLDOWN_SECONDS = 60

    async def check(
        self,
        tool: str,
        args: dict,
        sender: SenderContext,
        db: AsyncSession,
        **extra: Any,
    ) -> ConflictResult:
        redis = extra.get("redis")
        if redis is None:
            return ConflictResult(False, ToolOutcome.OK, "")

        recipients = args.get("to") or []
        subject = args.get("subject") or ""
        if not recipients:
            return ConflictResult(False, ToolOutcome.OK, "")

        subj_hash = hashlib.md5(subject.encode()).hexdigest()
        for rcpt in recipients:
            key = (
                f"mail_dedup:{sender.tenant_id}:{sender.internal_user_id}"
                f":{rcpt}:{subj_hash}"
            )
            try:
                exists = await redis.exists(key)
            except Exception:
                continue
            if exists:
                return ConflictResult(
                    has_conflict=True,
                    outcome=ToolOutcome.COOLDOWN,
                    reason="mail_recent_duplicate",
                    detail={
                        "recipient": rcpt,
                        "cooldown_s": self.COOLDOWN_SECONDS,
                    },
                )
        return ConflictResult(False, ToolOutcome.OK, "")


mail_recent_duplicate_check = MailRecentDuplicateCheck()
register("mail_recent_duplicate", mail_recent_duplicate_check)


# ── 3. expense_recent_duplicate ─────────────────────────────────────
class ExpenseRecentDuplicateCheck:
    """동일 사용자×금액×카테고리, ``spent_at`` ±5 분 윈도우 내 중복 차단."""

    name = "expense_recent_duplicate"
    WINDOW_MINUTES = 5

    async def check(
        self,
        tool: str,
        args: dict,
        sender: SenderContext,
        db: AsyncSession,
        **extra: Any,
    ) -> ConflictResult:
        amount = args.get("amount")
        category = args.get("category")
        spent_at = _coerce_dt(args.get("spent_at"))
        if amount is None or category is None or spent_at is None:
            return ConflictResult(False, ToolOutcome.OK, "")

        window_start = spent_at - timedelta(minutes=self.WINDOW_MINUTES)
        window_end = spent_at + timedelta(minutes=self.WINDOW_MINUTES)

        stmt = text(
            """
            SELECT id
              FROM documents
             WHERE tenant_id = :tenant_id
               AND created_by = :user_id
               AND kind = 'agent_expense'
               AND (payload->>'amount')::numeric = :amount
               AND payload->>'category' = :category
               AND (payload->>'spent_at')::timestamptz BETWEEN :w_start AND :w_end
            """
        )
        params = {
            "tenant_id": str(sender.tenant_id) if sender.tenant_id else None,
            "user_id": str(sender.internal_user_id)
            if sender.internal_user_id
            else None,
            "amount": amount,
            "category": category,
            "w_start": window_start,
            "w_end": window_end,
        }
        rows = (await db.execute(stmt, params)).all()
        if rows:
            return ConflictResult(
                has_conflict=True,
                outcome=ToolOutcome.DUPLICATE,
                reason="expense_recent_duplicate",
                detail={"count": len(rows)},
            )
        return ConflictResult(False, ToolOutcome.OK, "")


expense_recent_duplicate_check = ExpenseRecentDuplicateCheck()
register("expense_recent_duplicate", expense_recent_duplicate_check)


# ── 4. memo_recent_duplicate ────────────────────────────────────────
class MemoRecentDuplicateCheck:
    """동일 사용자가 60 초 내 동일 본문 (sha256) 메모 재등록 차단.

    ``body_hash`` 컬럼은 Task 6 마이그레이션 056 에서 추가 — 본 단계에서는
    SQL 내 ``payload->>'body_hash'`` 로 라우팅 (mock 테스트는 모두 통과,
    실 DB 연동은 Task 6 이후 활성화).
    """

    name = "memo_recent_duplicate"
    WINDOW_SECONDS = 60

    async def check(
        self,
        tool: str,
        args: dict,
        sender: SenderContext,
        db: AsyncSession,
        **extra: Any,
    ) -> ConflictResult:
        content = args.get("content") or ""
        if not content.strip():
            return ConflictResult(False, ToolOutcome.OK, "")

        body_hash = hashlib.sha256(content.strip().encode()).hexdigest()
        window_start = datetime.now(timezone.utc) - timedelta(
            seconds=self.WINDOW_SECONDS
        )

        stmt = text(
            """
            SELECT id
              FROM documents
             WHERE tenant_id = :tenant_id
               AND created_by = :user_id
               AND kind = 'agent_memo'
               AND payload->>'body_hash' = :body_hash
               AND created_at >= :window_start
            """
        )
        params = {
            "tenant_id": str(sender.tenant_id) if sender.tenant_id else None,
            "user_id": str(sender.internal_user_id)
            if sender.internal_user_id
            else None,
            "body_hash": body_hash,
            "window_start": window_start,
        }
        rows = (await db.execute(stmt, params)).all()
        if rows:
            return ConflictResult(
                has_conflict=True,
                outcome=ToolOutcome.DUPLICATE,
                reason="memo_recent_duplicate",
                detail={"count": len(rows)},
            )
        return ConflictResult(False, ToolOutcome.OK, "")


memo_recent_duplicate_check = MemoRecentDuplicateCheck()
register("memo_recent_duplicate", memo_recent_duplicate_check)
