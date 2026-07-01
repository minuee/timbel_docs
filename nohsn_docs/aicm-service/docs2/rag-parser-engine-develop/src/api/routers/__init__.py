"""KMS Pipeline API 라우터 패키지 — 파이프라인/검색 라우터만 포함."""

from src.api.routers.health import router as health_router
from src.api.routers.repositories import router as repositories_router
from src.api.routers.repository_groups import router as repository_groups_router
from src.api.routers.categories import router as categories_router
from src.api.routers.document_types import router as document_types_router
from src.api.routers.documents import router as documents_router
from src.api.routers.blocks import router as blocks_router
from src.api.routers.chunks import router as chunks_router
from src.api.routers.search import router as search_router
from src.api.routers.rag import router as rag_router
from src.api.routers.rag_assist import router as rag_assist_router
from src.api.routers.search_proxy import router as search_proxy_router
from src.api.routers.synonyms import router as synonyms_router
from src.api.routers.ab_tests import router as ab_tests_router
from src.api.routers.confidentiality import router as confidentiality_router
from src.api.routers.pii import router as pii_router
from src.api.routers.anonymization import router as anonymization_router
from src.api.routers.stats import router as stats_router
from src.api.routers.analytics import router as analytics_router
from src.api.routers.feedback_stats import router as feedback_stats_router
from src.api.routers.knowledge_gap import router as knowledge_gap_router
from src.api.routers.classification_quality import router as classification_quality_router
from src.api.routers.webhook_inbound import router as webhook_inbound_router
from src.api.routers.preview import router as preview_router
from src.api.routers.playground import router as playground_router
from src.api.routers.reprocess import router as reprocess_router
from src.api.routers.notes import router as notes_router
from src.api.routers.pipeline_admin import router as pipeline_admin_router
from src.api.routers.admin_reset import router as admin_reset_router
from src.api.routers.workers_admin import router as workers_admin_router
from src.api.routers.llm_metrics import router as llm_metrics_router
from src.api.routers.mail_accounts import router as mail_accounts_router
from src.api.routers.inbox import router as inbox_router
from src.api.routers.manifest import router as manifest_router
from src.api.routers.library_folders_v1 import router as library_folders_router

__all__ = [
    "ab_tests_router",
    "admin_reset_router",
    "health_router",
    "llm_metrics_router",
    "analytics_router",
    "anonymization_router",
    "blocks_router",
    "categories_router",
    "chunks_router",
    "classification_quality_router",
    "confidentiality_router",
    "document_types_router",
    "documents_router",
    "feedback_stats_router",
    "knowledge_gap_router",
    "notes_router",
    "pii_router",
    "pipeline_admin_router",
    "playground_router",
    "preview_router",
    "rag_assist_router",
    "rag_router",
    "reprocess_router",
    "repositories_router",
    "repository_groups_router",
    "search_proxy_router",
    "search_router",
    "stats_router",
    "synonyms_router",
    "webhook_inbound_router",
    "workers_admin_router",
    "mail_accounts_router",
    "inbox_router",
    "manifest_router",
    "library_folders_router",
]
