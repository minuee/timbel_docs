# Board API 스펙

> 참조: [FD-DOC-문서관리 &sect;7](../../01-requirements/features/FD-DOC-문서관리.md) &middot; [FD-NTC-공지사항 &sect;1](../../01-requirements/features/FD-NTC-공지사항.md) &middot; [rules.md](./rules.md) &middot; [data.md](./data.md) &middot; [03-auth-architecture](../../02-architecture/03-auth-architecture.md) &middot; [04-permission-architecture](../../02-architecture/04-permission-architecture.md)

---

## 엔드포인트 요약

| # | 메서드 | 경로 | 설명 | 권한 |
|---|--------|------|------|------|
| 1 | GET | `/boards/tree` | 게시판 트리 조회 (사이드바용) | 인증된 사용자 |
| 2 | GET | `/admin/boards` | 게시판 목록 조회 (관리용) | `manage_boards` |
| 3 | GET | `/admin/boards/:id` | 게시판 단건 조회 | `manage_boards` |
| 4 | POST | `/admin/boards` | 게시판 생성 | `manage_boards` |
| 5 | PUT | `/admin/boards/:id` | 게시판 수정 (설정 포함) | `manage_boards` |
| 6 | DELETE | `/admin/boards/:id` | 게시판 삭제 (soft delete) | `manage_boards` |
| 7 | PATCH | `/admin/boards/:id/move` | 게시판 이동 (parent_id/sort_order 변경) | `manage_boards` |
| 8 | GET | `/admin/boards/:id/permissions` | 게시판 권한 조회 | `manage_boards` |
| 9 | PUT | `/admin/boards/:id/permissions` | 게시판 권한 일괄 설정 | `manage_boards` |

---

## 1. GET `/boards/tree`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 현재 사용자가 VIEW 권한을 가진 게시판을 재귀 트리 구조로 반환. 사이드바 네비게이션용 |
| 권한 | 인증된 사용자 |
| 비즈니스 규칙 | BR-BRD-001 |

### Request

```typescript
// Query
interface GetBoardTreeQuery {
  board_type?: 'knowledge' | 'community' | 'notice' | 'custom'; // 특정 타입만 필터 (생략 시 전체)
}
```

### Response

```typescript
// 200 OK
interface BoardTreeNodeDto {
  id: string;
  name: string;
  slug: string;
  board_type: 'knowledge' | 'community' | 'notice' | 'custom';
  is_active: boolean;
  sort_order: number;
  children: BoardTreeNodeDto[];
}

type GetBoardTreeResponse = BoardTreeNodeDto[];
```

### 비즈니스 규칙

| BR | 설명 |
|----|------|
| BR-BRD-001 | 사용자의 유효 역할(effective roles)로부터 VIEW 권한이 있는 게시판만 반환. is_active = true인 게시판만 포함 |

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 401 | `AUTH_TOKEN_MISSING` | 인증 토큰 없음 | — |
| 401 | `AUTH_TOKEN_EXPIRED` | 토큰 만료 | — |

---

## 2. GET `/admin/boards`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 전체 게시판 목록을 플랫 구조로 조회. 관리자 게시판 설정 화면용 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002 |

### Request

```typescript
// Query
interface GetBoardsQuery {
  board_type?: 'knowledge' | 'community' | 'notice' | 'custom'; // 타입 필터
  is_active?: boolean;      // 활성 상태 필터
  parent_id?: string | null; // 상위 게시판 필터 (null이면 루트만)
  page?: number;             // 페이지 번호 (기본 1)
  limit?: number;            // 페이지 크기 (기본 20, 최대 100)
}
```

### Response

```typescript
// 200 OK
interface BoardListItemDto {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  board_type: 'knowledge' | 'community' | 'notice' | 'custom';
  approval_required: boolean;
  versioning_enabled: boolean;
  parent_id: string | null;
  sort_order: number;
  is_active: boolean;
  created_by: string;
  created_at: string;       // ISO 8601
  updated_at: string;       // ISO 8601
}

interface GetBoardsResponse {
  items: BoardListItemDto[];
  total: number;
  page: number;
  limit: number;
}
```

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |

---

## 3. GET `/admin/boards/:id`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 게시판 단건 상세 조회 — 설정(board_config), 승인/버전/템플릿/보존 정책 포함 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002, BR-BRD-010 |

### Request

```typescript
// Path Params
interface GetBoardParams {
  id: string; // 게시판 UUID
}
```

### Response

```typescript
// 200 OK
interface BoardDetailDto {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  board_type: 'knowledge' | 'community' | 'notice' | 'custom';
  approval_required: boolean;
  versioning_enabled: boolean;
  parent_id: string | null;
  sort_order: number;
  is_active: boolean;
  mandatory_approval_config: MandatoryApprovalConfig | null;
  default_approval_template_id: string | null;
  default_template_id: string | null;
  default_retention_policy_id: string | null;
  board_config: BoardConfig;
  created_by: string;
  created_at: string;       // ISO 8601
  updated_at: string;       // ISO 8601
  deleted_at: string | null; // ISO 8601
}

interface MandatoryApprovalConfig {
  self_approve_blocked: boolean;
  delegation_allowed: boolean;
  sla_hours: number;
  auto_reject_grace_hours: number;
}

interface BoardConfig {
  notice?: NoticeConfig;
  banner?: BannerConfig;
  [key: string]: unknown;   // 댓글/표시/첨부/알림/글작성 등 확장 키
}

interface NoticeConfig {
  default_popup: boolean;
  default_popup_frequency: 'once' | 'every_login' | 'daily';
  default_confirmation_required: boolean;
  default_confirmation_deadline_days: number | null;
  max_pinned_count: number;
  reminder_days_before: number[];
  overdue_reminder_interval_hours: number;
  allowed_notification_channels: string[];
  include_in_rag: boolean;
}

interface BannerConfig {
  show_cross_board_banner: boolean;
  max_banner_count: number;
}
```

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |
| 404 | `BRD_NOT_FOUND` | 존재하지 않는 게시판 ID | BR-BRD-010 |

---

## 4. POST `/admin/boards`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 새 게시판 생성 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002, BR-BRD-003, BR-BRD-004, BR-BRD-005, BR-BRD-014 |

### Request

```typescript
// Body
interface CreateBoardRequest {
  name: string;                          // 게시판명 (필수)
  slug: string;                          // URL 경로용 식별자 (필수, UNIQUE)
  description?: string;                  // 게시판 설명
  board_type: 'knowledge' | 'community' | 'notice' | 'custom'; // 게시판 타입 (필수)
  approval_required?: boolean;           // 승인 필수 여부 (기본 false)
  versioning_enabled?: boolean;          // 버전 관리 여부 (기본 false)
  parent_id?: string;                    // 상위 게시판 UUID (생략 시 루트)
  sort_order?: number;                   // 정렬 순서 (기본 0)
  mandatory_approval_config?: MandatoryApprovalConfig;
  default_approval_template_id?: string;
  default_template_id?: string;
  default_retention_policy_id?: string;
  board_config?: BoardConfig;
}
```

### Response

```typescript
// 201 Created
interface CreateBoardResponse {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  board_type: 'knowledge' | 'community' | 'notice' | 'custom';
  approval_required: boolean;
  versioning_enabled: boolean;
  parent_id: string | null;
  sort_order: number;
  is_active: boolean;
  board_config: BoardConfig;
  created_by: string;
  created_at: string;       // ISO 8601
}
```

### 비즈니스 규칙

| BR | 설명 |
|----|------|
| BR-BRD-002 | `manage_boards` AdminPermission 필수 |
| BR-BRD-003 | slug는 시스템 전체에서 UNIQUE. 중복 시 `BRD_SLUG_DUPLICATE` 반환 |
| BR-BRD-004 | parent_id가 지정된 경우 해당 게시판이 존재하고 삭제되지 않았어야 함 |
| BR-BRD-005 | notice 타입 생성 시 기본 board_config.notice 설정이 자동 적용됨 [BR-NTC-006] |
| BR-BRD-014 | notice 타입 생성 시 전체 사용자에게 VIEW 권한 기본 부여 [BR-NTC-003] |

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 400 | `BRD_INVALID_BOARD_TYPE` | 유효하지 않은 board_type 값 | — |
| 400 | `BRD_INVALID_PARENT` | parent_id가 존재하지 않거나 삭제된 게시판 | BR-BRD-004 |
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |
| 409 | `BRD_SLUG_DUPLICATE` | slug 중복 | BR-BRD-003 |

---

## 5. PUT `/admin/boards/:id`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 게시판 정보 및 설정 수정 — board_config, 승인/버전/템플릿/보존 정책 포함 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002, BR-BRD-003, BR-BRD-006, BR-BRD-010, BR-BRD-013, BR-BRD-015 |

### Request

```typescript
// Path Params
interface UpdateBoardParams {
  id: string; // 게시판 UUID
}

// Body
interface UpdateBoardRequest {
  name?: string;
  slug?: string;
  description?: string | null;
  board_type?: 'knowledge' | 'community' | 'notice' | 'custom';
  approval_required?: boolean;
  versioning_enabled?: boolean;
  is_active?: boolean;
  mandatory_approval_config?: MandatoryApprovalConfig | null;
  default_approval_template_id?: string | null;
  default_template_id?: string | null;
  default_retention_policy_id?: string | null;
  board_config?: BoardConfig;
}
```

### Response

```typescript
// 200 OK
interface UpdateBoardResponse {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  board_type: 'knowledge' | 'community' | 'notice' | 'custom';
  approval_required: boolean;
  versioning_enabled: boolean;
  parent_id: string | null;
  sort_order: number;
  is_active: boolean;
  board_config: BoardConfig;
  updated_at: string;       // ISO 8601
}
```

### 비즈니스 규칙

| BR | 설명 |
|----|------|
| BR-BRD-002 | `manage_boards` AdminPermission 필수 |
| BR-BRD-003 | slug 변경 시 시스템 전체에서 UNIQUE 검증 |
| BR-BRD-006 | approval_required, versioning_enabled는 루트 게시판에서만 설정 가능. 하위 게시판은 상속 |
| BR-BRD-010 | 존재하지 않는 게시판 ID 시 `BRD_NOT_FOUND` 반환 |
| BR-BRD-013 | is_active 변경 시 활성/비활성 전환 — 비활성화 시 사용자 트리에서 제외, 새 문서 작성 차단 |
| BR-BRD-015 | board_config 키 누락 시 애플리케이션 레벨 기본값 적용 [BR-NTC-006] |

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 400 | `BRD_INVALID_BOARD_TYPE` | 유효하지 않은 board_type 값 | — |
| 400 | `BRD_ROOT_ONLY_SETTING` | 하위 게시판에서 approval_required/versioning_enabled 변경 시도 | BR-BRD-006 |
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |
| 404 | `BRD_NOT_FOUND` | 존재하지 않는 게시판 ID | BR-BRD-010 |
| 409 | `BRD_SLUG_DUPLICATE` | slug 중복 | BR-BRD-003 |

---

## 6. DELETE `/admin/boards/:id`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 게시판 소프트 삭제 (deleted_at 설정). 하위 게시판이 있으면 삭제 차단 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002, BR-BRD-007, BR-BRD-008, BR-BRD-010 |

### Request

```typescript
// Path Params
interface DeleteBoardParams {
  id: string; // 게시판 UUID
}
```

### Response

```typescript
// 200 OK
interface DeleteBoardResponse {
  id: string;
  deleted_at: string; // ISO 8601
}
```

### 비즈니스 규칙

| BR | 설명 |
|----|------|
| BR-BRD-002 | `manage_boards` AdminPermission 필수 |
| BR-BRD-007 | 하위 게시판(parent_id = 해당 ID)이 존재하면 삭제 차단 |
| BR-BRD-008 | 게시판에 published 상태의 문서가 존재하면 삭제 차단. 문서를 먼저 이동하거나 아카이브 처리 필요 |
| BR-BRD-010 | 존재하지 않는 게시판 ID 시 `BRD_NOT_FOUND` 반환 |

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |
| 404 | `BRD_NOT_FOUND` | 존재하지 않는 게시판 ID | BR-BRD-010 |
| 409 | `BRD_HAS_CHILDREN` | 하위 게시판이 존재하여 삭제 불가 | BR-BRD-007 |
| 409 | `BRD_HAS_DOCUMENTS` | published 상태의 문서가 존재하여 삭제 불가 | BR-BRD-008 |

---

## 7. PATCH `/admin/boards/:id/move`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 게시판 위치 이동 — parent_id 변경 또는 sort_order 변경 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002, BR-BRD-004, BR-BRD-009, BR-BRD-010 |

### Request

```typescript
// Path Params
interface MoveBoardParams {
  id: string; // 게시판 UUID
}

// Body
interface MoveBoardRequest {
  parent_id?: string | null; // 이동 대상 상위 게시판 (null이면 루트로 이동)
  sort_order?: number;       // 새 정렬 순서
}
```

### Response

```typescript
// 200 OK
interface MoveBoardResponse {
  id: string;
  parent_id: string | null;
  sort_order: number;
  updated_at: string; // ISO 8601
}
```

### 비즈니스 규칙

| BR | 설명 |
|----|------|
| BR-BRD-002 | `manage_boards` AdminPermission 필수 |
| BR-BRD-004 | parent_id가 지정된 경우 해당 게시판이 존재하고 삭제되지 않았어야 함 |
| BR-BRD-009 | 자기 자신 또는 자신의 하위 게시판으로 이동 불가 (순환 참조 방지) |
| BR-BRD-010 | 존재하지 않는 게시판 ID 시 `BRD_NOT_FOUND` 반환 |

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 400 | `BRD_INVALID_PARENT` | parent_id가 존재하지 않거나 삭제된 게시판 | BR-BRD-004 |
| 400 | `BRD_CIRCULAR_REFERENCE` | 자기 자신 또는 하위 게시판으로 이동 시도 (순환 참조) | BR-BRD-009 |
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |
| 404 | `BRD_NOT_FOUND` | 존재하지 않는 게시판 ID | BR-BRD-010 |

---

## 8. GET `/admin/boards/:id/permissions`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 특정 게시판의 Role-Action 권한 매핑 목록 조회 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002, BR-BRD-010 |

### Request

```typescript
// Path Params
interface GetBoardPermissionsParams {
  id: string; // 게시판 UUID
}
```

### Response

```typescript
// 200 OK
interface BoardPermissionDto {
  id: string;
  board_id: string;
  role_id: string;
  role_name: string;         // Role 조인 조회
  action: 'VIEW' | 'EDIT' | 'APPROVE';
  created_at: string;        // ISO 8601
}

type GetBoardPermissionsResponse = BoardPermissionDto[];
```

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |
| 404 | `BRD_NOT_FOUND` | 존재하지 않는 게시판 ID | BR-BRD-010 |

---

## 9. PUT `/admin/boards/:id/permissions`

### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 게시판 권한 일괄 설정 — 기존 권한을 전체 교체 (Replace All). 변경 시 `board.permissions_updated` 이벤트 발행 |
| 권한 | `manage_boards` AdminPermission |
| 비즈니스 규칙 | BR-BRD-002, BR-BRD-010, BR-BRD-011, BR-BRD-012 |

### Request

```typescript
// Path Params
interface SetBoardPermissionsParams {
  id: string; // 게시판 UUID
}

// Body
interface SetBoardPermissionsRequest {
  permissions: BoardPermissionInput[];
}

interface BoardPermissionInput {
  role_id: string;
  action: 'VIEW' | 'EDIT' | 'APPROVE';
}
```

### Response

```typescript
// 200 OK
interface SetBoardPermissionsResponse {
  board_id: string;
  permissions: BoardPermissionDto[];
  updated_at: string; // ISO 8601
}
```

### 비즈니스 규칙

| BR | 설명 |
|----|------|
| BR-BRD-002 | `manage_boards` AdminPermission 필수 |
| BR-BRD-010 | 존재하지 않는 게시판 ID 시 `BRD_NOT_FOUND` 반환 |
| BR-BRD-011 | role_id가 유효한 활성 역할이어야 함. 존재하지 않거나 비활성 역할 시 `BRD_INVALID_ROLE` 반환 |
| BR-BRD-012 | 권한 변경 완료 후 `board.events` BullMQ 큐에 `board.permissions_updated` 이벤트를 발행하여 AuthModule의 권한 캐시를 무효화 |

### 에러 응답

| HTTP | 에러 코드 | 조건 | BR |
|------|----------|------|---|
| 400 | `BRD_INVALID_ROLE` | 존재하지 않거나 비활성 상태의 role_id | BR-BRD-011 |
| 400 | `BRD_INVALID_ACTION` | 유효하지 않은 action 값 (VIEW/EDIT/APPROVE 외) | — |
| 403 | `ACL_PERMISSION_DENIED` | `manage_boards` 권한 미보유 | BR-BRD-002 |
| 404 | `BRD_NOT_FOUND` | 존재하지 않는 게시판 ID | BR-BRD-010 |

---

## 내부 서비스 인터페이스 (모듈 간 DI)

다른 모듈이 BoardModule에 DI로 접근하는 핵심 인터페이스.

### BoardService

```typescript
interface BoardService {
  /** 게시판 단건 조회 (삭제된 게시판 제외) */
  findById(boardId: string): Promise<Board | null>;

  /** 게시판 설정 조회 — DocumentModule, ApprovalModule에서 사용 */
  getBoardSettings(boardId: string): Promise<BoardSettingsDto>;

  /** 게시판 트리 조회 (캐시 적용) — 사이드바용 */
  getBoardTree(boardType?: string): Promise<BoardTreeNodeDto[]>;

  /** 특정 게시판의 하위 게시판 ID 목록 (재귀) — 검색/RAG 범위 한정용 */
  getDescendantBoardIds(boardId: string): Promise<string[]>;
}

interface BoardSettingsDto {
  board_type: 'knowledge' | 'community' | 'notice' | 'custom';
  approval_required: boolean;
  versioning_enabled: boolean;
  mandatory_approval_config: MandatoryApprovalConfig | null;
  default_approval_template_id: string | null;
  default_template_id: string | null;
  default_retention_policy_id: string | null;
  board_config: BoardConfig;
}
```

---

## 공통 에러 코드

| 에러 코드 | HTTP | 설명 | BR |
|----------|------|------|---|
| `BRD_NOT_FOUND` | 404 | 존재하지 않는 게시판 ID 접근 | BR-BRD-010 |
| `BRD_SLUG_DUPLICATE` | 409 | slug 중복 — 시스템 전체 UNIQUE 위반 | BR-BRD-003 |
| `BRD_INVALID_BOARD_TYPE` | 400 | 유효하지 않은 board_type 값 (knowledge/community/notice/custom 외) | — |
| `BRD_INVALID_PARENT` | 400 | parent_id가 존재하지 않거나 삭제된 게시판 | BR-BRD-004 |
| `BRD_CIRCULAR_REFERENCE` | 400 | 자기 자신 또는 하위 게시판으로 이동 시도 (순환 참조) | BR-BRD-009 |
| `BRD_ROOT_ONLY_SETTING` | 400 | 하위 게시판에서 루트 전용 설정(approval_required/versioning_enabled) 변경 시도 | BR-BRD-006 |
| `BRD_HAS_CHILDREN` | 409 | 하위 게시판이 존재하여 삭제 불가 | BR-BRD-007 |
| `BRD_HAS_DOCUMENTS` | 409 | published 상태의 문서가 존재하여 삭제 불가 | BR-BRD-008 |
| `BRD_INVALID_ROLE` | 400 | 존재하지 않거나 비활성 상태의 role_id | BR-BRD-011 |
| `BRD_INVALID_ACTION` | 400 | 유효하지 않은 action 값 (VIEW/EDIT/APPROVE 외) | — |
| `ACL_PERMISSION_DENIED` | 403 | `manage_boards` AdminPermission 미보유 | BR-BRD-002 |
