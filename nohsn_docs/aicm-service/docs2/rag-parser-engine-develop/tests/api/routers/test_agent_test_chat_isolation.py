"""POST /api/v1/agents/{id}/test-chat — agent_context 격리 회귀.

CRITICAL fix (2026-05-07): test-chat endpoint 가 engine.turn 호출 시
``agent_context`` kwarg 를 전달 안 함 → 모든 격리 layer (Tool RAG / SOP RAG /
repo namespace / OOS policy) 우회. role agent 의 test mode 가 전체 tenant
repo 에서 검색 → 잘못된 산업 자료 반환.

본 테스트는 DB / engine 없이 mock 으로 검증:
  1. role agent test-chat 시 engine.turn 이 agent_context.kind='role' 로 호출.
  2. admin agent test-chat 시 agent_context.kind='admin' 로 호출.
  3. account_id_hint, sender, agent_context kwargs 모두 set.
  4. SenderContext.tier='admin' (운영자 진입 — JWT role admin/owner).
  5. 비활성 agent → 403, 다른 tenant agent → 404.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.agent_framework.api.dependencies import get_agent_engine
from src.api.auth.jwt_utils import create_access_token
from src.api.main import app


TENANT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())

_ROUTER_PATH = "src.api.routers.agents_v1"
_TEST_CHAT_URL = f"/api/v1/agents/{AGENT_ID}/test-chat"


def _token(*, tenant_id: str = TENANT_ID, user_id: str = USER_ID, role: str = "admin") -> str:
    return create_access_token(subject=user_id, tenant_id=tenant_id, role=role)


def _mock_agent_orm(
    *,
    agent_id: str = AGENT_ID,
    tenant_id: str = TENANT_ID,
    is_active: bool = True,
    kind: str = "role",
    name: str = "kbsoldier_advisor",
):
    """ORM Agent stub — AgentContext.from_agent 가 access 하는 attribute."""
    a = MagicMock()
    a.id = uuid.UUID(agent_id)
    a.tenant_id = uuid.UUID(tenant_id)
    a.name = name
    a.goal = "KB 장병내일적금 상담"
    a.guidelines_md = "## OOS\n- 적금 외 문의는 거절"
    a.primary_repo_ids = [uuid.UUID("11111111-0000-0000-0000-000000000003")]
    a.fallback_repo_ids = []
    a.knowledge_isolation = "strict"
    a.allowed_tools = ["kms_rag.search"]
    a.done_when = None
    a.is_active = is_active
    a.kind = kind
    a.delegate_to_agent_ids = []
    a.persona = ""
    a.system_prompt = ""
    return a


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_engine():
    """Engine fixture — FastAPI Depends override 로 주입.

    각 테스트가 ``fake_engine.turn`` 에 자기 _fake_turn 을 set 한 뒤 client
    호출. yield 후 dependency_overrides 정리.
    """
    eng = MagicMock()

    async def _default_turn(sid, tid, txt, **kw):
        yield {"event": "done", "data": {}}

    eng.turn = _default_turn

    async def _override():
        return eng

    app.dependency_overrides[get_agent_engine] = _override
    yield eng
    app.dependency_overrides.pop(get_agent_engine, None)


def _membership_db_mock():
    """tenant_memberships 조회용 가짜 DB engine."""
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(
        return_value=MagicMock(first=MagicMock(return_value=("admin",)))
    )
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_db = MagicMock()
    fake_db.begin = MagicMock(return_value=fake_ctx)
    return fake_db


def _patch_repo(agent_orm):
    repo_inst = MagicMock()
    repo_inst.get = AsyncMock(return_value=agent_orm)

    sess_inst = AsyncMock()
    sess_inst.__aenter__ = AsyncMock(return_value=sess_inst)
    sess_inst.__aexit__ = AsyncMock(return_value=False)

    return (
        patch(f"{_ROUTER_PATH}.AgentRepository", return_value=repo_inst),
        patch(f"{_ROUTER_PATH}.AsyncSession", return_value=sess_inst),
        patch(
            f"{_ROUTER_PATH}.create_async_engine",
            return_value=MagicMock(dispose=AsyncMock()),
        ),
        repo_inst,
    )


def test_role_agent_passes_agent_context_to_engine(client, fake_engine):
    """role agent test-chat → engine.turn 이 agent_context.kind='role' 로 호출."""
    captured: dict = {}

    async def _fake_turn(sid, tid, txt, **kw):
        captured["session_id"] = sid
        captured["tenant_id"] = tid
        captured["text"] = txt
        captured["agent_context"] = kw.get("agent_context")
        captured["sender"] = kw.get("sender")
        captured["account_id_hint"] = kw.get("account_id_hint")
        yield {"event": "done", "data": {}}

    fake_engine.turn = _fake_turn

    agent_orm = _mock_agent_orm(kind="role")
    repo_patches = _patch_repo(agent_orm)

    with (
        patch(f"{_ROUTER_PATH}._get_engine", return_value=_membership_db_mock()),
        repo_patches[0],
        repo_patches[1],
        repo_patches[2],
    ):
        resp = client.post(
            _TEST_CHAT_URL,
            json={"text": "배달이 지연 되는데 주문 취소 가능?"},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    # 핵심: agent_context 가 None 이 아니고 role kind.
    ctx = captured.get("agent_context")
    assert ctx is not None, "agent_context 가 engine.turn 에 전달돼야 함 (CRITICAL fix)"
    assert getattr(ctx, "kind", None) == "role"
    assert getattr(ctx, "is_admin", True) is False  # role agent 는 is_admin=False
    assert getattr(ctx, "name", None) == "kbsoldier_advisor"
    # 격리 layer 가 작동할 primary_repo_ids 가 보존돼야 함.
    assert len(getattr(ctx, "primary_repo_ids", [])) == 1
    assert getattr(ctx, "knowledge_isolation", None) == "strict"

    # account_id_hint 도 JWT sub 으로 채워져야 함.
    assert captured.get("account_id_hint") == USER_ID

    # sender 도 빌드돼야 함 — admin tier (운영자 진입).
    sender = captured.get("sender")
    assert sender is not None
    assert getattr(sender, "tier", None) == "admin"
    assert getattr(sender, "channel_kind", None) == "web"


def test_admin_agent_passes_agent_context_kind_admin(client, fake_engine):
    """admin agent test-chat → agent_context.kind='admin' 로 호출."""
    captured: dict = {}

    async def _fake_turn(sid, tid, txt, **kw):
        captured["agent_context"] = kw.get("agent_context")
        yield {"event": "done", "data": {}}

    fake_engine.turn = _fake_turn

    agent_orm = _mock_agent_orm(kind="admin", name="locus_admin")
    repo_patches = _patch_repo(agent_orm)

    with (
        patch(f"{_ROUTER_PATH}._get_engine", return_value=_membership_db_mock()),
        repo_patches[0],
        repo_patches[1],
        repo_patches[2],
    ):
        resp = client.post(
            _TEST_CHAT_URL,
            json={"text": "안녕"},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )

    assert resp.status_code == 200, resp.text
    ctx = captured.get("agent_context")
    assert ctx is not None
    assert getattr(ctx, "kind", None) == "admin"
    assert getattr(ctx, "is_admin", False) is True


def test_inactive_agent_returns_403(client, fake_engine):
    """비활성 agent → 403 (engine.turn 미호출)."""

    async def _fake_turn(sid, tid, txt, **kw):
        raise AssertionError("engine.turn 가 inactive agent 에 호출되면 안 됨")
        yield  # pragma: no cover

    fake_engine.turn = _fake_turn

    agent_orm = _mock_agent_orm(is_active=False)
    repo_patches = _patch_repo(agent_orm)

    with (
        patch(f"{_ROUTER_PATH}._get_engine", return_value=_membership_db_mock()),
        repo_patches[0],
        repo_patches[1],
        repo_patches[2],
    ):
        resp = client.post(
            _TEST_CHAT_URL,
            json={"text": "안녕"},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )
    assert resp.status_code == 403


def test_agent_not_in_tenant_returns_404(client, fake_engine):
    """repo.get() → None → 404."""
    repo_inst = MagicMock()
    repo_inst.get = AsyncMock(return_value=None)

    sess_inst = AsyncMock()
    sess_inst.__aenter__ = AsyncMock(return_value=sess_inst)
    sess_inst.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(f"{_ROUTER_PATH}._get_engine", return_value=_membership_db_mock()),
        patch(f"{_ROUTER_PATH}.AgentRepository", return_value=repo_inst),
        patch(f"{_ROUTER_PATH}.AsyncSession", return_value=sess_inst),
        patch(
            f"{_ROUTER_PATH}.create_async_engine",
            return_value=MagicMock(dispose=AsyncMock()),
        ),
    ):
        resp = client.post(
            _TEST_CHAT_URL,
            json={"text": "hello"},
            headers={
                "Authorization": f"Bearer {_token()}",
                "X-Tenant-ID": TENANT_ID,
            },
        )
    assert resp.status_code == 404


def test_no_cross_tenant_leak_via_test_chat(client, fake_engine):
    """다른 tenant agent → repo.get() return None (RowLevel 격리) → 404.

    cross-leak 0 검증 — agent_context 가 빌드되지 않으면 engine.turn 진입 자체
    가 차단돼야 함.
    """
    repo_inst = MagicMock()
    # AgentRepository.get(agent_id, tenant_id=tid) 는 다른 tenant agent 면 None.
    repo_inst.get = AsyncMock(return_value=None)

    sess_inst = AsyncMock()
    sess_inst.__aenter__ = AsyncMock(return_value=sess_inst)
    sess_inst.__aexit__ = AsyncMock(return_value=False)

    other_tenant = str(uuid.uuid4())

    with (
        patch(f"{_ROUTER_PATH}._get_engine", return_value=_membership_db_mock()),
        patch(f"{_ROUTER_PATH}.AgentRepository", return_value=repo_inst),
        patch(f"{_ROUTER_PATH}.AsyncSession", return_value=sess_inst),
        patch(
            f"{_ROUTER_PATH}.create_async_engine",
            return_value=MagicMock(dispose=AsyncMock()),
        ),
    ):
        # 사용자가 자기 tenant 의 agent_id 인 척 다른 tenant 의 agent 를 호출 시도.
        resp = client.post(
            _TEST_CHAT_URL,
            json={"text": "hello"},
            headers={
                "Authorization": f"Bearer {_token(tenant_id=other_tenant)}",
                "X-Tenant-ID": other_tenant,
            },
        )
    assert resp.status_code == 404
    # repo.get 가 정확히 (target_id, tenant_id=other_tenant) 로 호출됐는지.
    repo_inst.get.assert_awaited_once()
    call_kwargs = repo_inst.get.await_args.kwargs
    assert str(call_kwargs.get("tenant_id")) == other_tenant
