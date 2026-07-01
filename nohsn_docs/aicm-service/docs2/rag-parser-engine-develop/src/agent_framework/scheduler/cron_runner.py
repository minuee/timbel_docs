"""APScheduler wrapper for scheduled skill triggers.

Each skill with `trigger_type: scheduled` (or non-null `schedule:` field) registers
a cron job that fires `engine._fire_scheduled_skill(skill_id)` at the specified time.

Scheduler timezone (codex P2-8)
--------------------------------
Scheduler 본체 timezone 은 server-side 베이스. PR P3 부터 feed cron worker 들이
**account 별 timezone** 을 직접 읽어 처리한다 (``accounts.preferences.timezone``,
없으면 tenant timezone, 없으면 ``Asia/Seoul``). 즉 cron 자체는 server tz 로
정시 발화하지만, worker 가 각 사용자 시각으로 환산해 quiet_hours / 보낼지 여부 /
표시 라벨을 결정한다. 단일 scheduler tz 를 모든 사용자에 강요하지 않는다.
"""
from __future__ import annotations
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


class CronRunner:
    def __init__(self, timezone: str = "Asia/Seoul"):
        # 베이스 timezone — cron 표현식 ``07 0 * * *`` 같은 정수 시각이 어느 tz
        # 의 정시인가를 결정. 사용자별 cadence 는 worker 가 ``preferences.timezone``
        # 으로 환산해 다시 처리.
        self.scheduler = AsyncIOScheduler(timezone=timezone)

    def register(
        self,
        cron_expr: str,
        job: Callable[[], Awaitable[None]],
        job_id: str,
    ) -> None:
        """Register an async callable to fire per cron expression."""
        self.scheduler.add_job(
            job,
            CronTrigger.from_crontab(cron_expr),
            id=job_id,
            replace_existing=True,
        )

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)


def resolve_account_timezone(
    account_prefs: dict | None,
    tenant_prefs: dict | None = None,
    fallback: str = "Asia/Seoul",
) -> str:
    """codex P2-8 — account.timezone path.

    ``accounts.preferences.timezone`` → ``tenants.preferences.timezone`` → fallback.
    빈 문자열 / None / 잘못된 타입은 모두 다음 우선순위로 떨어진다.
    """
    if isinstance(account_prefs, dict):
        v = account_prefs.get("timezone")
        if isinstance(v, str) and v.strip():
            return v.strip()
    if isinstance(tenant_prefs, dict):
        v = tenant_prefs.get("timezone")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return fallback
