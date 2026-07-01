"""Phase 2 T2.4 — RLS write path 회귀 (alembic 081 적용 후 DB 통합 검증).

spec §8.1 명시: "write path (INSERT/UPDATE/DELETE) 회귀 테스트 필수 — read-only
RLS 보호만으로 부족".

본 테스트는 실 PostgreSQL 이 필요하며 alembic 081 이 적용된 상태를 가정한다.
운영 환경에서 staging 회귀 시 ``pytest -m requires_db tests/db/`` 로 호출.

미적용 환경에서는 conftest fixture 가 자동 skip.
"""
from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.requires_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sync_db_url() -> str | None:
    """DATABASE_URL 을 psycopg2 driver 로 변환."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


@pytest.fixture(scope="module")
def engine():
    url = _sync_db_url()
    if not url:
        pytest.skip("DATABASE_URL not set — requires_db test skipped")
    try:
        from sqlalchemy import create_engine
    except ImportError:
        pytest.skip("sqlalchemy not available")
    eng = create_engine(url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """transaction 단위 RLS context 격리. 매 test 끝나면 ROLLBACK."""
    with engine.connect() as connection:
        trans = connection.begin()
        try:
            yield connection
        finally:
            trans.rollback()


def _set_rls(conn, *, scope: str, tenant_id: str | None, agent_id: str | None = None) -> None:
    """alembic 081 정책이 참조하는 GUC 3종 SET LOCAL."""
    from sqlalchemy import text

    conn.execute(text("SELECT set_config('app.current_scope', :v, true)"), {"v": scope})
    conn.execute(
        text("SELECT set_config('app.current_tenant_id', :v, true)"),
        {"v": tenant_id or ""},
    )
    conn.execute(
        text("SELECT set_config('app.current_agent_id', :v, true)"),
        {"v": agent_id or ""},
    )


@pytest.fixture
def tenants(conn):
    """두 tenant 시드 — cross-tenant write 차단 검증용."""
    from sqlalchemy import text

    # superadmin scope 로 transaction 시작 (RLS 우회 — current_user 화이트리스트 의존).
    # 본 fixture 는 alembic 081 적용 후 superadmin role 로 실행해야 함.
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    _set_rls(conn, scope="superadmin", tenant_id=None)
    conn.execute(
        text(
            "INSERT INTO tenants (id, name, slug) VALUES "
            "(:a, 'TenantA', 'tenant-a-' || :a), "
            "(:b, 'TenantB', 'tenant-b-' || :b)"
        ),
        {"a": tenant_a, "b": tenant_b},
    )
    return {"a": tenant_a, "b": tenant_b}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_role_attributes_after_migration(conn) -> None:
    """alembic 081 적용 후 lucas_kms_app / lucas_kms_migrate role 속성 검증."""
    from sqlalchemy import text

    row = conn.execute(
        text(
            "SELECT rolsuper, rolbypassrls, rolcanlogin "
            "FROM pg_roles WHERE rolname = 'lucas_kms_app'"
        )
    ).first()
    if row is None:
        pytest.skip("lucas_kms_app role not created — alembic 081 미적용")
    # NOSUPERUSER NOBYPASSRLS LOGIN — spec §8.1 핵심 요구.
    assert row.rolsuper is False, "lucas_kms_app must be NOSUPERUSER"
    assert row.rolbypassrls is False, "lucas_kms_app must be NOBYPASSRLS"
    assert row.rolcanlogin is True

    row = conn.execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles "
            "WHERE rolname = 'lucas_kms_migrate'"
        )
    ).first()
    if row is None:
        pytest.skip("lucas_kms_migrate role not created")
    assert row.rolsuper is False
    assert row.rolbypassrls is False, "migrate role도 NOBYPASSRLS"


def test_force_rls_applied(conn) -> None:
    """7 KMS table 에 FORCE RLS 비트 설정."""
    from sqlalchemy import text

    expected = (
        "repositories",
        "chunks",
        "search_logs",
        "intent_logs",
        "sections",
        "blocks",
        "categories",
    )
    rows = conn.execute(
        text(
            "SELECT relname, relrowsecurity, relforcerowsecurity "
            "FROM pg_class WHERE relname = ANY(:t)"
        ),
        {"t": list(expected)},
    ).fetchall()
    by_name = {r.relname: r for r in rows}
    for tbl in expected:
        if tbl not in by_name:
            pytest.skip(f"{tbl} not present — alembic 081 미적용 또는 schema mismatch")
        assert by_name[tbl].relrowsecurity is True, f"{tbl}: RLS not enabled"
        assert by_name[tbl].relforcerowsecurity is True, f"{tbl}: FORCE not set"


def test_write_blocked_without_tenant_id(conn, tenants) -> None:
    """tenant_id 미설정 + agent scope → INSERT 실패 (default deny)."""
    from sqlalchemy import exc, text

    _set_rls(conn, scope="agent", tenant_id=None)
    with pytest.raises(exc.DBAPIError):
        # repositories INSERT — tenant_id 부재 시 정책 차단.
        conn.execute(
            text("INSERT INTO repositories (tenant_id, name) VALUES (:tid, 'forbidden')"),
            {"tid": tenants["a"]},
        )


def test_cross_tenant_insert_blocked(conn, tenants) -> None:
    """app.current_tenant_id=A 인데 tenant_id=B 로 INSERT → 정책 거부."""
    from sqlalchemy import exc, text

    _set_rls(conn, scope="admin", tenant_id=tenants["a"])
    with pytest.raises(exc.DBAPIError):
        conn.execute(
            text("INSERT INTO repositories (tenant_id, name) VALUES (:tid, 'cross')"),
            {"tid": tenants["b"]},
        )


def test_same_tenant_insert_allowed(conn, tenants) -> None:
    """app.current_tenant_id=A + tenant_id=A → 정상 INSERT."""
    from sqlalchemy import text

    _set_rls(conn, scope="admin", tenant_id=tenants["a"])
    conn.execute(
        text("INSERT INTO repositories (tenant_id, name) VALUES (:tid, 'same-tenant')"),
        {"tid": tenants["a"]},
    )
    cnt = conn.execute(
        text("SELECT COUNT(*) FROM repositories WHERE tenant_id = :tid"),
        {"tid": tenants["a"]},
    ).scalar()
    assert cnt >= 1


def test_cross_tenant_select_returns_zero_rows(conn, tenants) -> None:
    """superadmin 으로 양쪽 tenant 데이터 시드 후, admin tenant=A 로 SELECT 시 B 0건."""
    from sqlalchemy import text

    # 시드: superadmin (sequence: tenants fixture 가 사용한 conn 의 superadmin scope 유지 필요 X
    #       — 본 test 는 conn fixture 의 새 transaction. 우선 superadmin 으로 두 row 삽입.)
    _set_rls(conn, scope="superadmin", tenant_id=None)
    conn.execute(
        text("INSERT INTO repositories (tenant_id, name) VALUES (:a, 'repo-A'), (:b, 'repo-B')"),
        {"a": tenants["a"], "b": tenants["b"]},
    )

    # admin scope tenant_id=A 로 SELECT — A 만 조회.
    _set_rls(conn, scope="admin", tenant_id=tenants["a"])
    names = conn.execute(text("SELECT name FROM repositories WHERE name IN ('repo-A', 'repo-B')")).scalars().all()
    assert "repo-A" in names
    assert "repo-B" not in names, "cross-tenant SELECT must be blocked"


def test_join_policy_blocks_cross_tenant_sections(conn, tenants) -> None:
    """sections 의 JOIN 정책 — document.tenant_id mismatch 시 SELECT 0건."""
    from sqlalchemy import text

    # 시드: tenant A 의 repository + document + section, tenant B 의 동일.
    _set_rls(conn, scope="superadmin", tenant_id=None)
    repo_a = str(uuid.uuid4())
    repo_b = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO repositories (id, tenant_id, name) VALUES "
            "(:ra, :a, 'ra'), (:rb, :b, 'rb')"
        ),
        {"ra": repo_a, "rb": repo_b, "a": tenants["a"], "b": tenants["b"]},
    )
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO documents (id, tenant_id, repository_id, title) VALUES "
            "(:da, :a, :ra, 'da'), (:db, :b, :rb, 'db')"
        ),
        {
            "da": doc_a, "db": doc_b,
            "a": tenants["a"], "b": tenants["b"],
            "ra": repo_a, "rb": repo_b,
        },
    )
    conn.execute(
        text(
            "INSERT INTO sections (id, document_id, content) VALUES "
            "(gen_random_uuid(), :da, 'sa'), (gen_random_uuid(), :db, 'sb')"
        ),
        {"da": doc_a, "db": doc_b},
    )

    # admin scope tenant_id=A 로 sections SELECT.
    _set_rls(conn, scope="admin", tenant_id=tenants["a"])
    rows = conn.execute(text("SELECT content FROM sections WHERE content IN ('sa', 'sb')")).scalars().all()
    assert "sa" in rows
    assert "sb" not in rows, "JOIN policy must block cross-tenant section"
