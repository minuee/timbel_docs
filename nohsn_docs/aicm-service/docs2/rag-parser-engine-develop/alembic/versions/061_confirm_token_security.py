"""confirm_token security — sha256 hash + TTL + 5축 binding (Phase 1.5A Task 8b).

Revision ID: 061
Revises: 060
Create Date: 2026-05-07

목적 (GPT-5.5 deep dive 결함 #2):
- ``tool_invocations.resume_token`` 이 plaintext 저장 + TTL 부재 + binding 부재.
- DB 누출 시 token 평문 노출 → 영구 유효 → 어떤 tenant/account/session/tool
  에서도 재사용 (replay attack + cross-user 위장) 가능.

Fix:
- ``token_hash`` (sha256 hex) 컬럼 신설. 기존 ``resume_token`` (plaintext) 은
  *deprecated* 라벨로 유지 (NOT NULL 해제) — 점진적 마이그레이션. 신규 호출은
  ``token_hash`` 만 INSERT, 기존 호환 코드는 ``resume_token`` 도 함께 채울 수 있게.
- ``expires_at TIMESTAMPTZ NOT NULL`` — 기본 5분 (env CONFIRM_TOKEN_TTL_SECONDS).
- 5축 binding: ``bound_tenant_id`` / ``bound_account_id`` / ``bound_session_id``
  / ``bound_tool`` / ``bound_input_hash`` — token 사용 시 모두 일치해야 통과.
- ``consumed_at TIMESTAMPTZ NULL`` + ``status`` CHECK 에 'consumed','expired',
  'revoked' 추가. 일회용 SELECT FOR UPDATE 패턴.
- index ``ix_tool_inv_token_hash_active`` (token_hash) WHERE status='pending'.
- index ``ix_tool_inv_expires_at`` (expires_at) WHERE status='pending' — 만료
  배치 cleanup 빠르게.

회귀 위험:
- 기존 코드 (resume_token plaintext 흐름) 는 그대로 동작. 새 컬럼 모두 nullable
  이거나 server_default='pending_confirm' 시 NULL 허용 패턴 유지.
- ``status`` CHECK 제약을 새 값 포함하도록 확장 (기존 값 호환).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "061"
down_revision: Union[str, None] = "060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """tool_invocations 보안 강화 — token_hash + TTL + 5축 binding."""
    # 1. 새 컬럼 추가 (모두 nullable 로 시작 — 기존 row 백필 후 enforce 가능).
    op.add_column(
        "tool_invocations",
        sa.Column("token_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("bound_tenant_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("bound_account_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("bound_session_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("bound_tool", sa.String(128), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("bound_input_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "tool_invocations",
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # 2. resume_token (plaintext, deprecated) — NOT NULL 이 아니었으므로 그대로.
    #    신규 코드는 token_hash 만 채움. 기존 코드 호환을 위해 컬럼은 유지.

    # 3. status CHECK 제약 갱신 — 'consumed','expired','revoked' 추가.
    op.execute("ALTER TABLE tool_invocations DROP CONSTRAINT IF EXISTS tool_inv_status_check")
    op.execute(
        """
        ALTER TABLE tool_invocations
        ADD CONSTRAINT tool_inv_status_check
        CHECK (status IN (
            'pending_confirm','pending_resume','succeeded','failed',
            'dry_run','canceled','timeout','consumed','expired','revoked'
        ))
        """
    )

    # 4. 인덱스 — token_hash lookup 빠르게 (pending 만).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tool_inv_token_hash_active "
        "ON tool_invocations (token_hash) "
        "WHERE status IN ('pending_confirm','pending_resume')"
    )
    # 만료 cleanup 용 부분 인덱스.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tool_inv_expires_at "
        "ON tool_invocations (expires_at) "
        "WHERE status IN ('pending_confirm','pending_resume')"
    )


def downgrade() -> None:
    """역순으로 인덱스/컬럼 제거 + status CHECK 원상복구."""
    op.execute("DROP INDEX IF EXISTS ix_tool_inv_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_tool_inv_token_hash_active")

    op.execute("ALTER TABLE tool_invocations DROP CONSTRAINT IF EXISTS tool_inv_status_check")
    op.execute(
        """
        ALTER TABLE tool_invocations
        ADD CONSTRAINT tool_inv_status_check
        CHECK (status IN (
            'pending_confirm','pending_resume','succeeded','failed',
            'dry_run','canceled','timeout'
        ))
        """
    )

    for col in [
        "consumed_at",
        "bound_input_hash",
        "bound_tool",
        "bound_session_id",
        "bound_account_id",
        "bound_tenant_id",
        "expires_at",
        "token_hash",
    ]:
        op.drop_column("tool_invocations", col)
