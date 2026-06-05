# user-service API Spec

> **대상 독자**: user-service 개발 담당자
> Base URL: `{USER_SERVICE_URL}/api/v1`

이 문서는 AICM이 user-service로부터 기대하는 API 계약을 정의한다. user-service 담당자는 이 스펙에 맞춰 API를 구현하면 AICM 측 연동 코드와 호환된다.

> **원천 문서**: [user-service 연동 설계](../6-5-user-service-integration.md)

---

## 엔드포인트 요약

| Method | Endpoint | 설명 | 비고 |
|--------|----------|------|------|
| `GET` | `/organizations/tree` | 전사 조직도 트리 조회 | §1 |
| `GET` | `/organizations/{departmentId}` | 단일 부서 조회 | §2 |
| `GET` | `/users/{userId}` | 사용자 상세 조회 | §3 |
| `GET` | `/users` | 사용자 목록 조회 (필터·페이지네이션) | §4 |
| `GET` | `/health` | 헬스체크 | §5 |

---

## 공통 규칙

### 네이밍

- DTO·응답 필드명은 **camelCase**를 사용한다.
- 날짜/시각 필드는 **ISO 8601** 형식이다 (예: `2026-04-13T09:00:00+09:00`).

### 인증

> 인증 방식은 미확정이다(API Key / JWT / mTLS 중 협의 필요). 확정 시 이 섹션을 업데이트한다.

### 에러 응답 공통 구조

모든 4xx/5xx 에러는 아래 구조로 반환한다.

```typescript
interface UserServiceError {
  error: {
    code: string;
    message: string;
    details?: Record<string, any>;
  };
  requestId?: string;
}
```

| HTTP 상태 | 에러 코드 | 설명 |
|:---------:|----------|------|
| `400` | `INVALID_REQUEST` | 요청 파라미터 오류 |
| `401` | `UNAUTHORIZED` | 인증 실패 |
| `403` | `FORBIDDEN` | 권한 부족 |
| `404` | `NOT_FOUND` | 대상 리소스 미존재 |
| `429` | `RATE_LIMITED` | 요청 제한 초과 |
| `500` | `INTERNAL_ERROR` | 서버 내부 오류 |
| `503` | `SERVICE_UNAVAILABLE` | 서비스 비가용 |

---

## 1. `GET /organizations/tree`

전사 조직도를 트리 구조로 반환한다. AICM은 이 데이터를 동기화하여 문서 접근 권한, 승인 라인 구성, 게시판 부서 할당에 사용한다.

### Query Parameters

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:----:|------|
| `activeOnly` | `boolean` | N | `true`면 활성 부서만 포함 (기본값: `true`) |

### Response `200`

```typescript
interface OrganizationTreeResponse {
  root: DepartmentNode;
  totalDepartments: number;
  totalUsers: number;
  syncedAt: string;                // ISO 8601 — 마지막 동기화 시점
}
```

`DepartmentNode`는 [§ 공유 타입](#공유-타입) 참조.

### 예시 응답

```json
{
  "root": {
    "id": "org-root",
    "name": "회사",
    "level": 0,
    "path": "company",
    "isActive": true,
    "children": [
      {
        "id": "dept-tech",
        "name": "기술본부",
        "level": 1,
        "parentId": "org-root",
        "path": "company/tech",
        "managerId": "user-002",
        "isActive": true,
        "children": [
          {
            "id": "dept-dev1",
            "name": "개발1팀",
            "level": 2,
            "parentId": "dept-tech",
            "path": "company/tech/dev1",
            "managerId": "user-002",
            "sortOrder": 1,
            "isActive": true,
            "userCount": 5,
            "children": []
          }
        ]
      }
    ]
  },
  "totalDepartments": 14,
  "totalUsers": 85,
  "syncedAt": "2026-04-13T09:00:00+09:00"
}
```

---

## 2. `GET /organizations/{departmentId}`

단일 부서의 상세 정보를 반환한다. 하위 부서 트리는 포함하지 않는다.

### Path Parameters

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `departmentId` | `string` | 부서 고유 ID |

### Response `200`

```typescript
interface DepartmentDetailResponse {
  id: string;
  code?: string;
  name: string;
  nameEn?: string;
  level: number;
  parentId?: string;
  path: string;
  managerId?: string;
  sortOrder?: number;
  isActive: boolean;
  userCount?: number;
}
```

### Response `404`

부서가 존재하지 않을 때 반환한다.

---

## 3. `GET /users/{userId}`

사용자 상세 정보를 반환한다.

### Path Parameters

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `userId` | `string` | 사용자 고유 ID |

### Response `200`

```typescript
interface UserResponse {
  id: string;
  employeeId: string;           // 사번
  email: string;                // 로그인 ID
  name: string;
  nameEn?: string;
  phone?: string;
  profileImageUrl?: string;
  departmentId: string;         // 소속 부서 ID
  departmentPath: string;       // 소속 부서 경로 (예: "company/tech/dev1")
  position: string;             // 직급 (선임, 책임, 수석 등)
  jobTitle?: string;            // 직책 (팀장, 파트장 등)
  /** 포털·인사 연동 표시용 — AICM 인가와 무관 */
  externalRoleLabel?: string;
  status: UserStatus;
  joinedAt?: string;            // 입사일 (ISO 8601)
  lastLoginAt?: string;         // 마지막 로그인 (ISO 8601)
}
```

### Response `404`

사용자가 존재하지 않을 때 반환한다.

---

## 4. `GET /users`

사용자 목록을 조회한다. 부서 필터 및 페이지네이션을 지원한다.

### Query Parameters

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:----:|------|
| `departmentId` | `string` | N | 부서 ID로 필터링 |
| `includeChildren` | `boolean` | N | `true`면 하위 부서 소속 사용자 포함 (기본값: `false`) |
| `externalRoleLabel` | `string` | N | 표시 라벨(있다면)로 필터링 — AICM 인가와 무관 |
| `status` | `UserStatus` | N | 사용자 상태로 필터링 (기본값: `active`) |
| `keyword` | `string` | N | 이름/사번/이메일 검색 |
| `page` | `number` | N | 페이지 번호 (기본값: `1`, 1-based) |
| `pageSize` | `number` | N | 페이지 크기 (기본값: `20`, 최대: `100`) |

### Response `200`

```typescript
interface UserListResponse {
  users: UserSummary[];
  totalCount: number;
  page: number;
  pageSize: number;
}

interface UserSummary {
  id: string;
  employeeId: string;
  email: string;
  name: string;
  departmentId: string;
  departmentName: string;
  position: string;
  jobTitle?: string;
  externalRoleLabel?: string;
  status: UserStatus;
}
```

---

## 5. `GET /health`

서비스 가용성을 확인한다.

### Response `200`

```typescript
interface HealthResponse {
  status: 'ok' | 'degraded' | 'down';
  uptimeSeconds: number;
}
```

| `status` | 조건 |
|----------|------|
| `ok` | 모든 컴포넌트 정상 |
| `degraded` | 일부 기능 비가용 |
| `down` | 서비스 불가 |

---

## 공유 타입

### `DepartmentNode`

```typescript
interface DepartmentNode {
  id: string;                   // 부서 고유 ID (UUID 권장)
  code?: string;                // 부서 코드 (HR 시스템 연계용) — 선택
  name: string;                 // 부서명
  nameEn?: string;              // 영문 부서명
  level: number;                // 트리 깊이 (0 = 최상위)
  parentId?: string;            // 상위 부서 ID (root는 미전달)
  path: string;                 // 경로 (예: "company/tech/dev1")
  managerId?: string;           // 부서장 사용자 ID
  sortOrder?: number;           // 형제 노드 내 정렬 순서 — 선택
  isActive: boolean;            // 활성 여부
  children: DepartmentNode[];   // 하위 부서 목록 (트리 조회 시만 포함)
  userCount?: number;           // 직속 사용자 수 (하위 부서 미포함) — 선택
}
```

### 외부 표시 라벨 (`externalRoleLabel`)

UserService·포털이 사용자에게 붙일 수 있는 **표시용 문자열**(선택). 고객사마다 값 집합이 다르며, **`system` / `admin` / `normal` 고정 3단계를 강제하지 않는다.**

> **AICM 연동**: 위 필드는 표시·감사·연동 **메타데이터**로만 쓴다. AICM API 인가는 AICM **Role**의 `BoardPermission`·`AdminPermission`만으로 판단한다. 외부 라벨과 `AdminPermission` 보유 여부는 **대응되지 않는다**([FD-ACL](../../../01-requirements/features/FD-ACL-권한체계.md) §2).

### `UserStatus`

```typescript
type UserStatus = 'active' | 'inactive' | 'suspended' | 'resigned';
```

| 값 | 설명 |
|----|------|
| `active` | 재직 중 (정상) |
| `inactive` | 비활성 (휴직 등) |
| `suspended` | 정지 |
| `resigned` | 퇴직 |

---

## 미확정 사항

아래 항목은 AICM-user-service 간 협의가 필요하다.

| # | 항목 | 현재 상태 | 비고 |
|---|------|----------|------|
| 1 | 인증 방식 | TBD | API Key / JWT / mTLS 중 협의 필요 |
| 2 | Rate Limit 정책 | TBD | 분당 호출 수 / 동기화 배치 크기 협의 |
| 3 | 웹훅 vs 폴링 동기화 | TBD | 동기화 방식 협의 필요 |
| 4 | 사용자 삭제 정책 | TBD | soft delete vs hard delete — 개인정보보호 정책 검토 필요 |
| 5 | 조직도 변경 이벤트 | TBD | 부서 신설/폐지/이동 시 이벤트 발행 여부 |

---

## 관련 문서

- [user-service 연동 설계](../6-5-user-service-integration.md) — AICM 측 통합 설계 (추상화 전략, 목업 데이터 포함)
