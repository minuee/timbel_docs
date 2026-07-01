"""documents.tenant_id 직접 컬럼 추가 (멀티테넌트 격리 강화).

Revision ID: 030
Revises: 029
Create Date: 2026-04-25

forward-only. NULL allowed initially → backfill → NOT NULL → index.

Backfill 전략: ``repositories.tenant_id`` 를 통해 채움.
백필 후 NULL row 가 남아있으면 (orphan doc) NOT NULL 강제는 skip — 운영
정합성 수동 처리 필요. NOTICE 로 경고.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. nullable 컬럼 추가
    op.add_column(
        "documents",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
    )

    # 2. backfill — repositories.tenant_id 에서
    op.execute(
        """
        UPDATE documents d
           SET tenant_id = r.tenant_id
          FROM repositories r
         WHERE d.repository_id = r.id
           AND d.tenant_id IS NULL
        """
    )

    # 3. NOT NULL 강제 — 백필 결과 NULL 0건일 때만
    op.execute(
        """
        DO $$
        DECLARE
            null_count INT;
        BEGIN
            SELECT COUNT(*) INTO null_count FROM documents WHERE tenant_id IS NULL;
            IF null_count > 0 THEN
                RAISE NOTICE 'Some documents still have NULL tenant_id (count: %), keeping nullable for safety', null_count;
            ELSE
                ALTER TABLE documents ALTER COLUMN tenant_id SET NOT NULL;
            END IF;
        END $$;
        """
    )

    # 4. 인덱스 — (tenant_id, status) 조회 패턴 가속
    op.create_index(
        "idx_documents_tenant_status",
        "documents",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_documents_tenant_status", table_name="documents")
    op.drop_column("documents", "tenant_id")
