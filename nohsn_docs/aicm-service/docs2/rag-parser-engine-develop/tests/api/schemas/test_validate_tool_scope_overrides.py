"""D23 §2 verify (D29 §1) — _validate_tool_scope_overrides 단위 test.

agents.tool_scope_overrides Pydantic validator (`src/api/schemas/agent.py`)
가 (1) 승격 차단 (2) 크기 상한 (3) 알 수 없는 scope 거부 (4) 잘못된 입력
거부 contract 를 만족하는지 검증.

D29 §1 결정 (2026-05-08): UI 노출 보류 (power-user feature, 운영 risk),
서버 validator 만 enforcement layer 로 사용. 본 test 가 enforcement 의
contract 보장.
"""
from __future__ import annotations

import pytest

from src.api.schemas.agent import _validate_tool_scope_overrides


# ---------------------------------------------------------------------------
# Valid path
# ---------------------------------------------------------------------------


def test_none_returns_empty_dict():
    assert _validate_tool_scope_overrides(None) == {}


def test_empty_dict_returns_empty_dict():
    assert _validate_tool_scope_overrides({}) == {}


def test_valid_session_override_for_agent_default():
    """memo.create default = agent → session 으로 하향 OK."""
    result = _validate_tool_scope_overrides({"memo.create": "session"})
    assert result == {"memo.create": "session"}


def test_valid_agent_override_for_user_default():
    """mail.send default = user → agent 로 하향 OK (좁은 scope)."""
    result = _validate_tool_scope_overrides({"mail.send": "agent"})
    assert result == {"mail.send": "agent"}


def test_valid_same_scope_keep_default():
    """memo.create default = agent → agent 그대로 — equal OK."""
    result = _validate_tool_scope_overrides({"memo.create": "agent"})
    assert result == {"memo.create": "agent"}


def test_valid_session_override_for_tenant_default():
    """kms_rag.search default = tenant → session 하향 OK."""
    result = _validate_tool_scope_overrides({"kms_rag.search": "session"})
    assert result == {"kms_rag.search": "session"}


# ---------------------------------------------------------------------------
# Promotion rejection (핵심 보안)
# ---------------------------------------------------------------------------


def test_reject_promotion_agent_to_tenant():
    """memo.create default = agent → tenant 승격 차단."""
    with pytest.raises(ValueError, match="cannot promote"):
        _validate_tool_scope_overrides({"memo.create": "tenant"})


def test_reject_promotion_session_to_agent_for_session_tool():
    """미등록 도구는 fallback 'agent' default — 그러므로 session→agent 는 승격이 아니라 동등."""
    # unknown.tool default = 'agent' fallback
    # 'agent' 그대로 두는 건 OK
    result = _validate_tool_scope_overrides({"unknown.tool": "agent"})
    assert result == {"unknown.tool": "agent"}
    # session 으로 하향도 OK
    result = _validate_tool_scope_overrides({"unknown.tool": "session"})
    assert result == {"unknown.tool": "session"}


def test_reject_promotion_agent_to_user_for_memo():
    """memo.create default = agent → user 승격 차단."""
    with pytest.raises(ValueError, match="cannot promote"):
        _validate_tool_scope_overrides({"memo.create": "user"})


def test_reject_promotion_user_to_tenant_for_mail():
    """mail.send default = user → tenant 승격 차단."""
    with pytest.raises(ValueError, match="cannot promote"):
        _validate_tool_scope_overrides({"mail.send": "tenant"})


# ---------------------------------------------------------------------------
# Invalid scope values
# ---------------------------------------------------------------------------


def test_reject_invalid_scope_string():
    with pytest.raises(ValueError, match="invalid scope"):
        _validate_tool_scope_overrides({"memo.create": "admin"})


def test_reject_non_string_scope():
    with pytest.raises(ValueError, match="invalid scope"):
        _validate_tool_scope_overrides({"memo.create": 4})  # type: ignore[dict-item]


def test_reject_empty_tool_name():
    with pytest.raises(ValueError, match="invalid tool key"):
        _validate_tool_scope_overrides({"": "agent"})


def test_reject_non_string_tool_key():
    with pytest.raises(ValueError, match="invalid tool key"):
        _validate_tool_scope_overrides({123: "agent"})  # type: ignore[dict-item]


def test_reject_non_dict_input():
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_tool_scope_overrides("memo.create=agent")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------


def test_reject_too_many_keys():
    """200 키 상한 — DoS 방지."""
    overrides = {f"tool_{i}.create": "agent" for i in range(201)}
    with pytest.raises(ValueError, match="too many keys"):
        _validate_tool_scope_overrides(overrides)


def test_accept_max_keys_boundary():
    """200 키 정확히 — boundary OK (단, 16KB 안)."""
    overrides = {f"tool_{i}.x": "agent" for i in range(200)}
    # 16KB 직렬화 검증 — 짧은 키 200 = 약 4KB ≤ 16KB
    result = _validate_tool_scope_overrides(overrides)
    assert len(result) == 200


def test_reject_too_large_serialized():
    """16KB 상한 — 긴 키 적은 수도 거부."""
    long_key = "x" * 200
    overrides = {f"{long_key}_{i}.create": "agent" for i in range(100)}
    with pytest.raises(ValueError, match="too large"):
        _validate_tool_scope_overrides(overrides)


# ---------------------------------------------------------------------------
# Mixed scenarios
# ---------------------------------------------------------------------------


def test_multiple_valid_overrides():
    """여러 override 동시 — 모두 valid."""
    result = _validate_tool_scope_overrides({
        "memo.create": "session",
        "mail.send": "agent",
        "kms_rag.search": "user",
    })
    assert result == {
        "memo.create": "session",
        "mail.send": "agent",
        "kms_rag.search": "user",
    }


def test_first_promotion_rejects_all():
    """한 promote 가 있으면 전체 reject."""
    with pytest.raises(ValueError, match="cannot promote"):
        _validate_tool_scope_overrides({
            "memo.create": "session",  # OK
            "memo.update": "tenant",   # 승격
            "memo.delete": "agent",    # OK
        })
