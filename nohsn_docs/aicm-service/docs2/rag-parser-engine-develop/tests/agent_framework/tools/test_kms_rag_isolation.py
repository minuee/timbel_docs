"""cross-industry RAG isolation 회귀 테스트 (KMS-Plus, 2026-05-07).

role agent (knowledge_isolation in {strict, priority, broad}) 가 kms_rag.search
를 호출할 때 SearchRequest.repository_ids 가 의도대로 전파되는지 검증.

대상 결함 (시연 D-day 직전 발견):
- ricky tenant 5 role agent (baemin/homeshop/kbsoldier/musinsa/samchully) 의
  knowledge_isolation='strict' 가 DB 에는 set 되어 있지만 runtime 에서
  enforce 되지 않아 cross-industry leak 위험.

검증 포인트:
1. KMSRagTool 자체 — args["repo_ids"] 전파.
2. Engine ``_enrich_plan_tool_args`` — agent_context.knowledge_isolation 분기
   로 repo_ids 자동 inject (strict / priority / broad).
3. ToolCallingLoop — agent_context 가 들어왔을 때 동일 분기.
4. SearchService 측은 service.py 에서 dense/sparse/keyword 모두 repo_ids 필터
   적용됨이 별도 search 모듈 테스트로 보장 (이 테스트의 범위 외).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from src.agent_framework.tools.kms_rag import KMSRagTool


REPO_BAEMIN = uuid4()
REPO_MUSINSA = uuid4()
REPO_SAMCHULLY = uuid4()
REPO_GENERIC = uuid4()


class _FakeResultItem:
    def __init__(self, chunk_id, document_id, document_title, content, score):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.document_title = document_title
        self.section_title = ""
        self.content = content
        self.score = score


class _FakeResponse:
    def __init__(self, results):
        self.results = results


def _make_agent_context(
    *,
    isolation: str,
    primary: list[UUID],
    fallback: list[UUID] | None = None,
    is_admin: bool = False,
) -> SimpleNamespace:
    """AgentContext 와 동등한 duck-typed 객체 (frozen dataclass 회피)."""
    return SimpleNamespace(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="test-agent",
        knowledge_isolation=isolation,
        primary_repo_ids=list(primary),
        fallback_repo_ids=list(fallback or []),
        is_admin=is_admin,
        kind="admin" if is_admin else "role",
        allowed_tools=[],
    )


# ============================================================
# Layer 1 — KMSRagTool repo_ids 전파
# ============================================================


@pytest.mark.asyncio
async def test_kms_rag_propagates_repo_ids_to_search_request():
    """args["repo_ids"] 가 SearchRequest.repository_ids 로 전달."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([]))

    with patch(
        "src.search.factory.create_search_service",
        AsyncMock(return_value=fake_svc),
    ):
        tool = KMSRagTool()
        await tool({
            "query": "배민 라이더 매뉴얼",
            "repo_ids": [str(REPO_BAEMIN)],
            "enforce_repo_ids": True,
        })

    req = fake_svc.search.await_args.kwargs["request"]
    assert req.repository_ids == [REPO_BAEMIN]
    assert req.enforce_repository_ids is True


@pytest.mark.asyncio
async def test_kms_rag_strict_empty_repo_ids_returns_zero_hits():
    """strict + primary_repo_ids 가 비고 enforce=True 면 SearchService 호출 없이 0건."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([
        _FakeResultItem("c1", "d1", "leaked", "다른 산업 내용", 0.9),
    ]))

    with patch(
        "src.search.factory.create_search_service",
        AsyncMock(return_value=fake_svc),
    ):
        tool = KMSRagTool()
        got = await tool({
            "query": "아무거나",
            "repo_ids": [],
            "enforce_repo_ids": True,
        })

    # SearchService 가 아예 호출되지 않아야 함 (early sentinel).
    fake_svc.search.assert_not_called()
    assert got["hits"] == []
    assert got["total"] == 0
    assert got["success"] is True


@pytest.mark.asyncio
async def test_kms_rag_no_repo_ids_means_broad_search():
    """repo_ids 미지정 시 SearchRequest.repository_ids=None (전체 tenant)."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([]))

    with patch(
        "src.search.factory.create_search_service",
        AsyncMock(return_value=fake_svc),
    ):
        tool = KMSRagTool()
        await tool({"query": "검색"})

    req = fake_svc.search.await_args.kwargs["request"]
    assert req.repository_ids is None
    assert req.enforce_repository_ids is False


# ============================================================
# Layer 2 — Engine _enrich_plan_tool_args 분기
# ============================================================


def _make_engine_with_agent_context(agent_context, is_admin: bool = False):
    """AgentEngine 의 _enrich_plan_tool_args 를 격리 호출하기 위한 minimal stub.

    실 AgentEngine 인스턴스 생성은 무거우니 __new__ 로 빈 객체만 만들고
    필수 attribute 만 set.
    """
    from src.agent_framework.runtime.engine import AgentEngine

    eng = AgentEngine.__new__(AgentEngine)
    eng._agent_context = agent_context
    eng._is_admin_agent = is_admin
    return eng


def _make_session():
    from src.agent_framework.runtime.session_store import SessionState

    return SessionState(
        session_id="sess-test",
        skill_id=None,
        current_state=None,
        slots={},
        history=[],
        tenant_id="11111111-1111-1111-1111-111111111111",
        identity={"phone": "01000000000"},
        account_id=None,
        personal_tenant_id=None,
    )


def test_enrich_strict_overrides_repo_ids():
    """strict 는 LLM 명시값을 *덮어쓰고* primary_repo_ids 로 강제."""
    ctx = _make_agent_context(
        isolation="strict",
        primary=[REPO_MUSINSA],
        fallback=[REPO_GENERIC],
    )
    eng = _make_engine_with_agent_context(ctx)
    sess = _make_session()

    # LLM 이 의도적으로 다른 repo 를 args 에 넣어도 strict 가 덮어써야 함.
    raw = {"query": "무신사 배송", "repo_ids": [str(REPO_BAEMIN)]}
    out = eng._enrich_plan_tool_args(raw, sess, tool_name="kms_rag.search")

    assert out["repo_ids"] == [str(REPO_MUSINSA)]
    assert out["enforce_repo_ids"] is True


def test_enrich_strict_with_empty_primary_zero_repo_sentinel():
    """strict + primary 빈 → repo_ids=[] sentinel + enforce=True (kms_rag 가 0건 반환)."""
    ctx = _make_agent_context(isolation="strict", primary=[])
    eng = _make_engine_with_agent_context(ctx)
    sess = _make_session()

    out = eng._enrich_plan_tool_args(
        {"query": "x"}, sess, tool_name="kms_rag.search"
    )
    assert out["repo_ids"] == []
    assert out["enforce_repo_ids"] is True


def test_enrich_priority_merges_primary_and_fallback():
    """priority 는 primary + fallback 합치고 enforce=False (level-4 broad fallback 가능)."""
    ctx = _make_agent_context(
        isolation="priority",
        primary=[REPO_SAMCHULLY],
        fallback=[REPO_GENERIC],
    )
    eng = _make_engine_with_agent_context(ctx)
    sess = _make_session()

    out = eng._enrich_plan_tool_args(
        {"query": "삼천리"}, sess, tool_name="kms_rag.search"
    )
    assert set(out["repo_ids"]) == {str(REPO_SAMCHULLY), str(REPO_GENERIC)}
    assert out["enforce_repo_ids"] is False


def test_enrich_priority_preserves_explicit_repo_ids():
    """priority + LLM 이 명시한 repo_ids 가 있으면 *유지* (override 금지)."""
    ctx = _make_agent_context(
        isolation="priority",
        primary=[REPO_SAMCHULLY],
        fallback=[REPO_GENERIC],
    )
    eng = _make_engine_with_agent_context(ctx)
    sess = _make_session()

    explicit = [str(REPO_GENERIC)]
    out = eng._enrich_plan_tool_args(
        {"query": "x", "repo_ids": explicit},
        sess,
        tool_name="kms_rag.search",
    )
    # LLM 명시값 그대로.
    assert out["repo_ids"] == explicit


def test_enrich_broad_does_not_inject():
    """broad 는 inject 안 함 — tenant 전체 검색."""
    ctx = _make_agent_context(
        isolation="broad",
        primary=[REPO_BAEMIN],
        fallback=[REPO_GENERIC],
    )
    eng = _make_engine_with_agent_context(ctx)
    sess = _make_session()

    out = eng._enrich_plan_tool_args(
        {"query": "x"}, sess, tool_name="kms_rag.search"
    )
    assert "repo_ids" not in out
    assert "enforce_repo_ids" not in out


def test_enrich_admin_agent_skips_isolation():
    """admin agent (Locus 어시스턴트) 는 knowledge_isolation 무관 — 항상 broad."""
    ctx = _make_agent_context(
        isolation="strict",  # admin 라도 무시되어야 함
        primary=[REPO_BAEMIN],
        is_admin=True,
    )
    eng = _make_engine_with_agent_context(ctx, is_admin=True)
    sess = _make_session()

    out = eng._enrich_plan_tool_args(
        {"query": "x"}, sess, tool_name="kms_rag.search"
    )
    assert "repo_ids" not in out


def test_enrich_no_agent_context_default_chat():
    """agent_context=None (default chat) 시 옛 동작 그대로 — repo inject 없음."""
    eng = _make_engine_with_agent_context(None)
    sess = _make_session()

    out = eng._enrich_plan_tool_args(
        {"query": "x"}, sess, tool_name="kms_rag.search"
    )
    assert "repo_ids" not in out


def test_enrich_other_tool_not_affected():
    """tool_name != kms_rag.search 면 isolation inject 무관 (예: web.search)."""
    ctx = _make_agent_context(
        isolation="strict",
        primary=[REPO_BAEMIN],
    )
    eng = _make_engine_with_agent_context(ctx)
    sess = _make_session()

    out = eng._enrich_plan_tool_args(
        {"query": "x"}, sess, tool_name="web.search"
    )
    assert "repo_ids" not in out


# ============================================================
# Layer 3 — 5 role agent end-to-end (mock SearchService)
# ============================================================


@pytest.mark.asyncio
async def test_five_role_agents_each_isolates_to_own_repo():
    """5 role agent 시뮬레이션 — 각자 자기 repo 만 args 로 보냄."""
    role_specs = [
        ("baemin",     REPO_BAEMIN),
        ("homeshop",   uuid4()),
        ("kbsoldier",  uuid4()),
        ("musinsa",    REPO_MUSINSA),
        ("samchully",  REPO_SAMCHULLY),
    ]

    for name, own_repo in role_specs:
        ctx = _make_agent_context(isolation="strict", primary=[own_repo])
        eng = _make_engine_with_agent_context(ctx)
        sess = _make_session()

        out = eng._enrich_plan_tool_args(
            # LLM 이 어떤 repo 도 명시 안 한 baseline 호출.
            {"query": f"{name} 매뉴얼 어디 있어"},
            sess,
            tool_name="kms_rag.search",
        )
        assert out["repo_ids"] == [str(own_repo)], (
            f"{name} agent leaked: got {out['repo_ids']}"
        )
        assert out["enforce_repo_ids"] is True


@pytest.mark.asyncio
async def test_kms_rag_tool_with_strict_inject_calls_search_with_filter():
    """integration — strict agent 의 inject 후 KMSRagTool 이 SearchRequest 에 전파."""
    fake_svc = AsyncMock()
    fake_svc.search = AsyncMock(return_value=_FakeResponse([]))

    ctx = _make_agent_context(isolation="strict", primary=[REPO_MUSINSA])
    eng = _make_engine_with_agent_context(ctx)
    sess = _make_session()

    enriched = eng._enrich_plan_tool_args(
        {"query": "무신사 배송"}, sess, tool_name="kms_rag.search"
    )

    with patch(
        "src.search.factory.create_search_service",
        AsyncMock(return_value=fake_svc),
    ):
        tool = KMSRagTool()
        await tool(enriched)

    req = fake_svc.search.await_args.kwargs["request"]
    assert req.repository_ids == [REPO_MUSINSA]
    assert req.enforce_repository_ids is True
