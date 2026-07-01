"""D41 Phase 4 — citations_v1 HTML preview unit tests.

DB 의존 통합 테스트가 아닌, router 의 *순수 helper* 와 Accept 분기 로직만 검증.

검증:
- _preferred_html_media() Accept q-value 파싱.
- _esc() HTML escape (XSS 차단).
- _render_html() placeholder escape + 조건부 meta.
- HTML headers 의무 항목 포함.
- _resolve_auth() — JWT/X-Tenant/token/없음 분기.
- token 만료 → 410. 잘못된 서명 → 401.
"""
from __future__ import annotations

import importlib
import time
import uuid

import pytest


_DEV_SECRET = "MIPKScw-vYjiSqtHLJubX7x-RBvGJZTaK3vGd3UzYU4N-wzFEgwDuIXazUd4A1Ap"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    """모든 테스트에 안전한 secret 설정."""
    from src.common import config as _cfg
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_SECRET", _DEV_SECRET, raising=False)
    monkeypatch.setattr(_cfg.settings, "CITATION_HMAC_TTL_SECS", 43200, raising=False)
    yield


def _fresh_router_module():
    """매 테스트마다 module reload — settings 변경 반영."""
    import src.common.security.citation_token as ct
    importlib.reload(ct)
    import src.api.routers.citations_v1 as cv
    importlib.reload(cv)
    return cv


# ---------------------------------------------------------------------------
# Accept header q-value 파싱
# ---------------------------------------------------------------------------
def test_preferred_html_media_empty_returns_none():
    cv = _fresh_router_module()
    # 빈 Accept → default JSON (None)
    assert cv._preferred_html_media("") is None


def test_preferred_html_media_wildcard_only_returns_none():
    """`*/*` only → JSON (Web frontend 보호)."""
    cv = _fresh_router_module()
    assert cv._preferred_html_media("*/*") is None
    assert cv._preferred_html_media("*/*;q=0.9") is None


def test_preferred_html_media_explicit_json_returns_none():
    cv = _fresh_router_module()
    assert cv._preferred_html_media("application/json") is None
    assert cv._preferred_html_media("application/json,*/*") is None


def test_preferred_html_media_browser_html_returns_html():
    """Telegram 모바일 브라우저의 일반적 Accept → HTML."""
    cv = _fresh_router_module()
    browser_accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    assert cv._preferred_html_media(browser_accept) == "text/html"


def test_preferred_html_media_json_wins_tie():
    """JSON q == HTML q → JSON 우선 (Web frontend 보호)."""
    cv = _fresh_router_module()
    assert cv._preferred_html_media("text/html;q=0.5,application/json;q=0.5") is None


def test_preferred_html_media_json_wins_when_higher():
    cv = _fresh_router_module()
    assert cv._preferred_html_media("text/html;q=0.5,application/json;q=0.9") is None


def test_preferred_html_media_xhtml_higher_returns_xhtml():
    cv = _fresh_router_module()
    result = cv._preferred_html_media("application/xhtml+xml;q=1,text/html;q=0.5")
    assert result == "application/xhtml+xml"


def test_preferred_html_media_malformed_q_treated_as_zero():
    cv = _fresh_router_module()
    # malformed q-value → q=0 → JSON 우선.
    result = cv._preferred_html_media("text/html;q=bogus,application/json")
    assert result is None


# ---------------------------------------------------------------------------
# HTML escape
# ---------------------------------------------------------------------------
def test_esc_basic_chars():
    cv = _fresh_router_module()
    assert cv._esc("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert cv._esc('a"b') == "a&quot;b"
    assert cv._esc("a&b") == "a&amp;b"


def test_esc_none_returns_empty():
    cv = _fresh_router_module()
    assert cv._esc(None) == ""
    assert cv._esc("") == ""


def test_esc_amp_first_no_double_escape():
    """``&`` 가 먼저 escape 되어야 `<` → `&lt;` 가 다시 `&amp;lt;` 안 됨."""
    cv = _fresh_router_module()
    result = cv._esc("<a>")
    assert result == "&lt;a&gt;"
    assert "&amp;lt;" not in result


# ---------------------------------------------------------------------------
# _render_html
# ---------------------------------------------------------------------------
def test_render_html_escapes_all_placeholders():
    cv = _fresh_router_module()
    data = {
        "title": "<DOC>",
        "repo_name": "KB&Co",
        "section_title": '"section"',
        "page_number": 7,
        "block_type": "<TABLE>",
        "content": '<script>alert("XSS")</script>',
    }
    html = cv._render_html(data)
    # 모든 placeholder 가 escape 처리 됨.
    assert "&lt;DOC&gt;" in html
    assert "KB&amp;Co" in html
    assert "&quot;section&quot;" in html
    assert "&lt;TABLE&gt;" in html
    assert "&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;" in html
    # raw `<script>` 가 본문에 들어가면 안됨.
    assert "<script>" not in html


def test_render_html_omits_empty_meta_spans():
    cv = _fresh_router_module()
    data = {
        "title": "Doc",
        "repo_name": None,
        "section_title": "",
        "page_number": None,
        "block_type": "",
        "content": "body",
    }
    html = cv._render_html(data)
    # 빈 meta span 은 omit — `<span class="badge"></span>` 같은 거 안 나옴.
    assert '<span class="badge"></span>' not in html
    assert "<span></span>" not in html
    assert "p.None" not in html


def test_render_html_full_meta_rendered():
    cv = _fresh_router_module()
    data = {
        "title": "Doc",
        "repo_name": "Repo",
        "section_title": "Sec",
        "page_number": 7,
        "block_type": "para",
        "content": "본문",
    }
    html = cv._render_html(data)
    assert '<span class="badge">Repo</span>' in html
    assert "<span>Sec</span>" in html
    assert "<span>p.7</span>" in html
    assert "<span>para</span>" in html


def test_render_html_has_korean_viewport_and_lang():
    cv = _fresh_router_module()
    html = cv._render_html({"title": "T", "content": "C"})
    assert 'lang="ko"' in html
    assert 'width=device-width' in html
    assert 'initial-scale=1.0' in html


# ---------------------------------------------------------------------------
# HTML headers
# ---------------------------------------------------------------------------
def test_html_headers_all_required_fields():
    cv = _fresh_router_module()
    h = cv._HTML_HEADERS
    assert h["Cache-Control"] == "no-store, private"
    assert h["Referrer-Policy"] == "no-referrer"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert h["Vary"] == "Accept"


# ---------------------------------------------------------------------------
# _resolve_auth — token / JWT / 401
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resolve_auth_no_creds_raises_401():
    cv = _fresh_router_module()
    from fastapi import HTTPException
    # 가짜 Request — state 비어있음
    class FakeReq:
        class state:  # noqa: D106
            pass
    block_id = uuid.uuid4()
    with pytest.raises(HTTPException) as excinfo:
        await cv._resolve_auth(
            request=FakeReq(),
            block_id=block_id,
            t=None, exp=None,
            authorization=None, x_tenant_id=None,
        )
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_resolve_auth_x_tenant_header_used():
    cv = _fresh_router_module()
    class FakeReq:
        class state:  # noqa: D106
            pass
    block_id = uuid.uuid4()
    tid = str(uuid.uuid4())
    result_tid, via_token = await cv._resolve_auth(
        request=FakeReq(),
        block_id=block_id,
        t=None, exp=None,
        authorization=None, x_tenant_id=tid,
    )
    assert result_tid == uuid.UUID(tid)
    assert via_token is False


@pytest.mark.asyncio
async def test_resolve_auth_valid_token():
    cv = _fresh_router_module()
    from src.common.security.citation_token import sign_citation_token
    class FakeReq:
        class state:  # noqa: D106
            pass
    block_id = uuid.uuid4()
    tid = str(uuid.uuid4())
    token, exp = sign_citation_token(str(block_id), tid)

    result_tid, via_token = await cv._resolve_auth(
        request=FakeReq(),
        block_id=block_id,
        t=token, exp=exp,
        authorization=None, x_tenant_id=None,
    )
    assert result_tid == uuid.UUID(tid)
    assert via_token is True


@pytest.mark.asyncio
async def test_resolve_auth_expired_token_raises_410():
    cv = _fresh_router_module()
    import base64, hashlib, hmac as _hmac
    class FakeReq:
        class state:  # noqa: D106
            pass
    block_id = uuid.uuid4()
    tid = str(uuid.uuid4())
    past_exp = int(time.time()) - 100
    secret = _DEV_SECRET.encode()
    payload = f"v1:{block_id}:{tid}:{past_exp}".encode()
    sig = _hmac.new(secret, payload, hashlib.sha256).hexdigest()
    tid_b64 = base64.urlsafe_b64encode(tid.encode()).rstrip(b"=").decode()
    token = f"v1.{tid_b64}.{sig}"

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        await cv._resolve_auth(
            request=FakeReq(),
            block_id=block_id,
            t=token, exp=past_exp,
            authorization=None, x_tenant_id=None,
        )
    assert excinfo.value.status_code == 410


@pytest.mark.asyncio
async def test_resolve_auth_invalid_signature_raises_401():
    cv = _fresh_router_module()
    class FakeReq:
        class state:  # noqa: D106
            pass
    block_id = uuid.uuid4()
    from fastapi import HTTPException
    # 가짜 token
    with pytest.raises(HTTPException) as excinfo:
        await cv._resolve_auth(
            request=FakeReq(),
            block_id=block_id,
            t="v1.YWJj.deadbeef", exp=int(time.time()) + 100,
            authorization=None, x_tenant_id=None,
        )
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_resolve_auth_jwt_priority_over_token():
    """JWT 가 valid 면 token 무시 (Web 사용자 회귀 0)."""
    cv = _fresh_router_module()
    from src.api.auth.jwt_utils import create_access_token

    class FakeReq:
        class state:  # noqa: D106
            pass

    block_id = uuid.uuid4()
    jwt_tid = uuid.uuid4()
    # JWT 발급 — tenant_id 명시
    jwt = create_access_token(
        subject=str(uuid.uuid4()),
        tenant_id=str(jwt_tid),
        role="viewer",
    )
    # token 의 tenant 와 다른 값 시도해도 JWT 가 우선.
    diff_tid = str(uuid.uuid4())
    from src.common.security.citation_token import sign_citation_token
    token, exp = sign_citation_token(str(block_id), diff_tid)

    result_tid, via_token = await cv._resolve_auth(
        request=FakeReq(),
        block_id=block_id,
        t=token, exp=exp,
        authorization=f"Bearer {jwt}",
        x_tenant_id=None,
    )
    assert result_tid == jwt_tid
    assert via_token is False  # JWT path


@pytest.mark.asyncio
async def test_resolve_auth_x_tenant_priority_over_token():
    """X-Tenant-Id 명시 시 token 보다 우선 (Web/admin path 보호).

    GPT-5 phase 4 pre P2 — JWT > X-Tenant-Id > token > 401 순서 보장.
    """
    cv = _fresh_router_module()
    from src.common.security.citation_token import sign_citation_token

    class FakeReq:
        class state:  # noqa: D106
            pass

    block_id = uuid.uuid4()
    header_tid = str(uuid.uuid4())
    token_tid = str(uuid.uuid4())
    token, exp = sign_citation_token(str(block_id), token_tid)

    result_tid, via_token = await cv._resolve_auth(
        request=FakeReq(),
        block_id=block_id,
        t=token, exp=exp,
        authorization=None,
        x_tenant_id=header_tid,
    )
    # X-Tenant-Id 가 token 보다 우선.
    assert result_tid == uuid.UUID(header_tid)
    assert via_token is False


# ---------------------------------------------------------------------------
# End-to-end (TestClient) — HTML 응답 헤더 실제 적용 검증
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_html_response_has_security_headers(monkeypatch):
    """실제 HTTP 호출 시 HTML 응답에 모든 보안 헤더 포함 검증.

    GPT-5 phase 4 pre P2 — _HTML_HEADERS 상수가 실제로 응답에 적용되는지.
    DB 의존 회피 — FastAPI dependency_overrides 로 block/repo/document 주입.
    """
    cv = _fresh_router_module()
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src.core.database import get_db
    from src.common.security.citation_token import sign_citation_token

    # Stub Block / Repository / Document.
    block_id = uuid.uuid4()
    tenant_uuid = uuid.uuid4()
    doc_id = uuid.uuid4()
    repo_id = uuid.uuid4()

    class FakeBlock:
        pass
    block_obj = FakeBlock()
    block_obj.id = block_id
    block_obj.repository_id = repo_id
    block_obj.document_id = doc_id
    block_obj.block_type = "para"
    block_obj.content = "본문 내용"
    block_obj.source_location = {"page_number": 3}
    block_obj.meta_info = {"section_title": "Sec"}

    class FakeRepo:
        pass
    repo_obj = FakeRepo()
    repo_obj.id = repo_id
    repo_obj.tenant_id = tenant_uuid
    repo_obj.name = "Repo"

    class FakeDoc:
        pass
    doc_obj = FakeDoc()
    doc_obj.id = doc_id
    doc_obj.title = "테스트 문서"
    doc_obj.source_format = "pdf"

    # Fake AsyncSession that returns the right model per query.
    class FakeResult:
        def __init__(self, v):
            self._v = v
        def scalar_one_or_none(self):
            return self._v

    class FakeDB:
        _call = 0
        async def execute(self, stmt):
            # block → repo → document 순.
            self._call += 1
            if self._call == 1:
                return FakeResult(block_obj)
            if self._call == 2:
                return FakeResult(repo_obj)
            if self._call == 3:
                return FakeResult(doc_obj)
            return FakeResult(None)

    async def _fake_db():
        yield FakeDB()

    app = FastAPI()
    app.include_router(cv.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _fake_db

    token, exp = sign_citation_token(str(block_id), str(tenant_uuid))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # HTML 요청 — Accept text/html
        resp = await ac.get(
            f"/api/v1/citations/{block_id}",
            params={"t": token, "exp": exp},
            headers={"Accept": "text/html"},
        )

    assert resp.status_code == 200
    # 보안 헤더 모두 확인
    assert resp.headers["cache-control"] == "no-store, private"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["vary"] == "Accept"
    # 본문 escape 확인
    assert "테스트 문서" in resp.text
    assert "본문 내용" in resp.text
    assert "<script>" not in resp.text


@pytest.mark.asyncio
async def test_guest_token_forces_html_even_with_json_accept(monkeypatch):
    """guest token-only path → Accept 무관 HTML 강제 (게스트에 JSON 차단)."""
    cv = _fresh_router_module()
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src.core.database import get_db
    from src.common.security.citation_token import sign_citation_token

    block_id = uuid.uuid4()
    tenant_uuid = uuid.uuid4()
    doc_id = uuid.uuid4()
    repo_id = uuid.uuid4()

    class FakeBlock:
        pass
    block_obj = FakeBlock()
    block_obj.id = block_id
    block_obj.repository_id = repo_id
    block_obj.document_id = doc_id
    block_obj.block_type = None
    block_obj.content = "guest 본문"
    block_obj.source_location = None
    block_obj.meta_info = None

    class FakeRepo:
        pass
    repo_obj = FakeRepo()
    repo_obj.id = repo_id
    repo_obj.tenant_id = tenant_uuid
    repo_obj.name = None

    class FakeDoc:
        pass
    doc_obj = FakeDoc()
    doc_obj.id = doc_id
    doc_obj.title = "guest 문서"
    doc_obj.source_format = None

    class FakeResult:
        def __init__(self, v):
            self._v = v
        def scalar_one_or_none(self):
            return self._v

    class FakeDB:
        _call = 0
        async def execute(self, stmt):
            self._call += 1
            if self._call == 1:
                return FakeResult(block_obj)
            if self._call == 2:
                return FakeResult(repo_obj)
            if self._call == 3:
                return FakeResult(doc_obj)
            return FakeResult(None)

    async def _fake_db():
        yield FakeDB()

    app = FastAPI()
    app.include_router(cv.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _fake_db

    token, exp = sign_citation_token(str(block_id), str(tenant_uuid))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # token + Accept application/json — guest 라 JSON 차단되어 HTML 강제.
        resp = await ac.get(
            f"/api/v1/citations/{block_id}",
            params={"t": token, "exp": exp},
            headers={"Accept": "application/json"},
        )

    assert resp.status_code == 200
    # 응답이 HTML (게스트에 JSON 차단).
    ct = resp.headers["content-type"]
    assert ct.startswith("text/html") or ct.startswith("application/xhtml+xml"), (
        f"guest token path should force HTML, got: {ct}"
    )
    assert "guest 문서" in resp.text


@pytest.mark.asyncio
async def test_endpoint_invalid_sig_past_exp_returns_401_not_410(monkeypatch):
    """GPT-5 phase 4 post P1 — 엔드포인트 레이어에서 만료 오라클 차단 검증.

    invalid 서명 + 과거 exp → 401 (410 아님 — 공격자가 만료를 추론 못 함).
    """
    cv = _fresh_router_module()
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src.core.database import get_db

    block_id = uuid.uuid4()
    # DB 도달 전 401 — fake_db 는 호출 안 됨.
    async def _fake_db():
        class _NoopDB:
            async def execute(self, stmt):
                raise AssertionError("should not reach DB on invalid token")
        yield _NoopDB()

    app = FastAPI()
    app.include_router(cv.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _fake_db

    # 위조 token + 과거 exp.
    past_exp = int(time.time()) - 1000
    fake_token = "v1.YWJjZGVm.deadbeef" * 4  # 적당히 긴 위조

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get(
            f"/api/v1/citations/{block_id}",
            params={"t": fake_token[:200], "exp": past_exp},
            headers={"Accept": "text/html"},
        )
    # 만료 오라클 차단 — 401 (410 아님).
    assert resp.status_code == 401, f"expected 401 (sig invalid first), got {resp.status_code}"


@pytest.mark.asyncio
async def test_jwt_cross_tenant_returns_404(monkeypatch):
    """JWT 의 tenant_id ≠ block.repository.tenant_id → 404 generic.

    GPT-5 phase 4 post P1 — cross-tenant 검증을 JWT path 에서도 수행.
    """
    cv = _fresh_router_module()
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src.core.database import get_db
    from src.api.auth.jwt_utils import create_access_token

    block_id = uuid.uuid4()
    block_tenant = uuid.uuid4()
    jwt_tenant = uuid.uuid4()  # 다른 tenant
    doc_id = uuid.uuid4()
    repo_id = uuid.uuid4()

    class FakeBlock:
        pass
    block_obj = FakeBlock()
    block_obj.id = block_id
    block_obj.repository_id = repo_id
    block_obj.document_id = doc_id
    block_obj.block_type = None
    block_obj.content = "tenant A secret"
    block_obj.source_location = None
    block_obj.meta_info = None

    class FakeRepo:
        pass
    repo_obj = FakeRepo()
    repo_obj.id = repo_id
    repo_obj.tenant_id = block_tenant
    repo_obj.name = "A"

    class FakeResult:
        def __init__(self, v):
            self._v = v
        def scalar_one_or_none(self):
            return self._v

    class FakeDB:
        _call = 0
        async def execute(self, stmt):
            self._call += 1
            if self._call == 1:
                return FakeResult(block_obj)
            if self._call == 2:
                return FakeResult(repo_obj)
            return FakeResult(None)

    async def _fake_db():
        yield FakeDB()

    app = FastAPI()
    app.include_router(cv.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _fake_db

    # attacker JWT — 다른 tenant
    jwt = create_access_token(
        subject=str(uuid.uuid4()),
        tenant_id=str(jwt_tenant),
        role="viewer",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get(
            f"/api/v1/citations/{block_id}",
            headers={"Authorization": f"Bearer {jwt}", "Accept": "application/json"},
        )
    # cross-tenant → 404 generic (enumeration 차단)
    assert resp.status_code == 404
    assert "tenant A secret" not in resp.text


@pytest.mark.asyncio
async def test_cross_tenant_token_returns_404(monkeypatch):
    """token tenant ≠ block.repository.tenant → 404 generic (enumeration 차단)."""
    cv = _fresh_router_module()
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src.core.database import get_db
    from src.common.security.citation_token import sign_citation_token

    block_id = uuid.uuid4()
    block_tenant = uuid.uuid4()    # block 소유 tenant
    token_tenant = uuid.uuid4()    # token 의 다른 tenant (attacker)
    doc_id = uuid.uuid4()
    repo_id = uuid.uuid4()

    class FakeBlock:
        pass
    block_obj = FakeBlock()
    block_obj.id = block_id
    block_obj.repository_id = repo_id
    block_obj.document_id = doc_id
    block_obj.block_type = None
    block_obj.content = "secret content of tenant A"
    block_obj.source_location = None
    block_obj.meta_info = None

    class FakeRepo:
        pass
    repo_obj = FakeRepo()
    repo_obj.id = repo_id
    repo_obj.tenant_id = block_tenant
    repo_obj.name = "A"

    class FakeResult:
        def __init__(self, v):
            self._v = v
        def scalar_one_or_none(self):
            return self._v

    class FakeDB:
        _call = 0
        async def execute(self, stmt):
            self._call += 1
            if self._call == 1:
                return FakeResult(block_obj)
            if self._call == 2:
                return FakeResult(repo_obj)  # repo.tenant_id ≠ token tenant
            return FakeResult(None)

    async def _fake_db():
        yield FakeDB()

    app = FastAPI()
    app.include_router(cv.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _fake_db

    # attacker token (다른 tenant)
    token, exp = sign_citation_token(str(block_id), str(token_tenant))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.get(
            f"/api/v1/citations/{block_id}",
            params={"t": token, "exp": exp},
            headers={"Accept": "text/html"},
        )
    # cross-tenant 면 generic 404.
    assert resp.status_code == 404
    # 비밀 내용이 응답에 안 새어나가는지 확인.
    assert "secret content" not in resp.text
