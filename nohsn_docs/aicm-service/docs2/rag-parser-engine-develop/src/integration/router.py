"""Integration 라우터 — 파이프라인 관련만 포함 (chat_api, series_api 제외)."""

from __future__ import annotations

from fastapi import APIRouter

from src.integration.api_gateway.router import router as api_key_router
from src.integration.rag_api.router import router as rag_api_router
from src.integration.sync.router import router as sync_router
from src.integration.webhook.router import router as webhook_router

integration_router = APIRouter()

# API Key 관리: /api/v1/api-keys
integration_router.include_router(api_key_router)

# 외부 검색/RAG API: /api/v1/ext/search, /api/v1/ext/ask, /api/v1/ext/ask/stream
integration_router.include_router(rag_api_router)

# Webhook 관리: /api/v1/webhooks
integration_router.include_router(webhook_router)

# 동기화 소스 관리: /api/v1/sync/sources
integration_router.include_router(sync_router)
