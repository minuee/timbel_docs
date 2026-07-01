"""NewsWorker 스텁 — RSS → agent_news_report snapshot auto-approve."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone


class NewsWorker:
    def __init__(self, *, rss_urls, parse_feed, doc_store, tenant_id: str):
        self.rss_urls = rss_urls
        self.parse_feed = parse_feed
        self.store = doc_store
        self.tenant_id = tenant_id

    async def run_once(self, *, topic: str = "general", max_per_feed: int = 5) -> dict:
        approved = 0
        for url in self.rss_urls:
            try:
                feed = await self.parse_feed(url)
            except Exception:
                continue
            for e in (feed.get("entries") or [])[:max_per_feed]:
                doc_id = f"d_news_{uuid.uuid4().hex[:8]}"
                await self.store.insert(
                    id=doc_id, tenant_id=self.tenant_id,
                    title=e.get("title"),
                    document_type="agent_news_report",
                    status="active",
                    processing_meta={
                        "document_type": "agent_news_report",
                        "body": {
                            "topic": topic, "url": e.get("link"),
                            "summary": e.get("summary"),
                            "published": e.get("published"),
                        },
                        "activation": {
                            "auto_approved": True,
                            "policy": "snapshot_read_only",
                            "approved_at": datetime.now(timezone.utc).isoformat(),
                        },
                    },
                )
                approved += 1
        return {"auto_approved": approved}
