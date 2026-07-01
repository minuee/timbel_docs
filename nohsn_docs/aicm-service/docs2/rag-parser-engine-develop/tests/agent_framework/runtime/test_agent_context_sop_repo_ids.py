"""D84 P1 — AgentContext.sop_repo_ids round-trip.

DB 컬럼 + AgentOut + AgentPatch 는 모두 sop_repo_ids 를 처리하는데
AgentContext.from_agent 만 매핑 누락이었던 silent drop 회귀를 차단.
"""

from types import SimpleNamespace
from uuid import uuid4

from src.agent_framework.runtime.agent_context import AgentContext


def _fake_agent(sop_ids=None, has_sop_attr: bool = True, **overrides):
    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "name": "t",
        "goal": "g",
        "guidelines_md": "",
        "primary_repo_ids": [],
        "fallback_repo_ids": [],
        "knowledge_isolation": "priority",
        "allowed_tools": [],
        "done_when": None,
        "kind": "role",
        "delegate_to_agent_ids": [],
        "web_search_mode": "off",
        "oos_keywords": [],
    }
    if has_sop_attr:
        base["sop_repo_ids"] = sop_ids
    base.update(overrides)
    return SimpleNamespace(**base)


def test_sop_repo_ids_passes_through():
    ids = [uuid4(), uuid4()]
    ctx = AgentContext.from_agent(_fake_agent(sop_ids=ids))
    assert list(ctx.sop_repo_ids) == ids


def test_sop_repo_ids_none_becomes_empty():
    ctx = AgentContext.from_agent(_fake_agent(sop_ids=None))
    assert ctx.sop_repo_ids == []


def test_sop_repo_ids_empty_list_preserved():
    ctx = AgentContext.from_agent(_fake_agent(sop_ids=[]))
    assert ctx.sop_repo_ids == []


def test_sop_repo_ids_absent_attr_safe():
    # 일부 테스트 fixture 에 sop_repo_ids 자체가 없을 수 있음.
    fake = _fake_agent(has_sop_attr=False)
    ctx = AgentContext.from_agent(fake)
    assert ctx.sop_repo_ids == []
