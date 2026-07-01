"""Phase 2 T2.4 — FORCE RLS + lucas_kms_app / lucas_kms_migrate role 분리.

Revision ID: 081
Revises: 080
Create Date: 2026-05-19

목적 (spec §8.1 rev3):
- 077 가 적용한 4 table (documents, library_folders, audit_logs, agent_documents)
  외 *KMS tenant-scoped* 잔여 table 에 FORCE ROW LEVEL SECURITY 강제.
- 077 에서 누락된 7 KMS table 보강:
  - 직접 tenant_id 보유: ``repositories``, ``search_logs``, ``intent_logs``
  - parent join 정책: ``sections`` (via document), ``blocks`` (via document),
    ``chunks`` (via repository), ``categories`` (via repository)
- role 분리: ``lucas_kms_app`` (NOSUPERUSER NOBYPASSRLS, 비-owner)
  + ``lucas_kms_migrate`` (DDL/owner 역할).
  - 078 의 ``kms_app`` 는 backward-compat 유지. 신규 이름은 *추가*.

설계 원칙 (077/078 와 동일):
- 비밀번호 env 변수 (``LUCAS_KMS_APP_PASSWORD``, ``LUCAS_KMS_MIGRATE_PASSWORD``).
  하드코딩 X — 운영은 별도 SQL bootstrap 권장.
- ``DO`` 블록 graceful no-op (CREATEROLE 권한 부재 환경 호환).
- 신규 정책은 077 와 동일 GUC ``app.current_scope`` / ``app.current_tenant_id`` /
  ``app.current_agent_id`` 사용. session helper (src/core/database.py) 기존 작동.

**실 DB 미적용** — 본 PR 은 migration *파일 작성* 만. staging 검증 후 적용.

회귀 0:
- 077/078 정책 미변경. FORCE 추가는 *새 table* 만.
- `repositories` 는 001 에서 ENABLE 만 적용된 상태 → FORCE 추가 + 정책 신규.
  (정책 부재 + ENABLE → default-deny 였으므로 KMS_DB_ROLE=migration BYPASSRLS 운영
  시 회귀 0. NOBYPASSRLS 전환 시 신규 정책 작동 필요.)

적용 절차:
1. alembic upgrade head (staging)
2. SELECT 0 / cross-tenant write 차단 회귀 검증
3. docker-compose KMS_DB_ROLE 를 `lucas_kms_app` 으로 전환
"""

from __future__ import annotations

import os
from typing import Sequence, Union

from alembic import op


revision: str = "081"
down_revision: Union[str, None] = "080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# KMS tenant-scoped table 분류 (spec line 280 + 실 model 확인)
# ---------------------------------------------------------------------------

# 직접 tenant_id 컬럼 보유 — RLS 정책에서 곧바로 매칭 가능.
DIRECT_TENANT_TABLES = (
    "repositories",
    "search_logs",
    "intent_logs",
)

# parent table 의 tenant_id 를 JOIN 으로 통과시키는 table.
# 직접 컬럼 부재 — EXISTS subquery 정책.
JOIN_TENANT_TABLES = {
    "sections": "documents",     # sections.document_id → documents.tenant_id
    "blocks": "documents",       # blocks.document_id → documents.tenant_id
    "chunks": "repositories",    # chunks.repository_id → repositories.tenant_id (직접 tenant_id 없음)
    "categories": "repositories",  # categories.repository_id → repositories.tenant_id
}

# JOIN 정책의 FK 컬럼명.
JOIN_FK_COLUMNS = {
    "sections": "document_id",
    "blocks": "document_id",
    "chunks": "repository_id",
    "categories": "repository_id",
}

# 077 가 이미 처리한 table — 본 migration 에서 *건드리지 않음*.
ALREADY_DONE_BY_077 = ("documents", "library_folders", "audit_logs", "agent_documents")


# ---------------------------------------------------------------------------
# Role 분리 — spec §8.1 rev3
# ---------------------------------------------------------------------------

def _password(env_key: str, default: str) -> str:
    return os.environ.get(env_key, default)


def _sql_string_literal(value: str) -> str:
    """SQL literal escape — 작은따옴표 doubled, 결과는 ``'...'`` 형태."""
    safe = value.replace("'", "''")
    return f"'{safe}'"


def _tenant_match() -> str:
    """current_setting('app.current_tenant_id') ::uuid 매칭 (R2 캐스팅 방향)."""
    return (
        "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    )


# ---------------------------------------------------------------------------
# Migration body
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # =====================================================================
    # 1) lucas_kms_app role — NOSUPERUSER NOBYPASSRLS, 비-owner (spec §8.1)
    #    이미 존재 시 skip. CREATEROLE 권한 부재 시 graceful no-op.
    # =====================================================================
    app_pwd_raw = _password("LUCAS_KMS_APP_PASSWORD", "lucas_kms_app_dev_password")
    app_pwd_lit = _sql_string_literal(app_pwd_raw)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lucas_kms_app') THEN
                EXECUTE format(
                    'CREATE ROLE lucas_kms_app LOGIN PASSWORD %L '
                    'NOSUPERUSER NOBYPASSRLS NOREPLICATION NOCREATEDB NOCREATEROLE',
                    {app_pwd_lit}
                );
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'lucas_kms_app role 생성 권한 부재 — DBA bootstrap 필요. (graceful no-op)';
        END $$;
        """
    )

    # =====================================================================
    # 2) lucas_kms_migrate role — DDL/owner. NOBYPASSRLS NOSUPERUSER + CREATE 권한.
    #    spec §8.1: app role 비-owner 분리 → DDL 은 별도 role.
    # =====================================================================
    migrate_pwd_raw = _password("LUCAS_KMS_MIGRATE_PASSWORD", "lucas_kms_migrate_dev_password")
    migrate_pwd_lit = _sql_string_literal(migrate_pwd_raw)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lucas_kms_migrate') THEN
                EXECUTE format(
                    'CREATE ROLE lucas_kms_migrate LOGIN PASSWORD %L '
                    'NOSUPERUSER NOBYPASSRLS NOREPLICATION CREATEDB NOCREATEROLE',
                    {migrate_pwd_lit}
                );
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'lucas_kms_migrate role 생성 권한 부재 — DBA bootstrap 필요. (graceful no-op)';
        END $$;
        """
    )

    # =====================================================================
    # 3) GRANT scope:
    #    - lucas_kms_app: CRUD only (DDL 권한 없음)
    #    - lucas_kms_migrate: ALL (DDL 포함)
    # =====================================================================
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lucas_kms_app') THEN
                EXECUTE format('GRANT CONNECT ON DATABASE %I TO lucas_kms_app', current_database());
                GRANT USAGE ON SCHEMA public TO lucas_kms_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lucas_kms_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO lucas_kms_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lucas_kms_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT USAGE, SELECT ON SEQUENCES TO lucas_kms_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lucas_kms_migrate') THEN
                EXECUTE format('GRANT CONNECT ON DATABASE %I TO lucas_kms_migrate', current_database());
                GRANT USAGE, CREATE ON SCHEMA public TO lucas_kms_migrate;
                GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO lucas_kms_migrate;
                GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO lucas_kms_migrate;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT ALL PRIVILEGES ON TABLES TO lucas_kms_migrate;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT ALL PRIVILEGES ON SEQUENCES TO lucas_kms_migrate;
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'lucas_kms_* GRANT 권한 부재 — DBA bootstrap 필요. (graceful no-op)';
        END $$;
        """
    )

    # =====================================================================
    # 4) FORCE RLS + 정책 — 직접 tenant_id 보유 4 table
    #    (repositories, chunks, search_logs, intent_logs)
    # =====================================================================
    for table in DIRECT_TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

        # admin/superadmin/agent SELECT — tenant 안 모든 row.
        op.execute(
            f"""
            CREATE POLICY p_{table}_admin_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'admin'
                AND {_tenant_match()}
              );
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_superadmin_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'superadmin'
                AND current_user IN ('kms_superadmin', 'lucas_kms_migrate')
              );
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_agent_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'agent'
                AND {_tenant_match()}
              );
            """
        )

        # INSERT / UPDATE / DELETE — admin or agent in tenant.
        using_clause = (
            f"(current_setting('app.current_scope', true) IN ('admin', 'agent') "
            f"AND {_tenant_match()}) "
            f"OR ("
            f"  current_setting('app.current_scope', true) = 'superadmin' "
            f"  AND current_user IN ('kms_superadmin', 'lucas_kms_migrate')"
            f")"
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_write_insert ON {table}
              AS PERMISSIVE FOR INSERT
              WITH CHECK ({using_clause});
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_write_update ON {table}
              AS PERMISSIVE FOR UPDATE
              USING ({using_clause})
              WITH CHECK ({using_clause});
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_write_delete ON {table}
              AS PERMISSIVE FOR DELETE
              USING ({using_clause});
            """
        )

    # =====================================================================
    # 5) FORCE RLS + JOIN 정책 — parent 의 tenant_id 통과 (3 table)
    #    sections / blocks → documents.tenant_id
    #    categories → repositories.tenant_id
    # =====================================================================
    for table, parent in JOIN_TENANT_TABLES.items():
        fk_col = JOIN_FK_COLUMNS[table]
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

        # JOIN 정책 — parent table 의 tenant_id 가 현 GUC 와 매칭되는지 EXISTS.
        join_subq = (
            f"EXISTS ("
            f"  SELECT 1 FROM {parent} p "
            f"  WHERE p.id = {table}.{fk_col} "
            f"  AND p.tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
            f")"
        )

        op.execute(
            f"""
            CREATE POLICY p_{table}_join_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) IN ('admin', 'agent')
                AND {join_subq}
              );
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_superadmin_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'superadmin'
                AND current_user IN ('kms_superadmin', 'lucas_kms_migrate')
              );
            """
        )

        join_using = (
            f"(current_setting('app.current_scope', true) IN ('admin', 'agent') "
            f"AND {join_subq}) "
            f"OR ("
            f"  current_setting('app.current_scope', true) = 'superadmin' "
            f"  AND current_user IN ('kms_superadmin', 'lucas_kms_migrate')"
            f")"
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_join_insert ON {table}
              AS PERMISSIVE FOR INSERT
              WITH CHECK ({join_using});
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_join_update ON {table}
              AS PERMISSIVE FOR UPDATE
              USING ({join_using})
              WITH CHECK ({join_using});
            """
        )
        op.execute(
            f"""
            CREATE POLICY p_{table}_join_delete ON {table}
              AS PERMISSIVE FOR DELETE
              USING ({join_using});
            """
        )


def downgrade() -> None:
    # =====================================================================
    # Reverse — 정책 삭제 + FORCE 해제. role 은 *유지* (다른 alembic head 의존 가능).
    # =====================================================================
    for table in DIRECT_TENANT_TABLES:
        for policy in (
            f"p_{table}_admin_select",
            f"p_{table}_superadmin_select",
            f"p_{table}_agent_select",
            f"p_{table}_write_insert",
            f"p_{table}_write_update",
            f"p_{table}_write_delete",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        # ENABLE 는 유지 (001 시점부터 ENABLE 인 table 들 회귀 방지).

    for table in JOIN_TENANT_TABLES:
        for policy in (
            f"p_{table}_join_select",
            f"p_{table}_superadmin_select",
            f"p_{table}_join_insert",
            f"p_{table}_join_update",
            f"p_{table}_join_delete",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # role / GRANT 는 유지. 명시 SQL bootstrap 으로 정리.
