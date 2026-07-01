"""DLQ part_blocked 조건부 차단 — split_job_starvation 계열만."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.common.constants import TOPIC_DOCUMENT_PART_BLOCKED
from src.pipeline.workers.dlq_handler import DLQHandler


@pytest.mark.asyncio
async def test_part_blocked_split_job_not_found_blocked():
    """part_blocked + 'Split job not found' 에러 → redelivery skip + failed 마킹."""
    producer = AsyncMock()
    handler = DLQHandler(producer=producer)
    handler._mark_doc_failed_with_summary = AsyncMock()

    msg = MagicMock(
        original_topic=TOPIC_DOCUMENT_PART_BLOCKED,
        error="Split job not found: abc-123",
        document_id=str(uuid4()),
    )
    await handler.schedule_retry(msg)

    handler._mark_doc_failed_with_summary.assert_awaited_once()
    # redelivery (Kafka send) 안 함
    producer.send_and_wait.assert_not_called()


@pytest.mark.asyncio
async def test_part_blocked_transient_db_error_redelivered():
    """part_blocked + 다른 에러 (transient DB) → 기존 redelivery 유지 (block 없음)."""
    producer = AsyncMock()
    handler = DLQHandler(producer=producer)
    handler._mark_doc_failed_with_summary = AsyncMock()

    msg = MagicMock(
        original_topic=TOPIC_DOCUMENT_PART_BLOCKED,
        error="DB connection timeout",
        document_id=str(uuid4()),
    )
    await handler.schedule_retry(msg)

    handler._mark_doc_failed_with_summary.assert_not_called()


@pytest.mark.asyncio
async def test_other_topic_not_affected():
    """part_blocked 외 topic 은 차단 로직 영향 0."""
    producer = AsyncMock()
    handler = DLQHandler(producer=producer)
    handler._mark_doc_failed_with_summary = AsyncMock()

    msg = MagicMock(
        original_topic="aicm.document.parsed",
        error="Split job not found",  # 같은 에러여도 topic 다르면 영향 X
        document_id=str(uuid4()),
    )
    await handler.schedule_retry(msg)

    handler._mark_doc_failed_with_summary.assert_not_called()
