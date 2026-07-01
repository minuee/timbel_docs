"""Daily feed composer — 매일 아침 brief 1건씩 ``feed_events`` 에 INSERT.

PR P3 (KMS-Plus). FeedPage 가 이걸 표시.

설계
----
1. 모든 활성 account 순회.
2. 각 account 의 ``personal_tenant_id`` (개인 scope) 으로 daily_briefing 생성.
3. ``feed_cadence.daily_briefing.enabled`` (default True) 인 account 만 대상.
4. quiet_hours 검사 — 사용자 timezone 으로 환산해 차단 구간이면 skip.
5. INSERT — kind/title/body/pills/source 모두 backend 에서 결정 (frontend 는
   그대로 렌더 — 하드코딩 enum 없음).

LLM 호출은 본 worker 에서는 하지 않는다. 본문은 단순 brief — 사용자에게
"오늘 아침 보고가 도착했어요" 류의 introduction. 깊은 brief 는 사용자가
카드 클릭 시 chat 으로 진입해 LLM 이 생성. (외부 서비스 미가동 환경에서도
worker 가 안전하게 돈다.)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.scheduler.cron_runner import resolve_account_timezone
from src.agent_framework.scheduler.feed_quiet_hours import (
    cadence_enabled,
    in_quiet_hours,
)
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


async def _reset_engine_for_tests() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


# ---------------------------------------------------------------------------
# Feed event INSERT helper — 4 worker 모두 공유.
# ---------------------------------------------------------------------------


async def insert_feed_event(
    eng: AsyncEngine,
    *,
    account_id: UUID | str,
    tenant_id: UUID | str,
    kind: str,
    title: str,
    body: str,
    body_html: str | None = None,
    pills: list[dict[str, Any]] | None = None,
    source: dict[str, Any] | None = None,
    produced_at: datetime | None = None,
) -> str:
    """``feed_events`` row INSERT. id 반환. 워커 4종 공통 helper."""
    pills_json = json.dumps(pills or [], ensure_ascii=False)
    source_json = json.dumps(source or {}, ensure_ascii=False)
    sql_cols = (
        "account_id, tenant_id, kind, title, body, body_html, "
        "pills, source"
    )
    sql_vals = (
        ":aid, :tid, :kind, :title, :body, :bh, "
        "CAST(:pills AS JSONB), CAST(:source AS JSONB)"
    )
    params: dict[str, Any] = {
        "aid": account_id,
        "tid": tenant_id,
        "kind": kind,
        "title": title,
        "body": body,
        "bh": body_html,
        "pills": pills_json,
        "source": source_json,
    }
    if produced_at is not None:
        sql_cols += ", produced_at"
        sql_vals += ", :pa"
        params["pa"] = produced_at
    sql = (
        f"INSERT INTO feed_events ({sql_cols}) VALUES ({sql_vals}) RETURNING id"
    )
    async with eng.begin() as conn:
        row = await conn.execute(text(sql), params)
        return str(row.scalar_one())


# ---------------------------------------------------------------------------
# Account 후보 조회 — 4 worker 공통.
# ---------------------------------------------------------------------------


async def list_active_accounts(eng: AsyncEngine) -> list[dict[str, Any]]:
    """``is_active=true`` 인 account 의 (id, personal_tenant_id, preferences) 목록.

    worker 들이 cadence/timezone/quiet_hours 결정에 쓸 최소 row. tenant 의 시간대
    fallback 은 ``tenants.config`` JSONB 의 ``timezone`` 키로 (현재 schema 에는
    ``preferences`` 컬럼이 없고 ``config`` 가 메타 dict 역할).
    """
    async with eng.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT a.id, a.personal_tenant_id, a.preferences, "
                    "       t.config AS tenant_prefs "
                    "  FROM accounts a "
                    "  LEFT JOIN tenants t ON t.id = a.personal_tenant_id "
                    " WHERE a.is_active = true "
                    "   AND a.personal_tenant_id IS NOT NULL"
                )
            )
        ).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        prefs = r[2] if isinstance(r[2], dict) else {}
        tprefs = r[3] if isinstance(r[3], dict) else {}
        out.append(
            {
                "account_id": r[0],
                "tenant_id": r[1],
                "preferences": prefs,
                "tenant_prefs": tprefs,
            }
        )
    return out


# ---------------------------------------------------------------------------
# 중복 방지 — 같은 kind 의 같은 날짜 (account tz 기준) row 가 이미 있으면 skip.
# ---------------------------------------------------------------------------


async def has_event_today(
    eng: AsyncEngine,
    account_id: UUID | str,
    tenant_id: UUID | str,
    kind: str,
    now: datetime,
    tz: str,
) -> bool:
    """오늘 (사용자 tz 기준) 같은 kind 의 row 가 이미 있는가."""
    try:
        from zoneinfo import ZoneInfo

        local = now.astimezone(ZoneInfo(tz))
    except Exception:
        local = now.astimezone(timezone.utc)
    # 사용자 tz 의 오늘 자정 → UTC 환산 → produced_at >= 비교.
    today_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = today_local.astimezone(timezone.utc)
    async with eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT 1 FROM feed_events "
                    " WHERE account_id = :aid AND tenant_id = :tid "
                    "   AND kind = :k AND produced_at >= :since "
                    " LIMIT 1"
                ),
                {"aid": account_id, "tid": tenant_id, "k": kind, "since": today_utc},
            )
        ).first()
    return row is not None


# ---------------------------------------------------------------------------
# daily_feed_compose — 매일 아침 1회.
# ---------------------------------------------------------------------------


_DAILY_KIND = "daily_briefing"


def _build_daily_brief_body() -> tuple[str, str, list[dict[str, str]]]:
    """daily brief 의 title/body/pills.

    pill 은 사용자가 클릭하면 chat composer 에 들어가는 trigger 문구.
    label 은 표시용, action_text 는 실제로 입력 값이 됨.
    """
    title = "오늘 아침 보고가 도착했어요"
    body = (
        "오늘 일정과 받은 메일, 시장 흐름을 한 번에 살펴보시려면"
        " 아래 버튼 중 하나를 눌러보세요."
    )
    pills = [
        {"label": "오늘 일정", "action_text": "오늘 일정 알려줘"},
        {"label": "받은 메일", "action_text": "오늘 받은 메일 요약해줘"},
        {"label": "시장 동향", "action_text": "오늘 시장 동향 알려줘"},
    ]
    return title, body, pills


async def compose_one(
    eng: AsyncEngine,
    account: dict[str, Any],
    now: datetime | None = None,
) -> str | None:
    """단일 account 에 daily_briefing INSERT. 이미 오늘 row 있으면 None."""
    now = now or datetime.now(timezone.utc)
    prefs = account.get("preferences") or {}
    tenant_prefs = account.get("tenant_prefs") or {}
    tz = resolve_account_timezone(prefs, tenant_prefs)

    if not cadence_enabled(prefs, _DAILY_KIND, default=True):
        return None
    # 일별 1회 — 같은 날짜에 중복 INSERT 금지.
    if await has_event_today(
        eng,
        account["account_id"],
        account["tenant_id"],
        _DAILY_KIND,
        now,
        tz,
    ):
        return None
    # daily_briefing 은 정의상 업무 시간대라 quiet_hours 적용 X (사용자 강조).

    title, body, pills = _build_daily_brief_body()
    return await insert_feed_event(
        eng,
        account_id=account["account_id"],
        tenant_id=account["tenant_id"],
        kind=_DAILY_KIND,
        title=title,
        body=body,
        pills=pills,
        source={"worker": "daily_feed_compose", "tz": tz},
    )


async def compose_for_all(
    eng: AsyncEngine | None = None,
    now: datetime | None = None,
) -> int:
    """모든 활성 account 대상 daily brief INSERT. 새로 만든 row 개수 반환."""
    eng = eng or _get_engine()
    now = now or datetime.now(timezone.utc)
    accounts = await list_active_accounts(eng)
    created = 0
    for acc in accounts:
        try:
            fid = await compose_one(eng, acc, now=now)
            if fid:
                created += 1
        except Exception as e:  # noqa: BLE001
            log.warning(
                "daily_feed_compose_failed",
                account_id=str(acc.get("account_id")),
                error=str(e),
            )
    log.info(
        "daily_feed_compose_done",
        created=created,
        accounts=len(accounts),
    )
    return created


async def daily_feed_compose() -> int:
    """cron entry point. ``cron.register("0 7 * * *", daily_feed_compose, ...)``."""
    return await compose_for_all()


# 외부 노출 — accounts iter helper (테스트에서 cleanup 용).
__all__ = [
    "insert_feed_event",
    "list_active_accounts",
    "has_event_today",
    "compose_one",
    "compose_for_all",
    "daily_feed_compose",
    "_reset_engine_for_tests",
]
