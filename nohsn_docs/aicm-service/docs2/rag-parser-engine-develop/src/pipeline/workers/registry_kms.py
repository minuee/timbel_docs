"""KMS worker registry — Lucas-KMS 분리 (Phase 1 T1.5).

KMS 단독 배포에서도 import 가능해야 하는 worker 집합 (chunk / embed / block /
classify 등). agent_framework 의존이 *없는* worker 만 이곳에 등록한다.

dispatch 함수는 main.py 의 supervisor / queue worker 가 부르는 진입점만
얇게 위임한다 — worker 로직은 기존 모듈 그대로 사용하며, 본 모듈은 *어느
worker 를 등록할지* 만 책임진다.

LUCAS_PRODUCT=kms 시 main.py 는 본 모듈만 활성화하고 registry_agent 는 skip.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from src.common.logging import get_logger

log = get_logger(__name__)


# KMS worker 식별자 — 로깅·메트릭에서 참조하는 이름.
# 키워드 enum 이 아니라 "어떤 worker 가 본 registry 에 속하는지" 의 단순 목록.
KMS_WORKER_NAMES: tuple[str, ...] = (
    "chunk_worker",
    "embed_worker",
    "block_worker",
    "classify_worker",
    "parse_worker",
    "split_worker",
    "merge_worker",
    "lint_worker",
    "lifecycle_worker",
    "reprocess_worker",
    "dlq_handler",
    "dlq_scheduler",
)


def list_workers() -> tuple[str, ...]:
    """본 registry 가 책임지는 worker 식별자 목록."""
    return KMS_WORKER_NAMES


def start_background_tasks(
    shutdown_event: asyncio.Event,
    *,
    create_task: Callable[..., asyncio.Task] = asyncio.create_task,
) -> list[asyncio.Task]:
    """KMS 전용 백그라운드 태스크 생성.

    현 단계에서는 main.py 의 기존 dispatch (consumer supervisor + queue worker)
    를 변경하지 않는다 — chunk/embed/block 워커는 supervisor 가 메시지 단위로
    호출하는 dispatch 함수이므로 별도 long-running task 가 필요 없다.

    DLQ scheduler 도 main.py 가 직접 생성하므로 본 함수는 현재 빈 리스트를
    반환한다 (향후 KMS 전용 사이드카가 늘어나면 본 함수에 모은다).
    """
    return []
