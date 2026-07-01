"""D35 §2 (#215) — _worker_rls_self_check fatal exit unit test.

검증:
- KMS_DB_ROLE=app + RLS_ENFORCE=true + bypass=True → SystemExit(99) raise.
- KMS_DB_ROLE=migration + bypass=True → fatal X (warning).
- KMS_DB_ROLE=super + bypass=True → fatal X (warning).
- RLS_ENFORCE=false + bypass=True → fatal X (info).
- bypass=False (정상 운영) → fatal X (info).
- bypass=None (DB query 실패) → fatal X (warning).
- DB query 자체 실패 → worker 차단 X (warning + 진행).

GPT-5 false positive 회피 절칙: migration/super/RLS_ENFORCE=false 모두 fatal X.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_row(current_user: str, bypassrls: bool | None) -> tuple:
    """fetchone() 응답 mock — (current_user, bypassrls)."""
    return (current_user, bypassrls)


@asynccontextmanager
async def _mock_session_with_row(row: tuple | None):
    """async_session_factory() 가 반환할 session mock — execute().fetchone() 패치."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchone = MagicMock(return_value=row)
    session.execute = AsyncMock(return_value=result)
    yield session


def _patched_session_factory(row: tuple | None):
    """async_session_factory 가 호출되면 row 반환하는 context manager 생성."""
    def _factory():
        return _mock_session_with_row(row)
    return _factory


@asynccontextmanager
async def _noop_bind_system_scope(*args, **kwargs):
    yield


@pytest.mark.asyncio
async def test_fatal_when_app_role_and_enforce_and_bypass_true(monkeypatch) -> None:
    """KMS_DB_ROLE=app + RLS_ENFORCE=true + bypass=True → SystemExit(99)."""
    from src.pipeline.workers import main as wmain

    # settings mock — KMS_DB_ROLE=app, RLS_ENFORCE=true.
    fake_settings = MagicMock()
    fake_settings.KMS_DB_ROLE = "app"
    fake_settings.RLS_ENFORCE = True
    monkeypatch.setattr(wmain, "settings", fake_settings)

    # database mock — bypass=True.
    fake_db_module = MagicMock()
    fake_db_module.async_session_factory = _patched_session_factory(
        _make_row("kms_app_overridden", True)
    )

    with patch.dict(
        "sys.modules", {"src.core.database": fake_db_module}
    ), patch.object(wmain, "bind_system_scope", _noop_bind_system_scope):
        with pytest.raises(SystemExit) as exc_info:
            await wmain._worker_rls_self_check()
    assert exc_info.value.code == 99


@pytest.mark.asyncio
async def test_no_fatal_when_migration_role_with_bypass_true(monkeypatch) -> None:
    """KMS_DB_ROLE=migration + bypass=True → fatal X (의도된 BYPASSRLS)."""
    from src.pipeline.workers import main as wmain

    fake_settings = MagicMock()
    fake_settings.KMS_DB_ROLE = "migration"
    fake_settings.RLS_ENFORCE = True
    monkeypatch.setattr(wmain, "settings", fake_settings)

    fake_db_module = MagicMock()
    fake_db_module.async_session_factory = _patched_session_factory(
        _make_row("kms_migration", True)
    )

    with patch.dict(
        "sys.modules", {"src.core.database": fake_db_module}
    ), patch.object(wmain, "bind_system_scope", _noop_bind_system_scope):
        await wmain._worker_rls_self_check()  # SystemExit X.


@pytest.mark.asyncio
async def test_no_fatal_when_super_role_with_bypass_true(monkeypatch) -> None:
    """KMS_DB_ROLE=super + bypass=True → fatal X."""
    from src.pipeline.workers import main as wmain

    fake_settings = MagicMock()
    fake_settings.KMS_DB_ROLE = "super"
    fake_settings.RLS_ENFORCE = True
    monkeypatch.setattr(wmain, "settings", fake_settings)

    fake_db_module = MagicMock()
    fake_db_module.async_session_factory = _patched_session_factory(
        _make_row("postgres", True)
    )

    with patch.dict(
        "sys.modules", {"src.core.database": fake_db_module}
    ), patch.object(wmain, "bind_system_scope", _noop_bind_system_scope):
        await wmain._worker_rls_self_check()


@pytest.mark.asyncio
async def test_no_fatal_when_rls_enforce_false(monkeypatch) -> None:
    """RLS_ENFORCE=false + KMS_DB_ROLE=app + bypass=True → fatal X."""
    from src.pipeline.workers import main as wmain

    fake_settings = MagicMock()
    fake_settings.KMS_DB_ROLE = "app"
    fake_settings.RLS_ENFORCE = False
    monkeypatch.setattr(wmain, "settings", fake_settings)

    fake_db_module = MagicMock()
    fake_db_module.async_session_factory = _patched_session_factory(
        _make_row("kms_app", True)
    )

    with patch.dict(
        "sys.modules", {"src.core.database": fake_db_module}
    ), patch.object(wmain, "bind_system_scope", _noop_bind_system_scope):
        await wmain._worker_rls_self_check()


@pytest.mark.asyncio
async def test_no_fatal_when_bypass_false(monkeypatch) -> None:
    """bypass=False (정상 kms_app 운영) → fatal X (info log)."""
    from src.pipeline.workers import main as wmain

    fake_settings = MagicMock()
    fake_settings.KMS_DB_ROLE = "app"
    fake_settings.RLS_ENFORCE = True
    monkeypatch.setattr(wmain, "settings", fake_settings)

    fake_db_module = MagicMock()
    fake_db_module.async_session_factory = _patched_session_factory(
        _make_row("kms_app", False)
    )

    with patch.dict(
        "sys.modules", {"src.core.database": fake_db_module}
    ), patch.object(wmain, "bind_system_scope", _noop_bind_system_scope):
        await wmain._worker_rls_self_check()


@pytest.mark.asyncio
async def test_no_fatal_when_bypass_none(monkeypatch) -> None:
    """bypass=None (DB role 조회 실패) → fatal X (warning + 진행)."""
    from src.pipeline.workers import main as wmain

    fake_settings = MagicMock()
    fake_settings.KMS_DB_ROLE = "app"
    fake_settings.RLS_ENFORCE = True
    monkeypatch.setattr(wmain, "settings", fake_settings)

    fake_db_module = MagicMock()
    fake_db_module.async_session_factory = _patched_session_factory(
        _make_row("kms_app", None)
    )

    with patch.dict(
        "sys.modules", {"src.core.database": fake_db_module}
    ), patch.object(wmain, "bind_system_scope", _noop_bind_system_scope):
        await wmain._worker_rls_self_check()


@pytest.mark.asyncio
async def test_no_crash_when_db_query_raises(monkeypatch) -> None:
    """DB query 자체 실패 → worker 차단 X (warning log + 진행)."""
    from src.pipeline.workers import main as wmain

    fake_settings = MagicMock()
    fake_settings.KMS_DB_ROLE = "app"
    fake_settings.RLS_ENFORCE = True
    monkeypatch.setattr(wmain, "settings", fake_settings)

    @asynccontextmanager
    async def _raising_session(*args, **kwargs):
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("DB unreachable"))
        yield session

    fake_db_module = MagicMock()
    fake_db_module.async_session_factory = lambda: _raising_session()

    with patch.dict(
        "sys.modules", {"src.core.database": fake_db_module}
    ), patch.object(wmain, "bind_system_scope", _noop_bind_system_scope):
        # SystemExit 안 발생 — exception 흡수.
        await wmain._worker_rls_self_check()


def test_flush_logging_handlers_no_crash() -> None:
    """_flush_logging_handlers — 항상 안전 (예외 흡수)."""
    from src.pipeline.workers.main import _flush_logging_handlers

    # 호출 자체가 안전 — root + 비루트 logger + stdout/stderr + shutdown.
    _flush_logging_handlers()
