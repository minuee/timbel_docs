"""DLQ 자동 재처리 스케줄러.

5분 주기로 dlq_messages 테이블을 스캔하여 재처리 조건을 충족하는
메시지를 원본 Kafka 토픽으로 재발행한다.

재처리 정책:
  - 지수 백오프: retry_count 기반 최소 대기 시간 (2^retry_count 분)
    retry_count 0→2분, 1→2분, 2→4분, 3→8분, 4→16분
  - 최대 재시도: retry_count >= 5 이면 permanent_failure 처리
  - 스캔 주기: 5분 (DLQ_SCAN_INTERVAL_SECONDS)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

DLQ_SCAN_INTERVAL_SECONDS = 300  # 5분
DLQ_MAX_RETRY_COUNT = 5          # 이 횟수 이상이면 permanent_failure
DLQ_BASE_BACKOFF_MINUTES = 2     # 지수 백오프 기본값 (분)


def _backoff_minutes(retry_count: int) -> int:
    """retry_count 기반 지수 백오프 대기 시간(분)을 계산한다.

    2^0=1 이지만 최소 2분을 보장:
      retry_count 0 → 2분 (초기 실패 → 2분 후 재시도)
      retry_count 1 → 2분
      retry_count 2 → 4분
      retry_count 3 → 8분
      retry_count 4 → 16분
    """
    exponent = max(0, retry_count - 1)
    return DLQ_BASE_BACKOFF_MINUTES * (2 ** exponent)


async def _mark_permanent_failures(session: Any) -> int:
    """retry_count >= DLQ_MAX_RETRY_COUNT 인 pending 메시지를 permanent_failure 로 전환.

    Returns
    -------
    int
        permanent_failure 로 전환된 메시지 수
    """
    from sqlalchemy import update

    from src.core.models.dlq_message import DLQMessageORM

    stmt = (
        update(DLQMessageORM)
        .where(
            DLQMessageORM.status == "pending",
            DLQMessageORM.retry_count >= DLQ_MAX_RETRY_COUNT,
            DLQMessageORM.permanent_failure == False,  # noqa: E712
        )
        .values(permanent_failure=True)
        .returning(DLQMessageORM.id)
    )
    result = await session.execute(stmt)
    rows = result.fetchall()
    if rows:
        await session.commit()
    return len(rows)


async def _get_retryable_messages(session: Any) -> list[Any]:
    """재처리 대상 메시지를 조회한다.

    조건:
      - status = 'pending'
      - permanent_failure = False
      - retry_count < DLQ_MAX_RETRY_COUNT
      - created_at + 지수 백오프 대기 시간 <= 현재 시각
    """
    from sqlalchemy import select

    from src.core.models.dlq_message import DLQMessageORM

    now = datetime.now(timezone.utc)
    stmt = (
        select(DLQMessageORM)
        .where(
            DLQMessageORM.status == "pending",
            DLQMessageORM.permanent_failure == False,  # noqa: E712
            DLQMessageORM.retry_count < DLQ_MAX_RETRY_COUNT,
        )
        .order_by(DLQMessageORM.created_at.asc())
    )
    result = await session.execute(stmt)
    candidates = result.scalars().all()

    # 지수 백오프 필터: 각 메시지의 대기 시간 충족 여부 확인
    retryable = []
    for msg in candidates:
        wait_minutes = _backoff_minutes(msg.retry_count)
        eligible_after = msg.created_at + timedelta(minutes=wait_minutes)
        if now >= eligible_after:
            retryable.append(msg)

    return retryable


async def _should_block_part_blocked_redelivery(msg: Any) -> bool:
    """T77 (2026-05-18) — spec §3.4 차단 조건 매칭.

    msg.topic == part_blocked + msg.payload 또는 error_message 에
    split_job_starvation 패턴 매칭 시 redelivery 차단 대상.
    """
    from src.common.constants import TOPIC_DOCUMENT_PART_BLOCKED

    if (getattr(msg, "topic", None) or "") != TOPIC_DOCUMENT_PART_BLOCKED:
        return False
    payload = (getattr(msg, "payload", None) or "")
    error_msg = (getattr(msg, "error_message", None) or "")
    patterns = ("Split job not found", "split_job_starvation_suspected")
    haystack = payload + " " + error_msg
    return any(p in haystack for p in patterns)


async def _quarantine_dlq_msg_for_blocked_pattern(msg: Any) -> None:
    """T77 — 차단된 메시지 quarantine: DB에서 즉시 삭제 + 알림 로그.

    재발행 안 함. spec §3.4 — 차단 패턴은 *영구 quarantine* (다음 scan 안 옴).
    """
    from sqlalchemy import delete

    from src.core.database import async_session_factory
    from src.core.models.dlq_message import DLQMessageORM

    log.info(
        "dlq_part_blocked_redelivery_blocked",
        msg_id=str(msg.id),
        topic=msg.topic,
        reason="split_job_starvation_suspected",
        consumer_role="dlq_scheduler",
    )
    async with async_session_factory() as session:
        await session.execute(
            delete(DLQMessageORM).where(DLQMessageORM.id == msg.id)
        )
        await session.commit()


async def _republish_message(producer: Any, msg: Any) -> bool:
    """DLQ 메시지를 원본 Kafka 토픽으로 재발행한다.

    T77 — 차단 조건 매칭 시 영구 quarantine (재발행 안 함, DB 삭제 후 True 반환).

    성공 시 DB 에서 해당 행을 삭제하고, 실패 시 retry_count 를 증가시킨다.

    Returns
    -------
    bool
        재발행 성공 여부 (차단된 메시지는 True — caller 가 DB 삭제 처리 진행)
    """
    from sqlalchemy import delete, update

    from src.core.models.dlq_message import DLQMessageORM

    # T77 — spec §3.4 part_blocked + split_job_starvation 패턴 차단
    if await _should_block_part_blocked_redelivery(msg):
        await _quarantine_dlq_msg_for_blocked_pattern(msg)
        return True  # caller 가 DB delete — 이미 처리됨, 중복 delete 무해

    try:
        from aiokafka import AIOKafkaProducer

        if not isinstance(producer, AIOKafkaProducer):
            log.warning(
                "dlq_scheduler_producer_not_kafka",
                msg_id=str(msg.id),
                consumer_role="dlq_scheduler",
            )
            return False

        value = msg.payload.encode("utf-8")
        await producer.send_and_wait(msg.topic, value=value)

        log.info(
            "dlq_scheduler_republished",
            msg_id=str(msg.id),
            topic=msg.topic,
            retry_count=msg.retry_count,
            consumer_role="dlq_scheduler",
        )
        return True

    except ImportError:
        log.warning("dlq_scheduler_aiokafka_not_installed", consumer_role="dlq_scheduler")
        return False
    except Exception as exc:
        log.error(
            "dlq_scheduler_republish_failed",
            msg_id=str(msg.id),
            topic=msg.topic,
            error=str(exc),
            consumer_role="dlq_scheduler",
        )
        return False


async def _run_single_scan(producer: Any) -> dict[str, int]:
    """DLQ 테이블을 1회 스캔하여 재처리를 수행한다.

    Returns
    -------
    dict
        처리 결과 통계 {republished, failed, permanent}
    """
    from sqlalchemy import delete, update

    from src.core.database import async_session_factory
    from src.core.models.dlq_message import DLQMessageORM

    stats = {"republished": 0, "failed": 0, "permanent": 0}

    async with async_session_factory() as session:
        # 1) 영구 실패 처리
        permanent_count = await _mark_permanent_failures(session)
        stats["permanent"] = permanent_count

        # 2) 재처리 대상 조회
        messages = await _get_retryable_messages(session)

        if not messages:
            return stats

        log.info(
            "dlq_scheduler_scan_found",
            retryable_count=len(messages),
            consumer_role="dlq_scheduler",
        )

        # 3) 각 메시지를 원본 토픽으로 재발행
        for msg in messages:
            success = await _republish_message(producer, msg)

            if success:
                # 성공: DB에서 삭제
                del_stmt = delete(DLQMessageORM).where(DLQMessageORM.id == msg.id)
                await session.execute(del_stmt)
                stats["republished"] += 1
            else:
                # 실패: retry_count 증가
                upd_stmt = (
                    update(DLQMessageORM)
                    .where(DLQMessageORM.id == msg.id)
                    .values(retry_count=msg.retry_count + 1)
                )
                await session.execute(upd_stmt)
                stats["failed"] += 1

        await session.commit()

    return stats


async def dlq_scheduler_loop(producer: Any, shutdown_event: asyncio.Event) -> None:
    """DLQ 자동 재처리 무한 루프.

    pipeline-worker 시작 시 asyncio.create_task 로 실행되며,
    shutdown_event 가 set 되면 종료한다.

    Parameters
    ----------
    producer : aiokafka.AIOKafkaProducer
        Kafka producer 인스턴스
    shutdown_event : asyncio.Event
        종료 시그널
    """
    log.info(
        "dlq_scheduler_started",
        scan_interval_sec=DLQ_SCAN_INTERVAL_SECONDS,
        max_retry=DLQ_MAX_RETRY_COUNT,
        base_backoff_min=DLQ_BASE_BACKOFF_MINUTES,
        consumer_role="dlq_scheduler",
    )

    # D34 §1 — bind_system_scope wrap. dlq_scheduler 는 task 로 spawn 되므로 진입부
    # 자체 wrap 으로 RLSContext 보장 (caller wrap 누락 대비). allow_null_tenant=True —
    # DLQ scan 은 cross-tenant SELECT 만 (rewrite 시 alembic 079 가 tenant_id 매칭 강제).
    from src.api.middleware.rls_context import bind_system_scope

    while not shutdown_event.is_set():
        try:
            async with bind_system_scope(None, allow_null_tenant=True):
                stats = await _run_single_scan(producer)
            if stats["republished"] or stats["failed"] or stats["permanent"]:
                log.info(
                    "dlq_scheduler_scan_result",
                    **stats,
                    consumer_role="dlq_scheduler",
                )
        except Exception as exc:
            log.error(
                "dlq_scheduler_scan_error",
                error=str(exc),
                consumer_role="dlq_scheduler",
            )

        # 다음 스캔까지 대기 (shutdown 시 즉시 탈출)
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=DLQ_SCAN_INTERVAL_SECONDS,
            )
            # shutdown_event 가 set 됨 → 루프 종료
            break
        except asyncio.TimeoutError:
            # 타임아웃 = 정상적 대기 완료 → 다음 스캔
            continue

    log.info("dlq_scheduler_stopped", consumer_role="dlq_scheduler")


# ---------------------------------------------------------------------------
# retry-all: 조건 충족 메시지 전체 즉시 재처리 (관리 API 용)
# ---------------------------------------------------------------------------

async def retry_all_eligible(producer: Any | None = None) -> dict[str, int]:
    """재처리 가능한 모든 DLQ 메시지를 즉시 재처리한다.

    producer 가 None 이면 DB 상태만 'retried' 로 변경한다.

    Returns
    -------
    dict
        {republished: int, failed: int, permanent: int, skipped: int}
    """
    from sqlalchemy import delete, select, update

    from src.core.database import async_session_factory
    from src.core.models.dlq_message import DLQMessageORM

    stats = {"republished": 0, "failed": 0, "permanent": 0, "skipped": 0}

    async with async_session_factory() as session:
        # 영구 실패 먼저 마킹
        permanent_count = await _mark_permanent_failures(session)
        stats["permanent"] = permanent_count

        # 재처리 가능 메시지 조회 (백오프 무시 — 즉시 전체)
        stmt = (
            select(DLQMessageORM)
            .where(
                DLQMessageORM.status == "pending",
                DLQMessageORM.permanent_failure == False,  # noqa: E712
                DLQMessageORM.retry_count < DLQ_MAX_RETRY_COUNT,
            )
            .order_by(DLQMessageORM.created_at.asc())
        )
        result = await session.execute(stmt)
        messages = result.scalars().all()

        for msg in messages:
            if producer is not None:
                success = await _republish_message(producer, msg)
                if success:
                    del_stmt = delete(DLQMessageORM).where(DLQMessageORM.id == msg.id)
                    await session.execute(del_stmt)
                    stats["republished"] += 1
                else:
                    upd_stmt = (
                        update(DLQMessageORM)
                        .where(DLQMessageORM.id == msg.id)
                        .values(retry_count=msg.retry_count + 1)
                    )
                    await session.execute(upd_stmt)
                    stats["failed"] += 1
            else:
                # producer 없음: DB 상태만 변경
                upd_stmt = (
                    update(DLQMessageORM)
                    .where(DLQMessageORM.id == msg.id)
                    .values(status="retried")
                )
                await session.execute(upd_stmt)
                stats["republished"] += 1

        await session.commit()

    return stats


async def get_dlq_stats() -> dict[str, Any]:
    """DLQ 메시지 상태별 통계를 반환한다.

    Returns
    -------
    dict
        {
          total: int,
          pending: int,
          retried: int,
          discarded: int,
          permanent_failure: int,
          retryable: int,   # 현재 재처리 가능 메시지 수
        }
    """
    from sqlalchemy import case, func, select

    from src.core.database import async_session_factory
    from src.core.models.dlq_message import DLQMessageORM

    async with async_session_factory() as session:
        # 상태별 카운트
        stmt = select(
            func.count().label("total"),
            func.count()
            .filter(DLQMessageORM.status == "pending")
            .label("pending"),
            func.count()
            .filter(DLQMessageORM.status == "retried")
            .label("retried"),
            func.count()
            .filter(DLQMessageORM.status == "discarded")
            .label("discarded"),
            func.count()
            .filter(DLQMessageORM.permanent_failure == True)  # noqa: E712
            .label("permanent_failure"),
            func.count()
            .filter(
                DLQMessageORM.status == "pending",
                DLQMessageORM.permanent_failure == False,  # noqa: E712
                DLQMessageORM.retry_count < DLQ_MAX_RETRY_COUNT,
            )
            .label("retryable"),
        ).select_from(DLQMessageORM)

        result = await session.execute(stmt)
        row = result.one()

        return {
            "total": row.total,
            "pending": row.pending,
            "retried": row.retried,
            "discarded": row.discarded,
            "permanent_failure": row.permanent_failure,
            "retryable": row.retryable,
        }
