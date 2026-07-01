"""Unit tests for AgentContext (Phase 1 Task 4)."""
import pytest
from uuid import uuid4
from unittest.mock import MagicMock
from src.agent_framework.runtime.agent_context import AgentContext


def test_from_agent_basic():
    agent = MagicMock()
    agent.id = uuid4()
    agent.tenant_id = uuid4()
    agent.name = "병원 상담"
    agent.goal = "예약 완수"
    agent.guidelines_md = "## rules\n존댓말 사용"
    agent.primary_repo_ids = [uuid4()]
    agent.fallback_repo_ids = []
    agent.knowledge_isolation = "priority"
    agent.allowed_tools = ["schedule.create", "kms_rag.search"]
    agent.done_when = "schedule.create ok"
    agent.kind = "role"

    ctx = AgentContext.from_agent(agent)
    assert ctx.agent_id == agent.id
    assert ctx.name == "병원 상담"
    assert ctx.knowledge_isolation == "priority"
    assert "schedule.create" in ctx.allowed_tools
    assert ctx.kind == "role"
    assert ctx.is_admin is False


def test_from_agent_handles_none_lists():
    agent = MagicMock()
    agent.id = uuid4()
    agent.tenant_id = uuid4()
    agent.name = "x"
    agent.goal = "y"
    agent.guidelines_md = "z"
    agent.primary_repo_ids = None
    agent.fallback_repo_ids = None
    agent.knowledge_isolation = None
    agent.allowed_tools = None
    agent.done_when = None
    agent.kind = None  # 058 — 누락 시 'role' fallback

    ctx = AgentContext.from_agent(agent)
    assert ctx.primary_repo_ids == []
    assert ctx.fallback_repo_ids == []
    assert ctx.knowledge_isolation == "priority"
    assert ctx.allowed_tools == []
    assert ctx.kind == "role"
    assert ctx.is_admin is False


def test_from_agent_admin_kind():
    """058 — kind='admin' 인 agent → is_admin True."""
    agent = MagicMock()
    agent.id = uuid4()
    agent.tenant_id = uuid4()
    agent.name = "Locus 어시스턴트"
    agent.goal = "사용자의 일상 지원"
    agent.guidelines_md = "친절히"
    agent.primary_repo_ids = []
    agent.fallback_repo_ids = []
    agent.knowledge_isolation = "priority"
    agent.allowed_tools = ["mail.send", "schedule.list"]
    agent.done_when = None
    agent.kind = "admin"

    ctx = AgentContext.from_agent(agent)
    assert ctx.kind == "admin"
    assert ctx.is_admin is True


def test_to_prompt_section_contains_all_fields():
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="병원", goal="예약 완수",
        guidelines_md="## rules\n존댓말",
        primary_repo_ids=[uuid4()], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=["schedule.create"],
        done_when="schedule.create ok",
        kind="role",
    )
    text = ctx.to_prompt_section()
    assert "## current agent" in text
    assert "병원" in text
    assert "예약 완수" in text
    assert "존댓말" in text
    assert "schedule.create" in text
    assert "schedule.create ok" in text
    # 058 — kind 라벨이 prompt 에 노출.
    assert "역할 에이전트 (role)" in text


def test_to_prompt_section_admin_label():
    """058 — admin agent prompt 는 'admin' 라벨 포함."""
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="Locus", goal="사용자 비서",
        guidelines_md="all enabled",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=["mail.send"], done_when=None,
        kind="admin",
    )
    text = ctx.to_prompt_section()
    assert "admin" in text
    assert "어시스턴트 본인" in text


def test_to_prompt_section_empty_tools():
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="x", goal="y", guidelines_md="z",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None,
    )
    text = ctx.to_prompt_section()
    assert "전체 카탈로그" in text  # allowed_tools 비었을 때 안내
    assert "LLM 이 자율 판정" in text  # done_when 비었을 때


def test_to_binding_policy_block_extracts_guidelines():
    """OOS-policy fix (2026-05-07) — guidelines_md 가 [BINDING POLICY] block 으로
    추출. role agent 의 도메인 외 발화 정책이 LLM 에 *최우선* 적용되도록.
    """
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="KB 장병내일적금 상담", goal="가입 안내",
        guidelines_md=(
            "## 역할\n장병내일적금 안내만 응대.\n\n"
            "## 도메인 외 발화 정책\n무관 발화 거절."
        ),
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=["kms_rag.search"], done_when=None, kind="role",
    )
    block = ctx.to_binding_policy_block()
    assert block, "binding policy block 이 비어 있으면 안 된다"
    assert "[BINDING POLICY" in block
    assert "[/BINDING POLICY]" in block
    assert "KB 장병내일적금" in block
    assert "도메인 외 발화 정책" in block
    # 자동 OOS guard 한 줄 강제 inject (guidelines_md 안에 정책 있어도 추가).
    assert "도메인 외" in block or "도메인·역할과 무관" in block


def test_to_binding_policy_block_empty_returns_empty():
    """OOS-policy fix — guidelines_md 비어 있으면 binding block 도 빈 문자열.
    회귀 0 보장 (default chat / agent_context 미설정 path 와 시각 동일).
    """
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="x", goal="y", guidelines_md="",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None, kind="role",
    )
    assert ctx.to_binding_policy_block() == ""


def test_to_prompt_section_binding_policy_prepended():
    """OOS-policy fix — to_prompt_section 의 [BINDING POLICY] 가 ## current agent
    섹션 *위* 에 prepend 됨. plan_orchestrator system prompt 에서 LLM 이 정책을
    *먼저* 본다.
    """
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="병원", goal="예약",
        guidelines_md="## 도메인 외\n타 도메인 거절",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=["schedule.create"], done_when=None, kind="role",
    )
    text = ctx.to_prompt_section()
    binding_idx = text.find("[BINDING POLICY")
    section_idx = text.find("## current agent")
    assert binding_idx != -1
    assert section_idx != -1
    assert binding_idx < section_idx, (
        "[BINDING POLICY] 는 ## current agent 보다 앞에 위치해야 한다"
    )


def test_to_prompt_section_no_guidelines_no_binding():
    """guidelines_md 비면 [BINDING POLICY] 자체 없음 (회귀 0)."""
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="x", goal="y", guidelines_md="",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None, kind="role",
    )
    text = ctx.to_prompt_section()
    assert "[BINDING POLICY" not in text
    assert "## current agent" in text


def test_to_binding_policy_block_sop_rag_mode_drops_full_guidelines():
    """R6 (2026-05-07) — sop_rag_mode=True 면 guidelines_md 본문이 prepend 안 됨.
    SOP RAG layer 가 [SOP CONTEXT] 로 별도 inject. system prompt 길이 단축.
    """
    long_guidelines = "## 절차\n" + ("매우 긴 정책 본문 " * 200)
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="KB 장병", goal="적금 가입 안내",
        guidelines_md=long_guidelines,
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="strict",
        allowed_tools=["kms_rag.search"], done_when=None, kind="role",
    )
    block_default = ctx.to_binding_policy_block()
    block_sop = ctx.to_binding_policy_block(sop_rag_mode=True)
    # default path 는 본문 (긴 정책) 포함.
    assert "매우 긴 정책 본문" in block_default
    # sop_rag_mode 는 본문 제거 — agent 정체성 + OOS guard 만.
    assert "매우 긴 정책 본문" not in block_sop
    assert "[BINDING POLICY" in block_sop
    assert "[SOP CONTEXT]" in block_sop  # SOP context inject 안내 포함.
    # 길이 단축 확인 — 최소 50% 이상 짧아야.
    assert len(block_sop) < len(block_default) * 0.5


def test_immutable_frozen():
    ctx = AgentContext(
        agent_id=uuid4(), tenant_id=uuid4(),
        name="x", goal="y", guidelines_md="z",
        primary_repo_ids=[], fallback_repo_ids=[],
        knowledge_isolation="priority",
        allowed_tools=[], done_when=None,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        ctx.name = "changed"  # type: ignore
