"""D29 §3 (#157) — agent delete + transfer 단위 test.

backend `delete_agent` 의 transfer 모드 검증:
- transfer_to_agent_id 미명시 → 기존 동작 (회귀 0)
- self-transfer 거부 (400)
- cross-tenant target 거부 (403 from _load_agent_for_tenant)
- inactive target 거부 (400)
- transaction 안 lock + 재검증
- already_inactive idempotent

DB integration smoke 는 후속 dispatch (5 봇 + admin Phase 2).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


@pytest.fixture
def aid_uuid():
    return uuid4()


@pytest.fixture
def tid_uuid():
    return uuid4()


@pytest.fixture
def src_uuid():
    return uuid4()


@pytest.fixture
def tgt_uuid():
    return uuid4()


# ---------------------------------------------------------------------------
# Self-transfer reject (사전 검증)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_transfer_rejected(aid_uuid, tid_uuid, src_uuid):
    """transfer_to_agent_id == agent_id → 400."""
    from src.api.routers import agents_v1 as mod

    fake_agent = MagicMock(id=str(src_uuid), is_active=True, tenant_id=str(tid_uuid))

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_load_agent_for_tenant", new_callable=AsyncMock, return_value=fake_agent):
                    with pytest.raises(HTTPException) as exc:
                        await mod.delete_agent(
                            agent_id=str(src_uuid),
                            transfer_to_agent_id=str(src_uuid),  # self
                            authorization="Bearer xxx",
                            x_tenant_id=str(tid_uuid),
                        )
                    assert exc.value.status_code == 400
                    assert "self-transfer" in str(exc.value.detail).lower()


# ---------------------------------------------------------------------------
# Inactive target reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_target_rejected(aid_uuid, tid_uuid, src_uuid, tgt_uuid):
    """transfer target 이 is_active=False → 400."""
    from src.api.routers import agents_v1 as mod

    fake_src = MagicMock(id=str(src_uuid), is_active=True, tenant_id=str(tid_uuid))
    fake_tgt = MagicMock(id=str(tgt_uuid), is_active=False, tenant_id=str(tid_uuid))

    async def _load_for_tenant_stub(uid, tid):
        if uid == src_uuid:
            return fake_src
        if uid == tgt_uuid:
            return fake_tgt
        raise HTTPException(404, "not found")

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_load_agent_for_tenant", side_effect=_load_for_tenant_stub):
                    with pytest.raises(HTTPException) as exc:
                        await mod.delete_agent(
                            agent_id=str(src_uuid),
                            transfer_to_agent_id=str(tgt_uuid),
                            authorization="Bearer xxx",
                            x_tenant_id=str(tid_uuid),
                        )
                    assert exc.value.status_code == 400
                    assert "inactive" in str(exc.value.detail).lower()


# ---------------------------------------------------------------------------
# Permission / parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_role_rejected(aid_uuid, tid_uuid, src_uuid):
    """role='member' → 403 (transfer 옵션 무관)."""
    from src.api.routers import agents_v1 as mod

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "member")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="member"):
                with pytest.raises(HTTPException) as exc:
                    await mod.delete_agent(
                        agent_id=str(src_uuid),
                        transfer_to_agent_id=None,
                        authorization="Bearer xxx",
                        x_tenant_id=str(tid_uuid),
                    )
                assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_invalid_transfer_uuid_400(aid_uuid, tid_uuid, src_uuid):
    """transfer_to_agent_id 가 invalid UUID → 400."""
    from src.api.routers import agents_v1 as mod

    fake_src = MagicMock(id=str(src_uuid), is_active=True, tenant_id=str(tid_uuid))

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "owner")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="owner"):
                with patch.object(mod, "_load_agent_for_tenant", new_callable=AsyncMock, return_value=fake_src):
                    with pytest.raises(HTTPException) as exc:
                        await mod.delete_agent(
                            agent_id=str(src_uuid),
                            transfer_to_agent_id="not-uuid",
                            authorization="Bearer xxx",
                            x_tenant_id=str(tid_uuid),
                        )
                    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Backwards compatibility — transfer_to_agent_id None → 기존 동작
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_transfer_keeps_legacy_behavior(aid_uuid, tid_uuid, src_uuid):
    """transfer_to_agent_id 미전달 → owner 보존 + soft delete only.

    response shape 에 transferred_to=None, transferred={} 포함 (확장 OK).
    """
    from src.api.routers import agents_v1 as mod

    fake_src = MagicMock(id=str(src_uuid), is_active=True, tenant_id=str(tid_uuid))

    # Fake conn / engine
    fake_lock_row = MagicMock()
    fake_lock_row.__getitem__ = lambda self, idx: {0: src_uuid, 1: tid_uuid, 2: True}[idx]
    fake_lock_result = MagicMock()
    fake_lock_result.all = MagicMock(return_value=[(src_uuid, tid_uuid, True)])

    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock(return_value=fake_lock_result)

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.begin = MagicMock(return_value=_CM())

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_load_agent_for_tenant", new_callable=AsyncMock, return_value=fake_src):
                    with patch.object(mod, "_get_engine", return_value=fake_eng):
                        with patch.object(mod, "record_action"):
                            resp = await mod.delete_agent(
                                agent_id=str(src_uuid),
                                transfer_to_agent_id=None,
                                authorization="Bearer xxx",
                                x_tenant_id=str(tid_uuid),
                            )
                            assert resp["ok"] is True
                            assert resp["is_active"] is False
                            assert resp["transferred_to"] is None
                            assert resp["transferred"] == {}


# ---------------------------------------------------------------------------
# Idempotent already_inactive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_inactive_idempotent(aid_uuid, tid_uuid, src_uuid):
    """source 가 이미 inactive → idempotent 200 + already_inactive 플래그."""
    from src.api.routers import agents_v1 as mod

    fake_src = MagicMock(id=str(src_uuid), is_active=False, tenant_id=str(tid_uuid))

    fake_lock_result = MagicMock()
    fake_lock_result.all = MagicMock(
        return_value=[(src_uuid, tid_uuid, False)]  # is_active=False
    )

    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock(return_value=fake_lock_result)

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.begin = MagicMock(return_value=_CM())

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_load_agent_for_tenant", new_callable=AsyncMock, return_value=fake_src):
                    with patch.object(mod, "_get_engine", return_value=fake_eng):
                        with patch.object(mod, "record_action"):
                            resp = await mod.delete_agent(
                                agent_id=str(src_uuid),
                                transfer_to_agent_id=None,
                                authorization="Bearer xxx",
                                x_tenant_id=str(tid_uuid),
                            )
                            assert resp["ok"] is True
                            assert resp.get("already_inactive") is True


# ---------------------------------------------------------------------------
# Response shape — transfer 모드
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transfer_mode_response_shape(aid_uuid, tid_uuid, src_uuid, tgt_uuid):
    """transfer 모드 → transferred_to + transferred counts + 회귀 0."""
    from src.api.routers import agents_v1 as mod

    fake_src = MagicMock(id=str(src_uuid), is_active=True, tenant_id=str(tid_uuid))
    fake_tgt = MagicMock(id=str(tgt_uuid), is_active=True, tenant_id=str(tid_uuid))

    async def _load_for_tenant_stub(uid, tid):
        if uid == src_uuid:
            return fake_src
        if uid == tgt_uuid:
            return fake_tgt
        raise HTTPException(404, "not found")

    # Fake DB:
    # 1st call: SELECT FOR UPDATE → 2 rows (src active, tgt active)
    # subsequent: UPDATE documents (rowcount 3), library_folders (rowcount 1),
    #             schedules.column check (None — no schedules table),
    #             UPDATE agents.
    fake_lock_result = MagicMock()
    fake_lock_result.all = MagicMock(
        return_value=[
            (src_uuid, tid_uuid, True),
            (tgt_uuid, tid_uuid, True),
        ]
    )
    fake_doc_update = MagicMock(rowcount=3)
    fake_lf_update = MagicMock(rowcount=1)
    # schedules column check returns None (legacy fixture — 컬럼 없음)
    fake_no_col = MagicMock()
    fake_no_col.first = MagicMock(return_value=None)

    fake_agents_update = MagicMock(rowcount=1)

    call_log = []

    async def _execute(sql, params=None):
        sql_str = str(sql)
        call_log.append(sql_str)
        if "SELECT id, tenant_id, is_active FROM agents" in sql_str and "FOR UPDATE" in sql_str:
            return fake_lock_result
        if "UPDATE documents" in sql_str:
            return fake_doc_update
        if "UPDATE library_folders" in sql_str:
            return fake_lf_update
        if "information_schema.columns" in sql_str:
            return fake_no_col
        if "UPDATE agents SET is_active" in sql_str:
            return fake_agents_update
        return MagicMock()

    fake_conn = MagicMock()
    fake_conn.execute = _execute

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.begin = MagicMock(return_value=_CM())

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_load_agent_for_tenant", side_effect=_load_for_tenant_stub):
                    with patch.object(mod, "_get_engine", return_value=fake_eng):
                        with patch.object(mod, "record_action"):
                            resp = await mod.delete_agent(
                                agent_id=str(src_uuid),
                                transfer_to_agent_id=str(tgt_uuid),
                                authorization="Bearer xxx",
                                x_tenant_id=str(tid_uuid),
                            )
                            assert resp["ok"] is True
                            assert resp["is_active"] is False
                            assert resp["transferred_to"] == str(tgt_uuid)
                            assert resp["transferred"]["documents"] == 3
                            assert resp["transferred"]["library_folders"] == 1
                            # schedules 컬럼 없음 → key 자체 미포함
                            assert "schedules" not in resp["transferred"]


# ---------------------------------------------------------------------------
# Lock + 재검증 — target inactive between sync and lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_target_inactive_during_lock_rejected(aid_uuid, tid_uuid, src_uuid, tgt_uuid):
    """사전 검증 시점에는 target active 였으나 lock 후 inactive 면 race 차단."""
    from src.api.routers import agents_v1 as mod

    fake_src = MagicMock(id=str(src_uuid), is_active=True, tenant_id=str(tid_uuid))
    fake_tgt = MagicMock(id=str(tgt_uuid), is_active=True, tenant_id=str(tid_uuid))

    async def _load_for_tenant_stub(uid, tid):
        return fake_src if uid == src_uuid else fake_tgt

    # lock 후 result: src active, tgt *inactive* (race)
    fake_lock_result = MagicMock()
    fake_lock_result.all = MagicMock(
        return_value=[
            (src_uuid, tid_uuid, True),
            (tgt_uuid, tid_uuid, False),
        ]
    )
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock(return_value=fake_lock_result)

    class _CM:
        async def __aenter__(self_):
            return fake_conn
        async def __aexit__(self_, *a):
            return False

    fake_eng = MagicMock()
    fake_eng.begin = MagicMock(return_value=_CM())

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_load_agent_for_tenant", side_effect=_load_for_tenant_stub):
                    with patch.object(mod, "_get_engine", return_value=fake_eng):
                        with patch.object(mod, "record_action"):
                            with pytest.raises(HTTPException) as exc:
                                await mod.delete_agent(
                                    agent_id=str(src_uuid),
                                    transfer_to_agent_id=str(tgt_uuid),
                                    authorization="Bearer xxx",
                                    x_tenant_id=str(tid_uuid),
                                )
                            assert exc.value.status_code == 400
                            assert "inactive" in str(exc.value.detail).lower()
