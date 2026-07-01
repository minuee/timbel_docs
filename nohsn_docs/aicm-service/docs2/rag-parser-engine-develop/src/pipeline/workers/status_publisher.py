"""파이프라인 진행 상태를 Redis Pub/Sub으로 발행하는 헬퍼.

WebSocket 엔드포인트가 이 채널을 구독하여 프론트엔드에 실시간 전달한다.
채널 형식: aicm:upload_progress:{document_id}
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

from src.common.logging import get_logger

log = get_logger(__name__)

# Redis 클라이언트 싱글톤
_redis_client: Any | None = None


async def _get_redis() -> Any:
    """Redis 클라이언트를 반환한다 (lazy init)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis

        from src.common.config import settings

        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        return _redis_client
    except Exception as exc:
        log.debug("redis_client_init_failed", error=str(exc))
        return None


async def publish_progress(
    document_id: UUID | str,
    stage: str,
    progress: int,
    message: str,
    detail: str = "",
) -> None:
    """파이프라인 진행 상태를 Redis Pub/Sub으로 발행한다.

    Parameters
    ----------
    document_id : UUID | str
        대상 문서 ID
    stage : str
        현재 단계 (parsing, blocking, embedding, indexing, completed, failed)
    progress : int
        해당 단계 내 진행률 (0-100)
    message : str
        사용자에게 표시할 메시지
    detail : str
        상세 로그 (선택)
    """
    try:
        redis = await _get_redis()
        if redis is None:
            return

        channel = f"aicm:upload_progress:{document_id}"
        payload = json.dumps(
            {
                "stage": stage,
                "progress": max(0, min(100, progress)),
                "message": message,
                "detail": detail,
                "timestamp": time.time(),
            },
            ensure_ascii=False,
        )
        await redis.publish(channel, payload)
        log.debug(
            "progress_published",
            document_id=str(document_id),
            stage=stage,
            progress=progress,
        )
    except Exception as exc:
        # 진행 상태 발행 실패는 파이프라인을 중단시키면 안 됨
        log.debug("progress_publish_failed", error=str(exc))


async def publish_stage_start(document_id: UUID | str, stage: str) -> None:
    """단계 시작 이벤트 발행."""
    stage_labels = {
        "parsing": "파싱 시작",
        "blocking": "블럭 세그멘테이션 시작",
        "embedding": "임베딩 시작",
        "indexing": "인덱싱 시작",
    }
    await publish_progress(
        document_id=document_id,
        stage=stage,
        progress=0,
        message=stage_labels.get(stage, f"{stage} 시작"),
    )


async def publish_stage_complete(document_id: UUID | str, stage: str) -> None:
    """단계 완료 이벤트 발행."""
    stage_labels = {
        "parsing": "파싱 완료",
        "blocking": "블럭 세그멘테이션 완료",
        "embedding": "임베딩 완료",
        "indexing": "인덱싱 완료",
    }
    await publish_progress(
        document_id=document_id,
        stage=stage,
        progress=100,
        message=stage_labels.get(stage, f"{stage} 완료"),
    )


async def publish_pipeline_complete(document_id: UUID | str) -> None:
    """파이프라인 전체 완료 이벤트 발행."""
    await publish_progress(
        document_id=document_id,
        stage="completed",
        progress=100,
        message="문서 처리가 완료되었습니다. 검색 가능 상태입니다.",
    )


async def publish_pipeline_failed(
    document_id: UUID | str,
    stage: str,
    error: str,
) -> None:
    """파이프라인 실패 이벤트 발행."""
    await publish_progress(
        document_id=document_id,
        stage="failed",
        progress=0,
        message=f"{stage} 단계에서 오류 발생",
        detail=error[:300],
    )
