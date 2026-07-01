"""``/agent/chat/upload`` Bearer 인증 + X-Tenant-ID 멤버십 검증 — P0.1 (codex P1-4).

기존 endpoint 는 ``phone`` form 으로 personal_tenant 를 resolve 하거나 실패 시
``DEFAULT_TENANT_UUID`` (00000000-…) 로 fallback 했다 — 인증 없이도 다른 사용자
저장소에 글이 떨어지는 데이터 누설 경로. 이 테스트는 다음을 검증한다.

1. Authorization 헤더 없으면 401.
2. invalid Bearer (decode 실패) 는 401.
3. 정상 Bearer + X-Tenant-ID 미지정 → personal_tenant 사용 + 201.
4. 정상 Bearer + 본인이 멤버 아닌 X-Tenant-ID → 403.

P0.1 hardening (codex 2차 review, 2026-04-28) 추가:
5. ``accounts.is_active = false`` 토큰 → 401 (P1-1).
6. ``tenant_memberships.role = 'viewer'`` → 403 (P1-2).
7. ``X-Tenant-ID`` 빈 문자열 → 400 (P2-1).

upload_document 파이프라인 (Kafka emit, license enforcer 등) 은 모듈 단위
monkeypatch 로 fake ApiResponse 반환 — 본 테스트의 책임은 인증/권한 분기.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.agent_framework.api import chat_upload as chat_upload_mod
from src.api.main import app
from src.api.routers import auth_v2
from src.api.schemas.common import ApiResponse
from src.core import database as core_db


TEST_EMAIL_PREFIX = "p01_chat_upload_"


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
    # asyncio loop 마다 engine pool 폐기 — pool 에 남은 연결이 다른 loop 에 묶여
    # "Event loop is closed" 가 나는 것을 방지 (chat_upload 가 src.core.database
    # 의 글로벌 engine 을 통해 get_db 를 호출하므로 함께 dispose).
    await auth_v2._reset_engine_for_tests()
    await core_db.engine.dispose()
    await _cleanup()
    yield
    await _cleanup()
    await auth_v2._reset_engine_for_tests()
    await core_db.engine.dispose()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest_asyncio.fixture
def fake_upload_document(monkeypatch):
    """upload_document 를 stub 으로 대체 — 파이프라인/Kafka/license 우회."""

    async def _fake(**kwargs):
        return ApiResponse(
            success=True,
            data={
                "document_id": str(uuid.uuid4()),
                "status": "processing",
                "message": "stubbed",
            },
        )

    monkeypatch.setattr(chat_upload_mod, "upload_document", _fake)
    return _fake


async def _signup_and_get_token(c: AsyncClient, email: str) -> tuple[str, str, str]:
    """signup → (access_token, account_id, personal_tenant_id)."""
    r = await c.post(
        "/auth/v2/signup",
        json={"email": email, "password": "Sup3rSecret!", "name": "Tester"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"], body["user"]["tenant_id"]


# ---------------------------------------------------------------------------
# 1. Bearer 누락 → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_no_bearer(clean_db, fake_upload_document):
    async with await _client() as c:
        files = {"file": ("test.txt", b"hello", "text/plain")}
        r = await c.post("/agent/chat/upload", files=files)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# 2. invalid Bearer → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_invalid_bearer(clean_db, fake_upload_document):
    async with await _client() as c:
        files = {"file": ("test.txt", b"hello", "text/plain")}
        r = await c.post(
            "/agent/chat/upload",
            files=files,
            headers={"Authorization": "Bearer notavalidjwt"},
        )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# 3. 정상 Bearer + X-Tenant-ID 미지정 → personal_tenant 로 201
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_uses_bearer_account_tenant(clean_db, fake_upload_document):
    async with await _client() as c:
        token, _account_id, personal_tid = await _signup_and_get_token(
            c, _email("ok")
        )
        files = {"file": ("test.txt", b"hello", "text/plain")}
        r = await c.post(
            "/agent/chat/upload",
            files=files,
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tenant_id"] == personal_tid
    assert body["filename"] == "test.txt"
    assert body["repository_id"]


# ---------------------------------------------------------------------------
# 4. cross-tenant — 본인이 멤버 아닌 X-Tenant-ID → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_cross_tenant(clean_db, fake_upload_document):
    """다른 사용자의 personal_tenant 로 X-Tenant-ID 를 보내면 403."""
    async with await _client() as c:
        # 두 명 가입 → A 가 B 의 tenant 에 접근 시도.
        token_a, _aid_a, _tid_a = await _signup_and_get_token(c, _email("alice"))
        _token_b, _aid_b, tid_b = await _signup_and_get_token(c, _email("bob"))

        files = {"file": ("test.txt", b"hello", "text/plain")}
        r = await c.post(
            "/agent/chat/upload",
            files=files,
            headers={
                "Authorization": f"Bearer {token_a}",
                "X-Tenant-ID": tid_b,
            },
        )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 5. P1-1 — accounts.is_active = false 계정의 토큰 → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_disabled_account(clean_db, fake_upload_document):
    """signup 후 ``is_active=false`` 로 toggle → 기존 access_token 도 401."""
    async with await _client() as c:
        token, account_id, _tid = await _signup_and_get_token(
            c, _email("disabled")
        )
        # is_active 를 직접 false 로 — 운영자 soft-disable 시뮬.
        eng = auth_v2._get_engine()
        async with eng.begin() as conn:
            await conn.execute(
                text("UPDATE accounts SET is_active = false WHERE id = :aid"),
                {"aid": account_id},
            )

        files = {"file": ("test.txt", b"hello", "text/plain")}
        r = await c.post(
            "/agent/chat/upload",
            files=files,
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# 6. P1-2 — viewer 롤은 chat upload 거부 → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_viewer_role(clean_db, fake_upload_document):
    """A 가 B 의 tenant 에 ``role='viewer'`` 로 멤버십이 있어도 upload → 403."""
    async with await _client() as c:
        token_a, aid_a, _tid_a = await _signup_and_get_token(c, _email("viewer"))
        _token_b, _aid_b, tid_b = await _signup_and_get_token(
            c, _email("vowner")
        )
        # A 를 B 의 tenant 에 viewer 로 추가.
        eng = auth_v2._get_engine()
        async with eng.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenant_memberships "
                    "(id, account_id, tenant_id, role) "
                    "VALUES (gen_random_uuid(), :aid, :tid, 'viewer')"
                ),
                {"aid": aid_a, "tid": tid_b},
            )

        files = {"file": ("test.txt", b"hello", "text/plain")}
        r = await c.post(
            "/agent/chat/upload",
            files=files,
            headers={
                "Authorization": f"Bearer {token_a}",
                "X-Tenant-ID": tid_b,
            },
        )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 7. P2-1 — 빈 X-Tenant-ID 헤더 → 400 (silent personal fallback 차단)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_empty_tenant_header(clean_db, fake_upload_document):
    """``X-Tenant-ID: ""`` 가 personal fallback 으로 흐르지 않고 400."""
    async with await _client() as c:
        token, _aid, _tid = await _signup_and_get_token(c, _email("emptyhdr"))
        files = {"file": ("test.txt", b"hello", "text/plain")}
        r = await c.post(
            "/agent/chat/upload",
            files=files,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-ID": "",
            },
        )
    # FastAPI/httpx 는 빈 헤더를 보존하지만, ASGI 레벨에서 drop 되는 경로가
    # 있다면 None 으로 도착해 personal fallback (201) 으로 흐를 수 있다.
    # 현행 동작은 빈 string 도 헤더로 도착 → 400.
    assert r.status_code == 400, r.text
