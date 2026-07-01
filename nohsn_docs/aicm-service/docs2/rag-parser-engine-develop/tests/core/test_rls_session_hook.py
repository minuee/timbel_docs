"""D25 (#158) — RLS session hook (SQLAlchemy ``begin`` event) unit tests.

D25 spec §3 — ``_rls_set_session_vars`` event listener 가 contextvar 의 RLSContext
를 ``SET LOCAL`` 명령으로 발행하는지 검증.

실 DB 없이 Mock connection 으로 ``exec_driver_sql`` 호출 매트릭스 검증.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.api.middleware.rls_context import (
    RLSContext,
    reset_rls_context,
    set_rls_context,
)


def _invoke_hook(mock_conn: MagicMock) -> None:
    """database 모듈의 _rls_set_session_vars 직접 호출 (event 미사용 path)."""
    from src.core.database import _rls_set_session_vars

    _rls_set_session_vars(mock_conn)


def _params_flat(mock_conn: MagicMock) -> list[str]:
    """conn.execute(text_sql, {"v": value}) 호출 인자에서 value 값 추출."""
    return [c.args[1]["v"] for c in mock_conn.execute.call_args_list]


def _sqls(mock_conn: MagicMock) -> list[str]:
    """conn.execute(text_sql, {"v": value}) 호출의 text_sql 의 문자열 표현."""
    return [str(c.args[0]) for c in mock_conn.execute.call_args_list]


def test_hook_no_context_skips() -> None:
    """contextvar 없으면 SET LOCAL 발행 0."""
    mock_conn = MagicMock()
    _invoke_hook(mock_conn)
    assert mock_conn.execute.call_count == 0


def test_hook_agent_scope_emits_three_set_local() -> None:
    """agent scope context — 3 set_config 발행 (bind param 안전, text())."""
    ctx = RLSContext(
        agent_id="11111111-1111-1111-1111-111111111111",
        scope="agent",
        tenant_id="22222222-2222-2222-2222-222222222222",
    )
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        _invoke_hook(mock_conn)
        # 3 conn.execute calls expected.
        assert mock_conn.execute.call_count == 3
        sqls = _sqls(mock_conn)
        for sql in sqls:
            assert "set_config" in sql
            assert ":v" in sql
        flat = _params_flat(mock_conn)
        assert "11111111-1111-1111-1111-111111111111" in flat
        assert "agent" in flat
        assert "22222222-2222-2222-2222-222222222222" in flat
    finally:
        reset_rls_context(token)


def test_hook_admin_scope_emits_set_local() -> None:
    """admin scope — agent_id 빈 + scope=admin + tenant_id."""
    ctx = RLSContext(
        agent_id=None,
        scope="admin",
        tenant_id="33333333-3333-3333-3333-333333333333",
    )
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        _invoke_hook(mock_conn)
        flat = _params_flat(mock_conn)
        # admin scope: agent_id 빈, scope='admin', tenant_id=33333...
        assert "" in flat  # agent_id 빈
        assert "admin" in flat
        assert "33333333-3333-3333-3333-333333333333" in flat
    finally:
        reset_rls_context(token)


def test_hook_superadmin_scope() -> None:
    """superadmin scope — cross-tenant (tenant_id 빈 가능)."""
    ctx = RLSContext(agent_id=None, scope="superadmin", tenant_id=None)
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        _invoke_hook(mock_conn)
        flat = _params_flat(mock_conn)
        assert "superadmin" in flat
        # agent_id, tenant_id 모두 빈
        assert flat.count("") >= 2
    finally:
        reset_rls_context(token)


def test_hook_sql_injection_safe_via_bind_param() -> None:
    """ctx 의 값이 SQL 메타문자를 포함해도 bind param 으로 안전."""
    ctx = RLSContext(
        agent_id="abc'; DROP TABLE users;--",
        scope="agent",
        tenant_id=None,
    )
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        _invoke_hook(mock_conn)
        sqls = _sqls(mock_conn)
        for sql in sqls:
            assert "DROP TABLE" not in sql
            assert "set_config" in sql
        flat = _params_flat(mock_conn)
        # 위험 문자열은 params 에만 존재
        assert "abc'; DROP TABLE users;--" in flat
    finally:
        reset_rls_context(token)


def test_hook_exception_swallowed() -> None:
    """hook 자체 실패 시 application 전체 fail 회피 (rollout phase 1 안전)."""
    ctx = RLSContext(agent_id="x", scope="agent", tenant_id="t")
    token = set_rls_context(ctx)
    try:
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = RuntimeError("fake DB failure")
        # 예외 swallow 확인 — 호출 자체가 raise 안 함.
        _invoke_hook(mock_conn)
    finally:
        reset_rls_context(token)
