"""Engine `_enrich_plan_tool_args` direct tests — D23 §3 (agent_id inject) +
§7 L1 (admin null_owner sentinel) + D29 §0 patches (override skip + log redact).

GPT-5 6cb93d2 사후 verdict R2 (engine-level test 부재) 권고 patch.
사용자 절칙: 회귀 0 / sentinel contract 일관 / cross-tenant 방어.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.agent_framework.runtime.engine import AgentEngine
from src.agent_framework.storage.agent_document_store import (
    ADMIN_NULL_OWNER_OK,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal stubs (engine 의 의존성 회피).
# ---------------------------------------------------------------------------


def _make_engine_stub(
    *,
    agent_ctx=None,
    active_sender=None,
):
    """`_enrich_plan_tool_args` 만 호출 가능한 minimal AgentEngine 인스턴스.

    `_resolve_args` 는 raw dict 를 그대로 return 하도록 monkey-patch.
    """
    eng = AgentEngine.__new__(AgentEngine)
    eng._agent_context = agent_ctx  # type: ignore[attr-defined]
    eng._active_sender = active_sender  # type: ignore[attr-defined]

    # _resolve_args 가 sess + raw → dict[copy] return.
    def _resolve_args_stub(raw, sess):
        return dict(raw)

    eng._resolve_args = _resolve_args_stub  # type: ignore[method-assign]
    return eng


def _make_session_stub(*, tenant_id=None, account_id=None, phone=None):
    """SessionState minimal stub (effective_personal_tenant_id / identity / etc)."""
    return SimpleNamespace(
        tenant_id=tenant_id or uuid4(),
        effective_personal_tenant_id=None,
        identity={"phone": phone} if phone else None,
        account_id=account_id,
    )


def _make_agent_ctx(
    *,
    agent_id: UUID | str | None = None,
    is_admin: bool = False,
    tool_scope_overrides: dict | None = None,
):
    return SimpleNamespace(
        agent_id=agent_id,
        is_admin=is_admin,
        tool_scope_overrides=tool_scope_overrides or {},
    )


# ---------------------------------------------------------------------------
# §3 — agent_id server-side inject
# ---------------------------------------------------------------------------


def test_inject_overwrites_llm_payload_for_supported_tool():
    """attacker LLM 이 다른 agent_id 시도 → server 가 강제 덮어씀."""
    server_aid = uuid4()
    eng = _make_engine_stub(agent_ctx=_make_agent_ctx(agent_id=server_aid))
    sess = _make_session_stub()

    # LLM 가 attacker agent_id 시도
    attacker_aid = uuid4()
    out = eng._enrich_plan_tool_args(
        {"agent_id": str(attacker_aid), "title": "test"},
        sess,
        tool_name="schedule.create",
    )

    assert out["agent_id"] == str(server_aid), "server-side overwrite 실패 — cross-agent 격리 우회"
    assert out["title"] == "test"


def test_no_inject_when_agent_ctx_none():
    """REST CRUD path (agent_ctx None) → inject skip (회귀 0)."""
    eng = _make_engine_stub(agent_ctx=None)
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"title": "memo from rest"},
        sess,
        tool_name="memo.create",
    )

    assert "agent_id" not in out, "agent_ctx None 인데 inject 발생 — 회귀"


def test_no_inject_for_unknown_tool():
    """unknown tool — fallback 'agent' 라도 _TOOL_SUPPORTS_AGENT_ID 미등록 → skip."""
    server_aid = uuid4()
    eng = _make_engine_stub(agent_ctx=_make_agent_ctx(agent_id=server_aid))
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"q": "hello"},
        sess,
        tool_name="unknown_tool.do_something",
    )

    assert "agent_id" not in out, "unknown tool 에 inject — 보수적 default 위반"


def test_no_inject_when_override_to_session_for_supported_tool(capsys):
    """D29 §0 patch — agent_id-backed 도구 + non-agent override → skip + warning.

    structlog 가 stdout 으로 emit → capsys 로 capture.
    """
    server_aid = uuid4()
    eng = _make_engine_stub(
        agent_ctx=_make_agent_ctx(
            agent_id=server_aid,
            tool_scope_overrides={"memo.create": "session"},
        )
    )
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"title": "session-only memo"},
        sess,
        tool_name="memo.create",
    )

    assert "agent_id" not in out, "session override 인데 inject 발생 — D29 §0 patch 위반"
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert (
        "agent_id_backed_tool_non_agent_scope_skip" in combined
    ), f"warning event 발화 실패: out={captured.out!r} err={captured.err!r}"


# ---------------------------------------------------------------------------
# §7 L1 — admin null_owner sentinel
# ---------------------------------------------------------------------------


def test_pop_spoofed_admin_sentinel_for_non_admin():
    """non-admin LLM 이 _admin_null_owner_sentinel 직접 spoof → 항상 pop."""
    eng = _make_engine_stub(
        agent_ctx=_make_agent_ctx(agent_id=uuid4(), is_admin=False)
    )
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {
            "_admin_null_owner_sentinel": ADMIN_NULL_OWNER_OK,  # spoof 시도
            "title": "test",
        },
        sess,
        tool_name="memo.list",
    )

    assert "_admin_null_owner_sentinel" not in out, "spoof sentinel pop 실패 — 격리 우회"


def test_pop_spoofed_admin_sentinel_when_no_agent_ctx():
    """agent_ctx None 인 path 에서도 sentinel pop — 모든 path 보호."""
    eng = _make_engine_stub(agent_ctx=None)
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"_admin_null_owner_sentinel": ADMIN_NULL_OWNER_OK},
        sess,
        tool_name="memo.list",
    )

    assert "_admin_null_owner_sentinel" not in out


def test_admin_agent_converts_include_null_owner_to_sentinel():
    """admin agent 의 include_null_owner=True → sentinel 변환."""
    eng = _make_engine_stub(
        agent_ctx=_make_agent_ctx(agent_id=uuid4(), is_admin=True)
    )
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"include_null_owner": True},
        sess,
        tool_name="memo.list",
    )

    assert "include_null_owner" not in out, "include_null_owner pop 안 됨"
    assert out.get("_admin_null_owner_sentinel") is ADMIN_NULL_OWNER_OK, (
        "admin sentinel 변환 실패"
    )


def test_admin_sender_converts_include_null_owner_to_sentinel():
    """admin sender (test-chat) → sentinel 변환."""
    admin_sender = SimpleNamespace(is_admin=True)
    eng = _make_engine_stub(
        agent_ctx=_make_agent_ctx(agent_id=uuid4(), is_admin=False),
        active_sender=admin_sender,
    )
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"include_null_owner": True},
        sess,
        tool_name="memo.list",
    )

    assert out.get("_admin_null_owner_sentinel") is ADMIN_NULL_OWNER_OK


def test_non_admin_include_null_owner_denied(capsys):
    """non-admin path: bool True → pop + warning, sentinel 부재 (격리 유지)."""
    eng = _make_engine_stub(
        agent_ctx=_make_agent_ctx(agent_id=uuid4(), is_admin=False)
    )
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"include_null_owner": True},
        sess,
        tool_name="memo.list",
    )

    assert "include_null_owner" not in out
    assert "_admin_null_owner_sentinel" not in out
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert (
        "include_null_owner_denied_non_admin" in combined
    ), f"non-admin denial warning 발화 실패: out={captured.out!r} err={captured.err!r}"


def test_include_null_owner_false_path_no_sentinel():
    """include_null_owner=False 또는 미설정 → sentinel 부재 (default 격리)."""
    eng = _make_engine_stub(
        agent_ctx=_make_agent_ctx(agent_id=uuid4(), is_admin=True)
    )
    sess = _make_session_stub()

    out_false = eng._enrich_plan_tool_args(
        {"include_null_owner": False},
        sess,
        tool_name="memo.list",
    )
    out_missing = eng._enrich_plan_tool_args({}, sess, tool_name="memo.list")

    assert "_admin_null_owner_sentinel" not in out_false
    assert "_admin_null_owner_sentinel" not in out_missing


# ---------------------------------------------------------------------------
# regression — schedule.* 기존 동작 보존
# ---------------------------------------------------------------------------


def test_schedule_create_inject_regression():
    """schedule.create 는 D23 이전 hardcode path 와 동등 동작."""
    server_aid = uuid4()
    eng = _make_engine_stub(agent_ctx=_make_agent_ctx(agent_id=server_aid))
    sess = _make_session_stub()

    out = eng._enrich_plan_tool_args(
        {"title": "회의", "starts_at": "2026-05-08T10:00:00Z"},
        sess,
        tool_name="schedule.create",
    )

    assert out["agent_id"] == str(server_aid)
    assert out["title"] == "회의"
