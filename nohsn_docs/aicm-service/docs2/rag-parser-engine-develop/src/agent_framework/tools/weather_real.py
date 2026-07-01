"""PR-S — weather.lookup 실 API (Open-Meteo).

Open-Meteo: 무료 + API key 불필요. https://open-meteo.com/

PR-L2 의 weather_mock.py 와 인터페이스 동일 (date, location → summary).
환경변수 ``WEATHER_BACKEND`` = ``open-meteo`` (default) | ``mock`` 으로 전환.

날짜 정규화는 *LLM 위임* — 호출자 (plan_orchestrator) 가 ISO 형식 또는
자연어 자체를 args 에 넘기면, 여기서는 Open-Meteo API 가 받는 ISO 로 변환.
실패 시 그날 + 1 (내일) 폴백.
"""
from __future__ import annotations

import datetime
import os
from typing import Any

import httpx

from src.common.logging import get_logger

log = get_logger(__name__)


# 한국 주요 도시 → lat/lon (Open-Meteo geocoding 호출 회피용 캐시).
# 도시 이름이 이 dict 에 없으면 Open-Meteo geocoding API 로 lookup (무료).
# 이건 *위치 검색 캐시* 이지 *판단* 아님 — 좌표는 객관적 사실.
_LOCATION_HINTS: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780),
    "부산": (35.1796, 129.0756),
    "대구": (35.8714, 128.6014),
    "인천": (37.4563, 126.7052),
    "광주": (35.1595, 126.8526),
    "대전": (36.3504, 127.3845),
    "울산": (35.5384, 129.3114),
    "세종": (36.4801, 127.2891),
    "수원": (37.2636, 127.0286),
    "제주": (33.4996, 126.5312),
    "춘천": (37.8813, 127.7298),
    "강릉": (37.7519, 128.8761),
    "한강": (37.5326, 126.9905),
}

_API_BASE = "https://api.open-meteo.com/v1/forecast"
_GEO_BASE = "https://geocoding-api.open-meteo.com/v1/search"


async def _geocode(client: httpx.AsyncClient, name: str) -> tuple[float, float] | None:
    """도시 이름 → (lat, lon). _LOCATION_HINTS 안 맞으면 Open-Meteo geocoding."""
    if name in _LOCATION_HINTS:
        return _LOCATION_HINTS[name]
    try:
        r = await client.get(
            _GEO_BASE,
            params={"name": name, "count": 1, "language": "ko"},
            timeout=5.0,
        )
        if r.status_code != 200:
            return None
        results = (r.json() or {}).get("results") or []
        if not results:
            return None
        first = results[0]
        return (float(first["latitude"]), float(first["longitude"]))
    except Exception as e:  # noqa: BLE001
        log.debug("weather_geocode_failed", location=name, error=str(e))
        return None


def _normalize_date(date_raw: str) -> datetime.date:
    """ISO 형식만 받는다. plan_orchestrator 의 prompt 가 args 의 date 를 ISO
    8601 로 변환해 넘김 (PR-R: 제 1원칙 — 자연어 키워드 매핑 enum 금지).
    빈값/비ISO → 내일 fallback.
    """
    raw = (date_raw or "").strip()
    today = datetime.date.today()
    if not raw:
        return today + datetime.timedelta(days=1)
    try:
        return datetime.date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        pass
    # ISO 가 아닌 자연어가 들어오면 fallback. plan prompt 가 정확히 ISO 변환
    # 하도록 보강 (외부 도구 args 패턴).
    if False:
        # legacy stub — 제거된 키워드 enum 자리 유지용 no-op
        pass
    return today + datetime.timedelta(days=1)


def _wmo_to_korean(code: int) -> str:
    """Open-Meteo WMO weather code → 한국어 한 단어. 코드는 표준 WMO.

    표준 코드 매핑이라 *판단 X*. 외부 API 의 정의 그대로 옮긴 것.
    """
    # https://open-meteo.com/en/docs (WMO Weather interpretation codes)
    if code == 0:
        return "맑음"
    if code in (1, 2):
        return "구름 조금"
    if code == 3:
        return "흐림"
    if code in (45, 48):
        return "안개"
    if code in (51, 53, 55, 56, 57):
        return "이슬비"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "비"
    if code in (71, 73, 75, 77, 85, 86):
        return "눈"
    if code in (95, 96, 99):
        return "천둥번개"
    return "기상 정보"


async def lookup(args: dict[str, Any]) -> dict[str, Any]:
    """weather.lookup 실 API.

    Args:
    - ``date`` (선택): 자연어 또는 ISO. 빈값/실패 시 내일.
    - ``location`` (선택): "서울" 등 도시명. 빈값 시 서울.

    환경변수 ``WEATHER_BACKEND`` = ``mock`` 시 mock 폴백 (테스트/오프라인).

    반환: ``{success, date, location, condition, temp_high, temp_low, summary, source}``
    """
    backend = os.environ.get("WEATHER_BACKEND", "open-meteo").lower()
    if backend == "mock":
        from src.agent_framework.tools import weather_mock
        result = await weather_mock.lookup(args)
        result.setdefault("source", "mock")
        return result

    location = str(args.get("location") or "서울").strip() or "서울"
    date_raw = str(args.get("date") or "").strip()
    d = _normalize_date(date_raw)

    try:
        async with httpx.AsyncClient() as client:
            coord = await _geocode(client, location)
            if coord is None:
                # geocoding 실패 — 서울 폴백
                coord = _LOCATION_HINTS["서울"]
                location_resolved = f"{location} (좌표 미확인 → 서울 데이터)"
            else:
                location_resolved = location
            lat, lon = coord
            date_iso = d.isoformat()
            r = await client.get(
                _API_BASE,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "timezone": "Asia/Seoul",
                    "start_date": date_iso,
                    "end_date": date_iso,
                },
                timeout=8.0,
            )
            if r.status_code != 200:
                raise RuntimeError(f"open-meteo HTTP {r.status_code}: {r.text[:200]}")
            data = r.json() or {}
            daily = data.get("daily") or {}
            if not daily.get("time"):
                raise RuntimeError("open-meteo daily 응답 비어있음")
            wmo = int((daily.get("weathercode") or [0])[0])
            t_max = float((daily.get("temperature_2m_max") or [0])[0])
            t_min = float((daily.get("temperature_2m_min") or [0])[0])
            precip = float((daily.get("precipitation_sum") or [0])[0])
            condition = _wmo_to_korean(wmo)
            extra = f" (강수 {precip:.0f}mm)" if precip > 0 else ""
            summary = (
                f"{date_iso} {location_resolved} — {condition}, "
                f"최고 {t_max:.0f}도 / 최저 {t_min:.0f}도{extra}"
            )
            return {
                "success": True,
                "date": date_iso,
                "location": location_resolved,
                "condition": condition,
                "temp_high": round(t_max, 1),
                "temp_low": round(t_min, 1),
                "precipitation_mm": round(precip, 1),
                "summary": summary,
                "source": "open-meteo",
            }
    except Exception as e:  # noqa: BLE001
        log.warning(
            "weather_real_lookup_failed_fallback_mock",
            error=str(e),
            error_type=type(e).__name__,
        )
        # 실 API 실패 → mock 폴백 (사용자 답변 끊기지 않게).
        from src.agent_framework.tools import weather_mock
        result = await weather_mock.lookup(args)
        result["source"] = "mock-fallback"
        result["_real_api_error"] = str(e)
        return result
