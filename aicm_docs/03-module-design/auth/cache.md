# Auth 캐시 전략

> 참조: [08-cache-architecture](../../02-architecture/08-cache-architecture.md) · [03-auth-architecture §9](../../02-architecture/03-auth-architecture.md) · [events.md](./events.md) · [rules.md](./rules.md)

---

## 1. 캐시 개요

| # | 캐시 대상 | 전략 | TTL | 무효화 |
|---|----------|------|-----|--------|
| 1 | 유효 역할 | cache-aside | 5분 | 이벤트 기반 즉시 삭제 |
| 2 | 게시판 접근 가능 ID | cache-aside | 5분 | 이벤트 기반 즉시 삭제 |
| 3 | 사용자 소속 팀 (OrgProvider) | cache-aside | 10분 | 이벤트 기반 즉시 삭제 |

> Refresh Token 저장, Access Token 블랙리스트 등 토큰 생명주기 관리는 외부 인증 서비스 소관.

---

## 2. 캐시 상세

### 2.1 유효 역할 캐시

#### 기본 정보

| 항목 | 값 |
|------|---|
| 전략 | cache-aside |
| 키 패턴 | `{tenant_id}:cache:auth:effective-roles:{user_id}` |
| TTL | 300초 (5분) |
| 직렬화 | JSON (Role ID + name 배열) |

#### 무효화

| 트리거 이벤트 | BR | 동작 |
|-------------|---|------|
| `acl.user_role.updated` | BR-ACL-044 | 해당 userId의 키 삭제 |
| `acl.team.members_updated` | BR-ACL-044 | 추가/제거된 userId의 키 삭제 |
| `acl.role.status_changed` | BR-ACL-008, BR-ACL-009 | 해당 Role 보유 전체 사용자의 키 삭제 (RDB 조회) |
| `acl.role.permissions_updated` | BR-ACL-044 | 해당 Role 보유 전체 사용자의 키 삭제 (RDB 조회) |
| `acl.team.status_changed` | BR-ACL-014 | 해당 Team(+하위) 소속 전체 사용자의 키 삭제 (RDB 조회) |

#### Warm-up / Fallback

| 항목 | 값 |
|------|---|
| Warm-up | lazy-load (최초 요청 시 DB 조회 후 캐싱) |
| Fallback | DB 직접 조회 (Redis 장애 시 캐시 스킵) |

---

### 2.2 게시판 접근 가능 ID 캐시

#### 기본 정보

| 항목 | 값 |
|------|---|
| 전략 | cache-aside |
| 키 패턴 | `{tenant_id}:cache:auth:accessible-boards:{user_id}:{action}` |
| TTL | 300초 (5분) |
| 직렬화 | JSON (boardId 배열) |

#### 무효화

| 트리거 이벤트 | BR | 동작 |
|-------------|---|------|
| `acl.role.permissions_updated` | BR-ACL-044 | 해당 Role 보유 사용자의 `accessible-boards:*` 키 삭제 |
| `acl.user_role.updated` | BR-ACL-044 | 해당 userId의 `accessible-boards:*` 키 삭제 |
| `acl.team.members_updated` | BR-ACL-044 | 변경된 userId의 `accessible-boards:*` 키 삭제 |
| `board.permission.updated` | — | 해당 Role 보유 사용자의 `accessible-boards:*` 키 삭제 |

#### Warm-up / Fallback

| 항목 | 값 |
|------|---|
| Warm-up | lazy-load |
| Fallback | DB 직접 조회 |

---

### 2.3 사용자 소속 팀 캐시 (OrgProvider)

#### 기본 정보

| 항목 | 값 |
|------|---|
| 전략 | cache-aside |
| 키 패턴 | `{tenant_id}:cache:auth:org-ancestors:{user_id}` |
| TTL | 600초 (10분) |
| 직렬화 | JSON (teamId 배열 — 소속 팀 + 상위 팀 전체 체인) |

#### 무효화

| 트리거 이벤트 | BR | 동작 |
|-------------|---|------|
| `acl.team.members_updated` | BR-ACL-044 | 변경된 userId의 키 삭제 |
| Team 계층 변경 (parent_id) | BR-ACL-044 | 해당 팀 및 하위 팀 소속 전체 사용자의 키 삭제 (RDB 조회) |

#### Warm-up / Fallback

| 항목 | 값 |
|------|---|
| Warm-up | lazy-load |
| Fallback | DB 직접 조회 (RDB Team 재귀) 또는 UserService API 직접 호출 |

---

---

## 3. 키 패턴 요약

| 키 패턴 | TTL | 용도 |
|--------|-----|------|
| `{tenant_id}:cache:auth:effective-roles:{user_id}` | 5분 | 유효 역할 합산 결과 |
| `{tenant_id}:cache:auth:accessible-boards:{user_id}:{action}` | 5분 | 접근 가능 게시판 ID 목록 |
| `{tenant_id}:cache:auth:org-ancestors:{user_id}` | 10분 | 소속 팀 + 상위 팀 ID 목록 |

### 캐시 미적용 구간

| 구간 | 사유 |
|------|------|
| DocumentRestriction 판정 | 제한 문서 극소수, 실시간 반영 중요 (BR-ACL-045) |
| AdminPermission 판정 | 보유자 수가 상대적으로 적음, 단순 인덱스 스캔 |
| 검색용 제한 문서 ID 조회 | 극소수 결과, 캐시 이점 미미 |
