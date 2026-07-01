from unittest.mock import AsyncMock
import asyncio
import numpy as np
import pytest
from src.agent_framework.activation.overlap_analyzer import (
    KnowledgeOverlapAnalyzer, OverlapReport,
)
from src.agent_framework.activation.overlap_prefilter import Candidate


class StubEmbedder:
    async def embed(self, text: str) -> np.ndarray:
        v = np.zeros(16)
        v[0] = len(text) % 16
        v[1] = ord(text[0]) if text else 0
        v[2] = 1.0
        v /= np.linalg.norm(v) + 1e-12
        return v


class StubCorpusLoader:
    def __init__(self, corpus: list[Candidate]):
        self.corpus = corpus

    async def load_active(self, tenant_id: str) -> list[Candidate]:
        return self.corpus


def test_empty_corpus_returns_no_hits():
    analyzer = KnowledgeOverlapAnalyzer(
        embedder=StubEmbedder(),
        corpus_loader=StubCorpusLoader(corpus=[]),
        llm_client=AsyncMock(),
    )
    report = asyncio.run(analyzer.analyze(
        tenant_id="t1", new_doc_id="d_new", new_summary="hello"
    ))
    assert isinstance(report, OverlapReport)
    assert report.hits == []
    assert report.requires_human is False


def test_conflict_blocks_auto_approve():
    llm = AsyncMock()
    llm.classify_relation = AsyncMock(return_value={
        "relation": "conflicts",
        "confidence": 0.91,
        "evidence": "상반 정보",
    })
    llm.generate_replacement_draft = AsyncMock()
    corpus = [Candidate(doc_id="d_peer",
                        embedding=np.ones(16) / 4, title="peer", snippet="...")]
    analyzer = KnowledgeOverlapAnalyzer(
        embedder=StubEmbedder(),
        corpus_loader=StubCorpusLoader(corpus=corpus),
        llm_client=llm,
    )
    report = asyncio.run(analyzer.analyze(
        tenant_id="t1", new_doc_id="d_new", new_summary="hello world"
    ))
    assert report.requires_human is True
    assert any(h["relation"] == "conflicts" for h in report.hits)
    assert all("replacement_draft" not in h for h in report.hits)


def test_supersedes_generates_replacement_draft():
    llm = AsyncMock()
    llm.classify_relation = AsyncMock(return_value={
        "relation": "supersedes_existing",
        "confidence": 0.88,
        "evidence": "신규 날짜 최신",
    })
    llm.generate_replacement_draft = AsyncMock(return_value={
        "title": "업데이트된 가이드",
        "body_summary": "...",
        "diff_from_existing": ["추가된 사실 1"],
    })
    corpus = [Candidate(doc_id="d_peer", embedding=np.ones(16)/4,
                        title="peer", snippet="..." )]
    analyzer = KnowledgeOverlapAnalyzer(
        embedder=StubEmbedder(),
        corpus_loader=StubCorpusLoader(corpus=corpus),
        llm_client=llm,
    )
    report = asyncio.run(analyzer.analyze(
        tenant_id="t1", new_doc_id="d_new", new_summary="hello"
    ))
    hit = report.hits[0]
    assert hit["relation"] == "supersedes_existing"
    assert "replacement_draft" in hit
    assert hit["replacement_draft"]["title"]
    assert report.suggested_action.startswith("approve_and_archive")
