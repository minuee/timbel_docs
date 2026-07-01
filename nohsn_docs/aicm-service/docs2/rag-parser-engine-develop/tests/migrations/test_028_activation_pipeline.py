"""Alembic 028 migration smoke tests."""
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.usefixtures("alembic_upgraded_to_028")


# ---------------------------------------------------------------------------
# Task 1: documents.status CHECK 통일 (7 labels)
# ---------------------------------------------------------------------------
def test_documents_status_check_includes_all_labels(db):
    allowed = {"draft", "processing", "pending_review", "active", "archived", "rejected", "failed"}
    row = db.execute(
        text(
            "SELECT pg_get_constraintdef(oid) AS def "
            "FROM pg_constraint WHERE conname = 'documents_status_check'"
        )
    ).mappings().first()
    assert row is not None, "documents_status_check CHECK 제약 없음"
    for label in allowed:
        assert f"'{label}'" in row["def"], f"{label} not in CHECK"


def test_documents_status_rejects_unknown(db):
    with pytest.raises(Exception):
        db.execute(
            text("INSERT INTO documents (id, title, status) VALUES ('d_bad', 't', 'weirdstate')")
        )


# ---------------------------------------------------------------------------
# Task 2: skill_drafts.status_v2 백필 + CHECK
# ---------------------------------------------------------------------------
def test_skill_drafts_status_v2_backfilled(db):
    rows = db.execute(
        text(
            "SELECT status, status_v2 FROM skill_drafts "
            "WHERE status IS NOT NULL LIMIT 100"
        )
    ).mappings().all()
    mapping = {
        "pending": "pending_review",
        "approved": "active",
        "rejected": "rejected",
        "expired": "archived",
    }
    for r in rows:
        assert r["status_v2"] == mapping[r["status"]], f"mismatch: {r}"


def test_skill_drafts_status_v2_check(db):
    row = db.execute(
        text(
            "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conname = 'skill_drafts_status_v2_check'"
        )
    ).mappings().first()
    assert row is not None
    for label in (
        "draft",
        "processing",
        "pending_review",
        "active",
        "archived",
        "rejected",
        "failed",
    ):
        assert f"'{label}'" in row["def"]


# ---------------------------------------------------------------------------
# Task 5: 기존 active documents 에 legacy_auto_approved 백필
# ---------------------------------------------------------------------------
def test_legacy_active_docs_backfilled(db):
    """028 migration 이 기존 status='active' 문서의
    processing_meta.activation.legacy_auto_approved=true 설정했는지 확인."""
    legacy = db.execute(
        text(
            """
            SELECT COUNT(*) AS n FROM documents
             WHERE status = 'active'
               AND (processing_meta -> 'activation' ->> 'legacy_auto_approved')
                   IS NULL
            """
        )
    ).mappings().first()
    # migration 후에는 active 문서 중 legacy_auto_approved 미설정이 0 이어야 함
    assert legacy["n"] == 0, (
        f"backfill incomplete: {legacy['n']} active docs missing "
        "processing_meta.activation.legacy_auto_approved"
    )


# ---------------------------------------------------------------------------
# Task 7: CC-pair 3테이블 (connectors / connector_credentials /
#         connector_credential_pairs)
# ---------------------------------------------------------------------------
def test_cc_pair_tables_exist(db):
    for tbl in ("connectors", "connector_credentials", "connector_credential_pairs"):
        row = db.execute(text(f"SELECT to_regclass('{tbl}')")).scalar()
        assert row == tbl, f"{tbl} missing"


def test_ccp_fk_cascade(db):
    # 이전 실행에서 남은 fixture 행 정리 — credential 은 FK RESTRICT 라서
    # connector CASCADE 로는 지워지지 않아 UNIQUE 충돌이 날 수 있다.
    db.execute(text("DELETE FROM connector_credential_pairs WHERE id='p_x'"))
    db.execute(text("DELETE FROM connector_credentials WHERE id='cr_x'"))
    db.execute(text("DELETE FROM connectors WHERE id='c_x'"))
    db.execute(
        text(
            """
            INSERT INTO connectors
              (id, tenant_id, name, base_url, spec_kind, spec,
               allowed_ops, side_effect_level, created_by)
              VALUES ('c_x', 't1', 'cx', 'https://x', 'openapi', '{}'::jsonb,
                      '[]'::jsonb, 'read_only', 'u1');
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO connector_credentials
              (id, tenant_id, name, auth_type)
              VALUES ('cr_x', 't1', 'crx', 'none');
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO connector_credential_pairs
              (id, tenant_id, connector_id, credential_id, status)
              VALUES ('p_x', 't1', 'c_x', 'cr_x', 'draft');
            """
        )
    )
    db.execute(text("DELETE FROM connectors WHERE id='c_x'"))
    n = db.execute(
        text("SELECT COUNT(*) FROM connector_credential_pairs WHERE id='p_x'")
    ).scalar()
    assert n == 0, "ON DELETE CASCADE from connectors not working"


# ---------------------------------------------------------------------------
# Task 8: tool_invocations 감사 + interrupt/resume (델타 #5)
# ---------------------------------------------------------------------------
def test_tool_inv_status_check_includes_pending(db):
    row = db.execute(
        text(
            "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conname = 'tool_inv_status_check'"
        )
    ).mappings().first()
    assert row is not None, "tool_inv_status_check CHECK 제약 없음"
    for label in (
        "pending_confirm",
        "pending_resume",
        "succeeded",
        "failed",
        "dry_run",
        "canceled",
        "timeout",
    ):
        assert f"'{label}'" in row["def"], f"{label} not in CHECK"


def test_tool_inv_has_resume_token_and_turn_id(db):
    cols = {
        r["column_name"]
        for r in db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'tool_invocations'"
            )
        ).mappings().all()
    }
    assert "resume_token" in cols
    assert "turn_id" in cols
    assert "cc_pair_id" in cols
    assert "confirmed_by_user_id" in cols


def test_tool_inv_pending_partial_index(db):
    row = db.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'idx_tool_inv_pending'"
        )
    ).mappings().first()
    assert row is not None, "idx_tool_inv_pending 없음"
    assert "pending_confirm" in row["indexdef"] or "pending" in row["indexdef"]


# ---------------------------------------------------------------------------
# Task 9: knowledge_freshness_runs (델타 #4)
# ---------------------------------------------------------------------------
def test_freshness_runs_table(db):
    cols = {
        r["column_name"]
        for r in db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'knowledge_freshness_runs'"
            )
        ).mappings().all()
    }
    assert {
        "id",
        "tenant_id",
        "started_at",
        "finished_at",
        "status",
        "docs_scanned",
        "issues_found",
        "trigger",
    }.issubset(cols), f"missing cols: expected subset not in {cols}"
