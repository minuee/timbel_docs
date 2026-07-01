import uuid
import pytest
from sqlalchemy import text
from src.agent_framework.activation.service import ActivationService
from src.agent_framework.activation.state import ActivationState, InvalidTransition


_TEST_REPO_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def doc_id(db):
    did = str(uuid.uuid4())
    db.execute(text("""
        INSERT INTO documents (id, tenant_id, repository_id, title, status, processing_meta)
        VALUES (CAST(:id AS uuid),
                CAST('00000000-0000-0000-0000-000000000000' AS uuid),
                CAST(:rid AS uuid), 'sample', 'pending_review',
                '{"activation":{}}'::jsonb)
    """), {"id": did, "rid": _TEST_REPO_ID})
    db.commit()
    yield did
    # cleanup
    db.execute(text("DELETE FROM documents WHERE id=CAST(:id AS uuid)"), {"id": did})
    db.commit()


def test_approve_sets_active_and_audit(db, doc_id):
    svc = ActivationService(db_session=db)
    res = svc.approve(artifact_type="document", artifact_id=doc_id,
                      user_id="u1", action="add", note="ok")
    assert res["status"] == ActivationState.active.value
    row = db.execute(
        text("SELECT status, processing_meta FROM documents WHERE id=CAST(:id AS uuid)"),
        {"id": doc_id},
    ).mappings().first()
    assert row["status"] == "active"
    act = row["processing_meta"]["activation"]
    assert act["approved_by"] == "u1"
    assert act["approved_at"]
    assert act["auto_approved"] is False


def test_reject_sets_rejected_with_reason(db, doc_id):
    svc = ActivationService(db_session=db)
    res = svc.reject("document", doc_id, user_id="u1", reason="spam")
    assert res["status"] == "rejected"
    row = db.execute(
        text("SELECT status, processing_meta FROM documents WHERE id=CAST(:id AS uuid)"),
        {"id": doc_id},
    ).mappings().first()
    assert row["status"] == "rejected"
    assert row["processing_meta"]["activation"]["rejected_reason"] == "spam"


def test_deactivate_then_reactivate(db, doc_id):
    svc = ActivationService(db_session=db)
    svc.approve("document", doc_id, user_id="u1", action="add")
    svc.deactivate("document", doc_id, user_id="u1", reason="obsolete")
    r = db.execute(
        text("SELECT status FROM documents WHERE id=CAST(:id AS uuid)"), {"id": doc_id}
    ).scalar()
    assert r == "archived"
    svc.reactivate("document", doc_id, user_id="u1")
    r = db.execute(
        text("SELECT status FROM documents WHERE id=CAST(:id AS uuid)"), {"id": doc_id}
    ).scalar()
    assert r == "active"


def test_invalid_transition_raises(db, doc_id):
    svc = ActivationService(db_session=db)
    with pytest.raises(InvalidTransition):
        svc.deactivate("document", doc_id, user_id="u1", reason="x")


def test_approve_is_idempotent(db, doc_id):
    svc = ActivationService(db_session=db)
    svc.approve("document", doc_id, user_id="u1", action="add")
    res = svc.approve("document", doc_id, user_id="u2", action="add")
    assert res["status"] == "active"
    row = db.execute(
        text("SELECT processing_meta FROM documents WHERE id=CAST(:id AS uuid)"),
        {"id": doc_id},
    ).mappings().first()
    assert row["processing_meta"]["activation"]["approved_by"] == "u1"


def test_verify_sets_verified_and_trust_score(db, doc_id):
    svc = ActivationService(db_session=db)
    svc.approve("document", doc_id, user_id="u1", action="add")
    res = svc.verify("document", doc_id, user_id="u2", note="검토완료")
    assert res["verified_at"]
    assert res["trust_score"] > 0.5
    row = db.execute(
        text("SELECT processing_meta FROM documents WHERE id=CAST(:id AS uuid)"),
        {"id": doc_id},
    ).mappings().first()
    act = row["processing_meta"]["activation"]
    assert act["verified_by"] == "u2"
    assert act["trust_score"] > 0.5
