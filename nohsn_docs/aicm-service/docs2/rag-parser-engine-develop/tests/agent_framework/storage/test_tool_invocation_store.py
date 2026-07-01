import asyncio
import pytest
from sqlalchemy import text
from src.agent_framework.storage.tool_invocation_store import ToolInvocationStore


def test_insert_pending_returns_token(db):
    store = ToolInvocationStore(db)
    inv_id, token = asyncio.run(store.insert_pending(
        tenant_id="t1", session_id="s1", turn_id="tn1",
        skill_id="sk1", cc_pair_id="ccp1", tool_name="x", input_args={"a":1}))
    assert inv_id and len(token) >= 16
    row = db.execute(text("SELECT status, resume_token FROM tool_invocations WHERE id=:i"),
                     {"i": inv_id}).mappings().first()
    assert row["status"] == "pending_confirm"
    assert row["resume_token"] == token
    db.execute(text("DELETE FROM tool_invocations WHERE id=:i"), {"i": inv_id}); db.commit()


def test_confirm_result_updates_status_and_duration(db):
    store = ToolInvocationStore(db)
    inv_id, _ = asyncio.run(store.insert_pending(
        tenant_id="t1", session_id="s1", turn_id="tn1",
        skill_id="sk1", cc_pair_id="ccp1", tool_name="x", input_args={}))
    asyncio.run(store.confirm_result(
        inv_id, status="succeeded", output={"ok":True}, duration_ms=42,
        confirmed_by_user_id="u1"))
    row = db.execute(text("SELECT status, duration_ms, confirmed_by_user_id, executed_at "
                           "FROM tool_invocations WHERE id=:i"),
                     {"i": inv_id}).mappings().first()
    assert row["status"] == "succeeded"
    assert row["duration_ms"] == 42
    assert row["confirmed_by_user_id"] == "u1"
    assert row["executed_at"] is not None
    db.execute(text("DELETE FROM tool_invocations WHERE id=:i"), {"i": inv_id}); db.commit()


def test_get_usage_today_counts_only_today_and_skill(db):
    store = ToolInvocationStore(db)
    created: list[str] = []
    for _ in range(3):
        inv, _ = asyncio.run(store.insert_pending(
            tenant_id="t1", session_id=None, turn_id=None,
            skill_id="sk_counted", cc_pair_id=None, tool_name="x", input_args={}))
        asyncio.run(store.confirm_result(inv, status="succeeded", output={}, duration_ms=0))
        created.append(inv)
    for _ in range(2):
        inv, _ = asyncio.run(store.insert_pending(
            tenant_id="t1", session_id=None, turn_id=None,
            skill_id="sk_other", cc_pair_id=None, tool_name="x", input_args={}))
        asyncio.run(store.confirm_result(inv, status="succeeded", output={}, duration_ms=0))
        created.append(inv)
    n = asyncio.run(store.get_usage_today("sk_counted"))
    assert n == 3
    # cleanup
    for i in created:
        db.execute(text("DELETE FROM tool_invocations WHERE id=:i"), {"i": i}); db.commit()
