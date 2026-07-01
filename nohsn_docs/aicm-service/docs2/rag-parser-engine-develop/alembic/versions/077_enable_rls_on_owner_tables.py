"""Postgres RLS — DB-level 격리 (D25 §1-§4).

Revision ID: 077
Revises: 076
Create Date: 2026-05-08

목적 (사용자 명시 2026-05-08 / D25):
- D23 (#196) + D24 (#198) 의 application-only 격리를 *DB-level* 강제로 격상.
- application 이 raw SQL 을 owner 필터 없이 실행해도 DB 가 차단.

설계 (GPT-5 phase 0 R1 GO_WITH_CHANGES → R2 GO_WITH_CHANGES → R3 patch 반영):
- ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` + ``FORCE`` (table owner 도 적용).
- session 변수 (``app.current_agent_id`` / ``app.current_scope`` /
  ``app.current_tenant_id``) 기반 정책. application 이 transaction 시작 시
  ``SET LOCAL`` 으로 주입.
- bypass 는 *PostgreSQL role attribute* (BYPASSRLS) 로만 — GUC 토글 폐기.
  운영: kms_app (NOBYPASSRLS) / kms_migration (BYPASSRLS) 분리.

R2 patch:
- 캐스팅 방향: 좌변 (컬럼) 은 그대로, 우변 (current_setting) 만 ``::uuid`` —
  B-tree 인덱스 사용 가능.
- agent_documents write 정책 INSERT/UPDATE/DELETE 분리 (FOR ALL 제거).
- audit_logs INSERT 의 NULL owner 전역 가드 추가
  (``owner_agent_id IS NOT NULL OR owner_scope IN ('admin','system')``).
- tenant_id 컬럼 실존 확인 — audit_logs (alembic 011), agent_documents (alembic 070),
  documents (legacy), library_folders (alembic 067) 모두 NOT NULL tenant_id 보유.

대상 테이블:
- ``documents`` (alembic 072) — owner_agent_id NULLABLE FK
- ``library_folders`` (alembic 071) — owner_agent_id NULLABLE FK
- ``audit_logs`` (alembic 076) — owner_scope + owner_agent_id (append-only)
- ``agent_documents`` (alembic 070) — agent_id (owner_agent_id 부재)

회귀 0 보장:
- Phase 1: alembic 077 적용 + middleware 배포 + KMS_DB_ROLE=migration (BYPASSRLS) 임시 사용
- Phase 2: 검증 후 KMS_DB_ROLE=app (NOBYPASSRLS) 전환 — 실 격리 작동
- Phase 3: superadmin scope 분리, audit chain 운영 안정화

R3 follow-up (별도 PR):
- 테이블 OWNER 를 NOLOGIN 전용 소유자 (kms_owner) 로 변경 + kms_migration 멤버십.
- superadmin DB role (kms_superadmin BYPASSRLS) — current_user 화이트리스트.
- docker-compose / .env.sample 의 기본 접속 role = kms_app 분리.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "077"
down_revision: Union[str, None] = "076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# owner_agent_id 기반 RLS — agent 자료 격리 (D23 §1).
OWNER_TABLES = ("documents", "library_folders")
# audit_logs — append-only (UPDATE/DELETE 정책 부재).
AUDIT_TABLE = "audit_logs"
# agent_documents — agent_id 기반 (owner_agent_id 부재).
AGENT_DOCS_TABLE = "agent_documents"
# RLS ENABLE 대상 4 테이블.
ALL_TABLES = OWNER_TABLES + (AUDIT_TABLE, AGENT_DOCS_TABLE)


# === R2 patch: 캐스팅 방향 — 좌변 column, 우변 current_setting::uuid ===
# NULLIF — 빈 문자열 GUC ('') → NULL (RLS 정책상 NULL = 비매칭 → 거부).
def _agent_id_match() -> str:
    return (
        "owner_agent_id = NULLIF(current_setting('app.current_agent_id', true), '')::uuid"
    )


def _tenant_id_match() -> str:
    return (
        "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    )


def _agent_documents_id_match() -> str:
    """agent_documents.agent_id 컬럼 매칭 (owner_agent_id 부재)."""
    return (
        "agent_id = NULLIF(current_setting('app.current_agent_id', true), '')::uuid"
    )


def upgrade() -> None:
    # ===========================================================
    # 1) RLS ENABLE + FORCE on 4 tables
    # ===========================================================
    for table in ALL_TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')
        # FORCE — table owner 도 RLS 적용 (BYPASSRLS attribute 만 우회).
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;')

    # ===========================================================
    # 2) admin SELECT — 자기 tenant 안 모든 row (NULL owner 포함)
    # ===========================================================
    for table in OWNER_TABLES + (AUDIT_TABLE, AGENT_DOCS_TABLE):
        op.execute(f"""
            CREATE POLICY p_{table}_admin_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'admin'
                AND {_tenant_id_match()}
              );
        """)

    # ===========================================================
    # 3) superadmin SELECT — cross-tenant (Locus 운영자 only)
    #    NOTE: R2 — 향후 PR 에서 current_user IN ('kms_superadmin') 화이트리스트
    #    이중 체크로 격상 권고. 본 PR 은 GUC 단독 — application role
    #    NOBYPASSRLS 가 임의 SET LOCAL 을 차단해주는 가정 (kms_app role).
    # ===========================================================
    for table in OWNER_TABLES + (AUDIT_TABLE, AGENT_DOCS_TABLE):
        op.execute(f"""
            CREATE POLICY p_{table}_superadmin_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (current_setting('app.current_scope', true) = 'superadmin');
        """)

    # ===========================================================
    # 4) agent SELECT — owner_agent_id (또는 agent_id) 매칭 + tenant 경계
    # ===========================================================
    for table in OWNER_TABLES + (AUDIT_TABLE,):
        op.execute(f"""
            CREATE POLICY p_{table}_agent_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'agent'
                AND owner_agent_id IS NOT NULL
                AND {_agent_id_match()}
                AND {_tenant_id_match()}
              );
        """)
    # agent_documents 는 agent_id (owner_agent_id 컬럼 부재).
    op.execute(f"""
        CREATE POLICY p_agent_documents_agent_select ON agent_documents
          AS PERMISSIVE FOR SELECT
          USING (
            current_setting('app.current_scope', true) = 'agent'
            AND {_agent_documents_id_match()}
            AND {_tenant_id_match()}
          );
    """)

    # ===========================================================
    # 5) documents / library_folders 의 INSERT/UPDATE/DELETE 분리
    # ===========================================================
    using_owner_agent = f"""
        (current_setting('app.current_scope', true) = 'admin'
         AND {_tenant_id_match()})
        OR current_setting('app.current_scope', true) = 'superadmin'
        OR (
          current_setting('app.current_scope', true) = 'agent'
          AND {_agent_id_match()}
          AND {_tenant_id_match()}
        )
    """
    for table in OWNER_TABLES:
        op.execute(f"""
            CREATE POLICY p_{table}_agent_insert ON {table}
              AS PERMISSIVE FOR INSERT
              WITH CHECK ({using_owner_agent});
        """)
        op.execute(f"""
            CREATE POLICY p_{table}_agent_update ON {table}
              AS PERMISSIVE FOR UPDATE
              USING ({using_owner_agent})
              WITH CHECK ({using_owner_agent});
        """)
        op.execute(f"""
            CREATE POLICY p_{table}_agent_delete ON {table}
              AS PERMISSIVE FOR DELETE
              USING ({using_owner_agent});
        """)

    # ===========================================================
    # 6) agent_documents 의 INSERT/UPDATE/DELETE 분리 (R2 patch — FOR ALL 제거)
    # ===========================================================
    using_agent_docs = f"""
        (current_setting('app.current_scope', true) = 'admin'
         AND {_tenant_id_match()})
        OR current_setting('app.current_scope', true) = 'superadmin'
        OR (
          current_setting('app.current_scope', true) = 'agent'
          AND {_agent_documents_id_match()}
          AND {_tenant_id_match()}
        )
    """
    op.execute(f"""
        CREATE POLICY p_agent_documents_agent_insert ON agent_documents
          AS PERMISSIVE FOR INSERT
          WITH CHECK ({using_agent_docs});
    """)
    op.execute(f"""
        CREATE POLICY p_agent_documents_agent_update ON agent_documents
          AS PERMISSIVE FOR UPDATE
          USING ({using_agent_docs})
          WITH CHECK ({using_agent_docs});
    """)
    op.execute(f"""
        CREATE POLICY p_agent_documents_agent_delete ON agent_documents
          AS PERMISSIVE FOR DELETE
          USING ({using_agent_docs});
    """)

    # ===========================================================
    # 7) audit_logs INSERT — owner_scope 검증 강화 + 전역 NULL owner 가드 (R2 patch)
    #    R3 patch (필수): admin/system + NULL owner 분기에 tenant_id 매칭 강제
    #    (cross-tenant 로그 오염 방지)
    #    audit_logs UPDATE/DELETE 정책 *부재* → append-only 강제 (RLS 기본 거부)
    # ===========================================================
    op.execute(f"""
        CREATE POLICY p_audit_logs_insert ON audit_logs
          AS PERMISSIVE FOR INSERT
          WITH CHECK (
            -- 전역 NULL owner 가드 (R2 권고 #4)
            (owner_agent_id IS NOT NULL OR owner_scope IN ('admin', 'system'))
            AND (
              -- admin scope (자기 tenant)
              (current_setting('app.current_scope', true) = 'admin'
               AND {_tenant_id_match()})
              -- superadmin
              OR current_setting('app.current_scope', true) = 'superadmin'
              -- agent 본인 row
              OR (
                current_setting('app.current_scope', true) = 'agent'
                AND owner_scope = 'agent'
                AND owner_agent_id IS NOT NULL
                AND {_agent_id_match()}
                AND {_tenant_id_match()}
              )
              -- system / admin scope + NULL owner (background worker / cron) —
              -- R3 패치: tenant_id 매칭 강제 (admin 이 타 tenant 로 로그 오염 차단)
              OR (
                current_setting('app.current_scope', true) IN ('admin', 'system')
                AND owner_scope IN ('admin', 'system')
                AND owner_agent_id IS NULL
                AND {_tenant_id_match()}
              )
            )
          );
    """)


def downgrade() -> None:
    # documents / library_folders policies (admin/superadmin/agent SELECT + INSERT/UPDATE/DELETE)
    for table in OWNER_TABLES:
        for policy in (
            f"p_{table}_admin_select",
            f"p_{table}_superadmin_select",
            f"p_{table}_agent_select",
            f"p_{table}_agent_insert",
            f"p_{table}_agent_update",
            f"p_{table}_agent_delete",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")

    # audit_logs policies
    for policy in (
        "p_audit_logs_admin_select",
        "p_audit_logs_superadmin_select",
        "p_audit_logs_agent_select",
        "p_audit_logs_insert",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON audit_logs;")

    # agent_documents policies (R2 split)
    for policy in (
        "p_agent_documents_admin_select",
        "p_agent_documents_superadmin_select",
        "p_agent_documents_agent_select",
        "p_agent_documents_agent_insert",
        "p_agent_documents_agent_update",
        "p_agent_documents_agent_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON agent_documents;")

    # NO FORCE + DISABLE RLS
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
