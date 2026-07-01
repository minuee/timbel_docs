"""Phase B-2 — /api/v1/documents/{id}/apply_classification + reject_classification.

DocumentService.get_by_id, _get_or_create_repository, _get_or_create_document_type
를 monkeypatch 로 교체해 DB 접근 없이 라우터 동작을 검증한다.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.routers import documents as documents_mod
from src.api.main import app


FIXED_TENANT_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_TENANT_ID = UUID("44444444-4444-4444-4444-444444444444")


class _FakeDoc:
    """DocumentService.get_by_id 반환용 최소 더미."""

    def __init__(
        self,
        doc_id: UUID,
        tenant_id: UUID,
        repository_id: UUID,
        classification: dict | None = None,
    ):
        self.id = doc_id
        self.title = "Test Doc"
        self.repository_id = repository_id
        self.document_type_id = None
        self.source_format = "pdf"
        self._tenant_id = tenant_id  # 외부 노출 X — stub 에서 검증용
        self.processing_meta = {
            "auto_classification": classification or {
                "category_guess": "상담 매뉴얼",
                "domain": "finance",
                "tags": ["kms"],
                "suggested_repository_name": "크레온 상담 자료실",
                "suggested_document_type": "manual",
                "confidence": 0.82,
                "rationale": "표지에 '상담 매뉴얼' 명시",
            }
        }


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _make_patches(monkeypatch, doc: _FakeDoc, *, tenant_ok: bool = True):
    """DocumentService.get_by_id + repo/doctype helper + db.flush 를 stub."""

    async def fake_get_by_id(self, doc_id, *, tenant_id=None):
        if tenant_ok and (tenant_id is None or tenant_id == doc._tenant_id):
            return doc
        from src.core.exceptions import DocumentNotFoundError
        raise DocumentNotFoundError(str(doc_id))

    monkeypatch.setattr(
        documents_mod.DocumentService, "get_by_id", fake_get_by_id
    )

    # repository / document_type helpers
    async def fake_repo(db, *, tenant_id, name):
        return SimpleNamespace(id=uuid4(), name=name, tenant_id=tenant_id)

    async def fake_doctype(db, *, tenant_id, name):
        return uuid4()

    monkeypatch.setattr(documents_mod, "_get_or_create_repository", fake_repo)
    monkeypatch.setattr(documents_mod, "_get_or_create_document_type", fake_doctype)

    # db.flush no-op — get_db fixture 는 AsyncSession 을 주입하지만 우리는 테스트에서
    # AsyncSession.flush 가 실제 DB 로 가지 않도록 AsyncSession 을 override.
    class _FakeDb:
        async def flush(self):
            return None
        async def execute(self, *a, **kw):  # audit_service 경로 — 사용 안됨
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def _override_get_db():
        yield _FakeDb()

    from src.core.database import get_db
    app.dependency_overrides[get_db] = _override_get_db


def _clear_deps():
    from src.core.database import get_db
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_apply_with_suggested_values_uses_suggested(monkeypatch):
    """body 비우면 suggested_repository_name / suggested_document_type 를 사용."""
    doc_id = uuid4()
    doc = _FakeDoc(doc_id=doc_id, tenant_id=FIXED_TENANT_ID, repository_id=uuid4())
    _make_patches(monkeypatch, doc)
    try:
        async with await _client() as c:
            resp = await c.post(
                f"/api/v1/documents/{doc_id}/apply_classification",
                headers={"X-Tenant-Id": str(FIXED_TENANT_ID)},
                json={},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["applied"] is True
        assert body["repository_name"] == "크레온 상담 자료실"
        assert body["document_type"] == "manual"
        # processing_meta 에 applied=true 가 기록됨
        assert doc.processing_meta["auto_classification"]["applied"] is True
        assert "applied_at" in doc.processing_meta["auto_classification"]
    finally:
        _clear_deps()


@pytest.mark.asyncio
async def test_apply_with_override_values_uses_provided(monkeypatch):
    """body 로 전달된 repository_name / document_type 가 우선."""
    doc_id = uuid4()
    doc = _FakeDoc(doc_id=doc_id, tenant_id=FIXED_TENANT_ID, repository_id=uuid4())
    _make_patches(monkeypatch, doc)
    try:
        async with await _client() as c:
            resp = await c.post(
                f"/api/v1/documents/{doc_id}/apply_classification",
                headers={"X-Tenant-Id": str(FIXED_TENANT_ID)},
                json={"repository_name": "Override Repo", "document_type": "script"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["repository_name"] == "Override Repo"
        assert body["document_type"] == "script"
        assert doc.processing_meta["auto_classification"]["applied_repository_name"] == "Override Repo"
        assert doc.processing_meta["auto_classification"]["applied_document_type"] == "script"
    finally:
        _clear_deps()


@pytest.mark.asyncio
async def test_reject_marks_applied_false(monkeypatch):
    doc_id = uuid4()
    doc = _FakeDoc(doc_id=doc_id, tenant_id=FIXED_TENANT_ID, repository_id=uuid4())
    _make_patches(monkeypatch, doc)
    try:
        async with await _client() as c:
            resp = await c.post(
                f"/api/v1/documents/{doc_id}/reject_classification",
                headers={"X-Tenant-Id": str(FIXED_TENANT_ID)},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["applied"] is False
        assert doc.processing_meta["auto_classification"]["applied"] is False
        assert "rejected_at" in doc.processing_meta["auto_classification"]
        # 원본 suggested_* 는 유지
        assert doc.processing_meta["auto_classification"]["suggested_repository_name"] == "크레온 상담 자료실"
    finally:
        _clear_deps()


@pytest.mark.asyncio
async def test_apply_tenant_mismatch_returns_404(monkeypatch):
    """다른 tenant 의 문서 접근 → DocumentNotFoundError → 404 로 응답."""
    doc_id = uuid4()
    doc = _FakeDoc(doc_id=doc_id, tenant_id=FIXED_TENANT_ID, repository_id=uuid4())
    _make_patches(monkeypatch, doc, tenant_ok=False)
    try:
        async with await _client() as c:
            resp = await c.post(
                f"/api/v1/documents/{doc_id}/apply_classification",
                headers={"X-Tenant-Id": str(OTHER_TENANT_ID)},
                json={},
            )
        # DocumentNotFoundError 는 엔드포인트에서 HTTPException 404 로 래핑
        assert resp.status_code == 404
    finally:
        _clear_deps()
