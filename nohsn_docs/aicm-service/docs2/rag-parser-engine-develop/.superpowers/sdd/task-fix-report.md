# query-decomposition 코드리뷰 수정 보고서

날짜: 2026-06-22

## 변경 파일

- `src/search/service.py` — F1, F2, F4, F5, F6
- `src/search/query_splitter.py` — F3
- `tests/search/test_execute_with_split.py` — 4개 신규 테스트 추가, 헬퍼 확장
- `tests/search/test_query_splitter.py` — 1개 신규 테스트 추가

---

## 수정 내용

### F1 — Score 내림차순 재정렬 (critical)

`round_robin_merge` 이후 merged 리스트를 score 내림차순으로 정렬한다.
`round_robin_merge` 자체는 변경하지 않았다.

```python
merged.sort(key=lambda h: (h.score if getattr(h, "score", None) is not None else 0.0), reverse=True)
```

### F2 — rewritten_query = 원본 쿼리

split 경로 반환 시 analysis의 `rewritten_query`를 첫 서브쿼리의 query가 아닌 `request.query` (원본)로 설정한다.

```python
analysis = dict(ok[0][4])
analysis["rewritten_query"] = request.query
```

### F3 — `<think>` 태그 제거

`QuerySplitter._parse`에서 JSON 파싱 전에 `<think>...</think>` 블록을 제거한다.
기존 `re` import를 그대로 사용한다.

```python
text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
```

### F4 — decomposed_dict 전달

split 경로 반환 시 4번째 원소를 `None` 대신 `ok[0][3]` (첫 서브쿼리의 decomposed_dict)로 전달한다.

```python
return merged, first_trace, total_latency, ok[0][3], analysis
```

### F5 — latency max

병렬 실행이므로 총 latency를 `sum`이 아닌 `max`로 계산한다.

```python
total_latency = max(r[2] for r in ok)
```

### F6 — 서브쿼리 reformulate 비활성화

서브쿼리 request 생성 시 `enable_llm_rewrite=False`를 추가해 서브쿼리가 다시 LLM rewrite 단계를 거치지 않도록 한다.

```python
sub_req = request.model_copy(update={"query": sub_q, "enable_llm_rewrite": False})
```

---

## 테스트 결과

### 대상 테스트

```
python -m pytest tests/search/test_execute_with_split.py tests/search/test_query_splitter.py tests/search/test_round_robin_merge.py -v
```

결과: **23 passed** (GREEN)

### 전체 search 테스트

```
python -m pytest tests/search/ -v
```

결과: **136 passed, 4 failed**

실패 4건(`test_search_excluded_filter.py` — frontend-v3 TypeScript 파일 부재)은 변경 전에도 동일하게 실패하는 기존 실패다. 본 수정과 무관하다.

---

## 주의사항

- `_execute_pipeline` 본문, `rag_assist.py`, `round_robin_merge` 로직은 변경하지 않았다.
- 5-tuple 시그니처 유지: `(hits, trace, latency_ms, decomposed_dict, analysis)`.
- off/N1 위임 경로(splitter None이거나 len <= 1일 때 _execute_pipeline 직접 호출)는 변경하지 않았다.
- F4로 인해 분해 쿼리의 첫 서브쿼리 decomposed_dict가 전파되는데, 이 값이 None이면 기존 동작과 동일하다.
