"""/api/v1/chat — frontend-v2 호환 chat 라우터 (sessions 외 message/briefing/onboarding/confirm-capture).

frontend 호출:
- ``POST /api/v1/chat/message``         — 메시지 전송 (SSE stream → /agent/chat 위임)
- ``GET  /api/v1/chat/briefing``        — 아침 브리핑 (오늘 일정·새 뉴스 요약)
- ``POST /api/v1/chat/onboarding``      — 첫 방문 4단계 온보딩
- ``POST /api/v1/chat/confirm-capture`` — capture 확정 stub

P1.3-P1.4. message 는 /agent/chat 로 forward + chat_messages 테이블에 user/assistant 각각 1행.
briefing 은 agent_data (schedules/news/diaries) 조합. onboarding 은 step 1~4 진행.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterable
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

# KMS-only image (.dockerignore 가 src/agent_framework 제거) 에서는 본 모듈이 mount 되지 않지만
# mail_accounts 가 _get_engine/_scope helper 를 import 하므로 모듈 자체는 로딩됨 → top-level
# agent_framework import 만 lazy 로 감싸 import 실패 차단. router endpoint 실행 시점에는 KMS 모드에서
# 이 코드 경로가 닿지 않음.
try:
    from src.agent_framework.api.dependencies import get_agent_engine
    from src.agent_framework.observability.latency_probe import LatencyProbe
    from src.agent_framework.runtime.engine import AgentEngine
    from src.agent_framework.runtime.sender_context import SenderContext
except ModuleNotFoundError:
    get_agent_engine = None  # type: ignore[assignment]
    LatencyProbe = None  # type: ignore[assignment]
    AgentEngine = None  # type: ignore[assignment]
    SenderContext = None  # type: ignore[assignment]
from src.api.auth.jwt_utils import InvalidToken, decode_token
from src.common.config import settings
from src.common.feature_flags import FeatureFlag, is_enabled


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/chat", tags=["chat-v1"])


# ---------------------------------------------------------------------------
# G1 (KMS-Plus, 2026-04-26) — context 유지 전략 상수
# ---------------------------------------------------------------------------
# 사용자 요구: "1000번의 대화 이내로, 그에 맞게 컨텍스트 유지 전략도".
#
# 전략 = sliding window + per-turn 길이 cap.
#   - 한 번의 LLM 입력에 직전 12 turn (user+assistant 6 라운드 ≈ 6쌍) 포함
#   - 각 turn 의 content 는 200자 cap → 짧게 요약된 형태로만 prompt 에 들어가
#     1000 turn 까지 가도 prompt 길이가 폭발하지 않음
#   - 전체 effective_text 는 MAX_PROMPT_CHARS 로 한 번 더 안전 truncate
#   - 1000 turn 도달 시: WARNING 로그 (자동 archive/rotation 은 후속 follow-up).
#     사용자에게 보이는 동작은 깨지지 않음 (DB 저장은 계속 허용).
HISTORY_TURN_LIMIT = 12        # 가장 최근 12개 메시지 (user+assistant 혼합)
HISTORY_PER_TURN_CAP = 200     # turn 당 최대 200자 (한국어 기준 약 80~100 토큰)
MAX_PROMPT_CHARS = 4000        # 전체 prompt 안전 cap
SOFT_TURN_CAP = 1000           # 세션당 권고 메시지 cap (soft, log only)


# ---------------------------------------------------------------------------
# P0.2 hardening (codex 2차 review, 2026-04-28) — structured_blocks 사이즈 cap.
# ---------------------------------------------------------------------------
# 배경: SSE 스트림 중 ``structured_block`` event 가 무제한으로 들어와도
# ``final_structured_blocks`` 에 그대로 누적 → JSONB INSERT 시 worker 메모리
# 폭주 + DB row 비대화 가능. 잘못된 engine path / 무한 루프 / 악의적 page-load
# 등 모두 방어.
#
# 한도값은 일반 패턴 (메모리 안정화 + UI 가독성) 으로 결정.
# 사례 enum 가 아니라 절대 한도 — 어떤 도메인이 와도 동일 적용.
STRUCTURED_BLOCKS_MAX_COUNT = 16          # assistant 메시지 1건당 최대 block 수
STRUCTURED_BLOCKS_MAX_BYTES_PER = 64 * 1024  # block 1개의 직렬화 한도 (64 KB)
STRUCTURED_BLOCKS_MAX_TOTAL_BYTES = 256 * 1024  # 전체 직렬화 한도 (256 KB)


def _cap_structured_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``final_structured_blocks`` 를 INSERT 직전에 한도 적용.

    - block 1개가 ``STRUCTURED_BLOCKS_MAX_BYTES_PER`` 초과 시 ``payload`` 만
      ``{_truncated: True, _original_bytes: N}`` 로 치환. title/kind/id 등
      메타는 보존 — frontend 가 truncate 안내 가능.
    - 전체 합계가 ``STRUCTURED_BLOCKS_MAX_TOTAL_BYTES`` 초과하기 직전에 중단.
    - block 수가 ``STRUCTURED_BLOCKS_MAX_COUNT`` 초과 시 즉시 중단.
    """
    capped: list[dict[str, Any]] = []
    total = 0
    for b in blocks:
        if not isinstance(b, dict):
            continue
        s = json.dumps(b, ensure_ascii=False)
        if len(s) > STRUCTURED_BLOCKS_MAX_BYTES_PER:
            # payload 만 sentinel 로. title/kind/id 등 메타 키는 살린다.
            replaced = {
                **{k: v for k, v in b.items() if k != "payload"},
                "payload": {
                    "_truncated": True,
                    "_original_bytes": len(s),
                },
            }
            b = replaced
            s = json.dumps(b, ensure_ascii=False)
        if total + len(s) > STRUCTURED_BLOCKS_MAX_TOTAL_BYTES:
            break
        capped.append(b)
        total += len(s)
        if len(capped) >= STRUCTURED_BLOCKS_MAX_COUNT:
            break
    return capped


_engine: AsyncEngine | None = None


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    return _engine


async def _reset_engine_for_tests() -> None:
    """테스트 간 event-loop 격리. 이전 fixture loop 의 connection pool 누설 방지."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def _scope(authorization: str, x_tenant_id: str | None) -> tuple[UUID, UUID]:
    """(account_id, tenant_id) 추출. JWT tenant claim 만 신뢰.

    Phase 1.5A Task 8c (GPT-5.5 deep dive 발견 — 2026-05-06):
    이전 구현은 ``X-Tenant-ID`` 헤더를 우선시 했음. 그래서 valid JWT 를 가진
    호출자가 다른 tenant 의 ID 를 헤더로 보내면 그 tenant 인 척 위장이 가능.
    Cross-tenant impersonation 으로 production blocking.

    Phase 1.5A Task 8c.2 (2026-05-07): 동일 패턴이 5+ 라우터에 존재 —
    ``_tenant_scope.resolve_tenant_id`` 공유 헬퍼로 통합. 본 함수는 sub 검증·
    UUID 변환·"missing scope" (400) 호환성 보존을 위해 헬퍼를 호출만 함.
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
        raise HTTPException(400, "missing scope")
    # JWT claim authoritative — 헤더 mismatch → 401.
    # 기존 거동 보존: JWT tenant claim 부재 + 헤더 부재 → 400 'missing scope'.
    # JWT claim 부재 + 헤더 존재 → 401 mismatch (헤더로 권한 상승 시도 차단).
    if payload.get("tenant_id"):
        tid_str = resolve_tenant_id(payload, x_tenant_id)
    else:
        if x_tenant_id is not None and x_tenant_id != "":
            raise HTTPException(401, "tenant claim mismatch")
        raise HTTPException(400, "missing scope")
    try:
        return UUID(str(sub)), UUID(str(tid_str))
    except ValueError as e:
        raise HTTPException(400, f"invalid uuid: {e}") from e


# ---------------------------------------------------------------------------
# T4 (KMS-Plus, 2026-05-06) — phase measurement helper
# ---------------------------------------------------------------------------
# helper 정의만. dispatcher 내 호출은 T5 에서 조건부 wrap 으로 추가 예정.
# flag off 시 dispatcher 가 호출 안 하면 시연 path 영향 0.
# 호출하더라도 record_phase 외 부수효과 없음 — 결과/예외 그대로 전파.


async def _phase_wrap(
    probe: LatencyProbe,
    phase_name: str,
    coro_factory,
    *,
    extract_meta=None,
):
    """phase 측정 wrapper. caller 예외는 그대로 전파.

    coro_factory: () -> Awaitable[Any]
    extract_meta: 선택 — 결과로부터 phase meta dict 추출.

    flag off 시 dispatcher 가 호출 안 하면 시연 path 영향 0. 호출하더라도
    record_phase 외 부수효과 없음 — caller 의 흐름은 결과/예외 그대로.
    """
    started = time.time()
    result = None
    error: Exception | None = None
    try:
        result = await coro_factory()
    except Exception as e:  # KeyboardInterrupt/SystemExit 는 즉시 전파
        error = e
    ended = time.time()
    meta: dict = {}
    if error is None and extract_meta is not None:
        try:
            meta = extract_meta(result) or {}
        except Exception:
            meta = {}
    probe.record_phase(phase_name, started, ended, **meta)
    if error is not None:
        raise error
    return result


# ---------------------------------------------------------------------------
# Phase 1.5A Task 7 — SenderContext factory (web session)
# ---------------------------------------------------------------------------


def _build_sender_context_from_session(
    user: Any,
    *,
    channel_kind: str = "web",
) -> SenderContext:
    """web session login user → SenderContext.

    user 는 ``id`` / ``tenant_id`` / ``role`` 만 있으면 됨 (User ORM 또는
    duck-typed object 모두 지원).

    role ∈ {admin, owner} → tier=admin, 그 외 → tier=verified.
    web 진입은 항상 verified_via='session_login' (JWT 통과한 user).
    """
    role = (getattr(user, "role", None) or "")
    # User ORM 의 role 은 enum (UserRole) 일 수 있으므로 .value 우선.
    role_str = getattr(role, "value", role) if not isinstance(role, str) else role
    role_norm = (role_str or "").lower()
    tier = "admin" if role_norm in ("admin", "owner") else "verified"
    return SenderContext(
        tier=tier,
        internal_user_id=user.id,
        tenant_id=user.tenant_id,
        channel_kind=channel_kind,
        verified_via="session_login",
        confirm_token=None,
    )


async def _sse_mirror_tee(
    source: AsyncIterable[dict],
    consumer: Callable[[dict], Awaitable[None]],
):
    """SSE event generator 를 사용자에게 yield 하면서 동시에 consumer 에
    push. consumer 예외는 격리 (사용자 흐름 영향 X).

    consumer must be fast (<1ms typical); serial await preserves order — slow consumer 는 사용자 SSE 도 느리게 만듦.

    flag off 시 dispatcher 가 호출 안 하면 시연 path 영향 0. 호출하더라도
    yield 순서/내용 변화 없음 — consumer 는 best-effort 미러.
    """
    async for ev in source:
        try:
            await consumer(ev)
        except Exception:
            logger.exception("latency_probe mirror consumer failed (isolated)")
        yield ev


# ---------------------------------------------------------------------------
# /chat/message — /agent/chat alias with persistence
# ---------------------------------------------------------------------------


class MessageRequest(BaseModel):
    text: str
    session_id: str | None = None
    stream: bool = True
    # Phase 1 Task 6 — agent_id 분기. 미지정 시 None → 기존 동작 byte-equal.
    agent_id: str | None = None


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


@router.post("/message")
async def chat_message(
    request: Request,
    body: MessageRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(None, alias="X-Agent-Id"),
    engine: AgentEngine = Depends(get_agent_engine),
) -> StreamingResponse:
    """/agent/chat 와 동일한 SSE engine 위에 user/assistant 메시지 chat_messages 영속.

    session_id 없으면 신규 세션 자동 생성.

    agent_id 지정 시 (body.agent_id 또는 X-Agent-Id 헤더) AgentContext 로드 →
    effective_text 에 agent 목표/지침 inject. 미지정 시 byte-equal (기존 동작).
    """
    aid, tid = _scope(authorization, x_tenant_id)

    # Phase 1 Task 6 — agent_id 분기.
    # body.agent_id 우선, 없으면 X-Agent-Id 헤더.
    # 미지정 시 agent_context=None → 기존 동작 byte-equal (아래 inject 블록 건너뜀).
    _raw_agent_id: str | None = body.agent_id or x_agent_id
    agent_context = None
    if _raw_agent_id:
        from src.agent_framework.runtime.agent_context import AgentContext
        from src.core.repositories.agent_repository import AgentRepository

        try:
            _agent_uuid = UUID(_raw_agent_id)
        except ValueError as e:
            raise HTTPException(400, f"agent_id must be valid UUID: {e}") from e

        # AgentRepository 는 AsyncSession 기반 — 공유 lazy engine 위에서 세션 생성.
        # D28 §4 (2026-05-08): 이전에는 매 요청마다 별도 `create_async_engine` +
        # `dispose()` → connection pool 매번 생성/파기. 5 봇 + admin path 가 모두
        # agent_id 를 보내므로 모든 chat 메시지 영향. 공유 `_get_engine()` 으로 교체
        # → pool reuse + 표준 SQLAlchemy 패턴 + 동일 옵션 (pool_pre_ping=True).
        # 세션 격리는 유지 (engine 공유 ≠ session 공유). GPT-5 §4 GO + caveat 반영.
        async with AsyncSession(_get_engine()) as _sess:
            _repo = AgentRepository(_sess)
            _agent = await _repo.get(_agent_uuid, tenant_id=tid)

        if _agent is None:
            raise HTTPException(404, "agent not found in tenant")
        if not _agent.is_active:
            raise HTTPException(404, "agent inactive")
        agent_context = AgentContext.from_agent(_agent)
    db = _get_engine()
    system_prompt: str = ""
    async with db.begin() as conn:
        sid: UUID
        if body.session_id:
            try:
                sid = UUID(body.session_id)
            except ValueError as e:
                raise HTTPException(400, f"invalid session_id: {e}") from e
            # 권한 검증 + system_prompt 같이 fetch
            r = (
                await conn.execute(
                    text(
                        "SELECT system_prompt FROM chat_sessions "
                        "WHERE id = :sid AND account_id = :aid AND tenant_id = :tid"
                    ),
                    {"sid": sid, "aid": aid, "tid": tid},
                )
            ).first()
            if not r:
                raise HTTPException(404, "session not found")
            system_prompt = r[0] or ""
        else:
            # R5 (2026-05-07) — agent_id 가 헤더/body 로 들어왔으면 INSERT 에 같이.
            # web 진입점에서 chat_sessions.agent_id 가 NULL 로 박히면 통합 인박스
            # / 분석 / agent 별 메트릭 모두 무용지물. agent_context.agent_id 우선,
            # 없으면 _raw_agent_id (UUID 검증 실패 케이스 포함 — 이미 위에서 catch).
            _agent_id_for_session: UUID | None = None
            if agent_context is not None:
                _agent_id_for_session = getattr(agent_context, "agent_id", None)
            row = await conn.execute(
                text(
                    "INSERT INTO chat_sessions (account_id, tenant_id, agent_id) "
                    "VALUES (:aid, :tid, :agid) RETURNING id"
                ),
                {"aid": aid, "tid": tid, "agid": _agent_id_for_session},
            )
            sid = row.scalar_one()
        # R5 — 기존 session 재사용 path 에서도 agent_id 가 변경됐으면 backfill.
        # 첫 turn 에 agent 가 결정되지 않았다가 두 번째 turn 에 결정되는 경우를 위한
        # 복구. 이미 다른 agent_id 가 박힌 row 는 *덮어쓰지 않음* (변경 의도 모호).
        if body.session_id and agent_context is not None:
            _new_agent_id = getattr(agent_context, "agent_id", None)
            if _new_agent_id is not None:
                await conn.execute(
                    text(
                        "UPDATE chat_sessions SET agent_id = :agid "
                        "WHERE id = :sid AND agent_id IS NULL"
                    ),
                    {"agid": _new_agent_id, "sid": sid},
                )
        # user 메시지 저장
        await conn.execute(
            text(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (:sid, 'user', :content)
                """
            ),
            {"sid": sid, "content": body.text},
        )

    # 페르소나 + 대화 컨텍스트 주입.
    # F5 (KMS-Plus, 2026-04-26) — 컨텍스트 관리 강화.
    # 사용자 보고 버그: turn 3 "가입 한도는?" 에서 turn 1-2 의 "장병내일준비적금"
    # 컨텍스트를 잃고 "상품마다 다릅니다" 라는 일반론으로 답변. 원인: engine 의
    # session.history (Redis) 가 제대로 살아있더라도 (1) sticky persona 가 끊기거나
    # (2) RAG retrieval 이 키워드 못 찾거나 (3) 페르소나 fallback 경로로 빠지면
    # LLM 입력에 prior turns 가 빠질 수 있음. belt+suspenders 로 chat_v1 단에서
    # 직전 대화 + 시스템 규칙 + 현재 발화를 명시적으로 합성해 engine 에 전달.
    hist: list[Any] = []
    total_messages = 0
    async with db.begin() as conn:
        # G1 — 1000-turn soft cap 체크. 별도 COUNT 쿼리는 한 세션에서 한 번씩이면
        # 비용 미미. 도달 시 WARNING 만 (rotation 은 후속).
        cnt_row = (
            await conn.execute(
                text("SELECT COUNT(*) FROM chat_messages WHERE session_id = :sid"),
                {"sid": sid},
            )
        ).first()
        total_messages = int(cnt_row[0]) if cnt_row else 0
        if total_messages >= SOFT_TURN_CAP:
            logger.warning(
                "chat session %s reached %d messages (soft cap=%d); "
                "consider session rotation",
                sid,
                total_messages,
                SOFT_TURN_CAP,
            )
        hist_rows = (
            await conn.execute(
                text(
                    """
                    SELECT role, content
                    FROM chat_messages
                    WHERE session_id = :sid
                    ORDER BY created_at DESC
                    LIMIT :lim
                    """
                ),
                {"sid": sid, "lim": HISTORY_TURN_LIMIT},
            )
        ).all()
        # 시간순 정렬. 방금 INSERT 한 user 메시지 (가장 최근) 가 마지막에 오는데,
        # body.text 와 같으면 중복이라 prior context 에서 제외.
        hist = list(reversed(hist_rows))
        if hist and hist[-1][0] == "user" and hist[-1][1] == body.text:
            hist = hist[:-1]

    context_parts: list[str] = []
    # 1. 가장 강한 규칙 — 컨텍스트 유지 + 추측 금지
    context_parts.append(
        "[중요 규칙 — 반드시 지킬 것]\n"
        "- 이전 대화의 주제·상품·맥락을 반드시 유지하라. "
        "사용자가 대명사·생략형 ('가입 한도는?', '그럼 어떻게 돼?') 으로 물으면 "
        "직전 턴들에서 다룬 구체 상품·도메인을 그대로 이어서 답변할 것\n"
        "- 새로운 상품·도메인으로 임의 화제 전환 금지\n"
        "- 자료에 없는 사실은 \"해당 자료에는 ...에 대한 정보가 없습니다\" 라고 명확히 답하라. "
        "추측·일반론 ('상품마다 차이가 있습니다') 으로 대체하지 말 것"
    )
    # 2. 페르소나 (system_prompt 있을 때만)
    if system_prompt.strip():
        context_parts.append(
            f"[역할 지시 — 반드시 따를 것]\n{system_prompt.strip()}"
        )
    # 2b. Phase 1 Task 6 — agent_context 주입 (지정 시).
    # agent_id 미지정 시 agent_context=None → 이 블록 건너뜀 → byte-equal.
    if agent_context is not None:
        context_parts.append(
            f"[에이전트 컨텍스트]\n{agent_context.to_prompt_section()}"
        )
    # 3. 직전 대화 — G1 sliding window 전략.
    #    각 turn 을 HISTORY_PER_TURN_CAP (200자) 으로 잘라 prompt 폭주 방지.
    #    1000 turn 까지 가도 직전 12개만 보내고, 12개 각각이 200자 cap →
    #    convo 본문 ~2.5KB 이하로 안정.
    if hist:
        def _truncate(s: str, n: int = HISTORY_PER_TURN_CAP) -> str:
            if not s:
                return ""
            s = s.strip()
            return s if len(s) <= n else s[:n] + " …"

        convo_lines = [
            f"{'사용자' if r[0] == 'user' else '어시스턴트'}: {_truncate(r[1])}"
            for r in hist
        ]
        # 12 turn 헤더에 총 메시지 수를 같이 알려주면 LLM 이 '이건 일부' 라는 것을
        # 인식. 1000 turn 가까이 가도 hallucinated continuity 줄임.
        header = (
            f"[이전 대화 — 주제·맥락 유지 · 최근 {len(hist)} turn / 전체 {total_messages} turn]"
        )
        context_parts.append(f"{header}\n" + "\n".join(convo_lines))
    # 4. 현재 발화
    context_parts.append(f"[현재 사용자 발화]\n{body.text}")

    # Phase 1.5A Task 7 — SenderContext 빌드.
    # web session 은 항상 JWT 통과한 verified user. role 분류는 manifest 의
    # _resolve_account_role 과 동일 패턴 (preferences.user_groups='admin' 우선,
    # tenant_memberships.role fallback). 실패 시 tier='verified' default.
    _sender: SenderContext | None = None
    try:
        _sender_role: str | None = None
        async with db.connect() as _conn:
            _prefs_row = (
                await _conn.execute(
                    text("SELECT preferences FROM accounts WHERE id = :aid LIMIT 1"),
                    {"aid": aid},
                )
            ).first()
            if _prefs_row is not None:
                _raw = _prefs_row[0] or {}
                if isinstance(_raw, str):
                    try:
                        _raw = json.loads(_raw)
                    except Exception:
                        _raw = {}
                if isinstance(_raw, dict):
                    _ug = _raw.get("user_groups") or []
                    if isinstance(_ug, list) and "admin" in _ug:
                        _sender_role = "admin"
            if _sender_role is None:
                _r = (
                    await _conn.execute(
                        text(
                            "SELECT role FROM tenant_memberships "
                            "WHERE account_id = :aid AND tenant_id = :tid LIMIT 1"
                        ),
                        {"aid": aid, "tid": tid},
                    )
                ).first()
                if _r and _r[0]:
                    _sender_role = str(_r[0] or "").lower() or None

        # duck-typed user object — helper 는 id/tenant_id/role 만 필요.
        class _SessionUser:
            __slots__ = ("id", "tenant_id", "role")

            def __init__(self, id_, tenant_id_, role_):
                self.id = id_
                self.tenant_id = tenant_id_
                self.role = role_

        _sender = _build_sender_context_from_session(
            _SessionUser(aid, tid, _sender_role),
            channel_kind="web",
        )
    except Exception:
        # sender 빌드 실패 시 None — engine.turn() 은 sender=None default 로 동작.
        # 시연 path 에 무영향.
        logger.exception("sender_context build failed (continuing with sender=None)")
        _sender = None

    effective_text = "\n\n".join(context_parts)
    # 안전 cap. 12 turn × 200자 + persona + 현재 발화 정도면 보통 2~3KB 이지만
    # persona/system_prompt 가 과도하게 길어진 경우 등 edge case 방지.
    if len(effective_text) > MAX_PROMPT_CHARS:
        # 앞부분 (중요 규칙 + 페르소나) 보존, 중간 (이전 대화 일부) 자르기.
        keep_head = 1500   # 중요 규칙 + 페르소나
        keep_tail = 1500   # 직전 turn 들 + 현재 발화
        effective_text = (
            effective_text[:keep_head]
            + "\n\n[…이전 대화 일부 생략…]\n\n"
            + effective_text[-keep_tail:]
        )
        logger.info(
            "chat session %s effective_text truncated %d → %d chars",
            sid,
            len("\n\n".join(context_parts)),
            len(effective_text),
        )

    final_text_parts: list[str] = []
    captured_intent: str | None = None
    # PR-D — server-side trace collector. SSE 흐름 동안 디버깅 trace 가치가 있는
    # event 들을 모아 finally 시점에 chat_messages.trace JSONB 컬럼에 영속.
    # frontend 가 reload 시 동일 데이터로 TraceStrip 복원 가능.
    trace_events: list[dict[str, Any]] = []
    # P0.3 codex P1-1 hardening — citation reconciliation.
    # engine 은 LLM 토큰 스트림 시작 *전* 에 ``event: citations`` 를 emit 하므로
    # 이 시점에는 본문에 [N] 마커가 박힐지 알 수 없다. 스트림 종료 후 본문 텍스트
    # 안의 [N] 마커를 파싱해 각 citation 에 ``referenced=True/False`` 플래그를 채워
    # (a) frontend P8 이 inline-link 활성 여부 결정, (b) trace 영속본도 reconciled
    # 결과로 갱신되도록 한다. citations event 는 수집만 — frontend 는 finalized
    # 이벤트 또는 reload 시 trace 의 reconciled payload 를 사용.
    captured_citations: list[dict[str, Any]] = []
    engine_emitted_finalized = False
    # P0.2 (KMS-Plus) — Context Panel payload 영속화. structured_block event 는
    # trace 와는 분리된 채널 (chat_messages.structured_blocks JSONB) 로 저장.
    final_structured_blocks: list[dict[str, Any]] = []
    # P0.2 hardening (codex 2차 review) — 수집 단계에서 cap 한도를 즉시 알 수
    # 있도록 플래그. 중복 WARNING 로그 방지.
    sb_cap_warned: dict[str, bool] = {"warned": False}
    _TRACE_KINDS = {
        "intent", "skill_activated", "compound_detected", "progress",
        "citations", "tool_call", "tool_result", "slot_update",
        "slot_fill_decision", "retrieval_gate_decision",
        "persona_grounding_skipped", "query_rewrite", "hyde_expansion",
        "guard_eval", "error_frame",
        # PR-F — 저장소 자동 타겟팅 결정 trace
        "repo_target_decision",
        # P0.2 (KMS-Plus) — Context Panel + drawer cross-trigger payloads.
        "structured_block",
        "ui_hint",
        # P11-7 (2026-04-29) — plan_orchestrator path trace 영속.
        # 빠진 채로 두면 plan path turn 이 재진입 시 intent 1개만 남고 모두
        # 사라짐. 사용자 보고: "채팅 나갔다 들어오면 추론 1단계 0ms 로 바뀜".
        "plan_generated",
        "plan_step",
        "plan_clarify",
        "plan_reasoning",
        "citations_finalized",
    }
    import time as _t

    # T-INTEGRATE (2026-05-06): flag 를 stream() 진입 전 *한 번* 평가.
    # stream() 내부에서 재평가하지 않아 per-event 오버헤드 0.
    _probe_enabled: bool = is_enabled(FeatureFlag.LATENCY_PROBE_SSE, tenant_id=str(tid))

    # Stage 4 (2026-05-06): SKILL_INTENT_RECONCILE wire.
    # flag 를 stream() 진입 전 *한 번* 평가 — per-event 오버헤드 0.
    # flag false 시 _reconcile_enabled=False → 분기 안 실행, 변수 미생성,
    # reconcile 호출 자체 없음. 기존 dispatcher 동작 byte-equal 보장.
    _reconcile_enabled: bool = is_enabled(
        FeatureFlag.SKILL_INTENT_RECONCILE, tenant_id=str(tid)
    )

    async def stream():
        nonlocal captured_intent, captured_citations
        # P11-19e — session_id 를 SSE 첫 이벤트로 emit. harness 가 multi-turn
        # 시 같은 session 유지하도록. 이전 (event: session 미발행) → 매 turn
        # 마다 신규 session 생성 → multi_turn 회귀 12건의 직접 원인.
        yield _sse("session", {"session_id": str(sid)})
        # Stage 4 — reconciler 용 skill_v2 이름 수집 버퍼.
        # flag off 시 이 블록 자체 미진입 → 변수 생성 없음.
        if _reconcile_enabled:
            _captured_skill_v2_name: str | None = None
        try:
            # T-INTEGRATE: probe + mirror 통합 — flag off 시 _probe_enabled=False
            # → 분기 안 실행, engine.turn() 직접 iter, byte-equal 출력 보장.
            #
            # D33 §3 사후 GPT-5 §1 WARN patch: engine.turn() / _sse_mirror_tee 의
            # *생성* 도 bind_agent_scope context 안으로 이동 — 생성 시점의
            # background task / future spawn 도 contextvar 전파 보장.
            if _probe_enabled:
                probe = LatencyProbe()
                _turn_started = _t.time()

                # P2-2: probe 를 keyword default 로 바인딩 — 향후 재대입 시 late-binding race 방지.
                # P3-1: plan_step 전용에서 모든 event 로 일반화.
                async def _consume_event(item: dict, *, probe: LatencyProbe = probe) -> None:
                    probe.consume_event(item)
            else:
                _consume_event = None  # type: ignore[assignment]
            # D33 §3 — bind_agent_scope() 실 호출 site. agent_context.agent_id 가
            # 있으면 turn 진행 동안 RLSContext.scope 를 admin → agent 로 일시 전환.
            # agent_id 미존재 (admin path / Locus admin) 시 bind_agent_scope 는
            # no-op (RLSContext 그대로 admin scope 유지).
            #
            # 사후 GPT-5 §3 §1 WARN patch: engine.turn / _sse_mirror_tee 의 *생성*
            # 까지 bind_agent_scope context 안으로 이동 — 생성 시점의 background
            # task / future spawn 도 contextvar 전파 보장.
            from src.api.middleware.rls_context import bind_agent_scope as _bind_scope
            _bind_aid = (
                str(getattr(agent_context, "agent_id", None))
                if agent_context is not None
                and getattr(agent_context, "agent_id", None) is not None
                else None
            )

            async def _scoped_iter(
                aid_=_bind_aid, tid_=str(tid),
                probe_enabled=_probe_enabled,
            ):
                """async generator — bind_agent_scope context 안에서 source/iter 생성+소진.

                D33 §3 사후 GPT-5 §1 WARN patch — contextvars 가 매 __anext__ 마다
                caller context 따르고, 더해 생성 시점의 background spawn 도 안전.
                """
                async with _bind_scope(aid_, tid_):
                    if probe_enabled:
                        _src = engine.turn(
                            str(sid),
                            str(tid),
                            effective_text,
                            account_id_hint=str(aid),
                            agent_context=agent_context,
                            sender=_sender,
                        )
                        _it_inner = _sse_mirror_tee(_src, _consume_event)
                    else:
                        _it_inner = engine.turn(
                            str(sid),
                            str(tid),
                            effective_text,
                            account_id_hint=str(aid),
                            agent_context=agent_context,
                            sender=_sender,
                        )
                    async for _it_item in _it_inner:
                        yield _it_item

            _item_iter = _scoped_iter()

            async for item in _item_iter:
                ev = item.get("event", "message")
                data = item.get("data", {}) or {}
                # engine yields `token` (per-token streamed text) AND historically
                # `delta` from older callers. Capture both. login_brief / ack are
                # pre-response chrome — not stored.
                if ev in ("token", "delta") and isinstance(data, dict):
                    chunk = data.get("text") or data.get("delta") or ""
                    if chunk:
                        final_text_parts.append(chunk)
                # Stage 4 — skill_v2 이름 수집 (reconciler 용).
                # flag off 시 _captured_skill_v2_name 미존재 → 이 분기 미진입.
                if _reconcile_enabled and ev == "skill_activated" and isinstance(data, dict):
                    _captured_skill_v2_name = data.get("name") or None
                if ev == "intent" and isinstance(data, dict):
                    intents = data.get("intents") or []
                    if intents:
                        captured_intent = intents[0] if isinstance(intents[0], str) else (intents[0] or {}).get("name")
                    # Stage 4 — reconcile hook: intent event 수신 직후 / token 스트림 전.
                    # flag off 시 이 블록 미진입 — reconcile 호출 자체 없음.
                    if _reconcile_enabled and _captured_skill_v2_name and captured_intent:
                        try:
                            from src.agent_framework.runtime.reconcilers.skill_intent_reconciler import (
                                reconcile,
                                SkillIntentDecision,
                            )

                            _recon_llm = (
                                getattr(engine, "llm", None)
                                or getattr(
                                    getattr(engine, "response_generator", None), "llm", None
                                )
                                or getattr(
                                    getattr(engine, "fallback_router", None), "llm", None
                                )
                                or getattr(
                                    getattr(engine, "intent_classifier", None), "llm", None
                                )
                            )
                            if _recon_llm is not None and hasattr(_recon_llm, "complete"):
                                _recon_available = list(
                                    {_captured_skill_v2_name, captured_intent}
                                )
                                decision: SkillIntentDecision = await reconcile(
                                    user_message=body.text,
                                    skill_v2_decision=_captured_skill_v2_name,
                                    intent_label=captured_intent,
                                    available_skills=_recon_available,
                                    llm=_recon_llm,
                                )
                                if decision.conflict:
                                    _resolved = (
                                        decision.resolved_skill
                                        if decision.resolved_skill
                                        else (captured_intent or _captured_skill_v2_name)
                                    )
                                    logger.info(
                                        "skill_intent_reconciler: %s vs %s → "
                                        "resolved=%s conf=%.2f",
                                        _captured_skill_v2_name,
                                        captured_intent,
                                        _resolved,
                                        decision.confidence,
                                    )
                                    captured_intent = _resolved
                                    yield _sse(
                                        "skill_intent_reconciled",
                                        {
                                            "skill_v2": _captured_skill_v2_name,
                                            "intent": decision.intent_label,
                                            "resolved": _resolved,
                                            "confidence": decision.confidence,
                                            "reason": decision.reason,
                                        },
                                    )
                        except Exception as _recon_exc:  # noqa: BLE001
                            logger.warning(
                                "skill_intent_reconciler_failed: %s", _recon_exc
                            )
                # P0.3 codex P1-1 hardening — citation reconciliation 위해 원본 캡처.
                # engine 의 citations event 는 token 스트림 시작 전 emit (chrome 분리).
                # P11-17: 여러 citations event 가 와도 *누적* (plan path 가 kms+web
                # 두 step 의 hits 를 별도 event 로 emit). 옛 overwrite 동작은 마지막
                # event 만 남겨 reconcile 의 orphans 가 false-positive 로 발생.
                if ev == "citations" and isinstance(data, dict):
                    citem = data.get("items")
                    if isinstance(citem, list):
                        captured_citations.extend(
                            c for c in citem if isinstance(c, dict)
                        )
                # P11-17 — engine plan path 이 자체로 citations_finalized 를 emit
                # 하면 chat_v1 의 fallback reconcile 은 skip (중복 event 방지).
                if ev == "citations_finalized":
                    engine_emitted_finalized = True
                # PR-D — trace collector. _TRACE_KINDS 에 속한 event 만 영속.
                # token/delta/ack/login_brief/done 등 chrome 또는 본문 채널은 제외.
                if ev in _TRACE_KINDS:
                    trace_events.append({"event": ev, "data": data, "ts": _t.time()})
                # P0.2 (KMS-Plus) — Context Panel payload 별도 수집.
                # structured_block event 는 trace 에도 들어가고 (디버깅용),
                # chat_messages.structured_blocks 컬럼에도 들어가서 frontend
                # 가 reload 시 Context Panel 복원에 사용.
                #
                # P0.2 hardening: 수집 시점에서 count cap. 추가 cap 은
                # _cap_structured_blocks 로 INSERT 직전 한 번 더 — count 만
                # 막고 size 는 JSON 직렬화 비용 때문에 INSERT 직전 일괄 처리.
                if ev == "structured_block" and isinstance(data, dict):
                    if len(final_structured_blocks) < STRUCTURED_BLOCKS_MAX_COUNT:
                        final_structured_blocks.append(data)
                    elif not sb_cap_warned["warned"]:
                        sb_cap_warned["warned"] = True
                        logger.warning(
                            "structured_blocks count cap (%d) reached for "
                            "session %s; further blocks dropped",
                            STRUCTURED_BLOCKS_MAX_COUNT,
                            sid,
                        )
                # PR-B (❸) — citations single source-of-truth: engine 의 grounding
                # 결과만 사용. chat_v1 별도 검색 (옛 _fetch_citations_for_query) 제거.
                # engine 이 token 스트림 시작 전에 ``event: citations`` 를 송출하므로
                # 여기서는 그대로 forward 만 한다.
                # PR-A 의 chat_v1 단 retrieval gate 도 함수 제거로 자연 무효 — engine
                # 이 이미 동일 게이트 (SkillV2.retrieval 메타 + intent classifier 안전망)
                # 를 통과시킨 grounding 결과만 emit 하므로 단의 게이트가 불필요.
                #
                # 2026-05-08 D21 (사용자 보고) — stream chunk sanitize 누락 fix.
                # token chunk 는 raw 송출 (변경 0), done event payload 에
                # ``final_text`` (normalize + sanitize) 주입 → frontend 가 done 시
                # 누적 buffer 를 final_text 로 교체. KRX 봇 답변에 raw `### 1.` /
                # `$\rightarrow$` 노출 결함 차단 (D18-v2 + 15750d2 사후 fix).
                if ev == "done":
                    try:
                        _final_raw = "".join(final_text_parts)
                        if _final_raw:
                            from src.common.text.markdown_normalizer import (
                                normalize_markdown,
                            )
                            from src.common.text.latex_sanitizer import (
                                sanitize_latex_to_unicode,
                            )
                            _final_clean = sanitize_latex_to_unicode(
                                normalize_markdown(_final_raw).strip()
                            )
                            # data 가 None / dict 어느 쪽이든 안전하게 새 dict 합성.
                            _done_data = dict(data) if isinstance(data, dict) else {}
                            _done_data["final_text"] = _final_clean
                            yield _sse(ev, _done_data)
                            continue
                    except Exception:
                        # 후처리 실패 시 raw done 그대로 (frontend fallback 동작).
                        logger.exception(
                            "done_event_final_text_inject_failed (session=%s)",
                            sid,
                        )
                yield _sse(ev, data)

            # T-INTEGRATE / P2-1: engine.turn() 루프 종료 후 latency_probe emit.
            # done event 이후에 emit — frontend 는 listen 안 함 (observability 전용).
            # 백엔드 로그 / replay 분석 도구만 수집. SSE stream 이 이미 done 으로
            # 닫혔어도 backend observability pipeline 은 수신 가능.
            # P3-1: finalize_derived_phases — SSE event timeline 에서 sub-phase 도출
            # (intent_classifier / plan_generator / answer_compose_finalize).
            if _probe_enabled:
                probe.record_phase("engine_turn", _turn_started, _t.time())
                probe.finalize_derived_phases(_turn_started)
                yield _sse("latency_probe", probe.to_sse_payload())

            # P0.3 codex P1-1 — 토큰 스트림 종료 직후 reconciled citations 송출.
            # done 이벤트보다 *앞* 에 와야 frontend 가 done 신호로 stream 종료 처리
            # 하기 전에 받음. orphans (본문엔 [N] 박혔지만 매칭 citation 없음) 는
            # WARNING 로그로 운영 가시성 확보.
            if captured_citations and not engine_emitted_finalized:
                from src.agent_framework.runtime.grounding import (
                    reconcile_citation_references,
                )
                body_so_far = "".join(final_text_parts)
                reconciled, orphans = reconcile_citation_references(
                    captured_citations, body_so_far
                )
                if orphans:
                    logger.warning(
                        "citation marker orphans for session %s — body has %s "
                        "but no matching citation item",
                        sid,
                        orphans,
                    )
                # trace 에도 reconciled 결과를 기록 — reload 시 동일 정합 사용 가능.
                trace_events.append({
                    "event": "citations_finalized",
                    "data": {"items": reconciled, "orphans": orphans},
                    "ts": _t.time(),
                })
                yield _sse(
                    "citations_finalized",
                    {"items": reconciled, "orphans": orphans},
                )
        finally:
            # assistant 메시지 저장 (스트림 종료 후)
            assistant_text = "".join(final_text_parts).strip()
            if assistant_text:
                # 2026-05-08 — markdown 정합성 후처리. heading/표 앞 빈 줄 자동
                # 보장 (LLM 답변에 raw `###` 노출 결함 차단). idempotent.
                # GPT-5 Phase 1 §5: normalize 가 선두에 빈 줄 추가할 가능성 있어
                # *후* strip() 한 번 더 — 선두/말미 공백 정리.
                try:
                    from src.common.text.markdown_normalizer import (
                        normalize_markdown,
                    )
                    assistant_text = normalize_markdown(assistant_text).strip()
                except Exception:
                    # normalizer 결함이 저장 흐름 끊지 않도록 swallow.
                    pass
                # 2026-05-08 — LaTeX → 유니코드 변환 (D18-v2 hook 누락 fix).
                # `$\rightarrow$` raw 노출 차단. normalize 후 적용.
                try:
                    from src.common.text.latex_sanitizer import (
                        sanitize_latex_to_unicode,
                    )
                    assistant_text = sanitize_latex_to_unicode(assistant_text)
                except Exception:
                    pass
                # D65 (2026-05-12) — tool_scope_filter INSERT 직전 적용. role agent 의
                # 응답이 *없는 도구 영역* 행위 제안 패턴이면 T3 셀프가이드로 치환.
                # engine 의 _persist_turn 은 session_store (Redis) 만 sanitize 하므로,
                # chat_messages DB 본도 별도로 sanitize 필요. agent_context 가 set 됐고
                # admin 이 아닐 때만 적용 (회귀 안전).
                try:
                    if agent_context is not None and not agent_context.is_admin:
                        from src.agent_framework.runtime.tool_scope_filter import (
                            scope_filter_apply,
                        )
                        # D82-A — final_structured_blocks 안 tool_result block 추출
                        # → evidence 검증용. block 구조: {"type": "tool_result",
                        # "tool": ..., "result": ...}.
                        #
                        # D82-A 사후 GPT-5.5 #A (2026-05-13) — `tool_call` block 제외:
                        # `tool_call` 은 *실행 요청/preview* 일 수 있어 그 자체로는
                        # state-change evidence 가 될 수 없다. evidence pool 에서
                        # *원천 배제*. 추가로 block_type 필드를 보존해
                        # _has_strong_state_evidence 의 방어 가드가 동작하도록 함.
                        _tool_results_for_scope: list[dict] = []
                        for _b in (final_structured_blocks or []):
                            if not isinstance(_b, dict):
                                continue
                            _btype = (_b.get("type") or "").lower()
                            if _btype != "tool_result":
                                # tool_call 또는 기타 block type 은 evidence 아님 — 제외.
                                continue
                            _tool_results_for_scope.append(
                                {
                                    "tool": _b.get("tool") or _b.get("name") or "",
                                    "name": _b.get("name") or _b.get("tool") or "",
                                    "result": _b.get("result") or {},
                                    "status": (
                                        _b.get("status")
                                        or (_b.get("result") or {}).get("status")
                                        or ""
                                    ),
                                    "block_type": _btype,
                                }
                            )
                        _orig_len = len(assistant_text)
                        assistant_text = scope_filter_apply(
                            assistant_text,
                            agent_context.allowed_tools or [],
                            tool_results=_tool_results_for_scope or None,
                        )
                        if len(assistant_text) != _orig_len:
                            logger.info(
                                "tool_scope_filter_applied path=chat_v1.INSERT "
                                "agent_id=%s original_len=%d filtered_len=%d",
                                str(agent_context.agent_id),
                                _orig_len,
                                len(assistant_text),
                            )
                except Exception as _tfe:
                    logger.warning("tool_scope_filter_failed in chat_v1: %s", _tfe)
                # D68 (2026-05-12) — adversarial false-confirm 차단 chat_v1 INSERT path
                # 도 동일 적용 (이중 안전장치). admin 봇 포함 *모든* agent — D66 #258
                # A04 (admin 25000원) 같은 적대적 prompt injection 차단.
                # GPT-5 권고 (2026-05-12 사전 diff verdict): chat_v1 path 는 tool_results
                # 직접 접근 불가 → final_structured_blocks 안에 type="tool_call" 또는
                # "tool_result" 가 *없을 때만* 적용 (정상 도구 호출 후 등록완료 응답을
                # false-positive 로 차단하지 않도록).
                try:
                    _has_tool_signal = any(
                        (b.get("type") or "") in {"tool_call", "tool_result"}
                        for b in (final_structured_blocks or [])
                    )
                    if not _has_tool_signal:
                        from src.agent_framework.runtime.adversarial_checker import (
                            adversarial_apply,
                        )
                        _orig_adv_len = len(assistant_text)
                        _adv_text, _adv_replaced = adversarial_apply(
                            body.text or "", assistant_text, None
                        )
                        if _adv_replaced:
                            logger.warning(
                                "adversarial_checker_applied path=chat_v1.INSERT "
                                "agent_id=%s original_len=%d replaced_len=%d "
                                "user_excerpt=%s",
                                str(agent_context.agent_id) if agent_context else "admin",
                                _orig_adv_len,
                                len(_adv_text),
                                (body.text or "")[:80],
                            )
                            assistant_text = _adv_text
                except Exception as _ae:
                    logger.warning("adversarial_checker_failed in chat_v1: %s", _ae)
                # P0.2 hardening — INSERT 직전 size cap 일괄 적용.
                capped_sb = _cap_structured_blocks(final_structured_blocks)
                if len(capped_sb) < len(final_structured_blocks) and not sb_cap_warned["warned"]:
                    sb_cap_warned["warned"] = True
                    logger.warning(
                        "structured_blocks size cap reached for session %s; "
                        "%d/%d blocks persisted",
                        sid,
                        len(capped_sb),
                        len(final_structured_blocks),
                    )
                # P0.2 hardening (P2-8) — structured_blocks 컬럼 미존재
                # (구 DB / rolling deploy 중간) 에서도 INSERT 가 깨지지 않게
                # try/except 후 컬럼 없는 INSERT 로 fallback.
                try:
                    async with db.begin() as conn2:
                        # PR-D — trace JSONB 동시 INSERT. CAST(:trace AS JSONB) 로
                        # 명시 캐스트 (psycopg2 + asyncpg 둘 다 안전).
                        await conn2.execute(
                            text(
                                """
                                INSERT INTO chat_messages
                                  (session_id, role, content, intent, trace,
                                   structured_blocks)
                                VALUES (:sid, 'assistant', :content, :intent,
                                        CAST(:trace AS JSONB),
                                        CAST(:sb AS JSONB))
                                """
                            ),
                            {
                                "sid": sid,
                                "content": assistant_text,
                                "intent": captured_intent,
                                "trace": json.dumps(trace_events),
                                "sb": json.dumps(capped_sb),
                            },
                        )
                        await conn2.execute(
                            text(
                                "UPDATE chat_sessions SET updated_at = now() "
                                "WHERE id = :sid"
                            ),
                            {"sid": sid},
                        )
                except Exception as e:
                    # 컬럼 없는 환경 fallback. structured_blocks / trace 둘 중
                    # 하나가 미존재해도 본 INSERT 가 실패할 수 있음.
                    msg = str(e).lower()
                    if "structured_blocks" in msg or "undefinedcolumn" in msg or "column" in msg:
                        logger.warning(
                            "chat_messages INSERT fallback (column missing): %s",
                            e,
                        )
                        async with db.begin() as conn2:
                            await conn2.execute(
                                text(
                                    "INSERT INTO chat_messages "
                                    "  (session_id, role, content, intent) "
                                    "VALUES (:sid, 'assistant', :content, :intent)"
                                ),
                                {
                                    "sid": sid,
                                    "content": assistant_text,
                                    "intent": captured_intent,
                                },
                            )
                            await conn2.execute(
                                text(
                                    "UPDATE chat_sessions SET updated_at = now() "
                                    "WHERE id = :sid"
                                ),
                                {"sid": sid},
                            )
                    else:
                        raise

    return StreamingResponse(stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# PR-B (❸) — 옛 _fetch_citations_for_query 제거.
# citations single source-of-truth = engine grounding (engine.turn 이 token 스트림
# 시작 전에 ``event: citations`` 를 송출). chat_v1 의 별도 검색은 답변 본문과
# 다른 결과를 만들어 inconsistency 를 야기하던 원인이라 통째로 제거.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 1 Task 6 — external_agent webhook 진입점용 helper.
#
# webhook router (external_agent_v1.py) 가 channel → agent → chat 처리까지
# 이 helper 를 통해 단일 경로로 수렴. 기존 chat_message dispatcher 와 동일한
# engine.turn() 경로 — agent_context 를 effective_text 에 inject 한 뒤 호출.
# ---------------------------------------------------------------------------


async def _handle_external_agent_message(
    *,
    text: str,
    agent_context: "Any",  # AgentContext — circular import 방지 위해 Any
    tenant_id: "UUID",
    session_id: str,
    engine: "Any",  # AgentEngine
    # 059 — chat_sessions 통합 (옵션 B, 2026-05-07 spec).
    # internal_account_id 가 set 이면 (mapping 매칭된 admin 사용자) chat_sessions
    # row 보장 + chat_messages 에 user/assistant INSERT. None (guest) 이면 engine
    # 내부 처리만 (현 동작 유지) — 권한 누설 방지.
    internal_account_id: "UUID | None" = None,
    channel_kind: str | None = None,
    channel_id: "UUID | None" = None,
    external_user_id: str | None = None,
    agent_id: "UUID | None" = None,
    # Phase 1.5A Task 7 — SenderContext. None 시 engine.turn 은 기존 default.
    sender: "Any" = None,
    # webhook account_id 자동 주입 (mail.send/diary/expense 등 user-scoped 도구용).
    # mapping.internal_account_id 가 set 인 경우 caller 가 str 로 변환해 전달 →
    # engine.tool_loop 의 args["account_id"] 자동 주입 활성화. None 이면 기존 동작.
    account_id_hint: str | None = None,
) -> "AsyncIterable[dict]":
    """webhook 진입 → engine.turn() SSE 스트림 반환.

    agent_context.to_prompt_section() 을 effective_text 선두에 주입.
    token/delta 이벤트만 가공 없이 그대로 yield — caller (webhook router) 가
    adapter.collect_response() 로 채널 메시지 변환.

    agent_context=None 은 호출하지 않는 것이 원칙 (webhook 경로는 항상 agent 존재).

    **chat_sessions 통합** (059, spec 2026-05-07):
    - ``internal_account_id`` 가 set: chat_sessions 1행 보장 + user 메시지
      즉시 INSERT, assistant 메시지는 stream 종료 시 누적 INSERT.
    - ``internal_account_id`` 가 None: 기존 동작 (engine 만, DB row X).
    """
    # mail-send-2 디버그 — webhook→chat_v1 도달 추적. account_id_hint 가 정상
    # 전달되는지 (None 인지) 확인.
    logger.info(
        "handle_external_agent_message_entry session=%s account_id_hint=%s "
        "internal_account_id=%s sender_kind=%s channel_kind=%s agent_id=%s",
        session_id,
        account_id_hint,
        str(internal_account_id) if internal_account_id else None,
        getattr(sender, "trust_tier", None) if sender is not None else None,
        channel_kind,
        str(agent_id) if agent_id else None,
    )
    agent_section = agent_context.to_prompt_section() if agent_context is not None else ""
    effective = (
        f"[에이전트 컨텍스트]\n{agent_section}\n\n[현재 사용자 발화]\n{text}"
        if agent_section
        else text
    )

    # internal_account_id 가 set 이면 chat_sessions 보장 + user INSERT.
    chat_sid: UUID | None = None
    if internal_account_id is not None:
        try:
            chat_sid = await _ensure_channel_session(
                account_id=internal_account_id,
                channel_kind=channel_kind or "custom",
                channel_id=channel_id,
                external_user_id=external_user_id,
                agent_id=agent_id,
            )
            await _insert_chat_message_user(chat_sid, content=text)
        except Exception:
            # 영속화 실패는 채팅 실패가 아님 — log + 계속 진행.
            logger.exception(
                "channel chat_sessions persist failed (continuing without persistence): "
                "account=%s channel_kind=%s channel_id=%s",
                internal_account_id,
                channel_kind,
                channel_id,
            )
            chat_sid = None

    # 058 — agent_context 를 engine 에 직접 전달 → admin bypass 가능.
    # Phase 1.5A Task 7 — sender 도 함께 전달. None 이면 engine 내부 default.
    collected: list[str] = []
    async for item in engine.turn(
        session_id,
        str(tenant_id),
        effective,
        agent_context=agent_context,
        sender=sender,
        account_id_hint=account_id_hint,
    ):
        # token/delta event 누적 — assistant 메시지 INSERT 용.
        if chat_sid is not None:
            ev = item.get("event", "message") if isinstance(item, dict) else "message"
            data = item.get("data", {}) if isinstance(item, dict) else {}
            if ev in ("token", "delta") and isinstance(data, dict):
                chunk = data.get("text") or data.get("delta") or ""
                if chunk:
                    collected.append(chunk)
        yield item

    # stream 종료 후 assistant 메시지 INSERT.
    if chat_sid is not None:
        assistant_text = "".join(collected).strip()
        if assistant_text:
            try:
                await _insert_chat_message_assistant(chat_sid, content=assistant_text)
            except Exception:
                logger.exception(
                    "channel assistant message persist failed (chat_session=%s)",
                    chat_sid,
                )


# ---------------------------------------------------------------------------
# 059 — chat_sessions 채널 통합 helpers
# ---------------------------------------------------------------------------


async def _ensure_channel_session(
    *,
    account_id: UUID,
    channel_kind: str,
    channel_id: UUID | None,
    external_user_id: str | None,
    agent_id: UUID | None,
) -> UUID:
    """(account_id, channel_kind, channel_id, external_user_id) 매칭 chat_sessions
    row 가 있으면 id 반환 (+ updated_at touch), 없으면 INSERT.

    텔레그램은 thread 가 아닌 single chat UX → 영구 1 session 정책 (spec §10).
    """
    db = _get_engine()
    # tenant_id 는 account.personal_tenant_id 사용 — 웹 chat_sessions 와 동일 anchor.
    async with db.begin() as conn:
        # R5 (2026-05-07) — LOOKUP 에 agent_id 까지 포함. (account, channel,
        # channel_id, external_user_id) 조합이 동일해도 *다른 agent* 가 매핑된
        # 채널 webhook 진입 시 이전 agent 의 session 을 재사용하던 잠재 결함
        # (agent 매핑 변경 또는 동일 user 다중 봇 운영 시) 차단. agent_id IS NULL
        # row 도 동일 user 가 처음 진입했을 때만 1번 매칭 — 그 이후 첫 매칭에서
        # agent_id 가 채워지면 다음 turn 부터 격리.
        row = (
            await conn.execute(
                text(
                    """
                    SELECT id, agent_id FROM chat_sessions
                    WHERE account_id = :aid
                      AND channel_kind = :ck
                      AND channel_id IS NOT DISTINCT FROM :cid
                      AND external_user_id IS NOT DISTINCT FROM :eu
                      AND (agent_id IS NOT DISTINCT FROM :agid OR agent_id IS NULL)
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "aid": account_id,
                    "ck": channel_kind,
                    "cid": channel_id,
                    "eu": external_user_id,
                    "agid": agent_id,
                },
            )
        ).first()
        if row is not None:
            sid = row[0]
            existing_agent_id = row[1]
            # R5 — agent_id 가 NULL 인 row 발견 시 즉시 backfill. 다음 turn 부터
            # 정상적으로 (agent_id 일치) 격리.
            if existing_agent_id is None and agent_id is not None:
                await conn.execute(
                    text(
                        "UPDATE chat_sessions SET agent_id = :agid, updated_at = now() "
                        "WHERE id = :sid"
                    ),
                    {"agid": agent_id, "sid": sid},
                )
            else:
                await conn.execute(
                    text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"),
                    {"sid": sid},
                )
            return sid

        # 신규 session — account 의 personal_tenant_id 를 anchor 로.
        tenant_row = (
            await conn.execute(
                text(
                    "SELECT personal_tenant_id FROM accounts WHERE id = :aid LIMIT 1"
                ),
                {"aid": account_id},
            )
        ).first()
        if not tenant_row:
            raise RuntimeError(
                f"_ensure_channel_session: account {account_id} not found"
            )
        tenant_id = tenant_row[0]
        ins = await conn.execute(
            text(
                """
                INSERT INTO chat_sessions
                  (account_id, tenant_id, channel_kind, channel_id,
                   external_user_id, agent_id)
                VALUES (:aid, :tid, :ck, :cid, :eu, :agid)
                RETURNING id
                """
            ),
            {
                "aid": account_id,
                "tid": tenant_id,
                "ck": channel_kind,
                "cid": channel_id,
                "eu": external_user_id,
                "agid": agent_id,
            },
        )
        return ins.scalar_one()


async def _insert_chat_message_user(session_id: UUID, *, content: str) -> None:
    """user 메시지 1건 INSERT. session updated_at 동시 touch."""
    db = _get_engine()
    async with db.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES (:sid, 'user', :content)
                """
            ),
            {"sid": session_id, "content": content},
        )
        await conn.execute(
            text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"),
            {"sid": session_id},
        )


async def _insert_chat_message_assistant(session_id: UUID, *, content: str) -> None:
    """assistant 메시지 1건 INSERT. structured_blocks 컬럼 미존재 환경 fallback 포함."""
    # 2026-05-08 — markdown 정합성 후처리 (heading/표 앞 빈 줄 보장).
    # idempotent — 호출자가 미리 normalize 했어도 안전.
    try:
        from src.common.text.markdown_normalizer import normalize_markdown
        content = normalize_markdown(content)
    except Exception:
        pass
    # 2026-05-08 — LaTeX → 유니코드 (D18-v2 hook 누락 fix).
    # `$\rightarrow$` raw 노출 차단. normalize 후 적용. idempotent.
    try:
        from src.common.text.latex_sanitizer import sanitize_latex_to_unicode
        content = sanitize_latex_to_unicode(content)
    except Exception:
        pass
    db = _get_engine()
    try:
        async with db.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO chat_messages (session_id, role, content)
                    VALUES (:sid, 'assistant', :content)
                    """
                ),
                {"sid": session_id, "content": content},
            )
            await conn.execute(
                text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"),
                {"sid": session_id},
            )
    except Exception:
        logger.exception(
            "channel assistant chat_messages INSERT failed (session=%s)",
            session_id,
        )


# ---------------------------------------------------------------------------
# /chat/briefing — 아침 브리핑
# ---------------------------------------------------------------------------


@router.get("/briefing")
async def briefing(
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """오늘 일정 + 최근 뉴스 + 최근 일기 요약. agent_data 가 비어있으면 인사만."""
    aid, tid = _scope(authorization, x_tenant_id)
    db = _get_engine()
    cards: list[dict] = []
    schedule_count = 0
    diary_count = 0
    news_count = 0
    async with db.begin() as conn:
        # 오늘 일정 — agent_data 의 documents 에 doctype=agent_schedule 인 것
        try:
            r = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM documents d
                        JOIN repositories r ON d.repository_id = r.id
                        JOIN document_types t ON d.document_type_id = t.id
                        WHERE r.tenant_id = :tid
                          AND t.name = 'agent_schedule'
                          AND d.status = 'active'
                        """
                    ),
                    {"tid": tid},
                )
            ).first()
            schedule_count = int(r[0]) if r else 0
        except Exception:
            pass
        try:
            r = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM documents d
                        JOIN repositories r ON d.repository_id = r.id
                        JOIN document_types t ON d.document_type_id = t.id
                        WHERE r.tenant_id = :tid
                          AND t.name = 'agent_diary'
                          AND d.status = 'active'
                        """
                    ),
                    {"tid": tid},
                )
            ).first()
            diary_count = int(r[0]) if r else 0
        except Exception:
            pass
        try:
            r = (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM documents d
                        JOIN repositories r ON d.repository_id = r.id
                        JOIN document_types t ON d.document_type_id = t.id
                        WHERE r.tenant_id = :tid
                          AND t.name = 'agent_news_sub'
                          AND d.status = 'active'
                        """
                    ),
                    {"tid": tid},
                )
            ).first()
            news_count = int(r[0]) if r else 0
        except Exception:
            pass

    parts: list[str] = ["좋은 하루입니다."]
    if schedule_count:
        parts.append(f"오늘 일정 {schedule_count}건이 있습니다.")
        cards.append({"type": "schedule_summary", "count": schedule_count})
    if diary_count:
        parts.append(f"최근 일기 {diary_count}건을 확인할 수 있어요.")
    if news_count:
        parts.append(f"구독 중인 뉴스 주제 {news_count}개에서 새 소식을 가져올 수 있습니다.")
        cards.append({"type": "news_subscriptions", "count": news_count})
    if not (schedule_count or diary_count or news_count):
        parts.append("오늘 시작할 일을 알려주세요. 일정·메모·검색 모두 도와드립니다.")

    return {
        "message": " ".join(parts),
        "cards": cards,
        "intent": "morning_briefing",
        "stats": {
            "schedules": schedule_count,
            "diaries": diary_count,
            "news_subscriptions": news_count,
        },
    }


# ---------------------------------------------------------------------------
# /chat/onboarding — 4-step state machine
# ---------------------------------------------------------------------------


class OnboardingRequest(BaseModel):
    step: int = Field(..., ge=0, le=4)
    session_id: str | None = None
    response: str | None = None
    selections: list[str] = Field(default_factory=list)


_ONBOARDING_STEPS: dict[int, dict[str, Any]] = {
    0: {
        "message": "안녕하세요! 처음 오셨네요. 함께 시작해 볼까요?",
        "next_step": 1,
        "cards": [{"type": "onboarding_intro"}],
    },
    1: {
        "message": "이름이 어떻게 되세요? 편하게 부를 호칭이면 됩니다.",
        "next_step": 2,
        "cards": [],
    },
    2: {
        "message": "오늘 가장 도움이 필요한 영역은 어떤 건가요?",
        "next_step": 3,
        "cards": [
            {"type": "choice", "options": ["업무 자료 검색", "일정 관리", "메모/일기", "뉴스 요약", "기타"]},
        ],
    },
    3: {
        "message": "원하는 답변 톤은 어떤가요?",
        "next_step": 4,
        "cards": [
            {"type": "choice", "options": ["격식체", "친근체", "간결체"]},
        ],
    },
    4: {
        "message": "준비 완료! 무엇이든 편하게 물어보세요.",
        "next_step": 4,
        "cards": [],
        "completed": True,
    },
}


@router.post("/onboarding")
async def onboarding(
    body: OnboardingRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    """간단 state machine. 사용자 응답은 user_life_context 에 저장."""
    aid, tid = _scope(authorization, x_tenant_id)
    cfg = _ONBOARDING_STEPS.get(body.step) or _ONBOARDING_STEPS[0]

    # 사용자가 보낸 응답을 컨텍스트로 저장 (step 1~3)
    if body.response or body.selections:
        db = _get_engine()
        title_map = {1: "호칭", 2: "관심 영역", 3: "선호 톤"}
        title = title_map.get(body.step, f"onboarding_step_{body.step}")
        content = body.response or ", ".join(body.selections)
        try:
            async with db.begin() as conn:
                await conn.execute(
                    text(
                        """
                        INSERT INTO user_life_context
                          (account_id, category, title, content, metadata)
                        VALUES
                          (:aid, 'onboarding', :title, :content, CAST(:meta AS jsonb))
                        """
                    ),
                    {
                        "aid": aid,
                        "title": title,
                        "content": content,
                        "meta": json.dumps({"step": body.step, "selections": body.selections}),
                    },
                )
        except Exception:
            # 저장 실패해도 onboarding 진행은 계속
            pass

    return {
        "step": cfg["next_step"],
        "message": cfg["message"],
        "cards": cfg.get("cards", []),
        "completed": cfg.get("completed", False),
    }


# ---------------------------------------------------------------------------
# /chat/confirm-capture — stub
# ---------------------------------------------------------------------------


class ConfirmCaptureRequest(BaseModel):
    capture_id: str | None = None
    accepted: bool = True
    edits: dict[str, Any] | None = None


@router.post("/confirm-capture")
async def confirm_capture(
    body: ConfirmCaptureRequest,
    authorization: str = Header(...),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> dict:
    _scope(authorization, x_tenant_id)
    return {
        "ok": True,
        "capture_id": body.capture_id,
        "accepted": body.accepted,
        "applied": False,
        "note": "capture pipeline 미구현 — 응답만 200 (P2 backlog)",
    }
