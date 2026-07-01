import pytest
from src.search.hybrid.es_keyword import ESKeywordSearcher


@pytest.mark.asyncio
async def test_resolve_aggregates_by_document_id(monkeypatch):
    searcher = ESKeywordSearcher.__new__(ESKeywordSearcher)

    class _FakeES:
        async def search(self, index, body):
            return {"aggregations": {"by_doc": {"buckets": [
                {"key": "docHANA", "max_score": {"value": 7.2}},
                {"key": "docHANTU", "max_score": {"value": 2.1}},
            ]}}}

    async def _fake_client():
        return _FakeES()
    monkeypatch.setattr(searcher, "_get_client", _fake_client)
    out = await searcher.resolve_documents_by_title(
        "하나코리아 펀드 환매 수수료", "aicm_t_blocks", ["repo1"], "ten1")
    assert out[0] == ("docHANA", 7.2)
    assert out[1][0] == "docHANTU"
