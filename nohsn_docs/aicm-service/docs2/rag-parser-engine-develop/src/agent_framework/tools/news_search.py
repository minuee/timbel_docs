"""PR-S — news.search 실 API (RSS 기반).

기본 백엔드: 공개 RSS 피드 (무료, key 불필요). 한국 언론사 RSS 직접 fetch
+ 발화 키워드 매칭. 환경변수 ``NEWS_BACKEND`` 로 전환:
- ``rss`` (default) — 공개 RSS 피드. 카테고리별 (정치/경제/IT/스포츠/생활).
- ``naver``           — Naver Open API (NAVER_CLIENT_ID/SECRET 필요).
- ``stub``            — fixture 데이터 (테스트/오프라인).

LLM 위임 원칙:
- 카테고리 필터 / 키워드 매칭은 *LLM 이 args 에 명시* (category, query).
- 여기서는 fetch + 단순 합집합. *어떤 뉴스가 중요한가* 의 판단은 호출자
  (plan_orchestrator + reasoning step) 가 LLM 으로 정렬·요약.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from src.common.logging import get_logger

log = get_logger(__name__)


# 카테고리 → RSS URL 후보 (다중 — 한 곳 fail 시 다른 곳 시도).
# 외부 표준 RSS 엔드포인트의 *주소* 일 뿐 — 본문 판단 X. 공개 피드.
_RSS_FEEDS: dict[str, list[str]] = {
    "정치": [
        "https://rss.donga.com/politics.xml",
        "https://www.hani.co.kr/rss/politics/",
    ],
    "경제": [
        "https://rss.donga.com/economy.xml",
        "https://www.hani.co.kr/rss/economy/",
    ],
    "사회": [
        "https://rss.donga.com/national.xml",
        "https://www.hani.co.kr/rss/society/",
    ],
    "IT": [
        "https://rss.donga.com/science.xml",
    ],
    "스포츠": [
        "https://rss.donga.com/sports.xml",
        "https://www.hani.co.kr/rss/sports/",
    ],
    "문화": [
        "https://rss.donga.com/culture.xml",
        "https://www.hani.co.kr/rss/culture/",
    ],
    "전체": [
        "https://rss.donga.com/total.xml",
        "https://www.hani.co.kr/rss/",
    ],
}


def _parse_rss_items(xml_text: str, max_items: int = 10) -> list[dict[str, Any]]:
    """RSS 2.0 / Atom 둘 다 try. 실패는 빈 list."""
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                items.append(
                    {"title": title, "summary": desc[:300], "link": link, "published": pub}
                )
        # Atom fallback
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
                summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href") if link_el is not None else ""
                pub = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
                if title:
                    items.append(
                        {"title": title, "summary": summary[:300], "link": link or "", "published": pub}
                    )
    except ET.ParseError as e:
        log.debug("news_rss_parse_failed", error=str(e))
    return items


async def _fetch_rss(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    try:
        r = await client.get(url, timeout=8.0, follow_redirects=True)
        if r.status_code != 200:
            return []
        return _parse_rss_items(r.text)
    except Exception as e:  # noqa: BLE001
        log.debug("news_rss_fetch_failed", url=url, error=str(e))
        return []


async def _fetch_naver(query: str, count: int) -> list[dict[str, Any]]:
    """Naver Open News API. 환경변수 필요. 미설정 시 빈 list."""
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not csec:
        return []
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://openapi.naver.com/v1/search/news.json",
                params={"query": query, "display": min(count, 20), "sort": "date"},
                headers={
                    "X-Naver-Client-Id": cid,
                    "X-Naver-Client-Secret": csec,
                },
                timeout=8.0,
            )
            if r.status_code != 200:
                return []
            data = r.json() or {}
            items = data.get("items") or []
            return [
                {
                    "title": (it.get("title") or "").replace("<b>", "").replace("</b>", ""),
                    "summary": (it.get("description") or "").replace("<b>", "").replace("</b>", ""),
                    "link": it.get("link") or it.get("originallink") or "",
                    "published": it.get("pubDate") or "",
                }
                for it in items[:count]
            ]
    except Exception as e:  # noqa: BLE001
        log.debug("news_naver_fetch_failed", error=str(e))
        return []


def _stub_items(category: str, count: int) -> list[dict[str, Any]]:
    """offline / 테스트용 stub. plan_orchestrator 가 *의도 정밀 추출* 검증."""
    return [
        {
            "title": f"[stub-{category}-{i+1}] 샘플 헤드라인",
            "summary": f"이 항목은 stub 데이터입니다 (NEWS_BACKEND={os.environ.get('NEWS_BACKEND', 'rss')}, 카테고리={category}).",
            "link": "",
            "published": "",
        }
        for i in range(count)
    ]


async def search(args: dict[str, Any]) -> dict[str, Any]:
    """news.search.

    Args (LLM 이 plan step 의 tool args 에 명시):
    - ``category`` (선택): "정치", "경제", "사회", "IT", "스포츠", "문화", "전체".
      해당 없으면 "전체".
    - ``query`` (선택): 키워드. naver 백엔드일 때 활용.
    - ``count`` (선택, 기본 5): 반환 항목 수.

    반환: ``{success, items: [{title, summary, link, published}], category, source, summary}``.

    의도 보존 원칙: 모든 카테고리·키워드 조합 허용 — 매칭 0건이면 빈 items
    + summary 에 "관련 기사 없음" 명시. plan executor 가 reasoning step 으로
    재시도 / 폴백 / 사용자 안내 결정.
    """
    backend = os.environ.get("NEWS_BACKEND", "rss").lower()
    category = str(args.get("category") or "전체").strip() or "전체"
    query = str(args.get("query") or "").strip()
    try:
        count = int(args.get("count") or 5)
    except (TypeError, ValueError):
        count = 5
    count = max(1, min(count, 20))

    items: list[dict[str, Any]] = []
    source = backend

    if backend == "stub":
        items = _stub_items(category, count)
        source = "stub"
    elif backend == "naver" and query:
        items = await _fetch_naver(query, count)
        source = "naver"
        if not items:
            # naver 빈 결과 시 RSS 폴백
            backend = "rss"
            source = "rss-fallback"

    if backend == "rss" and not items:
        feeds = _RSS_FEEDS.get(category) or _RSS_FEEDS["전체"]
        async with httpx.AsyncClient() as client:
            for url in feeds:
                got = await _fetch_rss(client, url)
                if got:
                    items.extend(got)
                    if len(items) >= count:
                        break
        items = items[:count]
        if not source.startswith("rss"):
            source = "rss"

    # query 키워드 매칭이 *명시* 됐으면 단순 부분 문자열 필터 — LLM 이 키워드
    # 결정. *어떤 게 중요한가* 의 판단은 호출자 LLM 이 처리.
    if query and items:
        q = query.lower()
        items = [it for it in items if q in (it["title"] + " " + it["summary"]).lower()] or items

    if items:
        titles = " · ".join(it["title"] for it in items[:3])
        summary = f"{category} 뉴스 {len(items)}건 — {titles}"
    else:
        summary = f"{category} 뉴스 결과 없음"

    return {
        "success": bool(items),
        "category": category,
        "items": items,
        "source": source,
        "summary": summary,
    }
