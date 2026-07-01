from src.search.context_weighting import (
    build_context_text,
    combine_dense_vectors,
    context_fingerprint,
)


def test_build_context_text_joins_recent_turns():
    hist = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
        {"role": "assistant", "content": "d"},
    ]
    assert build_context_text(hist, max_turns=1) == "c d"


def test_build_context_text_empty():
    assert build_context_text(None) == ""
    assert build_context_text([]) == ""


def test_combine_dense_vectors_weighted():
    assert combine_dense_vectors([1.0, 0.0], [0.0, 1.0], 0.8, 0.2) == [0.8, 0.2]


def test_combine_empty_context_returns_primary():
    assert combine_dense_vectors([1.0, 2.0], [], 0.8, 0.2) == [1.0, 2.0]


def test_combine_length_mismatch_returns_primary():
    assert combine_dense_vectors([1.0, 2.0], [1.0], 0.8, 0.2) == [1.0, 2.0]


def test_context_fingerprint_differs_by_history():
    a = context_fingerprint([{"role": "user", "content": "x"}], 0.8, 0.2)
    b = context_fingerprint([{"role": "user", "content": "y"}], 0.8, 0.2)
    assert a != "" and a != b


def test_context_fingerprint_empty_history():
    assert context_fingerprint(None, 0.8, 0.2) == ""


def test_search_request_context_weighted_defaults():
    from uuid import uuid4
    from src.search.models import SearchRequest

    req = SearchRequest(query="q", tenant_id=uuid4())
    assert req.context_weighted is False
    assert req.w_c == 0.8
    assert req.w_p == 0.2
    req2 = SearchRequest(query="q", tenant_id=uuid4(), context_weighted=True)
    assert req2.context_weighted is True
