# 리팩토링 후 기능 수정 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 리팩토링 완료 후 발견된 기능 결함 4건을 수정한다 — Race condition, 데드코드, 임시 requestId, 상담사 이름 미연동.

**Architecture:** 각 Task는 독립적이며 단일 파일 또는 최대 2개 파일만 수정한다. 실 API 연동이 필요한 고객 정보 하드코딩(`useChatMessageParser.ts`)은 백엔드 확인 후 별도 작업으로 분리한다.

**Tech Stack:** TypeScript, Vue 3, NestJS, Pinia

---

## 수정 범위 요약

| # | 파일 | 이슈 | 심각도 |
|---|------|------|--------|
| 1 | `useChatSocket.ts:19` | `forEach(async)` Race condition | 🔴 높음 |
| 2 | `useChatAssist.ts:146–192` | `handleAutoSelectKeyword` V1 데드코드 | 🟠 중간 |
| 3 | `admin.guard.ts:20` | `Math.random()` requestId | 🟠 중간 |
| 4 | `CustomerInfo.vue:56` | `consultantName: "-"` 임시 처리 | 🟠 중간 |
| — | `useChatMessageParser.ts:121` | 고객 정보 하드코딩 | ⏳ 별도 작업 (백엔드 확인 필요) |

---

## Task 1: `useChatSocket.ts` — `forEach(async)` Race condition 수정

**문제:** `requestAndJoin` 내부에서 `forEach(async ...)` 패턴을 사용하고 있어,
`forEach`는 Promise를 추적하지 않으므로 채널 구독이 완료되기 전에 함수가 반환된다.
`unsubscribeChannels`는 이미 `Promise.all`을 올바르게 사용 중이므로 같은 패턴으로 통일한다.

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatSocket.ts:18–31`

**Step 1: 현재 코드 확인**

```typescript
// 현재 (문제 있음):
const requestAndJoin = () => {
  socketChannels.forEach(async channel => {
    const response = await SubscribeAPI.instance.subscribeChannel(channel);
    ...
  });
};
```

**Step 2: `Promise.all` + `map`으로 교체**

`requestAndJoin` 함수를 아래와 같이 수정한다:

```typescript
const requestAndJoin = async () => {
  await Promise.all(
    socketChannels.map(async channel => {
      const response = await SubscribeAPI.instance.subscribeChannel(channel);
      if (response && response.data?.success) {
        const { room } = response.data.socketConnection;
        joinRoom(room);
        if (!subscribedRooms.value.includes(room)) {
          subscribedRooms.value.push(room);
        }
      } else {
        console.warn(`채널 구독 및 룸 참가 실패: ${channel}`);
      }
    })
  );
};
```

`socket.once("connect", requestAndJoin)` 호출부는 변경 불필요 — `once` 콜백은 async 함수를 허용한다.

**Step 3: 타입 체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit 2>&1 | grep "useChatSocket"
```
Expected: 에러 없음

**Step 4: 커밋**

```bash
git add asst-web/src/view/advisor/components/chat/composables/useChatSocket.ts
git commit -m "fix: 채널 구독 forEach(async) → Promise.all 교체로 Race condition 수정"
```

---

## Task 2: `useChatAssist.ts` — `handleAutoSelectKeyword` V1 데드코드 제거

**문제:** `handleAutoSelectKeyword` (V1) 함수는 두 가지 이유로 완전한 데드코드다:
1. 내부의 `fetchKeywordData()` 호출이 주석 처리되어 있어 함수 자체가 아무것도 하지 않는다.
2. `index.vue`에서 구조분해로 가져오지만 실제 호출되는 곳이 없다.
   (`handleAutoSelectKeywordV2`가 실제 사용 중인 버전)

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatAssist.ts:146–192, 773`
- Modify: `asst-web/src/view/advisor/components/chat/index.vue:931`

**Step 1: `useChatAssist.ts`에서 V1 함수 제거**

`useChatAssist.ts`에서 아래 블록 전체를 삭제:

```typescript
// 삭제 대상 (146~192줄):
// 키워드 자동 선택 공통 함수 (자동 선택 제거 - 데이터만 캐싱)
const handleAutoSelectKeyword = async (firstKeyword: string, intentId: string, customerUtterance: string) => {
  ...
};
```

return 객체(~773줄)에서도 제거:
```typescript
// 삭제:
handleAutoSelectKeyword,
```

**Step 2: `index.vue`에서 구조분해 제거**

`index.vue:931`에서 `handleAutoSelectKeyword,` 한 줄 삭제:

```typescript
// 수정 후:
const {
  summaryLoading,
  handleAssistStream,
  handleAutoSelectKeywordV2,
  handleSearchQueryClick,
  executeAutoSelection,
  abortAllStreams
} = useChatAssist({ ... });
```

**Step 3: 타입 체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit 2>&1 | grep -E "useChatAssist|index.vue"
```
Expected: 에러 없음

**Step 4: 커밋**

```bash
git add asst-web/src/view/advisor/components/chat/composables/useChatAssist.ts \
        asst-web/src/view/advisor/components/chat/index.vue
git commit -m "refactor: handleAutoSelectKeyword V1 데드코드 제거 (V2로 대체됨)"
```

---

## Task 3: `admin.guard.ts` — `Math.random()` requestId 수정

**문제:** `Math.random().toString(36).substring(7)`은 길이가 불규칙하고 중복 가능성이 있어
로그 추적 ID로 부적합하다. 외부 uuid 라이브러리 없이 `Date.now() + 카운터`로 유일성을 보장한다.

**Files:**
- Modify: `asst-service/src/common/guards/admin.guard.ts:20`

**Step 1: 수정**

`AdminGuard` 클래스에 static 카운터를 추가하고 requestId 생성 로직 교체:

```typescript
@Injectable()
export class AdminGuard implements CanActivate {
  private static counter = 0;

  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<RequestWithUserRole>();
    const userRole = request.userRole;
    const requestId = `${Date.now().toString(36)}-${(++AdminGuard.counter).toString(36)}`;
    ...
```

**Step 2: lint 실행**

```bash
cd asst-service && npm run lint 2>&1 | grep "admin.guard"
```
Expected: 에러 없음

**Step 3: 커밋**

```bash
git add asst-service/src/common/guards/admin.guard.ts
git commit -m "fix: AdminGuard requestId를 Math.random에서 timestamp+counter 방식으로 교체"
```

---

## Task 4: `CustomerInfo.vue` — `consultantName` API 연동

**문제:** `consultantName: "-"`로 하드코딩되어 이전 상담 이력에 상담사 이름이 항상 "-"로 표시된다.
`CustomerInfo.vue`는 현재 로그인한 상담원의 이전 통화 이력만 보여주는 컴포넌트이므로,
`userProfileStore.agent?.name`으로 간단히 해결된다.

근거: `callHistoryStore`의 API 조회 파라미터가 `agent_id: userProfileStore.agent.cc_cti_id`로 고정되어 있어, 조회 결과는 항상 현재 상담원의 통화만 포함된다.

**Files:**
- Modify: `asst-web/src/components/layout/HeaderActionBar/CustomerInfo.vue`

**Step 1: `useUserProfileStore` import 추가**

파일 상단 script 블록에 추가:
```typescript
import { useUserProfileStore } from "@/stores/modules/userProfile";
```

**Step 2: store 인스턴스 생성**

`useCallHistoryStore()` 선언 아래에 추가:
```typescript
const userProfileStore = useUserProfileStore();
```

**Step 3: `consultantName` 교체**

```typescript
// 수정 전:
consultantName: "-", // API에서 상담사 정보가 없어서 임시로 "-"

// 수정 후:
consultantName: userProfileStore.agent?.name || "-",
```

**Step 4: 타입 체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit 2>&1 | grep "CustomerInfo"
```
Expected: 에러 없음

**Step 5: 커밋**

```bash
git add asst-web/src/components/layout/HeaderActionBar/CustomerInfo.vue
git commit -m "fix: CustomerInfo 상담사 이름을 userProfileStore에서 조회하도록 수정"
```

---

## 보류 항목: `useChatMessageParser.ts` 고객 정보 하드코딩

```typescript
// useChatMessageParser.ts:120–129
useCustomerStore().setCustomer({
  id: "-",
  name: "-",
  phoneNumber: formatPhoneNumber(...),
  email: "-",
  location: "-",
  callType: "-",
});
```

**보류 이유:** `id`, `name`, `email`, `location`, `callType`은 소켓 이벤트 메시지에 포함되지 않는다.
실 구현을 위해서는:
- 백엔드에서 `:call:events` 소켓 메시지에 고객 정보 필드 추가, 또는
- 프론트에서 전화번호 기반 고객 조회 API 호출 추가

→ **백엔드와 소켓 이벤트 스펙 협의 후 별도 작업으로 진행**

---

## 검증 체크리스트

```
□ Task 1: 소켓 연결 후 채널 구독이 모두 완료됨 확인 (실제 통화 테스트)
□ Task 2: 빌드 성공 + 기존 자동선택(V2) 기능 정상 동작 확인
□ Task 3: 관리자 API 호출 시 로그에 requestId가 고유하게 찍히는지 확인
□ Task 4: 이전 상담 내역 팝오버에서 상담사 이름이 올바르게 표시되는지 확인
```
