"""피부과 예약 mock — 의사 + 한 달치 가용 슬롯.

의사 데이터는 고정 시드 상수. 가용 슬롯은 오늘 기준 N일 치 평일 09:00~18:00
30분 단위로 자동 생성. 예약은 Redis set 에 저장되어 multi-worker 공유.

Week 5 polish B: _BOOKED in-memory set → Redis set.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.agent_framework.tools import _redis_store as rs

_TZ = ZoneInfo("Asia/Seoul")
_CATEGORY = "calendar_booked"

# ── 의사 시드 ───────────────────────────────────────────────

_DOCTORS: list[dict] = [
    {
        "id": "dr_kim",
        "name": "김도현",
        "specialty": "레이저·색소",
        "intro": "10년 경력. 피코·토닝 전문.",
        "days_of_week": [0, 1, 2, 3, 4],  # 월~금
    },
    {
        "id": "dr_park",
        "name": "박지영",
        "specialty": "필러·보톡스",
        "intro": "성형외과 전공. 자연스러운 윤곽 시술.",
        "days_of_week": [0, 2, 3, 4, 5],  # 월·수·목·금·토
    },
    {
        "id": "dr_lee",
        "name": "이민석",
        "specialty": "여드름·흉터",
        "intro": "중등도~중증 여드름 치료. 염증·흉터 레이저.",
        "days_of_week": [1, 2, 3, 4, 5],  # 화~토
    },
    {
        "id": "dr_choi",
        "name": "최서연",
        "specialty": "안티에이징·리프팅",
        "intro": "HIFU·울쎄라 전문. 40대 이상 주력.",
        "days_of_week": [0, 1, 3, 4],  # 월·화·목·금
    },
]

# 근무 시간 (KST, 모든 의사 공통)
_WORK_START = time(9, 0)
_WORK_END = time(18, 0)
_SLOT_MINUTES = 30
# 점심시간 (예약 불가)
_LUNCH_START = time(12, 30)
_LUNCH_END = time(13, 30)


def _reset() -> None:
    rs._reset_sync()


def _member(dt_iso: str, doctor_id: str) -> str:
    return f"{dt_iso}|{doctor_id}"


def _today() -> date:
    return datetime.now(_TZ).date()


def _generate_slots_for_doctor(doctor: dict, from_date: date, days: int) -> list[datetime]:
    """특정 의사의 from_date ~ from_date+days 구간 가용 슬롯 생성 (예약 여부 무관)."""
    slots: list[datetime] = []
    for d_off in range(days):
        day = from_date + timedelta(days=d_off)
        if day.weekday() not in doctor["days_of_week"]:
            continue
        # 09:00 부터 18:00 전까지 30분 단위
        cur = datetime.combine(day, _WORK_START, tzinfo=_TZ)
        end = datetime.combine(day, _WORK_END, tzinfo=_TZ)
        while cur < end:
            # 점심시간 제외
            t = cur.time()
            if not (_LUNCH_START <= t < _LUNCH_END):
                slots.append(cur)
            cur += timedelta(minutes=_SLOT_MINUTES)
    return slots


# ── Tools ───────────────────────────────────────────────────

async def list_doctors(args: dict[str, Any]) -> dict[str, Any]:
    """의사 목록 + 전문 분야 + 근무 요일."""
    weekday_map = ["월", "화", "수", "목", "금", "토", "일"]
    return {
        "doctors": [
            {
                "id": d["id"],
                "name": d["name"],
                "specialty": d["specialty"],
                "intro": d["intro"],
                "days": [weekday_map[w] for w in d["days_of_week"]],
            }
            for d in _DOCTORS
        ]
    }


async def list_available_slots(args: dict[str, Any]) -> dict[str, Any]:
    """지정 날짜(또는 오늘부터 N일)의 가용 슬롯 목록.

    args:
      date: 'YYYY-MM-DD' (optional — 없으면 오늘+7일)
      doctor_id: 특정 의사 필터 (optional)
      days: 조회 기간 (optional, default 1 if date 지정, 아니면 7)
    """
    from_date_str = args.get("date")
    if from_date_str:
        try:
            from_date = datetime.fromisoformat(from_date_str).date()
        except ValueError:
            from_date = _today()
        days = int(args.get("days", 1))
    else:
        from_date = _today()
        days = int(args.get("days", 7))

    target_doctor_id = args.get("doctor_id")

    out_slots: list[dict] = []
    for doctor in _DOCTORS:
        if target_doctor_id and doctor["id"] != target_doctor_id:
            continue
        for slot_dt in _generate_slots_for_doctor(doctor, from_date, days):
            if await rs.sismember(_CATEGORY, _member(slot_dt.isoformat(), doctor["id"])):
                continue
            out_slots.append({
                "datetime": slot_dt.isoformat(),
                "doctor_id": doctor["id"],
                "doctor_name": doctor["name"],
            })

    out_slots.sort(key=lambda s: s["datetime"])
    # 응답 크기 제한 — LLM context 폭주 방지
    return {"slots": out_slots[:50], "total": len(out_slots)}


async def check_availability(args: dict[str, Any]) -> dict[str, Any]:
    """특정 datetime + doctor_id 의 예약 가능 여부.

    args:
      datetime: 'YYYY-MM-DDTHH:MM[:SS]' (KST)
      doctor_id: 'dr_kim' 등
    """
    dt_str = args.get("datetime")
    if not dt_str:
        return {"available": False, "reason": "missing datetime"}
    # datetime 파싱 + tz 정규화
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_TZ)
    except ValueError:
        return {"available": False, "reason": "invalid datetime format"}

    doctor_id = args.get("doctor_id")
    doctor = next((d for d in _DOCTORS if d["id"] == doctor_id), None)
    if not doctor:
        return {"available": False, "reason": f"unknown doctor: {doctor_id}"}

    # 근무 요일 체크
    if dt.weekday() not in doctor["days_of_week"]:
        return {
            "available": False,
            "reason": "doctor not working that day",
            "doctor_name": doctor["name"],
        }

    # 근무 시간 + 점심 체크
    t = dt.time()
    if not (_WORK_START <= t < _WORK_END):
        return {
            "available": False,
            "reason": "outside working hours",
            "doctor_name": doctor["name"],
        }
    if _LUNCH_START <= t < _LUNCH_END:
        return {"available": False, "reason": "lunch break", "doctor_name": doctor["name"]}

    # 이미 예약?
    if await rs.sismember(_CATEGORY, _member(dt.isoformat(), doctor_id)):
        return {"available": False, "reason": "already booked", "doctor_name": doctor["name"]}

    return {"available": True, "doctor_name": doctor["name"]}


async def book(args: dict[str, Any]) -> dict[str, Any]:
    """예약 확정."""
    # 먼저 availability 재확인
    avail = await check_availability(
        {"datetime": args.get("datetime"), "doctor_id": args.get("doctor_id")}
    )
    if not avail.get("available"):
        return {"success": False, "reason": avail.get("reason", "not available")}

    dt = datetime.fromisoformat(args["datetime"])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TZ)
    await rs.sadd_member(_CATEGORY, _member(dt.isoformat(), args["doctor_id"]))

    return {
        "success": True,
        "confirmation": (
            f"{dt.strftime('%m월 %d일 %H:%M')} · {avail['doctor_name']} 선생님 · "
            f"{args.get('service','상담')} (예약자 {args.get('name','손님')})"
        ),
        "doctor_name": avail["doctor_name"],
    }
