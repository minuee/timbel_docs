# 리뉴얼(UI v2) 작업 기록

> 이 파일은 **화면 리뉴얼(v1/v2 병행)** 관련 설계·진행 내용 전용.
> 일반 대화/분석 기록은 `CLAUDE-history.old.md` 에.

## 2026-06-16

### 1. 리뉴얼 방향 확정 — v1/v2 빌드 분기 구조
- **배경:** 기획자가 신규 화면을 실제 배포(`http://13.209.195.192:32010/asst-web-ui/#/agent/dashboard`)로 공유. 이를 시안으로 로컬 소스에 v2 구현.
- **운영 방식(확정, A안):**
  - 기존 URL 구조는 그대로 유지 = **v1**. **v2는 신규 URL만 추가** 생성.
  - 웹팩 **엔트리(main) 교체**로 v1/v2 빌드 분기. 빌드하는 사람만 어느 버전 배포할지 결정.
  - **브라우저에서 두 버전 동시 노출 불필요** → 한 빌드 = 한 버전.
- **재활용 원칙:** View 레이어만 교체. **api/service/store 는 그대로 재활용**, v2 신규 화면에 필요한 것만 신규 추가.
- **모듈페더레이션 주의:** 이 앱(`advisor_app`)은 `host_app` 에 `AdvisorConsultantComponent`/`AdvisorManagementUser` 를 expose 중(`webpack.config.js:88~97`). v2 신규 화면은 expose 하지 않으면 **호스트 앱 영향 없음**.

### 2. 제안 구조 (중복 제거형 엔트리 분기) — 구현 대기
- **핵심:** `main.ts` 통째 복붙(`main_v2.ts`) 금지. 전역 플러그인 등록 덩어리(element-plus/pinia/router/i18n/devextreme/전역컴포넌트/전역스타일)는 v1·v2 공통(95%)이라 중복 시 동기화 지옥.
- **디렉터리 계획:**
  ```
  src/
    bootstrap.ts      [신규] 공통 셋업 함수. 현 main.ts 내용 전부 이동. export function bootstrap(router){...mount}
    main.ts           [v1] bootstrap(routerV1) — 얇아짐
    main_v2.ts        [v2] bootstrap(routerV2) — 얇음
    routers/
      index.ts        v1 기존 (그대로)
      index.v2.ts     [신규] v2 전용 신규 URL
    view/      ...     v1 기존 (그대로)
    view-v2/   ...     [신규] v2 신규 화면 (api/service/store 재활용)
  ```
- **웹팩 분기(`webpack.config.js`):** `const uiVersion = process.env.UI_VERSION || "v1"; const entry = uiVersion==="v2" ? "src/main_v2.ts" : "src/main.ts";`
- **npm 스크립트:** `build:prd`(v1) / `build:prd:v2`(`UI_VERSION=v2 MODE=prd`) 식 추가.
- **현 상태:** 구조 설계 사용자 OK 대기. → OK 시 ① bootstrap 추출 + 골격 생성 + 웹팩 분기, ② Playwright MCP 연결 후 v2 시안 분석 → 현재 소스 대비 수정 규모 검토 → `view-v2/` 실구현.

### 3. 현재 빌드 구조 (사실 정리)
- 웹팩, 단일 엔트리 `entry: src/main.ts`(`webpack.config.js:19`). vite 아님(빌드는 webpack, deps에 `@originjs/vite-plugin-federation` 있으나 미사용).
- env: `.env.${MODE}` → DefinePlugin 주입. MODE 종류: development/local/5f.local/test/ncp/aws/dev/prd.
- 스택: Vue3 + pinia + vue-router + element-plus(+ devextreme, vue-flow, toast/tiptap editor, quasar 일부 비활성).

### 4. v2 시안 1차 훑기 (Playwright MCP) — 구조만 파악 후 **홀딩**
- **배경:** 시안이 아직 **확정 아님(추정)** + 기획문서 없이 데모 URL만 받은 상태 → 정식 분석은 다음으로 미룸. 오늘은 전체 구조만 캡쳐.
- **캡쳐물:** `asst-web/v2_image/v2-{dashboard,history,coaching,notice}.png` (4장, 다음 정식 분석 참고용). ⚠️ 앞으로 Playwright 캡쳐는 **전부 `v2_image/` 디렉토리에 저장**.
- **시안 정체:** 상담사(`/agent`) 워크스페이스 리뉴얼. 핀테크풍(다크 사이드바 + 라이트 메인, 퍼플 포인트, 카드 기반).
- **공통 레이아웃(3단):** ①좌측 다크 사이드바(ECP로고/Search/`AICC 플랫폼`메뉴그룹/하단 UI설정·홍길동) ②상단 **멀티탭 바**(열린 화면 탭 누적, ×닫기, 우측 ⋮) ③헤더(breadcrumb + 타이틀 + 우측 `홍길동|●대기중`+알림벨②).
- **4개 라우트(확인됨):**
  - `/agent/dashboard` — 긴급공지 배너 + 카드 7종(코칭/오늘통화/이슈어Top5/FAQ Top5/최근지식문서/오늘KPI)
  - `/agent/history` — 탭(전체/코칭받음/북마크) + 통화 리스트, **행 클릭 시 인라인 상세 펼침**
  - `/agent/coaching` — 탭(받은/요청한/완료) + 코칭 카드(라이브코칭/SOS응답, 수신·완료 뱃지)
  - `/agent/notice` — 공지 리스트(긴급/일반/정책/점검 라벨 + 좌측 컬러바)
- **현재 소스(v1) 대비:** 현 상담사 화면은 `src/view/advisor/agent/`(`Dashboard.vue`, `index.vue`, `composables/useKnowledgeExpand.ts`). 라우트는 `staticRouter.ts`엔 없음 → **`dynamicRouter.ts`(동적 등록) 미확인**.
- **아직 안 본 것:** 사이드바 `AICC 플랫폼` 하위메뉴/Search/UI설정 등 상담사 외 영역, 각 화면 인터랙션 상세, dynamicRouter.
- **다음 정식 분석 시작점:** 시안 확정 여부 확인 → (확정 시) 4화면 상세 인터랙션/데이터 단위 분해 + dynamicRouter 비교 → bootstrap 분기 골격(2번 계획) 착수.

---

## 2026-06-16 — 상담내용 헤더 VOC 인라인 노출 + VOC 상태 재진입 초기화

### 요청
1. 상담내용 헤더(왼쪽 패널)를 `docs/voc-real.png`처럼 변경 — `💬 상담내용` 옆에 `● VOC {긍정/중립/부정}` + `감정 ⋯ 0.00`
2. 대화 클리핑/추천태그 버튼 숨김(소스 유지, 추후 부활)
3. 점수는 감정/민원위험/이탈징후 3값 평균을 소수점 2자리(`0.00`)
4. `VOC 낮음` → `VOC 긍정/중립/부정`(라벨에서 "적" 제거), 앞 원형 점 색은 기존(녹/회/빨) 유지
5. 좌우 네비 제거, 최신값(`latestItem`)만 노출, **데이터 없으면 미노출**
6. **고객 VOC 탐지(`CustomerVocPanel`)는 비교용으로 그대로 유지** — 나중에 감춤
7. VOC 히스토리 잔존 버그: 콜 수신 후 다른 페이지 갔다 재진입 시 채팅은 초기화되는데 VOC만 이전 내역 남음

### 작업 내용
- **`components/chat/index.vue`**
  - 헤더 `대화 클리핑/추천태그` 버튼 그룹 `v-if="false"`(삭제 X, 숨김만)
  - `isClippingActive` 기본값 `true`→`false` (말풍선 클립 아이콘도 숨김)
  - 헤더에 인라인 VOC 추가: `v-if="vocLatest"`(데이터 있을 때만). `adv-voc-badge`(점+라벨) + `adv-voc-score`(감정 ⋯ 값)
  - script: `useVocStore` import, `vocLatest`/`VOC_SENTIMENT_META`(부정#ef4444/중립#94a3b8/긍정#22c55e)/`vocSentimentMeta`/`vocAverage`(3값 평균 `toFixed(2)`) computed 추가
  - scoped style: `.adv-voc-badge`, `.adv-voc-score`(점선 리더 `border-bottom: dotted`) 추가
- **`agent/index.vue`**
  - `useVocStore` import + 인스턴스, `onUnmounted`에서 `vocStore.clear()` 호출 → 페이지 이탈 시 VOC 전역상태 초기화(채팅과 동일 동작). 재진입 시 깨끗.
  - `CustomerVocPanel`은 **변경 없음(그대로 노출)** — 비교용, 추후 숨김 예정

### 원인 분석(VOC 잔존)
- `chatContent`는 컴포넌트 로컬 ref라 재마운트 시 자동 초기화. 반면 `vocStore`(pinia)는 전역이라 `startCall()`(새 통화) 때만 비워짐 → 페이지 이탈/재진입 시 이전 콜 history 잔존. `onUnmounted`에서 `clear()`로 해결.

### 추후 할 일
- 비교 끝나면 `agent/index.vue`의 `<CustomerVocPanel>` 숨김 처리

### 추가: 상담내용/고객VOC탐지 헤더 보더라인 높이 일치
- 두 패널 헤더(`.adv-page-content-header`) 보더라인 위치가 달라 보임. 자연 높이(콘텐츠 min-h-32 + padding-bottom 8 + border 1 = **41px**)로 양쪽을 결정적 고정.
- `chat/index.vue` 비-admin 헤더 + `CustomerVocPanel.vue` 헤더에 마커 클래스 `adv-panel-header-fixed` 추가, 각 scoped style에 `{ height:41px; box-sizing:border-box; align-items:center }` 부여. (admin 헤더는 별도 v-if라 영향 없음, 전역 클래스 미변경)
- 검증: 상담사 화면은 `isFirstMount=false`(통화 시작/수신) 시에만 패널 렌더 → 통화 상태에서 육안 확인 필요. px 미세조정 여지 있음.

### 마무리: VOC 본문 스크롤 / 헤더 wrap / 점선 리더 (최종 확정)
- **VOC 본문 7px 스크롤 제거** (`agent/index.vue`): `.adv-voc-area` `min-height: 190px → 200px` (본문 `.voc-panel__body` 7px 오버플로 해소).
- **상담내용 헤더 좁아질 때 2행 wrap** (`chat/index.vue`): 헤더 `.adv-panel-header-fixed` 를 `height:41px` 고정 → **`min-height:41px` + `flex-wrap:wrap` + `row-gap:4px`**. 1행이면 41px라 고객 VOC 패널 보더라인과 일치, 폭 부족 시 VOC 블록이 잘리지 않고 2행으로 내려감. (VOC 패널 헤더는 wrap 불필요 → `height:41px` 고정 유지, scoped라 독립)
- **VOC 인라인 블록** `.adv-voc-inline`: `flex-shrink:0` + `margin-left:auto` → 안 찌그러지고 2행에서도 우측 정렬.
- **점선 리더**: 가변 유지하되 점수영역 `.adv-voc-score { flex:0 0 auto; min-width:110px }` 로 폭 확보 → `감정 ⋯ 0.00` 사이 점선이 화면폭에 출렁이지 않고 안정적(길이 절반으로 조정: 150→110px).
- 헤더 양쪽 보더라인 높이 일치: `chat/index.vue` 비-admin 헤더 + `CustomerVocPanel.vue` 헤더 둘 다 마커클래스 `adv-panel-header-fixed`(자연높이 41px = 콘텐츠32+pb8+border1) 부여 + `flex-shrink:0`.

### 사용자 피드백(메모리에도 기록)
- 라이브 dev 화면 검증은 사용자가 직접 함. Claude의 Playwright evaluate/조작 자제(허락 후에만). dev: `localhost:8173`.

### 남은 TODO
- 비교 끝나면 `agent/index.vue`의 `<CustomerVocPanel>`("고객 VOC 탐지(메뉴제거예정-개발검증용)") 숨김 처리.
