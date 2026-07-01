"""Phase 1.5E — Agent namespace 3중 격리 layer 회귀 테스트.

Spec: docs/superpowers/specs/2026-05-07-agent-namespace-isolation-design.md
Migration: alembic/versions/065_agent_namespace.py

검증 대상:
1. ORM 모델 — Agent.repo_namespace + Repository.agent_id / namespace 컬럼.
2. AgentContext.from_agent — primary_repo_ids 가 그대로 전달 (namespace 인지 안
   해도 enforce 가능 — repo_id 기반).
3. Engine ``_enrich_plan_tool_args`` — 5 role agent 시뮬레이션:
   - baemin_consult (primary=[repo_baemin_sop]) → 자기 repo 만 inject.
   - admin agent (Locus 어시스턴트) → 어떤 isolation 라도 inject 안 함.
   - cross-leak: baemin agent 가 musinsa repo 를 args 에 박아도 strict 가 덮어씀.

* 본 테스트는 DB 미사용 — ORM column 검증은 alembic 적용 후 SQL 시뮬레이션.
* end-to-end RAG 검증은 별도 통합 테스트 (Doc/TestDoc) 에서 수행.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

# 5 role agent 시뮬레이션 — 실 ricky tenant 의 5 repo 매핑.
REPO_BAEMIN = UUID("11111111-0000-0000-0000-000000000001")
REPO_HOMESHOP = UUID("11111111-0000-0000-0000-000000000002")
REPO_KBSOLDIER = UUID("11111111-0000-0000-0000-000000000003")
REPO_MUSINSA = UUID("11111111-0000-0000-0000-000000000004")
REPO_SAMCHULLY = UUID("11111111-0000-0000-0000-000000000005")
REPO_PUBLIC = UUID("22222222-0000-0000-0000-000000000099")  # agent_id NULL = 공용


def _make_agent_ctx(
    *,
    name: str,
    isolation: str,
    primary: list[UUID],
    fallback: list[UUID] | None = None,
    is_admin: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name=name,
        knowledge_isolation=isolation,
        primary_repo_ids=list(primary),
        fallback_repo_ids=list(fallback or []),
        is_admin=is_admin,
        kind="admin" if is_admin else "role",
        allowed_tools=[],
    )


def _make_engine(agent_context, is_admin: bool = False):
    from src.agent_framework.runtime.engine import AgentEngine

    eng = AgentEngine.__new__(AgentEngine)
    eng._agent_context = agent_context
    eng._is_admin_agent = is_admin
    return eng


def _make_session():
    from src.agent_framework.runtime.session_store import SessionState

    return SessionState(
        session_id="sess-namespace-test",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="67d157c3-5084-49f9-bc15-92ad1bcd8ac7",
        identity={"phone": "01000000000"},
        account_id=None,
        personal_tenant_id=None,
    )


# ============================================================
# Layer A — ORM 컬럼 존재 검증 (alembic 065)
# ============================================================


def test_agent_model_has_repo_namespace_column():
    """Phase 1.5E — agents.repo_namespace 컬럼이 ORM 에 정의됨."""
    from src.core.models.agent import Agent

    cols = {c.name for c in Agent.__table__.columns}
    assert "repo_namespace" in cols, "agent.repo_namespace 컬럼 누락 (alembic 065)"


def test_repository_model_has_agent_id_and_namespace():
    """Phase 1.5E — repositories.agent_id + namespace 컬럼이 ORM 에 정의됨."""
    from src.core.models.repository import Repository

    cols = {c.name for c in Repository.__table__.columns}
    assert "agent_id" in cols, "repositories.agent_id 컬럼 누락 (alembic 065)"
    assert "namespace" in cols, "repositories.namespace 컬럼 누락 (alembic 065)"


def test_repository_agent_id_fk_on_delete_set_null():
    """Phase 1.5E — repositories.agent_id FK 가 ON DELETE SET NULL."""
    from src.core.models.repository import Repository

    fks = list(Repository.__table__.c.agent_id.foreign_keys)
    assert len(fks) == 1, "agent_id 에 FK 1개 기대"
    fk = fks[0]
    assert fk.ondelete == "SET NULL", (
        f"agent_id FK ondelete='SET NULL' 기대, 실제: {fk.ondelete}"
    )


# ============================================================
# Layer B — AgentContext repo_namespace 인식 (구조 검증)
# ============================================================


def test_agent_context_carries_primary_repo_ids():
    """AgentContext.from_agent 가 primary_repo_ids 를 그대로 전달.

    enforce 는 agent_id 가 아니라 repo_id 기반 — namespace 라벨은 표기 용.
    """
    from src.agent_framework.runtime.agent_context import AgentContext

    fake_agent = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        name="baemin_consult",
        goal="배민 응대",
        guidelines_md="",
        primary_repo_ids=[REPO_BAEMIN],
        fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=["kms_rag.search"],
        done_when=None,
        kind="role",
        delegate_to_agent_ids=[],
    )
    ctx = AgentContext.from_agent(fake_agent)
    assert ctx.primary_repo_ids == [REPO_BAEMIN]
    assert ctx.knowledge_isolation == "strict"
    assert ctx.is_admin is False


# ============================================================
# Layer C — 5 role agent 시뮬레이션 (cross-leak 차단)
# ============================================================


def test_baemin_agent_isolates_to_own_repo():
    """baemin_consult (strict) — 자기 repo 만 inject."""
    ctx = _make_agent_ctx(
        name="baemin_consult", isolation="strict", primary=[REPO_BAEMIN]
    )
    eng = _make_engine(ctx)
    sess = _make_session()
    out = eng._enrich_plan_tool_args(
        {"query": "배달 취소 절차"}, sess, tool_name="kms_rag.search"
    )
    assert out["repo_ids"] == [str(REPO_BAEMIN)]
    assert out["enforce_repo_ids"] is True


def test_musinsa_agent_isolates_to_own_repo():
    """musinsa_consult (strict) — 자기 repo 만."""
    ctx = _make_agent_ctx(
        name="musinsa_consult", isolation="strict", primary=[REPO_MUSINSA]
    )
    eng = _make_engine(ctx)
    sess = _make_session()
    out = eng._enrich_plan_tool_args(
        {"query": "교환 절차"}, sess, tool_name="kms_rag.search"
    )
    assert out["repo_ids"] == [str(REPO_MUSINSA)]


def test_baemin_agent_blocks_samchully_repo_in_args():
    """cross-leak 차단 — baemin agent 가 LLM 으로 samchully repo 를 args 에 넣어도 strict 가 덮어씀."""
    ctx = _make_agent_ctx(
        name="baemin_consult", isolation="strict", primary=[REPO_BAEMIN]
    )
    eng = _make_engine(ctx)
    sess = _make_session()
    # LLM 이 잘못 매칭해 samchully repo 를 args 에 넣음 (cross-leak 시도).
    out = eng._enrich_plan_tool_args(
        {"query": "삼천리 가스 누출", "repo_ids": [str(REPO_SAMCHULLY)]},
        sess,
        tool_name="kms_rag.search",
    )
    # strict 는 명시값을 *덮어쓰고* primary 로 강제.
    assert out["repo_ids"] == [str(REPO_BAEMIN)]
    assert str(REPO_SAMCHULLY) not in out["repo_ids"]


def test_admin_agent_bypasses_isolation():
    """admin agent (Locus 어시스턴트) — knowledge_isolation 무관, 모든 repo 접근."""
    ctx = _make_agent_ctx(
        name="locus_admin",
        isolation="strict",  # admin 라도 무시
        primary=[REPO_BAEMIN],
        is_admin=True,
    )
    eng = _make_engine(ctx, is_admin=True)
    sess = _make_session()
    out = eng._enrich_plan_tool_args(
        {"query": "임의 검색"}, sess, tool_name="kms_rag.search"
    )
    # admin 은 inject 안 함 — Layer 2 bypass.
    assert "repo_ids" not in out


def test_priority_isolation_includes_fallback_repos():
    """priority — primary + fallback 모두 inject. broad fallback level-4 가능."""
    ctx = _make_agent_ctx(
        name="kbsoldier_role",
        isolation="priority",
        primary=[REPO_KBSOLDIER],
        fallback=[REPO_PUBLIC],
    )
    eng = _make_engine(ctx)
    sess = _make_session()
    out = eng._enrich_plan_tool_args(
        {"query": "장병 적금 우대 금리"}, sess, tool_name="kms_rag.search"
    )
    assert set(out["repo_ids"]) == {str(REPO_KBSOLDIER), str(REPO_PUBLIC)}
    assert out["enforce_repo_ids"] is False


def test_five_role_agents_no_cross_leak():
    """5 role agent — 자기 repo 만 args 로 보냄, cross-leak 0."""
    role_specs = [
        ("baemin_consult", REPO_BAEMIN),
        ("homeshop_consult", REPO_HOMESHOP),
        ("kbsoldier_advisor", REPO_KBSOLDIER),
        ("musinsa_consult", REPO_MUSINSA),
        ("samchully_voc", REPO_SAMCHULLY),
    ]
    other_repos = {r for _, r in role_specs}

    for name, own_repo in role_specs:
        ctx = _make_agent_ctx(name=name, isolation="strict", primary=[own_repo])
        eng = _make_engine(ctx)
        sess = _make_session()
        out = eng._enrich_plan_tool_args(
            {"query": "임의 발화"}, sess, tool_name="kms_rag.search"
        )
        assert out["repo_ids"] == [str(own_repo)], (
            f"{name} cross-leak: expected only {own_repo}, got {out['repo_ids']}"
        )
        # 다른 4 repo 가 절대 누출되면 안 됨.
        injected = set(out["repo_ids"])
        leaked = injected & {str(r) for r in other_repos - {own_repo}}
        assert not leaked, f"{name} 에 cross-leak {leaked} 발생"
