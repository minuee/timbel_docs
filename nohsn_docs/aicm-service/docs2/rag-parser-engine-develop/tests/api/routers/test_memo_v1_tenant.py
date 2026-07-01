"""Cross-tenant isolation tests for memo_v1 endpoints.

Verifies that unregister / register / CRUD endpoints reject access to
another tenant's memo data and return 404 (no existence leak).

Uses unit-level mocks — no live DB required.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TENANT_A = str(uuid4())
_TENANT_B = str(uuid4())
_MEMO_ID = str(uuid4())
_DOC_ID = str(uuid4())

_ARGS_TENANT_A: dict[str, Any] = {
    "phone": "e:tenant_a@example.com",
    "tenant_id": _TENANT_A,
}

_TOKEN_A = "Bearer token_a"


def _make_resolve_args(args: dict[str, Any]) -> AsyncMock:
    return AsyncMock(return_value=args)


def _make_account_id_from_bearer(account_id: str) -> MagicMock:
    return MagicMock(return_value=account_id)


def _make_engine(row_list: list) -> MagicMock:
    """Build a MagicMock engine whose .begin() acts as an async context manager.

    The inner conn.execute() returns a result whose .all() returns `row_list`.
    """
    result = MagicMock()
    result.all.return_value = row_list

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def _begin():
        yield conn

    engine = MagicMock()
    engine.begin = _begin
    return engine


# ---------------------------------------------------------------------------
# unregister — cross-tenant must return 404
# ---------------------------------------------------------------------------


def test_unregister_other_tenant_memo_returns_404():
    """Tenant A token targeting Tenant B memo → 404 (cross-tenant blocked).

    The UPDATE WHERE clause includes tenant_id = A, so Tenant B's document
    returns 0 rows → endpoint raises 404 (no existence leak).
    """
    engine = _make_engine([])  # 0 rows: tenant mismatch

    with (
        patch(
            "src.api.routers.memo_v1._account_id_from_bearer",
            _make_account_id_from_bearer("account_a"),
        ),
        patch(
            "src.api.routers.memo_v1._resolve_args",
            _make_resolve_args(_ARGS_TENANT_A),
        ),
        patch("src.api.routers.memo_v1._eng", return_value=engine),
    ):
        r = client.delete(
            f"/api/v1/memo/{_MEMO_ID}/register-knowledge",
            headers={"authorization": _TOKEN_A},
        )

    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


def test_unregister_own_tenant_memo_works_normally():
    """Tenant A token targeting Tenant A memo → 200, unregistered_count == 1."""
    engine = _make_engine([(_DOC_ID,)])  # 1 row matched

    with (
        patch(
            "src.api.routers.memo_v1._account_id_from_bearer",
            _make_account_id_from_bearer("account_a"),
        ),
        patch(
            "src.api.routers.memo_v1._resolve_args",
            _make_resolve_args(_ARGS_TENANT_A),
        ),
        patch("src.api.routers.memo_v1._eng", return_value=engine),
    ):
        r = client.delete(
            f"/api/v1/memo/{_MEMO_ID}/register-knowledge",
            headers={"authorization": _TOKEN_A},
        )

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json()["unregistered_count"] == 1


# ---------------------------------------------------------------------------
# register — cross-tenant protection via memo_store scope
# ---------------------------------------------------------------------------


def test_register_other_tenant_memo_returns_404():
    """Register: memo_store scoped to account → Tenant B memo not visible → 404."""
    with (
        patch(
            "src.api.routers.memo_v1._account_id_from_bearer",
            _make_account_id_from_bearer("account_a"),
        ),
        patch(
            "src.api.routers.memo_v1._resolve_args",
            _make_resolve_args(_ARGS_TENANT_A),
        ),
        patch(
            "src.api.routers.memo_v1.memo_store.list_all",
            AsyncMock(return_value={"items": []}),
        ),
    ):
        r = client.post(
            f"/api/v1/memo/{_MEMO_ID}/register-knowledge",
            headers={"authorization": _TOKEN_A},
        )

    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


def test_register_own_tenant_memo_returns_ok():
    """Register: own memo found → document inserted → 200."""
    target_memo = {
        "id": _MEMO_ID,
        "title": "내 메모",
        "note": "내용",
        "deadline_at": None,
        "alarm_at": None,
        "raw_utterance": None,
    }
    engine = _make_engine([])  # INSERT doesn't return rows; all() unused here

    with (
        patch(
            "src.api.routers.memo_v1._account_id_from_bearer",
            _make_account_id_from_bearer("account_a"),
        ),
        patch(
            "src.api.routers.memo_v1._resolve_args",
            _make_resolve_args(_ARGS_TENANT_A),
        ),
        patch(
            "src.api.routers.memo_v1.memo_store.list_all",
            AsyncMock(return_value={"items": [target_memo]}),
        ),
        patch(
            "src.api.routers.memo_v1._get_or_create_memo_kb_repo",
            AsyncMock(return_value=str(uuid4())),
        ),
        patch("src.api.routers.memo_v1._eng", return_value=engine),
    ):
        r = client.post(
            f"/api/v1/memo/{_MEMO_ID}/register-knowledge",
            headers={"authorization": _TOKEN_A},
        )

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert data["memo_id"] == str(_MEMO_ID)
    assert data["title"] == "내 메모"


# ---------------------------------------------------------------------------
# update — delegated to memo_store (phone-scoped per account)
# ---------------------------------------------------------------------------


def test_update_other_tenant_memo_no_data_leaked():
    """Update: memo_store phone-scoped to Tenant A — Tenant B memo not exposed.

    memo_store.update returns an empty/error result for an unknown memo_id.
    The endpoint returns 200 but the body contains no Tenant B data.
    """
    with (
        patch(
            "src.api.routers.memo_v1._account_id_from_bearer",
            _make_account_id_from_bearer("account_a"),
        ),
        patch(
            "src.api.routers.memo_v1._resolve_args",
            _make_resolve_args(_ARGS_TENANT_A),
        ),
        patch(
            "src.api.routers.memo_v1.memo_store.update",
            AsyncMock(return_value={"error": "not found", "items": []}),
        ),
    ):
        r = client.patch(
            f"/api/v1/memo/{_MEMO_ID}",
            json={"title": "hacked"},
            headers={"authorization": _TOKEN_A},
        )

    assert r.status_code == 200
    body = r.json()
    # Must not expose other-tenant memo data
    assert "hacked" not in json.dumps(body)
