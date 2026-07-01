"""behavioral 회귀 — chunks RLS cross-tenant 격리 (2026-05-21).

GPT-5.5 adversarial review (GO_WITH_CHANGES) 요구: chunks 를 DIRECT→JOIN 으로
재분류한 뒤 *실제 Postgres RLS 가 cross-tenant write 를 차단* 하는지 behavioral
검증. 정적 분류 테스트(test_default_tenant_seed_consistency)는 분류 invariant 만
검증하므로, 본 테스트가 런타임 enforcement 를 보강한다.

전제:
- 환경변수 ``LUCAS_RLS_TEST_DATABASE_URL`` (superuser, throwaway DB) 가 있어야 실행.
  없으면 skip (repo 의 requires_db 패턴 — fresh CI 에서는 DB provisioning 후 활성).
- 본 테스트는 scripts/init_db.py 를 subprocess 로 실행해 schema+RLS 를 만든 뒤,
  NOBYPASSRLS 역할로 cross-tenant chunk INSERT 가 차단되는지 확인한다.
  (운영 역할 kms_app 은 BYPASSRLS 라 RLS 우회 — 별도 이슈. 본 테스트는 정책
  자체의 enforcement 를 NOBYPASSRLS 역할로 검증.)
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_db

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DB_URL = os.environ.get("LUCAS_RLS_TEST_DATABASE_URL")

TENANT_A = "00000000-0000-0000-0000-000000000001"
TENANT_B = "00000000-0000-0000-0000-000000000002"
REPO_A = "aaaaaaaa-0000-0000-0000-00000000000a"
REPO_B = "bbbbbbbb-0000-0000-0000-00000000000b"
DOC_A = "dddddddd-0000-0000-0000-00000000000a"
DOC_B = "dddddddd-0000-0000-0000-00000000000b"


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


# rls_probe 역할 idempotent 제거 — 테이블 GRANT 의존성(DependentObjectsStillExist)
# 때문에 DROP ROLE 전에 DROP OWNED BY 필요. 역할 부재 시 no-op.
_DROP_PROBE_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_probe') THEN
    EXECUTE 'DROP OWNED BY rls_probe';
    EXECUTE 'DROP ROLE rls_probe';
  END IF;
END $$;
"""


async def _run_probe(url: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(_asyncpg_url(url))
    try:
        await conn.execute(
            """
            INSERT INTO tenants (id,name,slug,config,plan,tenant_type,context_config,feature_flags)
            VALUES ($1,'T-B','t-b','{}','standard','system','{}','{}') ON CONFLICT (id) DO NOTHING;
            """,
            TENANT_B,
        )
        await conn.execute(
            "INSERT INTO repositories (id,tenant_id,name) VALUES ($1,$2,'repoA'),($3,$4,'repoB') "
            "ON CONFLICT (id) DO NOTHING;",
            REPO_A, TENANT_A, REPO_B, TENANT_B,
        )
        await conn.execute(
            "INSERT INTO documents (id,tenant_id,repository_id,title) VALUES ($1,$2,$3,'docA'),($4,$5,$6,'docB') "
            "ON CONFLICT (id) DO NOTHING;",
            DOC_A, TENANT_A, REPO_A, DOC_B, TENANT_B, REPO_B,
        )
        await conn.execute(_DROP_PROBE_ROLE)
        await conn.execute("CREATE ROLE rls_probe NOLOGIN NOBYPASSRLS;")
        await conn.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO rls_probe;")

        await conn.execute("SET ROLE rls_probe;")
        await conn.execute("SET app.current_scope = 'admin';")
        await conn.execute(f"SET app.current_tenant_id = '{TENANT_A}';")

        # POSITIVE: 같은 tenant(repoA) → 성공
        await conn.execute(
            "INSERT INTO chunks (id,document_id,repository_id,content,chunk_index,chunk_hash) "
            "VALUES (gen_random_uuid(),$1,$2,'same',0,'h0');",
            DOC_A, REPO_A,
        )

        # NEGATIVE: 다른 tenant(repoB) → RLS 차단
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute(
                "INSERT INTO chunks (id,document_id,repository_id,content,chunk_index,chunk_hash) "
                "VALUES (gen_random_uuid(),$1,$2,'cross',0,'h1');",
                DOC_B, REPO_B,
            )
    finally:
        await conn.execute("RESET ROLE;")
        await conn.execute(_DROP_PROBE_ROLE)
        await conn.close()


@pytest.mark.skipif(not TEST_DB_URL, reason="LUCAS_RLS_TEST_DATABASE_URL 미설정 — DB 필요")
def test_chunks_cross_tenant_insert_blocked() -> None:
    """chunks 는 repository_id(JOIN) 로 tenant 격리 — cross-tenant INSERT 차단."""
    # init_db.py 로 schema + RLS 적용 (실 배포 경로 그대로).
    env = dict(os.environ, DATABASE_URL=TEST_DB_URL, PYTHONPATH=str(REPO_ROOT))
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "init_db.py")],
        env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"init_db 실패:\n{result.stderr[-2000:]}"

    asyncio.run(_run_probe(TEST_DB_URL))
