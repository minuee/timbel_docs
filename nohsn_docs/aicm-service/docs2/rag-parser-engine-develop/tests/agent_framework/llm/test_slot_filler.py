from unittest.mock import AsyncMock

import pytest

from src.agent_framework.llm.slot_filler import SlotFiller
from src.agent_framework.runtime.schema import SlotDef


@pytest.mark.asyncio
async def test_slot_filler_parses_json():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='{"preferred_date": "2026-04-25", "preferred_service": null}')
    filler = SlotFiller(llm_client=llm)

    slots = [
        SlotDef(name="preferred_date", type="date"),
        SlotDef(name="preferred_service", type="enum", values=["laser", "peeling"]),
    ]
    got = await filler.fill(
        user_message="다음주 토요일에 예약 하고 싶어요",
        slot_defs=slots,
    )
    assert got["preferred_date"] == "2026-04-25"
    assert got["preferred_service"] is None


@pytest.mark.asyncio
async def test_slot_filler_retries_on_bad_json():
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=[
        "이상한 텍스트 JSON 아님",
        '{"x": "y"}',
    ])
    filler = SlotFiller(llm_client=llm)
    got = await filler.fill(user_message="x", slot_defs=[SlotDef(name="x", type="text")])
    assert got == {"x": "y"}
    assert llm.complete.call_count == 2


@pytest.mark.asyncio
async def test_slot_filler_rejects_vague_evening_without_hour():
    """Bug 2 (2026-04-24) — '내일 저녁' 처럼 시각 없는 datetime 은 null 로 되돌려야.

    LLM 이 실수로 "2026-04-25 저녁" 같은 vague 값을 돌려줘도 SlotFiller
    가드 가 null 로 치환. state-machine 이 collect 에 머물러 재질문.
    """
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"title": "술 약속", "when": "2026-04-25 저녁"}'
    )
    filler = SlotFiller(llm_client=llm)
    got = await filler.fill(
        user_message="내일 저녁에 윤수석이랑 술먹기로 했어",
        slot_defs=[
            SlotDef(name="title", type="text"),
            SlotDef(name="when", type="datetime"),
        ],
    )
    assert got["title"] == "술 약속"
    assert got["when"] is None, f"vague datetime 이 통과됨: {got['when']!r}"


@pytest.mark.asyncio
async def test_slot_filler_accepts_explicit_time():
    """시각이 명시된 datetime 은 그대로 통과."""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"when": "2026-04-25 19:00"}'
    )
    filler = SlotFiller(llm_client=llm)
    got = await filler.fill(
        user_message="내일 저녁 7시",
        slot_defs=[SlotDef(name="when", type="datetime")],
    )
    assert got["when"] == "2026-04-25 19:00"


@pytest.mark.asyncio
async def test_slot_filler_accepts_korean_hour_marker():
    """'19시' 같은 한국어 시각 표기도 통과해야."""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"when": "내일 저녁 7시"}'
    )
    filler = SlotFiller(llm_client=llm)
    got = await filler.fill(
        user_message="내일 저녁 7시",
        slot_defs=[SlotDef(name="when", type="datetime")],
    )
    # 패턴은 "\d{1,2}\s*시" 매칭 — "7시" 는 구체 시각.
    assert got["when"] == "내일 저녁 7시"


@pytest.mark.asyncio
async def test_slot_filler_rejects_must_be_specific_when_user_omits_time():
    """Bug 3 (2026-04-28 사용자 신고) — '내일 대표님하고 미팅이 있어' 처럼
    user_message 에 시각 표시 없는데 LLM 이 06:00 default 채우면 null 로 reject.
    """
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"title": "대표님하고 미팅", "when": "2026-04-29T06:00:00", "who": "대표님"}'
    )
    filler = SlotFiller(llm_client=llm)
    got = await filler.fill(
        user_message="내일 대표님하고 미팅이 있어",
        slot_defs=[
            SlotDef(name="title", type="text"),
            SlotDef(name="when", type="datetime", must_be_specific=True),
            SlotDef(name="who", type="text"),
        ],
    )
    assert got["title"] == "대표님하고 미팅"
    assert got["who"] == "대표님"
    assert got["when"] is None, (
        f"user_message 시각 없는데 LLM default 가 통과됨: {got['when']!r}"
    )


@pytest.mark.asyncio
async def test_slot_filler_must_be_specific_passes_when_user_states_time():
    """user_message 에 시각 명시 ('3시') 가 있으면 strict 가드 우회 — 정상 채움."""
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"title": "회의", "when": "2026-04-29T15:00:00"}'
    )
    filler = SlotFiller(llm_client=llm)
    got = await filler.fill(
        user_message="내일 3시 회의 등록",
        slot_defs=[
            SlotDef(name="title", type="text"),
            SlotDef(name="when", type="datetime", must_be_specific=True),
        ],
    )
    assert got["title"] == "회의"
    assert got["when"] == "2026-04-29T15:00:00"
