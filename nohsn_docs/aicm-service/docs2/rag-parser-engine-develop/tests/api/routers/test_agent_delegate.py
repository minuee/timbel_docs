"""Phase 1.5B-γ — agents PATCH delegate_to_agent_ids 검증.

테스트 케이스:
- 정상 위임 등록 (admin 이 PATCH).
- 자기 자신 위임 거부 (400).
- 순환 위임 거부 (A → B → A) (400).
- 다른 tenant 의 agent 거부 (400).
- max_depth=3 초과 거부 (400).
- non-admin (member, owner) 편집 거부 (403).
- list/get 응답에 delegate_to_agent_ids 노출.

create_agent / update_agent 에서 _validate_delegate_targets 가 검증을
수행. DB 에 직접 의존하지 않도록 _get_engine 를 mock.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.auth.jwt_utils import create_access_token


TENANT_ID = str(uuid.uuid4())
OTHER_TENANT_ID = str(uuid.uuid4())
ADMIN_ID = str(uuid.uuid4())
AGENT_A = str(uuid.uuid4())
AGENT_B = str(uuid.uuid4())
AGENT_C = str(uuid.uuid4())
AGENT_D = str(uuid.uuid4())
AGENT_OTHER = str(uuid.uuid4())  # 다른 tenant 의 agent


def _admin_token() -> str:
    return create_access_token(subject=ADMIN_ID, tenant_id=TENANT_ID, role="admin")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _patch_auth(role: str = "admin"):
    """JWT/membership mock — role 을 admin 외 값으로 바꿔 non-admin 시뮬레이션."""
    return (
        patch(
            "src.api.routers.agents_v1._account_from_token",
            return_value=(uuid.UUID(ADMIN_ID), TENANT_ID, role),
        ),
        patch(
            "src.api.routers.agents_v1._verify_membership",
            new=AsyncMock(return_value=role),
        ),
    )


def _agent_row(agent_id: str, tenant_id: str = TENANT_ID, kind: str = "role"):
    """SELECT _AGENT_COLS 결과 row 형식 — 15개 컬럼."""
    return (
        uuid.UUID(agent_id),
        uuid.UUID(tenant_id),
        f"Agent-{agent_id[:6]}",
        "desc",
        "",  # persona
        "",  # system_prompt
        [],  # allowed_skills
        [],  # allowed_repos
        True,  # is_active
        60,  # rate_limit
        uuid.UUID(ADMIN_ID),  # created_by
        None,  # created_at
        None,  # updated_at
        kind,
        [],  # delegate_to_agent_ids
    )


def _engine_for_patch_validation(
    *,
    target_agent_row,
    tenant_active_ids: list[str],
    graph: dict[str, list[str]] | None = None,
):
    """update_agent 호출 흐름:
      1. _load_agent (_load_agent_for_tenant 내부) — SELECT row.
      2. _validate_delegate_targets (delegate_ids 가 있을 때만) —
         a) tenant + active SELECT (id IN ANY).
         b) _check_cycle_and_depth — 모든 active agent SELECT.
      3. UPDATE.
      4. _load_agent — SELECT row (return).

    각 SELECT/UPDATE 마다 conn.execute 호출 — side_effect 순차 응답.
    """
    if graph is None:
        graph = {}
    # mock execute 결과 객체.
    def mk_first(row):
        m = MagicMock()
        m.first.return_value = row
        return m

    def mk_iter(rows):
        m = MagicMock()
        m.__iter__ = lambda self: iter(rows)
        return m

    # 시퀀스: load(SELECT first) → validate-tenant(iter) → cycle(iter) → UPDATE → load(SELECT first)
    load_row1 = mk_first(target_agent_row)
    tenant_check_rows = mk_iter([(uuid.UUID(x),) for x in tenant_active_ids])
    cycle_rows = mk_iter(
        [(uuid.UUID(k), [uuid.UUID(v) for v in vs]) for k, vs in graph.items()]
    )
    update_result = MagicMock()
    update_result.rowcount = 1
    load_row2 = mk_first(target_agent_row)

    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = [
        load_row1,
        tenant_check_rows,
        cycle_rows,
        update_result,
        load_row2,
    ]

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None

    mock_eng = MagicMock()
    mock_eng.begin.return_value = mock_ctx
    return mock_eng


# ---------------------------------------------------------------------------


def test_patch_delegate_normal(client):
    """admin 이 정상 위임 등록 — 200."""
    pat_tok, pat_mem = _patch_auth("admin")
    target_row = _agent_row(AGENT_A, kind="admin")
    mock_eng = _engine_for_patch_validation(
        target_agent_row=target_row,
        tenant_active_ids=[AGENT_B],  # B 가 같은 tenant 의 active.
        graph={AGENT_B: []},  # B 는 위임 없음 — cycle/depth 안전.
    )
    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._get_engine", return_value=mock_eng
    ):
        r = client.patch(
            f"/api/v1/agents/{AGENT_A}",
            json={"delegate_to_agent_ids": [AGENT_B]},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text


def test_patch_delegate_self_rejected(client):
    """자기 자신 위임 — 400."""
    pat_tok, pat_mem = _patch_auth("admin")
    target_row = _agent_row(AGENT_A, kind="admin")
    # self check 는 _validate_delegate_targets 의 첫 단계 — load 후 즉시 reject.
    # _load_agent (1 SELECT) 만 호출되므로 simpler mock.
    load_row1 = MagicMock()
    load_row1.first.return_value = target_row

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = load_row1
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_eng = MagicMock()
    mock_eng.begin.return_value = mock_ctx

    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._get_engine", return_value=mock_eng
    ):
        r = client.patch(
            f"/api/v1/agents/{AGENT_A}",
            json={"delegate_to_agent_ids": [AGENT_A]},  # self
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400, r.text
    assert "itself" in r.json().get("detail", "").lower()


def test_patch_delegate_cycle_rejected(client):
    """A → B → A — cycle 거부, 400."""
    pat_tok, pat_mem = _patch_auth("admin")
    target_row = _agent_row(AGENT_A, kind="admin")
    # graph: 기존 B → A. 신규로 A → B 시도하면 A → B → A cycle.
    mock_eng = _engine_for_patch_validation(
        target_agent_row=target_row,
        tenant_active_ids=[AGENT_B],
        graph={AGENT_B: [AGENT_A]},  # B 가 A 를 이미 위임 중.
    )
    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._get_engine", return_value=mock_eng
    ):
        r = client.patch(
            f"/api/v1/agents/{AGENT_A}",
            json={"delegate_to_agent_ids": [AGENT_B]},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400, r.text
    assert "circular" in r.json().get("detail", "").lower()


def test_patch_delegate_other_tenant_rejected(client):
    """다른 tenant 의 agent 위임 — 400."""
    pat_tok, pat_mem = _patch_auth("admin")
    target_row = _agent_row(AGENT_A, kind="admin")
    # tenant_active_ids 가 비어 있으면 AGENT_OTHER 는 invalid.
    mock_eng = _engine_for_patch_validation(
        target_agent_row=target_row,
        tenant_active_ids=[],  # AGENT_OTHER 는 같은 tenant active 가 아님.
        graph={},
    )
    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._get_engine", return_value=mock_eng
    ):
        r = client.patch(
            f"/api/v1/agents/{AGENT_A}",
            json={"delegate_to_agent_ids": [AGENT_OTHER]},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400, r.text
    assert "not in same tenant" in r.json().get("detail", "").lower()


def test_patch_delegate_depth_exceeded_rejected(client):
    """A → B → C → D → E (depth 4) 시도 — max_depth=3 초과로 거부, 400.

    A 가 B 에 위임. 기존 graph 에 B → C → D → E (chain depth 4).
    A 부터 시작하면 path = [A, B, C, D, E] — 노드 수 5, depth 4 초과.
    """
    pat_tok, pat_mem = _patch_auth("admin")
    target_row = _agent_row(AGENT_A, kind="admin")
    AGENT_E = str(uuid.uuid4())
    mock_eng = _engine_for_patch_validation(
        target_agent_row=target_row,
        tenant_active_ids=[AGENT_B],
        graph={
            AGENT_B: [AGENT_C],
            AGENT_C: [AGENT_D],
            AGENT_D: [AGENT_E],
            AGENT_E: [],
        },
    )
    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._get_engine", return_value=mock_eng
    ):
        r = client.patch(
            f"/api/v1/agents/{AGENT_A}",
            json={"delegate_to_agent_ids": [AGENT_B]},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400, r.text
    assert "too deep" in r.json().get("detail", "").lower()


def test_patch_delegate_non_admin_rejected(client):
    """member role 이 delegate_to_agent_ids 편집 시도 — 403.

    member 는 _verify_membership 에서 이미 owner/admin 체크에 막힘.
    """
    pat_tok, pat_mem = _patch_auth("member")
    with pat_tok, pat_mem:
        r = client.patch(
            f"/api/v1/agents/{AGENT_A}",
            json={"delegate_to_agent_ids": [AGENT_B]},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 403, r.text
    assert "owner or admin" in r.json().get("detail", "").lower()


def test_patch_delegate_owner_rejected(client):
    """owner role 도 delegate_to_agent_ids 편집 거부 — 403 (admin 만 편집 가능)."""
    pat_tok, pat_mem = _patch_auth("owner")
    target_row = _agent_row(AGENT_A, kind="admin")
    # _load_agent_for_tenant 1번 통과 — 그 다음 admin role check 에서 reject.
    load_row1 = MagicMock()
    load_row1.first.return_value = target_row
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = load_row1
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_eng = MagicMock()
    mock_eng.begin.return_value = mock_ctx

    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._get_engine", return_value=mock_eng
    ):
        r = client.patch(
            f"/api/v1/agents/{AGENT_A}",
            json={"delegate_to_agent_ids": [AGENT_B]},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 403, r.text
    assert "admin" in r.json().get("detail", "").lower()


def test_get_agent_returns_delegate_field(client):
    """GET 응답에 delegate_to_agent_ids 필드 포함."""
    pat_tok, pat_mem = _patch_auth("admin")
    # target row 의 마지막 필드 = delegate_to_agent_ids = [B uuid].
    row_with_delegates = list(_agent_row(AGENT_A, kind="admin"))
    row_with_delegates[14] = [uuid.UUID(AGENT_B)]
    load_first = MagicMock()
    load_first.first.return_value = tuple(row_with_delegates)
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = load_first
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_ctx.__aexit__.return_value = None
    mock_eng = MagicMock()
    mock_eng.begin.return_value = mock_ctx

    with pat_tok, pat_mem, patch(
        "src.api.routers.agents_v1._get_engine", return_value=mock_eng
    ):
        r = client.get(
            f"/api/v1/agents/{AGENT_A}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "delegate_to_agent_ids" in body
    assert body["delegate_to_agent_ids"] == [AGENT_B]
