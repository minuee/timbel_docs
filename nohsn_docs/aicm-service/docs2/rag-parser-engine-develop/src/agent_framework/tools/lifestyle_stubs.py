"""PR-S — 생활 편의 미구현 도구 stub 모음.

사용자 제 1원칙: 카탈로그에 *기능이 없어도* 의도가 정밀하게 추출되어야 함.
이 stub 들은 *plan executor 가 호출했을 때* 의도 보존 응답을 돌려줘서
사용자에게 "이 기능은 현재 미구현 — 의도는 정확히 받았음" 명확히 알림.

각 stub:
- args 그대로 받고
- success=false, items=[], summary="(미구현 안내)", _unimplemented=true
- 호출자 (engine plan executor) 가 trace + 사용자 안내에 활용

PR-L3 후속에서 *실 API 연동* 시 stub 자리만 교체. 인터페이스 동일 유지.
"""
from __future__ import annotations

from typing import Any


_UNIMPLEMENTED_BANNER = "(미구현 — 의도는 정확히 받았으며 후속 PR 에서 실 API 연동 예정)"


async def stock_quote(args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args.get("symbol") or args.get("ticker") or "").strip() or "(미명시)"
    return {
        "success": False,
        "symbol": symbol,
        "items": [],
        "summary": f"주식 시세 조회 ({symbol}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def stock_predict(args: dict[str, Any]) -> dict[str, Any]:
    target = str(args.get("symbol") or args.get("market") or args.get("query") or "(시장 전체)").strip()
    return {
        "success": False,
        "target": target,
        "items": [],
        "summary": f"주식 예측 ({target}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def restaurant_search(args: dict[str, Any]) -> dict[str, Any]:
    location = str(args.get("location") or "(미명시)").strip()
    cuisine = str(args.get("cuisine") or args.get("category") or "").strip()
    return {
        "success": False,
        "location": location,
        "cuisine": cuisine,
        "items": [],
        "summary": f"맛집 검색 ({location}, {cuisine or '전체'}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def movie_lookup(args: dict[str, Any]) -> dict[str, Any]:
    target = str(args.get("title") or args.get("query") or "(전체)").strip()
    return {
        "success": False,
        "target": target,
        "items": [],
        "summary": f"영화 정보 조회 ({target}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def movie_boxoffice(args: dict[str, Any]) -> dict[str, Any]:
    period = str(args.get("period") or args.get("date") or "(주간)").strip()
    return {
        "success": False,
        "period": period,
        "items": [],
        "summary": f"박스오피스 ({period}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def fx_rate(args: dict[str, Any]) -> dict[str, Any]:
    base = str(args.get("base") or "USD").strip()
    target = str(args.get("target") or "KRW").strip()
    return {
        "success": False,
        "base": base,
        "target": target,
        "summary": f"환율 ({base}→{target}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def transit_status(args: dict[str, Any]) -> dict[str, Any]:
    location = str(args.get("location") or args.get("line") or "(미명시)").strip()
    return {
        "success": False,
        "location": location,
        "summary": f"교통 정보 ({location}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def flight_price(args: dict[str, Any]) -> dict[str, Any]:
    origin = str(args.get("origin") or "(미명시)").strip()
    dest = str(args.get("destination") or args.get("dest") or "(미명시)").strip()
    return {
        "success": False,
        "origin": origin,
        "destination": dest,
        "items": [],
        "summary": f"항공권 가격 ({origin}→{dest}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def concert_schedule(args: dict[str, Any]) -> dict[str, Any]:
    artist = str(args.get("artist") or args.get("query") or "").strip() or "(전체)"
    return {
        "success": False,
        "artist": artist,
        "items": [],
        "summary": f"콘서트 일정 ({artist}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def menu_recommend(args: dict[str, Any]) -> dict[str, Any]:
    meal = str(args.get("meal") or args.get("when") or "(미명시)").strip()
    return {
        "success": False,
        "meal": meal,
        "items": [],
        "summary": f"메뉴 추천 ({meal}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def streaming_lookup(args: dict[str, Any]) -> dict[str, Any]:
    service = str(args.get("service") or "넷플릭스").strip()
    category = str(args.get("category") or args.get("query") or "신작").strip()
    return {
        "success": False,
        "service": service,
        "category": category,
        "items": [],
        "summary": f"스트리밍 정보 ({service}, {category}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }


async def air_quality(args: dict[str, Any]) -> dict[str, Any]:
    location = str(args.get("location") or "서울").strip()
    return {
        "success": False,
        "location": location,
        "summary": f"미세먼지·공기질 ({location}) — {_UNIMPLEMENTED_BANNER}",
        "_unimplemented": True,
    }
