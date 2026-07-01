"""custom_tools (Level 1 webhook 인스턴스화)

Revision ID: 055
Revises: 054
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "custom_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # tool 식별자 — 'tenant_slug.custom_name' 또는 'custom.<uuid>'.
        # ToolPicker / agent.allowed_tools 에 노출되는 이름.
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False, server_default="custom"),
        # webhook 호출 설정
        sa.Column("endpoint_url", sa.Text, nullable=False),
        sa.Column("method", sa.Text, nullable=False, server_default="POST"),
        # auth header / 기타 설정 — Fernet 암호화 (token 보호)
        sa.Column("config_encrypted", sa.LargeBinary, nullable=False),
        # JSON Schema dict — input/output 시그니처
        sa.Column("input_schema", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("output_schema", postgresql.JSONB, nullable=False, server_default="{}"),
        # 활성 / 메타
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("tenant_id", "name", name="custom_tools_tenant_name_uq"),
        sa.CheckConstraint("method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')",
                          name="custom_tools_method_check"),
    )
    op.create_index("custom_tools_tenant_idx", "custom_tools", ["tenant_id"],
                    postgresql_where=sa.text("is_active = TRUE"))


def downgrade():
    op.drop_index("custom_tools_tenant_idx", table_name="custom_tools")
    op.drop_table("custom_tools")
