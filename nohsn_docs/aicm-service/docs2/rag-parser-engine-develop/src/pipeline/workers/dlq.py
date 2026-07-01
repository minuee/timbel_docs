"""Dead Letter Queue (DLQ) 핸들러 -- Phase 3 Production Hardening.

실패한 Kafka 메시지를 최대 3회 재시도한 후 ``aicm.document.dlq`` 토픽으로 전달한다.
지수 백오프: 5^n 초 (5s, 25s, 125s).

DLQ 메시지에는 원본 메시지, 에러 상세, 재시도 횟수, 타임스탬프가 포함된다.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.common.config import settings
from src.common.constants import (
    TOPIC_DOCUMENT_ALERT,
    TOPIC_DOCUMENT_DLQ,
    TOPIC_DOCUMENT_PART_BLOCKED,
)
from src.common.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

TOPIC_DLQ = TOPIC_DOCUMENT_DLQ
MAX_RETRIES = 3
BACKOFF_BASE = 5  # 5^1=5s, 5^2=25s, 5^3=125s

# spec §3.4 — split_job_starvation 계열만 차단. 다른 transient (DB 장애 등) 는 유지.
_DLQ_BLOCK_PATTERNS = (
    "Split job not found",
    "split_job_starvation_suspected",
)


# ---------------------------------------------------------------------------
# DLQ 메시지 모델
# ---------------------------------------------------------------------------

class DLQMessage(BaseModel):
    """DLQ 에 저장되는 메시지."""

    msg_id: UUID = Field(default_factory=uuid4)
    original_topic: str
    original_value: str  # base64 또는 JSON 문자열
    error_message: str
    error_traceback: str = ""
    retry_count: int = 0
    first_failure_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_failure_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    original_offset: int = 0
    original_partition: int = 0
    status: str = "pending"  # pending / retried / discarded


# ---------------------------------------------------------------------------
# DLQ 핸들러
# ---------------------------------------------------------------------------

class DLQHandler:
    """Dead Letter Queue 핸들러.

    Parameters
    ----------
    producer : aiokafka.AIOKafkaProducer
        Kafka producer 인스턴스
    max_retries : int
        최대 재시도 횟수 (기본 3)
    backoff_base : int
        지수 백오프 기반값 (기본 5)
    """

    def __init__(
        self,
        producer: Any,
        max_retries: int = MAX_RETRIES,
        backoff_base: int = BACKOFF_BASE,
    ) -> None:
        self._producer = producer
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        # 인메모리 DLQ 메시지 저장 (Phase 3: DB 이관 전 임시)
        self._dlq_store: dict[str, DLQMessage] = {}

    @property
    def dlq_store(self) -> dict[str, DLQMessage]:
        """인메모리 DLQ 저장소 (읽기 전용 접근)."""
        return self._dlq_store

    async def handle_with_retry(
        self,
        topic: str,
        value: bytes,
        offset: int,
        partition: int,
        dispatch_fn: Any,
    ) -> bool:
        """메시지를 재시도 로직과 함께 처리한다.

        Parameters
        ----------
        topic : str
            원본 Kafka 토픽
        value : bytes
            메시지 값
        offset : int
            Kafka 오프셋
        partition : int
            Kafka 파티션
        dispatch_fn : Callable
            실제 디스패치 함수 (topic, value, producer) -> None

        Returns
        -------
        bool
            처리 성공 여부
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                await dispatch_fn(topic, value, self._producer)
                return True
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "message_processing_retry",
                    topic=topic,
                    offset=offset,
                    attempt=attempt,
                    max_retries=self._max_retries,
                    error=str(exc),
                )

                if attempt < self._max_retries:
                    backoff = self._backoff_base ** attempt
                    log.info(
                        "retry_backoff",
                        topic=topic,
                        offset=offset,
                        backoff_seconds=backoff,
                        next_attempt=attempt + 1,
                    )
                    await asyncio.sleep(backoff)

        # 모든 재시도 소진 -> DLQ 전송
        assert last_exc is not None
        await self._send_to_dlq(
            topic=topic,
            value=value,
            offset=offset,
            partition=partition,
            error=last_exc,
        )
        return False

    async def _persist_to_db(self, dlq_msg: DLQMessage) -> None:
        """DLQ 메시지를 DB에 영속화한다 (실패 시 로그만)."""
        try:
            from src.core.database import async_session_factory
            from src.core.models.dlq_message import DLQMessageORM

            async with async_session_factory() as session:
                orm = DLQMessageORM(
                    id=dlq_msg.msg_id,
                    topic=dlq_msg.original_topic,
                    offset=dlq_msg.original_offset,
                    partition=dlq_msg.original_partition,
                    payload=dlq_msg.original_value,
                    error=dlq_msg.error_message,
                    error_traceback=dlq_msg.error_traceback,
                    retry_count=dlq_msg.retry_count,
                    status=dlq_msg.status,
                )
                session.add(orm)
                await session.commit()
                log.info("dlq_message_persisted_to_db", msg_id=str(dlq_msg.msg_id))
        except Exception as exc:
            log.warning("dlq_db_persist_failed", msg_id=str(dlq_msg.msg_id), error=str(exc))

    async def _send_to_dlq(
        self,
        topic: str,
        value: bytes,
        offset: int,
        partition: int,
        error: Exception,
    ) -> None:
        """실패한 메시지를 DLQ 토픽으로 전송한다."""
        now = datetime.now(timezone.utc)
        dlq_msg = DLQMessage(
            original_topic=topic,
            original_value=value.decode("utf-8", errors="replace"),
            error_message=str(error),
            error_traceback=traceback.format_exc(),
            retry_count=self._max_retries,
            first_failure_at=now,
            last_failure_at=now,
            original_offset=offset,
            original_partition=partition,
            status="pending",
        )

        # 인메모리 저장 (호환성 유지)
        self._dlq_store[str(dlq_msg.msg_id)] = dlq_msg

        # DB에 영속화
        await self._persist_to_db(dlq_msg)

        # Kafka DLQ 토픽으로 발행
        try:
            from aiokafka import AIOKafkaProducer

            if isinstance(self._producer, AIOKafkaProducer):
                payload = dlq_msg.model_dump_json().encode("utf-8")
                await self._producer.send_and_wait(TOPIC_DLQ, value=payload)
                log.info(
                    "message_sent_to_dlq",
                    msg_id=str(dlq_msg.msg_id),
                    original_topic=topic,
                    offset=offset,
                    error=str(error),
                )
            else:
                log.warning("producer_not_aiokafka_dlq_stored_in_memory_and_db")
        except ImportError:
            log.warning("aiokafka_not_installed_dlq_stored_in_memory_and_db")
        except Exception as exc:
            log.error(
                "dlq_send_failed",
                msg_id=str(dlq_msg.msg_id),
                error=str(exc),
            )

        # 갭1 — DLQ 확정 시 아직 processing 인 문서를 failed 로 전환 (단일 초크포인트).
        await self._mark_processing_doc_failed_on_dlq(value, topic, error)

    async def _mark_processing_doc_failed_on_dlq(
        self, value: bytes, topic: str, error: Exception
    ) -> None:
        """DLQ 확정 메시지의 문서가 아직 processing 이면 failed 로 전환한다 (best-effort).

        split/merge/classify/lint 워커는 자체 mark_failed 를 호출하지 않아, 이 단계에서
        실패하면 문서가 'processing' 에 영구 정체된다 (사용자에겐 무한 스피너). DLQ 확정은
        재시도 소진 후의 단일 종착점이므로, 여기서 단계 무관하게 문서를 failed 로 표시한다.

        parse/block/chunk/embed 는 이미 자체 핸들러에서 failed 로 전환했으므로
        status != 'processing' 이라 건너뛴다 (정밀 failed_stage 보존). active /
        pending_review / archived 등 비-processing 상태도 건드리지 않는다 (옛 잔재 메시지 보호).
        """
        try:
            import json as _json
            import uuid as _uuid

            try:
                parsed = _json.loads(value.decode("utf-8", errors="replace")) or {}
                doc_id = parsed.get("document_id")
            except Exception:  # noqa: BLE001 — 비-JSON / 스키마 외 메시지는 무시.
                return
            if not doc_id:
                return
            try:
                doc_uuid = _uuid.UUID(str(doc_id))
            except (ValueError, AttributeError, TypeError):
                return

            from src.api.middleware.rls_context import (
                RLSContext,
                reset_rls_context,
                set_rls_context,
            )
            from src.core.database import async_session_factory
            from src.core.services.document_service import DocumentService

            # worker context — system scope (BYPASSRLS).
            token = set_rls_context(
                RLSContext(agent_id=None, scope="system", tenant_id=None)
            )
            try:
                async with async_session_factory() as db:
                    svc = DocumentService(db)
                    try:
                        doc = await svc.get_by_id(doc_uuid)
                    except Exception:  # noqa: BLE001
                        return
                    # processing 만 대상 — 이미 failed 이거나 보호 상태는 건드리지 않음.
                    if getattr(doc, "status", None) != "processing":
                        return
                    await svc.transition_status(doc_uuid, target_status="failed")
                    await svc.update_processing_meta(
                        doc_uuid,
                        processing_meta={
                            "failed_stage": "pipeline_dlq",
                            "failed_topic": topic,
                            "error": str(error)[:500],
                            "error_summary": "moved_to_dlq_after_retries",
                        },
                    )
                    log.warning(
                        "dlq_marked_processing_doc_failed",
                        doc_id=str(doc_uuid),
                        topic=topic,
                    )
            finally:
                reset_rls_context(token)
        except Exception as exc:  # noqa: BLE001 — best-effort, DLQ 전송을 막지 않는다.
            log.warning(
                "dlq_mark_processing_doc_failed_error",
                topic=topic,
                error=str(exc),
            )

    async def _update_db_status(self, msg_id: str, status: str) -> None:
        """DB의 DLQ 메시지 상태를 업데이트한다."""
        try:
            from sqlalchemy import update

            from src.core.database import async_session_factory
            from src.core.models.dlq_message import DLQMessageORM

            async with async_session_factory() as session:
                stmt = (
                    update(DLQMessageORM)
                    .where(DLQMessageORM.id == UUID(msg_id))
                    .values(status=status)
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as exc:
            log.warning("dlq_db_status_update_failed", msg_id=msg_id, error=str(exc))

    async def retry_message(self, msg_id: str) -> bool:
        """DLQ 메시지를 원본 토픽으로 재발행한다.

        Parameters
        ----------
        msg_id : str
            DLQ 메시지 ID

        Returns
        -------
        bool
            재발행 성공 여부
        """
        dlq_msg = self._dlq_store.get(msg_id)
        if dlq_msg is None:
            log.warning("dlq_message_not_found", msg_id=msg_id)
            return False

        try:
            from aiokafka import AIOKafkaProducer

            if isinstance(self._producer, AIOKafkaProducer):
                value = dlq_msg.original_value.encode("utf-8")
                await self._producer.send_and_wait(
                    dlq_msg.original_topic, value=value
                )
                dlq_msg.status = "retried"
                dlq_msg.last_failure_at = datetime.now(timezone.utc)
                await self._update_db_status(msg_id, "retried")
                log.info(
                    "dlq_message_retried",
                    msg_id=msg_id,
                    original_topic=dlq_msg.original_topic,
                )
                return True
            else:
                log.warning("producer_not_aiokafka_retry_skipped")
                return False
        except ImportError:
            log.warning("aiokafka_not_installed_retry_skipped")
            return False
        except Exception as exc:
            log.error("dlq_retry_failed", msg_id=msg_id, error=str(exc))
            return False

    def discard_message(self, msg_id: str) -> bool:
        """DLQ 메시지를 폐기(discard) 처리한다.

        Parameters
        ----------
        msg_id : str
            DLQ 메시지 ID

        Returns
        -------
        bool
            폐기 성공 여부
        """
        dlq_msg = self._dlq_store.get(msg_id)
        if dlq_msg is None:
            log.warning("dlq_message_not_found_for_discard", msg_id=msg_id)
            return False

        dlq_msg.status = "discarded"
        # fire-and-forget DB 업데이트
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._update_db_status(msg_id, "discarded"))
            else:
                asyncio.run(self._update_db_status(msg_id, "discarded"))
        except Exception:
            pass
        log.info("dlq_message_discarded", msg_id=msg_id)
        return True

    def list_messages(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DLQMessage]:
        """DLQ 메시지 목록을 조회한다.

        Parameters
        ----------
        status : str | None
            필터링할 상태 (pending / retried / discarded)
        limit : int
            페이지 크기
        offset : int
            오프셋

        Returns
        -------
        list[DLQMessage]
        """
        messages = list(self._dlq_store.values())
        if status:
            messages = [m for m in messages if m.status == status]
        # 최신 순 정렬
        messages.sort(key=lambda m: m.last_failure_at, reverse=True)
        return messages[offset : offset + limit]

    def get_message(self, msg_id: str) -> Optional[DLQMessage]:
        """특정 DLQ 메시지를 조회한다."""
        return self._dlq_store.get(msg_id)

    async def schedule_retry(self, msg: Any) -> None:
        """DLQ scheduler 가 재처리 전 호출하는 진입점.

        spec §3.4 — part_blocked + split_job_starvation 패턴만 redelivery 차단.
        다른 transient (DB timeout, network 등) 는 기존 retry 로 유지 (회복성 보존).

        Parameters
        ----------
        msg : Any
            DLQ ORM 또는 DLQMessage 인스턴스.
            필수 속성: original_topic, error, document_id.
        """
        topic = getattr(msg, "original_topic", None) or ""
        error = getattr(msg, "error", None) or ""

        if topic == TOPIC_DOCUMENT_PART_BLOCKED and any(
            p in error for p in _DLQ_BLOCK_PATTERNS
        ):
            log.info(
                "dlq_part_blocked_redelivery_blocked",
                reason="split_job_starvation_suspected",
                doc_id=getattr(msg, "document_id", None),
                consumer_role="dlq_scheduler",
            )
            await self._mark_doc_failed_with_summary(
                doc_id=str(getattr(msg, "document_id", "") or ""),
                error_summary="split_job_starvation_suspected",
                recommended_action=(
                    "consumer 분리 적용 후 재발 안 함. "
                    "그래도 발생 시 운영팀 연락"
                ),
            )
            return

        # 기존 retry 로직 — DLQ scheduler 의 _republish_message 가 담당.
        # schedule_retry 는 블로킹 분기 전담이므로 통과 시 아무것도 하지 않는다.
        # (실제 republish 는 dlq_scheduler._run_single_scan 에서 수행)

    async def _mark_doc_failed_with_summary(
        self,
        *,
        doc_id: str,
        error_summary: str,
        recommended_action: str,
    ) -> None:
        """spec §3.5 / §3.6 — atomic retry_count 선점 + 자동 1회 retry 또는 alert.

        race window 차단 핵심: ``atomic_inc_retry_count(expected=0)`` 으로 publish
        *전* 에 원자적으로 retry_count 를 0 → 1 로 선점한다. publish 후 worker
        crash 시 retry_count 가 inc 안 되어 무한 auto-retry 가 발생하는 race 를
        제거. CAS 실패 (이미 1+) 시 즉시 영구 failed + alert 경로로 fall through.

        publish 실패 시 retry_count rollback 은 하지 않는다 (best-effort).
        spec §3.6 의도 — 한 단계 실패해도 다음 단계 (status / meta / alert) 는
        각각 try 격리로 진행.
        """
        import uuid as _uuid
        from datetime import datetime as _dt

        from src.api.middleware.rls_context import (
            RLSContext,
            reset_rls_context,
            set_rls_context,
        )
        from src.core.database import async_session_factory
        from src.core.services.document_service import DocumentService

        # worker context — system scope 로 RLS BYPASSRLS role attribute 가 처리.
        token = set_rls_context(
            RLSContext(agent_id=None, scope="system", tenant_id=None)
        )
        try:
            try:
                doc_uuid = _uuid.UUID(doc_id)
            except (ValueError, AttributeError, TypeError) as exc:
                log.error(
                    "dlq_mark_failed_invalid_doc_id",
                    doc_id=doc_id, error=str(exc),
                    consumer_role="dlq_scheduler",
                )
                return

            async with async_session_factory() as db:
                svc = DocumentService(db)

                # T78 (2026-05-18) — status check: archived/pending_review 는
                # 자동 retry 안 함. 사용자가 archive 한 doc 을 storm 으로 reprocess
                # 하지 않도록 보호. 대신 alert 만 (운영자에게 알림).
                try:
                    doc_for_check = await svc.get_by_id(doc_uuid)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "dlq_mark_failed_doc_lookup_failed",
                        doc_id=doc_id, error=str(exc),
                        consumer_role="dlq_scheduler",
                    )
                    return
                _retry_eligible_statuses = ("active", "failed")
                if doc_for_check.status not in _retry_eligible_statuses:
                    log.info(
                        "dlq_auto_retry_skipped_status",
                        doc_id=doc_id,
                        status=doc_for_check.status,
                        error_summary=error_summary,
                        consumer_role="dlq_scheduler",
                    )
                    # alert publish (운영자가 archived doc 의 잔재 메시지 인지).
                    try:
                        payload = json.dumps({
                            "doc_id": doc_id,
                            "error_summary": error_summary,
                            "recommended_action": (
                                f"doc status={doc_for_check.status} — auto retry skip. "
                                "옛 잔재 메시지일 가능성. 운영팀 확인"
                            ),
                            "skipped_reason": "non_retry_eligible_status",
                        }, ensure_ascii=False)
                        await self._producer.send_and_wait(
                            TOPIC_DOCUMENT_ALERT, payload.encode("utf-8"))
                    except Exception:  # noqa: BLE001 — alert best-effort
                        pass
                    return

                # CRITICAL — publish 전 atomic 선점 (race fix).
                new_count = await svc.atomic_inc_retry_count(
                    doc_uuid, expected=0
                )

                # 자동 1회 retry (new_count==1 + 정책 허용).
                if new_count == 1 and settings.PIPELINE_AUTO_RETRY_MAX >= 1:
                    try:
                        from src.api.routers.documents import (
                            _publish_upload_event,
                        )

                        doc = await svc.get_by_id(doc_uuid)
                        await _publish_upload_event(
                            document_id=doc.id,
                            tenant_id=doc.tenant_id,
                            repository_id=doc.repository_id,
                            source_format=doc.source_format or "unknown",
                            source_path=doc.source_file or "",
                        )
                        await svc.update_processing_meta(
                            doc.id,
                            processing_meta={
                                "last_auto_retry_at": _dt.utcnow().isoformat(),
                                "last_auto_retry_reason": error_summary,
                            },
                        )
                        log.info(
                            "dlq_auto_retry_dispatched",
                            doc_id=doc_id,
                            error_summary=error_summary,
                            new_retry_count=new_count,
                            consumer_role="dlq_scheduler",
                        )
                        return
                    except Exception as exc:  # noqa: BLE001
                        log.error(
                            "dlq_auto_retry_failed",
                            doc_id=doc_id,
                            error=str(exc),
                            consumer_role="dlq_scheduler",
                        )
                        # publish 실패 — fall through 로 failed + alert.

                # retry_count >= 1 (CAS 실패) 또는 publish 실패 → 영구 failed + alert.
                try:
                    await svc.transition_status(
                        doc_uuid, target_status="failed"
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "dlq_failed_status_transition_failed",
                        doc_id=doc_id, error=str(exc),
                        consumer_role="dlq_scheduler",
                    )
                try:
                    await svc.update_processing_meta(
                        doc_uuid,
                        processing_meta={
                            "failed_stage": "auto_retry_exhausted",
                            "error": error_summary,
                            "error_summary": error_summary,
                            "recommended_action": recommended_action,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "dlq_failed_meta_update_failed",
                        doc_id=doc_id, error=str(exc),
                        consumer_role="dlq_scheduler",
                    )

                # alert publish (best-effort).
                try:
                    payload = json.dumps({
                        "doc_id": doc_id,
                        "error_summary": error_summary,
                        "recommended_action": recommended_action,
                        "retry_count": new_count if new_count is not None else 1,
                        "timestamp": _dt.utcnow().isoformat(),
                    }).encode("utf-8")
                    await self._producer.send_and_wait(
                        TOPIC_DOCUMENT_ALERT,
                        value=payload,
                    )
                    log.info(
                        "dlq_alert_published",
                        doc_id=doc_id,
                        consumer_role="dlq_scheduler",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "dlq_alert_publish_failed",
                        doc_id=doc_id, error=str(exc),
                        consumer_role="dlq_scheduler",
                    )
        finally:
            reset_rls_context(token)
