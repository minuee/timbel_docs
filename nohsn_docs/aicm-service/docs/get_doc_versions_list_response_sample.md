# `/api/docs/get_doc_versions_list` 응답 샘플

## 엔드포인트 정보

**URL:** `GET /api/docs/get_doc_versions_list`

**쿼리 파라미터:**

- `workspace_id` (필수): 워크스페이스 ID
- `document_id` (필수): 문서 ID

## 응답 구조

응답은 해당 문서의 모든 버전(version) 목록을 배열로 반환합니다. 각 버전은 `fill_detail_dict` 메서드를 통해 생성된 상세 정보를 포함합니다.

## 응답 샘플

```json
[
  {
    "id": "encrypted_document_id_123",
    "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
    "version_name": "v1.2",
    "name": "문서 제목",
    "summary": "문서 요약 내용",
    "ai_summary": "AI가 생성한 문서 요약",
    "keywords": ["키워드1", "키워드2", "키워드3"],
    "categories": [
      {
        "id": "encrypted_category_id_1",
        "category_name": ["카테고리1", "하위카테고리1"]
      },
      {
        "id": "encrypted_category_id_2",
        "category_name": ["카테고리2"]
      }
    ],
    "attachments": ["encrypted_attachment_id_1", "encrypted_attachment_id_2"],
    "sources": ["encrypted_source_id_1", "https://example.com/reference"],
    "store_id": "encrypted_store_id_123",
    "creator_id": "user_123",
    "editor_id": "user_456",
    "manager_id": "user_789",
    "meta": {
      "custom_field1": "value1",
      "custom_field2": "value2"
    },
    "is_temporary": false,
    "approved_date": "2024-01-15T10:30:00Z",
    "effective_date": "2024-01-20T00:00:00Z",
    "expire_date": "2025-01-20T00:00:00Z",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-20T15:45:00Z",
    "hit_count": 42,
    "comment_count": 5,
    "doc_type": {
      "id": "doc_type_id_1",
      "name": "문서 타입명",
      "description": "문서 타입 설명"
    },
    "contents": {
      "outline": [
        {
          "title": "1장. 개요",
          "blocks": ["encrypted_section_id_1", "encrypted_section_id_2"],
          "children": [
            {
              "title": "1.1 소개",
              "blocks": ["encrypted_section_id_3"],
              "children": []
            }
          ]
        },
        {
          "title": "2장. 본문",
          "blocks": ["encrypted_section_id_4"],
          "children": []
        }
      ]
    },
    "blocks_map": [
      {
        "id": "encrypted_section_id_1",
        "content": "<p>첫 번째 섹션의 HTML 내용입니다.</p>",
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-01-15T10:30:00Z",
        "hit_count": 10
      },
      {
        "id": "encrypted_section_id_2",
        "content": "<p>두 번째 섹션의 HTML 내용입니다.</p>",
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-01-15T10:30:00Z",
        "hit_count": 5
      },
      {
        "id": "encrypted_section_id_3",
        "content": "<p>1.1 소개 섹션의 HTML 내용입니다.</p>",
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-01-15T10:30:00Z",
        "hit_count": 3
      },
      {
        "id": "encrypted_section_id_4",
        "content": "<p>본문 섹션의 HTML 내용입니다.</p>",
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-01-15T10:30:00Z",
        "hit_count": 8
      }
    ],
    "attachments_map": [
      {
        "id": "attachment_id_1",
        "name": "첨부파일1.pdf",
        "path": "aicm/docs/document_id/attachment_1.pdf",
        "size": 1024000,
        "content_type": "application/pdf",
        "created_at": "2024-01-15T10:30:00Z"
      },
      {
        "id": "attachment_id_2",
        "name": "이미지.png",
        "path": "aicm/docs/document_id/image.png",
        "size": 512000,
        "content_type": "image/png",
        "created_at": "2024-01-15T10:30:00Z"
      }
    ]
  },
  {
    "id": "encrypted_document_id_123",
    "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
    "version_name": "v1.1",
    "name": "문서 제목 (이전 버전)",
    "summary": "이전 버전의 문서 요약",
    "ai_summary": null,
    "keywords": ["키워드1", "키워드2"],
    "categories": [
      {
        "id": "encrypted_category_id_1",
        "category_name": ["카테고리1"]
      }
    ],
    "attachments": ["encrypted_attachment_id_1"],
    "sources": [],
    "store_id": "encrypted_store_id_123",
    "creator_id": "user_123",
    "editor_id": null,
    "manager_id": null,
    "meta": {},
    "is_temporary": false,
    "approved_date": null,
    "effective_date": null,
    "expire_date": null,
    "created_at": "2024-01-10T09:00:00Z",
    "updated_at": "2024-01-10T09:00:00Z",
    "hit_count": 15,
    "comment_count": 5,
    "doc_type": {
      "id": "doc_type_id_1",
      "name": "문서 타입명",
      "description": "문서 타입 설명"
    },
    "contents": {
      "outline": [
        {
          "title": "1장. 개요",
          "blocks": ["encrypted_section_id_1"],
          "children": []
        }
      ]
    },
    "blocks_map": [
      {
        "id": "encrypted_section_id_1",
        "content": "<p>이전 버전의 첫 번째 섹션 내용입니다.</p>",
        "created_at": "2024-01-10T09:00:00Z",
        "updated_at": "2024-01-10T09:00:00Z",
        "hit_count": 8
      }
    ],
    "attachments_map": [
      {
        "id": "attachment_id_1",
        "name": "첨부파일1.pdf",
        "path": "aicm/docs/document_id/attachment_1.pdf",
        "size": 1024000,
        "content_type": "application/pdf",
        "created_at": "2024-01-10T09:00:00Z"
      }
    ]
  },
  {
    "id": "encrypted_document_id_123",
    "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
    "version_name": "v1.0",
    "name": "문서 제목 (초기 버전)",
    "summary": null,
    "ai_summary": null,
    "keywords": [],
    "categories": [],
    "attachments": [],
    "sources": [],
    "store_id": "encrypted_store_id_123",
    "creator_id": "user_123",
    "editor_id": null,
    "manager_id": null,
    "meta": {},
    "is_temporary": true,
    "approved_date": null,
    "effective_date": null,
    "expire_date": null,
    "created_at": "2024-01-05T08:00:00Z",
    "updated_at": "2024-01-05T08:00:00Z",
    "hit_count": 0,
    "comment_count": 5,
    "doc_type": null,
    "contents": {
      "outline": []
    },
    "blocks_map": [],
    "attachments_map": []
  }
]
```

## 필드 설명

### 공통 필드

| 필드명            | 타입           | 설명                                                      |
| ----------------- | -------------- | --------------------------------------------------------- |
| `id`              | string         | 암호화된 문서 ID (모든 버전에서 동일)                     |
| `workspace_id`    | string         | 워크스페이스 ID                                           |
| `version_name`    | string         | 버전명 (예: "v1.0", "v1.1", "v1.2")                       |
| `name`            | string         | 문서 제목                                                 |
| `summary`         | string \| null | 문서 요약                                                 |
| `ai_summary`      | string \| null | AI가 생성한 문서 요약                                     |
| `keywords`        | array[string]  | 키워드 목록                                               |
| `categories`      | array[object]  | 카테고리 목록 (각 카테고리는 `id`와 `category_name` 포함) |
| `attachments`     | array[string]  | 첨부파일 ID 목록 (암호화됨)                               |
| `sources`         | array[string]  | 출처 목록 (ID 또는 URL)                                   |
| `store_id`        | string         | 저장소 ID (암호화됨)                                      |
| `creator_id`      | string         | 생성자 ID                                                 |
| `editor_id`       | string \| null | 편집자 ID                                                 |
| `manager_id`      | string \| null | 관리자 ID                                                 |
| `meta`            | object         | 문서 메타데이터 (사용자 정의 필드)                        |
| `is_temporary`    | boolean        | 임시 문서 여부                                            |
| `approved_date`   | string \| null | 승인 일시 (ISO 8601 형식)                                 |
| `effective_date`  | string \| null | 유효 시작일 (ISO 8601 형식)                               |
| `expire_date`     | string \| null | 유효 종료일 (ISO 8601 형식)                               |
| `created_at`      | string         | 생성 일시 (ISO 8601 형식)                                 |
| `updated_at`      | string         | 수정 일시 (ISO 8601 형식)                                 |
| `hit_count`       | integer        | 조회수                                                    |
| `comment_count`   | integer        | 댓글 개수                                                 |
| `doc_type`        | object \| null | 문서 타입 정보                                            |
| `contents`        | object         | 문서 내용 구조 (`outline` 포함)                           |
| `blocks_map`      | array[object]  | 섹션(블록) 목록                                           |
| `attachments_map` | array[object]  | 첨부파일 상세 정보 목록                                   |

### `contents.outline` 구조

문서의 목차 구조를 나타내는 트리 형태의 배열입니다.

```json
{
  "title": "섹션 제목",
  "blocks": ["section_id_1", "section_id_2"],
  "children": [
    {
      "title": "하위 섹션 제목",
      "blocks": ["section_id_3"],
      "children": []
    }
  ]
}
```

### `blocks_map` 항목 구조

각 섹션(블록)의 상세 정보입니다.

```json
{
  "id": "encrypted_section_id",
  "content": "<p>HTML 형식의 섹션 내용</p>",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "hit_count": 10
}
```

### `attachments_map` 항목 구조

첨부파일의 상세 정보입니다.

```json
{
  "id": "attachment_id",
  "name": "파일명.pdf",
  "path": "aicm/docs/document_id/file.pdf",
  "size": 1024000,
  "content_type": "application/pdf",
  "created_at": "2024-01-15T10:30:00Z"
}
```

## 정렬 순서

버전 목록은 `created_at` 기준 내림차순(최신 버전이 먼저)으로 정렬됩니다.

## 주의사항

1. **동일한 문서 ID**: 모든 버전은 동일한 `id` (문서 ID)를 가지지만, `version_name`으로 구분됩니다.
2. **버전별 차이**: 각 버전은 생성 시점의 문서 내용을 그대로 보존합니다.
3. **댓글 개수**: `comment_count`는 문서 전체의 댓글 개수이며, 버전별로 다르지 않습니다 (문서 ID 기준).
4. **빈 배열**: 문서에 버전이 없는 경우 빈 배열 `[]`을 반환합니다.

## 에러 응답

### 문서가 존재하지 않는 경우

```json
{
  "detail": "해당 document_id에 대한 문서가 존재하지 않습니다."
}
```

HTTP 상태 코드: `404 Not Found`
