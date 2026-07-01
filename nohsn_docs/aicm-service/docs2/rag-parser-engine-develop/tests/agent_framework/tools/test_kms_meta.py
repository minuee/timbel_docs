"""F7 — kms_meta.get_my_inventory read-only tool.

tenant 별 문서·저장소·외부 에이전트·일정/일기/뉴스·활성 스킬 카운트 + 마지막
문서 업데이트 시각을 한국어 요약과 함께 반환.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from src.agent_framework.tools import kms_meta


def _sync_url() -> str:
    return (
        os.environ["DATABASE_URL"]
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg", "postgresql")
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


@pytest.fixture
def fresh_tenant(db):
    """깨끗한 테스트용 tenant — 다른 테스트 데이터 0 건 보장."""
    tid = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO tenants (id, name, slug, config, plan, tenant_type,
                                 context_config)
            VALUES (CAST(:id AS uuid), :n, :s,
                    '{}'::jsonb, 'free', 'business',
                    '{}'::jsonb)
            """
        ),
        {"id": tid, "n": f"meta_test_{tid[:8]}", "s": f"meta-test-{tid[:8]}"},
    )
    db.commit()
    yield tid
    # cleanup — 외래키 제약 따라 의존 테이블 먼저 비우기
    db.execute(
        text("DELETE FROM tenant_skills WHERE tenant_id = CAST(:id AS uuid)"),
        {"id": tid},
    )
    db.execute(
        text(
            """
            DELETE FROM documents
             WHERE repository_id IN (
               SELECT id FROM repositories WHERE tenant_id = CAST(:id AS uuid)
             )
            """
        ),
        {"id": tid},
    )
    db.execute(
        text("DELETE FROM repositories WHERE tenant_id = CAST(:id AS uuid)"),
        {"id": tid},
    )
    db.execute(
        text("DELETE FROM agents WHERE tenant_id = CAST(:id AS uuid)"),
        {"id": tid},
    )
    db.execute(
        text("DELETE FROM tenants WHERE id = CAST(:id AS uuid)"), {"id": tid}
    )
    db.commit()


def _make_repo(db, tid: str) -> str:
    rid = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO repositories (id, tenant_id, name, description)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :n, 'test')
            """
        ),
        {"id": rid, "tid": tid, "n": f"meta_repo_{rid[:8]}"},
    )
    db.commit()
    return rid


def _make_doc(db, tid: str, rid: str, status: str = "active") -> str:
    did = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO documents (id, tenant_id, repository_id, title, status,
                                   version, processing_meta, legal_hold)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), CAST(:rid AS uuid),
                    :t, :s, 1, '{}'::jsonb, false)
            """
        ),
        {"id": did, "tid": tid, "rid": rid, "t": f"doc_{did[:6]}", "s": status},
    )
    db.commit()
    return did


def test_empty_tenant_returns_zeros(db, fresh_tenant):
    res = kms_meta.get_my_inventory(db_conn=db, tenant_id=fresh_tenant)
    raw = res["raw"]
    assert raw["documents"] == 0
    assert raw["repositories"] == 0
    assert raw["agents"] == 0
    assert raw["active_skills"] == 0
    assert raw["last_doc_update"] is None
    # 0건 tenant 는 "등록된 자료가 아직 없습니다" 안내
    assert "등록된 자료가 아직 없습니다" in res["summary_ko"]


def test_documents_repos_counted(db, fresh_tenant):
    rid = _make_repo(db, fresh_tenant)
    _make_doc(db, fresh_tenant, rid, "active")
    _make_doc(db, fresh_tenant, rid, "active")
    _make_doc(db, fresh_tenant, rid, "pending_review")  # not active → 제외

    res = kms_meta.get_my_inventory(db_conn=db, tenant_id=fresh_tenant)
    assert res["raw"]["documents"] == 2
    assert res["raw"]["repositories"] == 1
    assert "문서 2건" in res["summary_ko"]
    assert "저장소 1개" in res["summary_ko"]
    assert res["raw"]["last_doc_update"] is not None


def test_personal_tenant_id_fallback(db, fresh_tenant):
    """tenant_id 미지정 시 personal_tenant_id 로 fallback."""
    rid = _make_repo(db, fresh_tenant)
    _make_doc(db, fresh_tenant, rid)

    res = kms_meta.get_my_inventory(db_conn=db, personal_tenant_id=fresh_tenant)
    assert res["raw"]["documents"] == 1


def test_no_tenant_returns_friendly_message(db):
    res = kms_meta.get_my_inventory(db_conn=db)
    assert res["raw"] == {}
    assert "tenant 가 지정되지 않" in res["summary_ko"]
