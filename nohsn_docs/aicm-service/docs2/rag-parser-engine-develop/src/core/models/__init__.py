"""KMS Pipeline Core ORM 모델 패키지 — 파이프라인/검색에 필요한 모델만 포함."""

from src.core.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from src.core.models.tenant import Tenant
from src.core.models.user import User, UserRepositoryAccess, UserRole
from src.core.models.agent_document import AgentDocument
# AgentDocument.agent_id → agents.id FK 를 가지므로 Agent 모델도 함께 등록해야
# Base.metadata.create_all 이 dangling FK(NoReferencedTableError) 없이 fresh DB
# 를 생성한다. 순수 스키마 정합성 — runtime agent 기능(main_kms 미mount)과 무관.
from src.core.models.agent import Agent
from src.core.models.anonymization_log import AnonymizationLog
from src.core.models.block import Block
from src.core.models.category import Category
from src.core.models.dlq_message import DLQMessageORM
from src.core.models.document import Chunk, Document, Section, document_categories
from src.core.models.document_type import SYSTEM_DOCUMENT_TYPES, DocumentType
from src.core.models.library_folder import LibraryFolder
from src.core.models.llm_usage import LLMUsage
from src.core.models.repository import Repository
from src.core.models.repository_group import RepositoryGroup
from src.core.models.search_log import SearchLog
from src.core.models.intent_log import IntentLog
from src.core.models.integration import INTEGRATION_TYPES, Integration
from src.core.models.tenant_synonym import TenantSynonym

__all__ = [
    "AgentDocument",
    "AnonymizationLog",
    "Base",
    "Block",
    "Category",
    "Chunk",
    "DLQMessageORM",
    "Document",
    "DocumentType",
    "INTEGRATION_TYPES",
    "Integration",
    "LibraryFolder",
    "LLMUsage",
    "Repository",
    "RepositoryGroup",
    "SearchLog",
    "Section",
    "SoftDeleteMixin",
    "SYSTEM_DOCUMENT_TYPES",
    "TenantSynonym",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "document_categories",
]
