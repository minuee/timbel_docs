"""Wave Wire-up Final — /api/v1/admin/workers/{crawl,news,stock} endpoint 검증.

E 코스 워커 (CrawlWorker / NewsWorker / StockWorker) 가 호출자 0건이던 상태를
admin endpoint + helper 함수로 wire 한다. 본 테스트는:
- 3 endpoint 가 등록돼 있고 200 응답 (의존성 미구성 시 status='skipped')
- helper 함수 (_run_*_with_deps) 가 실제 worker 를 실행 + 결과 반환
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import workers_admin


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(workers_admin.router)
    return TestClient(app)


def test_crawl_endpoint_returns_skipped_without_deps(client: TestClient):
    resp = client.post(
        "/api/v1/admin/workers/crawl",
        json={"topic": "삼성전자", "max_results": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"skipped", "ok"}
    assert "doc_store" in body["detail"] or body["status"] == "ok"


def test_news_endpoint_returns_skipped_without_deps(client: TestClient):
    resp = client.post(
        "/api/v1/admin/workers/news",
        json={"topic": "general", "max_per_feed": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"


def test_stock_endpoint_returns_skipped_without_deps(client: TestClient):
    resp = client.post(
        "/api/v1/admin/workers/stock",
        json={"symbols": ["005930"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"


# ---------------------------------------------------------------------------
# Helper 함수 — 실 worker 를 의존성과 함께 호출. 호출자 0건 이슈 해소 검증.
# ---------------------------------------------------------------------------


class _StubDocStore:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    async def insert(self, **kwargs):
        self.inserted.append(kwargs)
        return kwargs.get("id")


@pytest.mark.asyncio
async def test_helper_run_crawl_with_deps_invokes_worker():
    """_run_crawl_with_deps 가 CrawlWorker.crawl_topic 까지 도달."""
    store = _StubDocStore()

    async def _search_fn(topic, max_results):
        return [{"url": "https://example.com/a", "title": "T", "snippet": "S"}]

    async def _fetch_body(url):
        return "본문 내용"

    res = await workers_admin._run_crawl_with_deps(
        search_fn=_search_fn,
        fetch_body=_fetch_body,
        doc_store=store,
        tenant_id="t1",
        trusted_domains={"example.com"},
        topic="테스트",
        max_results=1,
    )
    assert res["pending_count"] == 1
    assert res["topic"] == "테스트"
    assert len(store.inserted) == 1


@pytest.mark.asyncio
async def test_helper_run_news_with_deps_invokes_worker():
    store = _StubDocStore()

    async def _parse_feed(url):
        return {
            "entries": [
                {"title": "뉴스1", "link": "https://news/1", "summary": "요약", "published": "2026-04-25"}
            ]
        }

    res = await workers_admin._run_news_with_deps(
        rss_urls=["https://rss.example.com/feed"],
        parse_feed=_parse_feed,
        doc_store=store,
        tenant_id="t1",
        topic="general",
        max_per_feed=1,
    )
    assert res["auto_approved"] == 1
    assert len(store.inserted) == 1


@pytest.mark.asyncio
async def test_helper_run_stock_with_deps_invokes_worker():
    store = _StubDocStore()

    async def _price_fn(sym):
        return {"date": "2026-04-25", "close": 70000, "symbol": sym}

    res = await workers_admin._run_stock_with_deps(
        price_fn=_price_fn,
        doc_store=store,
        tenant_id="t1",
        symbols=["005930", "000660"],
    )
    assert res["auto_approved"] == 2
    assert len(store.inserted) == 2
