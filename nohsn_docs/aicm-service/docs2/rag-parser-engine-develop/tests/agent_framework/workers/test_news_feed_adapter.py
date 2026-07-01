import asyncio
from unittest.mock import patch, MagicMock
from src.agent_framework.workers.news_feed_adapter import FeedparserAdapter


def test_parse_feed_normalizes_entries():
    """feedparser 결과를 NewsWorker 가 기대하는 dict 포맷으로 정규화."""
    fake_result = MagicMock()
    fake_result.entries = [
        MagicMock(title="기사 A", link="https://news.example/1",
                  summary="요약 A", published="Sat, 25 Apr 2026 12:00:00 +0900",
                  get=lambda key, default=None: None),
        MagicMock(title="기사 B", link="https://news.example/2",
                  summary="요약 B", published="Sat, 25 Apr 2026 13:00:00 +0900",
                  get=lambda key, default=None: None),
    ]
    fake_result.bozo = 0
    with patch("src.agent_framework.workers.news_feed_adapter.feedparser.parse",
               return_value=fake_result):
        adapter = FeedparserAdapter()
        feed = asyncio.run(adapter.parse_feed("https://example.com/rss"))
    assert len(feed["entries"]) == 2
    assert feed["entries"][0]["title"] == "기사 A"
    assert feed["entries"][0]["link"].startswith("https://news.example")


def test_parse_feed_handles_bozo_error():
    """feedparser bozo=1 (parsing error) 일 때도 entries 비워서 반환."""
    fake_result = MagicMock()
    fake_result.entries = []
    fake_result.bozo = 1
    fake_result.bozo_exception = Exception("malformed")
    with patch("src.agent_framework.workers.news_feed_adapter.feedparser.parse",
               return_value=fake_result):
        adapter = FeedparserAdapter()
        feed = asyncio.run(adapter.parse_feed("https://broken.example"))
    assert feed["entries"] == []
    assert feed.get("error")
