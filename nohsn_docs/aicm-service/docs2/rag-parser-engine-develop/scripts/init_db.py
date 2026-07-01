"""DB 테이블 직접 생성 (마이그레이션 대신). 개발용."""

import asyncio
import sys
sys.path.insert(0, "/app")
sys.path.insert(0, ".")


# RLS 정책 적용 helper — alembic 077 + 078 + 079 + 081 의 최종 통합 상태를
# idempotent 하게 ensure (DROP POLICY IF EXISTS → CREATE 패턴).
# 081 의 lucas_kms_app / lucas_kms_migrate role 은 *추가 role* 이고 현 KMS
# 운영에서 미사용 — superadmin 화이트리스트에 entry 만 남기고 role 생성은 skip.
async def _apply_rls_policies(engine):
    from sqlalchemy import text

    _TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    _AGENT_MATCH = "owner_agent_id = NULLIF(current_setting('app.current_agent_id', true), '')::uuid"
    _AGENT_DOCS_ID_MATCH = "agent_id = NULLIF(current_setting('app.current_agent_id', true), '')::uuid"

    OWNER_TABLES = ("documents", "library_folders")
    ALL_077_TABLES = OWNER_TABLES + ("audit_logs", "agent_documents")

    DIRECT_TENANT_TABLES = ("repositories", "search_logs", "intent_logs")
    JOIN_TENANT_TABLES = {
        "sections": ("documents", "document_id"),
        "blocks": ("documents", "document_id"),
        # chunks 는 직접 tenant_id 컬럼이 없음 (모델/마이그레이션/실스키마 모두) —
        # repository_id 로 부모(repositories.tenant_id) 격리. sections/blocks 와 동일 패턴.
        "chunks": ("repositories", "repository_id"),
        "categories": ("repositories", "repository_id"),
    }

    using_owner_with_system = f"""
        (current_setting('app.current_scope', true) = 'admin' AND {_TENANT_MATCH})
        OR current_setting('app.current_scope', true) = 'superadmin'
        OR (current_setting('app.current_scope', true) = 'agent'
            AND {_AGENT_MATCH} AND {_TENANT_MATCH})
        OR (current_setting('app.current_scope', true) = 'system' AND {_TENANT_MATCH})
    """
    using_agent_docs_with_system = f"""
        (current_setting('app.current_scope', true) = 'admin' AND {_TENANT_MATCH})
        OR current_setting('app.current_scope', true) = 'superadmin'
        OR (current_setting('app.current_scope', true) = 'agent'
            AND {_AGENT_DOCS_ID_MATCH} AND {_TENANT_MATCH})
        OR (current_setting('app.current_scope', true) = 'system' AND {_TENANT_MATCH})
    """

    async with engine.begin() as conn:
        # migration 072/076 이 적용됐는지 확인 — owner_agent_id 컬럼 존재 여부.
        # 구버전 이미지로 init_db 만 재실행할 때 컬럼 미존재로 정책 생성 실패하는
        # 것을 방지. 컬럼이 없으면 agent_select 정책은 DROP 만 하고 생성 생략.
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'owner_agent_id'
            )
        """))
        row = result.fetchone()
        has_owner_agent_id = bool(row[0]) if row else False

        # ============ 077: ENABLE + FORCE on 4 tables ============
        for table in ALL_077_TABLES:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"))

        # 077 + 078: admin SELECT + superadmin SELECT (current_user 화이트리스트)
        for table in ALL_077_TABLES:
            await conn.execute(text(f"DROP POLICY IF EXISTS p_{table}_admin_select ON {table};"))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_admin_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'admin'
                         AND {_TENANT_MATCH});
            """))
            await conn.execute(text(f"DROP POLICY IF EXISTS p_{table}_superadmin_select ON {table};"))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_superadmin_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'superadmin'
                         AND current_user = 'kms_superadmin');
            """))

        # 077: agent SELECT (owner_agent_id 기반, documents/library_folders/audit_logs)
        # owner_agent_id 컬럼이 없으면 정책 DROP 만 수행 (migration 072/076 대기).
        for table in OWNER_TABLES + ("audit_logs",):
            await conn.execute(text(f"DROP POLICY IF EXISTS p_{table}_agent_select ON {table};"))
            if has_owner_agent_id:
                await conn.execute(text(f"""
                    CREATE POLICY p_{table}_agent_select ON {table}
                      AS PERMISSIVE FOR SELECT
                      USING (current_setting('app.current_scope', true) = 'agent'
                             AND owner_agent_id IS NOT NULL
                             AND {_AGENT_MATCH} AND {_TENANT_MATCH});
                """))
        # agent_documents: agent_id 기반
        await conn.execute(text("DROP POLICY IF EXISTS p_agent_documents_agent_select ON agent_documents;"))
        await conn.execute(text(f"""
            CREATE POLICY p_agent_documents_agent_select ON agent_documents
              AS PERMISSIVE FOR SELECT
              USING (current_setting('app.current_scope', true) = 'agent'
                     AND {_AGENT_DOCS_ID_MATCH} AND {_TENANT_MATCH});
        """))

        # 079: system SELECT (documents / library_folders / agent_documents)
        for table in OWNER_TABLES + ("agent_documents",):
            await conn.execute(text(f"DROP POLICY IF EXISTS p_{table}_system_select ON {table};"))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_system_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'system');
            """))

        # 077 + 079: documents/library_folders INSERT/UPDATE/DELETE (system 분기 포함)
        for table in OWNER_TABLES:
            for op_name in ("insert", "update", "delete"):
                await conn.execute(text(f"DROP POLICY IF EXISTS p_{table}_agent_{op_name} ON {table};"))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_agent_insert ON {table}
                  AS PERMISSIVE FOR INSERT
                  WITH CHECK ({using_owner_with_system});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_agent_update ON {table}
                  AS PERMISSIVE FOR UPDATE
                  USING ({using_owner_with_system})
                  WITH CHECK ({using_owner_with_system});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_agent_delete ON {table}
                  AS PERMISSIVE FOR DELETE
                  USING ({using_owner_with_system});
            """))

        # 077 + 079: agent_documents INSERT/UPDATE/DELETE (system 분기 포함)
        for op_name in ("insert", "update", "delete"):
            await conn.execute(text(f"DROP POLICY IF EXISTS p_agent_documents_agent_{op_name} ON agent_documents;"))
        await conn.execute(text(f"""
            CREATE POLICY p_agent_documents_agent_insert ON agent_documents
              AS PERMISSIVE FOR INSERT
              WITH CHECK ({using_agent_docs_with_system});
        """))
        await conn.execute(text(f"""
            CREATE POLICY p_agent_documents_agent_update ON agent_documents
              AS PERMISSIVE FOR UPDATE
              USING ({using_agent_docs_with_system})
              WITH CHECK ({using_agent_docs_with_system});
        """))
        await conn.execute(text(f"""
            CREATE POLICY p_agent_documents_agent_delete ON agent_documents
              AS PERMISSIVE FOR DELETE
              USING ({using_agent_docs_with_system});
        """))

        # 077: audit_logs INSERT (append-only — UPDATE/DELETE 정책 부재)
        # owner_agent_id 컬럼 미존재 시 간소화 버전 (agent 격리 없이 tenant 격리만)
        await conn.execute(text("DROP POLICY IF EXISTS p_audit_logs_insert ON audit_logs;"))
        if has_owner_agent_id:
            await conn.execute(text(f"""
                CREATE POLICY p_audit_logs_insert ON audit_logs
                  AS PERMISSIVE FOR INSERT
                  WITH CHECK (
                    (owner_agent_id IS NOT NULL OR owner_scope IN ('admin', 'system'))
                    AND (
                      (current_setting('app.current_scope', true) = 'admin' AND {_TENANT_MATCH})
                      OR current_setting('app.current_scope', true) = 'superadmin'
                      OR (current_setting('app.current_scope', true) = 'agent'
                          AND owner_scope = 'agent'
                          AND owner_agent_id IS NOT NULL
                          AND {_AGENT_MATCH} AND {_TENANT_MATCH})
                      OR (current_setting('app.current_scope', true) IN ('admin', 'system')
                          AND owner_scope IN ('admin', 'system')
                          AND owner_agent_id IS NULL
                          AND {_TENANT_MATCH})
                    )
                  );
            """))
        else:
            await conn.execute(text(f"""
                CREATE POLICY p_audit_logs_insert ON audit_logs
                  AS PERMISSIVE FOR INSERT
                  WITH CHECK (
                    (current_setting('app.current_scope', true) IN ('admin', 'system') AND {_TENANT_MATCH})
                    OR current_setting('app.current_scope', true) = 'superadmin'
                  );
            """))

        # ============ 081: DIRECT_TENANT_TABLES (4) ============
        write_clause_direct = f"""
            (current_setting('app.current_scope', true) IN ('admin', 'agent') AND {_TENANT_MATCH})
            OR (current_setting('app.current_scope', true) = 'superadmin'
                AND current_user IN ('kms_superadmin', 'lucas_kms_migrate'))
        """
        for table in DIRECT_TENANT_TABLES:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"))
            for suffix in ("admin_select", "superadmin_select", "agent_select",
                           "write_insert", "write_update", "write_delete"):
                await conn.execute(text(f"DROP POLICY IF EXISTS p_{table}_{suffix} ON {table};"))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_admin_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'admin'
                         AND {_TENANT_MATCH});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_superadmin_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'superadmin'
                         AND current_user IN ('kms_superadmin', 'lucas_kms_migrate'));
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_agent_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'agent'
                         AND {_TENANT_MATCH});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_write_insert ON {table}
                  AS PERMISSIVE FOR INSERT
                  WITH CHECK ({write_clause_direct});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_write_update ON {table}
                  AS PERMISSIVE FOR UPDATE
                  USING ({write_clause_direct})
                  WITH CHECK ({write_clause_direct});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_write_delete ON {table}
                  AS PERMISSIVE FOR DELETE
                  USING ({write_clause_direct});
            """))

        # ============ 081 + 082: JOIN_TENANT_TABLES (system scope 포함) ============
        for table, (parent, fk_col) in JOIN_TENANT_TABLES.items():
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"))
            for suffix in ("join_select", "superadmin_select", "system_select",
                           "join_insert", "join_update", "join_delete"):
                await conn.execute(text(f"DROP POLICY IF EXISTS p_{table}_{suffix} ON {table};"))
            join_subq = (
                f"EXISTS (SELECT 1 FROM {parent} p WHERE p.id = {table}.{fk_col} "
                f"AND p.tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)"
            )
            join_using = f"""
                (current_setting('app.current_scope', true) IN ('admin', 'agent') AND {join_subq})
                OR (current_setting('app.current_scope', true) = 'superadmin'
                    AND current_user IN ('kms_superadmin', 'lucas_kms_migrate'))
                OR (current_setting('app.current_scope', true) = 'system' AND {join_subq})
            """
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_join_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) IN ('admin', 'agent')
                         AND {join_subq});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_superadmin_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'superadmin'
                         AND current_user IN ('kms_superadmin', 'lucas_kms_migrate'));
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_system_select ON {table}
                  AS PERMISSIVE FOR SELECT
                  USING (current_setting('app.current_scope', true) = 'system'
                         AND {join_subq});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_join_insert ON {table}
                  AS PERMISSIVE FOR INSERT
                  WITH CHECK ({join_using});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_join_update ON {table}
                  AS PERMISSIVE FOR UPDATE
                  USING ({join_using})
                  WITH CHECK ({join_using});
            """))
            await conn.execute(text(f"""
                CREATE POLICY p_{table}_join_delete ON {table}
                  AS PERMISSIVE FOR DELETE
                  USING ({join_using});
            """))


async def main():
    from src.common.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine
    from src.core.models.base import Base

    # Import all models so they register with Base.metadata.
    # models/__init__ 이 AgentDocument 와 그 FK 대상 Agent 를 함께 등록하므로
    # create_all 이 dangling FK 없이 동작 (fresh DB 기동 가능).
    import src.core.models  # noqa: F401
    from src.core.models.user import User, UserRepositoryAccess  # noqa: F401
    from src.core.models.tenant import Tenant  # noqa: F401
    from src.core.models.tenant_link import TenantLink  # noqa: F401
    from src.core.models.audit_log import AuditLog  # noqa: F401
    from src.core.models.lifecycle_feedback import LifecycleFeedback  # noqa: F401
    from src.core.models.scheduled_action import ScheduledAction  # noqa: F401
    from src.core.models.transition import TransitionEvent, LifecyclePolicy  # noqa: F401
    from src.core.models.api_key import APIKey  # noqa: F401
    # AgentDocument FK 가 agents.id 를 참조하지만 src/core/models/__init__.py 는
    # KMS pipeline core scope 만 export 하므로 Agent 가 누락 → NoReferencedTableError.
    # Agent 모델 자체는 agent_framework runtime 과 무관 (sqlalchemy + Base 만 의존)
    # 이라 KMS image 에 안전하게 포함 가능. FK reference target 으로 빈 테이블 생성.
    from src.core.models.agent import (  # noqa: F401
        Agent,
        AgentChannel,
        ChannelInboundDedup,
        ChannelUserMapping,
    )

    engine = create_async_engine(settings.DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("\n✓ All tables created successfully.")

    # ====================================================================
    # kms_app / kms_superadmin role + GRANT — alembic 078 등가.
    # init_db.py 가 alembic 우회 경로이므로 분리 RLS user 도 여기서 직접 ensure.
    # IF NOT EXISTS 패턴이라 idempotent. 비밀번호는 env (compose default 와 일치).
    # ====================================================================
    import os
    from sqlalchemy import text

    def _sql_lit(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    kms_app_pwd_lit = _sql_lit(os.environ.get("KMS_APP_PASSWORD", "kms_app_dev_password"))
    kms_super_pwd_lit = _sql_lit(
        os.environ.get("KMS_SUPERADMIN_PASSWORD", "kms_superadmin_dev_password")
    )

    async with engine.begin() as conn:
        # kms_app role — 생성 + 비번 idempotent 갱신 (env 값을 source of truth 로).
        # ALTER ROLE 이 있어야 .env 의 비번을 *나중에* 바꿔도 PG 안의 비번이 따라옴.
        await conn.execute(text(f"""
            DO $do$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kms_app') THEN
                    EXECUTE format(
                        'CREATE ROLE kms_app LOGIN PASSWORD %L '
                        'NOSUPERUSER NOBYPASSRLS NOREPLICATION NOCREATEDB NOCREATEROLE',
                        {kms_app_pwd_lit}
                    );
                ELSE
                    EXECUTE format('ALTER ROLE kms_app WITH PASSWORD %L', {kms_app_pwd_lit});
                END IF;
            EXCEPTION
                WHEN insufficient_privilege THEN
                    RAISE NOTICE 'kms_app role 생성/갱신 권한 부재 — DBA bootstrap 필요.';
            END $do$;
        """))

        # kms_app GRANT
        await conn.execute(text("""
            DO $do$
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
                    RAISE NOTICE 'kms_app GRANT 권한 부재 — DBA bootstrap 필요.';
            END $do$;
        """))

        # kms_superadmin role + GRANT — 비번 idempotent 갱신 포함.
        await conn.execute(text(f"""
            DO $do$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kms_superadmin') THEN
                    EXECUTE format(
                        'CREATE ROLE kms_superadmin LOGIN PASSWORD %L '
                        'NOSUPERUSER NOBYPASSRLS NOREPLICATION NOCREATEDB NOCREATEROLE',
                        {kms_super_pwd_lit}
                    );
                ELSE
                    EXECUTE format('ALTER ROLE kms_superadmin WITH PASSWORD %L', {kms_super_pwd_lit});
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
                    RAISE NOTICE 'kms_superadmin role/grant 권한 부재 — DBA bootstrap 필요.';
            END $do$;
        """))

    print("✓ kms_app + kms_superadmin roles ensured.")

    # Insert default tenant + repo for testing
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from uuid import UUID
    Session = async_sessionmaker(engine)

    # 무인증 모드(LUCAS_AUTH_DISABLED=true)가 fallback 하는 default tenant.
    # settings 에서 읽어 config / alembic 082_seed_default_lucas_tenant 와 항상
    # 일치 — fresh 배포 시 tenant 부재로 인한 FK 위반(테넌트 에러) 방지.
    default_tenant_id = UUID(settings.LUCAS_DEFAULT_TENANT_ID)

    async with Session() as session:
        # Default tenant — 082 마이그레이션과 동일 속성 (idempotent)
        from sqlalchemy import select
        t = await session.execute(select(Tenant).where(Tenant.id == default_tenant_id))
        if not t.scalar_one_or_none():
            session.add(Tenant(
                id=default_tenant_id,
                name="Lucas-KMS Default",
                slug="lucas-kms-default",
                tenant_type="system",
            ))

        # Default repo — default tenant 에 귀속
        from src.core.models.repository import Repository
        r = await session.execute(select(Repository).where(Repository.id == UUID("00000000-0000-0000-0000-000000000001")))
        if not r.scalar_one_or_none():
            session.add(Repository(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                tenant_id=default_tenant_id,
                name="Test Repository",
            ))

        await session.commit()
        print(f"✓ Default tenant ({default_tenant_id}) + repository seeded.")

    # alembic_version.version_num 이 기본 VARCHAR(32) — 긴 revision ID 대비 확장.
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE alembic_version "
            "ALTER COLUMN version_num TYPE VARCHAR(255);"
        ))

    # ====================================================================
    # RLS 정책 적용 — alembic 077 + 078 + 079 + 081 통합 (4 + 4 + 3 tables).
    # seed 이후 적용 — kms (SUPERUSER) 가 RLS 우회로 seed 마무리 후 잠금.
    # GUC binding (app.current_scope / tenant_id / agent_id) 가 API/worker 의
    # session 시작 시 SET LOCAL 으로 주입되어야 retrieval 정상 동작.
    # ====================================================================
    await _apply_rls_policies(engine)
    print("✓ RLS policies applied (077 + 078 + 079 + 081 통합).")

    await engine.dispose()

asyncio.run(main())
