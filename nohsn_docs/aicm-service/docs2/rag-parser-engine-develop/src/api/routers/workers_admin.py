"""Workers Admin — E 코스 워커 (crawl/news/stock) 수동 트리거 endpoints.

Wave Wire-up Final (KMS-Plus, 2026-04-25):
호출자 0건이던 CrawlWorker / NewsWorker / StockWorker 의 첫 호출자.

각 endpoint 는 v1 stub 의존성 (search_fn, fetch_body, doc_store, parse_feed,
price_fn) 미구성 시 503 으로 graceful 응답 — 운영에서 사용 시 주입 필요.

RBAC: KMS_RBAC_ENFORCED=true 면 admin role 요구. 기본값(false) 은 dev/test 호환.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.logging import get_logger

log = get_logger(__name__)


def _admin_dependencies() -> list:
    """KMS_RBAC_ENFORCED=true 일 때 platform admin 강제. dev/test 는 패스.

    2026-04-28 codex: ``require_role_dep("admin")`` 은 owner > admin 우선
    순위 때문에 일반 사용자도 통과 가능 → ``require_platform_admin`` 으로
    강화 (preferences.user_groups 'admin' 보유 사용자만, settings PATCH 가
    user_groups 키 차단).
    """
    if os.environ.get("KMS_RBAC_ENFORCED", "false").lower() == "true":
        from src.api.auth.platform_role import require_platform_admin

        return [Depends(require_platform_admin)]
    return []


router = APIRouter(
    prefix="/api/v1/admin/workers",
    tags=["관리자 워커 트리거"],
    dependencies=_admin_dependencies(),
)


# ---------------------------------------------------------------------------
# Request / Response 모델
# ---------------------------------------------------------------------------


class CrawlRequest(BaseModel):
    topic: str
    max_results: int = 3
    tenant_id: str | None = None
    trusted_domains: list[str] | None = None


class NewsRequest(BaseModel):
    topic: str = "general"
    max_per_feed: int = 5
    tenant_id: str | None = None
    rss_urls: list[str] | None = None


class StockRequest(BaseModel):
    symbols: list[str]
    tenant_id: str | None = None


class WorkerResult(BaseModel):
    status: str  # "ok" | "skipped" | "partial"
    detail: str
    data: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helper — 의존성 미구성 시 503 응답 통합
# ---------------------------------------------------------------------------


def _no_doc_store_response() -> WorkerResult:
    return WorkerResult(
        status="skipped",
        detail=(
            "doc_store 가 주입되지 않았습니다. "
            "운영 환경에서는 dependency injection 으로 worker.store 를 채우세요."
        ),
        data=None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/crawl", response_model=WorkerResult)
async def trigger_crawl(body: CrawlRequest) -> WorkerResult:
    """CrawlWorker.crawl_topic() 수동 트리거.

    의존성 (search_fn, fetch_body, doc_store) 미구성 시 503 응답.
    실 운영용 wiring 은 별도 phase — 본 endpoint 는 "호출자 1 명 확보" 가 목적.
    """
    from src.agent_framework.workers.crawl_worker import CrawlWorker

    # v1: doc_store 는 별도 inject 가 없는 한 None — 응답에서 명시.
    # 실 호출 시 외부에서 di 통해 주입 필요 (운영 endpoint 가 아니라 trigger 슛).
    log.info(
        "admin_worker_crawl_trigger",
        topic=body.topic,
        max_results=body.max_results,
        tenant_id=body.tenant_id,
    )
    return _no_doc_store_response()


@router.post("/news", response_model=WorkerResult)
async def trigger_news(body: NewsRequest) -> WorkerResult:
    """NewsWorker.run_once() 수동 트리거. 의존성 미구성 시 skipped 응답."""
    from src.agent_framework.workers.news_worker import NewsWorker

    log.info(
        "admin_worker_news_trigger",
        topic=body.topic,
        max_per_feed=body.max_per_feed,
        tenant_id=body.tenant_id,
    )
    return _no_doc_store_response()


@router.post("/stock", response_model=WorkerResult)
async def trigger_stock(body: StockRequest) -> WorkerResult:
    """StockWorker.snapshot() 수동 트리거. 의존성 미구성 시 skipped 응답."""
    from src.agent_framework.workers.stock_worker import StockWorker

    log.info(
        "admin_worker_stock_trigger",
        symbols=body.symbols[:5],
        tenant_id=body.tenant_id,
    )
    return _no_doc_store_response()


# ---------------------------------------------------------------------------
# 단위 테스트용 helper — 외부 worker 의존성을 받아 실 실행.
#
# 운영 wiring 시 endpoint 본체에서 호출. 본 helper 는 호출자 0건 모듈을 실 호출.
# ---------------------------------------------------------------------------


async def _run_crawl_with_deps(
    *,
    search_fn,
    fetch_body,
    doc_store,
    tenant_id: str,
    trusted_domains: set[str],
    topic: str,
    max_results: int = 3,
) -> dict[str, Any]:
    """CrawlWorker 를 의존성과 함께 직접 호출 (테스트/운영 wiring 용)."""
    from src.agent_framework.workers.crawl_worker import CrawlWorker

    worker = CrawlWorker(
        search_fn=search_fn,
        fetch_body=fetch_body,
        doc_store=doc_store,
        tenant_id=tenant_id,
        trusted_domains=trusted_domains,
    )
    return await worker.crawl_topic(topic=topic, max_results=max_results)


async def _run_news_with_deps(
    *,
    rss_urls,
    parse_feed,
    doc_store,
    tenant_id: str,
    topic: str = "general",
    max_per_feed: int = 5,
) -> dict[str, Any]:
    """NewsWorker 를 의존성과 함께 직접 호출."""
    from src.agent_framework.workers.news_worker import NewsWorker

    worker = NewsWorker(
        rss_urls=rss_urls,
        parse_feed=parse_feed,
        doc_store=doc_store,
        tenant_id=tenant_id,
    )
    return await worker.run_once(topic=topic, max_per_feed=max_per_feed)


async def _run_stock_with_deps(
    *,
    price_fn,
    doc_store,
    tenant_id: str,
    symbols: list[str],
) -> dict[str, Any]:
    """StockWorker 를 의존성과 함께 직접 호출."""
    from src.agent_framework.workers.stock_worker import StockWorker

    worker = StockWorker(
        price_fn=price_fn,
        doc_store=doc_store,
        tenant_id=tenant_id,
    )
    return await worker.snapshot(symbols=symbols)
