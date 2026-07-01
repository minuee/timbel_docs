"""KMSRagTool 실 SearchService 어댑터 테스트.

create_search_service() 를 mock 해서 factory import 없이 검증.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agent_framework.tools.kms_rag import KMSRagTool, DEFAULT_TENANT_SLUG, DEFAULT_TENANT_UUID


class _FakeResultItem:
    """SearchResultItem-like (pydantic 없이 attr access)."""

    def __init__(self, chunk_id, document_id, document_title, content, score, section_title=None):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.document_title = document_title
        self.section_title = section_title
        self.content = content
        self.score = score


class _FakeResponse:
    def __init__(self, results):
        self.results = results


@pytest.mark.asyncio
async def test_tool_returns_hits_shape():
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([
        _FakeResultItem("c1", "d1", "레이저 안내", "레이저 시술은...", 0.8, section_title="가격"),
    ]))

    with patch("src.search.factory.create_search_service", AsyncMock(return_value=fake_svc)):
        tool = KMSRagTool()
        got = await tool({"query": "레이저 가격?", "top_k": 3})

    assert "hits" in got
    assert len(got["hits"]) == 1
    h = got["hits"][0]
    assert h["title"] == "레이저 안내"
    assert h["section"] == "가격"
    assert "레이저" in h["content"]
    assert h["score"] == 0.8
    assert got["total"] == 1

    # SearchRequest 에 tenant/top_k 정확히 전달됐는지
    call_kwargs = fake_svc.search.await_args.kwargs
    req = call_kwargs["request"]
    assert str(req.tenant_id) == str(DEFAULT_TENANT_UUID)
    assert req.top_k == 3
    assert req.query == "레이저 가격?"
    assert call_kwargs["tenant_slug"] == DEFAULT_TENANT_SLUG


@pytest.mark.asyncio
async def test_tool_empty_query_fails_fast():
    tool = KMSRagTool()
    got = await tool({"query": "   "})
    assert got["hits"] == []
    assert "empty" in got.get("error", "")


@pytest.mark.asyncio
async def test_tool_service_init_failure_graceful():
    with patch("src.search.factory.create_search_service", AsyncMock(side_effect=RuntimeError("boom"))):
        tool = KMSRagTool()
        got = await tool({"query": "뭐든"})
    assert got["hits"] == []
    assert "unavailable" in got.get("error", "")


@pytest.mark.asyncio
async def test_tool_search_error_graceful():
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(side_effect=RuntimeError("ES timeout"))
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=fake_svc)):
        tool = KMSRagTool()
        got = await tool({"query": "any"})
    assert got["hits"] == []
    assert "ES timeout" in got.get("error", "")


@pytest.mark.asyncio
async def test_tool_top_k_clamped():
    """top_k 가 과도하게 크면 10 으로, 0 이면 1 로 클램프."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([]))

    with patch("src.search.factory.create_search_service", AsyncMock(return_value=fake_svc)):
        tool = KMSRagTool()
        await tool({"query": "x", "top_k": 999})
        req = fake_svc.search.await_args.kwargs["request"]
        assert req.top_k == 10

        fake_svc.search.reset_mock()
        await tool({"query": "x", "top_k": 0})
        req = fake_svc.search.await_args.kwargs["request"]
        assert req.top_k == 1
