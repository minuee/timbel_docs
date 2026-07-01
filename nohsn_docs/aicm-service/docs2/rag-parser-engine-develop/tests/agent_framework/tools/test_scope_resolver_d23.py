"""D23 §3 — _TOOL_SUPPORTS_AGENT_ID + tool_supports_agent_id() 테스트.

GPT-5 phase 0 R4 GO 명시 — registry alignment unit test.
"""
from __future__ import annotations

import pytest

from src.agent_framework.tools import scope_resolver
from src.agent_framework.tools.scope_resolver import (
    _TOOL_DEFAULT_SCOPES,
    _TOOL_SUPPORTS_AGENT_ID,
    get_default_scope,
    is_promotion,
    resolve_tool_scope,
    tool_supports_agent_id,
)


def test_supports_set_is_frozen() -> None:
    """immutable — runtime mutation 차단."""
    assert isinstance(_TOOL_SUPPORTS_AGENT_ID, frozenset)


def test_supports_helper_schedule() -> None:
    assert tool_supports_agent_id("schedule.create") is True
    assert tool_supports_agent_id("schedule.list") is True
    assert tool_supports_agent_id("schedule.update") is True
    assert tool_supports_agent_id("schedule.delete") is True


def test_supports_helper_memo() -> None:
    for verb in ("create", "list", "update", "delete", "complete"):
        assert tool_supports_agent_id(f"memo.{verb}") is True


def test_supports_helper_expense() -> None:
    for verb in ("create", "list", "sum_by_category", "delete", "update"):
        assert tool_supports_agent_id(f"expense.{verb}") is True


def test_supports_helper_diary() -> None:
    assert tool_supports_agent_id("diary.save") is True
    assert tool_supports_agent_id("diary.search") is True
    assert tool_supports_agent_id("diary.delete") is True


def test_supports_helper_reminder() -> None:
    assert tool_supports_agent_id("reminder.schedule") is True
    assert tool_supports_agent_id("reminder.list") is True
    assert tool_supports_agent_id("reminder.cancel") is True


def test_supports_helper_kms_save() -> None:
    assert tool_supports_agent_id("note.save_research") is True
    assert tool_supports_agent_id("kms.save_research") is True


def test_supports_helper_excludes_user_scope_tools() -> None:
    """user / tenant scope 도구는 inject 안 함 (보수적)."""
    # mail.send 는 user scope — agent scope 아님
    assert tool_supports_agent_id("mail.send") is False
    # stock.quote 는 tenant — 시장 데이터
    assert tool_supports_agent_id("stock.quote") is False
    # web.search 는 tenant
    assert tool_supports_agent_id("web.search") is False


def test_supports_helper_unknown_tool() -> None:
    """unknown tool 은 fallback 'agent' scope 라도 inject 안 함."""
    assert tool_supports_agent_id("unknown.tool") is False
    assert tool_supports_agent_id("malicious_tool_name") is False
    # default scope 가 'agent' 인 미등록 도구 — inject 안 함 (보수적).
    assert get_default_scope("malicious_tool_name") == "agent"
    assert tool_supports_agent_id("malicious_tool_name") is False


def test_all_supports_keys_have_default_scope_agent() -> None:
    """_TOOL_SUPPORTS_AGENT_ID 의 모든 키는 default_scope='agent' 여야 함.

    (효과적으로 inject 작동하려면 effective_scope=='agent' 필요. user/tenant 로
    default 인 도구를 supports set 에 넣으면 *agent override* 가 있어야만
    inject — 회귀 0 보장 안 됨.)
    """
    for tool_name in _TOOL_SUPPORTS_AGENT_ID:
        default = get_default_scope(tool_name)
        assert default == "agent", (
            f"{tool_name} 가 _TOOL_SUPPORTS_AGENT_ID 에 있지만 default_scope='{default}' — "
            f"agent 가 아니면 effective_scope=='agent' 보장 안 됨"
        )


def test_resolve_with_agent_default() -> None:
    """default agent 도구 + override 없음 → agent."""
    assert resolve_tool_scope(
        agent_overrides=None, tool_name="schedule.create"
    ) == "agent"
    assert resolve_tool_scope(
        agent_overrides={}, tool_name="memo.create"
    ) == "agent"


def test_resolve_with_session_override() -> None:
    """agent → session 하향 override (정당)."""
    assert resolve_tool_scope(
        agent_overrides={"memo.create": "session"}, tool_name="memo.create"
    ) == "session"


def test_is_promotion_blocks_agent_to_tenant() -> None:
    """agent → tenant 는 승격 (차단 대상)."""
    assert is_promotion(default="agent", override="tenant") is True
    assert is_promotion(default="agent", override="user") is True


def test_is_promotion_allows_agent_to_session() -> None:
    """agent → session 은 하향 (허용)."""
    assert is_promotion(default="agent", override="session") is False
    assert is_promotion(default="agent", override="agent") is False


def test_supports_set_count() -> None:
    """현재 등록 도구 수 — 회귀 detection.

    D26 (2026-05-08): schedule.delete_all/delete_duplicates/availability/suggest_slots
    추가 (GPT-5 phase0 risk #2 권고) → 22 + 4 = 26.
    """
    # 4 schedule core + 4 schedule helper (D26) + 5 memo + 5 expense + 3 diary
    # + 3 reminder + 2 kms.save = 26
    assert len(_TOOL_SUPPORTS_AGENT_ID) == 26
