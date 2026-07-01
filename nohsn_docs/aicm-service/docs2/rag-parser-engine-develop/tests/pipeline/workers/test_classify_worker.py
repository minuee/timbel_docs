"""classify_worker 테스트 — Stage B-Core-4 (KMS-Plus).

- feature flag off → no-op
- 정상 msg + mocked classifier → persist 호출
- classifier 예외 → fallback, no persist crash
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.pipeline.models.document import ProcessingDifficulty
from src.pipeline.models.events import DocumentParsedEvent
from src.pipeline.workers import classify_worker


def _make_event(doc_type: str | None = None) -> DocumentParsedEvent:
    return DocumentParsedEvent(
        event_id=uuid4(),
        document_id=uuid4(),
        tenant_id=uuid4(),
        repository_id=uuid4(),
        difficulty=ProcessingDifficulty.LOW,
        page_count=3,
        table_count=0,
        image_count=0,
        raw_text_length=200,
        source_path="/tmp/x.pdf",
        document_type=doc_type,
    )


class _FakeSession:
    """async_session_factory() 가 반환하는 async-context-manager 를 모방."""

    def __init__(self):
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.committed = True

    async def execute(self, *args, **kwargs):
        # title 조회용 — scalar_one_or_none → None (워커는 빈 제목 허용)
        rv = MagicMock()
        rv.scalar_one_or_none = MagicMock(return_value="테스트 문서")
        return rv


def _session_factory(session: _FakeSession):
    # factory() -> async-context-manager
    def factory():
        return session
    return factory


@pytest.mark.asyncio
async def test_disabled_flag_returns_none(monkeypatch):
    monkeypatch.setenv("AGENT_AUTO_CLASSIFY", "off")
    event = _make_event()
    got = await classify_worker.handle_document_parsed_for_classify(
        event,
        classifier=AsyncMock(),
        db_session_factory=_session_factory(_FakeSession()),
    )
    assert got is None


@pytest.mark.asyncio
async def test_happy_path_persists(monkeypatch):
    """정상 classify 호출 + DocumentService.update_processing_meta 경유 persist."""
    monkeypatch.setenv("AGENT_AUTO_CLASSIFY", "on")

    event = _make_event(doc_type="manual")

    # classifier mock
    classifier = AsyncMock()
    classifier.classify = AsyncMock(
        return_value={
            "category_guess": "상담 매뉴얼",
            "domain": "customer_support",
            "tags": ["상담", "매뉴얼"],
            "suggested_repository_name": "상담 자료실",
            "suggested_document_type": "manual",
            "confidence": 0.75,
            "rationale": "응대 스크립트가 기술되어 있음.",
        }
    )

    session = _FakeSession()

    # Patch _load_document_sample to avoid real DB/cache
    async def _fake_load(event):
        return ("테스트 매뉴얼", "본 매뉴얼은 고객 응대 절차를 다룬다. " * 10)

    # DocumentService 도 patch 해서 실제 ORM 안 건드리게.
    captured: dict = {}

    class _FakeDocumentService:
        def __init__(self, db):
            self._db = db

        async def update_processing_meta(self, doc_id, *, processing_meta, tenant_id=None):
            captured["doc_id"] = doc_id
            captured["processing_meta"] = processing_meta
            return MagicMock()

    with patch.object(classify_worker, "_load_document_sample", _fake_load), patch(
        "src.core.services.document_service.DocumentService", _FakeDocumentService
    ):
        got = await classify_worker.handle_document_parsed_for_classify(
            event,
            classifier=classifier,
            db_session_factory=_session_factory(session),
        )

    classifier.classify.assert_called_once()
    assert got is not None
    assert got["domain"] == "customer_support"
    assert "analyzed_at" in got
    assert captured["doc_id"] == event.document_id
    assert captured["processing_meta"]["auto_classification"]["domain"] == "customer_support"
    assert session.committed is True


@pytest.mark.asyncio
async def test_classifier_exception_does_not_crash(monkeypatch):
    """classifier 가 예외를 던져도 파이프라인은 영향 X. 반환 None."""
    monkeypatch.setenv("AGENT_AUTO_CLASSIFY", "on")

    event = _make_event()
    classifier = AsyncMock()
    classifier.classify = AsyncMock(side_effect=RuntimeError("llm down"))

    async def _fake_load(event):
        return ("제목", "본문")

    with patch.object(classify_worker, "_load_document_sample", _fake_load):
        got = await classify_worker.handle_document_parsed_for_classify(
            event,
            classifier=classifier,
            db_session_factory=_session_factory(_FakeSession()),
        )
    assert got is None


@pytest.mark.asyncio
async def test_hint_domain_passed_from_event(monkeypatch):
    """event.document_type 이 있으면 classifier.classify 에 hint 로 전달."""
    monkeypatch.setenv("AGENT_AUTO_CLASSIFY", "on")

    event = _make_event(doc_type="contract")

    classifier = AsyncMock()
    classifier.classify = AsyncMock(
        return_value={
            "category_guess": "계약서",
            "domain": "legal",
            "tags": ["계약"],
            "suggested_repository_name": "",
            "suggested_document_type": "contract",
            "confidence": 0.8,
            "rationale": "계약 조항 포맷.",
        }
    )

    async def _fake_load(event):
        return ("계약서", "제1조 ...")

    class _FakeDocumentService:
        def __init__(self, db):
            pass

        async def update_processing_meta(self, doc_id, *, processing_meta, tenant_id=None):
            return MagicMock()

    with patch.object(classify_worker, "_load_document_sample", _fake_load), patch(
        "src.core.services.document_service.DocumentService", _FakeDocumentService
    ):
        await classify_worker.handle_document_parsed_for_classify(
            event,
            classifier=classifier,
            db_session_factory=_session_factory(_FakeSession()),
        )

    call_kwargs = classifier.classify.call_args.kwargs
    assert call_kwargs["hints"]["rule_based_domain"] == "contract"
