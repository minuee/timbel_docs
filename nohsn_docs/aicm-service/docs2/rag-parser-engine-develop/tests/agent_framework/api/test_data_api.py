"""Task 20 — Data API 엔드포인트 통합 테스트.

httpx.ASGITransport 로 FastAPI app 직접 호출. 각 테스트는 conftest 의
autouse fixture 로 mock 상태 자동 리셋.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# ── 일정 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedules_create_and_list():
    async with await _client() as c:
        resp = await c.post("/agent/data/schedules", json={
            "phone": "010-1", "title": "회의", "when": "2026-05-01T10:00",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        sid = data["id"]

        resp2 = await c.get("/agent/data/schedules", params={"phone": "010-1"})
        assert resp2.status_code == 200
        items = resp2.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == sid


@pytest.mark.asyncio
async def test_schedules_delete():
    async with await _client() as c:
        create = await c.post("/agent/data/schedules", json={
            "phone": "010-2", "title": "X", "when": "2026-05-01T10:00",
        })
        sid = create.json()["id"]

        del_resp = await c.delete(f"/agent/data/schedules/{sid}", params={"phone": "010-2"})
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        after = await c.get("/agent/data/schedules", params={"phone": "010-2"})
        assert after.json()["items"] == []


@pytest.mark.asyncio
async def test_schedules_scoped_by_phone():
    async with await _client() as c:
        await c.post("/agent/data/schedules", json={"phone": "010-A", "title": "A", "when": "2026-05-01T10:00"})
        await c.post("/agent/data/schedules", json={"phone": "010-B", "title": "B", "when": "2026-05-01T11:00"})
        a = (await c.get("/agent/data/schedules", params={"phone": "010-A"})).json()["items"]
        b = (await c.get("/agent/data/schedules", params={"phone": "010-B"})).json()["items"]
        assert len(a) == 1 and a[0]["title"] == "A"
        assert len(b) == 1 and b[0]["title"] == "B"


# ── 일기 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_diaries_create_and_search():
    async with await _client() as c:
        resp = await c.post("/agent/data/diaries", json={
            "phone": "010-3", "entry_text": "오늘 기분이 좋았다",
            "emotion": "기쁨", "date": "2026-04-23",
        })
        assert resp.status_code == 200
        list_resp = await c.get("/agent/data/diaries", params={"phone": "010-3", "query": "기분"})
        hits = list_resp.json()["hits"]
        assert len(hits) == 1
        assert hits[0]["emotion"] == "기쁨"


@pytest.mark.asyncio
async def test_diaries_filter_by_emotion():
    async with await _client() as c:
        await c.post("/agent/data/diaries", json={"phone": "010-4", "entry_text": "좋은 날", "emotion": "기쁨"})
        await c.post("/agent/data/diaries", json={"phone": "010-4", "entry_text": "우울한 날", "emotion": "슬픔"})
        list_resp = await c.get("/agent/data/diaries", params={"phone": "010-4", "emotion": "슬픔"})
        hits = list_resp.json()["hits"]
        assert len(hits) == 1
        assert hits[0]["text"] == "우울한 날"


@pytest.mark.asyncio
async def test_diaries_delete_404_unknown():
    async with await _client() as c:
        resp = await c.delete("/agent/data/diaries/nonexistent", params={"phone": "010-none"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diaries_delete_ok():
    async with await _client() as c:
        create = await c.post("/agent/data/diaries", json={"phone": "010-5", "entry_text": "X"})
        did = create.json()["id"]
        resp = await c.delete(f"/agent/data/diaries/{did}", params={"phone": "010-5"})
        assert resp.status_code == 200


# ── 뉴스 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_news_subscribe_and_get():
    async with await _client() as c:
        await c.post("/agent/data/news/subscriptions", json={"phone": "010-6", "topic": "AI 스타트업"})
        resp = await c.get("/agent/data/news", params={"phone": "010-6"})
        data = resp.json()
        assert "AI 스타트업" in data["subscription"]["topics"]
        assert data["recent_reports"] == []


@pytest.mark.asyncio
async def test_news_remove_subscription():
    async with await _client() as c:
        await c.post("/agent/data/news/subscriptions", json={"phone": "010-7", "topic": "X"})
        await c.post("/agent/data/news/subscriptions", json={"phone": "010-7", "topic": "Y"})
        # remove X
        resp = await c.request("DELETE", "/agent/data/news/subscriptions",
                                json={"phone": "010-7", "topic": "X"})
        assert resp.status_code == 200
        after = await c.get("/agent/data/news", params={"phone": "010-7"})
        assert after.json()["subscription"]["topics"] == ["Y"]
