"""Task 25-C — 의사 + 슬롯 기반 calendar_mock."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.agent_framework.tools.calendar_mock import (
    _reset,
    book,
    check_availability,
    list_available_slots,
    list_doctors,
)

_TZ = ZoneInfo("Asia/Seoul")


def _next_weekday(target_wd: int, from_date: date | None = None) -> date:
    """가장 가까운 target_wd 요일 (월=0) 날짜 반환."""
    base = from_date or datetime.now(_TZ).date()
    days_ahead = (target_wd - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


@pytest.mark.asyncio
async def test_list_doctors_returns_4():
    r = await list_doctors({})
    ids = {d["id"] for d in r["doctors"]}
    assert ids == {"dr_kim", "dr_park", "dr_lee", "dr_choi"}
    assert all(
        "name" in d and "specialty" in d and "days" in d and "intro" in d
        for d in r["doctors"]
    )


@pytest.mark.asyncio
async def test_list_slots_today_plus_7():
    _reset()
    r = await list_available_slots({})
    assert r["total"] >= 0
    # 슬롯 존재할 경우 ISO datetime 형식
    if r["slots"]:
        s = r["slots"][0]
        assert "datetime" in s
        datetime.fromisoformat(s["datetime"])
        assert s["doctor_id"] in {"dr_kim", "dr_park", "dr_lee", "dr_choi"}


@pytest.mark.asyncio
async def test_list_slots_filter_by_doctor():
    _reset()
    r = await list_available_slots({"doctor_id": "dr_kim"})
    assert all(s["doctor_id"] == "dr_kim" for s in r["slots"])


@pytest.mark.asyncio
async def test_check_available_weekday_working_hour():
    _reset()
    # 김도현 선생님 근무 요일 (월~금) 의 다음 월요일 10시
    monday = _next_weekday(0)
    dt = datetime.combine(monday, datetime.min.time().replace(hour=10)).replace(tzinfo=_TZ)
    r = await check_availability({"datetime": dt.isoformat(), "doctor_id": "dr_kim"})
    assert r["available"] is True
    assert r["doctor_name"] == "김도현"


@pytest.mark.asyncio
async def test_check_unavailable_lunchtime():
    _reset()
    monday = _next_weekday(0)
    dt = datetime.combine(monday, datetime.min.time().replace(hour=13)).replace(tzinfo=_TZ)
    r = await check_availability({"datetime": dt.isoformat(), "doctor_id": "dr_kim"})
    assert r["available"] is False
    assert r["reason"] == "lunch break"


@pytest.mark.asyncio
async def test_check_unavailable_weekday_off():
    """이민석 (화~토) 의 월요일 요청 → 근무일 아님."""
    _reset()
    monday = _next_weekday(0)
    dt = datetime.combine(monday, datetime.min.time().replace(hour=10)).replace(tzinfo=_TZ)
    r = await check_availability({"datetime": dt.isoformat(), "doctor_id": "dr_lee"})
    assert r["available"] is False
    assert r["reason"] == "doctor not working that day"


@pytest.mark.asyncio
async def test_book_then_unavailable():
    _reset()
    monday = _next_weekday(0)
    dt = datetime.combine(monday, datetime.min.time().replace(hour=11)).replace(tzinfo=_TZ)

    # 첫 예약 성공
    r1 = await book(
        {
            "datetime": dt.isoformat(),
            "doctor_id": "dr_kim",
            "service": "laser",
            "phone": "010-1",
            "name": "홍길동",
        }
    )
    assert r1["success"] is True
    assert "김도현" in r1["confirmation"]

    # 같은 슬롯 다시 → 실패
    r2 = await book(
        {
            "datetime": dt.isoformat(),
            "doctor_id": "dr_kim",
            "service": "laser",
            "phone": "010-2",
            "name": "아무개",
        }
    )
    assert r2["success"] is False


@pytest.mark.asyncio
async def test_book_invalid_datetime():
    _reset()
    r = await book(
        {
            "datetime": "이상한문자",
            "doctor_id": "dr_kim",
            "service": "laser",
            "phone": "010-1",
        }
    )
    assert r["success"] is False


@pytest.mark.asyncio
async def test_check_unknown_doctor():
    _reset()
    dt = datetime.now(_TZ).replace(hour=10, minute=0).isoformat()
    r = await check_availability({"datetime": dt, "doctor_id": "dr_nonexistent"})
    assert r["available"] is False
    assert "unknown doctor" in r["reason"]
