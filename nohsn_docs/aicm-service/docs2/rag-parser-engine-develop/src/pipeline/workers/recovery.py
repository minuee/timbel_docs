"""파이프라인 워커 시작 시 중단된 문서 자동 복구.

워커가 재시작되거나 장애로 중단되면 ``status='processing'`` 인 문서가 DB에 남는데,
해당 문서는 Kafka 큐에 이벤트가 없어 영원히 멈춘다.

이 모듈은 컨슈머 루프 시작 **직전**에 한 번 실행되어:

1. ``status='processing'`` 이고 ``updated_at`` 이 10분 이상 경과한 문서를 DB에서 스캔
2. ``processing_meta.stages_completed`` 배열의 마지막 완료 단계를 기준으로 Kafka 이벤트를 재발행
3. ``processing_meta.auto_recover_count`` 를 누적하고 3회 이상이면 ``status='failed'`` 로 전환

안전장치:
- DB 연결 실패 시 복구를 skip 하고 경고만 남김 (워커 시작을 차단하지 않음)
- ``updated_at`` 10분 이상 경과한 문서만 대상 (다른 워커가 처리 중인 문서 제외)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from src.common.constants import (
    DOC_STATUS_FAILED,
    DOC_STATUS_PENDING_REVIEW,
    DOC_STATUS_PROCESSING,
    TOPIC_DOCUMENT_BLOCKED,
    TOPIC_DOCUMENT_PARSED,
    TOPIC_DOCUMENT_UPLOADED,
)
from src.common.logging import get_logger

log = get_logger(__name__)

# 복구 대상 판별: updated_at 이 이 시간(분) 이상 경과한 문서만
_STALE_THRESHOLD_MINUTES = 10

# 자동 복구 최대 시도 횟수 — 초과 시 failed 로 전환
_MAX_AUTO_RECOVER_COUNT = 3


async def recover_stale_documents(producer: Any) -> int:
    """시작 시 중단된 문서를 감지하고 마지막 완료 단계부터 재개한다.

    Parameters
    ----------
    producer : AIOKafkaProducer
        Kafka producer 인스턴스. 이벤트 재발행에 사용한다.

    Returns
    -------
    int
        복구가 시도된(이벤트 재발행 또는 failed 전환) 문서 수.
        DB 연결 실패 등으로 복구 자체를 skip 하면 0 을 반환한다.
    """
    log.info("recovery_scan_start")

    try:
        from sqlalchemy import text

        from src.core.database import async_session_factory
    except ImportError:
        log.warning("recovery_skip_database_not_available")
        return 0

    try:
        async with async_session_factory() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=_STALE_THRESHOLD_MINUTES)

            # documents 스키마에는 tenant_id 가 없고 repositories 를 거쳐 조회해야 함.
            result = await session.execute(
                text(
                    "SELECT d.id, r.tenant_id, d.repository_id, d.source_file, d.source_format, "
                    "       d.processing_meta, d.updated_at "
                    "FROM documents d "
                    "JOIN repositories r ON r.id = d.repository_id "
                    "WHERE d.status = :status "
                    "  AND d.updated_at < :cutoff "
                    "ORDER BY d.updated_at ASC"
                ),
                {"status": DOC_STATUS_PROCESSING, "cutoff": cutoff},
            )
            rows = result.fetchall()

        if not rows:
            log.info("recovery_scan_complete", stale_count=0)
            return 0

        log.info("recovery_stale_documents_found", stale_count=len(rows))

        recovered = 0
        for row in rows:
            doc_id = str(row[0])
            tenant_id = str(row[1])
            repository_id = str(row[2])
            source_file = row[3] or ""
            source_format = row[4] or "unknown"
            meta = row[5] or {}
            updated_at = row[6]

            try:
                recovered += await _recover_single_document(
                    session_factory=async_session_factory,
                    producer=producer,
                    doc_id=doc_id,
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    source_file=source_file,
                    source_format=source_format,
                    meta=meta,
                    updated_at=updated_at,
                )
            except Exception as exc:
                log.error(
                    "recovery_document_error",
                    document_id=doc_id,
                    error=str(exc),
                )

        log.info("recovery_scan_complete", stale_count=len(rows), recovered=recovered)
        return recovered

    except Exception as exc:
        log.warning(
            "recovery_scan_failed",
            error=str(exc),
            hint="워커 시작은 계속 진행됩니다.",
        )
        return 0


async def _recover_single_document(
    *,
    session_factory: Any,
    producer: Any,
    doc_id: str,
    tenant_id: str,
    repository_id: str,
    source_file: str,
    source_format: str,
    meta: dict,
    updated_at: Any,
) -> int:
    """단일 문서의 복구를 시도한다.

    Returns 1 if an action was taken (re-publish or mark failed), 0 otherwise.
    """
    from sqlalchemy import text

    auto_recover_count: int = meta.get("auto_recover_count", 0) + 1

    log.info(
        "recovery_document_start",
        document_id=doc_id,
        auto_recover_count=auto_recover_count,
        updated_at=str(updated_at),
    )

    # ------------------------------------------------------------------
    # 안전장치: 복구 횟수 초과 → failed 전환
    # ------------------------------------------------------------------
    if auto_recover_count > _MAX_AUTO_RECOVER_COUNT:
        log.warning(
            "recovery_max_attempts_exceeded",
            document_id=doc_id,
            auto_recover_count=auto_recover_count,
            action="marking_as_failed",
        )
        async with session_factory() as session:
            patch = json.dumps({
                "auto_recover_count": auto_recover_count,
                "auto_recover_failed_at": time.time(),
                "error_message": (
                    f"자동 복구 최대 시도 횟수({_MAX_AUTO_RECOVER_COUNT})를 초과하여 "
                    "처리를 중단합니다."
                ),
            })
            await session.execute(
                text(
                    "UPDATE documents "
                    "SET status = :status, "
                    "    processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb) "
                    "WHERE id = :did"
                ),
                {"did": doc_id, "status": DOC_STATUS_FAILED, "patch": patch},
            )
            await session.commit()
        return 1

    # ------------------------------------------------------------------
    # stages_completed 에서 마지막 완료 단계 결정
    # ------------------------------------------------------------------
    stages_completed: list[dict] = meta.get("stages_completed", [])
    last_stage = stages_completed[-1]["name"] if stages_completed else None

    # ------------------------------------------------------------------
    # 단계별 복구 로직
    # ------------------------------------------------------------------
    topic: str | None = None
    event_data: dict | None = None
    action_description: str = ""

    if last_stage == "embedding":
        # 임베딩까지 완료 → pending_review 로 전환 (엣지 케이스)
        log.info(
            "recovery_edge_case_embedding_complete",
            document_id=doc_id,
            action="transition_to_pending_review",
        )
        async with session_factory() as session:
            patch = json.dumps({
                "auto_recover_count": auto_recover_count,
                "auto_recovered_at": time.time(),
                "auto_recover_action": "status_transition_to_pending_review",
            })
            await session.execute(
                text(
                    "UPDATE documents "
                    "SET status = :status, "
                    "    processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb) "
                    "WHERE id = :did"
                ),
                {"did": doc_id, "status": DOC_STATUS_PENDING_REVIEW, "patch": patch},
            )
            await session.commit()

        log.info(
            "recovery_document_done",
            document_id=doc_id,
            action="status_transition_to_pending_review",
            topic="N/A",
        )
        return 1

    elif last_stage == "blocking":
        # 블로킹 완료 → aicm.document.blocked 재발행 (embed 부터 재개)
        topic = TOPIC_DOCUMENT_BLOCKED
        event_data = {
            "event_id": str(uuid4()),
            "document_id": doc_id,
            "tenant_id": tenant_id,
            "repository_id": repository_id,
            "block_count": meta.get("block_count", 0),
            "block_types": meta.get("block_types", {}),
            "source_path": source_file,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        action_description = "republish_blocked_for_embedding"

    elif last_stage == "parsing":
        # 파싱 완료 → aicm.document.parsed 재발행 (block 부터 재개)
        topic = TOPIC_DOCUMENT_PARSED
        event_data = {
            "event_id": str(uuid4()),
            "document_id": doc_id,
            "tenant_id": tenant_id,
            "repository_id": repository_id,
            "difficulty": meta.get("difficulty", "low"),
            "page_count": meta.get("page_count", 0),
            "table_count": meta.get("table_count", 0),
            "image_count": meta.get("image_count", 0),
            "raw_text_length": meta.get("raw_text_length", 0),
            "source_path": source_file,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        action_description = "republish_parsed_for_blocking"

    else:
        # 완료 단계 없음 → aicm.document.uploaded 재발행 (처음부터)
        topic = TOPIC_DOCUMENT_UPLOADED
        event_data = {
            "event_id": str(uuid4()),
            "document_id": doc_id,
            "tenant_id": tenant_id,
            "repository_id": repository_id,
            "source_format": source_format,
            "source_path": source_file,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        action_description = "republish_uploaded_for_full_reprocess"

    # ------------------------------------------------------------------
    # DB에 auto_recover_count 업데이트
    # ------------------------------------------------------------------
    async with session_factory() as session:
        patch = json.dumps({
            "auto_recover_count": auto_recover_count,
            "auto_recovered_at": time.time(),
            "auto_recover_action": action_description,
            "auto_recover_last_stage": last_stage,
        })
        await session.execute(
            text(
                "UPDATE documents "
                "SET processing_meta = COALESCE(processing_meta, '{}') || CAST(:patch AS jsonb) "
                "WHERE id = :did"
            ),
            {"did": doc_id, "patch": patch},
        )
        await session.commit()

    # ------------------------------------------------------------------
    # Kafka 이벤트 재발행
    # ------------------------------------------------------------------
    if producer is not None and topic and event_data is not None:
        await producer.send_and_wait(
            topic,
            value=json.dumps(event_data).encode("utf-8"),
        )

    log.info(
        "recovery_document_done",
        document_id=doc_id,
        action=action_description,
        topic=topic,
        last_completed_stage=last_stage or "none",
        auto_recover_count=auto_recover_count,
    )
    return 1
