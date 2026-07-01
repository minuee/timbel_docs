"""/api/v1/chat/sessions/* — frontend-v2 ChatEngine 호환 세션/메시지 라우터.

frontend 호출:
- ``GET  /api/v1/chat/sessions/latest``      — 가장 최근 세션 + 메시지
- ``POST /api/v1/chat/sessions/new``         — 새 세션 (현재 active session 종료/clear)
- ``GET  /api/v1/chat/sessions/history``     — 세션 목록 (요약)
- ``POST /api/v1/chat/sessions/{sid}/restore`` — 특정 세션 복원
- ``GET  /api/v1/chat/sessions/{sid}``       — 단건 세션 + 메시지
- ``DELETE /api/v1/chat/sessions/{sid}``     — 세션 삭제

응답 shape: 프론트가 ``data?.data ?? data`` 로 unwrap 하므로 raw dict 반환.

scope: account_id (JWT sub) + tenant_id (X-Tenant-ID 또는 token claim).

P0.2 hardening (codex P2-8): migration order tolerance.
    - 새 컬럼 (``trace`` / ``structured_blocks``) 가 아직 마이그레이션 되지
      않은 환경 (rolling deploy 중간) 에서 SELECT 가 ``UndefinedColumn`` 으로
      500 가 나지 않게 ``_select_messages`` helper 가 컬럼 존재 캐시 후
      두 가지 SELECT 중 하나를 실행. Fully migrated 환경에서는 추가 비용 1회.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat-v1"])

# P0.2 hardening — 새 컬럼이 마이그되었는지 1회 검사. (None=unknown, True/False)
_HAS_STRUCTURED_BLOCKS: bool | None = None


async def _has_structured_blocks(conn: Any) -> bool:
    """``chat_messages.structured_blocks`` 컬럼 존재 여부 (process-local 캐시).

    rolling deploy 중간 (코드 050 마이그 전) 에 구 DB 에 SELECT 하지 않게.
    """
    global _HAS_STRUCTURED_BLOCKS
    if _HAS_STRUCTURED_BLOCKS is not None:
        return _HAS_STRUCTURED_BLOCKS
    try:
        r = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'chat_messages' "
                    "  AND column_name = 'structured_blocks' LIMIT 1"
                )
            )
        ).first()
        _HAS_STRUCTURED_BLOCKS = r is not None
        if not _HAS_STRUCTURED_BLOCKS:
            logger.warning(
                "chat_messages.structured_blocks column missing — "
                "alembic 050 not yet applied. messages will return without "
                "structured_blocks until migration runs."
            )
        return _HAS_STRUCTURED_BLOCKS
    except Exception:
        # 컬럼 검사 실패 — 안전한 fallback: structured_blocks 없는 SELECT.
        _HAS_STRUCTURED_BLOCKS = False
        return False


def _msg_select_sql(has_sb: bool) -> str:
    """structured_blocks 컬럼 유/무에 따른 SELECT 문."""
    if has_sb:
        return (
            "SELECT id, role, content, intent, cards, created_at, trace, "
            "       structured_blocks "
            "FROM chat_messages WHERE session_id = :sid "
            "ORDER BY created_at ASC, id ASC"
        )
    return (
        "SELECT id, role, content, intent, cards, created_at, trace "
        "FROM chat_messages WHERE session_id = :sid "
        "ORDER BY created_at ASC, id ASC"
    )


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


async def _reset_engine_for_tests() -> None:
    """테스트 간 event-loop 격리."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def _scope_from_headers(authorization: str, x_tenant_id: str | None) -> tuple[UUID, UUID]:
    """(account_id, tenant_id). JWT tenant claim authoritative — Phase 1.5A Task 8c.2.

    이전: X-Tenant-ID 헤더 우선 → cross-tenant 위장 취약.
    이제: ``_tenant_scope.resolve_tenant_id`` 사용. 헤더 mismatch → 401.
    """
    from src.api.routers._tenant_scope import resolve_tenant_id

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        payload = decode_token(authorization[7:].strip())
    except InvalidToken as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(400, "missing account/tenant scope")
    # JWT claim 인증; 헤더 mismatch → 401. claim 부재 + 헤더 부재 → 400 보존.
    if payload.get("tenant_id"):
        tid_str = resolve_tenant_id(payload, x_tenant_id)
    else:
        if x_tenant_id is not None and x_tenant_id != "":
            raise HTTPException(401, "tenant claim mismatch")
        raise HTTPException(400, "missing account/tenant scope")
    try:
        return UUID(str(sub)), UUID(str(tid_str))
    except ValueError as e:
        raise HTTPException(400, f"invalid uuid: {e}") from e


def _serialize_message(row: Any) -> dict:
    """row(id, role, content, intent, cards, created_at, trace?, structured_blocks?) → dict.

    PR-D — trace 컬럼이 alembic 040 으로 추가됨. row 가 trace 까지 포함된 경우
    7번째 인덱스에서 추출, 없으면 빈 리스트.
    P0.2 (KMS-Plus) — structured_blocks 가 alembic 050 으로 추가됨. row 가
    structured_blocks 까지 포함된 경우 8번째 인덱스에서 추출, 없으면 빈 리스트.
    옛 row (6/7컬럼) 호환.
    """
    cards = row[4]
    if isinstance(cards, str):
        try:
            cards = json.loads(cards)
        except Exception:
            cards = []
    # trace 는 row[6] (선택 — SELECT 절이 가져왔을 때만 존재).
    trace: list = []
    if len(row) > 6 and row[6] is not None:
        raw_trace = row[6]
        if isinstance(raw_trace, str):
            try:
                raw_trace = json.loads(raw_trace)
            except Exception:
                raw_trace = []
        if isinstance(raw_trace, list):
            trace = raw_trace
    # structured_blocks 는 row[7] (선택 — SELECT 절이 가져왔을 때만 존재).
    structured_blocks: list = []
    if len(row) > 7 and row[7] is not None:
        raw_sb = row[7]
        if isinstance(raw_sb, str):
            try:
                raw_sb = json.loads(raw_sb)
            except Exception:
                raw_sb = []
        if isinstance(raw_sb, list):
            structured_blocks = raw_sb
    return {
        "message_id": str(row[0]),
        "role": row[1],
        "content": row[2],
        "intent": row[3],
        "cards": cards or [],
        "timestamp": row[5].isoformat() if row[5] else None,
        "trace": trace,
        "structured_blocks": structured_blocks,
    }


class NewSessionIn(BaseModel):
    system_prompt: str | None = None
    title: str | None = None
    # R5 (2026-05-07) — chat_sessions.agent_id 채우는 진입점.
    # frontend ChatPage / NewSessionDialog 가 agent 선택 시 같이 전달.
    # 미지정 시 default_persona 가 agent_id 매핑이면 그것을 사용 (아래 logic).
    agent_id: str | None = None


class NewSessionOut(BaseModel):
    session_id: str


class SessionPatch(BaseModel):
    system_prompt: str | None = None
    title: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions/latest")
async def latest_session(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """현재 (account, tenant) 의 마지막 세션 + 메시지. 없으면 빈 응답."""
    aid, tid = _scope_from_headers(authorization, x_tenant_id)
    eng = _get_engine()
    async with eng.begin() as conn:
        sess_row = (
            await conn.execute(
                text(
                    """
                    SELECT id, title, created_at, updated_at, system_prompt,
                           channel_kind, channel_id, external_user_id, agent_id
                    FROM chat_sessions
                    WHERE account_id = :aid AND tenant_id = :tid
                          AND channel_kind = 'web'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {"aid": aid, "tid": tid},
            )
        ).first()
        if not sess_row:
            return {"session_id": None, "messages": []}
        sid = sess_row[0]
        has_sb = await _has_structured_blocks(conn)
        msg_rows = (
            await conn.execute(text(_msg_select_sql(has_sb)), {"sid": sid})
        ).all()
    return {
        "session_id": str(sid),
        "title": sess_row[1],
        "created_at": sess_row[2].isoformat() if sess_row[2] else None,
        "updated_at": sess_row[3].isoformat() if sess_row[3] else None,
        "system_prompt": sess_row[4] or "",
        "messages": [_serialize_message(r) for r in msg_rows],
        "channel_kind": sess_row[5] or "web",
        "channel_id": str(sess_row[6]) if sess_row[6] is not None else None,
        "external_user_id": sess_row[7],
        "agent_id": str(sess_row[8]) if sess_row[8] is not None else None,
    }


@router.post("/sessions/new", response_model=NewSessionOut)
async def new_session(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    body: NewSessionIn | None = None,
) -> NewSessionOut:
    """빈 세션 1개 생성.

    body 로 system_prompt/title 명시 전달 가능. 둘 다 미지정 시 사용자 계정의
    ``preferences.default_persona`` (settings 에서 한 번 설정) 를 자동 적용.
    프론트에서 매 새 채팅마다 페르소나를 선택할 필요 없도록 함 (2026-04-28).
    """
    aid, tid = _scope_from_headers(authorization, x_tenant_id)
    sp = (body.system_prompt if body else None)
    title = (body.title if body else None)
    # R5 — body.agent_id 있으면 chat_sessions.agent_id 에 직접 채움. 통합
    # 인박스 / 분석 / cross-tenant 격리 모두 이 컬럼 기반.
    raw_agent_id: str | None = body.agent_id if body else None
    agent_uuid: UUID | None = None
    if raw_agent_id:
        try:
            agent_uuid = UUID(raw_agent_id)
        except ValueError as e:
            raise HTTPException(400, f"agent_id must be valid UUID: {e}") from e

    eng = _get_engine()

    # body 에 system_prompt/title 미지정이면 계정 default_persona 적용.
    if sp is None or title is None:
        async with eng.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT preferences FROM accounts WHERE id = :aid"),
                    {"aid": aid},
                )
            ).first()
        prefs = (row[0] if row else {}) or {}
        dp = prefs.get("default_persona") if isinstance(prefs, dict) else None
        if isinstance(dp, dict):
            if sp is None and isinstance(dp.get("system_prompt"), str):
                sp = dp["system_prompt"]
            if title is None and isinstance(dp.get("name"), str):
                title = dp["name"]

    sp = sp or ""

    async with eng.begin() as conn:
        # R5 — agent_id 가 명시된 경우 동일 tenant 의 active agent 인지 확인.
        # 다른 tenant 의 agent_id 가 박히면 cross-tenant leak. 미존재면 NULL 로
        # 안전 fallback (404 raise 안 함 — UI 가 실패하면 사용자 경험 깨짐).
        if agent_uuid is not None:
            ag_row = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM agents WHERE id = :aid AND tenant_id = :tid "
                        "AND is_active = true"
                    ),
                    {"aid": agent_uuid, "tid": tid},
                )
            ).first()
            if ag_row is None:
                agent_uuid = None
        row = await conn.execute(
            text(
                """
                INSERT INTO chat_sessions
                  (account_id, tenant_id, system_prompt, title, agent_id)
                VALUES (:aid, :tid, :sp, :title, :agid)
                RETURNING id
                """
            ),
            {
                "aid": aid,
                "tid": tid,
                "sp": sp,
                "title": title,
                "agid": agent_uuid,
            },
        )
        sid = row.scalar_one()
    return NewSessionOut(session_id=str(sid))


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: SessionPatch,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """system_prompt 또는 title 업데이트. 둘 중 하나라도 있어야 함."""
    aid, tid = _scope_from_headers(authorization, x_tenant_id)
    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid session_id: {e}") from e
    if body.system_prompt is None and body.title is None:
        raise HTTPException(400, "no fields to update")
    eng = _get_engine()
    async with eng.begin() as conn:
        r = await conn.execute(
            text(
                """
                UPDATE chat_sessions
                SET system_prompt = COALESCE(:sp, system_prompt),
                    title         = COALESCE(:title, title),
                    updated_at    = now()
                WHERE id = :sid AND account_id = :aid AND tenant_id = :tid
                RETURNING id, system_prompt, title
                """
            ),
            {"sp": body.system_prompt, "title": body.title, "sid": sid, "aid": aid, "tid": tid},
        )
        row = r.first()
        if not row:
            raise HTTPException(404, "session not found")
    return {
        "session_id": str(row[0]),
        "system_prompt": row[1],
        "title": row[2],
    }


@router.get("/sessions/history")
async def session_history(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    limit: int = 50,
    channel_kind: str | None = None,
) -> dict:
    """세션 목록 (최신순). 각 세션의 첫 user 메시지를 미리보기로 첨부.

    059 (spec 2026-05-07) — channel_kind 필터 + origin 필드 응답.
    - ``channel_kind`` 미지정 (default) → 모든 채널 표시 (기존 동작 보존, all 포함)
    - ``channel_kind='web'`` → 웹 세션만 (ChatPage 기존 sidebar 호환)
    - ``channel_kind='telegram'`` 등 → 해당 채널만 (admin inbox 용)
    응답에 channel_kind/channel_id/external_user_id/agent_id 추가.

    Phase 1.5D 후속 (2026-05-07) — agent_name/agent_kind 추가 (LEFT JOIN agents).
    하부 에이전트 다수 운영 시 통합 인박스에서 agent 별 분류·필터·그룹 가능.
    JOIN 은 SQL 단에서 안전하게 LEFT — agent 가 삭제된 세션은 None.
    """
    aid, tid = _scope_from_headers(authorization, x_tenant_id)
    eng = _get_engine()
    # channel_kind 필터 — None 이면 무필터.
    ck_filter_sql = ""
    params: dict[str, Any] = {"aid": aid, "tid": tid, "lim": max(1, min(limit, 200))}
    if channel_kind:
        ck_filter_sql = " AND s.channel_kind = :ck"
        params["ck"] = channel_kind
    async with eng.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    f"""
                    SELECT s.id, s.title, s.created_at, s.updated_at,
                           (SELECT m.content FROM chat_messages m
                            WHERE m.session_id = s.id AND m.role = 'user'
                            ORDER BY m.created_at ASC LIMIT 1) AS preview,
                           (SELECT COUNT(*) FROM chat_messages m
                            WHERE m.session_id = s.id) AS msg_count,
                           s.channel_kind, s.channel_id, s.external_user_id,
                           s.agent_id, a.name, a.kind
                    FROM chat_sessions s
                    LEFT JOIN agents a ON a.id = s.agent_id
                    WHERE s.account_id = :aid AND s.tenant_id = :tid
                          {ck_filter_sql}
                    ORDER BY s.updated_at DESC
                    LIMIT :lim
                    """
                ),
                params,
            )
        ).all()
    return {
        "sessions": [
            {
                "session_id": str(r[0]),
                "title": r[1],
                "created_at": r[2].isoformat() if r[2] else None,
                "updated_at": r[3].isoformat() if r[3] else None,
                "preview": r[4],
                "message_count": r[5],
                "channel_kind": r[6] or "web",
                "channel_id": str(r[7]) if r[7] is not None else None,
                "external_user_id": r[8],
                "agent_id": str(r[9]) if r[9] is not None else None,
                "agent_name": r[10],
                "agent_kind": r[11],
            }
            for r in rows
        ],
    }


@router.post("/sessions/{session_id}/restore")
async def restore_session(
    session_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    aid, tid = _scope_from_headers(authorization, x_tenant_id)
    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid session_id: {e}") from e
    eng = _get_engine()
    async with eng.begin() as conn:
        sess = (
            await conn.execute(
                text(
                    """
                    SELECT id, title, created_at, updated_at, system_prompt,
                           channel_kind, channel_id, external_user_id, agent_id
                    FROM chat_sessions
                    WHERE id = :sid AND account_id = :aid AND tenant_id = :tid
                    """
                ),
                {"sid": sid, "aid": aid, "tid": tid},
            )
        ).first()
        if not sess:
            raise HTTPException(404, "session not found")
        has_sb = await _has_structured_blocks(conn)
        msgs = (
            await conn.execute(text(_msg_select_sql(has_sb)), {"sid": sid})
        ).all()
        # touch updated_at — 사용자가 다시 봤다 = 활동
        await conn.execute(
            text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"),
            {"sid": sid},
        )
    return {
        "session_id": str(sess[0]),
        "title": sess[1],
        "created_at": sess[2].isoformat() if sess[2] else None,
        "updated_at": sess[3].isoformat() if sess[3] else None,
        "system_prompt": sess[4] or "",
        "messages": [_serialize_message(r) for r in msgs],
        "channel_kind": sess[5] or "web",
        "channel_id": str(sess[6]) if sess[6] is not None else None,
        "external_user_id": sess[7],
        "agent_id": str(sess[8]) if sess[8] is not None else None,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """단건 조회. restore 와 응답 동일하지만 updated_at 은 건드리지 않음."""
    aid, tid = _scope_from_headers(authorization, x_tenant_id)
    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid session_id: {e}") from e
    eng = _get_engine()
    async with eng.begin() as conn:
        sess = (
            await conn.execute(
                text(
                    """
                    SELECT id, title, created_at, updated_at, system_prompt,
                           channel_kind, channel_id, external_user_id, agent_id
                    FROM chat_sessions
                    WHERE id = :sid AND account_id = :aid AND tenant_id = :tid
                    """
                ),
                {"sid": sid, "aid": aid, "tid": tid},
            )
        ).first()
        if not sess:
            raise HTTPException(404, "session not found")
        has_sb = await _has_structured_blocks(conn)
        msgs = (
            await conn.execute(text(_msg_select_sql(has_sb)), {"sid": sid})
        ).all()
    return {
        "session_id": str(sess[0]),
        "title": sess[1],
        "created_at": sess[2].isoformat() if sess[2] else None,
        "updated_at": sess[3].isoformat() if sess[3] else None,
        "system_prompt": sess[4] or "",
        "messages": [_serialize_message(r) for r in msgs],
        "channel_kind": sess[5] or "web",
        "channel_id": str(sess[6]) if sess[6] is not None else None,
        "external_user_id": sess[7],
        "agent_id": str(sess[8]) if sess[8] is not None else None,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    aid, tid = _scope_from_headers(authorization, x_tenant_id)
    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(400, f"invalid session_id: {e}") from e
    eng = _get_engine()
    async with eng.begin() as conn:
        r = await conn.execute(
            text(
                """
                DELETE FROM chat_sessions
                WHERE id = :sid AND account_id = :aid AND tenant_id = :tid
                """
            ),
            {"sid": sid, "aid": aid, "tid": tid},
        )
    if (r.rowcount or 0) == 0:
        raise HTTPException(404, "session not found")
    return {"ok": True, "session_id": session_id}
