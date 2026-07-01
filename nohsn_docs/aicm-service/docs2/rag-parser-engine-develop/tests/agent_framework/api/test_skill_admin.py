"""Task 24 — 스킬 admin API 통합 테스트."""
import pytest
from httpx import AsyncClient, ASGITransport

from src.agent_framework.api.dependencies import get_agent_engine
from src.agent_framework.runtime.engine import SKILLS_DIR
from src.agent_framework.runtime.loader import load_all_skills
from src.api.main import app


class _LightEngine:
    """Redis/vLLM 없이 스킬만 로드하는 가벼운 엔진 스텁 (skill_admin 전용)."""

    def __init__(self):
        self.skills = load_all_skills(SKILLS_DIR)


@pytest.fixture(autouse=True)
def _override_engine():
    app.dependency_overrides[get_agent_engine] = lambda: _LightEngine()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_agent_engine, None)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_list_skills_returns_all_4():
    async with await _client() as c:
        resp = await c.get("/agent/skills/list")
        assert resp.status_code == 200
        skills = resp.json()
        ids = {s["id"] for s in skills}
        assert "appointment_derm" in ids
        assert "schedule_personal" in ids
        assert "diary_personal" in ids
        assert "news_daily_report" in ids


@pytest.mark.asyncio
async def test_list_skills_includes_triggers():
    async with await _client() as c:
        resp = await c.get("/agent/skills/list")
        derm = next(s for s in resp.json() if s["id"] == "appointment_derm")
        assert "book_appointment" in derm["triggers"]
        assert "ask_treatment" in derm["triggers"]


@pytest.mark.asyncio
async def test_get_yaml_returns_content():
    async with await _client() as c:
        resp = await c.get("/agent/skills/appointment_derm/yaml")
        assert resp.status_code == 200
        body = resp.json()
        assert body["skill_id"] == "appointment_derm"
        assert "id: appointment_derm" in body["yaml"]
        assert "triggers:" in body["yaml"]


@pytest.mark.asyncio
async def test_get_yaml_404_unknown():
    async with await _client() as c:
        resp = await c.get("/agent/skills/nonexistent_skill_xyz/yaml")
        assert resp.status_code == 404
