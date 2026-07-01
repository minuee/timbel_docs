"""account_bind guest tier — webhook 진입 시 phone column truncation 회귀 가드.

증상:
    warning   account_bind_failed
      error="(sqlalchemy.dialects.postgresql.asyncpg.Error)
            StringDataRightTruncationError:
            value too long for type character varying(32)
      [SQL: INSERT INTO accounts (id, phone, name, personal_tenant_id) ...
      [parameters: (..., None, UUID(...))]"

뿌리:
    webhook (channel_user_mappings.internal_user_id=NULL = guest tier) 이 진입하면
    engine.turn 의 account_bind fallback 이 ``phone=tenant_id`` 로
    ``get_or_create_account`` 를 호출 — tenant_id 가 UUID(36자) 면 phone
    VARCHAR(32) 컬럼 truncation 으로 실패. 결과: 매 webhook 마다 warning
    스팸 + sess.account_id/personal_tenant_id 가 모두 None 으로 남음.

PR-Q (2026-05-07) — guest tier 처리:
    tenant_id 가 UUID 형태이면 ``get_or_create_account`` 호출 자체를 생략
    (Phase 1.5A SenderContext 모델: guest = in-memory only). mapped admin 은
    Phase 2 에서 ``account_id_hint`` 경로로 진입하므로 영향 없음.

본 테스트는 LLM/Redis/DB 미의존 — engine.turn 의 새 세션 생성 분기까지만 가서
``get_or_create_account`` mock 호출 여부를 검증한다.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.runtime.session_store import SessionState
from src.agent_framework.tools.registry import ToolRegistry


class _FakeStore:
    """Redis 없이 SessionStore 인터페이스만 흉내 (메모리)."""

    def __init__(self) -> None:
        self._data: dict[str, SessionState] = {}

    async def get(self, session_id: str) -> SessionState | None:
        return self._data.get(session_id)

    async def put(self, state: SessionState) -> None:
        self._data[state.session_id] = state

    async def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)


def _build_minimal_engine() -> AgentEngine:
    """engine.turn 새 세션 분기까지 도달 가능한 최소 엔진. 그 이후
    intent/tool/response 경로는 본 테스트 관심사가 아니라 stub 으로 short-circuit."""
    from src.agent_framework.llm.fallback_router import FallbackDecision

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=[])

    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    fallback = AsyncMock()
    fallback.decide = AsyncMock(
        return_value=FallbackDecision(next_state="stay", response="ok")
    )

    response_gen = MagicMock()

    async def _stream(tpl: str, ctx: dict[str, Any], **kwargs):
        yield "ok"

    response_gen.stream = _stream

    async def _empty_tool_loop_run(*args, **kwargs):
        # tool_loop.run 은 async iterator. 본 테스트는 account_bind 분기까지만
        # 검증하므로 이벤트 0개 yield 후 즉시 종료.
        if False:  # pragma: no cover
            yield {}

    fake_tool_loop = MagicMock()
    fake_tool_loop.run = _empty_tool_loop_run

    return AgentEngine(
        session_store=_FakeStore(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry({}),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=fallback,
        intent_classifier=intent,
        tool_loop=fake_tool_loop,
    )


@pytest.mark.asyncio
async def test_webhook_uuid_tenant_id_skips_account_bind():
    """webhook 시뮬: tenant_id 가 UUID(36자) → ``get_or_create_account`` 미호출.

    이전 동작: phone=tenant_id 로 INSERT 시도 → varchar(32) truncation
              → ``account_bind_failed`` warning + account_id/personal_tenant_id None.
    신 동작:  guest tier 로 인지 → INSERT 자체 생략. session 은 tenant_id 만
              들고 살아남는다 (effective_personal_tenant_id 가 fallback).
    """
    engine = _build_minimal_engine()
    fake_tenant = str(uuid4())  # 36자 UUID — webhook 진입의 agent.tenant_id
    fake_session = f"wh-{uuid4()}-tg-12345"  # webhook session_id 형식

    with patch(
        "src.agent_framework.core.accounts.get_or_create_account",
        new=AsyncMock(side_effect=AssertionError(
            "guest tier 는 accounts 행 INSERT 를 시도하면 안 됨"
        )),
    ):
        # 새 세션 생성 — turn 안에서 account_bind 분기 도달.
        async for _ in engine.turn(fake_session, fake_tenant, "안녕"):
            pass  # 흐름만 통과하면 OK

    # 세션이 무사히 생성됐는지 확인 — tenant_id 는 살아있어야 한다.
    sess = await engine.session_store.get(fake_session)
    assert sess is not None, "세션 생성 실패"
    assert sess.tenant_id == fake_tenant
    assert sess.account_id is None, (
        "guest tier 는 account_id 가 None 이어야 함"
    )
    assert sess.personal_tenant_id is None, (
        "guest tier 는 personal_tenant_id 가 None 이어야 함"
    )
    # 핵심: effective_personal_tenant_id 가 tenant_id 로 fallback —
    # grounding/tool 경로는 그대로 동작.
    assert sess.effective_personal_tenant_id == fake_tenant


@pytest.mark.asyncio
async def test_phone_shaped_tenant_id_still_calls_account_bind():
    """기존 회귀 가드: tenant_id 가 phone 형태 (≤32자 비-UUID) 면 옛 fallback 유지.

    실제 운영에서 phone 이 tenant_id 자리에 들어오는 시나리오는 없지만
    legacy 호출자 (테스트/CLI) 가 phone 으로 호출하던 경로의 후방호환 유지.
    """
    engine = _build_minimal_engine()
    fake_phone = "010-1234-5678"  # 13자 — phone-shaped, not UUID
    fake_session = "sid-phone-legacy"

    fake_account_ctx = MagicMock()
    fake_account_ctx.account_id = uuid4()
    fake_account_ctx.personal_tenant_id = uuid4()

    with patch(
        "src.agent_framework.core.accounts.get_or_create_account",
        new=AsyncMock(return_value=fake_account_ctx),
    ) as mock_create:
        async for _ in engine.turn(fake_session, fake_phone, "안녕"):
            pass

        # phone 형태면 옛 경로대로 호출되어야 한다.
        mock_create.assert_awaited_once()
        kwargs = mock_create.await_args.kwargs
        args = mock_create.await_args.args
        called_phone = kwargs.get("phone") or (args[0] if args else None)
        assert called_phone == fake_phone


@pytest.mark.asyncio
async def test_account_id_hint_path_unaffected():
    """account_id_hint 가 주어지면 (web 로그인 경로) UUID/phone 무관 — DB lookup
    경로로 진입하고 ``get_or_create_account`` 는 호출되지 않는다.

    회귀 보호: 본 PR 의 fix 가 chat_v1 의 web login 경로에 영향 없음을 확인.
    """
    engine = _build_minimal_engine()
    fake_tenant = str(uuid4())
    fake_account_id = str(uuid4())
    fake_session = "sid-web-login"

    # account_id_hint 경로의 DB lookup 은 inline 으로 sqlalchemy create_async_engine
    # 을 만들어 SELECT 한다 — 그 부분을 통째로 stub.
    fake_engine = MagicMock()
    fake_conn = AsyncMock()
    fake_row = MagicMock()
    fake_row.__getitem__ = lambda self, i: [
        "010-7777-8888",  # phone
        uuid4(),  # personal_tenant_id
        {},  # preferences
    ][i]
    fake_result = MagicMock()
    fake_result.first = MagicMock(return_value=fake_row)
    fake_conn.execute = AsyncMock(return_value=fake_result)

    class _AsyncCM:
        async def __aenter__(self_inner):
            return fake_conn

        async def __aexit__(self_inner, *a):
            return False

    fake_engine.begin = MagicMock(return_value=_AsyncCM())
    fake_engine.dispose = AsyncMock()

    with (
        patch(
            "sqlalchemy.ext.asyncio.create_async_engine",
            return_value=fake_engine,
        ),
        patch(
            "src.agent_framework.core.accounts.get_or_create_account",
            new=AsyncMock(side_effect=AssertionError(
                "account_id_hint 경로에서는 get_or_create_account 가 호출되면 안 됨"
            )),
        ),
    ):
        async for _ in engine.turn(
            fake_session,
            fake_tenant,
            "안녕",
            account_id_hint=fake_account_id,
        ):
            pass

    sess = await engine.session_store.get(fake_session)
    assert sess is not None
    assert sess.account_id == fake_account_id


@pytest.mark.asyncio
async def test_resume_with_hint_rebinds_stale_account_id():
    """mail-send-2 fix 회귀 가드 — resume 시 sess.account_id=None 이고 hint 가
    있으면 rebind 한다.

    뿌리: webhook 첫 turn 이 mapping.internal_account_id 비어 있던 시점에
    생성되어 sess.account_id 가 None 으로 굳었던 경우. mapping 이 채워진 후에도
    resume 분기는 lookup 을 안 해 mail.send 가 영구 실패하던 결함.

    fix: resume 분기에서 ``account_id_hint and not sess.account_id`` 면
    ``_lookup_account_by_hint`` 을 호출해 sess 를 즉시 rebind.
    """
    engine = _build_minimal_engine()
    fake_tenant = str(uuid4())
    fake_account_id = str(uuid4())
    fake_session = "sid-resume-stale"

    # stale session 미리 적재 — account_id=None.
    stale = SessionState(
        session_id=fake_session,
        skill_id=None,
        current_state=None,
        slots={},
        history=[{"role": "user", "content": "이전 발화", "ts": None}],
        tenant_id=fake_tenant,
        identity=None,
        account_id=None,
        personal_tenant_id=None,
    )
    await engine.session_store.put(stale)

    # _lookup_account_by_hint 의 DB SELECT 를 mock — phone + personal_tenant_id 채움.
    fake_engine = MagicMock()
    fake_conn = AsyncMock()
    fake_pt = uuid4()
    fake_row = MagicMock()
    fake_row.__getitem__ = lambda self, i: [
        "010-1111-2222",
        fake_pt,
        {"user_groups": ["admin"]},
    ][i]
    fake_result = MagicMock()
    fake_result.first = MagicMock(return_value=fake_row)
    fake_conn.execute = AsyncMock(return_value=fake_result)

    class _AsyncCM:
        async def __aenter__(self_inner):
            return fake_conn

        async def __aexit__(self_inner, *a):
            return False

    fake_engine.begin = MagicMock(return_value=_AsyncCM())
    fake_engine.dispose = AsyncMock()

    with patch(
        "sqlalchemy.ext.asyncio.create_async_engine",
        return_value=fake_engine,
    ):
        async for _ in engine.turn(
            fake_session,
            fake_tenant,
            "발송해줘",
            account_id_hint=fake_account_id,
        ):
            pass

    sess = await engine.session_store.get(fake_session)
    assert sess is not None
    assert sess.account_id == fake_account_id, (
        "resume 분기에서 rebind 실패 — hint 있는데 sess.account_id 가 여전히 None"
    )
    assert sess.personal_tenant_id == str(fake_pt)
    assert sess.identity is not None
    assert sess.identity.get("phone") == "010-1111-2222"
    assert sess.identity.get("user_groups") == ["admin"]


@pytest.mark.asyncio
async def test_resume_with_hint_skipped_when_already_bound():
    """sess.account_id 가 이미 set 이면 hint 가 와도 lookup 미호출 (불필요한 DB 부하 방지).

    회귀 가드 — fix 의 trigger 조건이 ``not sess.account_id`` 임을 보장.
    """
    engine = _build_minimal_engine()
    fake_tenant = str(uuid4())
    bound_account_id = str(uuid4())
    fake_session = "sid-resume-already-bound"

    bound = SessionState(
        session_id=fake_session,
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id=fake_tenant,
        identity={"phone": "010-9999-0000"},
        account_id=bound_account_id,
        personal_tenant_id=str(uuid4()),
    )
    await engine.session_store.put(bound)

    # create_async_engine 호출되면 fail — 이 케이스에서는 lookup 안 해야 정상.
    create_engine_mock = MagicMock(
        side_effect=AssertionError(
            "이미 account_id 가 bound 인데 _lookup_account_by_hint 가 호출됨"
        )
    )

    with patch(
        "sqlalchemy.ext.asyncio.create_async_engine",
        new=create_engine_mock,
    ):
        async for _ in engine.turn(
            fake_session,
            fake_tenant,
            "발송해줘",
            account_id_hint=str(uuid4()),  # 다른 hint — 그래도 무시.
        ):
            pass

    sess = await engine.session_store.get(fake_session)
    assert sess is not None
    assert sess.account_id == bound_account_id  # 변경 없음.
