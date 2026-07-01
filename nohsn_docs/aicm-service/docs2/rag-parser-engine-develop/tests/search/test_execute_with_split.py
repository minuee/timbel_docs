import pytest
from types import SimpleNamespace
from src.search.service import SearchService


def _hit(doc, blk, score=0.5):
    return SimpleNamespace(document_id=doc, block_id=blk, chunk_id=blk, score=score)


def _make_service(monkeypatch, splitter, pipeline_results, latency_map=None, decomposed_map=None):
    """_execute_pipeline 를 서브쿼리별 결과 dict 로 모킹한 SearchService."""
    svc = SearchService.__new__(SearchService)  # __init__ 우회(외부 의존 회피)
    svc._query_splitter = splitter
    svc._decomp_enabled = True
    svc._decomp_max = 4
    svc._decomp_timeout = 2.0
    svc._decomp_concurrency = 2

    calls = []

    async def fake_pipeline(request, tenant_slug, tenant_config=None, repo_config=None):
        calls.append(request.query)
        hits = pipeline_results.get(request.query, [])
        trace = SimpleNamespace(steps=[])
        analysis = {"rewritten_query": request.query, "keywords": []}
        latency = (latency_map or {}).get(request.query, 10)
        decomposed = (decomposed_map or {}).get(request.query, None)
        return hits, trace, latency, decomposed, analysis

    svc._execute_pipeline = fake_pipeline
    svc._calls = calls
    return svc


class _Splitter:
    def __init__(self, result):
        self._result = result
    async def split(self, query, conversation_history, max_subqueries=4, timeout_s=2.0):
        return self._result


def _req(query):
    # model_copy 를 지원하는 최소 스텁
    class _R:
        def __init__(self, q):
            self.query = q
            self.conversation_history = None
            self.top_k = 5
            self.category_ids = None
        def model_copy(self, update=None):
            r = _R(self.query)
            r.category_ids = self.category_ids
            for k, v in (update or {}).items():
                setattr(r, k, v)
            return r
    return _R(query)


@pytest.mark.asyncio
async def test_n1_passthrough_calls_pipeline_once():
    svc = _make_service(None, _Splitter(["원본"]), {"원본": [_hit("d1", "a")]})
    out = await svc._execute_with_split(_req("원본"), "slug")
    assert svc._calls == ["원본"]
    assert [h.document_id for h in out[0]] == ["d1"]


@pytest.mark.asyncio
async def test_compound_fans_out_and_merges():
    svc = _make_service(
        None, _Splitter(["서브1", "서브2"]),
        {"서브1": [_hit("d1", "a1")], "서브2": [_hit("d2", "b1")]},
    )
    req = _req("원본복합")
    out = await svc._execute_with_split(req, "slug")
    assert set(svc._calls) == {"서브1", "서브2"}
    assert [(h.document_id) for h in out[0]] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_disabled_flag_single_pipeline():
    svc = _make_service(None, _Splitter(["서브1", "서브2"]), {"원본": [_hit("d1", "a")]})
    svc._decomp_enabled = False
    out = await svc._execute_with_split(_req("원본"), "slug")
    assert svc._calls == ["원본"]


@pytest.mark.asyncio
async def test_subquery_request_isolation_preserves_category_ids():
    svc = _make_service(None, _Splitter(["서브1", "서브2"]),
                        {"서브1": [_hit("d1", "a1")], "서브2": [_hit("d2", "b1")]})
    req = _req("원본")
    req.category_ids = ["cat-x"]
    await svc._execute_with_split(req, "slug")
    # 원본 request 의 query 는 변이되지 않아야(격리)
    assert req.query == "원본"


# --- F1: 병합 결과 score 내림차순 정렬 ---
@pytest.mark.asyncio
async def test_merged_hits_sorted_by_score_descending():
    # 서브1 → score 0.3, 서브2 → score 0.9; 병합 후 0.9 → 0.3 순이어야 함
    svc = _make_service(
        None, _Splitter(["서브1", "서브2"]),
        {"서브1": [_hit("d_low", "a1", score=0.3)], "서브2": [_hit("d_high", "b1", score=0.9)]},
    )
    out = await svc._execute_with_split(_req("원본"), "slug")
    scores = [h.score for h in out[0]]
    assert scores == sorted(scores, reverse=True), f"score 내림차순 아님: {scores}"
    assert out[0][0].document_id == "d_high"


# --- F2: rewritten_query 는 원본 쿼리 ---
@pytest.mark.asyncio
async def test_analysis_rewritten_query_equals_original():
    svc = _make_service(
        None, _Splitter(["서브1", "서브2"]),
        {"서브1": [_hit("d1", "a1")], "서브2": [_hit("d2", "b1")]},
    )
    req = _req("원본복합질문")
    out = await svc._execute_with_split(req, "slug")
    analysis = out[4]
    assert analysis["rewritten_query"] == "원본복합질문"


# --- F4: decomposed_dict 는 ok[0][3] ---
@pytest.mark.asyncio
async def test_decomposed_dict_from_first_subquery():
    decomposed_val = {"category_ids": ["cat-1"]}
    svc = _make_service(
        None, _Splitter(["서브1", "서브2"]),
        {"서브1": [_hit("d1", "a1")], "서브2": [_hit("d2", "b1")]},
        decomposed_map={"서브1": decomposed_val, "서브2": {"category_ids": ["cat-2"]}},
    )
    out = await svc._execute_with_split(_req("원본"), "slug")
    # decomposed_dict 는 첫 서브쿼리 결과(ok[0][3])여야 함
    assert out[3] == decomposed_val


# --- F5: latency 는 sum 이 아닌 max ---
@pytest.mark.asyncio
async def test_latency_is_max_not_sum():
    svc = _make_service(
        None, _Splitter(["서브1", "서브2"]),
        {"서브1": [_hit("d1", "a1")], "서브2": [_hit("d2", "b1")]},
        latency_map={"서브1": 30, "서브2": 50},
    )
    out = await svc._execute_with_split(_req("원본"), "slug")
    assert out[2] == 50  # max(30, 50) — sum 이면 80 이 됨
