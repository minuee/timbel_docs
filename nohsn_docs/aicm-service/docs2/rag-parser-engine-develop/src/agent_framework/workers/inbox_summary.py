"""Inbox summary feed worker — 메일 신착 알림용 ``feed_events`` writer.

PR P3 (KMS-Plus). 두 모드를 지원:
1. **realtime**: inbox webhook (메일 신착) 시 호출. 1통씩 신착 메시지에 대한
   feed_event 1건 INSERT. ``feed_cadence.inbox_summary.realtime`` 가 True 일 때만.
2. **daily fallback**: realtime 가 비활성이거나 webhook 미가용일 때
   ``run_daily_summary`` 가 어제 받은 메일을 합산해 1건 작성.

설계
----
- 본 worker 는 LLM 호출하지 않음. 본문은 단순 metadata 요약 (보낸이/제목).
  "요약 보기" pill 클릭 → chat 진입해 LLM 이 실제 요약 생성.
- ``feed_cadence.inbox_summary.enabled=False`` 면 두 모드 모두 skip.
- quiet_hours 안이면 realtime 라도 skip (사용자 휴식 시간 보호).
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
    cadence_param,
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


_KIND = "inbox_summary"


def _build_realtime_body(message: dict[str, Any]) -> tuple[str, str, list[dict[str, str]]]:
    """1 통 신착 알림 본문."""
    sender = str(message.get("sender") or message.get("from") or "(보낸이 미상)")
    subj = str(message.get("subject") or "(제목 없음)")
    title = f"새 메일 · {sender}"
    body = subj[:200]
    pills = [
        {"label": "요약 보기", "action_text": f"이 메일 요약해줘: {subj}"},
        {"label": "받은편지함", "action_text": "받은편지함 열어줘"},
    ]
    return title, body, pills


def _build_daily_body(count: int) -> tuple[str, str, list[dict[str, str]]]:
    title = f"어제 받은 메일 {count}통"
    body = "어제 받은 메일을 한 번에 살펴보시려면 아래 요약 버튼을 눌러주세요."
    pills = [
        {"label": "어제 메일 요약", "action_text": "어제 받은 메일 요약해줘"},
        {"label": "받은편지함", "action_text": "받은편지함 열어줘"},
    ]
    return title, body, pills


async def emit_realtime(
    eng: AsyncEngine | None,
    account_id: UUID | str,
    tenant_id: UUID | str,
    message: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str | None:
    """메일 신착 1건 → feed_event 1건 INSERT. 사용자 cadence/quiet_hours 검사."""
    eng = eng or _get_engine()
    now = now or datetime.now(timezone.utc)
    # 사용자 prefs 조회 (한 row 만 — 패턴 stock_monitor 와 비슷).
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT a.preferences, t.config "
                    "  FROM accounts a "
                    "  LEFT JOIN tenants t ON t.id = a.personal_tenant_id "
                    " WHERE a.id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
    if row is None:
        return None
    prefs = row[0] if isinstance(row[0], dict) else {}
    tprefs = row[1] if isinstance(row[1], dict) else {}
    if not cadence_enabled(prefs, _KIND, default=True):
        return None
    if not bool(cadence_param(prefs, _KIND, "realtime", default=True)):
        return None
    tz = resolve_account_timezone(prefs, tprefs)
    if in_quiet_hours(prefs, now, tz):
        return None
    title, body, pills = _build_realtime_body(message)
    return await insert_feed_event(
        eng,
        account_id=account_id,
        tenant_id=tenant_id,
        kind=_KIND,
        title=title,
        body=body,
        pills=pills,
        source={
            "worker": "inbox_summary",
            "mode": "realtime",
            "message_id": str(message.get("id") or ""),
        },
    )


async def _count_yesterday_for_account(
    eng: AsyncEngine, account_id: UUID | str, tz: str, now: datetime
) -> int:
    """``inbox_messages`` 테이블에서 어제 (사용자 tz) 받은 메일 수."""
    try:
        from zoneinfo import ZoneInfo

        local = now.astimezone(ZoneInfo(tz))
    except Exception:
        local = now.astimezone(timezone.utc)
    today_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_local = today_local - timedelta(days=1)
    yesterday_utc = yesterday_local.astimezone(timezone.utc)
    today_utc = today_local.astimezone(timezone.utc)
    async with eng.connect() as conn:
        # inbox_messages 테이블이 존재하는지부터 확인 — 없으면 0 반환 (graceful).
        try:
            row = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM inbox_messages "
                        " WHERE account_id = :aid "
                        "   AND received_at >= :s "
                        "   AND received_at <  :e"
                    ),
                    {"aid": account_id, "s": yesterday_utc, "e": today_utc},
                )
            ).first()
            return int(row[0]) if row else 0
        except Exception:
            return 0


async def run_daily_summary(
    eng: AsyncEngine | None = None,
    now: datetime | None = None,
) -> int:
    """daily fallback. realtime 미사용 사용자에 대해 어제 메일 합산 1건.

    realtime 활성 사용자도 daily 합산을 받고 싶을 수 있으니 cadence_param
    ``daily`` (default False) 로 명시적 opt-in 시 추가 INSERT.
    """
    eng = eng or _get_engine()
    now = now or datetime.now(timezone.utc)
    created = 0
    for acc in await list_active_accounts(eng):
        prefs = acc.get("preferences") or {}
        tprefs = acc.get("tenant_prefs") or {}
        if not cadence_enabled(prefs, _KIND, default=True):
            continue
        realtime_on = bool(cadence_param(prefs, _KIND, "realtime", default=True))
        daily_on = bool(cadence_param(prefs, _KIND, "daily", default=False))
        if realtime_on and not daily_on:
            continue
        tz = resolve_account_timezone(prefs, tprefs)
        if in_quiet_hours(prefs, now, tz):
            continue
        # 같은 날 daily summary 중복 방지.
        kind_daily = f"{_KIND}.daily"
        if await has_event_today(
            eng,
            acc["account_id"],
            acc["tenant_id"],
            kind_daily,
            now,
            tz,
        ):
            continue
        count = await _count_yesterday_for_account(
            eng, acc["account_id"], tz, now
        )
        if count == 0:
            continue
        title, body, pills = _build_daily_body(count)
        try:
            await insert_feed_event(
                eng,
                account_id=acc["account_id"],
                tenant_id=acc["tenant_id"],
                kind=kind_daily,
                title=title,
                body=body,
                pills=pills,
                source={"worker": "inbox_summary", "mode": "daily", "count": count},
            )
            created += 1
        except Exception as e:  # noqa: BLE001
            log.warning(
                "inbox_summary_daily_failed",
                account_id=str(acc.get("account_id")),
                error=str(e),
            )
    log.info("inbox_summary_daily_done", created=created)
    return created


async def daily_inbox_summary() -> int:
    return await run_daily_summary()
