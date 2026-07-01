"""feedparser 어댑터 — NewsWorker 가 사용하는 parse_feed 인터페이스 구현.

NewsWorker 는 외부에서 parse_feed(url) -> {"entries": [...]} 를 주입받는다.
이 어댑터는 feedparser 동기 라이브러리를 async wrapper 로 감싸 normalized dict 반환.
"""
from __future__ import annotations
import asyncio
import feedparser
from typing import Any


def _entry_to_dict(entry: Any) -> dict:
    return {
        "title": getattr(entry, "title", None) or "",
        "link": getattr(entry, "link", None) or "",
        "summary": getattr(entry, "summary", None) or "",
        "published": getattr(entry, "published", None) or "",
    }


class FeedparserAdapter:
    """sync feedparser 를 asyncio.to_thread 로 감싸서 NewsWorker 에 호환되는 시그너처 제공."""

    async def parse_feed(self, url: str) -> dict:
        result = await asyncio.to_thread(feedparser.parse, url)
        if getattr(result, "bozo", 0) and not result.entries:
            return {"entries": [], "error": str(getattr(result, "bozo_exception", "parse error"))}
        return {"entries": [_entry_to_dict(e) for e in (result.entries or [])]}


# 표준 한국 뉴스 RSS 후보 (참고용 — 실제 사용 시 환경 변수 또는 설정으로 주입)
DEFAULT_KOREAN_NEWS_FEEDS = [
    "https://www.yna.co.kr/RSS/economy.xml",         # 연합뉴스 경제 (확인필요)
    "https://www.hani.co.kr/rss/economy/",            # 한겨레 경제 (확인필요)
    "https://rss.donga.com/economy.xml",              # 동아일보 경제 (확인필요)
]
