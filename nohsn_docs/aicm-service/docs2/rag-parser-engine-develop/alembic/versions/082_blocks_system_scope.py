"""blocks/sections/chunks/categories RLS — system scope INSERT/DELETE 허용 (#219).

Revision ID: 082
Revises: 081
Create Date: 2026-05-28

문제:
  081_rls_force_lucas_kms_app.py 의 JOIN_TENANT_TABLES (blocks, sections, chunks, categories)
  에 대한 INSERT/UPDATE/DELETE 정책이 scope IN ('admin', 'agent') 와 'superadmin' 만 허용.
  파이프라인 워커는 bind_system_scope() 로 scope='system' 진입 → blocks INSERT 가 RLS
  에 의해 항상 차단 → _persist_blocks_to_db 예외 silently 무시 → blocks 테이블 항상 비어있음.

수정:
  blocks, sections, chunks, categories 의 INSERT/UPDATE/DELETE 정책에 system scope 분기 추가.
  SELECT 도 pipeline worker 가 blocks 삭제 전 조회 필요할 수 있으므로 system_select 추가.

대상: blocks, sections, chunks, categories (081 의 JOIN_TENANT_TABLES 전체).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "082"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 081 의 JOIN_TENANT_TABLES 와 동일
JOIN_TENANT_TABLES = {
    "sections": "documents",
    "blocks": "documents",
    "chunks": "repositories",
    "categories": "repositories",
}
JOIN_FK_COLUMNS = {
    "sections": "document_id",
    "blocks": "document_id",
    "chunks": "repository_id",
    "categories": "repository_id",
}


def upgrade() -> None:
    for table, parent in JOIN_TENANT_TABLES.items():
        fk_col = JOIN_FK_COLUMNS[table]

        join_subq = (
            f"EXISTS ("
            f"  SELECT 1 FROM {parent} p "
            f"  WHERE p.id = {table}.{fk_col} "
            f"  AND p.tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
            f")"
        )

        # system scope SELECT — pipeline worker 가 DELETE 전 read 필요 시.
        op.execute(f"DROP POLICY IF EXISTS p_{table}_system_select ON {table};")
        op.execute(
            f"""
            CREATE POLICY p_{table}_system_select ON {table}
              AS PERMISSIVE FOR SELECT
              USING (
                current_setting('app.current_scope', true) = 'system'
                AND {join_subq}
              );
            """
        )

        # 기존 INSERT/UPDATE/DELETE 정책 DROP 후 system 분기 포함 재생성.
        for policy in (
            f"p_{table}_join_insert",
            f"p_{table}_join_update",
            f"p_{table}_join_delete",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")

        join_using = (
            f"(current_setting('app.current_scope', true) IN ('admin', 'agent') "
            f"AND {join_subq}) "
            f"OR ("
            f"  current_setting('app.current_scope', true) = 'superadmin' "
            f"  AND current_user IN ('kms_superadmin', 'lucas_kms_migrate')"
            f") "
            f"OR ("
            f"  current_setting('app.current_scope', true) = 'system' "
            f"  AND {join_subq}"
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
    for table, parent in JOIN_TENANT_TABLES.items():
        fk_col = JOIN_FK_COLUMNS[table]

        # system_select 제거
        op.execute(f"DROP POLICY IF EXISTS p_{table}_system_select ON {table};")

        # INSERT/UPDATE/DELETE 를 system 분기 없는 081 원본으로 복원.
        for policy in (
            f"p_{table}_join_insert",
            f"p_{table}_join_update",
            f"p_{table}_join_delete",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table};")

        join_subq = (
            f"EXISTS ("
            f"  SELECT 1 FROM {parent} p "
            f"  WHERE p.id = {table}.{fk_col} "
            f"  AND p.tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
            f")"
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
