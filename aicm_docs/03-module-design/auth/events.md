# Auth 이벤트 및 부수효과

> 참조: [05-async-event-architecture](../../02-architecture/05-async-event-architecture.md) · [02-module-architecture](../../02-architecture/02-module-architecture.md) · [rules.md](./rules.md)

---

## 1. 발행 이벤트

### 1.1 Important 티어 — BullMQ

권한 변경은 검색 가시성, 캐시 무효화, 알림 등 다수 소비자에게 영향을 주므로 BullMQ로 보장한다.

**큐 이름**: `acl.events`

| 이벤트명 | 트리거 | BR | 소비자 |
|----------|--------|---|--------|
| `acl.role.permissions_updated` | Role의 BoardPermission 또는 AdminPermission 변경 | BR-ACL-044 | 캐시 무효화, 검색 가시성 재평가, 알림 |
| `acl.role.status_changed` | Role 비활성화/잠금/활성화 | BR-ACL-008, BR-ACL-009 | 캐시 무효화, 영향 사용자 알림 |
| `acl.team.members_updated` | Team 멤버 추가/제거 | BR-ACL-044 | 유효 역할 재계산, 캐시 무효화 |
| `acl.team.status_changed` | Team 비활성화/활성화 | BR-ACL-014 | 유효 역할 재계산, 캐시 무효화 |
| `acl.user_role.updated` | 사용자 직접 Role 할당/해제 | BR-ACL-044 | 캐시 무효화, 알림 |
| `acl.board_permission.updated` | 게시판별 권한 변경 | BR-ACL-044 | 검색 가시성 재평가, 캐시 무효화 |
| `acl.restriction.updated` | 문서 접근 제한 설정/해제/화이트리스트 변경 | BR-ACL-026 | 검색 가시성 재평가 |

#### 페이로드

```typescript
interface AclRolePermissionsUpdatedPayload {
  schemaVersion: 1;
  roleId: string;
  changedPermissions: {
    type: 'board' | 'admin';
    action: 'added' | 'removed';
    boardId?: string;          // type=board일 때
    boardAction?: BoardAction; // type=board일 때
    permissionKey?: string;    // type=admin일 때
  }[];
  affectedUserCount: number;
  traceId: string;
}

interface AclRoleStatusChangedPayload {
  schemaVersion: 1;
  roleId: string;
  previousStatus: 'active' | 'inactive' | 'locked';
  newStatus: 'active' | 'inactive' | 'locked';
  reason?: string;  // locked일 때 잠금 사유
  traceId: string;
}

interface AclTeamMembersUpdatedPayload {
  schemaVersion: 1;
  teamId: string;
  addedUserIds: string[];
  removedUserIds: string[];
  traceId: string;
}

interface AclTeamStatusChangedPayload {
  schemaVersion: 1;
  teamId: string;
  previousStatus: 'active' | 'inactive';
  newStatus: 'active' | 'inactive';
  traceId: string;
}

interface AclUserRoleUpdatedPayload {
  schemaVersion: 1;
  userId: string;
  roleId: string;
  action: 'assigned' | 'revoked';
  traceId: string;
}

interface AclBoardPermissionUpdatedPayload {
  schemaVersion: 1;
  roleId: string;
  boardId: string;
  changes: {
    action: 'added' | 'removed';
    boardAction: BoardAction;
  }[];
  traceId: string;
}

interface AclRestrictionUpdatedPayload {
  schemaVersion: 1;
  documentId: string;
  restricted: boolean;
  changes: {
    action: 'added' | 'removed';
    subjectType: 'USER' | 'TEAM';
    subjectId: string;
    boardAction: BoardAction;
  }[];
  traceId: string;
}
```

#### 재시도 정책

| 항목 | 값 |
|------|---|
| 최대 재시도 | 3회 |
| 백오프 | 지수 (5s → 10s → 20s) |
| DLQ | `acl.events-dlq` |
| 멱등 키 | `{event_name}:{entityId}` |

### 1.2 Normal 티어 — EventBus

> 로그인/로그아웃/토큰 폐기는 외부 인증 서비스 소관이므로 KMS에서 이벤트를 발행하지 않는다.

해당 없음.

---

## 2. 소비 이벤트

| 이벤트명 | 발행 모듈 | 처리 |
|----------|----------|------|
| `acl.role.permissions_updated` | 자체 (AuthModule) | 해당 Role 보유 사용자의 권한 캐시 무효화 |
| `acl.role.status_changed` | 자체 (AuthModule) | 해당 Role 보유 사용자의 권한 캐시 무효화 |
| `acl.team.members_updated` | 자체 (AuthModule) | 변경된 멤버의 권한 캐시 무효화 |
| `acl.team.status_changed` | 자체 (AuthModule) | 해당 Team 소속 사용자의 권한 캐시 무효화 |
| `acl.user_role.updated` | 자체 (AuthModule) | 해당 사용자의 권한 캐시 무효화 |
| `board.permission.updated` | BoardModule | 해당 Role 보유 사용자의 `accessible-boards` 캐시 무효화 |
