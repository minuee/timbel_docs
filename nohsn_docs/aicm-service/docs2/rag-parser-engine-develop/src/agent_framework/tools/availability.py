"""schedule.availability + schedule.suggest_slots — Phase 1.5A Task 5.

guest 도 호출 가능 (scope=aggregated_query). raw 일정 정보 노출 X —
yes/no 또는 빈 슬롯 *N개 무작위 추첨* 만.

duration_minutes 미지정 시 default 30 (SOP RAG 가 호출 시 명시).

Schedule ORM 모델 부재 — agent_document_store (documents 테이블) 기반
일정 데이터를 SQLAlchemy text query 로 조회. db.execute(stmt) 인터페이스
유지로 테스트 mock 완전 호환.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent_framework.tools.outcomes import (
    ToolOutcome,
    ToolResult,
    ToolResultMeta,
)

_DEFAULT_DURATION_MINUTES = 30


async def _has_overlap(
    db: AsyncSession,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    target_user_id: UUID | None,
) -> bool:
    """주어진 [start, end] 가 active 일정과 겹치는지.

    documents 테이블 (agent_document_store 기반) 에서 agent_schedule 타입
    문서의 body->>'when' 을 파싱해 겹치는지 확인.
    target_user_id 가 None 이면 tenant 전체 범위.

    테스트에서는 db.execute 가 mock 되므로 실제 SQL 실행 경로와 독립.
    """
    start_iso = start.isoformat()
    end_iso = end.isoformat()

    if target_user_id is not None:
        stmt = text(
            """
            SELECT 1 FROM documents
            WHERE tenant_id = :tenant_id
              AND document_type = 'agent_schedule'
              AND status = 'active'
              AND (body->>'start_at') IS NOT NULL
              AND (body->>'end_at') IS NOT NULL
              AND (body->>'start_at')::timestamptz < :end_dt
              AND (body->>'end_at')::timestamptz > :start_dt
              AND created_by = :user_id
            LIMIT 1
            """
        ).bindparams(
            tenant_id=str(tenant_id),
            start_dt=start_iso,
            end_dt=end_iso,
            user_id=str(target_user_id),
        )
    else:
        stmt = text(
            """
            SELECT 1 FROM documents
            WHERE tenant_id = :tenant_id
              AND document_type = 'agent_schedule'
              AND status = 'active'
              AND (body->>'start_at') IS NOT NULL
              AND (body->>'end_at') IS NOT NULL
              AND (body->>'start_at')::timestamptz < :end_dt
              AND (body->>'end_at')::timestamptz > :start_dt
            LIMIT 1
            """
        ).bindparams(
            tenant_id=str(tenant_id),
            start_dt=start_iso,
            end_dt=end_iso,
        )

    rows = (await db.execute(stmt)).all()
    return len(rows) > 0


async def schedule_availability(
    *,
    db: AsyncSession,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    target_user_id: UUID | None = None,
) -> ToolResult:
    """점 query — 그 시간 가능한지 yes/no.

    raw 일정 정보 노출 X. {"available": true/false} 만.
    """
    has_overlap = await _has_overlap(db, tenant_id, start, end, target_user_id)
    return ToolResult(
        success=True,
        items=[{"available": not has_overlap}],
        summary=("가능한 시간" if not has_overlap else "다른 일정 있음"),
        meta=ToolResultMeta(
            outcome=ToolOutcome.OK,
            reason="",
            kind="domain_empty",
        ),
    )


async def schedule_suggest_slots(
    *,
    db: AsyncSession,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
    duration_minutes: int | None = None,
    target_user_id: UUID | None = None,
    n_suggestions: int = 2,
) -> ToolResult:
    """범위 query — 비어있는 슬롯 N개 무작위 추첨.

    SOP RAG 가 duration_minutes 명시 (시술별 다름). 미명시 시 30 default.
    빈 슬롯 K 발견 → 그 중 *무작위 N 개* 만 노출 (정렬 X — 정보 비공개 강화).
    """
    if duration_minutes is None or duration_minutes <= 0:
        duration_minutes = _DEFAULT_DURATION_MINUTES
    duration = timedelta(minutes=duration_minutes)
    # 슬롯 후보 생성 — start..end 사이 duration_minutes 그리드 (최대 30분 step)
    grid_step = timedelta(minutes=min(duration_minutes, 30))
    candidates = []
    cursor = start
    while cursor + duration <= end:
        candidates.append((cursor, cursor + duration))
        cursor += grid_step

    # 비어있는 후보 추출
    free = []
    for s, e in candidates:
        if not await _has_overlap(db, tenant_id, s, e, target_user_id):
            free.append({"start": s.isoformat(), "end": e.isoformat()})

    if not free:
        return ToolResult(
            success=True,
            items=[],
            summary="해당 기간 빈 슬롯 없음",
            meta=ToolResultMeta(
                outcome=ToolOutcome.SATURATED,
                reason="all_booked",
                kind="domain_empty",
                user_action_required=True,
            ),
        )

    # n_suggestions 개 무작위 추첨 (모든 빈 시간 노출 X)
    if len(free) < n_suggestions:
        return ToolResult(
            success=True,
            items=free,
            summary=f"빈 슬롯 {len(free)}개",
            meta=ToolResultMeta(
                outcome=ToolOutcome.PARTIAL,
                reason="fewer_than_requested",
                kind="domain_empty",
            ),
        )

    sampled = random.sample(free, n_suggestions)
    return ToolResult(
        success=True,
        items=sampled,
        summary=f"빈 슬롯 {n_suggestions}개 추천",
        meta=ToolResultMeta(
            outcome=ToolOutcome.OK,
            reason="",
            kind="domain_empty",
        ),
    )
