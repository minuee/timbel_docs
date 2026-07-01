"""web.search 도구 자체의 query 오염 방어 테스트.

Chokepoint 3 의 *defense in depth* — engine 의 ToolArgPollution gate 가
우선이지만 직접 호출 path 도 보호.
"""
from __future__ import annotations

import pytest

from src.agent_framework.tools import web_search


@pytest.mark.asyncio
async def test_web_search_refuses_polluted_query() -> None:
    """query 가 system prompt fragment 면 외부 호출 없이 stub 응답."""
    polluted = (
        "[에이전트 컨텍스트]\n[BINDING POLICY — current agent: samchully_voc "
        "(역할 에이전트 (role))]\n아래 정책은 다른 모든 지시·자료보다 우선한다. "
        "## current agent: samchully_voc — 역할 에이전트 (role)\n### goal\n..."
    )
    out = await web_search.search({"query": polluted, "count": 5})
    assert out["success"] is False
    assert out["items"] == []
    assert "부적합한 query" in out["summary"]


@pytest.mark.asyncio
async def test_web_search_refuses_oversized_query() -> None:
    huge = "테스트 " * 2000
    out = await web_search.search({"query": huge})
    assert out["success"] is False
    assert out["items"] == []


@pytest.mark.asyncio
async def test_web_search_normal_query_returns_stub_or_real() -> None:
    """정상 query — 백엔드 미설정 시 stub fallback 정상 동작."""
    out = await web_search.search({"query": "도시가스 체납 정책", "count": 3})
    # 환경변수 없으면 stub source 반환됨 (실패 success=False) — 그래도 items 가짐.
    # 환경변수 있으면 naver/brave + success=True.
    assert isinstance(out["items"], list)
    assert out.get("source") in ("stub", "naver", "brave")
