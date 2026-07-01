"""Phase 1.5A Task 8b — confirm_token TTL + sha256 hash + 5축 binding 검증.

Coverage:
- token issue 후 정상 consume 통과
- TTL 만료 후 consume 실패 (reason=expired)
- 다른 tenant 로 consume 실패 (reason=binding_mismatch)
- 다른 input_args 로 consume 실패 (reason=binding_mismatch)
- 다른 tool_name 으로 consume 실패 (reason=binding_mismatch)
- 다른 account 로 consume 실패 (reason=binding_mismatch)
- 두 번째 consume 실패 (reason=already_consumed) — replay 방지
- 잘못된 raw_token 으로 consume 실패 (reason=unknown)
- token_hash 가 sha256 hex 임을 검증 (plaintext 미저장)
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest
from sqlalchemy import text

from src.agent_framework.storage.tool_invocation_store import (
    ToolInvocationStore,
    canonical_input_hash,
    _sha256_hex,
)


def _cleanup(db, inv_id: str) -> None:
    db.execute(text("DELETE FROM tool_invocations WHERE id=:i"), {"i": inv_id})
    db.commit()


def test_issue_token_returns_raw_and_hash(db):
    store = ToolInvocationStore(db)
    inv_id, raw, h = asyncio.run(
        store.issue_token(
            tenant_id="t-A",
            account_id="acc-1",
            session_id="sess-1",
            turn_id="trn-1",
            skill_id="sk1",
            cc_pair_id=None,
            tool_name="schedule.delete",
            input_args={"id": "abc"},
        )
    )
    assert inv_id and raw and h
    assert h == _sha256_hex(raw)
    # DB 에 plaintext 가 token_hash 로 저장되지 않았는지 확인.
    row = db.execute(
        text(
            "SELECT token_hash, expires_at, bound_tenant_id, bound_account_id, "
            "       bound_session_id, bound_tool, bound_input_hash, status "
            "  FROM tool_invocations WHERE id=:i"
        ),
        {"i": inv_id},
    ).mappings().first()
    assert row["token_hash"] == h
    assert row["token_hash"] != raw  # plaintext 가 아님
    assert row["bound_tenant_id"] == "t-A"
    assert row["bound_account_id"] == "acc-1"
    assert row["bound_session_id"] == "sess-1"
    assert row["bound_tool"] == "schedule.delete"
    assert row["bound_input_hash"] == canonical_input_hash({"id": "abc"})
    assert row["status"] == "pending_confirm"
    assert row["expires_at"] is not None
    _cleanup(db, inv_id)


def test_consume_token_happy_path(db):
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A",
            account_id="acc-1",
            session_id="s-1",
            turn_id=None,
            skill_id="sk",
            cc_pair_id=None,
            tool_name="expense.delete",
            input_args={"id": "x"},
        )
    )
    ok, reason, returned_id = asyncio.run(
        store.consume_token(
            raw,
            tenant_id="t-A",
            account_id="acc-1",
            session_id="s-1",
            tool_name="expense.delete",
            input_args={"id": "x"},
        )
    )
    assert ok is True
    assert reason == "consumed"
    assert returned_id == inv_id

    row = db.execute(
        text("SELECT status, consumed_at FROM tool_invocations WHERE id=:i"),
        {"i": inv_id},
    ).mappings().first()
    assert row["status"] == "consumed"
    assert row["consumed_at"] is not None
    _cleanup(db, inv_id)


def test_consume_token_replay_blocked(db):
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A",
            account_id="acc-1",
            session_id="s-1",
            turn_id=None,
            skill_id="sk",
            cc_pair_id=None,
            tool_name="x.delete",
            input_args={"id": "y"},
        )
    )
    ok1, _, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-A", account_id="acc-1", session_id="s-1",
            tool_name="x.delete", input_args={"id": "y"},
        )
    )
    assert ok1 is True
    # 2번째 시도 — already_consumed.
    ok2, reason2, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-A", account_id="acc-1", session_id="s-1",
            tool_name="x.delete", input_args={"id": "y"},
        )
    )
    assert ok2 is False
    assert reason2 == "already_consumed"
    _cleanup(db, inv_id)


def test_consume_token_cross_tenant_blocked(db):
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A",
            account_id="acc-1",
            session_id="s-1",
            turn_id=None,
            skill_id="sk",
            cc_pair_id=None,
            tool_name="t.del",
            input_args={"id": "z"},
        )
    )
    # 다른 tenant 로 consume 시도.
    ok, reason, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-B", account_id="acc-1", session_id="s-1",
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    assert ok is False
    assert reason == "binding_mismatch"
    # row 는 그대로 pending_confirm 이어야 함 (consume 안 됨).
    row = db.execute(
        text("SELECT status FROM tool_invocations WHERE id=:i"), {"i": inv_id},
    ).mappings().first()
    assert row["status"] == "pending_confirm"
    _cleanup(db, inv_id)


def test_consume_token_cross_account_blocked(db):
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A", account_id="acc-1", session_id="s-1",
            turn_id=None, skill_id="sk", cc_pair_id=None,
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    ok, reason, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-A", account_id="acc-2", session_id="s-1",
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    assert ok is False
    assert reason == "binding_mismatch"
    _cleanup(db, inv_id)


def test_consume_token_input_hash_mismatch_blocked(db):
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A", account_id="acc-1", session_id="s-1",
            turn_id=None, skill_id="sk", cc_pair_id=None,
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    # input_args 변경.
    ok, reason, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-A", account_id="acc-1", session_id="s-1",
            tool_name="t.del", input_args={"id": "tampered"},
        )
    )
    assert ok is False
    assert reason == "binding_mismatch"
    _cleanup(db, inv_id)


def test_consume_token_tool_mismatch_blocked(db):
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A", account_id="acc-1", session_id="s-1",
            turn_id=None, skill_id="sk", cc_pair_id=None,
            tool_name="schedule.delete", input_args={"id": "z"},
        )
    )
    # 다른 tool 로 consume 시도 — privilege escalation 차단.
    ok, reason, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-A", account_id="acc-1", session_id="s-1",
            tool_name="expense.delete", input_args={"id": "z"},
        )
    )
    assert ok is False
    assert reason == "binding_mismatch"
    _cleanup(db, inv_id)


def test_consume_unknown_token_returns_unknown(db):
    store = ToolInvocationStore(db)
    ok, reason, inv = asyncio.run(
        store.consume_token(
            "not_a_real_token_anywhere",
            tenant_id="t-A", account_id="acc-1", session_id="s-1",
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    assert ok is False
    assert reason == "unknown"
    assert inv is None


def test_consume_expired_token_blocked(db, monkeypatch):
    """ttl_seconds=1 로 발급 후 sleep 2초 → expired."""
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A", account_id="acc-1", session_id="s-1",
            turn_id=None, skill_id="sk", cc_pair_id=None,
            tool_name="t.del", input_args={"id": "z"},
            ttl_seconds=1,
        )
    )
    time.sleep(2)
    ok, reason, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-A", account_id="acc-1", session_id="s-1",
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    assert ok is False
    assert reason == "expired"
    # status 가 expired 로 마킹됐는지.
    row = db.execute(
        text("SELECT status FROM tool_invocations WHERE id=:i"), {"i": inv_id},
    ).mappings().first()
    assert row["status"] == "expired"
    _cleanup(db, inv_id)


def test_consume_session_mismatch_blocked(db):
    store = ToolInvocationStore(db)
    inv_id, raw, _ = asyncio.run(
        store.issue_token(
            tenant_id="t-A", account_id="acc-1", session_id="sess-original",
            turn_id=None, skill_id="sk", cc_pair_id=None,
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    # 다른 session 으로 consume — 다른 채팅창에서 hijack 시도.
    ok, reason, _ = asyncio.run(
        store.consume_token(
            raw, tenant_id="t-A", account_id="acc-1", session_id="sess-other",
            tool_name="t.del", input_args={"id": "z"},
        )
    )
    assert ok is False
    assert reason == "binding_mismatch"
    _cleanup(db, inv_id)


def test_legacy_insert_pending_still_works(db):
    """시연 path 호환 — insert_pending (plaintext) 은 그대로 동작해야 한다."""
    store = ToolInvocationStore(db)
    inv_id, token = asyncio.run(
        store.insert_pending(
            tenant_id="t-A", session_id="s", turn_id="t",
            skill_id="sk", cc_pair_id=None, tool_name="x", input_args={},
        )
    )
    assert inv_id and token
    row = db.execute(
        text(
            "SELECT status, resume_token, token_hash "
            "  FROM tool_invocations WHERE id=:i"
        ),
        {"i": inv_id},
    ).mappings().first()
    assert row["status"] == "pending_confirm"
    assert row["resume_token"] == token
    # legacy 경로는 token_hash 미주입 — secure consume 거부됨.
    assert row["token_hash"] is None
    _cleanup(db, inv_id)
