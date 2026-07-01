# add_doc_with_files API 가이드

## 개요

`add_doc_with_files` API는 문서와 첨부 파일을 함께 생성할 수 있는 기능을 제공합니다. 이 API는 `multipart/form-data` 형식을 사용하여 파일 업로드를 지원합니다.

## 엔드포인트

**엔드포인트:** `POST /api/docs/add_doc_with_files`

**Content-Type:** `multipart/form-data`

## 요청 헤더

```
X-auth-token: {인증 토큰}
Content-Type: multipart/form-data
```

## 요청 파라미터

### Form 필드

| 필드명 | 타입 | 필수 | 설명 | 예시 |
|--------|------|------|------|------|
| `workspace_id` | string | ✅ | 워크스페이스 ID | `"0198d0e1-c214-71ae-8b84-b0e282f6c394"` |
| `name` | string | ✅ | 문서 이름 | `"문서 제목"` |
| `contents` | string (JSON) | ✅ | 문서 내용 (JSON 문자열) | `"{\"sections\": [...]}"` |
| `summary` | string | ❌ | 문서 요약 | `"문서 요약 내용"` |
| `ai_summary` | string | ❌ | AI 생성 문서 요약 | `"AI 요약 내용"` |
| `keywords` | string (JSON) | ❌ | 키워드 리스트 (JSON 문자열) | `"[\"키워드1\", \"키워드2\"]"` |
| `categories` | string (JSON) | ✅ | 카테고리 리스트 (JSON 문자열) | `"[\"cat_123\", \"cat_456\"]"` |
| `sources` | string (JSON) | ❌ | 출처 리스트 (JSON 문자열) | `"[\"doc_123\", \"https://example.com\"]"` |
| `store_id` | string | ✅ | 저장소 ID | `"store_1234567890"` |
| `creator_id` | string | ✅ | 작성자 ID | `"user_1234567890"` |
| `meta` | string (JSON) | ✅ | 문서 메타데이터 (JSON 문자열) | `"{\"author\": \"홍길동\"}"` |
| `doc_type` | string (JSON) | ❌ | 문서 타입 ID (JSON 문자열) | `"\"doc_type_123\""` |
| `is_temporary` | string | ✅ | 임시저장 여부 (`"true"` 또는 `"false"`) | `"false"` |
| `attachments` | string (JSON) | ❌ | 첨부 파일 메타데이터 (JSON 문자열) | `"[{\"filename\": \"file.pdf\"}]"` |
| `attachment_files` | File[] | ❌ | 첨부 파일 (다중 파일 업로드 가능) | - |

### JSON 필드 상세 설명

#### `contents` (필수)
문서의 구조화된 내용을 JSON 객체로 전달합니다.

```json
{
  "sections": [
    {
      "id": "section_1",
      "title": "섹션 제목",
      "content": "섹션 내용"
    }
  ]
}
```

#### `keywords` (선택)
문서와 관련된 키워드 배열입니다.

```json
["키워드1", "키워드2", "키워드3"]
```

#### `categories` (필수)
문서가 속한 카테고리 ID 배열입니다.

```json
["category_id_1", "category_id_2"]
```

#### `sources` (선택)
문서의 출처 정보 배열입니다. 문서 ID나 URL을 포함할 수 있습니다.

```json
["doc_1234567890", "https://example.com/reference"]
```

#### `meta` (필수)
문서의 추가 메타데이터를 담는 JSON 객체입니다.

```json
{
  "author": "홍길동",
  "department": "개발팀",
  "version": "1.0"
}
```

#### `attachments` (선택)
첨부 파일의 메타데이터 배열입니다. `attachment_files`와 함께 사용됩니다.

```json
[
  {
    "filename": "document.pdf",
    "description": "참고 문서"
  }
]
```

#### `doc_type` (선택)
문서 타입 ID를 문자열로 전달합니다.

```json
"doc_type_1234567890"
```

## 요청 예시

### cURL 예시

```bash
curl -X POST "http://localhost:8000/api/docs/add_doc_with_files" \
  -H "X-auth-token: your_token_here" \
  -F "workspace_id=0198d0e1-c214-71ae-8b84-b0e282f6c394" \
  -F "name=새로운 문서" \
  -F "contents={\"sections\":[{\"id\":\"section_1\",\"title\":\"제목\",\"content\":\"내용\"}]}" \
  -F "summary=문서 요약 내용" \
  -F "keywords=[\"키워드1\",\"키워드2\"]" \
  -F "categories=[\"cat_123\",\"cat_456\"]" \
  -F "store_id=store_1234567890" \
  -F "creator_id=user_1234567890" \
  -F "meta={\"author\":\"홍길동\"}" \
  -F "is_temporary=false" \
  -F "attachment_files=@/path/to/file1.pdf" \
  -F "attachment_files=@/path/to/file2.docx"
```

### JavaScript (FormData) 예시

```javascript
const formData = new FormData();

// 기본 필드
formData.append('workspace_id', '0198d0e1-c214-71ae-8b84-b0e282f6c394');
formData.append('name', '새로운 문서');
formData.append('contents', JSON.stringify({
  sections: [
    {
      id: 'section_1',
      title: '제목',
      content: '내용'
    }
  ]
}));
formData.append('summary', '문서 요약 내용');
formData.append('keywords', JSON.stringify(['키워드1', '키워드2']));
formData.append('categories', JSON.stringify(['cat_123', 'cat_456']));
formData.append('store_id', 'store_1234567890');
formData.append('creator_id', 'user_1234567890');
formData.append('meta', JSON.stringify({
  author: '홍길동',
  department: '개발팀'
}));
formData.append('is_temporary', 'false');

// 파일 첨부
const fileInput = document.querySelector('input[type="file"]');
if (fileInput.files.length > 0) {
  for (let i = 0; i < fileInput.files.length; i++) {
    formData.append('attachment_files', fileInput.files[i]);
  }
}

const response = await fetch('http://localhost:8000/api/docs/add_doc_with_files', {
  method: 'POST',
  headers: {
    'X-auth-token': 'your_token_here'
  },
  body: formData
});

const data = await response.json();
console.log(data);
```

### Python (requests) 예시

```python
import requests
import json

url = "http://localhost:8000/api/docs/add_doc_with_files"
headers = {
    "X-auth-token": "your_token_here"
}

# Form 데이터 준비
data = {
    "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
    "name": "새로운 문서",
    "contents": json.dumps({
        "sections": [
            {
                "id": "section_1",
                "title": "제목",
                "content": "내용"
            }
        ]
    }),
    "summary": "문서 요약 내용",
    "keywords": json.dumps(["키워드1", "키워드2"]),
    "categories": json.dumps(["cat_123", "cat_456"]),
    "store_id": "store_1234567890",
    "creator_id": "user_1234567890",
    "meta": json.dumps({
        "author": "홍길동",
        "department": "개발팀"
    }),
    "is_temporary": "false"
}

# 파일 첨부
files = [
    ("attachment_files", ("file1.pdf", open("/path/to/file1.pdf", "rb"), "application/pdf")),
    ("attachment_files", ("file2.docx", open("/path/to/file2.docx", "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
]

response = requests.post(url, headers=headers, data=data, files=files)
result = response.json()
print(result)
```

## 응답 예시

### 성공 응답 (200 OK)

```json
{
  "id": "document_abc123def456",
  "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
  "name": "새로운 문서",
  "contents": {
    "sections": [
      {
        "id": "section_1",
        "title": "제목",
        "content": "내용"
      }
    ]
  },
  "summary": "문서 요약 내용",
  "keywords": ["키워드1", "키워드2"],
  "categories": ["cat_123", "cat_456"],
  "store_id": "store_1234567890",
  "creator_id": "user_1234567890",
  "meta": {
    "author": "홍길동",
    "department": "개발팀"
  },
  "is_temporary": false,
  "attachments": [
    {
      "id": "attachment_123",
      "filename": "file1.pdf",
      "url": "https://minio.example.com/bucket/file1.pdf"
    }
  ],
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

### 에러 응답

#### 400 Bad Request
필수 필드 누락 또는 잘못된 데이터 형식

```json
{
  "detail": {
    "error": "bad_request",
    "message": "필수 필드가 누락되었습니다."
  }
}
```

#### 401 Unauthorized
인증 토큰 없음 또는 유효하지 않음

```json
{
  "detail": "인증 토큰이 필요합니다."
}
```

#### 409 Conflict
이미 같은 이름의 문서가 존재함

```json
{
  "detail": {
    "error": "이미 같은 이름의 문서가 존재합니다.",
    "message": "Document with name '새로운 문서' already exists"
  }
}
```

## 처리 흐름

1. **워크스페이스 검증**: `workspace_id`가 유효한지 확인합니다.
2. **인증 토큰 검증**: `X-auth-token` 헤더에서 토큰을 추출하여 검증합니다.
3. **파일 처리**: `attachment_files`로 전달된 파일들을 읽어 메모리에 저장합니다.
4. **JSON 파싱**: JSON 문자열로 전달된 필드들(`contents`, `keywords`, `categories` 등)을 파싱합니다.
5. **문서 생성**: `DocumentCreate` 스키마로 변환하여 데이터베이스에 문서를 생성합니다.
6. **파일 업로드**: 첨부 파일은 MinIO에 비동기로 업로드됩니다 (Celery 태스크).
7. **검색 엔진 인덱싱**: 생성된 문서는 검색 엔진에 인덱싱됩니다.
8. **응답 반환**: 생성된 문서 정보를 반환합니다.

## 주의사항

1. **인증**: 모든 API 요청에는 `X-auth-token` 헤더가 필요합니다.
2. **워크스페이스 검증**: 모든 요청은 유효한 `workspace_id`를 포함해야 합니다.
3. **JSON 문자열**: `contents`, `keywords`, `categories`, `sources`, `meta`, `attachments`, `doc_type` 필드는 JSON 문자열로 전달해야 합니다.
4. **is_temporary**: `"true"` 또는 `"false"` 문자열로 전달해야 합니다 (대소문자 구분).
5. **파일 업로드**: `attachment_files`는 다중 파일 업로드를 지원합니다. 각 파일은 별도의 `attachment_files` 필드로 전달합니다.
6. **파일 크기 제한**: 서버 설정에 따라 파일 크기 제한이 있을 수 있습니다.
7. **비동기 처리**: 첨부 파일 업로드는 Celery를 통해 비동기로 처리됩니다.
8. **검색 엔진**: 문서 생성 후 자동으로 검색 엔진에 인덱싱됩니다 (`approved='production'`).

## 관련 파일

- 엔드포인트: `api/endpoints/documents/documents_endpoint.py`
- 서비스: `services/document_service.py`
- DB 서비스: `db/services/document/document_service.py`
- 스키마: `api/schemas/document_schemas.py` (DocumentCreate)
- 모델: `db/models/document/documents_model.py`



