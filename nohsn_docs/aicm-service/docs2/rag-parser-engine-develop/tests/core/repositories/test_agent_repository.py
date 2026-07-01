import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from src.core.repositories.agent_repository import AgentRepository


@pytest.fixture
def fake_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_create_sets_tenant_and_creator(fake_db):
    repo = AgentRepository(fake_db)
    tid = uuid4()
    uid = uuid4()
    agent = await repo.create(
        tenant_id=tid, created_by=uid,
        name="병원", goal="goal text 10+ chars", guidelines_md="guidelines text 10+",
    )
    fake_db.add.assert_called_once()
    fake_db.flush.assert_awaited_once()
    assert agent.tenant_id == tid
    assert agent.created_by == uid
    assert agent.name == "병원"


@pytest.mark.asyncio
async def test_get_filters_by_tenant(fake_db):
    repo = AgentRepository(fake_db)
    aid = uuid4()
    tid = uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    fake_db.execute.return_value = mock_result

    result = await repo.get(aid, tenant_id=tid)
    assert result is None
    fake_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_by_tenant_active_only_default(fake_db):
    repo = AgentRepository(fake_db)
    tid = uuid4()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    fake_db.execute.return_value = mock_result

    out = await repo.list_by_tenant(tid)
    assert out == []


@pytest.mark.asyncio
async def test_update_returns_none_when_not_found(fake_db):
    repo = AgentRepository(fake_db)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    fake_db.execute.return_value = mock_result

    result = await repo.update(uuid4(), tenant_id=uuid4(), name="new")
    assert result is None


@pytest.mark.asyncio
async def test_update_skips_none_patch(fake_db):
    """patch 의 None 값은 setattr 안 됨 (PATCH semantics)."""
    repo = AgentRepository(fake_db)

    fake_agent = MagicMock()
    fake_agent.name = "old"
    fake_agent.description = "old_desc"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_agent
    fake_db.execute.return_value = mock_result

    await repo.update(uuid4(), tenant_id=uuid4(), name="new", description=None)
    assert fake_agent.name == "new"
    assert fake_agent.description == "old_desc"  # None 은 무시


@pytest.mark.asyncio
async def test_soft_delete_sets_inactive(fake_db):
    repo = AgentRepository(fake_db)

    fake_agent = MagicMock()
    fake_agent.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_agent
    fake_db.execute.return_value = mock_result

    ok = await repo.soft_delete(uuid4(), tenant_id=uuid4())
    assert ok is True
    assert fake_agent.is_active is False


@pytest.mark.asyncio
async def test_soft_delete_returns_false_when_not_found(fake_db):
    repo = AgentRepository(fake_db)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    fake_db.execute.return_value = mock_result

    ok = await repo.soft_delete(uuid4(), tenant_id=uuid4())
    assert ok is False
