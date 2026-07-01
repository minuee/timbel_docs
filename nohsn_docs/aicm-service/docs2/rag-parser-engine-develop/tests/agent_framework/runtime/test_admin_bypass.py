"""058 admin bypass — plan_orchestrator + engine.

핵심 회귀:
 1. admin agent (Locus 어시스턴트) 의 plan_orchestrator 호출은 카테고리별
    7-tool subset 이 아닌 agent.allowed_tools (예: 20개) 그대로 사용.
 2. role agent / agent_context=None 은 기존 동작 그대로 — 카테고리 subset.
 3. validate_plan_tools 가 admin 일 때 extra_allowed 로 admin 전체 도구 허용.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.runtime.agent_context import AgentContext
from src.agent_framework.runtime.plan_orchestrator import PlanOrchestrator
from src.agent_framework.runtime.plan_router import validate_plan_tools, MAIL


def _admin_ctx(allowed_tools: list[str] | None = None) -> AgentContext:
    return AgentContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="Locus 어시스턴트",
        goal="사용자 일상 지원",
        guidelines_md="모든 도구 사용 가능",
        primary_repo_ids=[],
        fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=allowed_tools or [
            "kms_rag.search", "web.search", "web.fetch",
            "schedule.create", "schedule.list", "schedule.delete",
            "mail.search", "mail.send", "mail.compose",
            "memo.save", "diary.save", "sms.send",
            "expense.add", "expense.list",
            "doc.draft", "doc.summarize",
            "weather.lookup", "news.search", "stock.predict",
        ],
        done_when=None,
        kind="admin",
    )


def _role_ctx() -> AgentContext:
    return AgentContext(
        agent_id=uuid4(),
        tenant_id=uuid4(),
        name="병원 상담봇",
        goal="예약 처리",
        guidelines_md="존댓말",
        primary_repo_ids=[],
        fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=["schedule.create"],
        done_when=None,
        kind="role",
    )


def test_admin_validate_extra_allowed_admits_full_catalog():
    """validate_plan_tools 의 extra_allowed 인자가 admin 의 전체 도구 통과시킴.

    카테고리 = SCHEDULE 인데 admin agent 가 mail.compose / news.search 같은
    도메인 외 도구 호출하려 해도 admin extra_allowed 에 있으면 통과.
    """
    from src.agent_framework.runtime.plan_orchestrator import PlanStep

    plan = [
        PlanStep(step=1, kind="tool", raw={"tool": "mail.compose", "args": {}}),
        PlanStep(step=2, kind="tool", raw={"tool": "news.search", "args": {}}),
    ]
    admin = _admin_ctx()
    valid, invalid = validate_plan_tools(
        plan, "schedule",
        extra_allowed=list(admin.allowed_tools),
    )
    assert invalid == []
    assert len(valid) == 2


def test_role_validate_blocks_outside_category():
    """role agent 에 extra_allowed 미주입 시 카테고리 외 도구 차단."""
    from src.agent_framework.runtime.plan_orchestrator import PlanStep

    plan = [
        PlanStep(step=1, kind="tool", raw={"tool": "mail.compose", "args": {}}),
    ]
    valid, invalid = validate_plan_tools(plan, "schedule")
    assert invalid == ["mail.compose"]
    assert valid == []


def test_admin_context_is_admin():
    ctx = _admin_ctx()
    assert ctx.is_admin is True
    assert ctx.kind == "admin"


def test_role_context_not_admin():
    ctx = _role_ctx()
    assert ctx.is_admin is False
    assert ctx.kind == "role"


@pytest.mark.asyncio
async def test_plan_orchestrator_admin_uses_full_catalog():
    """admin agent 가 plan_orchestrator 에 주입되면 LLM 에 전달되는 available_tools
    는 카테고리 subset 이 아닌 agent.allowed_tools (20 개) 그대로.

    LLM 호출 인자 inspect 로 검증.
    """
    captured: dict = {}

    class _StubLLM:
        async def complete(self, system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            # MAIL 카테고리 plan — mail.compose 사용.
            return json.dumps(
                {
                    "plan": [
                        {
                            "step": 1,
                            "kind": "tool",
                            "tool": "mail.compose",
                            "args": {"to": "test@example.com"},
                        },
                    ],
                    "ambiguity_reasons": [],
                    "summary": "메일 작성",
                }
            )

    orch = PlanOrchestrator(_StubLLM())
    admin = _admin_ctx()

    result = await orch.generate_plan(
        user_message="이번주 수요일 만나는거 가능한지 메일 보낼려구 초안 작성해줘",
        history=None,
        intents=["mail_send"],
        utterance_verb="log",
        utterance_domain="mail",
        agent_context=admin,
    )
    assert result is not None
    user_payload = json.loads(captured["user"])
    avail = user_payload.get("available_tools") or ""
    # admin 의 전체 도구가 LLM 에 노출돼야 함.
    assert "mail.compose" in avail
    assert "news.search" in avail
    assert "stock.predict" in avail
    # mail.compose step 이 validate 통과.
    assert any(
        s.kind == "tool" and (s.raw or {}).get("tool") == "mail.compose"
        for s in result.plan
    )


@pytest.mark.asyncio
async def test_plan_orchestrator_role_uses_category_subset():
    """role agent 또는 agent_context=None 이면 기존대로 카테고리 subset."""
    captured: dict = {}

    class _StubLLM:
        async def complete(self, system, user, **kwargs):
            captured["user"] = user
            return json.dumps(
                {
                    "plan": [
                        {
                            "step": 1,
                            "kind": "tool",
                            "tool": "schedule.create",
                            "args": {"title": "test"},
                        },
                    ],
                    "ambiguity_reasons": [],
                    "summary": "schedule",
                }
            )

    orch = PlanOrchestrator(_StubLLM())
    role = _role_ctx()

    result = await orch.generate_plan(
        user_message="내일 미팅 잡아줘",
        history=None,
        intents=["create_schedule"],
        utterance_verb="log",
        utterance_domain="schedule",
        agent_context=role,
    )
    assert result is not None
    user_payload = json.loads(captured["user"])
    avail = user_payload.get("available_tools") or ""
    # role 은 SCHEDULE 카테고리 subset — mail.compose 노출 안 됨.
    assert "schedule.create" in avail
    assert "mail.compose" not in avail
    assert "news.search" not in avail
