from types import SimpleNamespace
from src.search.merge import round_robin_merge


def _hit(doc, blk):
    return SimpleNamespace(document_id=doc, block_id=blk, chunk_id=blk)


def test_interleaves_two_lists():
    a = [_hit("d1", "a1"), _hit("d1", "a2")]
    b = [_hit("d2", "b1"), _hit("d2", "b2")]
    out = round_robin_merge([a, b], top_k=4)
    assert [(h.document_id, h.block_id) for h in out] == [
        ("d1", "a1"), ("d2", "b1"), ("d1", "a2"), ("d2", "b2")
    ]


def test_dedup_keeps_first_occurrence():
    dup = _hit("d1", "x")
    a = [dup, _hit("d1", "a2")]
    b = [_hit("d1", "x"), _hit("d2", "b2")]  # 같은 (d1,x) 중복
    out = round_robin_merge([a, b], top_k=10)
    keys = [(h.document_id, h.block_id) for h in out]
    assert keys == [("d1", "x"), ("d1", "a2"), ("d2", "b2")]


def test_truncates_to_top_k():
    a = [_hit("d1", f"a{i}") for i in range(5)]
    b = [_hit("d2", f"b{i}") for i in range(5)]
    out = round_robin_merge([a, b], top_k=3)
    assert len(out) == 3


def test_single_list_passthrough():
    a = [_hit("d1", "a1"), _hit("d1", "a2")]
    out = round_robin_merge([a], top_k=5)
    assert [(h.document_id, h.block_id) for h in out] == [("d1", "a1"), ("d1", "a2")]


def test_uneven_lists():
    a = [_hit("d1", "a1")]
    b = [_hit("d2", "b1"), _hit("d2", "b2"), _hit("d3", "b3")]
    out = round_robin_merge([a, b], top_k=10)
    assert [(h.document_id, h.block_id) for h in out] == [
        ("d1", "a1"), ("d2", "b1"), ("d2", "b2"), ("d3", "b3")
    ]


def test_empty_lists():
    assert round_robin_merge([], top_k=5) == []
    assert round_robin_merge([[], []], top_k=5) == []
