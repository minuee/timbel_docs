# tests/agent_framework/workers/test_news_worker.py
import asyncio
from src.agent_framework.workers.news_worker import NewsWorker


def test_news_fetch_auto_approves():
    feed_stub = {"entries": [
        {"title":"Naver 뉴스 샘플", "link":"https://news.example.com/1",
         "summary":"요약1", "published":"Sat, 25 Apr 2026 12:00:00 +0900"},
    ]}
    class Store:
        def __init__(self): self.inserted = []
        async def insert(self, **k):
            self.inserted.append(k); return k["id"]
    async def parse(url): return feed_stub

    store = Store()
    w = NewsWorker(rss_urls=["https://example.com/rss"],
                   parse_feed=parse, doc_store=store, tenant_id="t1")
    res = asyncio.run(w.run_once(topic="general"))
    assert res["auto_approved"] == 1
    assert store.inserted[0]["status"] == "active"
    assert store.inserted[0]["document_type"] == "agent_news_report"
    assert store.inserted[0]["processing_meta"]["activation"]["auto_approved"] is True
