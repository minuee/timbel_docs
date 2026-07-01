"""Chunk Worker -- aicm.document.parsed 소비 -> 청킹 실행 -> aicm.document.chunked 발행."""

from __future__ import annotations

import time
from uuid import uuid4

from src.common.constants import TOPIC_DOCUMENT_CHUNKED, TOPIC_DOCUMENT_FAILED
from src.common.logging import get_logger
from src.pipeline.chunkers.semantic import SemanticChunker
from src.pipeline.models.document import (
    ChunkObject,
    ChunkStrategy,
    ProcessingConfig,
)
from src.pipeline.models.events import DocumentChunkedEvent, DocumentParsedEvent
from src.pipeline.models.parse_result import ParseResult
from src.pipeline.parsers.router import detect_format, select_parser

log = get_logger(__name__)


async def handle_document_parsed(
    event: DocumentParsedEvent,
    producer: object,
    config: ProcessingConfig | None = None,
) -> None:
    """파싱 완료 이벤트를 처리한다.

    1. 파싱 결과 재로드 (파일에서 다시 파싱 -- 향후 중간 저장소 연동)
    2. 청킹 전략 선택
    3. 청킹 실행
    4. aicm.document.chunked 이벤트 발행

    Parameters
    ----------
    event : DocumentParsedEvent
    producer : Kafka producer
    config : 처리 설정 오버라이드
    """
    start = time.monotonic()

    # 제어 신호 확인 (취소/일시정지)
    from src.pipeline.services.status_updater import get_status_updater

    status_updater = get_status_updater()
    signal = await status_updater.check_control_signal(event.document_id)
    if signal == "cancel":
        log.info("pipeline_cancelled", document_id=str(event.document_id))
        await status_updater.mark_failed(event.document_id, "chunking", "사용자에 의해 취소됨")
        return
    if signal == "pause":
        log.info("pipeline_paused", document_id=str(event.document_id))
        return

    log.info(
        "chunk_worker_start",
        document_id=str(event.document_id),
        difficulty=event.difficulty.value,
    )

    # DB 상태 업데이트 (청킹 시작)
    await status_updater.mark_chunking_start(event.document_id)

    try:
        # 1) 파싱 결과 재로드
        # 향후: Redis/S3 캐시에서 ParseResult 를 직접 로드
        detected_format = detect_format(event.source_path)
        parser = select_parser(detected_format, event.source_path)
        parse_result: ParseResult = await parser.parse()

        # 2) 청킹 설정
        proc_config = config or ProcessingConfig()

        # 3) 청킹 실행
        chunker = SemanticChunker(proc_config)
        chunks: list[ChunkObject] = await chunker.chunk(
            parse_result.pages,
            source_file_path=parse_result.source_file_path,
            source_file_url=f"/repos/{event.repository_id}/docs/{event.document_id}",
            document_id=str(event.document_id),
        )

        # 평균 토큰 수 계산
        avg_tokens = (
            sum(c.token_count for c in chunks) / len(chunks) if chunks else 0.0
        )

        # 주요 전략 결정
        strategy_used = ChunkStrategy.SEMANTIC

        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info(
            "chunk_worker_complete",
            document_id=str(event.document_id),
            chunk_count=len(chunks),
            avg_tokens=round(avg_tokens, 1),
            elapsed_ms=elapsed_ms,
        )

        # 4) 결과 이벤트 발행
        chunked_event = DocumentChunkedEvent(
            event_id=uuid4(),
            document_id=event.document_id,
            tenant_id=event.tenant_id,
            repository_id=event.repository_id,
            chunk_count=len(chunks),
            strategy_used=strategy_used,
            avg_token_count=round(avg_tokens, 1),
            source_path=event.source_path,
        )

        await _produce_event(producer, TOPIC_DOCUMENT_CHUNKED, chunked_event)

        # DB 상태 업데이트 (청킹 완료)
        await status_updater.mark_chunking_complete(
            document_id=event.document_id,
            chunk_count=len(chunks),
            strategy=strategy_used.value,
        )

    except Exception as exc:
        log.error(
            "chunk_worker_failed",
            document_id=str(event.document_id),
            error=str(exc),
        )
        await status_updater.mark_failed(event.document_id, "chunking", str(exc))
        await _produce_failure(producer, event.document_id, "chunking", str(exc))
        raise


async def _produce_event(producer: object, topic: str, event: object) -> None:
    """Kafka 이벤트를 발행한다."""
    try:
        from aiokafka import AIOKafkaProducer

        if isinstance(producer, AIOKafkaProducer):
            value = event.model_dump_json().encode("utf-8")  # type: ignore[union-attr]
            await producer.send_and_wait(topic, value=value)
            log.info("event_produced", topic=topic)
    except ImportError:
        log.warning("aiokafka_not_available_event_skipped", topic=topic)


async def _produce_failure(
    producer: object,
    document_id: object,
    stage: str,
    error: str,
) -> None:
    """실패 이벤트를 발행한다."""
    import json

    try:
        from aiokafka import AIOKafkaProducer

        if isinstance(producer, AIOKafkaProducer):
            payload = json.dumps(
                {
                    "document_id": str(document_id),
                    "stage": stage,
                    "error": error,
                }
            ).encode("utf-8")
            await producer.send_and_wait(TOPIC_DOCUMENT_FAILED, value=payload)
    except ImportError:
        log.warning("aiokafka_not_available_failure_event_skipped")
