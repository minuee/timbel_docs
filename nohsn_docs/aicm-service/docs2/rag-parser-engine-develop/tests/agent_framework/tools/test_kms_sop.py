"""KMSSopTool — Phase 1.5B-β SOP RAG tool 테스트.

embedding fn / qdrant client / DB session 모두 mock 으로 우회. 실 인프라 없이
input/output shape + filter + agent.sop_repo_ids 분기를 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


_AGENT_ID = uuid4()
_TENANT_ID = uuid4()
_REPO_A = uuid4()
_REPO_B = uuid4()


class _FakeHit:
    def __init__(self, payload: dict, score: float):
        self.payload = payload
        self.score = score


class _FakeRow:
    """SQLAlchemy ``Row`` 흉내 — index access 만 사용."""

    def __init__(self, sop_repo_ids, tenant_id):
        self._values = (sop_repo_ids, tenant_id)

    def __getitem__(self, idx):
        return self._values[idx]


def _make_session_with_row(row):
    """async_session_factory() 가 반환하는 async context manager mock."""
    sess = MagicMock()
    exec_result = MagicMock()
    # .first() 만 사용
    exec_result.first = MagicMock(return_value=row)
    sess.execute = AsyncMock(return_value=exec_result)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=sess)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=cm)
    return factory, sess


def _reset_tool_class():
    """모듈 캐시 (embedding_fn / qdrant_client) 초기화."""
    from src.agent_framework.tools.kms_sop import KMSSopTool
    KMSSopTool._embedding_fn = None
    KMSSopTool._qdrant_client = None


@pytest.fixture(autouse=True)
def _reset_caches():
    _reset_tool_class()
    yield
    _reset_tool_class()


@pytest.mark.asyncio
async def test_kms_sop_search_basic():
    """agent_id + query → top_k chunks 반환 + payload shape."""
    from src.agent_framework.tools.kms_sop import KMSSopTool, build_sop_collection_name

    factory, sess = _make_session_with_row(_FakeRow([_REPO_A, _REPO_B], _TENANT_ID))

    fake_hits = [
        _FakeHit(
            payload={
                "text": "## escalation_channels\n원장님 직통 02-1234-5678",
                "repo_id": str(_REPO_A),
                "document_id": str(uuid4()),
                "chunk_index": 2,
                "heading": "escalation_channels",
            },
            score=0.91,
        ),
        _FakeHit(
            payload={
                "text": "## time_policy\n영업시간 09-18",
                "repo_id": str(_REPO_A),
                "document_id": str(uuid4()),
                "chunk_index": 0,
                "heading": "time_policy",
            },
            score=0.72,
        ),
    ]
    fake_qdrant = MagicMock()
    fake_qdrant.search = AsyncMock(return_value=fake_hits)

    with patch(
        "src.core.database.async_session_factory", factory
    ), patch.object(
        KMSSopTool, "_get_embedding_fn",
        AsyncMock(return_value=AsyncMock(return_value=([0.1] * 1024, {}))),
    ), patch.object(
        KMSSopTool, "_get_qdrant_client", AsyncMock(return_value=fake_qdrant)
    ):
        tool = KMSSopTool()
        got = await tool({"query": "원장님 연락처", "agent_id": str(_AGENT_ID)})

    assert got["success"] is True
    assert got["total"] == 2
    assert len(got["chunks"]) == 2
    c0 = got["chunks"][0]
    assert "escalation" in c0["text"]
    assert c0["score"] == pytest.approx(0.91)
    assert c0["repo_id"] == str(_REPO_A)
    assert c0["heading"] == "escalation_channels"
    assert c0["chunk_index"] == 2

    # collection 이름 — sop_v1_{tenant_id (underscore)}
    call = fake_qdrant.search.await_args.kwargs
    assert call["collection_name"] == build_sop_collection_name(_TENANT_ID)
    assert call["limit"] == 5  # default top_k


@pytest.mark.asyncio
async def test_sop_repo_ids_empty():
    """agent.sop_repo_ids 가 비면 즉시 빈 결과 — Qdrant 호출 X."""
    from src.agent_framework.tools.kms_sop import KMSSopTool

    factory, _ = _make_session_with_row(_FakeRow([], _TENANT_ID))
    fake_qdrant = MagicMock()
    fake_qdrant.search = AsyncMock(return_value=[])

    with patch(
        "src.core.database.async_session_factory", factory
    ), patch.object(
        KMSSopTool, "_get_qdrant_client", AsyncMock(return_value=fake_qdrant)
    ):
        tool = KMSSopTool()
        got = await tool({"query": "policy?", "agent_id": str(_AGENT_ID)})

    assert got["success"] is True
    assert got["chunks"] == []
    assert got["total"] == 0
    fake_qdrant.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_top_k_clamps_to_20():
    """top_k=999 → 20 으로 clamp (destructive force 가 사용할 max)."""
    from src.agent_framework.tools.kms_sop import KMSSopTool

    factory, _ = _make_session_with_row(_FakeRow([_REPO_A], _TENANT_ID))
    fake_qdrant = MagicMock()
    fake_qdrant.search = AsyncMock(return_value=[])

    with patch(
        "src.core.database.async_session_factory", factory
    ), patch.object(
        KMSSopTool, "_get_embedding_fn",
        AsyncMock(return_value=AsyncMock(return_value=([0.1] * 1024, {}))),
    ), patch.object(
        KMSSopTool, "_get_qdrant_client", AsyncMock(return_value=fake_qdrant)
    ):
        tool = KMSSopTool()
        await tool(
            {"query": "force", "agent_id": str(_AGENT_ID), "top_k": 999}
        )

    assert fake_qdrant.search.await_args.kwargs["limit"] == 20


@pytest.mark.asyncio
async def test_missing_agent_id_fails_fast():
    from src.agent_framework.tools.kms_sop import KMSSopTool

    tool = KMSSopTool()
    got = await tool({"query": "x"})
    assert got["success"] is False
    assert "agent_id" in got["error"]


@pytest.mark.asyncio
async def test_empty_query_fails_fast():
    from src.agent_framework.tools.kms_sop import KMSSopTool

    tool = KMSSopTool()
    got = await tool({"query": "  ", "agent_id": str(_AGENT_ID)})
    assert got["success"] is False
    assert "empty" in got["error"]


@pytest.mark.asyncio
async def test_qdrant_collection_missing_graceful():
    """collection 미존재 (Qdrant 404) → success=true / 빈 chunks."""
    from src.agent_framework.tools.kms_sop import KMSSopTool

    factory, _ = _make_session_with_row(_FakeRow([_REPO_A], _TENANT_ID))
    fake_qdrant = MagicMock()
    fake_qdrant.search = AsyncMock(side_effect=RuntimeError("collection not found"))

    with patch(
        "src.core.database.async_session_factory", factory
    ), patch.object(
        KMSSopTool, "_get_embedding_fn",
        AsyncMock(return_value=AsyncMock(return_value=([0.1] * 1024, {}))),
    ), patch.object(
        KMSSopTool, "_get_qdrant_client", AsyncMock(return_value=fake_qdrant)
    ):
        tool = KMSSopTool()
        got = await tool({"query": "x", "agent_id": str(_AGENT_ID)})

    assert got["success"] is True  # graceful degrade
    assert got["chunks"] == []


@pytest.mark.asyncio
async def test_repo_filter_applied():
    """Qdrant search 시 sop_repo_ids 만 매칭되는 filter 가 적용."""
    from src.agent_framework.tools.kms_sop import KMSSopTool

    factory, _ = _make_session_with_row(_FakeRow([_REPO_A, _REPO_B], _TENANT_ID))
    fake_qdrant = MagicMock()
    fake_qdrant.search = AsyncMock(return_value=[])

    with patch(
        "src.core.database.async_session_factory", factory
    ), patch.object(
        KMSSopTool, "_get_embedding_fn",
        AsyncMock(return_value=AsyncMock(return_value=([0.1] * 1024, {}))),
    ), patch.object(
        KMSSopTool, "_get_qdrant_client", AsyncMock(return_value=fake_qdrant)
    ):
        tool = KMSSopTool()
        await tool({"query": "policy", "agent_id": str(_AGENT_ID)})

    qfilter = fake_qdrant.search.await_args.kwargs["query_filter"]
    # qfilter.must[0].match.any 가 [str(_REPO_A), str(_REPO_B)] 포함.
    must = qfilter.must
    assert len(must) == 1
    cond = must[0]
    assert cond.key == "repo_id"
    assert set(cond.match.any) == {str(_REPO_A), str(_REPO_B)}


def test_collection_name_format():
    """sop_v1_{tenant_id} — hyphen 은 underscore 로 정규화."""
    from src.agent_framework.tools.kms_sop import build_sop_collection_name

    tid = UUID("12345678-1234-5678-1234-567812345678")
    name = build_sop_collection_name(tid)
    assert name == "sop_v1_12345678_1234_5678_1234_567812345678"
    assert "-" not in name
