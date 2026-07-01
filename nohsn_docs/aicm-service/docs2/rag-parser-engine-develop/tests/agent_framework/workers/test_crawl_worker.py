# tests/agent_framework/workers/test_crawl_worker.py
from unittest.mock import AsyncMock
import asyncio
from src.agent_framework.workers.crawl_worker import CrawlWorker


def test_crawl_creates_pending_review_doc():
    search_stub = AsyncMock(return_value=[
        {"url": "https://example.com/a", "title": "Test", "snippet": "..."},
    ])
    fetch_stub = AsyncMock(return_value="본문 텍스트 샘플입니다." * 30)
    doc_store = _stub_doc_store()
    worker = CrawlWorker(
        search_fn=search_stub, fetch_body=fetch_stub,
        doc_store=doc_store, tenant_id="t1",
        trusted_domains={"example.com"},
    )
    result = asyncio.run(worker.crawl_topic(topic="AI 활성화", max_results=1))
    assert result["pending_count"] == 1
    assert doc_store.inserted[0]["document_type"] == "crawl_digest"
    assert doc_store.inserted[0]["status"] == "pending_review"


def _stub_doc_store():
    class S:
        def __init__(self):
            self.inserted = []
        async def insert(self, **kw):
            self.inserted.append(kw)
            return kw.get("id") or f"d_stub_{len(self.inserted)}"
    return S()
