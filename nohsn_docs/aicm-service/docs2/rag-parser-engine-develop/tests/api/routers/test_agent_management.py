"""agent_management endpoints — Phase 1.5D unit tests (mock-based).

Tests 13 endpoints across 6 areas:
  agent-templates: GET / POST / GET-one / PATCH / POST-import
  dashboard: GET
  billing: GET-list / GET-period
  insights: GET (with cache)
  audit: GET
  alerts: GET / POST-ack
  graph: GET

DB 없이 실행 — _get_engine / _account_from_token / _verify_membership /
_load_agent_for_tenant 를 mock 으로 대체. agent_management 가 agents_v1 의
helper 를 import 하므로 patch path 는 ``agent_management`` 모듈.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token


TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())
TEMPLATE_ID = str(uuid.uuid4())
ALERT_ID = str(uuid.uuid4())


def _admin_token() -> str:
    return create_access_token(subject=ADMIN_ID, tenant_id=TENANT_ID, role="admin")


def _member_token() -> str:
    return create_access_token(subject=MEMBER_ID, tenant_id=TENANT_ID, role="member")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_agent():
    from src.api.routers.agents_v1 import AgentOut

    return AgentOut(
        id=AGENT_ID,
        tenant_id=TENANT_ID,
        name="Imported",
        description="d",
        persona="p",
        system_prompt="",
        allowed_skills=[],
        allowed_repos=[],
        is_active=True,
        rate_limit_per_min=60,
        created_by=ADMIN_ID,
    )


def _patch_auth(role: str = "admin"):
    """3 helper functions in agent_management module."""
    aid = uuid.UUID(ADMIN_ID) if role in ("owner", "admin") else uuid.UUID(MEMBER_ID)
    return [
        patch(
            "src.api.routers.agent_management._account_from_token",
            return_value=(aid, TENANT_ID, role),
        ),
        patch(
            "src.api.routers.agent_management._verify_membership",
            new=AsyncMock(return_value=role),
        ),
        patch(
            "src.api.routers.agent_management._load_agent_for_tenant",
            new=AsyncMock(return_value=_mock_agent()),
        ),
    ]


def _mock_engine_with_rows(rows_per_call: list):
    """rows_per_call: list of result objects (row list, scalar, or first()).

    Each conn.execute() call pops one. Use iterator-friendly returns.
    """
    call_idx = [0]

    async def _execute(*args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx < len(rows_per_call):
            return rows_per_call[idx]
        # default empty
        m = MagicMock()
        m.__iter__ = MagicMock(return_value=iter([]))
        m.first = MagicMock(return_value=None)
        m.scalar_one = MagicMock(return_value=uuid.uuid4())
        m.rowcount = 0
        return m

    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = _execute
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_eng = MagicMock()
    mock_eng.begin.return_value = mock_ctx
    return mock_eng


def _result(rows=None, first_row=None, scalar=None, rowcount=0):
    """Build a single execute-return mock."""
    m = MagicMock()
    m.__iter__ = MagicMock(return_value=iter(rows or []))
    m.first = MagicMock(return_value=first_row)
    m.scalar_one = MagicMock(return_value=scalar)
    m.rowcount = rowcount
    return m


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. GET /api/v1/agent-templates
# ---------------------------------------------------------------------------


def test_list_templates_returns_items(client):
    """published 카탈로그 list — admin role OK."""
    now = datetime.utcnow()
    fake_row = (
        uuid.UUID(TEMPLATE_ID), "homeshop_v1", "홈쇼핑 응대",
        "retail", "친절한 상담사", "## SOP", ["kms_rag.search"], ["web"],
        [], "published", uuid.UUID(ADMIN_ID), 1, {"model": "free"},
        "홈쇼핑 카탈로그", None, "Locus", now, now,
    )
    eng = _mock_engine_with_rows([_result(rows=[fake_row])])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            "/api/v1/agent-templates",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["template_key"] == "homeshop_v1"
    assert body["items"][0]["category"] == "retail"


# ---------------------------------------------------------------------------
# 2. POST /api/v1/agent-templates — admin only (member 403)
# ---------------------------------------------------------------------------


def test_create_template_member_blocked(client):
    pat_tok, pat_mem, pat_load = _patch_auth("member")
    with pat_tok, pat_mem, pat_load:
        r = client.post(
            "/api/v1/agent-templates",
            headers={"Authorization": f"Bearer {_member_token()}"},
            json={
                "template_key": "k1",
                "template_name": "T",
                "category": "other",
            },
        )
    assert r.status_code == 403


def test_create_template_admin_returns_row(client):
    new_id = uuid.uuid4()
    now = datetime.utcnow()
    fake_row = (
        new_id, "k1", "T", "other", "", "", [], [], [],
        "draft", uuid.UUID(ADMIN_ID), 1, {}, None, None, None, now, now,
    )
    eng = _mock_engine_with_rows([
        _result(scalar=new_id),     # INSERT RETURNING id
        _result(first_row=fake_row),  # SELECT ... back
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.post(
            "/api/v1/agent-templates",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={"template_key": "k1", "template_name": "T", "category": "other"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["template_key"] == "k1"


# ---------------------------------------------------------------------------
# 3. GET /api/v1/agent-templates/{id} — 404 when missing
# ---------------------------------------------------------------------------


def test_get_template_not_found(client):
    eng = _mock_engine_with_rows([_result(first_row=None)])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            f"/api/v1/agent-templates/{TEMPLATE_ID}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 4. PATCH /api/v1/agent-templates/{id} — name update
# ---------------------------------------------------------------------------


def test_patch_template_admin_ok(client):
    now = datetime.utcnow()
    fake_row = (
        uuid.UUID(TEMPLATE_ID), "k1", "Updated", "other", "", "", [], [], [],
        "draft", uuid.UUID(ADMIN_ID), 1, {}, None, None, None, now, now,
    )
    eng = _mock_engine_with_rows([
        _result(),  # UPDATE
        _result(first_row=fake_row),  # SELECT
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.patch(
            f"/api/v1/agent-templates/{TEMPLATE_ID}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={"template_name": "Updated"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["template_name"] == "Updated"


# ---------------------------------------------------------------------------
# 5. POST /api/v1/agent-templates/{id}/import — happy path
# ---------------------------------------------------------------------------


def test_import_template_unpublished_400(client):
    """draft 상태는 import 불가."""
    tpl_row = (
        uuid.UUID(TEMPLATE_ID), "T", "retail", "p", "## sop",
        [], [], "draft", {},
    )
    eng = _mock_engine_with_rows([_result(first_row=tpl_row)])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.post(
            f"/api/v1/agent-templates/{TEMPLATE_ID}/import",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400
    assert "not published" in r.text


def test_import_template_published_creates_agent_and_subscription(client):
    """published 템플릿 → agent + subscription INSERT."""
    new_agent_id = uuid.uuid4()
    new_sub_id = uuid.uuid4()
    tpl_row = (
        uuid.UUID(TEMPLATE_ID), "T", "retail", "p", "## sop",
        [], [], "published", {"model": "free"},
    )
    eng = _mock_engine_with_rows([
        _result(first_row=tpl_row),       # SELECT template
        _result(scalar=new_agent_id),     # INSERT agents
        _result(),                         # UPDATE lineage_root_id
        _result(scalar=new_sub_id),        # INSERT subscriptions
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.post(
            f"/api/v1/agent-templates/{TEMPLATE_ID}/import",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == str(new_agent_id)
    assert body["subscription_id"] == str(new_sub_id)
    assert "/admin/agents/" in body["redirect_to"]


def test_import_template_member_blocked(client):
    pat_tok, pat_mem, pat_load = _patch_auth("member")
    with pat_tok, pat_mem, pat_load:
        r = client.post(
            f"/api/v1/agent-templates/{TEMPLATE_ID}/import",
            headers={"Authorization": f"Bearer {_member_token()}"},
        )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 6. GET /api/v1/agents/{id}/dashboard
# ---------------------------------------------------------------------------


def test_get_dashboard_aggregates_kpi(client):
    """dashboard — mv view + 24h + 7d + timeseries + channel + tools + errors + alerts."""
    eng = _mock_engine_with_rows([
        _result(first_row=(12, 4, 0.01, 800)),  # mv
        _result(first_row=(120, 30, 850, 1200, 2)),  # 24h agg
        _result(first_row=(800,)),  # 7d agg
        _result(rows=[
            (date(2026, 5, 1), 100, 850),
            (date(2026, 5, 2), 110, 900),
        ]),  # timeseries
        _result(rows=[("web", 600), ("telegram", 200)]),  # channel
        _result(rows=[("kms_rag.search", 420, 0.02)]),  # top tools
        _result(rows=[]),  # recent errors
        _result(rows=[]),  # alerts
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}/dashboard",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpi"]["turn_5m"] == 12
    assert body["kpi"]["turn_24h"] == 120
    assert body["kpi"]["turn_7d"] == 800
    assert len(body["timeseries_7d"]["turn"]) == 2
    assert body["channel_dist"][0]["kind"] == "web"
    assert body["top_tools"][0]["name"] == "kms_rag.search"


# ---------------------------------------------------------------------------
# 7. GET /api/v1/agents/{id}/billing — list (synthetic when empty)
# ---------------------------------------------------------------------------


def test_list_billing_synthesizes_when_empty(client):
    """ledger 비면 _synthetic_period 가 현재 월 1건 합성."""
    eng = _mock_engine_with_rows([
        _result(rows=[]),  # SELECT billing
        _result(first_row=(50, 1000, 800)),  # synthetic agg
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}/billing",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["turn_count"] == 50


# ---------------------------------------------------------------------------
# 8. GET /api/v1/agents/{id}/billing/{period} — specific month
# ---------------------------------------------------------------------------


def test_get_billing_period_invalid_format(client):
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load:
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}/billing/notavalidperiod",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400


def test_get_billing_period_synthetic_fallback(client):
    """없는 month 도 agent_message_log 기반 추정치 반환."""
    eng = _mock_engine_with_rows([
        _result(first_row=None),  # SELECT billing — none
        _result(first_row=(0, 0, 0)),  # synthetic empty
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}/billing/2026-05",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 9. GET /api/v1/agents/{id}/insights — LLM 권고 (heuristic 으로 구현됨)
# ---------------------------------------------------------------------------


def test_get_insights_zero_traffic_returns_info(client):
    """7일 호출 0 → '호출 없음' info 권고."""
    # clear cache
    from src.api.routers.agent_management import _INSIGHT_CACHE
    _INSIGHT_CACHE.clear()

    eng = _mock_engine_with_rows([
        _result(first_row=(0, 0, 0, 0)),  # 7d agg
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}/insights",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) >= 1
    assert "호출" in body["items"][0]["title"] or "호출" in body["items"][0]["summary"]
    assert body["cache_hit"] is False


def test_get_insights_cache_hit_on_second_call(client):
    """두번째 호출 = cache_hit True."""
    from src.api.routers.agent_management import _INSIGHT_CACHE
    _INSIGHT_CACHE.clear()

    eng = _mock_engine_with_rows([
        _result(first_row=(0, 0, 0, 0)),
        _result(first_row=(0, 0, 0, 0)),  # 두번째도 호출 가능 — but cache 가 가로챔
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r1 = client.get(
            f"/api/v1/agents/{AGENT_ID}/insights",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
        r2 = client.get(
            f"/api/v1/agents/{AGENT_ID}/insights",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r1.json()["cache_hit"] is False
    assert r2.json()["cache_hit"] is True


# ---------------------------------------------------------------------------
# 10. GET /api/v1/agents/{id}/audit — chain 검증 best-effort
# ---------------------------------------------------------------------------


def test_get_audit_returns_items(client):
    fake_row = (
        uuid.uuid4(), uuid.UUID(ADMIN_ID), "UPDATE", "agent",
        uuid.UUID(AGENT_ID), {}, {"name": "X"}, datetime.utcnow(),
        "agent_update", "admin", None, "success", "abc", "prev",
    )
    eng = _mock_engine_with_rows([_result(rows=[fake_row])])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}/audit",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert len(body["items"]) == 1


# ---------------------------------------------------------------------------
# 11. GET /api/v1/agents/{id}/alerts
# ---------------------------------------------------------------------------


def test_list_alerts_empty(client):
    eng = _mock_engine_with_rows([_result(rows=[])])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            f"/api/v1/agents/{AGENT_ID}/alerts",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["items"] == []


# ---------------------------------------------------------------------------
# 12. POST /api/v1/agents/{id}/alerts/{alert_id}/ack — 404 when missing
# ---------------------------------------------------------------------------


def test_ack_alert_not_found(client):
    eng = _mock_engine_with_rows([_result(rowcount=0)])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.post(
            f"/api/v1/agents/{AGENT_ID}/alerts/{ALERT_ID}/ack",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 13. GET /api/v1/agents/graph — nodes / edges
# ---------------------------------------------------------------------------


def test_get_graph_returns_nodes_and_edges(client):
    """delegate_to_agent_ids → edge."""
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    a3 = uuid.uuid4()
    eng = _mock_engine_with_rows([
        _result(rows=[
            (a1, "Admin", "admin", True, None, [a2, a3]),
            (a2, "Sales", "role", True, None, []),
            (a3, "Support", "role", True, None, []),
        ]),
        _result(rows=[]),  # alerts
    ])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            "/api/v1/agents/graph",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["nodes"]) == 3
    assert len(body["edges"]) == 2
    assert body["edges"][0]["source"] == str(a1)


# ---------------------------------------------------------------------------
# 14. GET /api/v1/agents/graph — empty tenant returns empty
# ---------------------------------------------------------------------------


def test_get_graph_empty_tenant(client):
    eng = _mock_engine_with_rows([_result(rows=[]), _result(rows=[])])
    pat_tok, pat_mem, pat_load = _patch_auth("admin")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            "/api/v1/agents/graph",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == []
    assert body["edges"] == []


# ---------------------------------------------------------------------------
# 15. unauthorized member can read graph but cannot mutate
# ---------------------------------------------------------------------------


def test_member_can_view_graph(client):
    eng = _mock_engine_with_rows([_result(rows=[]), _result(rows=[])])
    pat_tok, pat_mem, pat_load = _patch_auth("member")
    with pat_tok, pat_mem, pat_load, patch(
        "src.api.routers.agent_management._get_engine", return_value=eng
    ):
        r = client.get(
            "/api/v1/agents/graph",
            headers={"Authorization": f"Bearer {_member_token()}"},
        )
    assert r.status_code == 200
