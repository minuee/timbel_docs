"""SopInjectLayer 테스트.

mock tool_call 로 ``kms_sop.search`` 응답을 시뮬레이션. cache / destructive
force / failure_response_patterns deterministic include / prefetch 검증.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.agent_framework.runtime.sop_inject import (
    SopChunk,
    SopInjectLayer,
    extract_failure_response_patterns,
)


_AGENT_ID = uuid4()
_REPO_A = uuid4()
_DOC_A = uuid4()


_GUIDELINES_WITH_FAILURE = """\
# 미용실 SOP

## rules
- 친근한 톤 유지

## time_policy
- 영업시간 10-20시

## 실패 응답 패턴
### schedule.suggest_slots
- empty: "원장님 직통 02-1234-5678 로 안내"
- saturated: "내일 가능 시간 안내"

### kms_rag.search
- empty: "원장님께 직접 문의 권장"

## escalation_channels
- name: "원장 전화"
"""


_GUIDELINES_NO_FAILURE = """\
# 일반 SOP

## rules
- 정중한 톤
"""


def _make_kms_sop_result(chunks: list[dict]) -> dict:
    return {"success": True, "chunks": chunks, "total": len(chunks)}


def _make_chunk_payload(text: str, score: float = 0.8) -> dict:
    return {
        "text": text,
        "score": score,
        "repo_id": str(_REPO_A),
        "document_id": str(_DOC_A),
        "chunk_index": 0,
        "heading": "rules",
    }


# ---- extract_failure_response_patterns ---------------------------------------


def test_extract_failure_pattern_section():
    body = extract_failure_response_patterns(_GUIDELINES_WITH_FAILURE)
    assert "schedule.suggest_slots" in body
    assert "kms_rag.search" in body
    # 다음 H2 이후 텍스트 (escalation_channels) 는 포함되지 않아야 함.
    assert "원장 전화" not in body
    assert "## escalation" not in body


def test_extract_failure_pattern_missing():
    assert extract_failure_response_patterns(_GUIDELINES_NO_FAILURE) == ""


def test_extract_failure_pattern_english_heading():
    md = "## failure_response_patterns\n- a\n- b\n## next\n- c"
    body = extract_failure_response_patterns(md)
    assert "- a" in body and "- b" in body
    assert "- c" not in body


def test_extract_failure_pattern_empty_input():
    assert extract_failure_response_patterns("") == ""
    assert extract_failure_response_patterns(None) == ""  # type: ignore[arg-type]


# ---- SopInjectLayer ---------------------------------------------------------


@pytest.mark.asyncio
async def test_kms_sop_search_basic_flow():
    """기본 fetch — RAG chunks + failure_response_patterns 모두 반환."""
    tool_call = AsyncMock(
        return_value=_make_kms_sop_result(
            [
                _make_chunk_payload("## rules\n친근한 톤", 0.9),
                _make_chunk_payload("## time_policy\n영업시간 10-20", 0.7),
            ]
        )
    )
    layer = SopInjectLayer(tool_call=tool_call)
    chunks = await layer.fetch_chunks(
        _AGENT_ID,
        "오늘 예약 가능?",
        guidelines_md=_GUIDELINES_WITH_FAILURE,
    )

    # 첫 chunk = failure_response_patterns (deterministic include)
    assert chunks[0].is_failure_pattern is True
    assert "schedule.suggest_slots" in chunks[0].text
    # 다음 RAG chunks
    assert chunks[1].is_failure_pattern is False
    assert chunks[2].is_failure_pattern is False
    assert len(chunks) == 3

    # tool_call args 검증
    name, args = tool_call.await_args.args
    assert name == "kms_sop.search"
    assert args["agent_id"] == str(_AGENT_ID)
    assert args["query"] == "오늘 예약 가능?"
    assert args["top_k"] == 5  # default


@pytest.mark.asyncio
async def test_destructive_force_top_k_20():
    """destructive=True → top_k=20 + cache 우회."""
    tool_call = AsyncMock(return_value=_make_kms_sop_result([]))
    layer = SopInjectLayer(tool_call=tool_call)

    await layer.fetch_chunks(
        _AGENT_ID,
        "삭제할까?",
        top_k=5,
        destructive=True,
        guidelines_md=_GUIDELINES_NO_FAILURE,
    )
    _, args = tool_call.await_args.args
    assert args["top_k"] == 20


@pytest.mark.asyncio
async def test_failure_response_patterns_always_included():
    """RAG 결과 0건이어도 failure_response_patterns 는 prompt 에 포함."""
    tool_call = AsyncMock(return_value=_make_kms_sop_result([]))
    layer = SopInjectLayer(tool_call=tool_call)
    chunks = await layer.fetch_chunks(
        _AGENT_ID,
        "x",
        guidelines_md=_GUIDELINES_WITH_FAILURE,
    )
    assert len(chunks) == 1
    assert chunks[0].is_failure_pattern is True
    assert "schedule.suggest_slots" in chunks[0].text


@pytest.mark.asyncio
async def test_failure_response_patterns_missing_no_inject():
    """guidelines 에 섹션 없으면 RAG only — failure chunk 미주입."""
    tool_call = AsyncMock(
        return_value=_make_kms_sop_result(
            [_make_chunk_payload("rule body", 0.5)]
        )
    )
    layer = SopInjectLayer(tool_call=tool_call)
    chunks = await layer.fetch_chunks(
        _AGENT_ID,
        "x",
        guidelines_md=_GUIDELINES_NO_FAILURE,
    )
    assert all(not c.is_failure_pattern for c in chunks)
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_cache_30s_hit():
    """동일 query 두 번 → tool_call 1번만."""
    tool_call = AsyncMock(
        return_value=_make_kms_sop_result(
            [_make_chunk_payload("body", 0.6)]
        )
    )
    # 시계 고정 — TTL 안 만료되도록.
    fake_now = [1000.0]

    def clock():
        return fake_now[0]

    layer = SopInjectLayer(tool_call=tool_call, cache_ttl_s=30.0, clock=clock)

    a = await layer.fetch_chunks(_AGENT_ID, "예약?", guidelines_md=None)
    fake_now[0] = 1010.0  # 10s 경과 — TTL 안.
    b = await layer.fetch_chunks(_AGENT_ID, "예약?", guidelines_md=None)

    assert tool_call.await_count == 1
    # cached chunks 반환 — same shape
    assert len(a) == len(b)
    assert a[0].text == b[0].text


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    """TTL 경과 시 재조회."""
    tool_call = AsyncMock(
        return_value=_make_kms_sop_result(
            [_make_chunk_payload("body", 0.6)]
        )
    )
    fake_now = [1000.0]

    def clock():
        return fake_now[0]

    layer = SopInjectLayer(tool_call=tool_call, cache_ttl_s=30.0, clock=clock)
    await layer.fetch_chunks(_AGENT_ID, "예약?", guidelines_md=None)
    fake_now[0] = 1100.0  # 100s 경과 — 만료.
    await layer.fetch_chunks(_AGENT_ID, "예약?", guidelines_md=None)
    assert tool_call.await_count == 2


@pytest.mark.asyncio
async def test_destructive_bypasses_cache():
    """destructive=True 는 cache hit 라도 tool_call 강제."""
    tool_call = AsyncMock(
        return_value=_make_kms_sop_result(
            [_make_chunk_payload("body", 0.6)]
        )
    )
    layer = SopInjectLayer(tool_call=tool_call)
    await layer.fetch_chunks(_AGENT_ID, "예약?", guidelines_md=None)
    await layer.fetch_chunks(_AGENT_ID, "예약?", destructive=True, guidelines_md=None)
    assert tool_call.await_count == 2


@pytest.mark.asyncio
async def test_prefetch_metadata():
    """첫 turn 시 prefetch 호출 → failure_response_patterns 캐싱."""
    tool_call = AsyncMock(return_value=_make_kms_sop_result([]))
    layer = SopInjectLayer(tool_call=tool_call)
    await layer.prefetch(_AGENT_ID, _GUIDELINES_WITH_FAILURE, [_REPO_A])

    entry = layer.get_prefetched(_AGENT_ID)
    assert entry is not None
    assert _REPO_A in entry.sop_repo_ids
    assert "schedule.suggest_slots" in entry.failure_response_patterns

    # 다음 fetch 시 guidelines_md 미전달이어도 prefetch 의 failure 사용.
    chunks = await layer.fetch_chunks(_AGENT_ID, "x", guidelines_md=None)
    assert len(chunks) == 1
    assert chunks[0].is_failure_pattern is True


@pytest.mark.asyncio
async def test_malformed_chunks_dropped():
    """tool 응답에 invalid UUID 섞여도 drop, raise 안 함."""
    tool_call = AsyncMock(
        return_value={
            "success": True,
            "chunks": [
                {
                    "text": "ok",
                    "score": 0.5,
                    "repo_id": str(_REPO_A),
                    "document_id": str(_DOC_A),
                    "chunk_index": 0,
                    "heading": "x",
                },
                {
                    "text": "bad",
                    "score": 0.4,
                    "repo_id": "not-a-uuid",
                    "document_id": str(_DOC_A),
                },
            ],
        }
    )
    layer = SopInjectLayer(tool_call=tool_call)
    chunks = await layer.fetch_chunks(_AGENT_ID, "x", guidelines_md=None)
    # 1 valid + 0 failure_patterns
    assert len(chunks) == 1
    assert chunks[0].text == "ok"


@pytest.mark.asyncio
async def test_tool_call_failure_graceful():
    """tool_call 이 raise 해도 layer 는 빈 결과 반환 + failure_pattern 만 inject."""
    tool_call = AsyncMock(side_effect=RuntimeError("qdrant down"))
    layer = SopInjectLayer(tool_call=tool_call)
    chunks = await layer.fetch_chunks(
        _AGENT_ID, "x", guidelines_md=_GUIDELINES_WITH_FAILURE
    )
    # failure_response_patterns 만 inject — RAG 0개.
    assert len(chunks) == 1
    assert chunks[0].is_failure_pattern is True


def test_sop_chunk_dataclass_immutable():
    """SopChunk 는 frozen dataclass."""
    c = SopChunk(
        text="x", score=0.5, repo_id=_REPO_A, document_id=_DOC_A,
    )
    with pytest.raises((AttributeError, Exception)):
        c.text = "y"  # type: ignore[misc]
