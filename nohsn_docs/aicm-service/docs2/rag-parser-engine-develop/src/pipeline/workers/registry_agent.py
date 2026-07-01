"""Agent worker registry — Lucas 풀제품 전용 (Phase 1 T1.5).

reminder_worker 등 agent_framework 의존 worker 를 모은 곳.
Lucas-KMS 단독 배포 (`LUCAS_PRODUCT=kms`) 환경에서는 본 모듈을 *import 하지
않는다* — agent_framework 패키지가 미포함이라도 KMS 가 안전 기동되도록.

Phase 3 packaging 단계에서 본 모듈 및 reminder_worker 는 lucas-agent
패키지로 이동 예정. 현 단계는 dynamic gate.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from src.common.logging import get_logger

log = get_logger(__name__)


AGENT_WORKER_NAMES: tuple[str, ...] = ("reminder_worker",)


def list_workers() -> tuple[str, ...]:
    return AGENT_WORKER_NAMES


def start_background_tasks(
    shutdown_event: asyncio.Event,
) -> list[asyncio.Task]:
    """Agent 전용 백그라운드 태스크 생성.

    현재는 reminder_worker (1분 주기 polling) 하나. import 실패 시
    (agent_framework 미포함 환경 = Lucas-KMS) graceful 로그 후 빈 리스트
    반환 — 호출 측은 본 모듈을 import 한 이상 agent worker 가 의도된 것으로
    보고, import 단계 실패도 별도 로그를 남긴다.
    """
    tasks: list[asyncio.Task] = []
    try:
        from src.pipeline.workers.reminder_worker import _run_loop as _reminder_run
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "reminder_worker_import_failed",
            error=str(exc),
            hint="agent_framework 미포함 — Lucas-KMS 환경에서 정상",
        )
        return tasks

    try:
        task = asyncio.create_task(
            _reminder_run(shutdown_event),
            name="reminder-worker",
        )
        tasks.append(task)
        log.info("reminder_worker_task_created")
    except Exception as exc:  # noqa: BLE001
        log.warning("reminder_worker_start_failed", error=str(exc))

    return tasks
