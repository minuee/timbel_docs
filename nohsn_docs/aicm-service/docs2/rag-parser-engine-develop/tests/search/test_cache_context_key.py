from uuid import UUID

from src.search.cache import SearchCache

REPO = UUID("f7dc80c9-4fbe-4832-aa72-cf97c268c10c")


def test_cache_key_differs_by_context_key():
    k_none = SearchCache._build_cache_key(query="적립 안돼", repository_id=REPO, context_key="")
    k_ctx = SearchCache._build_cache_key(query="적립 안돼", repository_id=REPO, context_key="abc123")
    assert k_none != k_ctx


def test_cache_key_same_when_context_key_same():
    a = SearchCache._build_cache_key(query="q", repository_id=REPO, context_key="x")
    b = SearchCache._build_cache_key(query="q", repository_id=REPO, context_key="x")
    assert a == b
