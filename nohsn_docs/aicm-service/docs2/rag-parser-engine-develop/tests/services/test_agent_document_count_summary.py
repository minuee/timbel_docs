"""AgentDocumentService.count_summary — DB integration test.

GPT-5 P0 (2026-05-07): NULL 3-value logic 회귀 방지. f.kind=NULL,
d.is_sop=false 인 doc 이 kms_repo_inferred 에 *반드시* 포함돼야 함.

이전 SQL `NOT (d.is_sop=true OR f.kind='sop')` 는 (false OR NULL)=NULL →
NOT(NULL)=NULL → WHERE 절 탈락 → kms_repo_inferred undercount 발생.

수정: COALESCE(d.is_sop, false)=false AND f.kind IS DISTINCT FROM 'sop'.

Spec: docs/superpowers/specs/2026-05-07-sop-kms-prompt-architecture.md §4.4
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from src.common.config import settings
from src.core.services.agent_document_service import AgentDocumentService


TEST_PREFIX = "agds_summary__"


async def _make_tenant(conn, slug: str) -> UUID:
    r = await conn.execute(
        text(
            """
            INSERT INTO tenants
              (id, slug, name, tenant_type, plan, config, context_config, is_active)
            VALUES
              (gen_random_uuid(), :slug, :name, 'personal', 'free',
               '{}'::jsonb, '{}'::jsonb, true)
            RETURNING id
            """
        ),
        {"slug": slug, "name": slug},
    )
    return r.scalar_one()


async def _make_repo(conn, tenant_id: UUID, name: str) -> UUID:
    r = await conn.execute(
        text(
            """
            INSERT INTO repositories
              (id, tenant_id, name, namespace, description, is_active,
               created_at, updated_at)
            VALUES
              (gen_random_uuid(), :tid, :name, :ns, '', true, now(), now())
            RETURNING id
            """
        ),
        {"tid": tenant_id, "name": name, "ns": name},
    )
    return r.scalar_one()


async def _make_account(conn, personal_tenant_id: UUID) -> UUID:
    """test fixture account — agents.created_by FK 충족용.

    accounts.personal_tenant_id NOT NULL — caller 가 tenant 미리 만들어 전달.
    """
    r = await conn.execute(
        text(
            """
            INSERT INTO accounts
              (id, phone, name, personal_tenant_id, email, password_hash,
               email_verified, is_active, preferences,
               created_at, updated_at)
            VALUES
              (gen_random_uuid(), :phone, 'test', :ptid, :email, 'x',
               false, true, '{}'::jsonb,
               now(), now())
            RETURNING id
            """
        ),
        {
            "phone": f"010-{uuid4().hex[:8]}",
            "ptid": personal_tenant_id,
            "email": f"test_{uuid4().hex[:8]}@local",
        },
    )
    return r.scalar_one()


async def _make_agent(
    conn,
    tenant_id: UUID,
    name: str,
    sop_repos: list[UUID],
    primary_repos: list[UUID],
    created_by: UUID,
) -> UUID:
    """최소 컬럼만 채워 agent INSERT.

    NOT NULL 컬럼 누락 시 schema 에 따라 추가 필요.
    """
    r = await conn.execute(
        text(
            """
            INSERT INTO agents
              (id, tenant_id, name, kind, sop_repo_ids, primary_repo_ids,
               fallback_repo_ids, is_active, rate_limit_per_min,
               persona, system_prompt, allowed_skills, allowed_repos,
               goal, guidelines_md, knowledge_isolation, allowed_tools,
               test_mode_visible, delegate_to_agent_ids, is_template,
               web_search_mode,
               created_by, created_at, updated_at)
            VALUES
              (gen_random_uuid(), :tid, :name, 'role',
               CAST(:sop_ids AS uuid[]), CAST(:pri_ids AS uuid[]),
               CAST(:empty AS uuid[]), true, 60,
               '', '', '[]'::jsonb, '[]'::jsonb,
               '', '', 'priority', '{}'::text[],
               true, CAST(:empty AS uuid[]), false,
               'off',
               :cb, now(), now())
            RETURNING id
            """
        ),
        {
            "tid": tenant_id,
            "name": name,
            "sop_ids": [str(r) for r in sop_repos],
            "pri_ids": [str(r) for r in primary_repos],
            "empty": [],
            "cb": created_by,
        },
    )
    return r.scalar_one()


async def _make_doc(
    conn,
    tenant_id: UUID,
    repo_id: UUID,
    *,
    title: str,
    is_sop: bool = False,
    folder_id: UUID | None = None,
) -> UUID:
    r = await conn.execute(
        text(
            """
            INSERT INTO documents
              (id, tenant_id, repository_id, folder_id, title, status,
               source_format, is_sop, created_at, updated_at)
            VALUES
              (gen_random_uuid(), :tid, :rid, :fid, :title, 'active',
               'md', :is_sop, now(), now())
            RETURNING id
            """
        ),
        {
            "tid": tenant_id,
            "rid": repo_id,
            "fid": folder_id,
            "title": title,
            "is_sop": is_sop,
        },
    )
    return r.scalar_one()


async def _cleanup_tenant(
    engine: AsyncEngine, tenant_id: UUID, account_ids: list[UUID] | None = None
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM agent_documents WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await conn.execute(
            text(
                """
                DELETE FROM documents
                WHERE repository_id IN (
                    SELECT id FROM repositories WHERE tenant_id = :tid
                )
                """
            ),
            {"tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM agents WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM library_folders WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM repositories WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await conn.execute(
            text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        )
        for aid in account_ids or []:
            await conn.execute(
                text("DELETE FROM accounts WHERE id = :aid"), {"aid": aid}
            )


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(settings.DATABASE_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def tenant(engine: AsyncEngine):
    slug = f"{TEST_PREFIX}{uuid4().hex[:8]}"
    async with engine.begin() as conn:
        tid = await _make_tenant(conn, slug)
    yield tid
    await _cleanup_tenant(engine, tid)


@pytest_asyncio.fixture
async def account(engine: AsyncEngine, tenant: UUID):
    """test 고정 account — agents.created_by FK 충족용.

    personal_tenant_id 는 별도 fixture tenant 재사용 (간단화 — 실제 운영
    isolation 과 무관, 테스트 격리만 충족).
    """
    async with engine.begin() as conn:
        aid = await _make_account(conn, personal_tenant_id=tenant)
    yield aid
    # accounts 정리는 cleanup_tenant 에서 함께 처리 — tenants ON DELETE RESTRICT
    # 회피 위해 tenant fixture teardown 전에 미리 삭제.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM accounts WHERE id = :aid"), {"aid": aid}
        )


@pytest.mark.asyncio
async def test_repo_inferred_kms_includes_doc_with_null_folder_and_is_sop_false(
    engine: AsyncEngine, tenant: UUID, account: UUID
):
    """GPT-5 P0 회귀 테스트.

    - doc.is_sop = false
    - doc.folder_id = NULL (→ f.kind = NULL)
    - doc 의 repo 가 agent.primary_repo_ids 안에 있음
    - agent_documents 매핑 없음 (mapping 권위 없음)

    이 doc 은 *반드시* kms_repo_inferred = 1 로 카운트돼야 함.

    버그 SQL `NOT (d.is_sop=true OR f.kind='sop')` 는 (false OR NULL)=NULL →
    NOT(NULL)=NULL → WHERE 탈락 → 0 반환 (false negative).
    수정 SQL 은 1 반환.
    """
    repo_id = None
    agent_id = None
    async with engine.begin() as conn:
        repo_id = await _make_repo(conn, tenant, "repo_kms_only")
        agent_id = await _make_agent(
            conn, tenant, "agent_kms_repo",
            sop_repos=[], primary_repos=[repo_id], created_by=account,
        )
        # is_sop=false + folder_id=NULL — 핵심 케이스.
        await _make_doc(
            conn, tenant, repo_id, title="manual_no_folder", is_sop=False
        )

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as sess:
        svc = AgentDocumentService(sess)
        result = await svc.count_summary(agent_id=agent_id, tenant_id=tenant)

    assert result["sop"] == 0, f"expected sop=0, got {result['sop']}"
    assert result["kms"] == 1, (
        f"expected kms=1 (repo_inferred include doc with NULL folder + is_sop=false), "
        f"got {result['kms']} — possible NULL 3-value logic regression"
    )
    assert result["by_source"]["kms_repo_inferred"] == 1
    assert result["by_source"]["kms_mapping"] == 0
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_disjoint_mapping_priority_over_repo_inferred(
    engine: AsyncEngine, tenant: UUID, account: UUID
):
    """spec §4.4 — 같은 doc 이 mapping('kms') + sop_repo_ids 안 (is_sop=true)
    양쪽에 잡히는 경우 mapping='kms' 권위 → kms count 1, sop count 0.

    NOT EXISTS 로 sop_repo_inferred 에서 제외 + ROW_NUMBER mapping 우선.
    """
    repo_id = None
    agent_id = None
    doc_id = None
    async with engine.begin() as conn:
        repo_id = await _make_repo(conn, tenant, "repo_sop")
        agent_id = await _make_agent(
            conn, tenant, "agent_disjoint",
            sop_repos=[repo_id], primary_repos=[repo_id], created_by=account,
        )
        # is_sop=true (sop_repo_inferred 후보) — 단 mapping 으로 kms 권위 부여.
        doc_id = await _make_doc(
            conn, tenant, repo_id, title="ambiguous", is_sop=True
        )
        # mapping 'kms' — 권위.
        await conn.execute(
            text(
                """
                INSERT INTO agent_documents
                  (id, tenant_id, agent_id, document_id, mode, source,
                   created_at, updated_at)
                VALUES
                  (gen_random_uuid(), :tid, :aid, :did, 'kms', 'shared',
                   now(), now())
                """
            ),
            {"tid": tenant, "aid": agent_id, "did": doc_id},
        )

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as sess:
        svc = AgentDocumentService(sess)
        result = await svc.count_summary(agent_id=agent_id, tenant_id=tenant)

    # disjoint 보장 — 같은 doc 이 sop=1 + kms=1 양쪽 카운트되면 total=2 (버그).
    assert result["sop"] == 0, (
        f"expected sop=0 (mapping='kms' wins), got {result['sop']} — "
        f"NOT EXISTS exclusion may be broken"
    )
    assert result["kms"] == 1
    assert result["by_source"]["kms_mapping"] == 1
    assert result["by_source"]["sop_repo_inferred"] == 0
    assert result["total"] == 1, "sop+kms must equal total (disjoint)"


@pytest.mark.asyncio
async def test_empty_agent_returns_zero(
    engine: AsyncEngine, tenant: UUID, account: UUID
):
    """sop/primary 모두 빈 agent → 모두 0."""
    async with engine.begin() as conn:
        agent_id = await _make_agent(
            conn, tenant, "agent_empty",
            sop_repos=[], primary_repos=[], created_by=account,
        )

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as sess:
        svc = AgentDocumentService(sess)
        result = await svc.count_summary(agent_id=agent_id, tenant_id=tenant)

    assert result == {
        "sop": 0,
        "kms": 0,
        "total": 0,
        "by_source": {
            "sop_mapping": 0,
            "sop_repo_inferred": 0,
            "kms_mapping": 0,
            "kms_repo_inferred": 0,
        },
    }


@pytest.mark.asyncio
async def test_cross_tenant_permission_error(
    engine: AsyncEngine, tenant: UUID, account: UUID
):
    """다른 tenant 의 agent 조회 → PermissionError."""
    other_slug = f"{TEST_PREFIX}other_{uuid4().hex[:8]}"
    async with engine.begin() as conn:
        other_tid = await _make_tenant(conn, other_slug)
        agent_id = await _make_agent(
            conn, tenant, "agent_isolated",
            sop_repos=[], primary_repos=[], created_by=account,
        )

    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as sess:
            svc = AgentDocumentService(sess)
            with pytest.raises(PermissionError):
                # tenant 다른 caller 가 호출 → PermissionError
                await svc.count_summary(agent_id=agent_id, tenant_id=other_tid)
    finally:
        await _cleanup_tenant(engine, other_tid)
