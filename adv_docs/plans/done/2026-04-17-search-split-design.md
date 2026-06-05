# 문서 검색 keyword/hybrid 분리 설계

## 목표

현재 단일 hybrid 검색 요청을 keyword/hybrid 두 개의 독립 요청으로 분리하여, keyword 결과(문서 목록)를 먼저 표시하고 hybrid 결과(요약 정보)를 비동기로 로딩하는 UX를 구현한다.

## 현재 상태

- 프론트엔드 `handleDocumentSearch`가 `DocumentSearchAPI`로 단일 hybrid 요청 발송
- 백엔드 `SearchService`가 `mode: 'hybrid'`를 하드코딩하여 검색엔진 호출
- 응답의 `results[].metadata.search_summary`와 문서 내용이 한 번에 도착

## 변경 방향

### 백엔드

1. **DTO**: `SearchRequestDto`에 `mode?: 'hybrid' | 'keyword'` 필드 추가 (기본값: `'hybrid'`)
2. **SearchService**: `mode`에 따라 검색엔진 파라미터 분기

| 파라미터 | keyword | hybrid |
|---------|---------|--------|
| `mode` | `'keyword'` | `'hybrid'` |
| `use_hyde` | `false` | `true` |
| `enable_rerank` | `false` | `true` |
| `enable_llm_rewrite` | `false` | `true` |
| `use_fallback` | `false` | `true` |

### 프론트엔드

1. **타입**: `DocumentSearchReq`에 `mode` 추가
2. **`handleDocumentSearch` 분리**:
   - `handleKeywordSearch(query, messageId)` — `mode: 'keyword'`, 문서 결과 즉시 렌더링
   - `handleHybridSearch(query, messageId)` — `mode: 'hybrid'`, 요약 로딩 스피너 표시 후 `search_summary`만 추출하여 머지
3. **로딩 상태**: `summaryLoading` reactive Map으로 hybrid 요청 로딩 관리
4. **지식정보 패널**: 기존 `search_summary` 영역에 로딩 스피너 조건 추가

### 데이터 흐름

```
고객 발화 수신
  ├── keyword 요청 (빠름) → 문서 목록 렌더링 + 요약 영역 스피너
  └── hybrid 요청 (느림)  → search_summary 머지 + 스피너 해제
```
