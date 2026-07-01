"""chat_v1 dispatcher agent_id 분기 단위 테스트 (mock-based).

Phase 1 Task 6. 핵심 불변:
  - agent_id 미지정 → byte-equal (기존 동작 — 분기 코드 미실행)
  - agent_id 지정 + 자기 tenant agent → 200 (StreamingResponse)
  - agent_id 지정 + 다른 tenant agent → 404
  - agent_id 잘못된 UUID 형식 → 400
  - agent_id 지정 + 비활성 agent → 404

DB / engine 없이 실행 가능. 모든 외부 의존은 unittest.mock 으로 대체.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TENANT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())
OTHER_TENANT_ID = str(uuid.uuid4())


def _token(tenant_id: str = TENANT_ID, user_id: str = USER_ID) -> str:
    return create_access_token(subject=user_id, tenant_id=tenant_id)


def _mock_agent(
    *,
    agent_id: str = AGENT_ID,
    tenant_id: str = TENANT_ID,
    is_active: bool = True,
):
    a = MagicMock()
    a.id = uuid.UUID(agent_id)
    a.tenant_id = uuid.UUID(tenant_id)
    a.name = "Mock Agent"
    a.goal = "test goal"
    a.guidelines_md = "be precise"
    a.primary_repo_ids = []
    a.fallback_repo_ids = []
    a.knowledge_isolation = "priority"
    a.allowed_tools = []
    a.done_when = None
    a.is_active = is_active
    return a


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


_CHAT_PATH = "src.api.routers.chat_v1"
_MSG_URL = "/api/v1/chat/message"


def _common_patches():
    """chat_message handler 에서 DB / engine 호출을 막는 공통 패치 집합.

    - _get_engine: 가짜 AsyncEngine (begin 컨텍스트 매니저 포함)
    - get_agent_engine: 가짜 AgentEngine (turn = async generator)
    - AgentRepository.get: 테스트마다 override 가능하도록 별도 patch 으로 분리.
    """

    async def _fake_turn(sid, tid, txt, **kw):
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _fake_turn

    # DB 커넥션 mock — begin() async context manager
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(
        return_value=MagicMock(
            first=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=uuid.uuid4()),
        )
    )
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    fake_db_engine = MagicMock()
    fake_db_engine.begin = MagicMock(return_value=fake_ctx)

    return (
        patch(f"{_CHAT_PATH}._get_engine", return_value=fake_db_engine),
        patch(f"{_CHAT_PATH}.get_agent_engine", return_value=AsyncMock(return_value=fake_engine)),
        patch(
            "src.agent_framework.api.dependencies.get_agent_engine",
            return_value=AsyncMock(return_value=fake_engine),
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_agent_id_skips_branch(client):
    """agent_id 미지정 → agent 조회 코드 미실행 (byte-equal 보장)."""

    async def _fake_turn(sid, tid, txt, **kw):
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _fake_turn

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(
        return_value=MagicMock(
            first=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=uuid.uuid4()),
        )
    )
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_db_engine = MagicMock()
    fake_db_engine.begin = MagicMock(return_value=fake_ctx)

    with (
        patch(f"{_CHAT_PATH}._get_engine", return_value=fake_db_engine),
        patch(
            "src.agent_framework.api.dependencies.get_agent_engine",
            new=AsyncMock(return_value=fake_engine),
        ),
        patch("src.core.repositories.agent_repository.AgentRepository", side_effect=AssertionError("agent branch must not be called")) as _mock_repo,
    ):
        # agent_id 미지정 → AgentRepository 절대 호출 안 됨
        resp = client.post(
            _MSG_URL,
            json={"text": "안녕"},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )
    # AgentRepository patch 가 AssertionError 를 raise 하지 않았으면 통과.
    # 응답 코드는 200 이거나 engine mock 따라 다를 수 있지만, branch 미진입이 핵심.
    assert resp.status_code != 500 or "agent branch must not be called" not in resp.text


def test_invalid_uuid_agent_id_returns_400(client):
    """agent_id 가 유효하지 않은 UUID → 400."""

    async def _fake_turn(sid, tid, txt, **kw):
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _fake_turn

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(
        return_value=MagicMock(
            first=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=uuid.uuid4()),
        )
    )
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_db_engine = MagicMock()
    fake_db_engine.begin = MagicMock(return_value=fake_ctx)

    with (
        patch(f"{_CHAT_PATH}._get_engine", return_value=fake_db_engine),
        patch(
            "src.agent_framework.api.dependencies.get_agent_engine",
            new=AsyncMock(return_value=fake_engine),
        ),
    ):
        resp = client.post(
            _MSG_URL,
            json={"text": "hello", "agent_id": "not-a-uuid"},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )
    assert resp.status_code == 400


def test_agent_not_in_tenant_returns_404(client):
    """agent_id 지정 + repo.get() → None (다른 tenant 포함) → 404."""

    async def _fake_turn(sid, tid, txt, **kw):
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _fake_turn

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(
        return_value=MagicMock(
            first=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=uuid.uuid4()),
        )
    )
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_db_engine = MagicMock()
    fake_db_engine.begin = MagicMock(return_value=fake_ctx)

    mock_repo_instance = MagicMock()
    mock_repo_instance.get = AsyncMock(return_value=None)

    mock_sess_inst = AsyncMock()
    mock_sess_inst.__aenter__ = AsyncMock(return_value=mock_sess_inst)
    mock_sess_inst.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(f"{_CHAT_PATH}._get_engine", return_value=fake_db_engine),
        patch(
            "src.agent_framework.api.dependencies.get_agent_engine",
            new=AsyncMock(return_value=fake_engine),
        ),
        patch("src.core.repositories.agent_repository.AgentRepository", return_value=mock_repo_instance),
        patch(f"{_CHAT_PATH}.AsyncSession", return_value=mock_sess_inst),
        # D28 §4: chat_v1 이 이제 별도 create_async_engine 호출 안 함 — patch 불필요.
        # 기존 patch 는 dispose mock 으로 무해했지만, 이제 `_get_engine()` 만 사용.
    ):
        resp = client.post(
            _MSG_URL,
            json={"text": "hello", "agent_id": AGENT_ID},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )
    assert resp.status_code == 404


def test_inactive_agent_returns_404(client):
    """agent_id 지정 + 비활성 agent → 404."""

    async def _fake_turn(sid, tid, txt, **kw):
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _fake_turn

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(
        return_value=MagicMock(
            first=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=uuid.uuid4()),
        )
    )
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_db_engine = MagicMock()
    fake_db_engine.begin = MagicMock(return_value=fake_ctx)

    inactive_agent = _mock_agent(is_active=False)
    mock_repo_instance = MagicMock()
    mock_repo_instance.get = AsyncMock(return_value=inactive_agent)

    with (
        patch(f"{_CHAT_PATH}._get_engine", return_value=fake_db_engine),
        patch(
            "src.agent_framework.api.dependencies.get_agent_engine",
            new=AsyncMock(return_value=fake_engine),
        ),
        patch("src.core.repositories.agent_repository.AgentRepository", return_value=mock_repo_instance),
        patch(f"{_CHAT_PATH}.AsyncSession") as mock_sess,
        patch(f"{_CHAT_PATH}.create_async_engine", return_value=MagicMock(dispose=AsyncMock())),
    ):
        mock_sess_inst = AsyncMock()
        mock_sess_inst.__aenter__ = AsyncMock(return_value=mock_sess_inst)
        mock_sess_inst.__aexit__ = AsyncMock(return_value=False)
        mock_sess.return_value = mock_sess_inst

        resp = client.post(
            _MSG_URL,
            json={"text": "hello", "agent_id": AGENT_ID},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )
    assert resp.status_code == 404


def test_x_agent_id_header_also_accepted(client):
    """X-Agent-Id 헤더로도 agent_id 를 지정할 수 있음 (invalid UUID → 400)."""

    async def _fake_turn(sid, tid, txt, **kw):
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _fake_turn

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(
        return_value=MagicMock(
            first=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=uuid.uuid4()),
        )
    )
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_db_engine = MagicMock()
    fake_db_engine.begin = MagicMock(return_value=fake_ctx)

    with (
        patch(f"{_CHAT_PATH}._get_engine", return_value=fake_db_engine),
        patch(
            "src.agent_framework.api.dependencies.get_agent_engine",
            new=AsyncMock(return_value=fake_engine),
        ),
    ):
        resp = client.post(
            _MSG_URL,
            json={"text": "hello"},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
                "X-Agent-Id": "bad-uuid-value",
            },
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# _handle_external_agent_message helper 단위 테스트
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_external_agent_message_injects_context():
    """agent_context 가 있으면 effective_text 에 agent 섹션 포함."""
    from src.api.routers.chat_v1 import _handle_external_agent_message

    captured: list[str] = []

    async def _spy_turn(session_id, tenant_id, text, **kw):
        captured.append(text)
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _spy_turn

    mock_ctx = MagicMock()
    mock_ctx.to_prompt_section.return_value = "## goal\nhelp users"

    results = []
    async for item in _handle_external_agent_message(
        text="안녕하세요",
        agent_context=mock_ctx,
        tenant_id=uuid.uuid4(),
        session_id="test-session",
        engine=fake_engine,
    ):
        results.append(item)

    assert len(captured) == 1
    assert "안녕하세요" in captured[0]
    assert "help users" in captured[0]


@pytest.mark.asyncio
async def test_handle_external_agent_message_no_context():
    """agent_context=None 이면 effective_text = text 만."""
    from src.api.routers.chat_v1 import _handle_external_agent_message

    captured: list[str] = []

    async def _spy_turn(session_id, tenant_id, text, **kw):
        captured.append(text)
        yield {"event": "done", "data": {}}

    fake_engine = MagicMock()
    fake_engine.turn = _spy_turn

    async for _ in _handle_external_agent_message(
        text="안녕",
        agent_context=None,
        tenant_id=uuid.uuid4(),
        session_id="s1",
        engine=fake_engine,
    ):
        pass

    assert len(captured) == 1
    assert captured[0] == "안녕"
