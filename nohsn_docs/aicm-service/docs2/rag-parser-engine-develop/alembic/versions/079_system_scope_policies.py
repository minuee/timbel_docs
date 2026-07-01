"""D34 §0 — system scope RLS 정책 보강 (#211).

Revision ID: 079
Revises: 078
Create Date: 2026-05-08

목적:
- D33 가 KMS_DB_ROLE_API=app + bind_agent_scope 활성화 완료.
- D34 §2 가 KMS_DB_ROLE_WORKER=app 전환 — pipeline-worker 가 NOBYPASSRLS 로 connect.
- 077 정책에는 documents/library_folders/agent_documents 의 *system scope 분기 부재* —
  worker 가 system scope 진입해도 SELECT/INSERT 모두 차단.
- 본 리비전이 system scope 정책 추가 → bind_system_scope() helper 와 함께 worker 에서
  RLS 통과 가능.

GPT-5 phase 0 verdict (#211): GO_WITH_CHANGES. alembic 079 MUST 추가. system SELECT 는
cross-tenant 허용 (document_id → tenant_id 1차 lookup), INSERT/UPDATE/DELETE 는 tenant_id
매칭 강제 (cross-tenant 오염 차단).

설계:
1. system SELECT — 077 의 admin/superadmin/agent select 와 *별도 정책*. cross-tenant 허용
   (worker 가 document_id → tenant_id lookup 전 단계 전 보장).
2. system INSERT/UPDATE/DELETE — 077 의 using_owner_agent / using_agent_docs 식에 system
   분기 추가. **DROP + CREATE** (077 의 p_{table}_agent_insert/update/delete 정책 재생성).
3. agent_documents 동일 처리.
4. audit_logs — 077 에 이미 system 분기 있음. 변경 없음.

회귀 0 보장:
- 077 의 admin/superadmin/agent 분기는 DROP + CREATE 시 그대로 유지 (식만 OR system 추가).
- BYPASSRLS role (kms_migration / kms_superadmin) 은 정책 무관.
- 본 리비전은 *추가* 만 — 기존 정책 강도 유지 + 운영 path 회귀 0.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "079"
down_revision: Union[str, None] = "078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 077 와 동일 — 컬럼 매칭 식 helper.
OWNER_TABLES = ("documents", "library_folders")
AGENT_DOCS_TABLE = "agent_documents"


def _agent_id_match() -> str:
    return (
        "owner_agent_id = NULLIF(current_setting('app.current_agent_id', true), '')::uuid"
    )


def _tenant_id_match() -> str:
    return (
        "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    )


def _agent_documents_id_match() -> str:
    return (
        "agent_id = NULLIF(current_setting('app.current_agent_id', true), '')::uuid"
    )


def upgrade() -> None:
    # =========================================================
    # 1) system SELECT — cross-tenant 허용 (document_id → tenant_id lookup)
    # =========================================================
    for table in OWNER_TABLES + (AGENT_DOCS_TABLE,):
        op.execute(f"""
            CREATE POLICY p_{table}_system_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (current_setting('app.current_scope', true) = 'system');
        """)

    # =========================================================
    # 2) documents / library_folders 의 INSERT/UPDATE/DELETE 정책 재생성
    #    (077 의 p_{table}_agent_insert/update/delete 식에 system 분기 추가)
    # =========================================================
    using_owner_agent_with_system = f"""
        (current_setting('app.current_scope', true) = 'admin'
         AND {_tenant_id_match()})
        OR current_setting('app.current_scope', true) = 'superadmin'
        OR (
          current_setting('app.current_scope', true) = 'agent'
          AND {_agent_id_match()}
          AND {_tenant_id_match()}
        )
        OR (
          current_setting('app.current_scope', true) = 'system'
          AND {_tenant_id_match()}
        )
    """

    for table in OWNER_TABLES:
        # 077 의 정책 DROP 후 system 분기 포함 재생성.
        op.execute(f"DROP POLICY IF EXISTS p_{table}_agent_insert ON {table};")
        op.execute(f"DROP POLICY IF EXISTS p_{table}_agent_update ON {table};")
        op.execute(f"DROP POLICY IF EXISTS p_{table}_agent_delete ON {table};")

        op.execute(f"""
            CREATE POLICY p_{table}_agent_insert ON {table}
              AS PERMISSIVE FOR INSERT
              WITH CHECK ({using_owner_agent_with_system});
        """)
        op.execute(f"""
            CREATE POLICY p_{table}_agent_update ON {table}
              AS PERMISSIVE FOR UPDATE
              USING ({using_owner_agent_with_system})
              WITH CHECK ({using_owner_agent_with_system});
        """)
        op.execute(f"""
            CREATE POLICY p_{table}_agent_delete ON {table}
              AS PERMISSIVE FOR DELETE
              USING ({using_owner_agent_with_system});
        """)

    # =========================================================
    # 3) agent_documents 의 INSERT/UPDATE/DELETE 정책 재생성
    # =========================================================
    using_agent_docs_with_system = f"""
        (current_setting('app.current_scope', true) = 'admin'
         AND {_tenant_id_match()})
        OR current_setting('app.current_scope', true) = 'superadmin'
        OR (
          current_setting('app.current_scope', true) = 'agent'
          AND {_agent_documents_id_match()}
          AND {_tenant_id_match()}
        )
        OR (
          current_setting('app.current_scope', true) = 'system'
          AND {_tenant_id_match()}
        )
    """

    op.execute(
        "DROP POLICY IF EXISTS p_agent_documents_agent_insert ON agent_documents;"
    )
    op.execute(
        "DROP POLICY IF EXISTS p_agent_documents_agent_update ON agent_documents;"
    )
    op.execute(
        "DROP POLICY IF EXISTS p_agent_documents_agent_delete ON agent_documents;"
    )

    op.execute(f"""
        CREATE POLICY p_agent_documents_agent_insert ON agent_documents
          AS PERMISSIVE FOR INSERT
          WITH CHECK ({using_agent_docs_with_system});
    """)
    op.execute(f"""
        CREATE POLICY p_agent_documents_agent_update ON agent_documents
          AS PERMISSIVE FOR UPDATE
          USING ({using_agent_docs_with_system})
          WITH CHECK ({using_agent_docs_with_system});
    """)
    op.execute(f"""
        CREATE POLICY p_agent_documents_agent_delete ON agent_documents
          AS PERMISSIVE FOR DELETE
          USING ({using_agent_docs_with_system});
    """)

    # =========================================================
    # 4) audit_logs — 077 에 이미 system 분기. 변경 없음.
    # =========================================================


def downgrade() -> None:
    # 1) system SELECT 정책 DROP.
    for table in OWNER_TABLES + (AGENT_DOCS_TABLE,):
        op.execute(f"DROP POLICY IF EXISTS p_{table}_system_select ON {table};")

    # 2) 077 의 식 (system 분기 *없음*) 으로 정책 재생성.
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
        op.execute(f"DROP POLICY IF EXISTS p_{table}_agent_insert ON {table};")
        op.execute(f"DROP POLICY IF EXISTS p_{table}_agent_update ON {table};")
        op.execute(f"DROP POLICY IF EXISTS p_{table}_agent_delete ON {table};")

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

    # 3) agent_documents 077 식으로 재생성.
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

    op.execute(
        "DROP POLICY IF EXISTS p_agent_documents_agent_insert ON agent_documents;"
    )
    op.execute(
        "DROP POLICY IF EXISTS p_agent_documents_agent_update ON agent_documents;"
    )
    op.execute(
        "DROP POLICY IF EXISTS p_agent_documents_agent_delete ON agent_documents;"
    )

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
