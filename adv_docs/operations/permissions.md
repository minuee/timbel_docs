# 권한 관리

> Advisor 의 역할(role) 기반 접근 제어 + 메뉴 권한 + 동적 라우터.
> 백엔드 권한 시스템은 **미완성 상태**라는 점이 가장 중요한 인계 포인트.

---

## 1. 역할(Role) 종류

| Role | 설명 | 화면 분기 |
|------|------|----------|
| **`AGENT`** | 일반 상담원 | `AgentComponent` |
| **`ADMIN`** | 관리자 (상담원 모니터링 + 코칭 발송) | `AdminComponent` |
| **`VIEWER`** | 읽기 전용 관찰자 | AdminComponent의 `isViewer=true` 변형 |

화면 분기 위치: [view/advisor/consultant/index.vue:10-11](../../asst-web/src/view/advisor/consultant/index.vue#L10-L11), [:72](../../asst-web/src/view/advisor/consultant/index.vue#L72)

```typescript
resolvedRole.value = userResponse.agent?.role === "AGENT" ? "agent" : "admin";
```

→ `'AGENT'` 가 아니면 모두 `'admin'` 으로 fallback. ADMIN vs VIEWER 구분은 별도 플래그.

---

## 2. 백엔드 권한 시스템 (⚠️ 미완성)

### 2-1. 정의되어 있는 것

#### `AdminGuard` ([admin.guard.ts](../../asst-service/src/common/guards/admin.guard.ts))

```typescript
@Injectable()
export class AdminGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest();
    const userRole = request.userRole;

    if (!userRole) throw new HttpException('사용자 정보를 찾을 수 없습니다.', 401);
    if (userRole !== 'ADMIN') throw new HttpException('ADMIN 권한이 필요합니다.', 403);
    return true;
  }
}
```

#### `@AdminOnly()` 데코레이터 ([admin.decorator.ts](../../asst-service/src/common/decorators/admin.decorator.ts))

```typescript
export const AdminOnly = () => applyDecorators(Admin(), UseGuards(AdminGuard));
```

#### `@UserRole()`, `@CurrentUser()` 파라미터 데코레이터 ([user-role.decorator.ts](../../asst-service/src/common/decorators/user-role.decorator.ts))

```typescript
@Get()
async getData(@UserRole() role: string) { /* ... */ }
```

### 2-2. 빠진 것 (⚠️ 핵심 이슈)

**`AuthMiddleware` 가 `req.userRole` 을 부착하지 않음**:

[auth.middleware.ts](../../asst-service/src/common/middleware/auth.middleware.ts) 의 코드:
- ✅ `req.token` 부착
- ✅ `req.authHeader` 부착
- ✅ `req.dbConnection` 부착
- ❌ `req.userRole` 부착 안 함

**결과**:
- `AdminGuard` 가 적용된 엔드포인트는 **모두 401 응답** (userRole이 항상 undefined)
- 실제로 `AdminGuard` 를 사용하는 컨트롤러가 **0개** (grep 결과 확인됨)
- → 백엔드는 사실상 **role 검증을 안 함**

### 2-3. 현재 보안 상태

| 영역 | 권한 검증 |
|------|-----------|
| 백엔드 API | ❌ 없음 (인증 토큰만 검증) |
| 프론트엔드 UI | ✅ role 기반 화면 분기 |
| 코칭 발송 등 admin 전용 액션 | ❌ 백엔드 미검증 (UI에서만 가려짐) |

→ **결정적 문제**: 일반 상담원이 직접 API 호출하면 admin 전용 액션 가능 (예: 코칭 메시지 발송).

---

## 3. 인계 시 권장 보강 작업

### 3-1. `AuthMiddleware` 에 `userRole` 부착

```typescript
// auth.middleware.ts (수정안)
const tenantConfig = await this.tenantConfigService.getTenantConfig(token);
// USER_HOST 응답에서 role 추출
reqWithAuth.userRole = tenantConfig.user_info?.role; // 응답 형식 확인 필요
```

### 3-2. admin 전용 컨트롤러에 `@AdminOnly()` 적용

```typescript
@Post()
@AdminOnly()  // ← 추가
async createCoaching(@Body() dto: CreateCoachingDto) { ... }
```

대상 후보:
- `CoachingController` (코칭 발송)
- `NoticeController` (공지 생성)
- 관리자 화면 전용 통계 조회

### 3-3. ADMIN vs VIEWER 구분

VIEWER는 ADMIN과 같은 화면을 보지만 액션(코칭 발송, 공지 작성)은 차단해야 함:

- 새 가드 `@AdminOrViewer()` (read-only) vs `@AdminWriteOnly()`
- 또는 컨트롤러 내부에서 role 분기

---

## 4. 프론트엔드 권한 시스템

### 4-1. role 분기

[view/advisor/consultant/index.vue](../../asst-web/src/view/advisor/consultant/index.vue):

```typescript
resolvedRole.value = userResponse.agent?.role === "AGENT" ? "agent" : "admin";
```

[view/advisor/agent/index.vue](../../asst-web/src/view/advisor/agent/index.vue) 등 자식 컴포넌트:

```typescript
:idAdmin="isAdmin"
:isViewer="isViewer"
```

→ 컴포넌트 prop으로 전달되어 UI 분기.

### 4-2. 컴포저블에서 role 사용

[useChatMessageParser.ts](../../asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts) — `isAdmin.value` / `isViewer.value` 분기:

- `call:events start` 처리:
  - 일반 상담원: 본인 상태 → `ON_CALL`
  - 관리자/뷰어: `userList` 의 해당 상담원 상태 업데이트
- 채팅 액션 (코칭 추가 등):
  - 일반 상담원: 다른 동작
  - 관리자: 코칭 발송 가능

### 4-3. Redis 채널 구독 차이

[chat/index.vue:1213-1223](../../asst-web/src/view/advisor/components/chat/index.vue#L1213-L1223):

```typescript
const socketChannels = isAdmin.value
  ? [
      getRedisKey(tenantId, agentId, "nlp"),
      getRedisKey(tenantId, agentId, "partial"),
      getRedisKey(tenantId, agentId, "db")
    ]
  : [
      getRedisKey(tenantId, agentId, "events"),   // ← agent만 events 구독
      getRedisKey(tenantId, agentId, "nlp"),
      getRedisKey(tenantId, agentId, "partial"),
      getRedisKey(tenantId, agentId, "db")
    ];
```

→ 관리자는 자신이 통화하지 않으므로 `call:events` 구독 X.

---

## 5. 메뉴 권한 (동적 라우터)

### 5-1. 동적 라우터 로딩

[routers/index.ts:48-](../../asst-web/src/routers/index.ts#L48):

```typescript
router.beforeEach(async (to, from, next) => {
  // ...
  await initDynamicRouter();  // 사용자별 메뉴 권한 로드
});
```

### 5-2. `initDynamicRouter`

[routers/modules/dynamicRouter.ts](../../asst-web/src/routers/modules/dynamicRouter.ts):

```typescript
export const initDynamicRouter = async () => {
  const authStore = useAuthStore();
  await authStore.getAuthMenuList();  // 메뉴 권한 조회
  if (!authStore.authMenuListGet.length) return Promise.reject("No permission");

  authStore.flatMenuListGet.forEach(item => {
    // 권한이 있는 메뉴만 동적 라우터로 추가
    router.addRoute(item as RouteRecordRaw);
  });
};
```

### 5-3. 메뉴 권한 조회 (⚠️ Mock 사용 중)

[stores/modules/auth.ts:84-93](../../asst-web/src/stores/modules/auth.ts#L84-L93):

```typescript
async getAuthMenuList() {
  // API 메뉴구성
  // const { data } = await getAuthMenuListApi(userStore.groupId);  // ← 주석 처리

  // 목업 JSON 메뉴구성
  const { data } = await getAuthMenuListMockup();  // ← 현재 사용 중
}
```

⚠️ **현재 메뉴 권한이 mockup 데이터** — 실제 권한 API와 연동 필요.

### 5-4. 메뉴 메타 정보

[routers/index.ts:19-33](../../asst-web/src/routers/index.ts#L19-L33):

```typescript
@param meta.icon            메뉴 아이콘
@param meta.title           라우터 제목
@param meta.activeMenu      세부 페이지 시 강조할 메뉴
@param meta.isLink          외부 링크 주소
@param meta.isHide          메뉴 바에서 숨김 (예: 상세 페이지)
@param meta.isFull          전체 화면 (예: 대시보드)
@param meta.isAffix         탭 고정
@param meta.isKeepAlive     컴포넌트 캐싱
@param meta.isReadonly      현재 메뉴 권한 (읽기 전용)
```

→ 메뉴마다 `isReadonly` 플래그가 있지만 활용이 일관적인지 확인 필요.

---

## 6. 권한 매트릭스

### 6-1. 화면별 접근

| 화면 | AGENT | ADMIN | VIEWER |
|------|-------|-------|--------|
| 상담사 대시보드 | ✅ 본인 | ✅ 본인 + 모니터링 | ✅ 모니터링만 |
| 채팅 화면 | ✅ 본인 통화 | ✅ 선택한 상담원 통화 보기 | ✅ 보기만 |
| 코칭 작성 | ❌ | ✅ | ❌ |
| 공지 작성 | ❌ | ✅ | ❌ |
| 통화 통계 (대시보드) | ✅ 본인 | ✅ 전체 | ✅ 전체 |
| 사용자/그룹 관리 | ❌ | ✅ | ❌ |

### 6-2. API 호출별 권한 (이상적)

| 엔드포인트 | 일반 권한 |
|-----------|----------|
| `GET /agents/me` | 모두 |
| `GET /agents/*` (다른 상담원) | ADMIN, VIEWER |
| `POST /coachings` | ADMIN (현재 미검증) |
| `POST /notices` | ADMIN (현재 미검증) |
| `POST /summary` | 통화 소유자 또는 ADMIN |
| `GET /callstat/calls` | 모두 (본인 통화로 필터) |
| `GET /callstat/calls?agent_id=X` | ADMIN, VIEWER (다른 사람 통화 조회) |

→ 현재는 백엔드에서 강제하지 않음 (4-1, 4-2 참조).

---

## 7. 인계 시 주의 / 보강 우선순위

### 🔴 High (보안 위험)

1. **`AuthMiddleware` 에 `userRole` 부착** — `AdminGuard` 가 실제로 동작하도록
2. **admin 전용 API에 `@AdminOnly()` 적용** — 코칭/공지/관리자 통계
3. **메뉴 권한 API 실제 연동** — 현재 mock 사용 중

### 🟡 Medium (정합성)

4. **VIEWER 권한 명확화** — read-only 가드 추가
5. **테넌트 격리** — agent_id 가 다른 테넌트 사람이 아닌지 검증

### 🟢 Low (개선)

6. **`AdminGuard` 의 console.log 다수** — TraceLogger로 일원화
7. **메뉴 권한 변경 시 즉시 반영** (현재는 새로고침 필요)

---

## 8. 디버깅

| 확인 사항 | 방법 |
|----------|------|
| 현재 사용자 role | Vue DevTools → `userProfileStore.agent.role` |
| 활성 라우터 목록 | `router.getRoutes()` 콘솔 |
| 메뉴 권한 로드 결과 | `useAuthStore().authMenuListGet` |
| 백엔드 role 부착 여부 | asst-service 로그에서 `userRole` 검색 (현재 안 보임) |

---

## 9. 자주 발생하는 이슈

| 증상 | 원인 후보 |
|------|----------|
| 메뉴가 안 보임 | mock 데이터의 권한 누락. `getAuthMenuListMockup()` 응답 확인 |
| 라우터 가드 무한 redirect | `initDynamicRouter` 실패 → ERROR_URL → beforeEach 재진입 |
| ADMIN 화면이 안 뜸 | `userResponse.agent.role` 값 확인 |
| 코칭 발송이 일반 상담원에게서도 됨 | 정상 (현재 백엔드 미검증). 보강 필요. |
