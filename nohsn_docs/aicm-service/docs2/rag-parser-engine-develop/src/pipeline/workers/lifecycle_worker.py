"""Lifecycle Worker — 시간 기반 예약 작업 처리 백그라운드 워커.

매시간 실행되어 pending 상태이고 scheduled_at <= NOW() 인 예약 작업을 처리한다.
또한 1년 이상 미사용 블럭에 대한 자동 정리 리마인더를 생성한다.

사용법::

    python -m src.pipeline.workers.lifecycle_worker
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger, setup_logging

log = get_logger(__name__)

_SHUTDOWN_EVENT = asyncio.Event()
_POLL_INTERVAL_SECONDS = 3600  # 1시간


def _handle_signal(sig: int, frame: Any) -> None:
    """SIGTERM/SIGINT 시 graceful shutdown."""
    log.info("lifecycle_worker_shutdown_signal", signal=sig)
    _SHUTDOWN_EVENT.set()


async def _get_session() -> AsyncSession:
    """비동기 DB 세션을 생성한다."""
    from src.core.database import async_session_factory

    return async_session_factory()


async def _execute_action(
    session: AsyncSession,
    action_id: UUID,
    action: str,
    target_block_ids: list[str],
    params: dict | None,
    tenant_id: UUID,
) -> dict[str, Any]:
    """예약된 액션을 실행한다.

    Returns:
        실행 결과 dict
    """
    from src.core.models.block import Block

    now = datetime.now(timezone.utc)
    block_uuids = [UUID(bid) for bid in target_block_ids]

    if action == "change_status":
        new_status = (params or {}).get("new_status", "archived")
        reason = (params or {}).get("reason", f"lifecycle 예약 작업 ({action_id})")

        # legal_hold 블럭 제외
        held_stmt = select(Block.id).where(
            Block.id.in_(block_uuids),
            Block.legal_hold.is_(True),
        )
        held_result = await session.execute(held_stmt)
        held_ids = {row[0] for row in held_result.fetchall()}
        effective_ids = [bid for bid in block_uuids if bid not in held_ids]

        if effective_ids:
            stmt = (
                update(Block)
                .where(Block.id.in_(effective_ids))
                .values(
                    validity_status=new_status,
                    validity_reason=reason,
                    validity_changed_at=now,
                )
            )
            result = await session.execute(stmt)
            updated = result.rowcount
        else:
            updated = 0

        return {
            "action": "change_status",
            "new_status": new_status,
            "requested": len(block_uuids),
            "updated": updated,
            "skipped_legal_hold": len(held_ids),
        }

    elif action == "anonymize":
        # 비식별화 — anonymization 서비스 호출
        updated = 0
        for bid in block_uuids:
            try:
                block_stmt = select(Block).where(
                    Block.id == bid,
                    Block.legal_hold.is_(False),
                )
                block_result = await session.execute(block_stmt)
                block = block_result.scalar_one_or_none()
                if block is None:
                    continue

                # 비식별화 기록
                anon_log = block.anonymization_log or {}
                anon_log[now.isoformat()] = {
                    "action_id": str(action_id),
                    "type": "lifecycle_scheduled",
                }
                block.anonymization_log = anon_log
                block.validity_status = "archived"
                block.validity_reason = f"lifecycle 비식별화 ({action_id})"
                block.validity_changed_at = now
                updated += 1
            except Exception as exc:
                log.warning(
                    "anonymize_block_failed",
                    block_id=str(bid),
                    error=str(exc),
                )

        return {
            "action": "anonymize",
            "requested": len(block_uuids),
            "updated": updated,
        }

    elif action == "archive":
        reason = f"lifecycle 아카이브 ({action_id})"
        effective_ids = block_uuids  # legal_hold 체크

        held_stmt = select(Block.id).where(
            Block.id.in_(block_uuids),
            Block.legal_hold.is_(True),
        )
        held_result = await session.execute(held_stmt)
        held_ids = {row[0] for row in held_result.fetchall()}
        effective_ids = [bid for bid in block_uuids if bid not in held_ids]

        if effective_ids:
            stmt = (
                update(Block)
                .where(Block.id.in_(effective_ids))
                .values(
                    validity_status="archived",
                    validity_reason=reason,
                    validity_changed_at=now,
                )
            )
            result = await session.execute(stmt)
            updated = result.rowcount
        else:
            updated = 0

        return {
            "action": "archive",
            "requested": len(block_uuids),
            "updated": updated,
            "skipped_legal_hold": len(held_ids),
        }

    elif action == "purge":
        # 퍼지: 블럭 삭제 (소프트) — legal_hold 체크
        from sqlalchemy import delete

        held_stmt = select(Block.id).where(
            Block.id.in_(block_uuids),
            Block.legal_hold.is_(True),
        )
        held_result = await session.execute(held_stmt)
        held_ids = {row[0] for row in held_result.fetchall()}
        effective_ids = [bid for bid in block_uuids if bid not in held_ids]

        if effective_ids:
            # validity_status를 purged로 변경 (실제 삭제 대신)
            stmt = (
                update(Block)
                .where(Block.id.in_(effective_ids))
                .values(
                    validity_status="purged",
                    validity_reason=f"lifecycle 퍼지 ({action_id})",
                    validity_changed_at=now,
                )
            )
            result = await session.execute(stmt)
            updated = result.rowcount
        else:
            updated = 0

        return {
            "action": "purge",
            "requested": len(block_uuids),
            "updated": updated,
            "skipped_legal_hold": len(held_ids),
        }

    else:
        return {"action": action, "error": f"알 수 없는 액션: {action}"}


async def process_pending_actions() -> int:
    """pending 상태이고 scheduled_at <= NOW() 인 예약 작업을 처리한다.

    Returns:
        처리된 작업 수
    """
    from src.core.models.scheduled_action import ScheduledAction

    now = datetime.now(timezone.utc)
    processed = 0

    async with await _get_session() as session:
        try:
            # pending 작업 조회 (한 번에 최대 100건)
            stmt = (
                select(ScheduledAction)
                .where(
                    ScheduledAction.status == "pending",
                    ScheduledAction.scheduled_at <= now,
                )
                .order_by(ScheduledAction.scheduled_at.asc())
                .limit(100)
            )
            result = await session.execute(stmt)
            actions = result.scalars().all()

            if not actions:
                return 0

            log.info("lifecycle_worker_found_pending", count=len(actions))

            for action_row in actions:
                try:
                    exec_result = await _execute_action(
                        session=session,
                        action_id=action_row.id,
                        action=action_row.action,
                        target_block_ids=action_row.target_block_ids,
                        params=action_row.params,
                        tenant_id=action_row.tenant_id,
                    )

                    action_row.status = "executed"
                    action_row.result = exec_result
                    action_row.executed_at = now
                    processed += 1

                    log.info(
                        "lifecycle_action_executed",
                        action_id=str(action_row.id),
                        action=action_row.action,
                        result=exec_result,
                    )

                except Exception as exc:
                    action_row.status = "failed"
                    action_row.result = {"error": str(exc)}
                    action_row.executed_at = now

                    log.error(
                        "lifecycle_action_failed",
                        action_id=str(action_row.id),
                        error=str(exc),
                    )

            await session.commit()

        except Exception as exc:
            await session.rollback()
            log.error("lifecycle_worker_batch_failed", error=str(exc))

    return processed


async def generate_stale_reminders() -> int:
    """1년 이상 미사용 블럭에 대해 정리 리마인더를 생성한다.

    notifications JSONB 컬럼이 없으므로 scheduled_actions 테이블에
    action='reminder'로 저장하여 API에서 조회할 수 있도록 한다.

    Returns:
        생성된 리마인더 수
    """
    from src.core.models.block import Block
    from src.core.models.repository import Repository
    from src.core.models.scheduled_action import ScheduledAction

    one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
    now = datetime.now(timezone.utc)
    created = 0

    async with await _get_session() as session:
        try:
            # 1년 이상 미갱신된 active 블럭의 테넌트 + 카운트
            stale_stmt = (
                select(
                    Repository.tenant_id,
                    func.count(Block.id).label("stale_count"),
                    func.array_agg(Block.id).label("block_ids"),
                )
                .join(Repository, Block.repository_id == Repository.id)
                .where(
                    Block.validity_status == "active",
                    Block.updated_at < one_year_ago,
                )
                .group_by(Repository.tenant_id)
                .having(func.count(Block.id) >= 1)
            )
            result = await session.execute(stale_stmt)
            rows = result.all()

            for row in rows:
                tenant_id = row.tenant_id
                stale_count = row.stale_count
                block_ids = [str(bid) for bid in (row.block_ids or [])[:100]]

                # 이미 최근 7일 이내에 동일 테넌트에 대한 reminder가 있는지 확인
                week_ago = now - timedelta(days=7)
                existing_stmt = (
                    select(func.count(ScheduledAction.id))
                    .where(
                        ScheduledAction.tenant_id == tenant_id,
                        ScheduledAction.action == "reminder",
                        ScheduledAction.created_at >= week_ago,
                    )
                )
                existing_count = (await session.execute(existing_stmt)).scalar() or 0
                if existing_count > 0:
                    continue

                # 리마인더 생성 (즉시 조회 가능하도록 scheduled_at = now)
                reminder = ScheduledAction(
                    tenant_id=tenant_id,
                    action="reminder",
                    target_block_ids=block_ids,
                    params={"stale_count": stale_count},
                    scheduled_at=now,
                    status="pending",
                    reason=f"{stale_count}개 블럭이 1년 이상 미사용 상태입니다.",
                )
                session.add(reminder)
                created += 1

            await session.commit()

            if created > 0:
                log.info("stale_reminders_created", count=created)

        except Exception as exc:
            await session.rollback()
            log.error("stale_reminders_failed", error=str(exc))

    return created


async def run_lifecycle_loop() -> None:
    """메인 루프: 매시간 pending 작업 처리 + 1일 1회 리마인더 생성."""
    setup_logging()
    log.info("lifecycle_worker_started", poll_interval=_POLL_INTERVAL_SECONDS)

    last_reminder_check = datetime.min.replace(tzinfo=timezone.utc)

    while not _SHUTDOWN_EVENT.is_set():
        try:
            # 1) pending 작업 처리
            processed = await process_pending_actions()
            if processed > 0:
                log.info("lifecycle_worker_cycle_complete", processed=processed)

            # 2) 1일 1회 리마인더 체크
            now = datetime.now(timezone.utc)
            if (now - last_reminder_check) >= timedelta(hours=24):
                reminders = await generate_stale_reminders()
                last_reminder_check = now
                if reminders > 0:
                    log.info("lifecycle_reminders_generated", count=reminders)

        except Exception as exc:
            log.error("lifecycle_worker_loop_error", error=str(exc))

        # 다음 주기까지 대기 (shutdown 시 즉시 종료)
        try:
            await asyncio.wait_for(
                _SHUTDOWN_EVENT.wait(),
                timeout=_POLL_INTERVAL_SECONDS,
            )
            break  # shutdown 요청됨
        except asyncio.TimeoutError:
            continue  # 다음 주기


def main() -> None:
    """CLI 진입점."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    asyncio.run(run_lifecycle_loop())


if __name__ == "__main__":
    main()
