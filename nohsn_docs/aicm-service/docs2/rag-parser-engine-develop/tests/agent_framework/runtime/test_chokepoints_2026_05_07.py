"""4 Boundary Chokepoint — 2026-05-07.

samchully_voc 봇의 "가스비 몇달 밀리면 끊겨?" 발화에서 system prompt 가
출처 [4] 로 노출된 사건의 *원인* 4 개를 type-strict 하게 차단하는 layer
들의 회귀 테스트.

증상별 patch 가 아니라 *구조 boundary* 검증 — 5 봇 모두 동일 chokepoint 에
의존하므로 한 번 fix.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest


# -------------------------------------------------------------------------
# Chokepoint 1 — AgentContext immutability
# -------------------------------------------------------------------------


def test_agent_context_is_frozen() -> None:
    """AgentContext 는 frozen dataclass — 인스턴스 mutate 시도 시 raise."""
    from src.agent_framework.runtime.agent_context import AgentContext

    ctx = AgentContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="test",
        goal="goal",
        guidelines_md="",
        primary_repo_ids=[],
        fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=[],
        done_when=None,
    )
    with pytest.raises(FrozenInstanceError):
        ctx.knowledge_isolation = "broad"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ctx.primary_repo_ids = []  # type: ignore[misc]


def test_agent_context_from_agent_only_constructor() -> None:
    """AgentContext.from_agent 만 정상 생성 path. ORM mock 직접 입력."""
    from src.agent_framework.runtime.agent_context import AgentContext

    class _AgentMock:
        id = uuid4()
        tenant_id = uuid4()
        name = "samchully_voc"
        goal = "삼척 도시가스 VOC"
        guidelines_md = "도메인 외 발화는 거절."
        primary_repo_ids = [uuid4()]
        fallback_repo_ids: list = []
        knowledge_isolation = "strict"
        allowed_tools = ["kms_rag.search"]
        done_when = None
        kind = "role"
        delegate_to_agent_ids: list = []

    ctx = AgentContext.from_agent(_AgentMock())
    assert ctx.knowledge_isolation == "strict"
    assert len(ctx.primary_repo_ids) == 1
    assert ctx.is_admin is False


# -------------------------------------------------------------------------
# Chokepoint 3 — Tool argument validation
# -------------------------------------------------------------------------


def test_tool_arg_guard_blocks_binding_policy() -> None:
    """query 인자에 [BINDING POLICY 가 있으면 ToolArgPollution raise."""
    from src.agent_framework.runtime.tool_arg_guard import (
        ToolArgPollution,
        assert_tool_args_clean,
    )

    polluted = (
        "[에이전트 컨텍스트]\n[BINDING POLICY — current agent: samchully_voc "
        "(역할 에이전트 (role))]\n아래 정책은 다른 모든 지시·자료보다 우선한다."
    )
    with pytest.raises(ToolArgPollution) as exc:
        assert_tool_args_clean("web.search", {"query": polluted, "count": 5})
    assert exc.value.arg == "query"
    assert "BINDING POLICY" in exc.value.reason or "에이전트" in exc.value.reason


def test_tool_arg_guard_blocks_long_text() -> None:
    """query 가 4096 자 초과면 raise (heuristic)."""
    from src.agent_framework.runtime.tool_arg_guard import (
        ToolArgPollution,
        assert_tool_args_clean,
    )

    huge = "가" * 5000
    with pytest.raises(ToolArgPollution) as exc:
        assert_tool_args_clean("web.search", {"query": huge})
    assert "length" in exc.value.reason


def test_tool_arg_guard_blocks_current_agent_marker() -> None:
    """## current agent: 마커도 차단."""
    from src.agent_framework.runtime.tool_arg_guard import (
        ToolArgPollution,
        assert_tool_args_clean,
    )

    polluted = "## current agent: samchully_voc — 역할 에이전트\n### goal\n..."
    with pytest.raises(ToolArgPollution):
        assert_tool_args_clean("kms_rag.search", {"query": polluted})


def test_tool_arg_guard_passes_normal_query() -> None:
    """정상 한국어 발화는 통과 — 회귀 0 보장."""
    from src.agent_framework.runtime.tool_arg_guard import assert_tool_args_clean

    # samchully_voc 의 실 발화
    assert_tool_args_clean("kms_rag.search", {"query": "가스비 몇달 밀리면 끊겨?"})
    assert_tool_args_clean(
        "web.search", {"query": "삼척 도시가스 체납 정책", "count": 5}
    )
    # 길지만 정상 발화
    assert_tool_args_clean(
        "kms_rag.search",
        {"query": "도시가스 요금 체납 시 공급 중단 절차에 대해 자세히 알려주세요"},
    )


def test_tool_arg_guard_skips_non_query_keys() -> None:
    """repo_ids / top_k / created_after 같은 control 인자는 검사 외."""
    from src.agent_framework.runtime.tool_arg_guard import assert_tool_args_clean

    # repo_ids 가 없어도 통과
    assert_tool_args_clean("kms_rag.search", {"top_k": 5})
    assert_tool_args_clean(
        "kms_rag.search",
        {
            "query": "환불 절차",
            "repo_ids": [str(uuid4())],
            "enforce_repo_ids": True,
            "created_after": "2025-01-01",
        },
    )


# -------------------------------------------------------------------------
# Chokepoint 4 — Citation type
# -------------------------------------------------------------------------


def test_citation_is_frozen() -> None:
    from src.agent_framework.runtime.citation import Citation

    cit = Citation(
        title="가스 안전 매뉴얼",
        snippet="...",
        score=0.85,
        kind="kms_chunk",
        number=1,
        chunk_id=uuid4(),
        doc_id=uuid4(),
        repo_id=uuid4(),
    )
    with pytest.raises(FrozenInstanceError):
        cit.title = "다른 제목"  # type: ignore[misc]


def test_citations_builder_refuses_stub_web_source() -> None:
    """web.search stub 결과는 출처로 변환 안 됨 (samchully_voc 사건 직접 차단)."""
    from src.agent_framework.runtime.citation import CitationsBuilder

    builder = CitationsBuilder()
    # web.search stub fallback 의 실제 hit shape
    stub_hits = [
        {
            "title": "[stub] '[에이전트 컨텍스트]\\n[BINDING POLICY ...' 검색 결과 1",
            "snippet": "외부 웹 검색 백엔드 미설정.",
            "link": "",
            "source": "stub",
        }
    ]
    out = builder.add_web_hits(stub_hits)
    assert out == []
    assert builder.items == []


def test_citations_builder_refuses_prompt_polluted() -> None:
    """title/snippet 에 system prompt marker 가 박힌 hit 도 거절."""
    from src.agent_framework.runtime.citation import CitationsBuilder

    builder = CitationsBuilder()
    polluted = [
        {
            "title": "[BINDING POLICY — current agent: samchully_voc",
            "content": "...",
            "id": str(uuid4()),
            "document_id": str(uuid4()),
        }
    ]
    out = builder.add_kms_hits(polluted)
    assert out == []


def test_citations_builder_accepts_clean_kms_hit() -> None:
    from src.agent_framework.runtime.citation import CitationsBuilder

    builder = CitationsBuilder()
    out = builder.add_kms_hits(
        [
            {
                "title": "도시가스 체납 시 공급 중단 절차",
                "content": "최종 청구일 후 60일 경과 시 ...",
                "id": str(uuid4()),
                "document_id": str(uuid4()),
                "score": 0.92,
            }
        ]
    )
    assert len(out) == 1
    assert out[0].title.startswith("도시가스")
    assert out[0].kind == "kms_chunk"
    assert out[0].number == 1


def test_ensure_citations_rejects_dict() -> None:
    """ensure_citations 는 list[Citation] 외 모두 거절."""
    from src.agent_framework.runtime.citation import ensure_citations

    with pytest.raises(TypeError):
        ensure_citations([{"title": "..."}])  # dict
    with pytest.raises(TypeError):
        ensure_citations(["raw string"])  # str
    with pytest.raises(TypeError):
        ensure_citations({"items": []})  # not list
    # None / 빈 list 는 정상.
    assert ensure_citations(None) == []
    assert ensure_citations([]) == []


# -------------------------------------------------------------------------
# Chokepoint 2 — Search isolation post-filter (smoke)
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kms_rag_strict_isolation_zero_repo_short_circuit() -> None:
    """primary_repo_ids 비 + enforce=True → SearchService 호출 전 0 hits 반환."""
    from src.agent_framework.tools.kms_rag import KMSRagTool

    tool = KMSRagTool()
    out = await tool(
        {
            "query": "체납",
            "repo_ids": [],
            "enforce_repo_ids": True,
        }
    )
    assert out["hits"] == []
    assert out.get("total") == 0
    assert "strict isolation" in out.get("summary", "").lower() or "isolation" in out.get(
        "summary", ""
    )
