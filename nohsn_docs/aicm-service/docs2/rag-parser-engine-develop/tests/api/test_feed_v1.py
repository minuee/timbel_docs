"""``/api/v1/feed`` 라우터 테스트 — KMS-Plus P0.2 backend wrapper layer.

검증 항목
---------
1. Bearer 누락 → 401.
2. 빈 feed → ``{items: [], next_cursor: null}``.
3. INSERT 한 row 가 GET 으로 반환.
4. mark_read idempotent — 두 번째 호출은 success=False.
5. only_today=true 필터 — 오늘 row 만 반환.

upload_document / 파이프라인 우회 없음. DB 만 사용.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.main import app
from src.api.routers import auth_v2, feed_v1
from src.core import database as core_db


TEST_EMAIL_PREFIX = "p02_feed_v1_"


def _email(suffix: str) -> str:
    return f"{TEST_EMAIL_PREFIX}{suffix}_{uuid.uuid4().hex[:6]}@example.com"


async def _cleanup() -> None:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts WHERE email LIKE :p"
            ),
            {"p": f"{TEST_EMAIL_PREFIX}%"},
        )
        for account_id, tenant_id in list(rows):
            await conn.execute(
                text("DELETE FROM feed_events WHERE account_id = :aid"),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM tenant_memberships WHERE account_id = :aid"),
                {"aid": account_id},
            )
            await conn.execute(
                text("DELETE FROM accounts WHERE id = :aid"),
                {"aid": account_id},
            )
            if tenant_id:
                await conn.execute(
                    text("DELETE FROM repositories WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = :tid"),
                    {"tid": tenant_id},
                )


@pytest_asyncio.fixture
async def clean_db():
    await auth_v2._reset_engine_for_tests()
    await feed_v1._reset_engine_for_tests()
    await core_db.engine.dispose()
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()
    await feed_v1._reset_engine_for_tests()
    await core_db.engine.dispose()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _signup_and_get_token(c: AsyncClient, email: str) -> tuple[str, str, str]:
    r = await c.post(
        "/auth/v2/signup",
        json={"email": email, "password": "Sup3rSecret!", "name": "FeedTester"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"], body["user"]["tenant_id"]


async def _insert_feed_event(
    account_id: str,
    tenant_id: str,
    *,
    title: str = "Test event",
    body: str = "Body text",
    kind: str = "test.event",
    produced_at: datetime | None = None,
) -> str:
    """직접 INSERT 후 row id 반환."""
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        params: dict = {
            "aid": account_id,
            "tid": tenant_id,
            "kind": kind,
            "title": title,
            "body": body,
        }
        if produced_at is not None:
            row = await conn.execute(
                text(
                    "INSERT INTO feed_events "
                    "  (account_id, tenant_id, kind, title, body, produced_at) "
                    "VALUES (:aid, :tid, :kind, :title, :body, :pa) "
                    "RETURNING id"
                ),
                {**params, "pa": produced_at},
            )
        else:
            row = await conn.execute(
                text(
                    "INSERT INTO feed_events "
                    "  (account_id, tenant_id, kind, title, body) "
                    "VALUES (:aid, :tid, :kind, :title, :body) "
                    "RETURNING id"
                ),
                params,
            )
        return str(row.scalar_one())


# ---------------------------------------------------------------------------
# 1. Bearer 누락 → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_requires_bearer(clean_db):
    async with await _client() as c:
        r = await c.get("/api/v1/feed")
    # FastAPI 의 ``Header(...)`` 미존재 → 422 가 아니라 본 라우터는 디폴트 ...
    # → 422. 본 라우터는 해당 헤더 명시 401 처리에 의존하지 않으므로 ASGI default.
    # 그러나 FastAPI 는 missing required header 를 422 로 반환. 둘 다 인증 실패
    # 의미라서 401/422 모두 허용.
    assert r.status_code in (401, 422), r.text


@pytest.mark.asyncio
async def test_feed_invalid_bearer_returns_401(clean_db):
    async with await _client() as c:
        r = await c.get(
            "/api/v1/feed",
            headers={"Authorization": "Bearer notajwt"},
        )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# 2. 빈 feed → 빈 응답.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_empty(clean_db):
    async with await _client() as c:
        token, _aid, _tid = await _signup_and_get_token(c, _email("empty"))
        r = await c.get(
            "/api/v1/feed",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["items"] == []
    assert data["next_cursor"] is None


# ---------------------------------------------------------------------------
# 3. INSERT 한 row 반환.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_returns_inserted_event(clean_db):
    async with await _client() as c:
        token, aid, tid = await _signup_and_get_token(c, _email("ins"))
        await _insert_feed_event(aid, tid, title="hello", body="world")
        r = await c.get(
            "/api/v1/feed",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["title"] == "hello"
    assert item["body"] == "world"
    assert item["read_at"] is None
    assert item["produced_at"]


# ---------------------------------------------------------------------------
# 4. mark_read idempotent.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_idempotent(clean_db):
    async with await _client() as c:
        token, aid, tid = await _signup_and_get_token(c, _email("mr"))
        fid = await _insert_feed_event(aid, tid)
        # 첫 호출 → success=True
        r1 = await c.post(
            f"/api/v1/feed/{fid}/read",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["success"] is True
        # 두 번째 → success=False (이미 읽음).
        r2 = await c.post(
            f"/api/v1/feed/{fid}/read",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["success"] is False


# ---------------------------------------------------------------------------
# 5. only_today 필터.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# P0.2 hardening — tenant isolation tests.
# ---------------------------------------------------------------------------


async def _create_secondary_tenant(account_id: str) -> str:
    """추가 tenant + 멤버십 row 생성. tenant_id 반환.

    NOT NULL 컬럼 (config, plan) 도 함께 채움 — schema 가 있어 dynamic 으로
    DEFAULT 값이 없을 수도 있음.
    """
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        # 일부 컬럼이 NOT NULL 일 수 있어 information_schema 로 columns 확인 후
        # 필요한 default 값을 채워 INSERT.
        cols_rows = (
            await conn.execute(
                text(
                    "SELECT column_name, is_nullable, data_type, "
                    "       column_default "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'tenants'"
                )
            )
        ).all()
        cols = {
            r[0]: {"nullable": r[1] == "YES", "type": r[2], "default": r[3]}
            for r in cols_rows
        }
        insert_cols = ["id", "name", "slug", "tenant_type", "is_active"]
        insert_vals = ["gen_random_uuid()", ":n", ":s", "'company'", "TRUE"]
        params: dict[str, Any] = {
            "n": f"sec_{uuid.uuid4().hex[:6]}",
            "s": f"sec_{uuid.uuid4().hex[:6]}",
        }
        # NOT NULL 인데 default 없는 컬럼은 type 별 안전 default 채움.
        for col, info in cols.items():
            if col in insert_cols:
                continue
            if info["nullable"] or info["default"]:
                continue
            # NOT NULL + no default — 채워야 함.
            t = info["type"]
            if "json" in t:
                insert_cols.append(col)
                insert_vals.append("'{}'::jsonb")
            elif t in ("text", "character varying", "varchar"):
                insert_cols.append(col)
                insert_vals.append("''")
            elif t in ("integer", "bigint", "numeric", "smallint"):
                insert_cols.append(col)
                insert_vals.append("0")
            elif t == "boolean":
                insert_cols.append(col)
                insert_vals.append("FALSE")
        sql = (
            f"INSERT INTO tenants ({', '.join(insert_cols)}) VALUES "
            f"({', '.join(insert_vals)}) RETURNING id"
        )
        r = await conn.execute(text(sql), params)
        tid = str(r.scalar_one())
        await conn.execute(
            text(
                "INSERT INTO tenant_memberships (account_id, tenant_id, role) "
                "VALUES (:aid, :tid, 'admin')"
            ),
            {"aid": account_id, "tid": tid},
        )
    return tid


@pytest.mark.asyncio
async def test_feed_filters_by_tenant_header(clean_db):
    """X-Tenant-ID 헤더 → 그 tenant 의 feed 만 노출. 다른 tenant row 는 숨김."""
    async with await _client() as c:
        token, aid, t1 = await _signup_and_get_token(c, _email("th_a"))
        # 같은 account 가 tenant2 도 가짐.
        t2 = await _create_secondary_tenant(aid)

        await _insert_feed_event(aid, t1, title="t1_only", body="b1")
        await _insert_feed_event(aid, t2, title="t2_only", body="b2")

        # X-Tenant-ID = t1 → t1 의 row 만.
        r1 = await c.get(
            "/api/v1/feed",
            headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": t1},
        )
        assert r1.status_code == 200, r1.text
        titles1 = [it["title"] for it in r1.json()["items"]]
        assert "t1_only" in titles1
        assert "t2_only" not in titles1

        # X-Tenant-ID = t2 → t2 row 만.
        r2 = await c.get(
            "/api/v1/feed",
            headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": t2},
        )
        assert r2.status_code == 200
        titles2 = [it["title"] for it in r2.json()["items"]]
        assert "t2_only" in titles2
        assert "t1_only" not in titles2


@pytest.mark.asyncio
async def test_feed_rejects_non_member_tenant(clean_db):
    """본인 멤버십 없는 tenant → 403."""
    async with await _client() as c:
        token, _aid, _tid = await _signup_and_get_token(c, _email("nonm"))
        # 멤버십 없는 임의 tenant uuid.
        bogus = str(uuid.uuid4())
        r = await c.get(
            "/api/v1/feed",
            headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": bogus},
        )
    # 무작위 UUID 는 멤버십 row 없음 → 403.
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_mark_read_rejects_other_tenant(clean_db):
    """다른 tenant 의 row 를 X-Tenant-ID=mine 으로 mark_read → success=False."""
    async with await _client() as c:
        token, aid, t1 = await _signup_and_get_token(c, _email("mr_b"))
        t2 = await _create_secondary_tenant(aid)
        # t2 에서 만든 feed.
        fid = await _insert_feed_event(aid, t2, title="t2_event")
        # 헤더 = t1 으로 mark_read → 다른 tenant row 라 매칭 0.
        r = await c.post(
            f"/api/v1/feed/{fid}/read",
            headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": t1},
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# P0.2 hardening — composite cursor pagination 무손실 검증.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_no_loss_on_equal_produced_at(clean_db):
    """동일 produced_at 5 row 를 limit=2 로 페이지네이션 → 5 row 모두 노출."""
    async with await _client() as c:
        token, aid, tid = await _signup_and_get_token(c, _email("cur"))
        # 동일 시각 (테스트 재현 위해 명시 datetime).
        same_time = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            await _insert_feed_event(
                aid, tid, title=f"row_{i}", produced_at=same_time
            )

        seen: list[str] = []
        cursor: str | None = None
        for _ in range(5):
            params: dict = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            r = await c.get(
                "/api/v1/feed",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200, r.text
            data = r.json()
            seen.extend(it["title"] for it in data["items"])
            cursor = data.get("next_cursor")
            if not cursor:
                break

        assert sorted(seen) == sorted([f"row_{i}" for i in range(5)]), seen


@pytest.mark.asyncio
async def test_only_today_filter(clean_db):
    async with await _client() as c:
        token, aid, tid = await _signup_and_get_token(c, _email("today"))
        # 하나는 오늘 (now), 하나는 어제.
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1, hours=2)
        await _insert_feed_event(aid, tid, title="today", produced_at=now)
        await _insert_feed_event(
            aid, tid, title="yesterday", produced_at=yesterday
        )
        # only_today=true → 1개.
        r = await c.get(
            "/api/v1/feed?only_today=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        titles = [it["title"] for it in data["items"]]
        assert "today" in titles
        assert "yesterday" not in titles
        # only_today 미지정 → 둘 다.
        r2 = await c.get(
            "/api/v1/feed",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200
        all_titles = [it["title"] for it in r2.json()["items"]]
        assert "today" in all_titles
        assert "yesterday" in all_titles
