"""Supervisor pattern — crash 회복 + clean exit 정책."""

import asyncio
import pytest

from src.pipeline.workers.main import _consumer_supervisor, _SHUTDOWN_EVENT


@pytest.fixture(autouse=True)
def _reset_shutdown():
    _SHUTDOWN_EVENT.clear()
    yield
    _SHUTDOWN_EVENT.clear()


@pytest.mark.asyncio
async def test_crash_triggers_restart():
    """run_fn 이 Exception 으로 죽으면 backoff 후 재시작."""
    from src.pipeline.workers import main as main_mod
    main_mod._CONSUMER_BACKOFF_INITIAL_SEC = 0.01  # type: ignore
    main_mod._CONSUMER_BACKOFF_MAX_SEC = 0.05  # type: ignore

    attempts = []

    async def crashing():
        attempts.append("attempt")
        if len(attempts) < 3:
            raise RuntimeError("boom")
        _SHUTDOWN_EVENT.set()

    await _consumer_supervisor("test", crashing)
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_silent_exit_treated_as_crash():
    """run_fn 이 예외 없이 return + SHUTDOWN_EVENT 안 set → crash 취급 재시작."""
    from src.pipeline.workers import main as main_mod
    main_mod._CONSUMER_BACKOFF_INITIAL_SEC = 0.01  # type: ignore
    main_mod._CONSUMER_BACKOFF_MAX_SEC = 0.05  # type: ignore

    attempts = []

    async def silent():
        attempts.append("attempt")
        if len(attempts) >= 3:
            _SHUTDOWN_EVENT.set()
        # 예외 없이 return — supervisor 가 crash 로 취급해야

    await _consumer_supervisor("test", silent)
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_clean_exit_on_shutdown():
    """SHUTDOWN_EVENT set + run_fn return → 정상 종료, attempts=1."""
    attempts = []

    async def clean():
        attempts.append("attempt")
        _SHUTDOWN_EVENT.set()

    await _consumer_supervisor("test", clean)
    assert len(attempts) == 1
