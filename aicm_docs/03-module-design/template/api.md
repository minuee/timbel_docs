# Template API 스펙

> 참조: [FD-DOC-문서관리 §4](../../01-requirements/features/FD-DOC-문서관리.md) · [rules.md](./rules.md) · [data.md](./data.md) · [04-permission-architecture](../../02-architecture/04-permission-architecture.md)

---

## 엔드포인트 요약

### 관리 API — `manage_templates` AdminPermission

| # | 메서드 | 경로 | 설명 | 권한 |
|---|--------|------|------|------|
| 1 | GET | `/admin/templates` | 템플릿 목록 조회 (비활성 포함) | `manage_templates` |
| 2 | POST | `/admin/templates` | 템플릿 생성 | `manage_templates` |
| 3 | GET | `/admin/templates/:id` | 템플릿 상세 조회 | `manage_templates` |
| 4 | POST | `/admin/templates/:id/clone` | 템플릿 복제 | `manage_templates` |
| 5 | PATCH | `/admin/templates/:id/status` | 활성/비활성 토글 | `manage_templates` |

### 조회 API — 인증된 사용자

| # | 메서드 | 경로 | 설명 | 권한 |
|---|--------|------|------|------|
| 6 | GET | `/templates` | 활성 템플릿 목록 조회 | 인증된 사용자 |
| 7 | GET | `/templates/:id` | 템플릿 상세 조회 | 인증된 사용자 |

---

## 관리 API — 엔드포인트 상세

### 1. GET `/admin/templates`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 전체 템플릿 목록 조회 (비활성 포함) |
| 권한 | `manage_templates` |
| 비즈니스 규칙 | BR-TPL-007 |

#### Request

```typescript
// Query Parameters
interface ListAdminTemplatesQuery {
  category?: string;       // 카테고리 필터 (예: 'SOP', 'FAQ')
  isActive?: boolean;      // 활성 여부 필터
  search?: string;         // 템플릿명 검색 (ILIKE)
  page?: number;           // 페이지 번호 (기본: 1)
  limit?: number;          // 페이지 크기 (기본: 20, 최대: 100)
  sort?: string;           // 정렬 (기본: 'createdAt:desc')
}
```

#### Response

```typescript
// 200 OK
interface PaginatedTemplateResponse {
  items: TemplateDto[];
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

interface TemplateDto {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  contentBlocks: object[];     // Tiptap 블록 JSON 배열
  defaultTags: string[] | null;
  isActive: boolean;
  createdBy: string;
  createdAt: string;           // ISO 8601
  updatedAt: string;           // ISO 8601
}
```

---

### 2. POST `/admin/templates`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 새 템플릿 생성 |
| 권한 | `manage_templates` |
| 비즈니스 규칙 | BR-TPL-001, BR-TPL-007 |

#### Request

```typescript
interface CreateTemplateDto {
  name: string;                  // 필수, 템플릿명
  description?: string;          // 선택, 템플릿 설명
  category?: string;             // 선택, 분류 (SOP, FAQ, 체크리스트, 공지, 장애대응 등)
  contentBlocks: object[];       // 필수, Tiptap 블록 JSON 배열
  defaultTags?: string[];        // 선택, 기본 태그 목록
}
```

#### Response

```typescript
// 201 Created
TemplateDto
```

#### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 422 | `TPL_VALIDATION_ERROR` | name 누락 또는 contentBlocks가 빈 배열 | BR-TPL-001 |
| 403 | `ACL_PERMISSION_DENIED` | `manage_templates` 권한 미보유 | BR-TPL-007 |

---

### 3. GET `/admin/templates/:id`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 템플릿 상세 조회 (비활성 포함) |
| 권한 | `manage_templates` |
| 비즈니스 규칙 | BR-TPL-007 |

#### Request

```typescript
// Path Parameters
// id: string (UUID) — 템플릿 ID
```

#### Response

```typescript
// 200 OK
TemplateDto
```

#### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 404 | `TPL_NOT_FOUND` | 해당 ID의 템플릿이 존재하지 않음 | — |

---

### 4. POST `/admin/templates/:id/clone`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 기존 템플릿을 복제하여 새 템플릿 생성 |
| 권한 | `manage_templates` |
| 비즈니스 규칙 | BR-TPL-002, BR-TPL-001, BR-TPL-007 |

#### Request

```typescript
// Path Parameters
// id: string (UUID) — 복제 원본 템플릿 ID

interface CloneTemplateDto {
  name: string;                  // 필수, 새 템플릿명
  description?: string;          // 선택, 미지정 시 원본 값 복사
  category?: string;             // 선택, 미지정 시 원본 값 복사
  contentBlocks?: object[];      // 선택, 미지정 시 원본 값 복사
  defaultTags?: string[];        // 선택, 미지정 시 원본 값 복사
}
```

#### Response

```typescript
// 201 Created
TemplateDto  // 새로운 id 발급, is_active = true, created_by = 요청자
```

#### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 404 | `TPL_NOT_FOUND` | 원본 템플릿이 존재하지 않음 | BR-TPL-002 |
| 422 | `TPL_VALIDATION_ERROR` | name 누락 | BR-TPL-001 |
| 403 | `ACL_PERMISSION_DENIED` | `manage_templates` 권한 미보유 | BR-TPL-007 |

---

### 5. PATCH `/admin/templates/:id/status`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 템플릿 활성/비활성 토글 |
| 권한 | `manage_templates` |
| 비즈니스 규칙 | BR-TPL-004, BR-TPL-005, BR-TPL-007 |

#### Request

```typescript
// Path Parameters
// id: string (UUID) — 템플릿 ID

interface UpdateTemplateStatusDto {
  isActive: boolean;  // true: 활성, false: 비활성
}
```

#### Response

```typescript
// 200 OK
TemplateDto  // updated_at 갱신
```

#### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 404 | `TPL_NOT_FOUND` | 해당 ID의 템플릿이 존재하지 않음 | — |
| 409 | `TPL_ALREADY_INACTIVE` | 이미 비활성 상태에서 비활성 요청 | BR-TPL-004 |
| 409 | `TPL_ALREADY_ACTIVE` | 이미 활성 상태에서 활성 요청 | BR-TPL-005 |
| 403 | `ACL_PERMISSION_DENIED` | `manage_templates` 권한 미보유 | BR-TPL-007 |

---

## 조회 API — 엔드포인트 상세

### 6. GET `/templates`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 활성 템플릿 목록 조회 (문서 생성 시 선택용) |
| 권한 | 인증된 사용자 |
| 비즈니스 규칙 | BR-TPL-006 |

#### Request

```typescript
// Query Parameters
interface ListTemplatesQuery {
  category?: string;       // 카테고리 필터
  search?: string;         // 템플릿명 검색 (ILIKE)
  page?: number;           // 페이지 번호 (기본: 1)
  limit?: number;          // 페이지 크기 (기본: 20, 최대: 100)
  sort?: string;           // 정렬 (기본: 'name:asc')
}
```

#### Response

```typescript
// 200 OK
PaginatedTemplateResponse  // is_active = true인 항목만 반환
```

---

### 7. GET `/templates/:id`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 템플릿 상세 조회 (활성 템플릿만) |
| 권한 | 인증된 사용자 |
| 비즈니스 규칙 | BR-TPL-006 |

#### Request

```typescript
// Path Parameters
// id: string (UUID) — 템플릿 ID
```

#### Response

```typescript
// 200 OK
TemplateDto
```

#### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 404 | `TPL_NOT_FOUND` | 해당 ID의 템플릿이 존재하지 않거나 비활성 상태 | BR-TPL-006 |

---

## 내부 서비스 인터페이스 (모듈 간 DI)

다른 모듈이 TemplateModule에 DI로 접근하는 핵심 인터페이스.

### TemplateService

```typescript
interface TemplateService {
  /** 템플릿 상세 조회 (내부 모듈용 — is_active 무관) */
  findById(id: string): Promise<Template | null>;

  /** 활성 템플릿 목록 (문서 생성 시 선택용) */
  findActive(filter?: { category?: string }): Promise<Template[]>;
}
```

> DocumentModule은 문서 생성 시 `findById()`로 템플릿 구조를 조회한다. SearchModule은 `TemplateChunkingRule.template_id`를 통해 템플릿 기반 청킹 전략을 분기한다 (TemplateService DI 의존 없이 FK 참조).

---

## 공통 에러 코드

| 에러 코드 | HTTP | 설명 | BR |
|----------|------|------|---|
| `TPL_NOT_FOUND` | 404 | 템플릿을 찾을 수 없음 (비활성 포함) | — |
| `TPL_VALIDATION_ERROR` | 422 | 필수 필드 누락 또는 유효하지 않은 값 | BR-TPL-001 |
| `TPL_ALREADY_INACTIVE` | 409 | 이미 비활성 상태에서 비활성 요청 | BR-TPL-004 |
| `TPL_ALREADY_ACTIVE` | 409 | 이미 활성 상태에서 활성 요청 | BR-TPL-005 |
