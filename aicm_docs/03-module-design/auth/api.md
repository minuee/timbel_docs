# Auth API 스펙

> 참조: [FD-ACL-권한체계](../../01-requirements/features/FD-ACL-권한체계.md) · [rules.md](./rules.md) · [data.md](./data.md) · [03-auth-architecture](../../02-architecture/03-auth-architecture.md)

---

## 엔드포인트 요약

### Phase 1 — 권한 조회

| # | 메서드 | 경로 | 설명 | 권한 |
|---|--------|------|------|------|
| 1 | GET | `/me/permissions` | 현재 사용자 권한 조회 | 인증된 사용자 |

> 로그인/로그아웃/토큰 갱신은 KMS 영역이 아닌 외부 인증 서비스 소관이다. KMS(AuthGuard)는 수신된 토큰의 **검증만** 담당한다.

### Phase 2 — 관리 API (후속)

| # | 메서드 | 경로 | 설명 | 권한 |
|---|--------|------|------|------|
| 5 | GET | `/admin/roles` | 역할 목록 조회 | `manage_roles` |
| 6 | POST | `/admin/roles` | 역할 생성 | `manage_roles` |
| 7 | GET | `/admin/roles/:id` | 역할 상세 조회 | `manage_roles` |
| 8 | PUT | `/admin/roles/:id` | 역할 수정 | `manage_roles` |
| 9 | PATCH | `/admin/roles/:id/status` | 역할 상태 변경 | `manage_roles` |
| 10 | PUT | `/admin/roles/:id/permissions` | 역할 권한 일괄 설정 | `manage_roles` |
| 11 | GET | `/admin/teams` | 그룹 목록 조회 | `manage_teams` |
| 12 | POST | `/admin/teams` | 그룹 생성 | `manage_teams` |
| 13 | PUT | `/admin/teams/:id` | 그룹 수정 | `manage_teams` |
| 14 | PATCH | `/admin/teams/:id/status` | 그룹 상태 변경 | `manage_teams` |
| 15 | GET | `/admin/teams/:id/members` | 그룹 멤버 조회 | `manage_teams` |
| 16 | PUT | `/admin/teams/:id/members` | 멤버 일괄 설정 | `manage_teams` |
| 17 | PUT | `/admin/teams/:id/roles` | 그룹 역할 일괄 설정 | `manage_teams` |
| 18 | GET | `/admin/users/:id/effective-roles` | 사용자 유효 역할 조회 | `manage_roles` |

---

## Phase 1 — 엔드포인트 상세

### 1. GET `/me/permissions`

#### 기본 정보

| 항목 | 값 |
|------|---|
| 설명 | 현재 로그인 사용자의 유효 역할과 최종 권한 조회 |
| 권한 | 인증된 사용자 |
| 비즈니스 규칙 | BR-ACL-016 |

#### Request

```typescript
// Header: Authorization: Bearer <access_token>
// Query: 없음
```

#### Response

```typescript
// 200 OK
interface MyPermissionsResponse {
  /** 외부 IdP·ECP 등이 내려줄 수 있는 표시용 라벨(선택). AICM 인가 판단에는 사용하지 않는다. */
  serviceRole?: string;
  effectiveRoles: EffectiveRoleDto[];
  boardPermissions: BoardPermissionSummaryDto[];
  adminPermissions: string[];  // permission_key 목록
}

interface EffectiveRoleDto {
  id: string;
  name: string;
  source: 'direct' | 'team';  // 직접 할당 vs 그룹 상속
  teamName?: string;           // source=team일 때 팀명
}

interface BoardPermissionSummaryDto {
  boardId: string;
  boardName: string;
  actions: ('VIEW' | 'EDIT' | 'APPROVE')[];
}
```

---

## 내부 서비스 인터페이스 (모듈 간 DI)

다른 모듈이 auth 모듈에 DI로 접근하는 핵심 인터페이스. Guard/데코레이터를 통해 자동 적용된다.

### PermissionService

```typescript
enum BoardAction {
  VIEW = 'VIEW',
  EDIT = 'EDIT',
  APPROVE = 'APPROVE',
}

interface PermissionService {
  /** 유효 역할 산출 (캐시 적용) */
  getEffectiveRoles(userId: string): Promise<Role[]>;

  /** 게시판 접근 권한 확인 */
  checkBoardAccess(userId: string, boardId: string, action: BoardAction): Promise<boolean>;

  /** 문서 접근 권한 확인 (BoardPermission + DocumentRestriction) */
  checkDocumentAccess(userId: string, documentId: string, action: BoardAction): Promise<boolean>;

  /** AdminPermission 보유 확인 */
  checkAdminPermission(userId: string, permissionKey: string): Promise<boolean>;

  /** 접근 가능 게시판 ID 목록 (캐시 적용) — 검색 필터용 */
  getAccessibleBoardIds(userId: string, action: BoardAction): Promise<string[]>;

  /** 접근 제한된 문서 ID 목록 — 검색 필터용 */
  getRestrictedDocumentIds(userId: string): Promise<string[]>;

  /** 사용자 소속 팀 ID 목록 (상위 포함) */
  getUserTeamIds(userId: string): Promise<string[]>;
}
```

### AuthGuard / PermissionGuard 데코레이터

```typescript
// 컨트롤러에서 사용
@UseGuards(AuthGuard)                              // 인증만 확인
@UseGuards(AuthGuard, PermissionGuard)             // 인증 + 권한 확인

// 커스텀 데코레이터
@RequireBoardPermission(BoardAction.VIEW)          // 게시판 문서 자원 접근
@RequireAdminPermission('manage_roles')            // 관리 자원 접근
@RequireOwner()                                    // 개인 자원 접근 (소유자 확인)
```

---

## 공통 에러 코드

| 에러 코드 | HTTP | 설명 | BR |
|----------|------|------|---|
| `AUTH_TOKEN_MISSING` | 401 | Authorization 헤더 없음 | BR-ACL-040 |
| `AUTH_TOKEN_EXPIRED` | 401 | Access Token 만료 | BR-ACL-040 |
| `AUTH_TOKEN_INVALID` | 401 | 토큰 서명 검증 실패 | BR-ACL-040 |
| `ACL_PERMISSION_DENIED` | 403 | 해당 자원에 대한 권한 없음 | BR-ACL-022 |
| `ACL_RESTRICTION_DENIED` | 403 | DocumentRestriction 화이트리스트 미포함 | BR-ACL-026 |
