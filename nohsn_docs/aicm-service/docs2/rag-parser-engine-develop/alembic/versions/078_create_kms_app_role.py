"""D32 §1 — kms_app application role + GRANT (NOBYPASSRLS, NOSUPERUSER).

Revision ID: 078
Revises: 077
Create Date: 2026-05-08

목적 (사용자 명시 2026-05-08 / D32 §1, GPT-5 phase 0 R1):
- D30 의 R1 결함 — api 컨테이너가 ``kms`` 슈퍼유저 (BYPASSRLS) 로 connect 중 →
  RLS 정책 *런타임 무력화*. 본 PR 이 NOBYPASSRLS NOSUPERUSER role 도입.
- 동시에 superadmin SELECT 정책에 DB-level 화이트리스트 (``current_user='kms_superadmin'``)
  추가 — 077 의 GUC 단독 의존 위험 해소 (GPT-5 BLOCKER 패치).

설계 (GPT-5 phase 0 R1 GO_WITH_CHANGES):
- ``DO`` 블록으로 graceful no-op — CREATEROLE 권한 부재 환경 (managed Postgres 등) 회피.
- IDENTIFIED BY env 의 password (``KMS_APP_PASSWORD`` / ``KMS_SUPERADMIN_PASSWORD``)
  — 본 PR 은 dev default password (.env 변경 시 alembic 재실행 X). 운영은 별도 SQL bootstrap 권장.
- GRANT scope: SELECT/INSERT/UPDATE/DELETE on ALL TABLES + USAGE,SELECT on ALL SEQUENCES.
- ALTER DEFAULT PRIVILEGES — 신규 테이블/시퀀스 자동 GRANT.

회귀 0 보장:
- 본 PR 이 docker-compose / config 변경 없음 — DB 접속 user 변경 X. 077 정책 강화만.
- 077 superadmin SELECT 정책은 *교체* — 077 downgrade 시 077 원본 정책으로 복원 (077 코드 = ground truth).
"""

from __future__ import annotations

import os
from typing import Sequence, Union

from alembic import op


revision: str = "078"
down_revision: Union[str, None] = "077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# RLS 적용 4 테이블 — 077 와 동기.
RLS_TABLES = ("documents", "library_folders", "audit_logs", "agent_documents")


def _password(env_key: str, default: str) -> str:
    return os.environ.get(env_key, default)


def _sql_string_literal(value: str) -> str:
    """SQL literal escape — 작은따옴표 doubled, 결과는 ``'...'`` 형태.

    asyncpg 가 DO 블록에 bind param 을 지원하지 않으므로 Python-side 에서
    안전한 SQL 문자열 리터럴 생성. 비밀번호 등 특수문자 (', \\) 포함 가능.
    """
    safe = value.replace("'", "''")
    return f"'{safe}'"


def upgrade() -> None:
    # ===========================================================
    # 1) kms_app application role — NOBYPASSRLS NOSUPERUSER LOGIN
    #    GPT-5 §1 patch (간소): asyncpg 가 DO 블록에 bind param 미지원 →
    #    Python-side 안전 escape (작은따옴표 → ''). %L 스타일 SQL literal.
    # ===========================================================
    kms_app_pwd_raw = _password("KMS_APP_PASSWORD", "kms_app_dev_password")
    kms_app_pwd_lit = _sql_string_literal(kms_app_pwd_raw)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kms_app') THEN
                EXECUTE format(
                    'CREATE ROLE kms_app LOGIN PASSWORD %L '
                    'NOSUPERUSER NOBYPASSRLS NOREPLICATION NOCREATEDB NOCREATEROLE',
                    {kms_app_pwd_lit}
                );
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'kms_app role 생성 권한 부재 — DBA bootstrap 필요. (graceful no-op)';
        END $$;
        """
    )

    # ===========================================================
    # 2) GRANT scope — CONNECT + schema USAGE + table CRUD + sequence USAGE,SELECT
    #    + ALTER DEFAULT PRIVILEGES (신규 테이블 자동 grant)
    #    GPT-5 §1 patch: GRANT CONNECT 추가 (PUBLIC CONNECT 철회 환경 호환).
    # ===========================================================
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kms_app') THEN
                EXECUTE format('GRANT CONNECT ON DATABASE %I TO kms_app', current_database());
                GRANT USAGE ON SCHEMA public TO kms_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kms_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kms_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kms_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT USAGE, SELECT ON SEQUENCES TO kms_app;
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'kms_app GRANT 권한 부재 — DBA bootstrap 필요. (graceful no-op)';
        END $$;
        """
    )

    # ===========================================================
    # 3) kms_superadmin role — superadmin SELECT 정책 화이트리스트 용
    #    NOBYPASSRLS NOSUPERUSER LOGIN — 정책의 current_user 매칭만 통과.
    #    GPT-5 §1 patch: 비밀번호 안전 주입 + CONNECT 권한.
    # ===========================================================
    kms_super_pwd_raw = _password("KMS_SUPERADMIN_PASSWORD", "kms_superadmin_dev_password")
    kms_super_pwd_lit = _sql_string_literal(kms_super_pwd_raw)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kms_superadmin') THEN
                EXECUTE format(
                    'CREATE ROLE kms_superadmin LOGIN PASSWORD %L '
                    'NOSUPERUSER NOBYPASSRLS NOREPLICATION NOCREATEDB NOCREATEROLE',
                    {kms_super_pwd_lit}
                );
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kms_superadmin') THEN
                EXECUTE format('GRANT CONNECT ON DATABASE %I TO kms_superadmin', current_database());
                GRANT USAGE ON SCHEMA public TO kms_superadmin;
                GRANT SELECT ON ALL TABLES IN SCHEMA public TO kms_superadmin;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT SELECT ON TABLES TO kms_superadmin;
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'kms_superadmin role 생성/grant 권한 부재 — DBA bootstrap 필요.';
        END $$;
        """
    )

    # ===========================================================
    # 4) superadmin SELECT 정책 — DB-level 화이트리스트 강화
    #    GPT-5 BLOCKER 패치 — current_user = 'kms_superadmin' 추가.
    #    077 원본: current_setting('app.current_scope', true) = 'superadmin' 단독.
    #    078 강화: + AND current_user = 'kms_superadmin'.
    #    효과: kms_app 이 임의로 SET LOCAL app.current_scope='superadmin' 시도해도
    #    current_user mismatch 로 정책 차단.
    # ===========================================================
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_{table}_superadmin_select ON {table};")
        op.execute(
            f"""
            CREATE POLICY p_{table}_superadmin_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'superadmin'
                AND current_user = 'kms_superadmin'
              );
            """
        )


def downgrade() -> None:
    # 077 원본 superadmin SELECT 정책 (current_user 화이트리스트 제거) 복원.
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_{table}_superadmin_select ON {table};")
        op.execute(
            f"""
            CREATE POLICY p_{table}_superadmin_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (current_setting('app.current_scope', true) = 'superadmin');
            """
        )

    # role / GRANT 는 downgrade 에서 *유지*. DB 외부 backup tooling 의 의존 가능성 +
    # alembic chain 에서 role 자체는 schema 와 독립 — 명시적 SQL bootstrap 으로 정리.
    # (위험: drop 시 다른 alembic head 의 GRANT 의존 깨짐)
