"""KMSRagTool — KMS_FIRST_EARLY_RETURN sufficiency flag 주입 테스트.

Option β Stage 2: flag on/off 시 _kms_features / kms_sufficient 키 존재 여부
및 heuristic threshold 동작을 검증.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agent_framework.tools.kms_rag import KMSRagTool


class _FakeResultItem:
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


def _make_svc(*items: _FakeResultItem) -> AsyncMock:
    svc = AsyncMock()
    svc.search = AsyncMock(return_value=_FakeResponse(list(items)))
    return svc


# ---------------------------------------------------------------------------
# flag off — dict shape must be identical to pre-stage behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_off_no_features(monkeypatch):
    """FEATURE_KMS_FIRST_EARLY_RETURN 미설정이면 sufficiency 키 부재."""
    monkeypatch.delenv("FEATURE_KMS_FIRST_EARLY_RETURN", raising=False)

    svc = _make_svc(
        _FakeResultItem("c1", "d1", "Title A", "high content", 0.9),
    )
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=svc)):
        tool = KMSRagTool()
        result = await tool({"query": "검색어"})

    assert "kms_sufficient" not in result, "flag off 시 kms_sufficient 부재 필수"
    assert "_kms_features" not in result, "flag off 시 _kms_features 부재 필수"
    # 기존 키 shape 유지
    assert "hits" in result
    assert result["success"] is True


@pytest.mark.asyncio
async def test_flag_off_explicit_false(monkeypatch):
    """FEATURE_KMS_FIRST_EARLY_RETURN=false 도 동일하게 키 부재."""
    monkeypatch.setenv("FEATURE_KMS_FIRST_EARLY_RETURN", "false")

    svc = _make_svc(
        _FakeResultItem("c1", "d1", "Title A", "content", 0.9),
    )
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=svc)):
        tool = KMSRagTool()
        result = await tool({"query": "검색어"})

    assert "kms_sufficient" not in result
    assert "_kms_features" not in result


# ---------------------------------------------------------------------------
# flag on — sufficient signal (high score + clear gap)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_on_sufficient_signal(monkeypatch):
    """top_score > 0.7 AND rank_gap > 0.15 → kms_sufficient=True."""
    monkeypatch.setenv("FEATURE_KMS_FIRST_EARLY_RETURN", "true")

    svc = _make_svc(
        _FakeResultItem("c1", "d1", "Title A", "high content", 0.85),
        _FakeResultItem("c2", "d2", "Title B", "low content", 0.60),  # gap=0.25
    )
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=svc)):
        tool = KMSRagTool()
        result = await tool({"query": "검색어"})

    assert "kms_sufficient" in result
    assert "_kms_features" in result
    assert result["kms_sufficient"] is True, f"features={result['_kms_features']}"
    feats = result["_kms_features"]
    assert feats["top_score"] == pytest.approx(0.85)
    assert feats["rank_gap"] == pytest.approx(0.25)
    assert feats["n_hits"] == 2


# ---------------------------------------------------------------------------
# flag on — insufficient: low top_score
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_on_insufficient_low_score(monkeypatch):
    """top_score <= 0.7 → kms_sufficient=False even if gap is wide."""
    monkeypatch.setenv("FEATURE_KMS_FIRST_EARLY_RETURN", "true")

    svc = _make_svc(
        _FakeResultItem("c1", "d1", "Title A", "content A", 0.65),
        _FakeResultItem("c2", "d2", "Title B", "content B", 0.30),  # gap=0.35 (wide)
    )
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=svc)):
        tool = KMSRagTool()
        result = await tool({"query": "검색어"})

    assert result["kms_sufficient"] is False
    feats = result["_kms_features"]
    assert feats["top_score"] == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# flag on — insufficient: scores too close (small rank_gap)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_on_insufficient_close_scores(monkeypatch):
    """rank_gap <= 0.15 → kms_sufficient=False even if top_score is high."""
    monkeypatch.setenv("FEATURE_KMS_FIRST_EARLY_RETURN", "true")

    svc = _make_svc(
        _FakeResultItem("c1", "d1", "Title A", "content A", 0.82),
        _FakeResultItem("c2", "d2", "Title B", "content B", 0.75),  # gap=0.07 (narrow)
    )
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=svc)):
        tool = KMSRagTool()
        result = await tool({"query": "검색어"})

    assert result["kms_sufficient"] is False
    feats = result["_kms_features"]
    assert feats["rank_gap"] == pytest.approx(0.07)


# ---------------------------------------------------------------------------
# flag on — single hit (rank_gap is None → treated as gap-sufficient)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_on_single_hit_sufficient(monkeypatch):
    """단일 hit + top_score > 0.7 → rank_gap=None → gap 조건 충족으로 처리."""
    monkeypatch.setenv("FEATURE_KMS_FIRST_EARLY_RETURN", "true")

    svc = _make_svc(
        _FakeResultItem("c1", "d1", "Only Title", "only content", 0.90),
    )
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=svc)):
        tool = KMSRagTool()
        result = await tool({"query": "검색어"})

    assert result["kms_sufficient"] is True
    feats = result["_kms_features"]
    assert feats["rank_gap"] is None
    assert feats["n_hits"] == 1


# ---------------------------------------------------------------------------
# flag on — no hits → kms_sufficient=False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_on_no_hits(monkeypatch):
    """hits 없으면 kms_sufficient=False."""
    monkeypatch.setenv("FEATURE_KMS_FIRST_EARLY_RETURN", "true")

    svc = _make_svc()  # empty
    with patch("src.search.factory.create_search_service", AsyncMock(return_value=svc)):
        tool = KMSRagTool()
        result = await tool({"query": "없는 내용"})

    assert result["kms_sufficient"] is False
    feats = result["_kms_features"]
    assert feats["top_score"] is None
    assert feats["n_hits"] == 0
