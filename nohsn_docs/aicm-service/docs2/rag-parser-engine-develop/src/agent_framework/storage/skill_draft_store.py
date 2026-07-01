"""skill_drafts CRUD — "대화로 스킬 추가" Phase A 저장소.

Task 35 — chat 에서 ``_skill_draft_request`` sentinel 이 발생하면 엔진이
``DraftComposer`` 로 YAML draft 를 만든 뒤 이 저장소에 ``status='pending'``
으로 쌓는다. 관리자는 Phase B UI 에서 검토 후 approve/reject.

schema 는 alembic 025 migration 과 1:1. status 는 아래 4개만 유효:
- ``pending`` : 생성됐지만 아직 검토 전
- ``approved`` : 검토자가 승인 (active skill 로 promote 완료 후)
- ``rejected`` : 검토자가 거절
- ``expired`` : 오래된 draft 자동 만료 (Phase B 운영 정책 확정 후)

API 는 Protocol 스타일: engine 인자를 받는 async 함수. 테스트에서 쉽게 stub.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class SkillDraft:
    """DraftComposer 가 반환 + store 가 persist 하는 값 오브젝트.

    테이블 row 자체와 거의 같지만 identity (id/status/timestamps) 는 비워 두고
    생성 페이로드만 담는다. 꺼낼 때는 dict 로 반환 (API 직렬화 단순화).
    """

    title: str
    yaml_text: str
    rationale: str | None = None


VALID_STATUSES = {"pending", "approved", "rejected", "expired"}


async def create(
    engine: AsyncEngine,
    draft: SkillDraft,
    *,
    account_id: UUID,
    tenant_id: UUID,
    session_id: str | None,
    source_user_message: str,
) -> UUID:
    """Insert a new skill_drafts row with status='pending'.

    Returns the new draft UUID.
    """
    async with engine.begin() as conn:
        r = await conn.execute(
            text(
                """
                INSERT INTO skill_drafts
                  (id, account_id, tenant_id, session_id,
                   source_user_message, draft_yaml, draft_title, rationale,
                   status)
                VALUES
                  (gen_random_uuid(), :aid, :tid, :sid,
                   :src, :yaml, :title, :rationale,
                   'pending')
                RETURNING id
                """
            ),
            {
                "aid": account_id,
                "tid": tenant_id,
                "sid": session_id,
                "src": source_user_message,
                "yaml": draft.yaml_text,
                "title": draft.title,
                "rationale": draft.rationale,
            },
        )
        return r.scalar_one()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """DB row (Row) → plain dict (UUID/datetime → str)."""
    d = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    for k, v in list(d.items()):
        if isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


_SELECT_COLS = (
    "id, account_id, tenant_id, session_id, source_user_message, "
    "draft_yaml, draft_title, rationale, status, "
    "reviewed_by_account_id, reviewed_at, reject_reason, "
    "created_at, updated_at"
)


async def get(engine: AsyncEngine, draft_id: UUID) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(f"SELECT {_SELECT_COLS} FROM skill_drafts WHERE id = :id"),
                {"id": draft_id},
            )
        ).first()
    return _row_to_dict(row) if row else None


async def list_by_account(
    engine: AsyncEngine,
    account_id: UUID,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """account 소유 draft 목록. 최신순 (created_at DESC).

    ``status`` 지정 시 해당 상태만 필터.  Phase B UI 는 기본적으로 pending 만
    보여주되 승인·거절 이력도 탭으로 분리할 수 있도록 null fallback 지원.
    """
    params: dict[str, Any] = {"aid": account_id}
    status_clause = ""
    if status is not None:
        params["st"] = status
        status_clause = "AND status = :st"
    sql = f"""
        SELECT {_SELECT_COLS} FROM skill_drafts
        WHERE account_id = :aid
        {status_clause}
        ORDER BY created_at DESC
    """
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()
    return [_row_to_dict(r) for r in rows]


async def update_status(
    engine: AsyncEngine,
    draft_id: UUID,
    status: str,
    *,
    reviewer_account_id: UUID | None = None,
    reject_reason: str | None = None,
) -> bool:
    """Status 전환. 승인/거절 시 reviewed_at/by 도 같이 갱신.

    ``reject_reason`` 은 status='rejected' 일 때만 의미가 있다 (다른 상태 전환에서
    None 이면 기존 값을 보존하지만, 명시적으로 빈 문자열을 넘기면 그대로 저장됨).
    빈 사유도 사용자가 의도적으로 비웠을 수 있어 None vs '' 구분.

    Returns True 면 1 row 수정됨. 없거나 이미 같은 상태면 False 반환 가능.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; must be one of {sorted(VALID_STATUSES)}"
        )
    # pending 으로의 복귀는 운영 상 금지 — 실수 복구는 row 재생성으로.
    async with engine.begin() as conn:
        r = await conn.execute(
            text(
                """
                UPDATE skill_drafts
                SET status = CAST(:st AS VARCHAR),
                    reviewed_by_account_id = :rid,
                    reviewed_at = CASE
                        WHEN CAST(:st AS VARCHAR) IN ('approved','rejected') THEN NOW()
                        ELSE reviewed_at
                    END,
                    reject_reason = CASE
                        WHEN CAST(:st AS VARCHAR) = 'rejected' THEN :reason
                        ELSE reject_reason
                    END,
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {
                "id": draft_id,
                "st": status,
                "rid": reviewer_account_id,
                "reason": reject_reason,
            },
        )
        return (r.rowcount or 0) > 0


async def delete(engine: AsyncEngine, draft_id: UUID) -> bool:
    """Hard delete — 관리자 cleanup 용. 일반 사용자 흐름에선 호출 금지.

    draft 는 active skill 이 아니라 '검토 대기 중' 의 일회성 산출물이므로 soft
    delete 플로우를 따로 두지 않는다. rejected/expired 상태 자체가 soft delete.
    """
    async with engine.begin() as conn:
        r = await conn.execute(
            text("DELETE FROM skill_drafts WHERE id = :id"), {"id": draft_id}
        )
        return (r.rowcount or 0) > 0
