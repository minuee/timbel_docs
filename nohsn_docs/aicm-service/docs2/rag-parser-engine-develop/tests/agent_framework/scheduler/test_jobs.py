"""APScheduler default jobs (델타 #5 / KMS-Plus Phase 1).

register_default_jobs 가
- freshness_cross_scan, ccpair_reprobe 두 잡을 등록하고
- 중복 호출 시에도 replace_existing 으로 단 한 번만 등록되는지 확인.
"""
from __future__ import annotations

import pytest

from src.agent_framework.scheduler.jobs import (
    get_scheduler,
    register_default_jobs,
    reset_scheduler,
)


@pytest.fixture(autouse=True)
def _isolated_scheduler():
    """매 테스트마다 깨끗한 싱글턴 스케줄러를 보장."""
    reset_scheduler()
    yield
    reset_scheduler()


def test_register_default_jobs_adds_two_cron():
    async def fresh():  # pragma: no cover - 호출되지 않음
        pass

    async def probe():  # pragma: no cover - 호출되지 않음
        pass

    register_default_jobs(freshness_runner=fresh, probe_runner=probe)
    sched = get_scheduler()
    ids = {j.id for j in sched.get_jobs()}
    assert "freshness_cross_scan" in ids
    assert "ccpair_reprobe" in ids


def test_replace_existing_does_not_duplicate():
    async def fresh():  # pragma: no cover
        pass

    async def probe():  # pragma: no cover
        pass

    register_default_jobs(freshness_runner=fresh, probe_runner=probe)
    register_default_jobs(freshness_runner=fresh, probe_runner=probe)
    sched = get_scheduler()
    fr_jobs = [j for j in sched.get_jobs() if j.id == "freshness_cross_scan"]
    pr_jobs = [j for j in sched.get_jobs() if j.id == "ccpair_reprobe"]
    assert len(fr_jobs) == 1
    assert len(pr_jobs) == 1


# Phase 8 (KMS-Plus) — placeholder no-op → 실 runner.
# 실 DB 호출은 안 하고 callable / coroutine 여부만 검증.
# 이름이 _run_* 으로 module-private 이지만 main.py 에서 import 사용.


def test_real_runners_are_callable():
    """_run_freshness_all_tenants / _run_ccpair_reprobe 가 import 가능 + callable."""
    from src.agent_framework.scheduler.jobs import (
        _run_ccpair_reprobe,
        _run_freshness_all_tenants,
    )

    assert callable(_run_freshness_all_tenants)
    assert callable(_run_ccpair_reprobe)


def test_real_runners_return_coroutines():
    """async def — 호출 시 coroutine 객체를 반환 (await 만 하지 않으면 부작용 없음)."""
    import inspect

    from src.agent_framework.scheduler.jobs import (
        _run_ccpair_reprobe,
        _run_freshness_all_tenants,
    )

    assert inspect.iscoroutinefunction(_run_freshness_all_tenants)
    assert inspect.iscoroutinefunction(_run_ccpair_reprobe)


def test_real_runners_swallow_db_errors(monkeypatch):
    """DB 미가용 시 (DATABASE_URL 미설정) 예외를 throw 하지 않는다.

    APScheduler 는 job 이 raise 하면 종료되므로, runner 자체는 graceful
    fallback 해야 한다.
    """
    import asyncio

    from src.agent_framework.scheduler import jobs as jobs_mod

    # DATABASE_URL 자체를 강제로 못 쓰는 값으로 바꿔도 graceful 해야.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://nope:nope@nope-host-9999.invalid/nope"
    )

    # 두 runner 모두 await 시 예외 없이 None 반환.
    asyncio.run(jobs_mod._run_freshness_all_tenants())
    asyncio.run(jobs_mod._run_ccpair_reprobe())


# ---------------------------------------------------------------------------
# Wave Wire-up Final (KMS-Plus, 2026-04-25) — KnowledgeFreshnessWorker 실 호출 wire.
# ---------------------------------------------------------------------------


def test_freshness_worker_wired_when_flag_on(monkeypatch):
    """KMS_FRESHNESS_WORKER_ENABLED=true 면 _run_freshness_via_worker 경로 진입.

    실 DB 안 쓰는 mock 으로 _run_freshness_via_worker 를 가로채고 호출 여부만 확인.
    """
    import asyncio

    from src.agent_framework.scheduler import jobs as jobs_mod

    called: dict[str, int] = {"count": 0}

    async def _fake_run_via_worker(eng, tenant_rows):
        called["count"] += 1

    # DATABASE_URL 미가용 → 위 try/except 가 흡수해 호출자 0 으로 끝나면 의미가 없음.
    # 대신 sqlalchemy create_engine 자체를 가짜로 패치해 tenant_rows 를 바로 흘려보낸다.
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@x/x")
    monkeypatch.setenv("KMS_FRESHNESS_WORKER_ENABLED", "true")

    class _FakeConn:
        def execute(self, *a, **k):
            class _R:
                def mappings(self):
                    return self

                def all(self):
                    return [{"id": "tnt1"}, {"id": "tnt2"}]

            return _R()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeEng:
        def connect(self):
            return _FakeConn()

        def begin(self):
            return _FakeConn()

        def dispose(self):
            pass

    def _fake_create_engine(*a, **k):
        return _FakeEng()

    monkeypatch.setattr(jobs_mod, "_run_freshness_via_worker", _fake_run_via_worker)
    # create_engine 은 지역 import 라 모듈 attr 패치 대신 sqlalchemy 자체 패치.
    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", _fake_create_engine)

    asyncio.run(jobs_mod._run_freshness_all_tenants())
    assert called["count"] == 1
