"""PR-B 회귀 — RAG 파이프라인 풍부화 + citations 일관성.

❸ citations 가 답변과 따로 도는 문제 → grounding 결과를 single source-of-truth.
❻ 챗 retrieval 빈약 → conversation_history + enable_llm_rewrite + use_hyde 풍부화.

회귀 4개:
1) KMS 도메인 발화에서 grounding 후 SSE event: citations 가 정확히 1회 emit 되며,
   items 길이 == grounding_docs 길이.
2) citations item 의 schema 가 frontend Citation 인터페이스와 호환 (id 포함).
3) feedback._kms_search 가 SearchService.search() 에 enable_llm_rewrite=True,
   use_hyde=True, conversation_history=[...] 를 전달.
4) chat_v1._fetch_citations_for_query 가 더 이상 import 되지 않음 (제거 확인).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest


# ---------------------------------------------------------------------------
# (1) + (2): engine.turn → SSE citations event 검증
# ---------------------------------------------------------------------------


class _StubLLMComplete:
    """skill auto_loader 가 요구하는 LLMClient.complete()."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, *, response_format: str | None = None) -> str:
        self.calls.append((system, user))
        return self.response


def _build_engine(redis_client, *, llm) -> Any:
    from src.agent_framework.runtime.engine import AgentEngine
    from src.agent_framework.runtime.session_store import SessionStore
    from src.agent_framework.tools import calendar_mock
    from src.agent_framework.tools.registry import ToolRegistry

    intent = AsyncMock()
    intent.classify_multi = AsyncMock(return_value=["book_appointment"])
    slot_filler = AsyncMock()
    slot_filler.fill = AsyncMock(return_value={})

    async def stream_response(tpl, ctx, **kwargs):
        # 답변 LLM 토큰 — 인라인 [1] 마커 포함하는 형태로 모방.
        yield "참고 [1] 자료에 따르면..."

    response_gen = MagicMock()
    response_gen.stream = stream_response
    response_gen.llm = llm

    return AgentEngine(
        session_store=SessionStore(redis_client),
        tool_registry=ToolRegistry(
            {
                "calendar.check_availability": calendar_mock.check_availability,
                "calendar.book": calendar_mock.book,
            }
        ),
        slot_filler=slot_filler,
        response_generator=response_gen,
        fallback_router=AsyncMock(),
        intent_classifier=intent,
    )


@pytest.mark.asyncio
async def test_citations_event_emitted_once_with_grounding_docs(redis_client, monkeypatch):
    """❸ — grounding_docs 가 있으면 SSE citations 이벤트가 정확히 1회 emit 되고
    items 길이가 grounding_docs 길이와 일치."""
    from src.agent_framework.runtime import engine as engine_mod

    monkeypatch.setenv("KMS_AUTO_SKILL_ENABLED", "true")
    monkeypatch.delenv("KMS_MULTI_ORCHESTRATOR_ENABLED", raising=False)

    fake_llm = _StubLLMComplete(
        '{"skill_name": "study_planner", "confidence": 0.9, "reason": "KMS 검색"}'
    )
    engine = _build_engine(redis_client, llm=fake_llm)

    # _retrieve_persona_grounding 를 stub — grounding_docs 3건 반환.
    stub_docs = [
        {
            "block_id": "b1", "doc_id": "d1", "title": "통계 공정 관리 SPC 가이드",
            "heading": "정의", "snippet": "SPC 는...", "score": 0.92,
            "doctype": "manual", "product_name": "", "effective_date": None,
            "version_label": None, "relations": [], "source": "통계 공정 관리 SPC 가이드",
        },
        {
            "block_id": "b2", "doc_id": "d1", "title": "통계 공정 관리 SPC 가이드",
            "heading": "활용", "snippet": "관리도는...", "score": 0.85,
            "doctype": "manual", "product_name": "", "effective_date": None,
            "version_label": None, "relations": [], "source": "통계 공정 관리 SPC 가이드",
        },
        {
            "block_id": "b3", "doc_id": "d2", "title": "품질관리 매뉴얼",
            "heading": "검사", "snippet": "수입 검사는...", "score": 0.71,
            "doctype": "manual", "product_name": "", "effective_date": None,
            "version_label": None, "relations": [], "source": "품질관리 매뉴얼",
        },
    ]

    async def _stub_grounding(self, **kwargs):
        return {"grounding_docs": stub_docs, "domain_summary": None}

    monkeypatch.setattr(
        engine_mod.AgentEngine, "_retrieve_persona_grounding", _stub_grounding
    )

    events: list[dict[str, Any]] = []
    async for evt in engine.turn("s_pr_b_1", "tenant-x", "SPC 관리도 알려줘"):
        events.append(evt)

    citation_events = [e for e in events if e.get("event") == "citations"]
    assert len(citation_events) == 1, (
        f"expected exactly 1 citations event, got {[e['event'] for e in events]}"
    )
    items = citation_events[0]["data"].get("items") or []
    assert len(items) == len(stub_docs)


@pytest.mark.asyncio
async def test_citations_items_schema_matches_frontend_interface(redis_client, monkeypatch):
    """(2) — citations items 가 프론트 Citation 인터페이스(id, document_title,
    snippet, score) 와 호환. id 는 grounding block_id 와 매핑."""
    from src.agent_framework.runtime import engine as engine_mod

    monkeypatch.setenv("KMS_AUTO_SKILL_ENABLED", "true")
    monkeypatch.delenv("KMS_MULTI_ORCHESTRATOR_ENABLED", raising=False)

    fake_llm = _StubLLMComplete(
        '{"skill_name": "study_planner", "confidence": 0.9, "reason": "..."}'
    )
    engine = _build_engine(redis_client, llm=fake_llm)

    stub_docs = [
        {
            "block_id": "block-uuid-1", "doc_id": "doc-uuid-1",
            "title": "통계 공정 관리 SPC 가이드", "heading": "관리도",
            "snippet": "X-bar 관리도는 평균을 모니터링한다", "score": 0.91,
            "doctype": "manual", "product_name": "", "effective_date": "2026-01-01",
            "version_label": "v3", "relations": [], "source": "통계 공정 관리 SPC 가이드",
        },
    ]

    async def _stub_grounding(self, **kwargs):
        return {"grounding_docs": stub_docs, "domain_summary": None}

    monkeypatch.setattr(
        engine_mod.AgentEngine, "_retrieve_persona_grounding", _stub_grounding
    )

    events: list[dict[str, Any]] = []
    async for evt in engine.turn("s_pr_b_2", "tenant-x", "SPC 관리도 종류"):
        events.append(evt)

    cev = next(e for e in events if e.get("event") == "citations")
    item = cev["data"]["items"][0]
    # 프론트 Citation 인터페이스 필수 필드
    assert "id" in item and item["id"]
    assert item.get("document_title") == "통계 공정 관리 SPC 가이드"
    assert item.get("snippet")
    assert isinstance(item.get("score"), (int, float))
    # id 는 grounding block_id 또는 그에 안정적으로 파생된 값
    assert item["id"] == "block-uuid-1"


# ---------------------------------------------------------------------------
# (3): feedback._kms_search 가 SearchService.search() 에 풍부화 파라미터 전달
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kms_search_passes_rewrite_hyde_and_history(monkeypatch):
    """❻ — _kms_search 가 SearchRequest 에 enable_llm_rewrite=True, use_hyde=True,
    conversation_history=[...] 을 포함해 SearchService.search() 호출."""
    from src.agent_framework.runtime.grounding import feedback as fb

    captured: dict[str, Any] = {}

    class _FakeSvc:
        async def search(self, *, request, tenant_slug):
            captured["request"] = request
            captured["tenant_slug"] = tenant_slug
            return SimpleNamespace(results=[])

    async def _fake_factory():
        return _FakeSvc()

    monkeypatch.setattr(fb, "_kms_search", fb._kms_search)  # ensure original
    # factory module path is imported lazily inside _kms_search → patch import target
    import src.search.factory as sf

    monkeypatch.setattr(sf, "create_search_service", _fake_factory)

    convo = [
        {"role": "user", "content": "SPC 가 뭐야?"},
        {"role": "assistant", "content": "통계 공정 관리입니다."},
    ]

    result = await fb._kms_search(
        query="관리도 종류",
        tenant_id="00000000-0000-0000-0000-000000000001",
        tenant_slug="kb-bank",
        knowledge_scope=["kb_bank"],
        top_k=5,
        conversation_history=convo,
    )

    assert result == []
    req = captured["request"]
    assert req.enable_llm_rewrite is True, "enable_llm_rewrite must be True"
    assert req.use_hyde is True, "use_hyde must be True"
    assert req.conversation_history == convo, "conversation_history must be forwarded"


# ---------------------------------------------------------------------------
# (4): chat_v1._fetch_citations_for_query 함수 제거 확인
# ---------------------------------------------------------------------------


def test_fetch_citations_for_query_function_removed():
    """citations single source-of-truth = engine grounding. chat_v1 의 별도
    검색 함수 ``_fetch_citations_for_query`` 는 제거되어야 함."""
    from src.api.routers import chat_v1

    assert not hasattr(chat_v1, "_fetch_citations_for_query"), (
        "chat_v1._fetch_citations_for_query must be removed (single source-of-truth = engine grounding)"
    )
