"""``/api/v1/verification/*`` — KMS-Plus P0.2 hardening.

codex 2차 review 항목:
- P2-4: runs / proposals 가 trace/evidence 전체를 노출하던 부분 → summary.
- P2-6: runs/start 가 invalid scenario UUID 도 통과 → 사전 SELECT 검증.
        같은 시나리오 pending 중복 → 409.
"""
from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.main import app
from src.api.routers import auth_v2, verification_v1
from src.core import database as core_db


TEST_EMAIL_PREFIX = "p02_verif_h_"


def _email(suffix: str) -> str:
    return f"{TEST_EMAIL_PREFIX}{suffix}_{uuid.uuid4().hex[:6]}@example.com"


async def _cleanup() -> None:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        # accounts 정리.
        rows = await conn.execute(
            text(
                "SELECT id, personal_tenant_id FROM accounts WHERE email LIKE :p"
            ),
            {"p": f"{TEST_EMAIL_PREFIX}%"},
        )
        for account_id, tenant_id in list(rows):
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
                    text("DELETE FROM tenants WHERE id = :tid"),
                    {"tid": tenant_id},
                )
        # 테스트 시나리오/실행/제안 정리 (name prefix).
        await conn.execute(
            text("DELETE FROM verification_runs WHERE scenario_id IN ("
                 "SELECT id FROM verification_scenarios WHERE name LIKE :p)"),
            {"p": f"{TEST_EMAIL_PREFIX}%"},
        )
        await conn.execute(
            text("DELETE FROM verification_scenarios WHERE name LIKE :p"),
            {"p": f"{TEST_EMAIL_PREFIX}%"},
        )
        await conn.execute(
            text("DELETE FROM verification_proposals WHERE source LIKE :p"),
            {"p": f"{TEST_EMAIL_PREFIX}%"},
        )


@pytest_asyncio.fixture
async def clean_db():
    await auth_v2._reset_engine_for_tests()
    await verification_v1._reset_engine_for_tests()
    await core_db.engine.dispose()
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()
    await verification_v1._reset_engine_for_tests()
    await core_db.engine.dispose()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _signup_admin(c: AsyncClient, email: str) -> str:
    r = await c.post(
        "/auth/v2/signup",
        json={"email": email, "password": "Sup3rSecret!", "name": "Vh"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    aid = body["user"]["id"]
    # admin user_group 부여.
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "UPDATE accounts SET preferences = CAST(:p AS jsonb) "
                "WHERE id = :aid"
            ),
            {"p": json.dumps({"user_groups": ["admin"]}), "aid": aid},
        )
    return body["access_token"]


async def _create_scenario(name: str, yaml_text: str = "scenario:\n  step: 1\n") -> str:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        r = await conn.execute(
            text(
                "INSERT INTO verification_scenarios (name, yaml_text) "
                "VALUES (:n, :y) RETURNING id"
            ),
            {"n": name, "y": yaml_text},
        )
    return str(r.scalar_one())


async def _create_run(
    scenario_id: str | None,
    status: str = "pending",
    trace: dict | None = None,
) -> str:
    eng = auth_v2._get_engine()
    async with eng.begin() as conn:
        r = await conn.execute(
            text(
                "INSERT INTO verification_runs (scenario_id, status, trace) "
                "VALUES (:sid, :st, CAST(:tr AS jsonb)) RETURNING id"
            ),
            {
                "sid": scenario_id,
                "st": status,
                "tr": json.dumps(trace or {}),
            },
        )
    return str(r.scalar_one())


# ---------------------------------------------------------------------------
# P2-4: runs list 는 trace 자체 노출 X (has_trace boolean 만).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_list_returns_summary_no_trace(clean_db):
    async with await _client() as c:
        token = await _signup_admin(c, _email("runs"))
        sid = await _create_scenario(f"{TEST_EMAIL_PREFIX}sc1")
        secret_trace = {"events": [{"prompt": "secret", "tokens": "x" * 10}]}
        rid = await _create_run(sid, status="pass", trace=secret_trace)

        r = await c.get(
            "/api/v1/verification/runs",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "expected runs"
    target = [it for it in items if it["id"] == rid]
    assert target, "run row missing"
    row = target[0]
    # trace 자체 키 X — has_trace boolean 만.
    assert "trace" not in row
    assert row.get("has_trace") is True


@pytest.mark.asyncio
async def test_run_trace_detail_admin_only(clean_db):
    async with await _client() as c:
        token = await _signup_admin(c, _email("td"))
        sid = await _create_scenario(f"{TEST_EMAIL_PREFIX}sc_td")
        rid = await _create_run(sid, status="pass", trace={"events": [{"k": "v"}]})

        r = await c.get(
            f"/api/v1/verification/runs/{rid}/trace",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == rid
    assert data["trace"] == {"events": [{"k": "v"}]}


@pytest.mark.asyncio
async def test_run_trace_invalid_uuid_returns_400(clean_db):
    async with await _client() as c:
        token = await _signup_admin(c, _email("tdb"))
        r = await c.get(
            "/api/v1/verification/runs/not-a-uuid/trace",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# P2-4: scenarios list 는 yaml 첫 5줄 + truncate flag.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenarios_list_returns_yaml_preview(clean_db):
    yaml_long = "\n".join(f"line_{i}: x" for i in range(10))
    async with await _client() as c:
        token = await _signup_admin(c, _email("sc"))
        await _create_scenario(f"{TEST_EMAIL_PREFIX}preview", yaml_long)
        r = await c.get(
            "/api/v1/verification/scenarios",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    target = [it for it in items if it["name"] == f"{TEST_EMAIL_PREFIX}preview"]
    assert target, "scenario missing"
    row = target[0]
    assert "yaml_preview" in row
    assert row["yaml_truncated"] is True
    # 첫 5줄만 미리보기.
    assert row["yaml_preview"].count("\n") == 4


# ---------------------------------------------------------------------------
# P2-6: runs/start 사전 검증 — 존재하지 않는 scenario_id → 404.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_start_404_when_scenario_missing(clean_db):
    bogus = str(uuid.uuid4())
    async with await _client() as c:
        token = await _signup_admin(c, _email("404"))
        r = await c.post(
            f"/api/v1/verification/runs/start?scenario_id={bogus}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_runs_start_400_invalid_uuid(clean_db):
    async with await _client() as c:
        token = await _signup_admin(c, _email("inv"))
        r = await c.post(
            "/api/v1/verification/runs/start?scenario_id=not-a-uuid",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_runs_start_409_when_pending_exists(clean_db):
    async with await _client() as c:
        token = await _signup_admin(c, _email("dup"))
        sid = await _create_scenario(f"{TEST_EMAIL_PREFIX}dup")
        # 이미 pending row 가 있다.
        await _create_run(sid, status="pending")
        r = await c.post(
            f"/api/v1/verification/runs/start?scenario_id={sid}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_runs_start_succeeds_for_unique_scenario(clean_db):
    async with await _client() as c:
        token = await _signup_admin(c, _email("ok"))
        sid = await _create_scenario(f"{TEST_EMAIL_PREFIX}ok")
        r = await c.post(
            f"/api/v1/verification/runs/start?scenario_id={sid}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    assert "run_id" in r.json()
