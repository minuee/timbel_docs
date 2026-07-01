import json
import pytest
from src.search.query_splitter import QuerySplitter


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


class _FakeLLM:
    """AsyncOpenAI 호환 스텁 — chat.completions.create 모킹."""
    def __init__(self, content="", raise_exc=None):
        self._content = content
        self._raise = raise_exc
        self.chat = type("Chat", (), {"completions": self})()

    async def create(self, **kwargs):
        if self._raise:
            raise self._raise
        return _FakeResp(self._content)


def _splitter(content="", raise_exc=None):
    return QuerySplitter(llm_client=_FakeLLM(content, raise_exc), model="gemma-4-31B-it")


@pytest.mark.asyncio
async def test_split_compound_returns_n():
    s = _splitter('["한국투자테크펀드 위험등급", "한국투자테크펀드 환매 지급시기"]')
    out = await s.split("위험등급이랑 환매 언제", None)
    assert out == ["한국투자테크펀드 위험등급", "한국투자테크펀드 환매 지급시기"]


@pytest.mark.asyncio
async def test_split_simple_returns_one():
    s = _splitter('["미래에셋 차세대Fun 환매수수료"]')
    out = await s.split("미래에셋 차세대Fun 환매수수료", None)
    assert out == ["미래에셋 차세대Fun 환매수수료"]


@pytest.mark.asyncio
async def test_split_strips_json_fence():
    s = _splitter('```json\n["a", "b"]\n```')
    out = await s.split("q", None)
    assert out == ["a", "b"]


@pytest.mark.asyncio
async def test_split_caps_at_max():
    s = _splitter('["a","b","c","d","e","f"]')
    out = await s.split("q", None, max_subqueries=4)
    assert out == ["a", "b", "c", "d"]


@pytest.mark.asyncio
async def test_split_empty_array_falls_back_to_query():
    s = _splitter("[]")
    out = await s.split("원본질문", None)
    assert out == ["원본질문"]


@pytest.mark.asyncio
async def test_split_non_json_falls_back_to_query():
    s = _splitter("죄송합니다 분해할 수 없습니다")
    out = await s.split("원본질문", None)
    assert out == ["원본질문"]


@pytest.mark.asyncio
async def test_split_llm_exception_falls_back_to_query():
    s = _splitter(raise_exc=RuntimeError("llm down"))
    out = await s.split("원본질문", None)
    assert out == ["원본질문"]


@pytest.mark.asyncio
async def test_split_drops_non_string_and_blank_items():
    s = _splitter('["유효질문", "", 123, "  "]')
    out = await s.split("원본질문", None)
    assert out == ["유효질문"]


@pytest.mark.asyncio
async def test_split_strips_think_tags():
    # F3: <think>...</think> 블록이 JSON 앞에 있어도 정상 파싱
    s = _splitter('<think>내부 사고 내용</think>["a", "b"]')
    out = await s.split("q", None)
    assert out == ["a", "b"]
