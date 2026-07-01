"""CronRunner 단위 테스트 — 짧은 interval 로 동작 확인."""
import asyncio
import pytest

from src.agent_framework.scheduler.cron_runner import CronRunner


@pytest.mark.asyncio
async def test_register_and_fire():
    """interval 1초로 1.5초 대기 → job 최소 1회 실행."""
    runner = CronRunner()
    counter = {"n": 0}

    async def job():
        counter["n"] += 1

    # cron 대신 interval (테스트용)
    runner.scheduler.add_job(job, "interval", seconds=1, id="test_tick")
    runner.start()
    await asyncio.sleep(1.5)
    runner.shutdown()
    assert counter["n"] >= 1


@pytest.mark.asyncio
async def test_shutdown_safe_when_not_started():
    """start 안 한 상태에서 shutdown 호출해도 예외 없음."""
    runner = CronRunner()
    runner.shutdown()


@pytest.mark.asyncio
async def test_register_cron_expression():
    """실 cron 표현식 등록 (실행 안 하고 스케줄 등록만 확인)."""
    runner = CronRunner()

    async def job():
        pass

    runner.register("0 8 * * *", job, "daily_test")
    jobs = runner.scheduler.get_jobs()
    assert any(j.id == "daily_test" for j in jobs)
