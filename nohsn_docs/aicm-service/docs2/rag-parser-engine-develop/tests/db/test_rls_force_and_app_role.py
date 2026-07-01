"""Phase 2 T2.4 — alembic 081 FORCE RLS + lucas_kms_app role 단위 검증.

본 테스트는 실 DB 없이 alembic 081 migration 파일의 SQL syntax 와 정합성
(role 권한 비트, FORCE RLS 적용 table 목록, GUC 정책) 을 검증한다.

DB 실행 통합 테스트는 ``tests/db/test_rls_write_path.py`` (``pytest.mark.requires_db``).
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "081_rls_force_lucas_kms_app.py"
)


def _ensure_alembic_stub() -> None:
    """alembic 미설치 환경에서 ``from alembic import op`` 호환 stub 주입.

    본 단위 테스트는 alembic 실 실행이 아닌 *SQL 문 캡쳐* 만 검증.
    """
    try:
        import alembic  # noqa: F401
        from alembic import op  # noqa: F401
        return
    except ImportError:
        pass
    if "alembic" not in sys.modules:
        sys.modules["alembic"] = types.ModuleType("alembic")
    op_mod = types.ModuleType("alembic.op")
    op_mod.execute = MagicMock()  # type: ignore[attr-defined]
    sys.modules["alembic.op"] = op_mod
    setattr(sys.modules["alembic"], "op", op_mod)


def _load_migration_module():
    """alembic 패키지 의존성 없이 module 만 import (op 호출은 mock)."""
    _ensure_alembic_stub()
    spec = importlib.util.spec_from_file_location("alembic_081", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def migration_module():
    return _load_migration_module()


@pytest.fixture
def captured_sql(migration_module):
    """alembic.op.execute 를 mock 으로 캡쳐하고 upgrade() 실행."""
    captured: list[str] = []

    def _capture(sql: str) -> None:
        captured.append(sql)

    with patch.object(migration_module.op, "execute", side_effect=_capture):
        migration_module.upgrade()
    return captured


# ---------------------------------------------------------------------------
# 1) revision chain
# ---------------------------------------------------------------------------

def test_migration_revision_chain(migration_module) -> None:
    assert migration_module.revision == "081"
    assert migration_module.down_revision == "080"
    assert migration_module.branch_labels is None


# ---------------------------------------------------------------------------
# 2) role 분리 — lucas_kms_app + lucas_kms_migrate 생성 SQL
# ---------------------------------------------------------------------------

def test_creates_lucas_kms_app_role(captured_sql) -> None:
    """lucas_kms_app role CREATE 문 — NOSUPERUSER NOBYPASSRLS 명시."""
    sql_joined = "\n".join(captured_sql)
    assert "lucas_kms_app" in sql_joined
    assert "rolname = 'lucas_kms_app'" in sql_joined
    # NOSUPERUSER NOBYPASSRLS 명시 — spec §8.1 핵심 요구.
    assert "NOSUPERUSER NOBYPASSRLS" in sql_joined


def test_creates_lucas_kms_migrate_role(captured_sql) -> None:
    """lucas_kms_migrate role — DDL/owner. NOSUPERUSER NOBYPASSRLS + CREATEDB."""
    sql_joined = "\n".join(captured_sql)
    assert "lucas_kms_migrate" in sql_joined
    assert "rolname = 'lucas_kms_migrate'" in sql_joined
    # migrate role 은 schema CREATE 권한 필요 (DDL 용도).
    assert "CREATE ON SCHEMA public TO lucas_kms_migrate" in sql_joined


def test_lucas_kms_app_grants_crud_only(captured_sql) -> None:
    """lucas_kms_app 은 SELECT/INSERT/UPDATE/DELETE 만. DDL/ALL 권한 부재."""
    sql_joined = "\n".join(captured_sql)
    assert (
        "SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lucas_kms_app"
        in sql_joined
    )
    # lucas_kms_app 은 'ALL PRIVILEGES' 토큰을 직접 부여 받지 않음 — regex 로 정밀 검사.
    # "ALL PRIVILEGES ... TO lucas_kms_app" 패턴 부재 보장.
    assert not re.search(
        r"ALL PRIVILEGES\s+ON[^;]+TO\s+lucas_kms_app\b", sql_joined
    ), "lucas_kms_app must not receive ALL PRIVILEGES"
    # CREATE ON SCHEMA 도 부재 (DDL 권한 없음).
    assert not re.search(
        r"CREATE\s+ON\s+SCHEMA[^;]+TO\s+lucas_kms_app\b", sql_joined
    ), "lucas_kms_app must not have schema CREATE permission"


def test_role_password_env_indirection(monkeypatch, migration_module) -> None:
    """비밀번호 하드코딩 X — env 변수 LUCAS_KMS_APP_PASSWORD 사용."""
    monkeypatch.setenv("LUCAS_KMS_APP_PASSWORD", "test_secret_12345")
    captured: list[str] = []
    with patch.object(migration_module.op, "execute", side_effect=lambda s: captured.append(s)):
        migration_module.upgrade()
    sql_joined = "\n".join(captured)
    assert "test_secret_12345" in sql_joined
    # default 와 다른지 확인
    assert "lucas_kms_app_dev_password" not in sql_joined


# ---------------------------------------------------------------------------
# 3) FORCE RLS — 7 KMS table 적용 정합성
# ---------------------------------------------------------------------------

EXPECTED_FORCE_TABLES = (
    "repositories",
    "chunks",
    "search_logs",
    "intent_logs",
    "sections",
    "blocks",
    "categories",
)


@pytest.mark.parametrize("table", EXPECTED_FORCE_TABLES)
def test_force_rls_applied_to_kms_table(captured_sql, table) -> None:
    """KMS tenant-scoped 7 table 에 ENABLE + FORCE RLS 모두 적용."""
    sql_joined = "\n".join(captured_sql)
    assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql_joined
    assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql_joined


@pytest.mark.parametrize("table", ("repositories", "chunks", "search_logs", "intent_logs"))
def test_direct_tenant_policy_uses_current_setting(captured_sql, table) -> None:
    """직접 tenant_id table 의 정책은 ``current_setting('app.current_tenant_id')`` 매칭."""
    sql_joined = "\n".join(captured_sql)
    assert f"CREATE POLICY p_{table}_admin_select" in sql_joined
    assert f"CREATE POLICY p_{table}_agent_select" in sql_joined
    assert f"CREATE POLICY p_{table}_superadmin_select" in sql_joined
    # write path 분리 (INSERT/UPDATE/DELETE 분리 정책 — spec §8.1 write path 회귀)
    assert f"CREATE POLICY p_{table}_write_insert" in sql_joined
    assert f"CREATE POLICY p_{table}_write_update" in sql_joined
    assert f"CREATE POLICY p_{table}_write_delete" in sql_joined
    # GUC 키
    assert "current_setting('app.current_tenant_id', true)" in sql_joined


@pytest.mark.parametrize(
    "table,parent,fk_col",
    [
        ("sections", "documents", "document_id"),
        ("blocks", "documents", "document_id"),
        ("categories", "repositories", "repository_id"),
    ],
)
def test_join_tenant_policy_uses_parent_table(captured_sql, table, parent, fk_col) -> None:
    """JOIN 정책 — parent 테이블 tenant_id 매칭 (EXISTS subquery)."""
    sql_joined = "\n".join(captured_sql)
    assert f"CREATE POLICY p_{table}_join_select" in sql_joined
    assert f"CREATE POLICY p_{table}_join_insert" in sql_joined
    assert f"CREATE POLICY p_{table}_join_update" in sql_joined
    assert f"CREATE POLICY p_{table}_join_delete" in sql_joined
    # EXISTS subquery 구조 검증
    assert f"FROM {parent} p" in sql_joined
    assert f"p.id = {table}.{fk_col}" in sql_joined
    assert "p.tenant_id =" in sql_joined


# ---------------------------------------------------------------------------
# 4) superadmin 정책 — current_user 화이트리스트 (DB-level 격상)
# ---------------------------------------------------------------------------

def test_superadmin_select_requires_current_user_whitelist(captured_sql) -> None:
    """superadmin SELECT — current_user IN ('kms_superadmin', 'lucas_kms_migrate') 화이트리스트."""
    sql_joined = "\n".join(captured_sql)
    # GUC 단독 의존 회피 (078 BLOCKER 패치 패턴 동일)
    assert "current_user IN ('kms_superadmin', 'lucas_kms_migrate')" in sql_joined


# ---------------------------------------------------------------------------
# 5) downgrade — rollback 가능성
# ---------------------------------------------------------------------------

def test_downgrade_drops_policies_and_no_force(migration_module) -> None:
    captured: list[str] = []
    with patch.object(migration_module.op, "execute", side_effect=lambda s: captured.append(s)):
        migration_module.downgrade()
    sql_joined = "\n".join(captured)
    # 모든 신규 정책 drop
    for table in EXPECTED_FORCE_TABLES:
        # 직접 tenant + JOIN 모두 superadmin_select 정책 가짐.
        assert f"ON {table}" in sql_joined or f"on {table}" in sql_joined
        assert f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY" in sql_joined


# ---------------------------------------------------------------------------
# 6) SQL 안전성 — DO block 사용 + DROP TABLE 같은 위험 키워드 부재
# ---------------------------------------------------------------------------

def test_no_drop_table_in_upgrade(captured_sql) -> None:
    """본 migration 은 DROP TABLE 절대 금지 (schema 추가만)."""
    sql_joined = "\n".join(captured_sql).upper()
    assert "DROP TABLE" not in sql_joined


def test_graceful_no_op_via_do_block(captured_sql) -> None:
    """CREATE ROLE 은 DO block + EXCEPTION WHEN insufficient_privilege 로 감싸짐."""
    sql_joined = "\n".join(captured_sql)
    assert "DO $$" in sql_joined
    assert "WHEN insufficient_privilege THEN" in sql_joined


# ---------------------------------------------------------------------------
# 7) session helper — RLS_STRICT_TENANT_REQUIRED 강제 동작
# ---------------------------------------------------------------------------

def test_strict_mode_raises_on_empty_tenant(monkeypatch) -> None:
    """RLS_STRICT_TENANT_REQUIRED=true + tenant_val 빈 → RuntimeError 전파."""
    from unittest.mock import MagicMock

    from src.api.middleware.rls_context import (
        RLSContext,
        reset_rls_context,
        set_rls_context,
    )
    from src.common import config as config_mod
    from src.core import database as db_mod

    monkeypatch.setattr(config_mod.settings, "RLS_ENFORCE", True, raising=False)
    monkeypatch.setattr(
        config_mod.settings, "RLS_STRICT_TENANT_REQUIRED", True, raising=False
    )

    ctx = RLSContext(agent_id=None, scope="agent", tenant_id=None)
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        with pytest.raises(db_mod.RLSStrictTenantError, match="rls_strict_tenant_required"):
            db_mod._rls_set_session_vars(mock_conn)
    finally:
        reset_rls_context(token)


def test_strict_mode_allows_superadmin_without_tenant(monkeypatch) -> None:
    """superadmin scope 는 tenant_id 빈 값 허용 (cross-tenant 운영)."""
    from unittest.mock import MagicMock

    from src.api.middleware.rls_context import (
        RLSContext,
        reset_rls_context,
        set_rls_context,
    )
    from src.common import config as config_mod
    from src.core import database as db_mod

    monkeypatch.setattr(config_mod.settings, "RLS_ENFORCE", True, raising=False)
    monkeypatch.setattr(
        config_mod.settings, "RLS_STRICT_TENANT_REQUIRED", True, raising=False
    )

    ctx = RLSContext(agent_id=None, scope="superadmin", tenant_id=None)
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        # RuntimeError raise 되지 않음 — set_config 호출만.
        db_mod._rls_set_session_vars(mock_conn)
        assert mock_conn.execute.call_count == 3
    finally:
        reset_rls_context(token)


def test_strict_mode_disabled_by_default_no_raise(monkeypatch) -> None:
    """default (False) — tenant 빈 값에서 swallowed silent (회귀 0)."""
    from unittest.mock import MagicMock

    from src.api.middleware.rls_context import (
        RLSContext,
        reset_rls_context,
        set_rls_context,
    )
    from src.common import config as config_mod
    from src.core import database as db_mod

    monkeypatch.setattr(config_mod.settings, "RLS_ENFORCE", True, raising=False)
    monkeypatch.setattr(
        config_mod.settings, "RLS_STRICT_TENANT_REQUIRED", False, raising=False
    )

    ctx = RLSContext(agent_id=None, scope="agent", tenant_id=None)
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        # raise 0 — set_config 3회 그대로 발행 (tenant_id='' 로).
        db_mod._rls_set_session_vars(mock_conn)
        assert mock_conn.execute.call_count == 3
    finally:
        reset_rls_context(token)
