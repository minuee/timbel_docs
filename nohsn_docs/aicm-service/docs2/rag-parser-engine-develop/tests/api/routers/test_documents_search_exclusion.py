"""PATCH /documents/{id}/search-exclusion 엔드포인트 단위 테스트.

DB, Qdrant, ES 없이 DocumentService / payload_sync 을 monkeypatch 로 교체해
라우터 로직만 검증한다.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.routers import documents as documents_mod
from src.api.main import app

TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
REPO_ID = uuid4()
DOC_ID = uuid4()


class _FakeDoc:
    """검색 제외 토글 테스트용 최소 문서 더미."""

    def __init__(self, status: str = "active", search_excluded: bool = False):
        self.id = DOC_ID
        self.title = "테스트 문서"
        self.repository_id = REPO_ID
        self.document_type_id = None
        self.source_format = "pdf"
        self.status = status
        self.search_excluded = search_excluded
        self.processing_meta = {}
        self.version = 1
        self.description = None
        self.source_file = None
        self.created_by = None
        self.created_at = None
        self.updated_at = None


def _patch_all(monkeypatch, doc: _FakeDoc):
    """DocumentService.get_by_id / db.flush / sync 함수를 stub."""

    async def fake_get_by_id(self, doc_id, *, tenant_id=None):
        return doc

    monkeypatch.setattr(documents_mod.DocumentService, "get_by_id", fake_get_by_id)

    # sync_search_excluded — 외부 I/O 없이 통과
    async def fake_sync(doc_id, excluded, db, tenant_slug=None):
        return {"qdrant": 1, "es": 1}

    monkeypatch.setattr(documents_mod, "sync_search_excluded", fake_sync)

    # invalidate_repository_cache — 외부 I/O 없이 통과
    async def fake_invalidate(repo_id):
        pass

    monkeypatch.setattr(documents_mod, "invalidate_repository_cache", fake_invalidate)


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _auth_headers(tenant_id: UUID = TENANT_ID):
    return {"X-Tenant-Id": str(tenant_id)}


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exclude_active_document(monkeypatch):
    """active 문서 검색 제외 → 200, search_excluded=True."""
    doc = _FakeDoc(status="active", search_excluded=False)
    _patch_all(monkeypatch, doc)

    # db.flush 를 stub (AsyncSession 없이 동작)
    from unittest.mock import AsyncMock, MagicMock
    fake_db = MagicMock()
    fake_db.flush = AsyncMock()
    fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    from src.core.database import get_db
    app.dependency_overrides[get_db] = lambda: fake_db

    from src.api.dependencies import get_current_tenant_id
    app.dependency_overrides[get_current_tenant_id] = lambda: TENANT_ID

    try:
        async with await _client() as c:
            resp = await c.patch(
                f"/api/v1/documents/{DOC_ID}/search-exclusion",
                json={"excluded": True},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["search_excluded"] is True
        assert doc.search_excluded is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_restore_from_exclusion(monkeypatch):
    """검색 제외 문서 복원 → 200, search_excluded=False."""
    doc = _FakeDoc(status="active", search_excluded=True)
    _patch_all(monkeypatch, doc)

    from unittest.mock import AsyncMock, MagicMock
    fake_db = MagicMock()
    fake_db.flush = AsyncMock()

    from src.core.database import get_db
    from src.api.dependencies import get_current_tenant_id
    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_tenant_id] = lambda: TENANT_ID

    try:
        async with await _client() as c:
            resp = await c.patch(
                f"/api/v1/documents/{DOC_ID}/search-exclusion",
                json={"excluded": False},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200, resp.text
        assert doc.search_excluded is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_archived_document_rejected(monkeypatch):
    """archived 문서에 검색 제외 토글 시 400 반환."""
    doc = _FakeDoc(status="archived", search_excluded=False)
    _patch_all(monkeypatch, doc)

    from unittest.mock import AsyncMock, MagicMock
    fake_db = MagicMock()
    fake_db.flush = AsyncMock()

    from src.core.database import get_db
    from src.api.dependencies import get_current_tenant_id
    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_current_tenant_id] = lambda: TENANT_ID

    try:
        async with await _client() as c:
            resp = await c.patch(
                f"/api/v1/documents/{DOC_ID}/search-exclusion",
                json={"excluded": True},
                headers=_auth_headers(),
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_invalid_body_rejected():
    """body 에 excluded 필드 없으면 422."""
    from src.api.dependencies import get_current_tenant_id
    from src.core.database import get_db
    from unittest.mock import MagicMock
    app.dependency_overrides[get_current_tenant_id] = lambda: TENANT_ID
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        async with await _client() as c:
            resp = await c.patch(
                f"/api/v1/documents/{DOC_ID}/search-exclusion",
                json={"wrong_field": True},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()
