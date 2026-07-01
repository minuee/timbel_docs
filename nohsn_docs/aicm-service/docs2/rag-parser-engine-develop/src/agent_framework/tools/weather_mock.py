"""PR-L2 — weather.lookup mock tool.

자비스 비전 시나리오의 첫 외부 tool. 실제 weather API 통합 (PR-L3 또는 PR-O)
전 *plan executor 의 tool step 작동 검증* 목적의 mock.

LLM 의 plan_generation 이 ``[tool, weather.lookup, {date:내일, location:서울}]``
같은 step 만들 때 호출. mock 은 *date 파라미터 보고 결정적 가짜 결과* 반환 —
실제 외부 API 호출 없이 plan executor + reasoning step 동작 검증.

후속 PR-L3 에서 실제 API (OpenWeather/기상청) 통합. mock 인터페이스 유지하면
교체 시 plan executor 코드 변경 X.
"""
from __future__ import annotations

import datetime
from typing import Any


async def lookup(args: dict[str, Any]) -> dict[str, Any]:
    """날씨 조회 mock.

    Args (LLM 이 plan step 의 tool args 로 넘김):
    - ``date``: "내일" / "오늘" / "2026-04-29" 등 자연어 또는 ISO
    - ``location``: "서울" / "부산" 등 (옵션)

    Returns: ``{date, location, condition, temp_high, temp_low, summary}``.
    """
    date_raw = str(args.get("date") or "").strip()
    location = str(args.get("location") or "서울").strip()

    # date 정규화 — ISO 형식만 받는다. plan_orchestrator 가 args 의 date 를
    # 항상 ISO 로 보내도록 prompt 가이드. 자연어 매핑 코드 (오늘/내일/모레 등
    # 키워드 enum) 은 *제 1원칙 위반* 이라 제거 — LLM 이 ISO 로 변환해 넘김.
    # ISO 가 아니면 graceful fallback (내일).
    today = datetime.date.today()
    try:
        d = datetime.date.fromisoformat(date_raw[:10]) if date_raw else (
            today + datetime.timedelta(days=1)
        )
    except (ValueError, TypeError):
        d = today + datetime.timedelta(days=1)

    # mock 결정적 결과 — 날짜 day 의 % 4 로 condition 결정
    conditions = ["맑음", "구름 조금", "흐림", "비"]
    condition = conditions[d.day % len(conditions)]
    temp_high = 18 + (d.day % 7)
    temp_low = 8 + (d.day % 5)

    summary = (
        f"{d.isoformat()} {location} — {condition}, "
        f"최고 {temp_high}도 / 최저 {temp_low}도"
    )

    return {
        "success": True,
        "date": d.isoformat(),
        "location": location,
        "condition": condition,
        "temp_high": temp_high,
        "temp_low": temp_low,
        "summary": summary,
        "_note": "mock — 실제 API 미연동 (PR-L3 후속)",
    }
