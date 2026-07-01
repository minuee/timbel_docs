"""D29 §2 (#156) admin global view router 단위 test.

엔드포인트 자체의 routing / 권한 / static whitelist / parameter binding /
response shape 검증.

실제 DB 통합 (5 봇 + admin smoke) 은 후속 dispatch 의 Phase 2.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def aid_uuid():
    return uuid4()


@pytest.fixture
def tid_uuid():
    return uuid4()


def _patch_auth(role: str, aid, tid):
    """auth helpers 를 monkey-patch — DB call skip."""
    return {
        "src.api.routers.admin_global_view_v1._account_from_token": (
            lambda authorization: (aid, str(tid), role)
        ),
        "src.api.routers.admin_global_view_v1._resolve_tenant": (
            lambda token_tid, x: tid
        ),
    }


def test_static_whitelist_module_loaded():
    """static whitelist + repo 상수 임포트 가능."""
    from src.api.routers.admin_global_view_v1 import (
        _AGENT_DATA_REPO_NAME,
        _ORDER_ALIASES,
        _RANGE_ALIASES,
        _SCOPE_ALIASES,
        _SCOPE_TO_DOCTYPE,
    )
    assert "schedule" in _SCOPE_TO_DOCTYPE
    assert "memo" in _SCOPE_TO_DOCTYPE
    assert "expense" in _SCOPE_TO_DOCTYPE
    assert "diary" in _SCOPE_TO_DOCTYPE
    assert "reminder" in _SCOPE_TO_DOCTYPE
    assert _SCOPE_TO_DOCTYPE["schedule"] == "agent_schedule"
    assert _SCOPE_TO_DOCTYPE["memo"] == "agent_memo"
    assert "all" in _SCOPE_ALIASES
    assert _ORDER_ALIASES == ("desc", "asc")
    assert "today" in _RANGE_ALIASES
    assert _AGENT_DATA_REPO_NAME == "__agent_data__"


def test_resolve_range_today():
    from datetime import datetime, timezone
    from src.api.routers.admin_global_view_v1 import _resolve_range

    now = datetime(2026, 5, 8, 14, 30, 0, tzinfo=timezone.utc)
    since = _resolve_range("today", now=now)
    assert since is not None
    assert since.hour == 0 and since.minute == 0
    assert since.date() == now.date()


def test_resolve_range_week():
    from datetime import datetime, timedelta, timezone
    from src.api.routers.admin_global_view_v1 import _resolve_range

    now = datetime(2026, 5, 8, 14, 30, 0, tzinfo=timezone.utc)
    since = _resolve_range("week", now=now)
    assert since is not None
    assert (now - since) == timedelta(days=7)


def test_resolve_range_month():
    from datetime import datetime, timedelta, timezone
    from src.api.routers.admin_global_view_v1 import _resolve_range

    now = datetime(2026, 5, 8, tzinfo=timezone.utc)
    since = _resolve_range("month", now=now)
    assert since is not None
    assert (now - since) == timedelta(days=30)


def test_resolve_range_all_returns_none():
    from src.api.routers.admin_global_view_v1 import _resolve_range
    assert _resolve_range("all") is None


def test_router_registered_in_main():
    """router 가 main.py 에 정상 wire 됨."""
    from src.api.routers.admin_global_view_v1 import router

    routes = [r.path for r in router.routes]
    assert any("/global-view" in p for p in routes), f"global-view path 없음: {routes}"


# ---------------------------------------------------------------------------
# 권한 검증 — non-admin/owner role → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_view_rejects_member_role(aid_uuid, tid_uuid):
    """role='member' → 403."""
    from fastapi import HTTPException

    from src.api.routers import admin_global_view_v1 as mod

    # Patch auth helpers
    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "member")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="member"):
                with pytest.raises(HTTPException) as exc:
                    await mod.global_view(
                        scope="schedule",
                        agent_id=None,
                        limit=100,
                        order="desc",
                        range="all",
                        q=None,
                        authorization="Bearer xxx",
                        x_tenant_id=str(tid_uuid),
                    )
                assert exc.value.status_code == 403
                assert "owner or admin" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_global_view_invalid_scope(aid_uuid, tid_uuid):
    """static whitelist 외 scope → 400."""
    from fastapi import HTTPException

    from src.api.routers import admin_global_view_v1 as mod

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with pytest.raises(HTTPException) as exc:
                    await mod.global_view(
                        scope="malicious_doctype",
                        agent_id=None,
                        limit=100,
                        order="desc",
                        range="all",
                        q=None,
                        authorization="Bearer xxx",
                        x_tenant_id=str(tid_uuid),
                    )
                assert exc.value.status_code == 400
                assert "scope" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_global_view_invalid_agent_id_uuid(aid_uuid, tid_uuid):
    """agent_id 가 invalid UUID → 400."""
    from fastapi import HTTPException

    from src.api.routers import admin_global_view_v1 as mod

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with pytest.raises(HTTPException) as exc:
                    await mod.global_view(
                        scope="schedule",
                        agent_id="not-a-uuid",
                        limit=100,
                        order="desc",
                        range="all",
                        q=None,
                        authorization="Bearer xxx",
                        x_tenant_id=str(tid_uuid),
                    )
                assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_global_view_invalid_order(aid_uuid, tid_uuid):
    from fastapi import HTTPException
    from src.api.routers import admin_global_view_v1 as mod

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "owner")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="owner"):
                with pytest.raises(HTTPException) as exc:
                    await mod.global_view(
                        scope="schedule",
                        agent_id=None,
                        limit=100,
                        order="random",
                        range="all",
                        q=None,
                        authorization="Bearer xxx",
                        x_tenant_id=str(tid_uuid),
                    )
                assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_global_view_invalid_range(aid_uuid, tid_uuid):
    from fastapi import HTTPException
    from src.api.routers import admin_global_view_v1 as mod

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with pytest.raises(HTTPException) as exc:
                    await mod.global_view(
                        scope="schedule",
                        agent_id=None,
                        limit=100,
                        order="desc",
                        range="forever",
                        q=None,
                        authorization="Bearer xxx",
                        x_tenant_id=str(tid_uuid),
                    )
                assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_global_view_admin_with_mocked_query(aid_uuid, tid_uuid):
    """admin 권한 + mocked query → response shape 검증."""
    from src.api.routers import admin_global_view_v1 as mod

    mock_rows = [
        {
            "scope": "schedule",
            "id": str(uuid4()),
            "title": "회의",
            "preview": "회의",
            "created_at": "2026-05-08T10:00:00+00:00",
            "owner_agent_id": str(uuid4()),
            "agent_name": "agent A",
            "agent_is_active": True,
        }
    ]

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_get_engine", return_value=object()):
                    with patch.object(mod, "record_action"):
                        with patch.object(mod, "_query_doctype", new_callable=AsyncMock, return_value=mock_rows):
                            resp = await mod.global_view(
                                scope="schedule",
                                agent_id=None,
                                limit=100,
                                order="desc",
                                range="all",
                                q=None,
                                authorization="Bearer xxx",
                                x_tenant_id=str(tid_uuid),
                            )
                            assert resp.total == 1
                            assert resp.items[0].scope == "schedule"
                            assert resp.items[0].agent_name == "agent A"
                            assert resp.scope_counts["schedule"] == 1


@pytest.mark.asyncio
async def test_global_view_all_scope_runs_all_5_doctypes(aid_uuid, tid_uuid):
    """scope='all' → 5 doctype 병렬 query."""
    from src.api.routers import admin_global_view_v1 as mod

    call_count = {"n": 0}

    async def _stub_query(eng, **kwargs):
        call_count["n"] += 1
        return []

    with patch.object(mod, "_account_from_token", lambda x: (aid_uuid, str(tid_uuid), "admin")):
        with patch.object(mod, "_resolve_tenant", lambda token_tid, x: tid_uuid):
            with patch.object(mod, "_verify_membership", new_callable=AsyncMock, return_value="admin"):
                with patch.object(mod, "_get_engine", return_value=object()):
                    with patch.object(mod, "record_action"):
                        with patch.object(mod, "_query_doctype", side_effect=_stub_query):
                            resp = await mod.global_view(
                                scope="all",
                                agent_id=None,
                                limit=100,
                                order="desc",
                                range="all",
                                q=None,
                                authorization="Bearer xxx",
                                x_tenant_id=str(tid_uuid),
                            )
                            assert call_count["n"] == 5  # 5 doctype
                            assert set(resp.scope_counts.keys()) == {
                                "schedule",
                                "memo",
                                "expense",
                                "diary",
                                "reminder",
                            }


# ---------------------------------------------------------------------------
# SQL isolation 테스트 (GPT-5 권고 #1) — _build_query 직접 검증.
# ---------------------------------------------------------------------------


def test_build_query_enforces_d_tenant_id_equals():
    """`d.tenant_id = :tid` 강제 (NULL tenant 노출 차단)."""
    from src.api.routers.admin_global_view_v1 import _build_query

    sql, params = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=None,
        range_since=None,
        q=None,
        limit=100,
        order_desc=True,
    )
    # d.tenant_id = :tid 포함 (필수)
    assert "d.tenant_id = :tid" in sql
    # NULL tenant 허용 흔적 없음 (NO-GO patch)
    assert "d.tenant_id IS NULL" not in sql
    assert "OR d.tenant_id" not in sql
    # repo / dt 도 :tid 격리
    assert "r.tenant_id = :tid" in sql
    assert "dt.tenant_id = :tid" in sql


def test_build_query_q_uses_parameter_binding():
    """`q` 는 ILIKE :qpat 파라미터 바인딩 — 직접 string interpolation 없음."""
    from src.api.routers.admin_global_view_v1 import _build_query

    malicious = "'; DROP TABLE documents; --"
    sql, params = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=None,
        range_since=None,
        q=malicious,
        limit=100,
        order_desc=True,
    )
    # SQL 본문에 raw 문자열 미포함
    assert malicious not in sql
    assert "DROP TABLE" not in sql
    # parameter 로만 전달
    assert sql.count(":qpat") == 1
    assert "ILIKE :qpat" in sql
    assert params["qpat"] == f"%{malicious}%"


def test_build_query_order_only_asc_or_desc():
    """`order_desc` flag 로 ASC/DESC 만 선택 — 외부 입력 영향 없음."""
    from src.api.routers.admin_global_view_v1 import _build_query

    sql_desc, _ = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=None,
        range_since=None,
        q=None,
        limit=100,
        order_desc=True,
    )
    sql_asc, _ = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=None,
        range_since=None,
        q=None,
        limit=100,
        order_desc=False,
    )
    assert "ORDER BY d.created_at DESC" in sql_desc
    assert "ORDER BY d.created_at ASC" in sql_asc


def test_build_query_agent_id_filter_binds_param():
    from src.api.routers.admin_global_view_v1 import _build_query

    aid = uuid4()
    sql, params = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=aid,
        range_since=None,
        q=None,
        limit=100,
        order_desc=True,
    )
    assert "d.owner_agent_id = :aid" in sql
    assert params["aid"] == aid
    # raw UUID 가 SQL 본문에 없음
    assert str(aid) not in sql


def test_build_query_no_agent_id_no_filter_clause():
    """agent_id_filter None → owner_agent_id 필터 없음 (NULL bucket admin 노출)."""
    from src.api.routers.admin_global_view_v1 import _build_query

    sql, params = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=None,
        range_since=None,
        q=None,
        limit=100,
        order_desc=True,
    )
    # WHERE/AND 분기에 owner_agent_id 필터 없음 (SELECT 의 d.owner_agent_id 컬럼은 OK).
    assert "d.owner_agent_id = :aid" not in sql
    assert "aid" not in params


def test_build_query_range_since_binds_param():
    from datetime import datetime, timezone
    from src.api.routers.admin_global_view_v1 import _build_query

    since = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    sql, params = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=None,
        range_since=since,
        q=None,
        limit=100,
        order_desc=True,
    )
    assert "d.created_at >= :since" in sql
    assert params["since"] == since


def test_build_query_includes_left_join_agents():
    """agents JOIN — inactive agent 도 표시 (a.is_active 필터 없음)."""
    from src.api.routers.admin_global_view_v1 import _build_query

    sql, _ = _build_query(
        tenant_id=uuid4(),
        doctype_name="agent_memo",
        agent_id_filter=None,
        range_since=None,
        q=None,
        limit=100,
        order_desc=True,
    )
    assert "LEFT JOIN agents a" in sql
    assert "a.tenant_id = :tid" in sql  # cross-tenant agent name leak 차단
    # is_active 필터 없음 — soft-deleted agent 도 표시
    # ON 절 안에 a.is_active = ... 없음
    assert "a.is_active = " not in sql
