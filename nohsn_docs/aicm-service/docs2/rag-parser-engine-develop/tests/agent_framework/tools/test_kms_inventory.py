"""Phase 3 Task C — kms_inventory.get_summary read-only tool.

documents 테이블에 임시 row 를 꽂고 한국어 summary + raw 분포를 검증.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from src.agent_framework.tools import kms_inventory


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
def isolated_repo_id(db):
    """테스트별 고립된 repository_id — 다른 테스트 데이터 영향 차단.

    repositories 테이블에 임시 행을 만들고 yield. 끝나면 그 repo 의 모든 문서 +
    repo 자체 삭제.
    """
    # 임의 tenant_id — 외래키만 만족시키면 됨. 테스트용 더미 tenant 가 있어야 한다면
    # 여기서 생성. 보통 dev DB 에는 default tenant 가 있다.
    tenant_row = db.execute(
        text("SELECT id FROM tenants ORDER BY created_at LIMIT 1")
    ).scalar()
    if tenant_row is None:
        tenant_id = str(uuid.uuid4())
        db.execute(
            text(
                """
                INSERT INTO tenants (id, name)
                VALUES (CAST(:id AS uuid), :n)
                """
            ),
            {"id": tenant_id, "n": f"test_tenant_{tenant_id[:8]}"},
        )
        db.commit()
    else:
        tenant_id = str(tenant_row)
    rid = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO repositories (id, tenant_id, name, description)
            VALUES (CAST(:id AS uuid), CAST(:tid AS uuid), :n, 'test')
            """
        ),
        {"id": rid, "tid": tenant_id, "n": f"test_repo_{rid[:8]}"},
    )
    db.commit()
    yield rid
    db.execute(
        text("DELETE FROM documents WHERE repository_id = CAST(:id AS uuid)"),
        {"id": rid},
    )
    db.execute(
        text("DELETE FROM repositories WHERE id = CAST(:id AS uuid)"), {"id": rid}
    )
    db.commit()


def _insert_doc(db, rid: str, status: str, title: str) -> str:
    did = str(uuid.uuid4())
    db.execute(
        text(
            """
            INSERT INTO documents (id, tenant_id, repository_id, title, status, version,
                                   processing_meta, legal_hold)
            VALUES (CAST(:id AS uuid),
                    CAST('00000000-0000-0000-0000-000000000000' AS uuid),
                    CAST(:rid AS uuid), :t, :s, 1,
                    CAST(:meta AS jsonb), false)
            """
        ),
        {
            "id": did,
            "rid": rid,
            "t": title,
            "s": status,
            "meta": '{"activation":{"trust_score":0.7}}',
        },
    )
    db.commit()
    return did


def test_get_summary_returns_summary_ko(db, isolated_repo_id):
    _insert_doc(db, isolated_repo_id, "active", "doc_a1")
    _insert_doc(db, isolated_repo_id, "active", "doc_a2")
    _insert_doc(db, isolated_repo_id, "pending_review", "doc_p1")
    _insert_doc(db, isolated_repo_id, "archived", "doc_arc1")

    res = kms_inventory.get_summary(db_conn=db, repository_id=isolated_repo_id)
    assert "summary_ko" in res
    assert "raw" in res
    assert res["raw"]["by_status"].get("active") == 2
    assert res["raw"]["by_status"].get("pending_review") == 1
    assert res["raw"]["by_status"].get("archived") == 1
    # 한국어 요약에 핵심 숫자/단어가 포함됐는지
    s = res["summary_ko"]
    assert "활성 문서" in s
    assert "2건" in s
    assert "1건" in s
    assert res["raw"]["total_size_bytes"] > 0
    # 최근 7일 — 방금 생성한 4건 모두 포함
    assert sum(res["raw"]["recent_7d"].values()) >= 4


def test_get_summary_with_no_data_returns_zeros(db, isolated_repo_id):
    """비어있는 repository — by_status 빈 dict, summary_ko 는 0건 안내."""
    res = kms_inventory.get_summary(db_conn=db, repository_id=isolated_repo_id)
    assert res["raw"]["by_status"] == {}
    assert res["raw"]["total_size_bytes"] == 0
    assert sum(res["raw"]["recent_7d"].values()) == 0
    s = res["summary_ko"]
    # 0건 표시 — "0건" 이 들어가거나 active=0 명시
    assert "0건" in s
