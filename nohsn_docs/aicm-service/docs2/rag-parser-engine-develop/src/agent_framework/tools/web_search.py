"""web.search — 일반 웹 검색 도구 (외부 지식 습득 1단계).

자비스 비전 시나리오 1: 사용자가 외부 지식 (예: "B200 vLLM Gemma-4 31B
KV cache 영향") 정리를 요청하면 plan_orchestrator 가 ``web.search`` →
``web.fetch`` → ``reasoning`` → ``kms.save_research`` 순으로 실행해 수집·합성·
KMS 저장한다.

백엔드 fallback (환경변수 기반, *판단 X — 단순 우선순위*):
1. ``NAVER_CLIENT_ID`` + ``NAVER_CLIENT_SECRET`` 셋팅 → Naver Open API
   (한국어 검색 결과 강함). category 인자로 ``blog`` / ``news`` / ``webkr`` /
   ``cafearticle`` 중 선택. 미명시 시 ``webkr``.
2. 위 미설정 + ``BRAVE_SEARCH_API_KEY`` 셋팅 → Brave Search API (글로벌).
3. 둘 다 미설정 → stub (의도 보존, ``"미구현"`` 응답).

LLM 위임 원칙:
- query 는 호출자 LLM 이 *발화 핵심* 추출. 하드코딩 키워드 처리 X.
- category 는 *의도와 무관* (백엔드 endpoint 매핑일 뿐) — 호출자가 명시
  안 하면 default ``webkr`` (naver) 사용.
- 결과 ranking / "어떤 게 중요한가" 의 판단은 호출자 reasoning step.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from src.common.logging import get_logger

log = get_logger(__name__)


# Naver Open API 카테고리 → endpoint path. naver 가 제공하는 카테고리만
# 명시 — 그 외 (예: "academic") 는 백엔드 자체가 미지원.
_NAVER_ENDPOINTS = {
    "blog": "https://openapi.naver.com/v1/search/blog.json",
    "news": "https://openapi.naver.com/v1/search/news.json",
    "web": "https://openapi.naver.com/v1/search/webkr.json",
    "webkr": "https://openapi.naver.com/v1/search/webkr.json",
    "cafearticle": "https://openapi.naver.com/v1/search/cafearticle.json",
}


def _strip_naver_tags(s: str) -> str:
    """Naver API 가 검색어 강조용 ``<b>`` 태그를 박아 보냄. 본문엔 불필요."""
    if not s:
        return ""
    return s.replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")


async def _search_naver(
    query: str, count: int, category: str
) -> list[dict[str, Any]]:
    """Naver Open API. 환경변수 미설정이거나 실패 시 빈 list."""
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not csec:
        return []

    cat_key = (category or "webkr").lower()
    endpoint = _NAVER_ENDPOINTS.get(cat_key) or _NAVER_ENDPOINTS["webkr"]

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                endpoint,
                params={"query": query, "display": min(max(count, 1), 20)},
                headers={
                    "X-Naver-Client-Id": cid,
                    "X-Naver-Client-Secret": csec,
                },
            )
            if r.status_code != 200:
                log.debug("web_search_naver_http", status=r.status_code, body=r.text[:200])
                return []
            data = r.json() or {}
            items_raw = data.get("items") or []
            return [
                {
                    "title": _strip_naver_tags(it.get("title") or ""),
                    "snippet": _strip_naver_tags(
                        it.get("description") or it.get("postdate") or ""
                    ),
                    "link": it.get("link") or it.get("originallink") or "",
                    "source": "naver",
                }
                for it in items_raw[:count]
            ]
    except Exception as e:  # noqa: BLE001
        log.debug("web_search_naver_failed", error=str(e))
        return []


async def _search_brave(query: str, count: int) -> list[dict[str, Any]]:
    """Brave Search API. 환경변수 미설정 시 빈 list."""
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": min(max(count, 1), 20)},
                headers={
                    "X-Subscription-Token": key,
                    "Accept": "application/json",
                },
            )
            if r.status_code != 200:
                log.debug("web_search_brave_http", status=r.status_code, body=r.text[:200])
                return []
            data = r.json() or {}
            items_raw = (data.get("web") or {}).get("results") or []
            return [
                {
                    "title": it.get("title") or "",
                    "snippet": it.get("description") or "",
                    "link": it.get("url") or "",
                    "source": "brave",
                }
                for it in items_raw[:count]
            ]
    except Exception as e:  # noqa: BLE001
        log.debug("web_search_brave_failed", error=str(e))
        return []


def _stub_items(query: str, count: int) -> list[dict[str, Any]]:
    """offline / 미설정 시 의도 보존 stub. plan executor 는 이 응답을 보고
    "현재 외부 검색 백엔드 미설정 — 의도 자체는 받았음" 안내."""
    return [
        {
            "title": f"[stub] '{query}' 검색 결과 {i + 1}",
            "snippet": (
                "외부 웹 검색 백엔드(NAVER_CLIENT_ID/SECRET 또는 "
                "BRAVE_SEARCH_API_KEY) 가 설정되지 않았습니다."
            ),
            "link": "",
            "source": "stub",
        }
        for i in range(min(count, 1))
    ]


async def search(args: dict[str, Any]) -> dict[str, Any]:
    """web.search — 일반 웹 검색.

    Args:
        query (str, required): 검색 질의. 호출자 LLM 이 발화 핵심 추출.
        count (int, default=5, max=20): 반환 항목 수.
        category (str, optional): naver 백엔드용 — ``blog`` / ``news`` /
            ``webkr`` / ``cafearticle``. brave 는 무시.

    Returns:
        ``{success, items: [{title, snippet, link, source}], summary, source}``.

        - success=true 면 items 1+ 건. false 는 "결과 없음" 또는 "백엔드 미설정".
        - source: ``naver`` / ``brave`` / ``stub`` — 어떤 백엔드가 응답했는지.
        - summary: 한 줄 한국어 요약 (상단 3건 title 합집합 또는 미구현 안내).

    원칙: 의도 보존 — 백엔드 미설정이라도 success=false + 명확한 안내.
    plan executor 가 다음 step (reasoning / 사용자 안내) 결정.
    """
    query = str(args.get("query") or "").strip()
    try:
        count = int(args.get("count") or 5)
    except (TypeError, ValueError):
        count = 5
    count = max(1, min(count, 20))
    category = str(args.get("category") or "").strip().lower()

    if not query:
        return {
            "success": False,
            "items": [],
            "summary": "web.search: query 미명시.",
            "source": "stub",
        }

    # Chokepoint 3 defense-in-depth — query 에 system prompt 가 박혀 들어오면
    # 외부 검색에 보내지 않는다. plan_orchestrator 의 LLM 이 args 채우면서
    # binding policy 텍스트를 베껴 넣은 사례 (samchully_voc 2026-05-07) 의
    # 마지막 차단선. engine 의 ToolArgPollution gate 가 우선 작동하지만,
    # 직접 호출 path (legacy / test) 도 보호.
    _PROMPT_FENCES = (
        "[BINDING POLICY",
        "[/BINDING POLICY]",
        "[에이전트 컨텍스트]",
        "## current agent:",
        "### goal\n",
        "### guidelines\n",
        "### allowed_tools\n",
        "### done_when\n",
    )
    if any(_m in query for _m in _PROMPT_FENCES) or len(query) > 4096:
        log.warning(
            "web_search_polluted_query_refused",
            query_preview=query[:200],
            length=len(query),
        )
        return {
            "success": False,
            "items": [],
            "summary": "web.search: 부적합한 query (system prompt fragment 또는 과도한 길이).",
            "source": "stub",
        }

    items: list[dict[str, Any]] = []
    backend = "stub"

    # 1) Naver 우선. category 없으면 webkr 일반 검색.
    items = await _search_naver(query, count, category or "webkr")
    if items:
        backend = "naver"

    # 2) Naver 결과 0 이거나 미설정 → Brave fallback.
    if not items:
        items = await _search_brave(query, count)
        if items:
            backend = "brave"

    # 3) 둘 다 실패 → stub.
    if not items:
        items = _stub_items(query, count)
        backend = "stub"

    if backend == "stub":
        summary = (
            f"web.search '{query}': 외부 검색 백엔드 미설정 (NAVER_CLIENT_ID 또는 "
            "BRAVE_SEARCH_API_KEY 필요)."
        )
        success = False
    else:
        titles = " · ".join(it["title"] for it in items[:3] if it.get("title"))
        summary = f"'{query}' 웹 검색 {len(items)}건 ({backend}) — {titles}"
        success = True

    return {
        "success": success,
        "items": items,
        "summary": summary,
        "source": backend,
    }
