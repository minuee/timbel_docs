"""Activation multi-turn regression — spec §6.3.

5 시나리오:
1. upload → pending → approve → surface in 검색
2. crawl conflict → reject → 미노출
3. supersede chain: old active → new pending → approve+replace → old archived
4. deactivate → reactivate 왕복
5. skill_draft (missing connector) → approve (service-level 허용, UI/API 가 UX 가드)
"""
import os
import uuid
import json as _json
import pytest
from sqlalchemy import create_engine, text

from src.agent_framework.activation.service import ActivationService


DEFAULT_REPO = "00000000-0000-0000-0000-000000000001"


def _sync_url():
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )


@pytest.fixture
def db():
    eng = create_engine(_sync_url())
    conn = eng.connect()
    try:
        yield conn
    finally:
        conn.close()
        eng.dispose()


def _mk_doc(db, status="pending_review", title="t", meta=None):
    did = str(uuid.uuid4())
    default_meta = {"activation": {}}
    if meta:
        default_meta.update(meta)
    db.execute(text("""
        INSERT INTO documents (id, tenant_id, repository_id, title, status, version, processing_meta, legal_hold)
        VALUES (CAST(:id AS uuid),
                CAST('00000000-0000-0000-0000-000000000000' AS uuid),
                CAST(:r AS uuid), :t, :s, 1, CAST(:m AS jsonb), false)
    """), {"id": did, "r": DEFAULT_REPO, "t": title, "s": status,
           "m": _json.dumps(default_meta)})
    db.commit()
    return did


def _cleanup(db, ids):
    for i in ids:
        db.execute(text("DELETE FROM documents WHERE id=CAST(:i AS uuid)"), {"i": i})
    db.commit()


def test_upload_pending_approve_surface(db):
    did = _mk_doc(db)
    ActivationService(db).approve("document", did, user_id="u1", action="add")
    status = db.execute(text("SELECT status FROM documents WHERE id=CAST(:i AS uuid)"),
                        {"i": did}).scalar()
    assert status == "active"
    _cleanup(db, [did])


def test_crawl_conflict_reject(db):
    did = _mk_doc(db, title="크롤 스텁")
    ActivationService(db).reject("document", did, user_id="u1", reason="conflict")
    status = db.execute(text("SELECT status FROM documents WHERE id=CAST(:i AS uuid)"),
                        {"i": did}).scalar()
    assert status == "rejected"
    _cleanup(db, [did])


def test_supersede_chain(db):
    old = _mk_doc(db, status="active", title="v1")
    new = _mk_doc(db, title="v2")
    ActivationService(db).approve("document", new, user_id="u1",
                                   action="replace", target_doc_ids=[old])
    assert db.execute(text("SELECT status FROM documents WHERE id=CAST(:i AS uuid)"),
                      {"i": old}).scalar() == "archived"
    assert db.execute(text("SELECT status FROM documents WHERE id=CAST(:i AS uuid)"),
                      {"i": new}).scalar() == "active"
    _cleanup(db, [old, new])


def test_deactivate_and_reactivate(db):
    did = _mk_doc(db, status="pending_review")
    svc = ActivationService(db)
    svc.approve("document", did, user_id="u1", action="add")
    svc.deactivate("document", did, user_id="u1", reason="obsolete")
    assert db.execute(text("SELECT status FROM documents WHERE id=CAST(:i AS uuid)"),
                      {"i": did}).scalar() == "archived"
    svc.reactivate("document", did, user_id="u1")
    assert db.execute(text("SELECT status FROM documents WHERE id=CAST(:i AS uuid)"),
                      {"i": did}).scalar() == "active"
    _cleanup(db, [did])


def test_skill_draft_missing_connector_service_allows(db):
    # service 는 관대 — approve 허용. UI/API 가 UX 레벨에서 가드함.
    sid = str(uuid.uuid4())
    # 기존 seed 에서 account/tenant id 하나 가져오기
    row = db.execute(text(
        "SELECT id, personal_tenant_id FROM accounts ORDER BY created_at LIMIT 1"
    )).mappings().first()
    if not row:
        pytest.skip("no seed accounts available")
    db.execute(text("""
        INSERT INTO skill_drafts
          (id, account_id, tenant_id, source_user_message, draft_yaml, draft_title,
           status, status_v2, processing_meta)
        VALUES (CAST(:id AS uuid), :aid, :tid, 'msg', 'yaml: x', 'missing-connector-draft',
                'pending', 'pending_review', CAST(:m AS jsonb))
    """), {"id": sid, "aid": row["id"], "tid": row["personal_tenant_id"],
           "m": _json.dumps({"activation": {"dependencies":
                     {"unresolved_apis": 1, "consequential": True}}})})
    db.commit()
    res = ActivationService(db).approve("skill_draft", sid, user_id="u1",
                                         action="add",
                                         execution_policy={"required_connectors": ["ccp_missing"]})
    assert res["status"] == "active"
    db.execute(text("DELETE FROM skill_drafts WHERE id=CAST(:i AS uuid)"), {"i": sid})
    db.commit()
