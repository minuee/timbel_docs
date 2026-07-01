"""POST /documents/{id}/promote 엔드포인트 테스트.

DB / payload_sync 없이 DocumentService 를 monkeypatch 해서
라우터 로직만 검증한다.
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_promote_endpoint_module_imports():
    """import smoke test — endpoint 정의 확인."""
    from src.api.routers.documents import promote_document, PromoteRequest

    assert promote_document is not None
    assert PromoteRequest.model_fields.get("reason") is not None


def test_promote_request_reason_optional():
    """PromoteRequest: reason 없이도 인스턴스 생성 가능."""
    from src.api.routers.documents import PromoteRequest

    req = PromoteRequest()
    assert req.reason is None

    req_with_reason = PromoteRequest(reason="테스트 사유")
    assert req_with_reason.reason == "테스트 사유"


@pytest.mark.asyncio
async def test_promote_rejects_non_pending_review(monkeypatch):
    """pending_review 외 상태의 문서는 400 반환."""
    import uuid
    from types import SimpleNamespace
    from uuid import UUID, uuid4

    from httpx import ASGITransport, AsyncClient

    from src.api.routers import documents as documents_mod
    from src.api.main import app

    TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    DOC_ID = uuid4()

    class _FakeDoc:
        def __init__(self):
            self.id = DOC_ID
            self.status = "active"
            self.processing_meta = {}
            self.repository_id = uuid4()

    fake_doc = _FakeDoc()

    class _FakeSvc:
        def __init__(self, db):
            pass

        async def get_by_id(self, doc_id, tenant_id=None):
            return fake_doc

    monkeypatch.setattr(documents_mod, "DocumentService", _FakeSvc)

    async def _fake_tenant(request):
        return TENANT_ID

    from src.api import dependencies as dep_mod
    monkeypatch.setattr(dep_mod, "get_current_tenant_id", _fake_tenant)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/documents/{DOC_ID}/promote",
            headers={"X-Tenant-ID": str(TENANT_ID)},
            json={},
        )
    assert resp.status_code == 400
    assert "pending_review" in resp.json()["detail"]
