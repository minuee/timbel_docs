# Document Comment API 가이드

## 개요

Document Comment API는 문서에 대한 댓글을 생성, 조회, 수정, 삭제할 수 있는 기능을 제공합니다.

## 데이터 모델

### DocumentCommentModel

문서 댓글 정보를 저장하는 모델입니다.

| 필드명           | 타입       | 필수 | 설명             | 기본값           |
| ---------------- | ---------- | ---- | ---------------- | ---------------- |
| `id`             | String(50) | ✅   | 댓글 고유 ID     | `comment_{uuid}` |
| `workspace_id`   | String     | ✅   | 워크스페이스 ID  | -                |
| `document_id`    | String(50) | ✅   | 문서 ID (외래키) | -                |
| `user_id`        | String(50) | ❌   | 사용자 ID        | `null`           |
| `is_anonymity`   | Boolean    | ❌   | 익명 여부        | `false`          |
| `is_declaration` | Boolean    | ❌   | 신고 여부        | `false`          |
| `comment`        | Text       | ❌   | 댓글 내용        | `null`           |
| `created_at`     | DateTime   | ✅   | 생성 일시        | 현재 시간        |
| `updated_at`     | DateTime   | ✅   | 수정 일시        | 현재 시간        |

### 관계

- `document`: `DocumentsModel`과 다대일 관계 (`document_id` 외래키)
  - 문서가 삭제되면 댓글도 함께 삭제됨 (CASCADE)

## API 엔드포인트

### 1. 댓글 생성

문서에 새로운 댓글을 생성합니다.

**엔드포인트:** `POST /api/docs/comments`

**요청 헤더:**

```
X-auth-token: {인증 토큰}
```

**요청 본문:**

```json
{
  "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
  "document_id": "doc_1234567890",
  "user_id": "user_1234567890",
  "comment": "이 문서에 대한 의견입니다.",
  "is_anonymity": false,
  "is_declaration": false
}
```

**요청 스키마:**

```typescript
{
  workspace_id: string;      // 필수: 워크스페이스 ID
  document_id: string;        // 필수: 문서 ID
  user_id?: string;           // 선택: 사용자 ID
  comment?: string;           // 선택: 댓글 내용
  is_anonymity?: boolean;     // 선택: 익명 여부 (기본값: false)
  is_declaration?: boolean;   // 선택: 신고 여부 (기본값: false)
}
```

**응답 예시:**

```json
{
  "id": "comment_abc123def456",
  "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
  "document_id": "doc_1234567890",
  "user_id": "user_1234567890",
  "is_anonymity": false,
  "is_declaration": false,
  "comment": "이 문서에 대한 의견입니다.",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**에러 응답:**

- `400 Bad Request`: 필수 필드 누락 또는 잘못된 데이터
- `401 Unauthorized`: 인증 토큰 없음 또는 유효하지 않음
- `404 Not Found`: 문서가 존재하지 않음

---

### 2. 댓글 목록 조회

특정 문서의 댓글 목록을 조회합니다.

**엔드포인트:** `GET /api/docs/comments`

**요청 헤더:**

```
X-auth-token: {인증 토큰}
```

**쿼리 파라미터:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `workspace_id` | string | ✅ | 워크스페이스 ID |
| `document_id` | string | ✅ | 문서 ID |
| `limit` | integer | ❌ | 페이지당 건수 (기본값: 20, 최대: 100) |
| `page` | integer | ❌ | 페이지 번호 (기본값: 1) |
| `sort_order` | string | ❌ | 정렬 방향 (`asc` 또는 `desc`, 기본값: `desc`) |

**요청 예시:**

```
GET /api/docs/comments?workspace_id=0198d0e1-c214-71ae-8b84-b0e282f6c394&document_id=doc_1234567890&limit=20&page=1&sort_order=desc
```

**응답 예시:**

```json
{
  "total": 15,
  "page": 1,
  "limit": 20,
  "comments": [
    {
      "id": "comment_abc123def456",
      "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
      "document_id": "doc_1234567890",
      "user_id": "user_1234567890",
      "is_anonymity": false,
      "is_declaration": false,
      "comment": "이 문서에 대한 의견입니다.",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    },
    {
      "id": "comment_xyz789ghi012",
      "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
      "document_id": "doc_1234567890",
      "user_id": null,
      "is_anonymity": true,
      "is_declaration": false,
      "comment": "익명 댓글입니다.",
      "created_at": "2024-01-15T09:15:00Z",
      "updated_at": "2024-01-15T09:15:00Z"
    }
  ]
}
```

**에러 응답:**

- `400 Bad Request`: 필수 파라미터 누락
- `401 Unauthorized`: 인증 토큰 없음 또는 유효하지 않음

---

### 3. 댓글 단건 조회

특정 댓글의 상세 정보를 조회합니다.

**엔드포인트:** `GET /api/docs/comments/{comment_id}`

**요청 헤더:**

```
X-auth-token: {인증 토큰}
```

**경로 파라미터:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `comment_id` | string | ✅ | 댓글 ID |

**쿼리 파라미터:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `workspace_id` | string | ✅ | 워크스페이스 ID |

**요청 예시:**

```
GET /api/docs/comments/comment_abc123def456?workspace_id=0198d0e1-c214-71ae-8b84-b0e282f6c394
```

**응답 예시:**

```json
{
  "id": "comment_abc123def456",
  "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
  "document_id": "doc_1234567890",
  "user_id": "user_1234567890",
  "is_anonymity": false,
  "is_declaration": false,
  "comment": "이 문서에 대한 의견입니다.",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**에러 응답:**

- `400 Bad Request`: 필수 파라미터 누락
- `401 Unauthorized`: 인증 토큰 없음 또는 유효하지 않음
- `404 Not Found`: 댓글이 존재하지 않음

---

### 4. 댓글 수정

기존 댓글의 내용을 수정합니다.

**엔드포인트:** `PATCH /api/docs/comments/{comment_id}`

**요청 헤더:**

```
X-auth-token: {인증 토큰}
```

**경로 파라미터:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `comment_id` | string | ✅ | 댓글 ID |

**요청 본문:**

```json
{
  "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
  "comment": "수정된 댓글 내용입니다.",
  "is_declaration": false
}
```

**요청 스키마:**

```typescript
{
  workspace_id: string;      // 필수: 워크스페이스 ID
  comment?: string;          // 선택: 댓글 내용
  is_declaration?: boolean;  // 선택: 신고 여부
}
```

**응답 예시:**

```json
{
  "id": "comment_abc123def456",
  "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
  "document_id": "doc_1234567890",
  "user_id": "user_1234567890",
  "is_anonymity": false,
  "is_declaration": false,
  "comment": "수정된 댓글 내용입니다.",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T11:45:00Z"
}
```

**에러 응답:**

- `400 Bad Request`: 필수 필드 누락 또는 잘못된 데이터
- `401 Unauthorized`: 인증 토큰 없음 또는 유효하지 않음
- `403 Forbidden`: 권한 없음 (본인의 댓글이 아님)
- `404 Not Found`: 댓글이 존재하지 않음

---

### 5. 댓글 삭제

댓글을 삭제합니다.

**엔드포인트:** `DELETE /api/docs/comments/{comment_id}`

**요청 헤더:**

```
X-auth-token: {인증 토큰}
```

**경로 파라미터:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `comment_id` | string | ✅ | 댓글 ID |

**쿼리 파라미터:**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `workspace_id` | string | ✅ | 워크스페이스 ID |

**요청 예시:**

```
DELETE /api/docs/comments/comment_abc123def456?workspace_id=0198d0e1-c214-71ae-8b84-b0e282f6c394
```

**응답 예시:**

```json
{
  "message": "댓글이 삭제되었습니다.",
  "comment_id": "comment_abc123def456"
}
```

**에러 응답:**

- `400 Bad Request`: 필수 파라미터 누락
- `401 Unauthorized`: 인증 토큰 없음 또는 유효하지 않음
- `403 Forbidden`: 권한 없음 (본인의 댓글이 아님)
- `404 Not Found`: 댓글이 존재하지 않음

---

## 사용 예시

### cURL 예시

#### 댓글 생성

```bash
curl -X POST "http://localhost:8000/api/docs/comments" \
  -H "X-auth-token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
    "document_id": "doc_1234567890",
    "user_id": "user_1234567890",
    "comment": "이 문서에 대한 의견입니다.",
    "is_anonymity": false,
    "is_declaration": false
  }'
```

#### 댓글 목록 조회

```bash
curl -X GET "http://localhost:8000/api/docs/comments?workspace_id=0198d0e1-c214-71ae-8b84-b0e282f6c394&document_id=doc_1234567890&limit=20&page=1" \
  -H "X-auth-token: your_token_here"
```

#### 댓글 수정

```bash
curl -X PATCH "http://localhost:8000/api/docs/comments/comment_abc123def456" \
  -H "X-auth-token: your_token_here" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "0198d0e1-c214-71ae-8b84-b0e282f6c394",
    "comment": "수정된 댓글 내용입니다."
  }'
```

#### 댓글 삭제

```bash
curl -X DELETE "http://localhost:8000/api/docs/comments/comment_abc123def456?workspace_id=0198d0e1-c214-71ae-8b84-b0e282f6c394" \
  -H "X-auth-token: your_token_here"
```

### JavaScript (Fetch API) 예시

#### 댓글 생성

```javascript
const response = await fetch("http://localhost:8000/api/docs/comments", {
  method: "POST",
  headers: {
    "X-auth-token": "your_token_here",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    workspace_id: "0198d0e1-c214-71ae-8b84-b0e282f6c394",
    document_id: "doc_1234567890",
    user_id: "user_1234567890",
    comment: "이 문서에 대한 의견입니다.",
    is_anonymity: false,
    is_declaration: false,
  }),
});

const data = await response.json();
console.log(data);
```

#### 댓글 목록 조회

```javascript
const response = await fetch(
  "http://localhost:8000/api/docs/comments?workspace_id=0198d0e1-c214-71ae-8b84-b0e282f6c394&document_id=doc_1234567890&limit=20&page=1",
  {
    method: "GET",
    headers: {
      "X-auth-token": "your_token_here",
    },
  }
);

const data = await response.json();
console.log(data);
```

---

## 주의사항

1. **인증**: 모든 API 요청에는 `X-auth-token` 헤더가 필요합니다.
2. **워크스페이스 검증**: 모든 요청은 유효한 `workspace_id`를 포함해야 합니다.
3. **권한**: 댓글 수정/삭제는 본인이 작성한 댓글에 대해서만 가능합니다.
4. **CASCADE 삭제**: 문서가 삭제되면 해당 문서의 모든 댓글이 자동으로 삭제됩니다.
5. **익명 댓글**: `is_anonymity`가 `true`인 경우 `user_id`는 `null`로 저장됩니다.
6. **신고 기능**: `is_declaration`이 `true`인 댓글은 신고된 댓글로 표시됩니다.

---

## 데이터베이스 스키마

### 테이블명: `aicm.aicm_documents_comments`

```sql
CREATE TABLE aicm.aicm_documents_comments (
    id VARCHAR(50) PRIMARY KEY,
    workspace_id VARCHAR NOT NULL,
    document_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50),
    is_anonymity BOOLEAN DEFAULT FALSE,
    is_declaration BOOLEAN DEFAULT FALSE,
    comment TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    FOREIGN KEY (document_id) REFERENCES aicm.aicm_documents(id) ON DELETE CASCADE
);

CREATE INDEX idx_aicm_documents_comments_document_id ON aicm.aicm_documents_comments(document_id);
CREATE INDEX idx_aicm_documents_comments_workspace_id ON aicm.aicm_documents_comments(workspace_id);
CREATE INDEX idx_aicm_documents_comments_created_at ON aicm.aicm_documents_comments(created_at DESC);
```

---

## 관련 파일

- 모델: `db/models/document_comment.py`
- 스키마: `api/schemas/document_schemas.py` (예정)
- Repository: `db/repositories/document/document_comment_repository.py` (예정)
- Service: `db/services/document/document_comment_service.py` (예정)
- 엔드포인트: `api/endpoints/documents/comment_endpoints.py` (예정)
