"""외부 RAG API 통합 라우터."""

from __future__ import annotations

from fastapi import APIRouter

from src.integration.rag_api.answer_api import router as answer_router
from src.integration.rag_api.search_api import router as search_router
from src.integration.rag_api.stream_api import router as stream_router

router = APIRouter(prefix="/api/v1", tags=["External API"])

# /api/v1/ext/search
router.include_router(search_router)

# /api/v1/ext/ask
router.include_router(answer_router)

# /api/v1/ext/ask/stream (SSE 스트리밍)
router.include_router(stream_router)
