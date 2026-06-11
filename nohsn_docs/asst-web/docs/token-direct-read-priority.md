# 직접 토큰 조회 경로 정리 우선순위

## 개요

권한 전환 캐시 이슈를 정리하면서 `apiPlugin`과 `clearAdvisorSessionState()` 중심의 공통 경로는 정리되었지만, 일부 화면과 레거시 모듈에는 아직 토큰을 직접 읽는 코드가 남아 있습니다.

이 문서는 남은 경로를 영향도 기준으로 3단계로 나눈 후속 정리 메모입니다.

## 이미 정리된 기준 경로

- [`src/api/apiPlugin.ts`](../src/api/apiPlugin.ts)
  - 매 요청마다 최신 `accessToken`을 읽어 서비스별 헤더를 공통 적용합니다.
- [`src/utils/advisorSession.ts`](../src/utils/advisorSession.ts)
  - 로그아웃, 만료, 세션 전환 시 API, socket, router, store, profile cache를 한 번에 초기화합니다.
- [`src/api/modules/init.ts`](../src/api/modules/init.ts)
  - `EcpLogout()` 종료 시 공통 세션 정리로 귀결됩니다.
- [`src/utils/postMessage.ts`](../src/utils/postMessage.ts)
  - `expired` 수신 시 공통 세션 정리를 호출합니다.

## 1단계: 즉시 정리 필요

현재 권한 전환 이슈와 가장 가까우며, 실제 사용자 동작 중 직접 토큰 조회가 남아 있는 경로입니다.

### [`src/api/modules/request.ts`](../src/api/modules/request.ts)

- 쿠키에서 `accessToken`을 직접 읽어 `Authorization` 헤더를 주입합니다.
- refresh 처리와 재시도도 자체 axios 인스턴스에서 별도로 관리합니다.
- 세션 종료는 공통화됐지만, 요청 주입 경로는 여전히 `apiPlugin`을 우회합니다.

정리 방향:

- 가능하면 `apiPlugin` 기반 공통 클라이언트로 통합
- 최소한 토큰 조회/주입 로직만이라도 공통 헬퍼로 단일화

### [`src/common/interface/user.ts`](../src/common/interface/user.ts)

- `getCurrentUserServiceToken()`으로 조회 위치는 한 번 묶였지만, 여전히 `raw axios + X-auth-token 수동 주입` 구조입니다.
- `getUser()`, `getUserProfile()`, `getAdminsOfAgent()`, `getOrganizations()` 등 사용자/조직 조회가 이 경로를 사용합니다.
- 권한 판단과 사용자 관련 API 호출의 기준 토큰이 다시 분기될 여지가 있습니다.

정리 방향:

- `apiPlugin`의 `user` 또는 별도 공통 user client로 이관
- 적어도 헤더 생성은 공통 함수로 위임

## 2단계: 다음 단계 정리 권장

이번 이슈의 직접 원인이라기보다는, 세션 전환 이후 다른 화면에서 다시 문제를 만들 수 있는 독립 경로입니다.

### [`src/components/layout/HeaderActionBar/CounselingStatus.vue`](../src/components/layout/HeaderActionBar/CounselingStatus.vue)

- QA API 호출 시 `sessionStorage.getItem("accessToken")`으로 직접 헤더를 만듭니다.
- 컴포넌트 내부 `axios.post()`라 공통 API 정책과 분리되어 있습니다.

정리 방향:

- 공통 API 클라이언트 사용
- 최소한 최신 토큰 조회 헬퍼를 통해 헤더 주입

### [`src/view/advisor/components/ChatHistoryModal.vue`](../src/view/advisor/components/ChatHistoryModal.vue)

- 오디오 스트리밍 URL 생성 시 `sessionStorage.getItem("accessToken")` 또는 `VITE_ACCESS_TOKEN`을 직접 붙입니다.
- axios 호출은 아니지만, 세션 전환 이후 구 토큰이 URL에 남을 수 있는 독립 경로입니다.

정리 방향:

- 오디오 서비스 전용 URL 생성 헬퍼 도입
- 최신 토큰을 단일 source에서 읽도록 변경

### [`src/utils/AdvisorbotClient.ts`](../src/utils/AdvisorbotClient.ts)

- 소켓 연결 초기화 시 쿠키에서 토큰을 직접 읽어 `auth.token`에 넣습니다.
- 싱글톤 구조라 로그인 전환 시 초기화 타이밍에 따라 이전 문맥을 재사용할 가능성이 있습니다.

정리 방향:

- `init()` 시점 직접 조회를 공통 auth helper로 교체
- 세션 정리 시 `destroy()` 또는 재초기화 경로를 명시적으로 연결

### [`src/utils/postMessage.ts`](../src/utils/postMessage.ts)

- `expired`는 공통 세션 정리를 타지만, `refresh`는 아직 쿠키를 직접 갱신합니다.
- 외부 창 동기화 경로가 별도 토큰 갱신 source처럼 동작합니다.

정리 방향:

- refresh 토큰 반영도 공통 토큰 갱신 함수로 묶기
- 팝업 동기화와 실제 인증 source를 분리하지 않도록 정리

## 3단계: 레거시 또는 관찰 대상

현재 활성 영향도가 낮거나, 실제 사용 여부를 먼저 확인한 뒤 정리해도 되는 경로입니다.

### [`src/stores/modules/user.ts`](../src/stores/modules/user.ts)

- `accessToken` 필드가 persist 상태로 남아 있습니다.
- 현재 네트워크 계층의 기준 토큰은 주로 쿠키인데, 이 store도 토큰을 들고 있어 source of truth가 둘 이상입니다.
- 현재 확인된 실사용은 [`src/utils/postMessage.ts`](../src/utils/postMessage.ts) 의 팝업 전달용입니다.

정리 방향:

- 팝업 전달용으로만 필요하다면 역할을 명확히 분리
- 아니면 store에서 토큰 상태 자체를 제거 검토

### [`src/view/MenuComponent.vue`](../src/view/MenuComponent.vue)

- `sessionStorage.getItem("accessToken")`을 읽지만 현재 사용 흔적은 없습니다.
- 죽은 코드 가능성이 높습니다.

정리 방향:

- 사용처 확인 후 제거

### [`public/event/icAgentAPI.js`](../public/event/icAgentAPI.js)

- `sessionStorage.getItem("access_token")`을 직접 읽는 레거시 스크립트입니다.
- `public` 아래 독립 스크립트라 현재 앱 공통 세션 정리 범위와 분리될 가능성이 큽니다.

정리 방향:

- 실제 로드 여부 확인
- 사용 중이면 별도 정리 항목으로 승격

## 권장 적용 순서

1. `request.ts`와 `common/interface/user.ts`를 먼저 공통 토큰 경로로 통합합니다.
2. `CounselingStatus.vue`, `ChatHistoryModal.vue`, `AdvisorbotClient.ts`, `postMessage.ts`를 화면/소켓별 직접 조회 정리 대상으로 묶습니다.
3. `user` store 토큰, `MenuComponent.vue`, `public/event/icAgentAPI.js`는 사용 여부 확인 후 제거 또는 유지 판단합니다.

## 한 줄 결론

현재 구조는 `세션 종료`는 꽤 잘 공통화되었지만, `토큰 읽기와 주입`은 아직 일부 경로에서 직접 처리되고 있습니다. 후속 작업은 1단계 경로부터 정리하는 것이 가장 효과적입니다.
