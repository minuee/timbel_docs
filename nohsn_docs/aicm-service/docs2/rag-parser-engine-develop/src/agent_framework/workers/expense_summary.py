"""Expense summary feed worker — 매일 어제 지출 합계 1건.

PR P3 (KMS-Plus). 매일 오전 (cron ``5 7 * * *``) 어제 (사용자 tz 기준)
지출을 합산해 ``feed_events`` 1건 INSERT.

설계
----
- ``feed_cadence.expense_summary.enabled`` (default False — 명시적 opt-in).
- quiet_hours 안이면 skip (default 7:05 는 보통 quiet 끝난 직후).
- ``expenses`` (또는 ``expense_records``) 테이블에서 어제 row 합산.
  스키마 robust — 컬럼 자동 탐지 후 합산.
- 중복 방지: 같은 날 같은 kind row 가 이미 있으면 skip.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.agent_framework.scheduler.cron_runner import resolve_account_timezone
from src.agent_framework.scheduler.feed_quiet_hours import (
    cadence_enabled,
    in_quiet_hours,
)
from src.agent_framework.workers.feed_compose import (
    _get_engine,
    has_event_today,
    insert_feed_event,
    list_active_accounts,
)
from src.common.logging import get_logger

log = get_logger(__name__)


_KIND = "expense_summary"


async def _detect_expense_table(eng: AsyncEngine) -> dict[str, str] | None:
    """``expenses`` / ``expense_records`` 테이블 + 시각/금액 컬럼 탐지."""
    async with eng.connect() as conn:
        for table in ("expenses", "expense_records"):
            rows = (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        " WHERE table_name = :t"
                    ),
                    {"t": table},
                )
            ).all()
            cols = {r[0] for r in rows}
            if not cols:
                continue
            ts_col = None
            for c in ("spent_at", "occurred_at", "ts", "created_at", "date"):
                if c in cols:
                    ts_col = c
                    break
            amt_col = None
            for c in ("amount", "value", "total", "price"):
                if c in cols:
                    amt_col = c
                    break
            scope_col = None
            for c in ("account_id", "owner_id"):
                if c in cols:
                    scope_col = c
                    break
            if ts_col and amt_col and scope_col:
                return {
                    "table": table,
                    "ts": ts_col,
                    "amount": amt_col,
                    "scope": scope_col,
                }
    return None


async def _yesterday_total(
    eng: AsyncEngine,
    account_id: UUID | str,
    cols: dict[str, str],
    tz: str,
    now: datetime,
) -> tuple[float, int]:
    """어제 (사용자 tz) 지출 합계 + 건수."""
    try:
        from zoneinfo import ZoneInfo

        local = now.astimezone(ZoneInfo(tz))
    except Exception:
        local = now.astimezone(timezone.utc)
    today_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_local = today_local - timedelta(days=1)
    yesterday_utc = yesterday_local.astimezone(timezone.utc)
    today_utc = today_local.astimezone(timezone.utc)
    sql = (
        f"SELECT COALESCE(SUM({cols['amount']}), 0)::float, COUNT(*) "
        f"  FROM {cols['table']} "
        f" WHERE {cols['scope']} = :aid "
        f"   AND {cols['ts']} >= :s "
        f"   AND {cols['ts']} <  :e"
    )
    async with eng.connect() as conn:
        try:
            row = (
                await conn.execute(
                    text(sql),
                    {"aid": account_id, "s": yesterday_utc, "e": today_utc},
                )
            ).first()
        except Exception as e:  # noqa: BLE001
            log.warning("expense_summary_query_failed", error=str(e))
            return (0.0, 0)
    if row is None:
        return (0.0, 0)
    return (float(row[0] or 0), int(row[1] or 0))


def _build_body(total: float, count: int) -> tuple[str, str, list[dict[str, str]]]:
    title = f"어제 지출 {int(total):,}원 · {count}건"
    body = "어제 지출을 자세히 살펴보거나 카테고리별로 정리해보세요."
    pills = [
        {"label": "어제 지출 분석", "action_text": "어제 지출 분석해줘"},
        {"label": "이번 달 누적", "action_text": "이번 달 지출 누적 알려줘"},
    ]
    return title, body, pills


async def run_once(
    eng: AsyncEngine | None = None,
    now: datetime | None = None,
) -> int:
    """매일 1회 호출. 어제 지출 합산 → feed_event INSERT."""
    eng = eng or _get_engine()
    now = now or datetime.now(timezone.utc)
    cols = await _detect_expense_table(eng)
    if cols is None:
        return 0
    accounts = await list_active_accounts(eng)
    created = 0
    for acc in accounts:
        prefs = acc.get("preferences") or {}
        tprefs = acc.get("tenant_prefs") or {}
        # default False — 사용자가 명시적으로 enable 해야 발송.
        if not cadence_enabled(prefs, _KIND, default=False):
            continue
        tz = resolve_account_timezone(prefs, tprefs)
        if in_quiet_hours(prefs, now, tz):
            continue
        if await has_event_today(
            eng, acc["account_id"], acc["tenant_id"], _KIND, now, tz
        ):
            continue
        total, count = await _yesterday_total(
            eng, acc["account_id"], cols, tz, now
        )
        if count == 0:
            continue
        title, body, pills = _build_body(total, count)
        try:
            await insert_feed_event(
                eng,
                account_id=acc["account_id"],
                tenant_id=acc["tenant_id"],
                kind=_KIND,
                title=title,
                body=body,
                pills=pills,
                source={
                    "worker": "expense_summary",
                    "total": total,
                    "count": count,
                },
            )
            created += 1
        except Exception as e:  # noqa: BLE001
            log.warning(
                "expense_summary_insert_failed",
                account_id=str(acc.get("account_id")),
                error=str(e),
            )
    log.info("expense_summary_run_done", created=created)
    return created


async def expense_summary_daily() -> int:
    return await run_once()
