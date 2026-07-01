"""Crawl worker 스텁 — spec §4 (E 코스 최소 레일 증명).

구성:
- search_fn(topic, max_results) -> [{url, title, snippet}]
- fetch_body(url) -> str
- doc_store.insert(...) -> doc_id
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse


class CrawlWorker:
    def __init__(
        self, *, search_fn, fetch_body, doc_store,
        tenant_id: str, trusted_domains: set[str],
    ):
        self.search = search_fn
        self.fetch = fetch_body
        self.store = doc_store
        self.tenant_id = tenant_id
        self.trusted = trusted_domains

    async def crawl_topic(self, *, topic: str, max_results: int = 3) -> dict:
        results = await self.search(topic, max_results=max_results)
        inserted = 0
        for r in results or []:
            domain = urlparse(r["url"]).netloc.lower().lstrip("www.")
            trusted = any(domain.endswith(d) for d in self.trusted)
            try:
                body = await self.fetch(r["url"])
            except Exception as e:
                body = f"(fetch failed: {e})"
            doc_id = f"d_crawl_{uuid.uuid4().hex[:8]}"
            await self.store.insert(
                id=doc_id, tenant_id=self.tenant_id,
                title=r.get("title") or r["url"],
                document_type="crawl_digest",
                status="pending_review",
                processing_meta={
                    "document_type": "crawl_digest",
                    "body": {
                        "topic": topic, "url": r["url"], "snippet": r.get("snippet"),
                        "body_text": body[:5000],
                        "trusted_domain": trusted,
                        "domain": domain,
                    },
                    "activation": {
                        "policy": "require_review_all",
                        "crawled_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
            inserted += 1
        return {"pending_count": inserted, "topic": topic}
