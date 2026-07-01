"""주기 주식 모니터링 worker.

설계 — 단일 cron 작업이 매 분 깨어나 *due* 한 watch 항목만 처리.

처리 단계:
1) 모든 tenant 의 ``agent_stock_watch`` 항목 중 ``monitor_interval_min > 0`` 만 후보
2) ``last_monitor_at + interval`` 가 현재 ≤ 면 due
3) due 항목 종목코드 묶어 한 번에 시세 조회 (코드 unique 캐시 hit)
4) 변경: 가격이 ``alert_high`` 이상 또는 ``alert_low`` 이하 → notification row 추가
5) ``last_monitor_at`` 업데이트

Notification 저장: ``agent_documents`` document_type=``agent_stock_alert`` —
사용자가 다음 챗 진입 시 daily_briefing 또는 별도 inbox skill 이 읽어 노출.
환경 ``KMS_STOCK_MONITOR_ENABLED=1`` 이어야 등록.
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.agent_framework.storage import agent_document_store
from src.agent_framework.tools import stock_data
from src.common.config import settings
from src.common.logging import get_logger

log = get_logger(__name__)

_DOCUMENT_TYPE = "agent_stock_watch"
_ALERT_DOCUMENT_TYPE = "agent_stock_alert"

_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _is_due(item: dict[str, Any], now: _dt.datetime) -> bool:
    body = item.get("body") if isinstance(item, dict) else {}
    if not isinstance(body, dict):
        return False
    interval = int(body.get("monitor_interval_min") or 0)
    if interval <= 0:
        return False
    last = body.get("last_monitor_at")
    if not last:
        return True
    try:
        last_dt = _dt.datetime.fromisoformat(str(last))
    except ValueError:
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
    delta = now - last_dt
    return delta.total_seconds() >= interval * 60


async def _list_tenants_with_watches(eng: AsyncEngine) -> list[UUID]:
    """``agent_stock_watch`` document_type 을 가진 tenant 목록."""
    async with eng.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT dt.tenant_id
                      FROM document_types dt
                     WHERE dt.name = :name
                    """
                ),
                {"name": _DOCUMENT_TYPE},
            )
        ).all()
    return [r[0] for r in rows]


async def _save_alert(
    eng: AsyncEngine, tenant_id: UUID, body: dict[str, Any], title: str
) -> None:
    """alert document 한 건 저장. agent_stock_alert document_type."""
    try:
        await agent_document_store.create_item(
            eng, tenant_id, _ALERT_DOCUMENT_TYPE, title=title, body=body
        )
    except Exception as e:  # noqa: BLE001
        log.warning("stock_alert_save_failed", error=str(e))


async def tick() -> dict[str, Any]:
    """매 분 호출. due 한 watch 항목 처리."""
    eng = _get_engine()
    now = _now_utc()
    tenants = await _list_tenants_with_watches(eng)
    processed = 0
    alerts = 0
    for tid in tenants:
        try:
            items = await agent_document_store.list_items(eng, tid, _DOCUMENT_TYPE)
        except Exception as e:  # noqa: BLE001
            log.warning("stock_monitor_list_failed", tid=str(tid), error=str(e))
            continue
        due = [it for it in items if _is_due(it, now)]
        if not due:
            continue

        # 코드 별로 시세 한 번씩만 — 동일 종목 여러 watch (다른 사용자) 도 캐시 활용.
        for it in due:
            body = dict(it.get("body") or {})
            code = body.get("code")
            if not code:
                continue
            q = await stock_data.quote({"symbol": code})
            if not q.get("success"):
                continue
            cur = int(q.get("close") or 0)
            chg_pct = float(q.get("change_pct") or 0)

            # alert 충돌 검사
            ah = body.get("alert_high")
            al = body.get("alert_low")
            triggered: list[str] = []
            if ah is not None and cur >= int(ah):
                triggered.append(f"상단 alert {ah:,}원 도달 → 현재 {cur:,}원")
            if al is not None and cur <= int(al):
                triggered.append(f"하단 alert {al:,}원 도달 → 현재 {cur:,}원")

            if triggered:
                alert_body = {
                    "code": code,
                    "name": body.get("name"),
                    "current_price": cur,
                    "change_pct": chg_pct,
                    "watch_id": str(it.get("id")),
                    "triggered": triggered,
                    "ts": now.isoformat(timespec="seconds"),
                }
                title = f"{body.get('name') or code} alert · {cur:,}원 ({chg_pct:+.2f}%)"
                await _save_alert(eng, tid, alert_body, title)
                alerts += 1

            # last_monitor_at 갱신
            body["last_monitor_at"] = now.isoformat(timespec="seconds")
            try:
                await agent_document_store.update_item(
                    eng,
                    tid,
                    _DOCUMENT_TYPE,
                    str(it.get("id")),
                    body_patch=body,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("stock_monitor_update_failed", error=str(e))
            processed += 1

    log.info("stock_monitor_tick_done", processed=processed, alerts=alerts, tenants=len(tenants))
    return {"processed": processed, "alerts": alerts, "tenants": len(tenants)}


def is_enabled() -> bool:
    return os.environ.get("KMS_STOCK_MONITOR_ENABLED", "").lower() in ("1", "true", "yes")
