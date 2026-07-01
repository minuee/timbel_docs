# `/api/search/retrieve_doc` Filter 사용 가이드

## 개요

`/api/search/retrieve_doc` 엔드포인트는 문서 검색 시 `filters` 파라미터를 통해 Elasticsearch 쿼리에 필터 조건을 추가할 수 있습니다.

## Filter 구조

```json
{
  "text": "검색어",
  "workspace_id": "workspace_id",
  "task_id": "task_id",
  "top_k": 10,
  "filters": {
    "필드명": "값 또는 배열"
  }
}
```

## Filter 처리 방식

### 1. 단일 값 필터 (term 쿼리)

값이 단일 값(문자열, 숫자, 불린 등)인 경우, Elasticsearch의 `term` 쿼리로 변환됩니다.

```json
{
  "filters": {
    "approved": "production",
    "store_id": "store_123"
  }
}
```

**변환된 쿼리:**

```json
{
  "bool": {
    "filter": [
      { "term": { "approved": "production" } },
      { "term": { "store_id": "store_123" } }
    ]
  }
}
```

### 2. 다중 값 필터 (terms 쿼리)

값이 배열인 경우, Elasticsearch의 `terms` 쿼리로 변환되어 배열 내의 값 중 하나라도 일치하면 됩니다.

```json
{
  "filters": {
    "document_id": ["doc_1", "doc_2", "doc_3"],
    "categories": ["카테고리1", "카테고리2"]
  }
}
```

**변환된 쿼리:**

```json
{
  "bool": {
    "filter": [
      { "terms": { "document_id": ["doc_1", "doc_2", "doc_3"] } },
      { "terms": { "categories": ["카테고리1", "카테고리2"] } }
    ]
  }
}
```

## 사용 가능한 필드

Elasticsearch 인덱스에 저장된 다음 필드들을 filter로 사용할 수 있습니다:

| 필드명           | 타입         | 설명            | 예시                                        |
| ---------------- | ------------ | --------------- | ------------------------------------------- |
| `workspace_id`   | keyword      | 워크스페이스 ID | `"workspace_123"`                           |
| `document_id`    | keyword      | 문서 ID         | `"doc_123"` 또는 `["doc_1", "doc_2"]`       |
| `document_name`  | text/keyword | 문서 이름       | `"문서명"`                                  |
| `store_id`       | keyword      | 저장소 ID       | `"store_123"` 또는 `["store_1", "store_2"]` |
| `version_name`   | keyword      | 버전명          | `"v1.0"`                                    |
| `creator_id`     | keyword      | 생성자 ID       | `"user_123"`                                |
| `editor_id`      | keyword      | 편집자 ID       | `"user_456"`                                |
| `section_id`     | keyword      | 섹션 ID         | `"sect_123"`                                |
| `section_path`   | keyword      | 섹션 경로       | `["개요", "인삿말"]`                        |
| `approved`       | keyword      | 승인 상태       | `"production"`, `"archived"`, `"draft"`     |
| `categories`     | keyword      | 문서 분류       | `["카테고리1", "카테고리2"]`                |
| `keywords`       | keyword      | 키워드          | `["키워드1", "키워드2"]`                    |
| `created_at`     | date         | 생성일시        | ISO 8601 형식                               |
| `updated_at`     | date         | 수정일시        | ISO 8601 형식                               |
| `effective_date` | date         | 유효 시작일     | ISO 8601 형식                               |
| `expire_date`    | date         | 유효 종료일     | ISO 8601 형식                               |

## 특별한 경우: approved="production" 필터

`approved` 필드가 `["production"]`으로 설정된 경우, 시스템이 자동으로 유효기간 필터를 추가합니다:

- `effective_date < now/d` (유효 시작일이 오늘 이전)
- `expire_date >= now/d` 또는 `expire_date`가 없는 경우

이를 통해 현재 유효한 프로덕션 문서만 검색됩니다.

## 사용 예시

### 예시 1: 특정 저장소의 프로덕션 문서만 검색

```json
{
  "text": "검색어",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 10,
  "filters": {
    "store_id": "store_123",
    "approved": "production"
  }
}
```

### 예시 2: 여러 문서 ID로 필터링

```json
{
  "text": "검색어",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 5,
  "filters": {
    "document_id": ["doc_1", "doc_2", "doc_3"]
  }
}
```

### 예시 3: 카테고리와 키워드로 필터링

```json
{
  "text": "검색어",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 20,
  "filters": {
    "categories": ["기술문서", "매뉴얼"],
    "keywords": ["API", "가이드"]
  }
}
```

### 예시 4: 특정 생성자의 문서만 검색

```json
{
  "text": "검색어",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 10,
  "filters": {
    "creator_id": "user_123",
    "approved": "production"
  }
}
```

### 예시 5: 여러 조건 조합

```json
{
  "text": "검색어",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 15,
  "filters": {
    "store_id": ["store_1", "store_2"],
    "categories": ["카테고리1"],
    "approved": "production"
  }
}
```

## 구현 코드 참고

Filter는 `services/es_service.py`의 `retrieve_docs_core` 메서드에서 처리됩니다:

```121:127:services/es_service.py
        filter = []
        if filters:
            for key, value in filters.items():
                if isinstance(value, list):
                    filter.append({"terms": {key: value}})
                else:
                    filter.append({"term": {key: value}})
```

## 고급 필터: Range 쿼리 (작성일 범위)

작성일 범위로 필터링하려면 `filters`에 특별한 형식으로 `range` 쿼리를 지정할 수 있습니다.

### 작성일 범위 필터 형식

```json
{
  "filters": {
    "created_at": {
      "gte": "2024-01-01",
      "lte": "2024-12-31"
    }
  }
}
```

**지원되는 range 연산자:**

- `gte`: 이상 (greater than or equal)
- `gt`: 초과 (greater than)
- `lte`: 이하 (less than or equal)
- `lt`: 미만 (less than)

### 작성일 범위 예시

```json
{
  "text": "검색어",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 10,
  "filters": {
    "created_at": {
      "gte": "2024-01-01",
      "lte": "2024-12-31"
    }
  }
}
```

**변환된 쿼리:**

```json
{
  "bool": {
    "filter": [
      {
        "range": {
          "created_at": {
            "gte": "2024-01-01",
            "lte": "2024-12-31"
          }
        }
      }
    ]
  }
}
```

## 검색 필드 선택 (제목, 내용, 제목 또는 내용)

현재 시스템은 기본적으로 `document_name`, `title`, `content`, `keywords` 필드에서 검색합니다.

검색 범위를 제한하려면 `filters`에 특별한 키 `_search_fields`를 사용할 수 있습니다:

### 검색 필드 선택 형식

```json
{
  "filters": {
    "_search_fields": ["title"] // 제목만 검색
  }
}
```

**지원되는 값:**

- `["title"]`: 제목만 검색
- `["content"]`: 내용만 검색
- `["title", "content"]`: 제목 또는 내용 검색 (기본 동작과 동일)

### 검색 필드 선택 예시

#### 예시 1: 제목만 검색

```json
{
  "text": "API 가이드",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 10,
  "filters": {
    "_search_fields": ["title"]
  }
}
```

#### 예시 2: 내용만 검색

```json
{
  "text": "사용 방법",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 10,
  "filters": {
    "_search_fields": ["content"]
  }
}
```

#### 예시 3: 제목 또는 내용 검색

```json
{
  "text": "검색어",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 10,
  "filters": {
    "_search_fields": ["title", "content"]
  }
}
```

## 클라이언트 검색 조건 구현 예시

클라이언트에서 다음 검색 조건을 입력받는 경우:

1. **검색어**: `text` 파라미터 사용
2. **검색 범위** (제목/내용/제목 또는 내용): `filters._search_fields` 사용
3. **작성일 범위**: `filters.created_at` range 쿼리 사용

### 통합 예시

```json
{
  "text": "API 문서",
  "workspace_id": "workspace_123",
  "task_id": "task_456",
  "top_k": 20,
  "filters": {
    "_search_fields": ["title", "content"],
    "created_at": {
      "gte": "2024-01-01",
      "lte": "2024-12-31"
    },
    "approved": "production"
  }
}
```

이 요청은:

- "API 문서"를 제목 또는 내용에서 검색
- 2024년 1월 1일부터 12월 31일 사이에 작성된 문서만 필터링
- 프로덕션 승인된 문서만 검색

## 주의사항

1. **필드명 정확성**: 필드명은 Elasticsearch 인덱스에 실제로 존재하는 필드명을 사용해야 합니다.
2. **데이터 타입**: 필터 값의 타입은 인덱스의 필드 타입과 일치해야 합니다 (예: keyword 필드는 문자열, date 필드는 ISO 8601 형식).
3. **성능**: 다수의 filter를 사용할 경우 검색 성능에 영향을 줄 수 있습니다.
4. **workspace_id**: `workspace_id`는 필터에 포함하지 않아도 자동으로 쿼리에 추가됩니다.
5. **Range 쿼리**: `range` 쿼리는 날짜 필드(`created_at`, `updated_at`, `effective_date`, `expire_date`)에만 사용할 수 있습니다.
6. **검색 필드**: `_search_fields`는 특별한 예약 키워드로, 실제 Elasticsearch 필터가 아닌 검색 쿼리 구성에 사용됩니다.

## 관련 파일

- API 엔드포인트: `api/endpoints/documents/search_endpoints.py`
- 스키마 정의: `api/schemas/search_schemas.py`
- Elasticsearch 서비스: `services/es_service.py`
- 문서 변환: `services/es_action_transformer.py`
