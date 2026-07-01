"""Schedule alert worker — 다음 1시간 안에 일정이 있으면 ``feed_events`` INSERT.

PR P3 (KMS-Plus). 매시 정시(``0 * * * *``)에 깨어 각 사용자의 일정을 확인.

설계
----
- ``schedules`` 테이블에서 ``account_id`` 별 ``starts_at`` (또는 ``when_at``)
  이 (now, now + 60min] 인 row 를 찾음.
- 일정 1건당 feed_event 1건. 같은 schedule 에 대한 중복 알림 방지를 위해
  ``source.schedule_id`` 로 dedupe.
- ``feed_cadence.schedule_alert.enabled=False`` → skip.
- quiet_hours 안이면 skip.

스키마 robust
-------------
프로젝트 내에 ``schedules`` 테이블 컬럼명이 ``starts_at`` / ``start_at`` /
``when_at`` 등으로 변형될 수 있어, 존재하는 컬럼만 robust 하게 사용.
information_schema 로 컬럼 자동 탐지.
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
    insert_feed_event,
    list_active_accounts,
)
from src.common.logging import get_logger

log = get_logger(__name__)


_KIND = "schedule_alert"


async def _detect_schedule_columns(eng: AsyncEngine) -> dict[str, str] | None:
    """``schedules`` 테이블 존재 여부 + 시간/제목 컬럼 탐지. 없으면 None.

    D29 §4 (#161, 2026-05-08) — ``owner_agent_id`` 컬럼 존재 여부도 탐지.
    있으면 ``feed_events.source.owner_agent_id`` 로 forward (admin global
    view 에서 alert 의 출처 agent 추적 가능).
    """
    async with eng.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    " WHERE table_name = 'schedules' "
                    "   AND table_schema = current_schema()"
                )
            )
        ).all()
    cols = {r[0] for r in rows}
    if not cols:
        return None
    # 시각 컬럼 우선순위
    when_col = None
    for c in ("starts_at", "start_at", "when_at", "scheduled_at", "occurs_at"):
        if c in cols:
            when_col = c
            break
    if when_col is None:
        return None
    title_col = None
    for c in ("title", "summary", "name", "description"):
        if c in cols:
            title_col = c
            break
    title_col = title_col or "id"
    out: dict[str, str] = {"when": when_col, "title": title_col}
    if "account_id" in cols:
        out["scope_col"] = "account_id"
    elif "owner_id" in cols:
        out["scope_col"] = "owner_id"
    else:
        return None
    # D29 §4 — owner_agent_id 컬럼 (D23 격리 정책) 탐지. 없으면 forward 안 함.
    if "owner_agent_id" in cols:
        out["owner_agent_col"] = "owner_agent_id"
    return out


async def _list_upcoming_for_account(
    eng: AsyncEngine,
    account_id: UUID | str,
    cols: dict[str, str],
    horizon_start: datetime,
    horizon_end: datetime,
) -> list[dict[str, Any]]:
    """다음 horizon (now, now+60min] 에 시작하는 일정 list.

    D29 §4 (#161, 2026-05-08) — ``owner_agent_col`` 이 cols 에 있으면 SELECT 에
    포함하여 schedule.owner_agent_id 를 inherit. 없으면 None (회귀 0).
    """
    has_owner_col = "owner_agent_col" in cols
    select_owner = (
        f", {cols['owner_agent_col']} AS owner_agent_id" if has_owner_col else ""
    )
    sql = (
        f"SELECT id, {cols['title']} AS title, {cols['when']} AS when_ts"
        + select_owner
        + " FROM schedules "
        f" WHERE {cols['scope_col']} = :aid "
        f"   AND {cols['when']} > :s "
        f"   AND {cols['when']} <= :e "
        f" ORDER BY {cols['when']} ASC"
    )
    async with eng.connect() as conn:
        try:
            rows = (
                await conn.execute(
                    text(sql),
                    {"aid": account_id, "s": horizon_start, "e": horizon_end},
                )
            ).all()
        except Exception as e:  # noqa: BLE001
            log.warning("schedule_alert_query_failed", error=str(e))
            return []
    out: list[dict[str, Any]] = []
    for r in rows:
        item: dict[str, Any] = {
            "id": str(r[0]),
            "title": str(r[1] or "(제목 없음)"),
            "when": r[2],
        }
        if has_owner_col and len(r) > 3:
            owner_aid = r[3]
            item["owner_agent_id"] = str(owner_aid) if owner_aid else None
        out.append(item)
    return out


async def _already_alerted(
    eng: AsyncEngine,
    account_id: UUID | str,
    schedule_id: str,
) -> bool:
    """이 일정에 대해 이미 alert 를 보냈는지 — source->>'schedule_id' 매칭."""
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT 1 FROM feed_events "
                    " WHERE account_id = :aid "
                    "   AND kind = :k "
                    "   AND source->>'schedule_id' = :sid "
                    " LIMIT 1"
                ),
                {"aid": account_id, "k": _KIND, "sid": schedule_id},
            )
        ).first()
    return row is not None


def _build_body(item: dict[str, Any], tz: str) -> tuple[str, str, list[dict[str, str]]]:
    when_dt: datetime = item["when"]
    if when_dt.tzinfo is None:
        when_dt = when_dt.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        local = when_dt.astimezone(ZoneInfo(tz))
    except Exception:
        local = when_dt.astimezone(timezone.utc)
    when_str = local.strftime("%H:%M")
    title = f"{when_str} 일정 · {item['title'][:60]}"
    body = "곧 시작할 일정입니다. 자세히 살펴보려면 아래 버튼을 눌러주세요."
    pills = [
        {"label": "일정 자세히", "action_text": f"오늘 일정 자세히 알려줘"},
        {"label": "일정 변경", "action_text": f"이 일정 변경하고 싶어"},
    ]
    return title, body, pills


async def run_once(
    eng: AsyncEngine | None = None,
    now: datetime | None = None,
    horizon_minutes: int = 60,
) -> int:
    """매시 정시 호출. (now, now+60min] 일정 → feed_event INSERT. 새 row 수 반환."""
    eng = eng or _get_engine()
    now = now or datetime.now(timezone.utc)
    cols = await _detect_schedule_columns(eng)
    if cols is None:
        return 0
    horizon_end = now + timedelta(minutes=horizon_minutes)
    accounts = await list_active_accounts(eng)
    created = 0
    for acc in accounts:
        prefs = acc.get("preferences") or {}
        tprefs = acc.get("tenant_prefs") or {}
        if not cadence_enabled(prefs, _KIND, default=True):
            continue
        tz = resolve_account_timezone(prefs, tprefs)
        if in_quiet_hours(prefs, now, tz):
            continue
        items = await _list_upcoming_for_account(
            eng, acc["account_id"], cols, now, horizon_end
        )
        for item in items:
            if await _already_alerted(eng, acc["account_id"], item["id"]):
                continue
            title, body, pills = _build_body(item, tz)
            try:
                # D29 §4 (#161, 2026-05-08) — schedules.owner_agent_id 가
                # 컬럼으로 존재하면 source 에 forward (admin global view 에서
                # alert 출처 agent 추적). None / 컬럼 부재 시 유지.
                source: dict[str, Any] = {
                    "worker": "schedule_alert",
                    "schedule_id": item["id"],
                    "when": item["when"].isoformat()
                    if isinstance(item["when"], datetime)
                    else str(item["when"]),
                }
                if "owner_agent_id" in item:
                    source["owner_agent_id"] = item["owner_agent_id"]
                await insert_feed_event(
                    eng,
                    account_id=acc["account_id"],
                    tenant_id=acc["tenant_id"],
                    kind=_KIND,
                    title=title,
                    body=body,
                    pills=pills,
                    source=source,
                )
                created += 1
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "schedule_alert_insert_failed",
                    schedule_id=item["id"],
                    error=str(e),
                )
    log.info("schedule_alert_run_done", created=created)
    return created


async def schedule_alert_tick() -> int:
    return await run_once()
