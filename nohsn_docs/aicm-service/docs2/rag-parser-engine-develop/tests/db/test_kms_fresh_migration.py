"""Phase 2 T2.3 — KMS fresh DB migration isolation 검증.

목적 (spec §7):
- fresh postgres 에 ``alembic -c alembic.kms.ini upgrade kms@head`` 적용 후
  *KMS 10 table + shared 12 table + document_categories assoc = 23 table* 만
  존재하고 **agent 8 table 은 존재하지 않음** 을 검증.
- 회귀: ``alembic -c alembic.ini upgrade head`` (full) 도 모든 table 생성.

실행 (DB 가 필요):
    docker compose -f docker-compose.test-kms-migration.yml up -d postgres-test-kms
    DATABASE_URL=postgresql+asyncpg://kms_test:kms_test_pw@localhost:54320/kms_test_db \\
        pytest -m requires_db tests/db/test_kms_fresh_migration.py -v

DB 미존재 환경에서는 fixture 가 자동 skip.

기본 절칙:
- 하드코딩 X — table list 는 ``tools/alembic_audit/model_branches.json`` 에서 로드.
- 실 DB 미적용 — 본 PR 은 *테스트 작성* 만. 사용자 staging 검증 후 적용.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_db


ROOT = Path(__file__).resolve().parents[2]
MODEL_BRANCHES_JSON = ROOT / "tools/alembic_audit/model_branches.json"


# ---------------------------------------------------------------------------
# Expected table sets — model_branches.json 동적 로드 (하드코딩 X).
# ---------------------------------------------------------------------------


def _load_branch_tables() -> dict[str, set[str]]:
    data = json.loads(MODEL_BRANCHES_JSON.read_text(encoding="utf-8"))
    by_branch = data["by_branch"]
    return {
        b: {row["table"] for row in by_branch[b]}
        for b in ("kms", "agent", "shared")
    }


EXPECTED = _load_branch_tables()
KMS_TABLES = EXPECTED["kms"] | {"document_categories"}  # assoc
AGENT_TABLES = EXPECTED["agent"]
SHARED_TABLES = EXPECTED["shared"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sync_db_url() -> str | None:
    """DATABASE_URL 을 psycopg2 driver 로 변환 (test_rls_write_path.py 와 동일)."""
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
        pytest.skip("DATABASE_URL not set — fresh DB test skipped")
    if shutil.which("alembic") is None and not (ROOT / ".venv/bin/alembic").exists():
        pytest.skip("alembic CLI not found in PATH")
    try:
        from sqlalchemy import create_engine
    except ImportError:
        pytest.skip("sqlalchemy not available")
    eng = create_engine(url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def fresh_db(engine):
    """alembic upgrade 전 schema 가 비어 있는지 보장 (drop + recreate public)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))
    yield engine


def _run_alembic(ini: str, target: str = "head") -> subprocess.CompletedProcess:
    """alembic upgrade 실행. DATABASE_URL 은 caller env 에서 inherit."""
    cmd = ["alembic", "-c", ini, "upgrade", target]
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        env={**os.environ, "DATABASE_URL_MIGRATION": os.environ.get("DATABASE_URL", "")},
    )


def _public_tables(conn) -> set[str]:
    """현재 public schema 의 table 명 set."""
    from sqlalchemy import text

    result = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    )
    return {row[0] for row in result}


# ---------------------------------------------------------------------------
# Tests — KMS branch isolation
# ---------------------------------------------------------------------------


def test_kms_fresh_db_upgrade_produces_no_agent_tables(fresh_db):
    """``alembic -c alembic.kms.ini upgrade kms@head`` 후 agent table 0개."""
    proc = _run_alembic("alembic.kms.ini", "kms@head")
    assert proc.returncode == 0, (
        f"alembic kms upgrade failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )

    with fresh_db.connect() as conn:
        tables = _public_tables(conn)

    # KMS table 모두 존재
    missing_kms = KMS_TABLES - tables
    assert not missing_kms, f"KMS table 누락: {sorted(missing_kms)}"

    # Shared table 모두 존재
    missing_shared = SHARED_TABLES - tables
    assert not missing_shared, f"shared table 누락: {sorted(missing_shared)}"

    # Agent table 0 개
    leaked_agent = AGENT_TABLES & tables
    assert not leaked_agent, (
        f"agent table 이 KMS fresh DB 에 생성됨 — branch isolation 위반: "
        f"{sorted(leaked_agent)}"
    )


# ---------------------------------------------------------------------------
# Regression — full deployment (alembic.ini) 도 정상 동작
# ---------------------------------------------------------------------------


def test_full_alembic_upgrade_creates_all_tables(engine):
    """``alembic upgrade head`` (full) 후 KMS + Agent + Shared 모두 존재 (회귀)."""
    from sqlalchemy import text

    # 별도 schema 로 격리 (이전 fresh_db test 와 충돌 회피).
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))

    proc = _run_alembic("alembic.ini", "head")
    assert proc.returncode == 0, (
        f"full alembic upgrade failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )

    with engine.connect() as conn:
        tables = _public_tables(conn)

    # KMS + Agent + Shared 모두 존재
    for label, expected in [
        ("KMS", KMS_TABLES),
        ("Agent", AGENT_TABLES),
        ("Shared", SHARED_TABLES),
    ]:
        missing = expected - tables
        assert not missing, f"{label} table 누락 (full upgrade): {sorted(missing)}"


# ---------------------------------------------------------------------------
# Static — model_branches.json 정합성 (DB 없이도 통과)
# ---------------------------------------------------------------------------


def test_model_branches_json_is_self_consistent():
    """KMS / Agent / Shared 가 서로 disjoint."""
    kms = EXPECTED["kms"]
    agent = EXPECTED["agent"]
    shared = EXPECTED["shared"]

    assert not (kms & agent), f"KMS ∩ Agent: {kms & agent}"
    assert not (kms & shared), f"KMS ∩ Shared: {kms & shared}"
    assert not (agent & shared), f"Agent ∩ Shared: {agent & shared}"
