"""Reminder Worker — 1분 주기 polling + 발사 (P11-18, 2026-04-29).

reminder_store 의 active reminder 중 ``next_at <= now`` 인 항목을:
1. 발사 — feed_event 형태로 사용자 세션에 push (현 단계는 로그 + Redis pub).
2. last_fired_at = now stamp.
3. recurrence 가 있으면 next_at 재계산. 없으면 status='done'.

초기 단계 알림 채널은 *로그 + Redis pubsub* (frontend 가 subscribe 가능).
실제 SMS / push notification 통합은 후속 PR.

운영 주기: 60초. 시계 정확도 충분 (분 단위 알람).

기동:
    python -m src.pipeline.workers.reminder_worker
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import signal

from src.agent_framework.tools import reminder_store as rstore
from src.agent_framework.tools import _redis_store as rs
from src.common.logging import get_logger

log = get_logger(__name__)

POLL_INTERVAL_S = int(os.environ.get("REMINDER_WORKER_POLL_S", "60"))
PUBSUB_CHANNEL = "kms:reminder:fired"


async def _publish_fire_event(reminder: dict) -> None:
    """Redis pubsub 으로 fire 이벤트 송출. frontend / chat session 이 subscribe."""
    try:
        c = await rs._get_client()
        await c.publish(
            PUBSUB_CHANNEL,
            json.dumps(
                {
                    "id": str(reminder.get("id") or ""),
                    "title": reminder.get("title"),
                    "template": reminder.get("template"),
                    "tenant_id": reminder.get("tenant_id"),
                    "fired_at": _dt.datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            ),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("reminder_publish_failed", error=str(e), id=reminder.get("id"))


async def _process_due() -> int:
    """due reminder 일괄 처리. 반환 값 = 발사한 개수."""
    # local tz aware now — schedule() 가 같은 tz 로 next_at 을 stamp 한다.
    now = rstore._local_now()
    fired_count = 0
    items = await rstore.list_active()
    for it in items:
        # KMS 모드는 dict {id, body: {...}}, redis 모드는 dict {id, ...} flat.
        body = it.get("body") if isinstance(it, dict) and "body" in it else it
        rid = str(it.get("id") or body.get("id") or "")
        if not rid:
            continue
        next_at = body.get("next_at")
        if not next_at:
            continue
        try:
            due_at = _dt.datetime.fromisoformat(str(next_at))
        except ValueError:
            continue
        # next_at 가 naive 면 local tz 부여 (옛 row 호환).
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=rstore._local_tz())
        if due_at > now:
            continue

        # 발사
        log.info(
            "reminder_fired",
            id=rid,
            title=body.get("title"),
            template=body.get("template"),
            scheduled=next_at,
            actual=now.isoformat(timespec="seconds"),
        )
        # tenant_id 는 body 안에 따로 없을 수 있음 (kms 모드는 document row 의 tenant_id).
        # KMS 모드 list_items_global_doctype 은 tenant_id 를 포함해야 함.
        tenant_id = it.get("tenant_id") or body.get("tenant_id")
        await _publish_fire_event(
            {
                "id": rid,
                "title": body.get("title"),
                "template": body.get("template"),
                "tenant_id": str(tenant_id) if tenant_id else None,
            }
        )

        # next_at 재계산 (recurrence) 또는 done 처리.
        recurrence = body.get("recurrence")
        now_iso = now.isoformat(timespec="seconds")
        new_next_at = None
        new_status = None
        if recurrence:
            new_next_at = rstore.compute_next_occurrence(
                recurrence,
                now=now,
                last_fired_at=now_iso,
            )
        if not new_next_at:
            new_status = "done"

        await rstore.mark_fired(
            rid,
            tenant_id=str(tenant_id) if tenant_id else None,
            new_next_at=new_next_at,
            new_last_fired_at=now_iso,
            new_status=new_status,
        )
        fired_count += 1
    return fired_count


async def _run_loop(stop_event: asyncio.Event) -> None:
    log.info("reminder_worker_started", interval_s=POLL_INTERVAL_S)

    # D34 §1 — bind_system_scope wrap. reminder_worker 는 task 로 spawn — 진입부
    # 자체 wrap 으로 RLSContext 보장. allow_null_tenant=True (cross-tenant scan).
    # write 발생 시 alembic 079 가 tenant_id 매칭 강제.
    from src.api.middleware.rls_context import bind_system_scope

    while not stop_event.is_set():
        try:
            async with bind_system_scope(None, allow_null_tenant=True):
                n = await _process_due()
            if n:
                log.info("reminder_worker_tick", fired=n)
        except Exception as e:  # noqa: BLE001
            log.error("reminder_worker_tick_failed", error=str(e))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
    log.info("reminder_worker_stopped")


def main() -> None:
    stop_event = asyncio.Event()

    def _signal_handler(*_: object) -> None:
        stop_event.set()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass
    try:
        loop.run_until_complete(_run_loop(stop_event))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
