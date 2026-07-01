"""SelfQueryParser 테스트.

mock LLM 으로 JSON 응답 시뮬레이션. 시간/카테고리/상태/우선순위 추출 +
파싱 실패 / timeout fail-open 검증.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agent_framework.runtime.self_query import (
    SelfQueryFilter,
    SelfQueryParser,
)


def _resp(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, model="mock", usage={}, latency_ms=10)


def _json_resp(payload: dict) -> SimpleNamespace:
    return _resp(json.dumps(payload, ensure_ascii=False))


# ---- empty / passthrough ----------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query_returns_empty_filter():
    llm = AsyncMock()
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("")
    assert isinstance(result, SelfQueryFilter)
    assert result.is_empty()
    assert result.residual_query == ""
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_whitespace_query_returns_empty_filter():
    llm = AsyncMock()
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("   \n\t  ")
    assert result.is_empty()
    llm.generate.assert_not_awaited()


# ---- date extraction --------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_date_range_korean_month():
    """'5월 일정' → date_range 5월 1일~31일."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "date_range": {"start": "2026-05-01", "end": "2026-05-31"},
            "category": ["일정"],
            "status": [],
            "priority": None,
            "residual_query": "일정",
        })
    )
    parser = SelfQueryParser(llm, today_provider=lambda: "2026-05-07")
    result = await parser.extract_filters("내 5월 일정 보여줘")
    assert result.date_range == {"start": "2026-05-01", "end": "2026-05-31"}
    assert result.category == ["일정"]
    assert result.priority is None
    assert result.residual_query == "일정"


@pytest.mark.asyncio
async def test_extract_date_range_last_week():
    """'지난주' → 7일 범위."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "date_range": {"start": "2026-04-27", "end": "2026-05-03"},
            "category": [],
            "status": [],
            "priority": None,
            "residual_query": "회의록",
        })
    )
    parser = SelfQueryParser(llm, today_provider=lambda: "2026-05-07")
    result = await parser.extract_filters("지난주 회의록")
    assert result.date_range is not None
    assert result.date_range["start"] == "2026-04-27"
    assert result.date_range["end"] == "2026-05-03"


@pytest.mark.asyncio
async def test_invalid_date_format_silent_drop():
    """LLM 이 잘못된 date format 반환 → silent drop."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "date_range": {"start": "5월 1일", "end": "5/31"},  # invalid format
            "category": [],
            "status": [],
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("5월 회의")
    assert result.date_range is None  # validation 실패 → drop


@pytest.mark.asyncio
async def test_swapped_date_range_normalized():
    """start > end 면 swap."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "date_range": {"start": "2026-05-31", "end": "2026-05-01"},
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("5월")
    assert result.date_range == {"start": "2026-05-01", "end": "2026-05-31"}


# ---- category & status ------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_category():
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "category": ["예약", "결제"],
            "residual_query": "어제",
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("어제 예약/결제 건")
    assert result.category == ["예약", "결제"]


@pytest.mark.asyncio
async def test_extract_status():
    """'취소된' → status filter."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "status": ["취소"],
            "category": ["주문"],
            "residual_query": "주문",
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("취소된 주문 알려줘")
    assert result.status == ["취소"]
    assert result.category == ["주문"]


# ---- priority ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_priority_high():
    """'긴급' → priority high."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "priority": "high",
            "residual_query": "민원",
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("긴급 민원 보여줘")
    assert result.priority == "high"


@pytest.mark.asyncio
async def test_invalid_priority_silent_drop():
    """priority enum 외 값 → silent drop."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "priority": "URGENT",  # 잘못된 값
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("긴급 건")
    assert result.priority is None


# ---- parse failures ---------------------------------------------------------


@pytest.mark.asyncio
async def test_non_json_response_fail_open():
    """LLM 이 JSON 아닌 텍스트 반환 → empty filter (residual=원본)."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_resp("죄송합니다 추출 못했어요"))
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("어제 민원")
    assert result.is_empty()
    assert result.residual_query == "어제 민원"


@pytest.mark.asyncio
async def test_json_in_code_fence_extracted():
    """LLM 이 markdown code fence 로 감싸도 추출."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_resp(
            '여기 JSON 입니다:\n```json\n{"category": ["예약"]}\n```\n끝'
        )
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("예약 건")
    assert result.category == ["예약"]


@pytest.mark.asyncio
async def test_llm_timeout_fail_open():
    """LLM timeout → empty filter (residual=원본)."""
    llm = AsyncMock()

    async def slow(req):
        await asyncio.sleep(2.0)
        return _resp("late")

    llm.generate = AsyncMock(side_effect=slow)
    parser = SelfQueryParser(llm, timeout_s=0.05)
    result = await parser.extract_filters("긴급 민원")
    assert result.is_empty()
    assert result.residual_query == "긴급 민원"


@pytest.mark.asyncio
async def test_llm_exception_fail_open():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("vllm down"))
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("쿼리")
    assert result.is_empty()
    assert result.residual_query == "쿼리"


# ---- cache ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_llm():
    """동일 query 두 번 → LLM 1회만."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({"category": ["예약"], "residual_query": "건"})
    )
    parser = SelfQueryParser(llm)
    a = await parser.extract_filters("예약 건")
    b = await parser.extract_filters("예약 건")
    assert llm.generate.await_count == 1
    assert a.category == ["예약"]
    assert b.category == ["예약"]


@pytest.mark.asyncio
async def test_cache_ttl_expires():
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({"category": ["x"]})
    )
    fake_now = [1000.0]

    def clock() -> float:
        return fake_now[0]

    parser = SelfQueryParser(llm, cache_ttl_s=60.0, clock=clock)
    await parser.extract_filters("q")
    fake_now[0] = 1100.0
    await parser.extract_filters("q")
    assert llm.generate.await_count == 2


@pytest.mark.asyncio
async def test_timeout_not_cached():
    """timeout 결과는 cache 안 됨 — 다음 호출 시 재시도."""
    llm = AsyncMock()
    call_count = [0]

    async def maybe_slow(req):
        call_count[0] += 1
        if call_count[0] == 1:
            await asyncio.sleep(2.0)
            return _resp("late")
        return _json_resp({"category": ["c"]})

    llm.generate = AsyncMock(side_effect=maybe_slow)
    parser = SelfQueryParser(llm, timeout_s=0.05)
    a = await parser.extract_filters("질의")
    assert a.is_empty()  # timeout
    b = await parser.extract_filters("질의")
    # 재시도 — 두 번째 호출은 정상.
    assert b.category == ["c"]
    assert llm.generate.await_count == 2


# ---- residual query ---------------------------------------------------------


@pytest.mark.asyncio
async def test_residual_query_fallback_to_original():
    """LLM 이 residual_query 안 주면 원본 query 그대로."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "category": ["주문"],
            # residual_query 누락
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("주문 보여줘")
    assert result.residual_query == "주문 보여줘"
    assert result.category == ["주문"]


@pytest.mark.asyncio
async def test_tenant_filter_extracted():
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=_json_resp({
            "tenant_filter": "tenant-abc",
            "residual_query": "정책",
        })
    )
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("tenant-abc 의 정책")
    assert result.tenant_filter == "tenant-abc"


# ---- raw passthrough --------------------------------------------------------


@pytest.mark.asyncio
async def test_raw_payload_preserved():
    """raw 필드에 LLM 원본 JSON 보존 (디버그용)."""
    payload = {"category": ["예약"], "extra_field": "ignored"}
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_json_resp(payload))
    parser = SelfQueryParser(llm)
    result = await parser.extract_filters("예약")
    assert result.raw["category"] == ["예약"]
    assert result.raw.get("extra_field") == "ignored"
