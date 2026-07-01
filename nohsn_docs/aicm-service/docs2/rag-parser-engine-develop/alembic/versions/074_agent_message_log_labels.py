"""agent_message_log_labels — 골든셋 라벨링 인프라 (#163).

Revision ID: 074
Revises: 073
Create Date: 2026-05-07

Spec: docs/superpowers/specs/2026-05-07-golden-labeling-and-baseline-monitoring.md
GPT-5 phase 0: docs/superpowers/specs/2026-05-07-golden-labeling-and-baseline-monitoring.gpt5-phase0.json

목적 (사용자 명시 2026-05-07):
- 31B baseline 측정 + 회귀 가드를 위해 agent_message_log 위에 *품질 라벨* 적층.
- 1 row 1 라벨 (per labeled_by + rubric_version) — replay 가능한 평가 데이터셋.

GPT-5 verdict 반영 (block → fix 적용):
- expected_response / expected_citations_json — accuracy_score boolean 보강.
- hallucination_flag / refusal_correct / persona_score / safety_privacy_score
  — schema 사각지대 차단.
- rubric_version + label_status — 룰셋 진화 시 baseline 비교 가능 + draft
  라벨이 release metric 에 새지 않게.
- severity / eval_context_json — 회귀 우선순위 + freezing metadata.
- CHECK 제약 (1-5) — UI 외 입력 경로에서도 데이터 무결성.

회귀 0:
- 신규 테이블만, 기존 테이블 ALTER 0.
- agent_message_log / agents / users 어떤 컬럼도 변경 X.
- 51 tenant 영향 0 (신규 row 0).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "074"
down_revision: Union[str, None] = "073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_message_log_labels",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_log_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_message_log.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ---------- core labels ----------
        sa.Column("intent_label", sa.Text(), nullable=True),
        sa.Column("slots_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "tool_trace_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("tone_score", sa.Integer(), nullable=True),
        sa.Column("citation_correct", sa.Boolean(), nullable=True),
        sa.Column("accuracy_score", sa.Integer(), nullable=True),
        # ---------- gpt-5 phase 0 fixes ----------
        sa.Column("expected_response", sa.Text(), nullable=True),
        sa.Column(
            "expected_citations_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("hallucination_flag", sa.Boolean(), nullable=True),
        sa.Column("refusal_correct", sa.Boolean(), nullable=True),
        sa.Column("persona_score", sa.Integer(), nullable=True),
        sa.Column("safety_privacy_score", sa.Integer(), nullable=True),
        sa.Column(
            "severity",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'low'"),
        ),
        sa.Column(
            "eval_context_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # ---------- governance ----------
        sa.Column(
            "rubric_version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
        sa.Column(
            "label_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "labeled_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "labeled_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        # ---------- CHECK constraints (1-5 score, label_status enum, severity enum) ----------
        sa.CheckConstraint(
            "tone_score IS NULL OR (tone_score BETWEEN 1 AND 5)",
            name="ck_label_tone_score_range",
        ),
        sa.CheckConstraint(
            "accuracy_score IS NULL OR (accuracy_score BETWEEN 1 AND 5)",
            name="ck_label_accuracy_score_range",
        ),
        sa.CheckConstraint(
            "persona_score IS NULL OR (persona_score BETWEEN 1 AND 5)",
            name="ck_label_persona_score_range",
        ),
        sa.CheckConstraint(
            "safety_privacy_score IS NULL OR (safety_privacy_score BETWEEN 1 AND 5)",
            name="ck_label_safety_privacy_score_range",
        ),
        sa.CheckConstraint(
            "label_status IN ('draft','accepted','rejected','needs_adjudication')",
            name="ck_label_status_enum",
        ),
        sa.CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="ck_label_severity_enum",
        ),
    )

    # UNIQUE(message_log_id, labeled_by, rubric_version) — 같은 사람이 같은 row 를
    # 같은 rubric 으로 두 번 라벨링 안되게. rubric 변경 시 재라벨링 가능.
    # GPT-5 phase 5 fix — labeled_by NULL 허용 시 PostgreSQL UNIQUE 는 NULL 을
    # 별 row 로 취급. NULLS NOT DISTINCT 명시로 NULL labeler 도 중복 차단.
    # PostgreSQL 15+ 필수.
    op.execute(
        "CREATE UNIQUE INDEX uq_message_label_rater_rubric "
        "ON agent_message_log_labels (message_log_id, labeled_by, rubric_version) "
        "NULLS NOT DISTINCT"
    )
    op.create_index(
        "ix_msg_label_message",
        "agent_message_log_labels",
        ["message_log_id"],
    )
    op.create_index(
        "ix_msg_label_status",
        "agent_message_log_labels",
        ["label_status"],
    )
    op.create_index(
        "ix_msg_label_rubric",
        "agent_message_log_labels",
        ["rubric_version"],
    )
    op.create_index(
        "ix_msg_label_rater",
        "agent_message_log_labels",
        ["labeled_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_msg_label_rater", table_name="agent_message_log_labels")
    op.drop_index("ix_msg_label_rubric", table_name="agent_message_log_labels")
    op.drop_index("ix_msg_label_status", table_name="agent_message_log_labels")
    op.drop_index("ix_msg_label_message", table_name="agent_message_log_labels")
    op.drop_index("uq_message_label_rater_rubric", table_name="agent_message_log_labels")
    op.drop_table("agent_message_log_labels")
