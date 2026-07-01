"""기존 agent_schedule / agent_diary / agent_expense documents 의 NULL scope_group → 'personal' 일괄 backfill.

Revision ID: 045
Revises: 044
Create Date: 2026-04-28

배경
----
T4(044) 도입 후 documents.scope_group 가 NULL 또는 신규 row 의 'personal'
default 로 분리. 그러나 044 이전 생성된 agent_schedule / agent_diary /
agent_expense document 는 NULL 이라 scope 인지 query 에서 누락. codex
검토(2026-04-28): "list 의 None=all-scopes vs create 의 None='personal'
비대칭이 혼란 유발 → backfill 권장".

KMS 본문(지식 도메인)은 NULL 의도 그대로 유지 — agent_schedule/diary/
expense document_type 으로 등록된 row 만 backfill.
"""
from alembic import op


revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


AGENT_DOC_TYPES = ("agent_schedule", "agent_diary", "agent_expense")


def upgrade() -> None:
    op.execute(
        """
        UPDATE documents d
           SET scope_group = 'personal'
          FROM document_types dt
         WHERE d.document_type_id = dt.id
           AND d.scope_group IS NULL
           AND dt.name IN ('agent_schedule', 'agent_diary', 'agent_expense')
        """
    )


def downgrade() -> None:
    # 의도적 no-op — 045 가 backfill 한 row 와 044 이후 신규 생성된 row
    # ('personal' default) 를 구별할 수 없음. downgrade 시 신규 row 의
    # scope_group 까지 NULL 로 만들면 scope-aware query 에서 사라짐.
    # gpt-5.5 검토 (round 4): 안전한 downgrade 는 컬럼 자체를 dropping 하는
    # 044 의 downgrade 에 위임 (컬럼 자체가 사라지므로 row-level 복원 불필요).
    pass
