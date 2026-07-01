"""Add composite and partial indexes for query performance optimization.

Revision ID: 015_db_indexes
Revises: 014_add_system_settings
Create Date: 2026-04-12

Analysis of pg_stat_user_tables reveals:
- audit_logs: 100% sequential scans (0 index scans despite 5 single-column indexes)
- search_logs: 51.2% sequential scans on tenant_id + created_at range queries
- blocks: missing composite index for repository_id + validity_status filter
- documents: missing composite for repository_id + status + created_at ordering
- tenant_links: missing composite for user_id + status lookups

This migration adds composite, partial, and GIN indexes to cover the most
frequent query patterns identified in routers and services.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_db_indexes"
down_revision: Union[str, None] = "014_add_system_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite, partial, and GIN indexes for production query patterns."""

    # -----------------------------------------------------------------------
    # 1. audit_logs — tenant_id + created_at DESC (list_logs, get_daily_stats)
    #    Current state: 5 single-column indexes, 0 index scans, 100% seq scans
    #    The AuditService always filters by tenant_id first, then orders by
    #    created_at DESC. A composite index covers both the filter and the sort.
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_audit_logs_tenant_created",
        "audit_logs",
        ["tenant_id", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # audit_logs — user_id + created_at DESC (filter by user within tenant)
    op.create_index(
        "ix_audit_logs_user_created",
        "audit_logs",
        ["user_id", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # audit_logs — tenant_id + action + created_at (daily stats GROUP BY)
    op.create_index(
        "ix_audit_logs_tenant_action_created",
        "audit_logs",
        ["tenant_id", "action", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 2. search_logs — tenant_id + created_at (analytics: trends, popular, unanswered)
    #    Current state: 51.2% seq scans. All analytics queries filter by
    #    tenant_id + created_at >= since.
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_search_logs_tenant_created",
        "search_logs",
        ["tenant_id", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # search_logs — tenant_id + result_count + created_at (unanswered queries filter)
    op.create_index(
        "ix_search_logs_tenant_result_created",
        "search_logs",
        ["tenant_id", "result_count", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 3. documents — repository_id + status + created_at DESC (list_by_repository)
    #    The DocumentService.list_by_repository always filters by repository_id,
    #    optionally by status, and orders by created_at DESC.
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_documents_repo_status_created",
        "documents",
        ["repository_id", "status", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # documents — status + created_at (processing/failed document listing across repos)
    op.create_index(
        "ix_documents_status_created",
        "documents",
        ["status", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 4. blocks — repository_id + validity_status (active block searches)
    #    Search service filters blocks by repository + validity_status='active'.
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_blocks_repo_validity",
        "blocks",
        ["repository_id", "validity_status"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # blocks — block_hash (deduplication lookups during pipeline ingestion)
    op.create_index(
        "ix_blocks_block_hash",
        "blocks",
        ["block_hash"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # blocks — is_indexed partial index (find blocks pending vectorization)
    op.create_index(
        "ix_blocks_pending_index",
        "blocks",
        ["repository_id", "is_indexed"],
        if_not_exists=True,
        postgresql_using="btree",
        postgresql_where="is_indexed = false",
    )

    # blocks — block_type filter (router filters by block_type)
    op.create_index(
        "ix_blocks_doc_type_index",
        "blocks",
        ["document_id", "block_type", "block_index"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 5. tenant_links — user_id + status (active link queries)
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_tenant_links_user_status",
        "tenant_links",
        ["user_id", "status"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 6. chunks — repository_id + document_id (legacy pipeline queries)
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_chunks_repo_document",
        "chunks",
        ["repository_id", "document_id"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 7. llm_usage — tenant_id + created_at (cost analytics by date range)
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_llm_usage_tenant_created",
        "llm_usage",
        ["tenant_id", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # llm_usage — document_id + task (pipeline cost tracking per document)
    op.create_index(
        "ix_llm_usage_document_task",
        "llm_usage",
        ["document_id", "task"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 8. GIN indexes on JSONB fields queried with containment operators
    # -----------------------------------------------------------------------

    # blocks.metadata — searched via @> containment for ontology filtering
    op.create_index(
        "ix_blocks_metadata_gin",
        "blocks",
        ["metadata"],
        if_not_exists=True,
        postgresql_using="gin",
    )

    # blocks.entities — entity-based filtering (speakers, people, orgs)
    op.create_index(
        "ix_blocks_entities_gin",
        "blocks",
        ["entities"],
        if_not_exists=True,
        postgresql_using="gin",
    )

    # documents.processing_meta — pipeline stage querying
    op.create_index(
        "ix_documents_processing_meta_gin",
        "documents",
        ["processing_meta"],
        if_not_exists=True,
        postgresql_using="gin",
    )

    # -----------------------------------------------------------------------
    # 9. scheduled_actions — pending actions due for execution
    #    Table may not exist if migration 012 was skipped; guard with try/except.
    # -----------------------------------------------------------------------
    try:
        op.create_index(
            "ix_scheduled_actions_pending_due",
            "scheduled_actions",
            ["scheduled_at"],
            if_not_exists=True,
            postgresql_using="btree",
            postgresql_where="status = 'pending'",
        )
    except Exception:
        pass  # Table does not exist yet; index will be created when table is added

    # -----------------------------------------------------------------------
    # 10. dlq_messages — pending messages for retry processing
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_dlq_messages_pending_topic",
        "dlq_messages",
        ["topic", "created_at"],
        if_not_exists=True,
        postgresql_using="btree",
        postgresql_where="status = 'pending'",
    )

    # -----------------------------------------------------------------------
    # 11. anonymization_logs — tenant_id + block_id (audit trail lookups)
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_anonymization_logs_tenant",
        "anonymization_logs",
        ["tenant_id"],
        if_not_exists=True,
        postgresql_using="btree",
    )

    # -----------------------------------------------------------------------
    # 12. lifecycle_feedback — block_id + field_name (feedback aggregation)
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_lifecycle_feedback_block_field",
        "lifecycle_feedback",
        ["block_id", "field_name"],
        if_not_exists=True,
        postgresql_using="btree",
    )


def downgrade() -> None:
    """Remove all indexes added by this migration."""
    op.drop_index("ix_lifecycle_feedback_block_field", table_name="lifecycle_feedback", if_exists=True)
    op.drop_index("ix_anonymization_logs_tenant", table_name="anonymization_logs", if_exists=True)
    op.drop_index("ix_dlq_messages_pending_topic", table_name="dlq_messages", if_exists=True)
    try:
        op.drop_index("ix_scheduled_actions_pending_due", table_name="scheduled_actions", if_exists=True)
    except Exception:
        pass
    op.drop_index("ix_documents_processing_meta_gin", table_name="documents", if_exists=True)
    op.drop_index("ix_blocks_entities_gin", table_name="blocks", if_exists=True)
    op.drop_index("ix_blocks_metadata_gin", table_name="blocks", if_exists=True)
    op.drop_index("ix_llm_usage_document_task", table_name="llm_usage", if_exists=True)
    op.drop_index("ix_llm_usage_tenant_created", table_name="llm_usage", if_exists=True)
    op.drop_index("ix_chunks_repo_document", table_name="chunks", if_exists=True)
    op.drop_index("ix_tenant_links_user_status", table_name="tenant_links", if_exists=True)
    op.drop_index("ix_blocks_doc_type_index", table_name="blocks", if_exists=True)
    op.drop_index("ix_blocks_pending_index", table_name="blocks", if_exists=True)
    op.drop_index("ix_blocks_block_hash", table_name="blocks", if_exists=True)
    op.drop_index("ix_blocks_repo_validity", table_name="blocks", if_exists=True)
    op.drop_index("ix_documents_status_created", table_name="documents", if_exists=True)
    op.drop_index("ix_documents_repo_status_created", table_name="documents", if_exists=True)
    op.drop_index("ix_search_logs_tenant_result_created", table_name="search_logs", if_exists=True)
    op.drop_index("ix_search_logs_tenant_created", table_name="search_logs", if_exists=True)
    op.drop_index("ix_audit_logs_tenant_action_created", table_name="audit_logs", if_exists=True)
    op.drop_index("ix_audit_logs_user_created", table_name="audit_logs", if_exists=True)
    op.drop_index("ix_audit_logs_tenant_created", table_name="audit_logs", if_exists=True)
