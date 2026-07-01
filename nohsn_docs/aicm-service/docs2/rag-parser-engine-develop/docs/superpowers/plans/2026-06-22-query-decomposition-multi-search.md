# 다중질문 분해 → 멀티검색 → 병합 구현 계획 (#2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 복합질문을 LLM으로 N개 자기완결 서브질문으로 분해→서브쿼리별 독립 검색→라운드로빈 병합으로 각 의도를 top_k에 보장한다(콜봇+어드바이저, 플래그 on/off).

**Architecture:** 신규 `QuerySplitter`(LLM)와 순수 `round_robin_merge`를 만들고, `SearchService._execute_with_split`(= `_execute_pipeline`와 동일 5-tuple 시그니처)가 분해→서브쿼리 request 격리(model_copy)→동시제한 fan-out(`_execute_pipeline` 재사용)→병합을 수행한다. 3개 진입점에서 `_execute_pipeline`→`_execute_with_split` swap. 플래그 off/N=1이면 `_execute_pipeline` 그대로 위임(회귀 0).

**Tech Stack:** Python 3.11, asyncio, pydantic(SearchRequest/SearchHit), AsyncOpenAI(gemma via VLLM_URL), pytest(asyncio_mode=auto).

**Spec:** `docs/superpowers/specs/2026-06-22-query-decomposition-multi-search-design.md`

## Global Constraints
- 이모지 금지(코드/커밋/파일). (rag-parser CLAUDE.md §2)
- 하드코딩 금지(도메인 키워드/정답 문자열). 분해는 LLM, 규칙리스트 금지.
- 검증 multi-turn 회귀(중복요청/부정형/시간slot/참조해소) 포함.
- `_execute_with_split` 반환 = `_execute_pipeline`와 **동일 5-tuple** `(list[SearchHit], SearchTrace, int, dict|None, QueryAnalysis)`.
- 서브쿼리 request는 **`model_copy`로 격리**(in-place 변이 금지). 콜봇 명시 `category_ids`는 복사본에 보존.
- 서브검색 동시도 **`asyncio.Semaphore`≤2**(단일 cuda:0 경합). 무제한 gather 금지.
- 플래그 default on, off=현행 단일검색. fallback 항상 on(분해 실패→원본 단일).
- branch `develop`. 커밋 한국어.

## File Structure
- Create: `src/search/query_splitter.py` — `QuerySplitter`(LLM 분해, robust 파싱, fallback).
- Create: `src/search/merge.py` — `round_robin_merge`(순수 함수, dedup).
- Modify: `src/search/service.py` — `_execute_with_split` 추가, `__init__`에 `query_splitter` 파라미터, env 플래그, 3 진입점 swap(307,1418, 및 아래 Task4).
- Modify: `src/search/factory.py` — `QuerySplitter` 생성·주입.
- Modify: `src/api/routers/rag_assist.py:242` — `_execute_pipeline`→`_execute_with_split`.
- Test: `tests/search/test_query_splitter.py`, `tests/search/test_round_robin_merge.py`, `tests/search/test_execute_with_split.py`.

> 필터 처리(spec §5.1) 주: 콜봇 명시 `category_ids`는 model_copy로 전 서브쿼리 보존. 서브쿼리별 nature/entity 재분해는 `_execute_pipeline` 내부에서 일어나며(서브쿼리가 자기완결이라 적정), `_execute_pipeline` 내부 무수정 원칙을 지키기 위해 **"필터 1회 추출 공유"는 본 구현에서 생략**하고 model_copy 격리로 대체한다(Task 3 주석에 명시). **사용자 확정(2026-06-22)**: 서브쿼리 decompose가 LLM을 안 타(임베딩만·병렬 흡수) latency 이득이 없고, `_execute_pipeline` 무수정으로 회귀 위험을 줄이므로 단순화 채택.

---

### Task 1: QuerySplitter (LLM 분해 + robust 파싱 + fallback)

**Files:**
- Create: `src/search/query_splitter.py`
- Test: `tests/search/test_query_splitter.py`

**Interfaces:**
- Produces: `class QuerySplitter` with `async def split(self, query: str, conversation_history: list[dict] | None, max_subqueries: int = 4, timeout_s: float = 2.0) -> list[str]`. 분해 불가/단순/실패 시 `[query]`. LLM client는 생성자 주입(`AsyncOpenAI` 호환, `.chat.completions.create`), model은 생성자 인자.

- [ ] **Step 1: 실패 테스트 작성**

`tests/search/test_query_splitter.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/search/test_query_splitter.py -v`
Expected: FAIL — `ModuleNotFoundError: src.search.query_splitter`.

- [ ] **Step 3: 구현**

`src/search/query_splitter.py`:
```python
"""검색 쿼리 분해기 — 복합/멀티턴 질문을 자기완결 서브질문 N개로 분해(LLM).

기존 필터추출 QueryDecomposer 와 역할이 다르다(혼동 금지):
QueryDecomposer = 필터(category/nature/entity) 추출. QuerySplitter = 질문을 서브질문으로 분할.
"""
from __future__ import annotations

import asyncio
import json
import re

import structlog

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = (
    "너는 검색 쿼리 분해기다. 대화 맥락을 사용해 마지막 사용자 발화의 생략·대명사·참조를 "
    "해소하고, 의미 단위로 독립적이고 자기완결적인 검색용 서브질문으로 분해한다. "
    "복합이면 여러 개, 단순이면 1개. 각 서브질문은 그 자체로 검색 가능해야 한다. "
    'JSON 배열로만 답하라. 예: ["서브질문1", "서브질문2"]'
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class QuerySplitter:
    def __init__(self, llm_client, model: str):
        self._llm = llm_client
        self._model = model

    async def split(
        self,
        query: str,
        conversation_history: list[dict] | None,
        max_subqueries: int = 4,
        timeout_s: float = 2.0,
    ) -> list[str]:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": query})
        try:
            resp = await asyncio.wait_for(
                self._llm.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=256,
                ),
                timeout=timeout_s,
            )
            content = resp.choices[0].message.content or ""
        except Exception as exc:
            log.warning("query_split_llm_failed", error=str(exc))
            return [query]

        subs = self._parse(content)
        if not subs:
            return [query]
        return subs[:max_subqueries]

    @staticmethod
    def _parse(content: str) -> list[str]:
        text = content.strip()
        m = _FENCE_RE.search(text)
        if m:
            text = m.group(1).strip()
        try:
            arr = json.loads(text)
        except Exception:
            return []
        if not isinstance(arr, list):
            return []
        out = []
        for item in arr:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/search/test_query_splitter.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/search/query_splitter.py tests/search/test_query_splitter.py
git commit -m "feat(query-decomposition): QuerySplitter(LLM 분해+robust 파싱+fallback)+단위테스트"
```

---

### Task 2: round_robin_merge (순수 병합 함수)

**Files:**
- Create: `src/search/merge.py`
- Test: `tests/search/test_round_robin_merge.py`

**Interfaces:**
- Produces: `def round_robin_merge(hit_lists: list[list], top_k: int) -> list` — 각 리스트에서 순번대로 인터리브, `(document_id, block_id|chunk_id)` 기준 중복 제거(첫 등장 유지), top_k 절단. hit는 `.document_id`, `.block_id`, `.chunk_id` 속성을 가진 객체(SearchHit 덕타이핑).

- [ ] **Step 1: 실패 테스트 작성**

`tests/search/test_round_robin_merge.py`:
```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/search/test_round_robin_merge.py -v`
Expected: FAIL — `ModuleNotFoundError: src.search.merge`.

- [ ] **Step 3: 구현**

`src/search/merge.py`:
```python
"""서브쿼리 결과 라운드로빈 병합 — 각 의도(서브쿼리)의 대표성을 top_k에 보장."""
from __future__ import annotations


def _key(hit):
    blk = getattr(hit, "block_id", None) or getattr(hit, "chunk_id", None)
    return (getattr(hit, "document_id", None), blk)


def round_robin_merge(hit_lists: list[list], top_k: int) -> list:
    """각 서브쿼리 결과 리스트에서 순번대로 인터리브, 중복(첫 등장 유지) 제거, top_k 절단."""
    merged: list = []
    seen: set = set()
    if not hit_lists:
        return merged
    max_len = max((len(h) for h in hit_lists), default=0)
    for rank in range(max_len):
        for lst in hit_lists:
            if rank >= len(lst):
                continue
            hit = lst[rank]
            k = _key(hit)
            if k in seen:
                continue
            seen.add(k)
            merged.append(hit)
            if len(merged) >= top_k:
                return merged
    return merged
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/search/test_round_robin_merge.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/search/merge.py tests/search/test_round_robin_merge.py
git commit -m "feat(query-decomposition): round_robin_merge 순수 병합 함수 + 단위테스트"
```

---

### Task 3: `_execute_with_split` 오케스트레이터 + 플래그 + 주입 파라미터

**Files:**
- Modify: `src/search/service.py` (`__init__` 79-, `_execute_pipeline` 다음에 신규 메서드)
- Test: `tests/search/test_execute_with_split.py`

**Interfaces:**
- Consumes: Task1 `QuerySplitter.split`, Task2 `round_robin_merge`, 기존 `self._execute_pipeline(request, tenant_slug, tenant_config, repo_config) -> 5-tuple`.
- Produces: `async def _execute_with_split(self, request, tenant_slug, tenant_config=None, repo_config=None) -> tuple[list[SearchHit], SearchTrace, int, dict|None, QueryAnalysis]` — `_execute_pipeline`와 동일 시그니처/반환. `SearchService.__init__`에 `query_splitter=None` 파라미터 추가. 클래스 상수/ env: `SEARCH_QUERY_DECOMPOSITION_ENABLED`(default true), `SEARCH_DECOMPOSITION_MAX_SUBQUERIES`(4), `SEARCH_DECOMPOSITION_TIMEOUT_S`(2.0), 동시도 2.

- [ ] **Step 1: 실패 테스트 작성**

`tests/search/test_execute_with_split.py`:
```python
import pytest
from types import SimpleNamespace
from src.search.service import SearchService


def _hit(doc, blk):
    return SimpleNamespace(document_id=doc, block_id=blk, chunk_id=blk, score=0.5)


def _make_service(monkeypatch, splitter, pipeline_results):
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
        return hits, trace, 10, None, analysis

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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/search/test_execute_with_split.py -v`
Expected: FAIL — `AttributeError: 'SearchService' object has no attribute '_execute_with_split'`.

- [ ] **Step 3: 구현 — `__init__` 파라미터 + 플래그 + 메서드**

(3a) `src/search/service.py` `__init__`(79-) 파라미터 목록에 `query_splitter=None` 추가하고 본문(117행 `self._query_decomposer = ...` 인근)에 추가:
```python
        self._query_splitter = query_splitter  # QuerySplitter (선택적, #2 분해→멀티검색)
        import os
        self._decomp_enabled = os.getenv("SEARCH_QUERY_DECOMPOSITION_ENABLED", "true").lower() == "true"
        self._decomp_max = int(os.getenv("SEARCH_DECOMPOSITION_MAX_SUBQUERIES", "4"))
        self._decomp_timeout = float(os.getenv("SEARCH_DECOMPOSITION_TIMEOUT_S", "2.0"))
        self._decomp_concurrency = 2
```

(3b) `_execute_pipeline`(702-) 메서드 정의 바로 위 또는 아래에 신규 메서드 추가:
```python
    async def _execute_with_split(
        self,
        request: SearchRequest,
        tenant_slug: str,
        tenant_config: dict | None = None,
        repo_config: dict | None = None,
    ) -> tuple[list[SearchHit], SearchTrace, int, dict | None, QueryAnalysis]:
        """분해→서브쿼리별 _execute_pipeline(동시제한)→라운드로빈 병합.

        _execute_pipeline 와 동일 5-tuple 반환. 플래그 off/splitter 없음/N<=1 이면 단일 위임(회귀 0).
        서브쿼리 request 는 model_copy 로 격리(in-place 변이 금지), 콜봇 명시 category_ids 보존.
        """
        if not self._decomp_enabled or self._query_splitter is None:
            return await self._execute_pipeline(request, tenant_slug, tenant_config, repo_config)

        sub_queries = await self._query_splitter.split(
            request.query,
            getattr(request, "conversation_history", None),
            max_subqueries=self._decomp_max,
            timeout_s=self._decomp_timeout,
        )
        if len(sub_queries) <= 1:
            return await self._execute_pipeline(request, tenant_slug, tenant_config, repo_config)

        from src.search.merge import round_robin_merge
        import asyncio

        sem = asyncio.Semaphore(self._decomp_concurrency)

        async def _one(sub_q: str):
            sub_req = request.model_copy(update={"query": sub_q})
            async with sem:
                try:
                    return await self._execute_pipeline(sub_req, tenant_slug, tenant_config, repo_config)
                except Exception as exc:
                    log.warning("split_subquery_failed", sub_query=sub_q[:80], error=str(exc))
                    return None

        results = await asyncio.gather(*[_one(q) for q in sub_queries])
        ok = [r for r in results if r is not None]
        if not ok:
            # 전부 실패 → 원본 단일검색 fallback
            return await self._execute_pipeline(request, tenant_slug, tenant_config, repo_config)

        hit_lists = [r[0] for r in ok]
        merged = round_robin_merge(hit_lists, request.top_k)
        # trace/analysis 는 첫 서브쿼리 것, latency 는 합산(병렬이라 근사), decomposed 는 None.
        first_trace = ok[0][1]
        total_latency = sum(r[2] for r in ok)
        first_analysis = ok[0][4]
        return merged, first_trace, total_latency, None, first_analysis
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/search/test_execute_with_split.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/search/service.py tests/search/test_execute_with_split.py
git commit -m "feat(query-decomposition): _execute_with_split 오케스트레이터(분해→동시제한 fan-out→병합)+플래그+테스트"
```

---

### Task 4: 배선 (factory 주입 + 3 진입점 swap)

**Files:**
- Modify: `src/search/factory.py` (QuerySplitter 생성·주입)
- Modify: `src/search/service.py:307`, `:1418` (콜봇 진입점 2곳)
- Modify: `src/api/routers/rag_assist.py:242` (어드바이저)

**Interfaces:**
- Consumes: Task3 `_execute_with_split`(=_execute_pipeline 동일 시그니처), Task1 `QuerySplitter`.

- [ ] **Step 1: factory 주입**

`src/search/factory.py` — `llm_client` 생성(43-) 이후, `SearchService(...)` 생성 인자에 `query_splitter` 추가. `query_decomposer` 생성 블록(86-90) 인근에:
```python
        query_splitter = None
        if llm_client is not None:
            try:
                from src.search.query_splitter import QuerySplitter
                query_splitter = QuerySplitter(
                    llm_client=llm_client,
                    model=getattr(settings, "VLLM_MODEL", "gemma-4-31b"),
                )
                log.info("query_splitter_initialized")
            except Exception as exc:
                log.warning("query_splitter_init_failed", error=str(exc))
```
그리고 `SearchService(...)` 호출 인자에 `query_splitter=query_splitter,` 추가.

- [ ] **Step 2: 콜봇 진입점 swap (service.py 307, 1418)**

`service.py:307`(search() 비-fallback 분기)와 `:1418`(_search_with_fallback 내부 1차 시도)의 `await self._execute_pipeline(` 를 `await self._execute_with_split(` 로 교체(인자 동일). 

주의: 다른 `_execute_pipeline` 호출(464 cross-encoder, 541, 608, 664, 1320 — 내부 서브루틴)은 **교체 금지**. 정확히 307과 1418 두 곳만(검색 진입 파이프라인). 교체 후 grep으로 확인.

- [ ] **Step 3: 어드바이저 진입점 swap (rag_assist.py:242)**

`src/api/routers/rag_assist.py:242` `_hits, _trace, _latency, _decomposed, _analysis = await _svc._execute_pipeline(request=_req, tenant_slug=_preresolved_slug)` 에서 `_execute_pipeline` → `_execute_with_split`(인자 동일). 264행(다른 용도 _t_hits 보강 검색)은 **교체 금지**(필요 시 확인).

- [ ] **Step 4: 문법/회귀 확인**

Run: `python -c "import ast; ast.parse(open('src/search/service.py',encoding='utf-8').read()); ast.parse(open('src/search/factory.py',encoding='utf-8').read()); ast.parse(open('src/api/routers/rag_assist.py',encoding='utf-8').read()); print('AST OK')"`
Expected: `AST OK`

Run: `grep -nE '_execute_with_split|_execute_pipeline' src/search/service.py src/api/routers/rag_assist.py | head -30`
Expected: 307·1418·rag_assist:242 = `_execute_with_split`; 464·541·608·664·1320 = `_execute_pipeline` 유지.

Run: `python -m pytest tests/search/ -v`
Expected: 신규 3 테스트 파일 + 기존 search 테스트 무회귀(기존 통과분 유지).

- [ ] **Step 5: 커밋**

```bash
git add src/search/factory.py src/search/service.py src/api/routers/rag_assist.py
git commit -m "feat(query-decomposition): QuerySplitter 주입 + 3 진입점(콜봇 307/1418, 어드바이저 242) _execute_with_split 배선"
```

---

## Rollout & Validation (운영 — 코드 후, 사전 공지 필요)
1. **timbel 배포**: lucas-kms-api rebuild→up (search는 api 컨테이너).
2. **플래그 on(default)** 확인. env로 off 토글 동작 확인(=현행 단일검색).
3. **효과**: "위험등급이랑 환매 언제" → 두 의도 chunk 모두 top_k. 멀티턴 "그거 …" 참조해소.
4. **회귀(필수, multi-turn)**: 단순질문 무회귀(N=1), 단일의도 정확도, threshold 통과율, off=현행 동등.
5. **fan-out GPU 경합 latency 실측**(spec §13): 복합질문 동시제한(≤2)서 콜봇 total 예산 내 확인. 동시부하 tail 점검 → 필요 시 `_decomp_concurrency`/순차 조정. 어드바이저 3 LLM 홉 누적 latency 점검.
6. **AWS(POC)**: timbel 통과 후 동일.
7. **롤백**: env 플래그 off(즉시) 또는 코드 revert.

## Self-Review (작성자 체크)
- Spec coverage: §5 아키텍처=Task1/2/3; §5.1 격리·동시제한·진입점=Task3/4(필터1회공유는 model_copy 격리로 대체, 상단 주에 명시·사용자 확인 대상); §6 QuerySplitter=Task1; §7 병합=Task2; §8 플래그=Task3; §10 fallback=Task3; §12 테스트=Task1/2/3; §13 검증=Rollout.
- Placeholder: 없음(모든 step 코드/명령 포함).
- Type consistency: `_execute_with_split` 5-tuple = `_execute_pipeline` 일치. `QuerySplitter.split`/`round_robin_merge` 시그니처 Task 간 일치.
- 단순화 1건(필터 1회공유 생략→model_copy 격리): plan 제시 시 사용자 확인.
