# 두 번의 쿼리로 분리한 이유 분석

## 데이터 모델 구조

### 1. 문서 버전 관리 시스템

```
DocumentsModel (문서 메타데이터)
├── id: document_abc
├── created_at: 2024-01-01
├── updated_at: 2024-01-15
├── current_contents_id: contents_003  ← 현재 버전
└── effective_contents_id: contents_002  ← 승인된 버전

DocumentsContentModel (문서 컨텐츠 버전들)
├── id: contents_001, document_id: document_abc, version_name: "1.0.0"
├── id: contents_002, document_id: document_abc, version_name: "1.1.0"  ← 승인됨
└── id: contents_003, document_id: document_abc, version_name: "1.2.0"  ← 현재 작업 중
```

**핵심**: 하나의 문서(DocumentsModel)는 여러 버전의 컨텐츠(DocumentsContentModel)를 가질 수 있습니다.

## 두 번의 쿼리로 분리한 이유

### 1. **정렬 기준과 필터링 기준이 다른 테이블에 있음**

```python
# 정렬 기준: DocumentsModel에 있음
- created_at (문서 생성일)
- updated_at (문서 수정일)
- hit_count (조회수 - 하지만 서브쿼리 필요)

# 필터링 기준: DocumentsContentModel에 있음
- store_id (저장소)
- keywords (키워드 배열)
- categories (카테고리 배열)
- name (제목)
- is_temporary (임시 문서 여부)
- effective_date, approved_date (승인 관련)
```

### 2. **문서 레벨 정렬 vs 컨텐츠 레벨 필터링**

```python
# 첫 번째 쿼리: 문서 레벨에서 정렬
query = self.db.query(DocumentsModel)
query = query.filter(DocumentsModel.current_contents_id != None)
query = query.order_by(DocumentsModel.created_at.desc())  # 문서 생성일 기준 정렬
query = query.all()  # 모든 문서를 가져옴

# 두 번째 쿼리: 컨텐츠 레벨에서 필터링
pairs_set = set((d.id, d.current_contents_id) for d in query)
content = self.doc_contents_service.get_filtered_documents_contents(
    document_pairs=pairs_set,
    store_ids=store_ids,      # 컨텐츠 레벨 필터
    keywords=keywords,         # 컨텐츠 레벨 필터
    categories=categories,     # 컨텐츠 레벨 필터
    ...
)
```

### 3. **정렬 순서 유지**

```python
# 272번 라인: 첫 번째 쿼리의 정렬 순서를 유지하기 위해
query_ids = [q.id for q in query]  # 정렬된 문서 ID 순서
content_map = {c["document_id"]: c for c in content}  # 필터링된 컨텐츠를 딕셔너리로
ordered_content = [content_map[qid] for qid in query_ids if qid in content_map]
# ↑ 첫 번째 쿼리의 정렬 순서대로 재배열
```

## 설계 의도 (추정)

### 의도 1: 문서 생성일/수정일 기준 정렬

- 사용자가 "최근에 생성된 문서" 또는 "최근에 수정된 문서"를 보고 싶어함
- 문서 레벨의 `created_at`, `updated_at`으로 정렬하는 것이 논리적으로 맞음

### 의도 2: 버전 관리 시스템

- 하나의 문서는 여러 버전을 가질 수 있음
- `current_contents_id` 또는 `effective_contents_id`로 특정 버전을 지정
- 정렬은 문서 레벨에서, 필터링은 컨텐츠 레벨에서 수행

### 의도 3: 복잡한 필터링 조건 처리

- 필터링 조건이 많고 복잡함 (keywords 배열, categories 배열, LIKE 검색 등)
- 컨텐츠 레벨에서 필터링한 후, 문서 레벨 정렬 순서를 유지

## 현재 방식의 문제점

### 1. **성능 이슈**

```python
# 첫 번째 쿼리: LIMIT 없이 모든 문서를 가져옴
query = query.all()  # 모든 문서를 메모리로 로드

# 두 번째 쿼리: 필터링
content = self.doc_contents_service.get_filtered_documents_contents(...)

# Python에서 정렬 순서 유지 및 페이지네이션
ordered_content = [content_map[qid] for qid in query_ids if qid in content_map]
paged_documents = filled_documents[start:end]  # 메모리에서 슬라이싱
```

**문제**:

- 대량의 문서가 있을 경우 모든 문서를 메모리로 로드
- 필터링 후 실제로는 20개만 필요하지만, 전체를 처리함
- 메모리 사용량 증가 및 성능 저하

### 2. **논리적 문제**

```python
# 정렬 후 필터링이 아니라, 필터링 후 정렬이 되어야 함
# 예: "키워드 'AI'가 포함된 문서 중 최신순"
# 현재: 모든 문서를 최신순으로 정렬 → 키워드 필터링
# 기대: 키워드 필터링 → 최신순 정렬
```

### 3. **total 카운트 부정확**

```python
# 168번 라인
total = len(filled_documents)  # 필터링된 전체 문서 수
# 하지만 첫 번째 쿼리에서 모든 문서를 가져왔으므로,
# 실제로는 필터링 전 문서 수를 기준으로 정렬됨
```

## 개선 방안

### 방안 1: JOIN을 사용한 단일 쿼리

```sql
SELECT
    d.id,
    d.created_at,
    dc.*
FROM aicm.aicm_documents d
INNER JOIN aicm.aicm_documents_contents dc
    ON d.id = dc.document_id
    AND (d.current_contents_id = dc.id OR d.effective_contents_id = dc.id)
WHERE dc.workspace_id = ?
  AND dc.store_id IN (...)
  AND dc.keywords && ARRAY[...]
  -- ... 필터링 조건
ORDER BY d.created_at DESC  -- 정렬
LIMIT 20 OFFSET 0;  -- 페이지네이션
```

**장점**:

- DB에서 필터링 → 정렬 → 페이지네이션까지 처리
- 메모리 사용량 최소화
- 성능 향상

**단점**:

- JOIN으로 인한 쿼리 복잡도 증가
- 인덱스 설계가 더 중요해짐

### 방안 2: 서브쿼리 사용

```sql
SELECT
    d.id,
    d.created_at,
    dc.*
FROM aicm.aicm_documents d
INNER JOIN aicm.aicm_documents_contents dc
    ON d.id = dc.document_id
    AND dc.id = COALESCE(d.current_contents_id, d.effective_contents_id)
WHERE dc.workspace_id = ?
  AND dc.id IN (
      SELECT id FROM aicm.aicm_documents_contents
      WHERE workspace_id = ?
        AND store_id IN (...)
        AND keywords && ARRAY[...]
        -- ... 필터링 조건
  )
ORDER BY d.created_at DESC
LIMIT 20 OFFSET 0;
```

### 방안 3: 현재 방식 개선 (하이브리드)

```python
# 첫 번째 쿼리에 LIMIT 추가
query = query.order_by(DocumentsModel.created_at.desc())
query = query.limit(limit * 2)  # 여유있게 가져옴 (필터링 후 부족할 수 있음)
query = query.all()

# 두 번째 쿼리에서 필터링
content = self.doc_contents_service.get_filtered_documents_contents(...)

# 필터링된 결과가 limit보다 적으면 추가 쿼리
if len(ordered_content) < limit:
    # 추가 문서 가져오기
    ...
```

## 결론

### 현재 방식의 의도

1. **문서 레벨 정렬**: 문서 생성일/수정일 기준 정렬
2. **컨텐츠 레벨 필터링**: 복잡한 필터링 조건 처리
3. **버전 관리**: current_contents_id 또는 effective_contents_id로 특정 버전 지정

### 문제점

1. **성능**: 모든 문서를 메모리로 로드
2. **확장성**: 대량 데이터 처리 시 문제 발생
3. **논리적 순서**: 필터링 후 정렬이 아니라 정렬 후 필터링

### 권장 개선

- **JOIN을 사용한 단일 쿼리**로 변경
- DB에서 필터링 → 정렬 → 페이지네이션까지 처리
- 인덱스 최적화 필수
