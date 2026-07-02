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

## 2026-06-17 — AICM 검색속도(체감속도) 표시 + 동일 문서명 구분

### 0. 배경
- 시연회 핵심이 **속도 체크**. 지식저장소(`TabTypeKnowledgeIndex.vue`)는 2기능: ①상담중 실시간 트리거 문서노출(`/assist-stream`) ②수동검색(`/stream`). 둘 다 동일 SSE 파이프라인(`fetch` → `parseSseStream` → 이벤트 콜백).

### 1. 실시간 문서 수신 구조 (SSE) — 정리
- 발화 감지 시 백엔드 1회 요청 → 응답이 이벤트로 순차 스트리밍:
  `intent`(검색여부/skip) → **`sources`(문서후보 최대5, 유사도순) ← 화면 카드 뜨는 순간** → `distilled`(LLM 선별 selected_refs + 요약) → `token`(답변 글자, 여러번) → `done`.
- 문서 1개 = 문서 통째가 아니라 **청크(chunk)** 1조각. 같은 문서명 여러 개 가능, 청크별 `section_title`/`page_info`/`score` 다름.
- 수신·가공: `useChatAssist.ts` → emit → `agent/index.vue` 보관 → 챗버블/지식패널 렌더. 프론트 LLM 직접호출 0(순수 프록시).

### 2. 체감속도 측정 정의 (확정)
- **시작 = `fetch` 직전(로컬 시계 `Date.now`/`performance.now`), 끝 = 첫 `sources` 이벤트(문서 첫 도착).** 백엔드 `latency_ms` 무관.
- 나중에 너무 빨라 보이면 끝점만 `sources`→`done`(노출완료)로 교체 가능(주석 명시).
- 표시형태(요약문 맨 아래, 수동/실시간 동일):
  `AICM 검색속도 : 0.8s` / `(세부 시작 14:32:25.290 완료 14:32:26.093)`

### 3. 구현 (속도 표시)
- `api/types/assist-stream.type.ts`: `StreamTiming{startedAt,firstEventAt,elapsedMs}` + 핸들러 `onTiming?` 추가.
- `api/apis/assist-stream.api.ts` / `document-search.api.ts`: fetch 직전 시각 캡처, **첫 `sources` 1회** `onTiming` 보고.
- `utils/time.ts`: `formatClockMs`(HH:mm:ss.SSS), `formatElapsedSeconds`(0.6).
- 신규 `knowledge/SearchSpeedBadge.vue`: 양쪽 공용 배지(`flex-shrink:0`).
- 수동: `useKnowledgeSearch.ts` `SearchSession.timing` 저장 → `TabTypeKnowledgeIndex.vue` 요약 스크롤영역 **밖 아래** 배지.
- 실시간: `useChatAssist.ts`에서 요약 emit 자리에 `updateChatTiming` 동반 emit → `chat/index.vue` emit 선언 → `agent/index.vue` `chatDocumentSpeed`+`speedByKeyword` 캐시(summary 패턴 미러) → `DocumentContentPanel.vue` 요약박스 **밖 아래** 배지.

### 4. 테스트 후 버그 3건
1. **(내 버그) 잘림**: 배지를 스크롤/overflow:hidden 영역 *안*에 둬서 반만 보임 → 수동·실시간 모두 **요약영역 밖 아래로 이동** + `flex-shrink:0`.
2. **(기존 버그, 무관) 탭 좌우스크롤 1번째 못감**: `useKnowledgeScroll` 고정 스텝(-200) + 좌측 화살표(`absolute left:4px`)가 첫 탭 덮음 추정. 속도기능과 별개 → 미수정(보류).
3. **(크리티컬, 내 버그) 실시간 턴별 매핑 안됨**: 탭 전환 시 속도 사라짐.
   - 원인: 저장키=`messageId`(순수 버블id) vs 복원 조회키=`item.keyword`=`firstHintKey ?? messageId`(= `messageId_사유` 힌트키) **불일치**. summary도 동일 latent 버그(활성값 남아 안 띔).
   - 수정: `useChatAssist.ts` 두 emit(distilled/done-fallback)에서 **탭키 `firstHintKey ?? messageId`로 통일** emit → 저장=복원 일치. summary도 같이 정렬됨.
   - 검증: 수동검색은 탭 갔다와도 시간 유지 OK 확인. 실시간 재검증은 사용자 진행중.

### 5. 동일 문서명 구분 (챗버블 3개 문서 타이틀) — 진행
- 문제: `chat/index.vue:getDetailItemDisplayTitle`가 본문 `Q.~` 추출 우선, 없으면 `item.title=document_title` 폴백 → 같은 문서 청크들이 **동일 문서명**으로 떠서 다 같은 줄 착각(시연 지적).
- 해결(확정): **2줄 레이아웃**. 1줄=기존 타이틀, 2줄=`소제목 · p.페이지`(회색 11px, 한줄 ellipsis). 값 없으면 미노출(회귀0), 섹션==타이틀이면 생략, hover 시 전체 툴팁(`title` attr).
- 구현: `getDetailItemSubtitle`/`getDetailItemTooltip` 헬퍼 추가, 타이틀 div에 `:title` + 하위 `.title-subtext` 추가, CSS는 `min-width:120px` 유지(키워드 동반 레이아웃 불간섭)+`overflow:hidden`+subtext 스타일.
- 적용범위: 어시스트 실시간 3개 문서 챗버블만. 추천태그 하단(최대5)은 미적용(원하면 헬퍼 재사용).
- **사용자 확인 대기**: 로그에서 `section_title`이 청크마다 다른 값으로 차 있는지 / `page_info` 형식(`12` vs `p.12`). 형식 다르면 정규화 조정.

### 6. AI 답변 박스 일관화 (실시간 DocumentContentPanel) — 추가 수정
- 증상(여러 케이스 비일관): 박스 안에 넣으니 또 잘림 / 요약·속도 둘 다 없으면 "AI 답변" 타이틀째 미노출 / 요약 없어도 문서만 있는 경우 등.
- 원인①(잘림): `.document-content-panel`(flex column+overflow-y:auto) 안에서 `.llm-summary-box`가 flex 미지정→기본 `flex-shrink:1`이라 아래 문서뷰와 경쟁 시 찌그러져 `overflow:hidden`에 잘림 → **`flex-shrink:0`** 추가.
- 원인②(타이틀 미노출): 박스가 `v-if="summary||speed"`라 둘 다 없으면 미렌더 → prop `alwaysShowAnswer` 추가. 챗 패널 사용처에만 `:always-show-answer="true"` → **문서 있으면 요약/속도 없어도 박스+타이틀 항상 노출(본문 `-`)**. `ai-answer-body min-height:40px`.
- 수동검색 문서 단독보기 재사용처는 prop 미전달 → 빈 박스 안 뜸(기존 유지).
- 배지 UI: 사용자가 "내부 검토용이라 덜 튀게 박스 안에 속한 값처럼" 원함 → 수동/실시간 모두 **AI답변 박스 안 하단**. 단 수동은 본문만 스크롤(`.search-summary-scroll`)/배지 고정 구조로 잘림 방지.
- 결과: 검색속도 UI 정상 동작 확인(사용자 OK).

### 7. CustomerVocPanel 숨김 (agent/index.vue)
- "고객 VOC 탐지(메뉴제거예정-개발검증용)" `<CustomerVocPanel>`에 **`v-if="false"`** → 지식저장소(`.adv-knowledge-area` flex:9)가 우측 컬럼 전체 사용. (TODO였던 항목 처리됨, 복귀는 false만 제거)

### 8. 대시보드 헤더 고정 UX (Dashboard.vue)
- 문제: 화면 작아지면 "내 상담 요약" 카드가 컬럼 `overflow:hidden`에 잘리고 스크롤 없음.
- 1차로 컬럼(`.dashboard-left/right`) `overflow-y:auto` 시도 → 공지사항까지 통째로 스크롤되는 부작용 → **되돌림**.
- 최종: **"내 상담 요약" 카드만** 헤더 고정 + 본문 스크롤(엑셀 행 고정). `.consultation-card`를 `flex:0 1 auto; min-height:0; display:flex; column; overflow:hidden`, `:deep(.el-card__body)` flex column, `.card-content`에 `flex:1; min-height:0; overflow-y:auto`. (card-header는 공통 `flex-shrink:0`로 고정)
- 공지사항/자주열람지식 카드는 **이미** 헤더 고정+리스트 스크롤 구조(`.notice-list`/`.knowledge-items`가 `flex:1; overflow-y:auto`, card-header `flex-shrink:0`) → 추가 수정 불필요 확인.

### 메모
- 라이브 검증은 사용자 직접(합의 유지). dev `localhost:8173`.

### 다음 할 일 (오늘 마무리, 열린 항목)
- 동일 문서명 구분(5번): 로그에서 `section_title` 청크별 상이 여부 / `page_info` 형식 확인 후 정규화 조정.
- (선택) 대시보드 좌측 3항목 `.summary-items { justify-content: space-between }` → `flex-start` 정리 여부.
- (보류) 지식저장소 탭 좌우 스크롤 1번째 도달 문제(기존 버그, 속도기능과 무관).

## 2026-06-18 — 콜이력 모달 UX + AICM 검색속도 "상세" 타임라인 모니터링

### 1. 콜이력 → 상담이력 모달 재진입 UX (완료)
- 증상: 오른쪽 Drawer "콜 이력"(`CallHistory.vue`) 리스트 팝업에서 "보기" 클릭 시 상담내용 모달(`ChatHistoryModal`) 뜨는데, 모달 닫으면 콜이력 리스트 팝업이 사라져 다시 "콜 이력" 버튼을 눌러야 했음.
- 원인: `handleHistoryModal`에서 `showPopover.value = false`(팝업 닫음) + `emit("menuClick")`(부모 `activeMenu=null`)을 호출 → 콜이력 메뉴 자체가 비활성됨.
- 해결: 두 줄 제거. 콜이력 팝업(z 2001) 위에 상담내용 모달(ElDialog z 9999, backdrop)이 덮어서 뜨므로, 팝업을 닫을 필요 없음. 모달 닫으면 리스트가 그대로 남아 연속 열람 가능.
- 파일: `components/layout/Drawer/components/CallHistory/CallHistory.vue` `handleHistoryModal` 만 수정.

### 2. AICM 검색속도 "상세" 모니터링 — 단계 타임라인 모달 (구현 완료, 라이브 검증 대기)
- 목적: 어제 만든 배지(요청~첫 sources)에 더해, **SSE 전 구간 단계별 타임라인**을 보고자료/시연용으로 시각화. 임시(상담서비스 미제공). DB 저장은 추후 검토.
- ⭐ **기존 배지(`SearchSpeedBadge`/`StreamTiming`/`onTiming`)·측정·배선은 전부 그대로 유지. 순수 additive(회귀 0).**
- 결정(사용자): ①6포인트 풀상세(요청→intent→sources→distilled→token→done) ②배지 옆 "상세" 버튼 진입 ③가로 간트식 타임라인 + 순차 막대 애니메이션.

#### 핵심 설계 — 실시간 5단 릴레이 회피 위해 pinia store 중심
- API 레이어에서 각 SSE 이벤트 첫 도착시각 누적 → `done` 때 `onTrace(StreamTraceData)` 1콜백. 호출부 2곳에서 `traceStore.add(...)` 한 줄.
- 모달은 store만 구독 → 기존 5단 emit 릴레이(useChatAssist→chat→agent→Tab→Panel) 안 탐.

#### 추가/수정 파일
- **신규**
  - `api/types/assist-stream.type.ts`: `TraceStage`/`StreamMark`/`StreamTraceData`/`StreamTrace` 타입 + 핸들러 `onTrace?` (기존 `StreamTiming`/`onTiming` 그대로).
  - `stores/modules/speedTrace.ts`: trace ring buffer(최근 20) + `add`(같은 id면 교체)/`openModal(id)`/`close`, getter `selected`/`latest`/`hasTraceById`.
  - `view/advisor/components/knowledge/SearchFlowModal.vue`: ElDialog, 간트(인접 마크쌍=구간, sources=★강조) + 단계 도착시각 목록 + 막대 grow 애니메이션(모달 open/selected 변경마다 replay). `TabTypeKnowledgeIndex`에 1곳만 마운트(수동·실시간 배지 둘 다 이 안).
- **수정(가볍게)**
  - `api/apis/assist-stream.api.ts` / `document-search.api.ts`: 이벤트 첫 등장 시각 누적(`request` 0마크 포함) + `done`에 `onTrace`.
  - `useChatAssist.ts`(실시간): `onTrace`→`traceStore.add({id: firstHintKey ?? messageId, kind:"assist", query}, t)` (timing emit과 동일 키).
  - `useKnowledgeSearch.ts`(수동): `onTrace`→`traceStore.add({id: newSessionId, kind:"search", query}, t)`.
  - `SearchSpeedBadge.vue`: `traceId` prop + "상세" 버튼(해당 id trace 있을 때만 노출) → `openModal`.
  - `TabTypeKnowledgeIndex.vue`: `chatDocumentTraceId` prop 추가, 실시간 패널/수동 배지에 `:trace-id` 전달, `SearchFlowModal` 마운트.
  - `DocumentContentPanel.vue`: `traceId` prop → 배지 전달.
  - `agent/index.vue`: `chatDocumentTraceId` ref, timing update 시 `=messageId`/탭전환 시 `=keyword`, Tab에 prop 전달.

#### trace.id 매칭 규칙 (중요)
- 배지 `traceId` = 그 검색의 timing 키와 동일해야 매칭. 수동=`sessionId`, 실시간=`firstHintKey ?? messageId`(탭키). → "상세" 클릭 시 store에서 그 id 조회.
- 에러로 `done` 미수신 시 trace 미저장 → "상세" 버튼 미노출(배지는 정상).

#### 검증 포인트 (라이브 — 사용자 직접)
- 수동검색/실시간 어시스트 각각 배지 옆 "상세" → 간트 모달 + 애니메이션.
- 탭 전환 시 그 검색의 상세가 맞게 뜨는지(키 매칭).
- 기존 배지/속도 회귀 0. 모달 떠도 실시간 상담 무영향(읽기전용 오버레이).
- 전 변경 파일 타입 진단 0건 확인됨.

### 3. 모달 내용/디자인 보완 라운드 (전부 `SearchFlowModal.vue` + 일부 API/타입)
- **아래 상세에 구간시간 병기**: 각 단계 줄에 `+누적s (+구간s)` — 누적(시작 후 경과) 옆에 직전 구간(=그래프 막대 길이) 괄호 표기.
- **라벨 변경**: `검색(RAG)` → **`검색(AICM)`** (모든 RAG 표기 AICM 통일).
- **헤더 구분**: `el-dialog__header` 하단 보더라인 + 타이틀 폰트 18px bold. body 상단 `padding-top:10px`(보더-검색어 겹침 해소).
- **범례 툴팁**: "실시간/수동검색" 칩 옆 ⓘ → hover 시 6단계 용어 설명(+ LLM 뱃지, ★검색속도 배지 기준).
- **그래프↔목록 일치**: 둘 다 같은 `rows`(공용) 사용. 한때 6단계 고정+"기록 없음" 자리표시였으나 → **B안으로 변경**: 미수신 단계는 행 자체를 생성 안 함(`if(!m) continue`) → 자동 숨김. (그래프/목록 동시 숨김, "기록 없음"/absent CSS 제거)
- **LLM/RAG 색 구분**: `STAGE_DEFS.isLlm` 하드코딩 → 막대 색. 의도판단/선별/생성=보라(LLM), 검색(AICM)=파랑★(벡터검색), 요청/완성=회색. 그래프 하단 색 범례 + 툴팁 LLM 뱃지.
- **백엔드 latency 병기(G)**: `done` 이벤트 `stages` → `StreamTraceData.backendStages` 추가(타입+API 2곳). 모달 맨 아래 주석 위 `백엔드 보고: 의도 X · 검색 Y …` 한 줄(살짝 bold, 부각 최소). 값 없으면 자동 생략.
- "보기 직후 버튼 안 뜸" 논의: trace는 `done`(답변 완성)에 저장되므로 답변 다 나와야 버튼 노출. **부분 저장으로 앞당기려다 → 사용자 판단으로 철회**(AI 요약도 검색결과의 일부, done까지가 완성된 타임라인이라 현 동작이 맞음). 코드 변경 없음.

### 4. 백엔드 구조 확인 (사용자가 백엔드에서 공유받음)
- `asst-service`의 assist-stream / search 두 API는 **순수 SSE 릴레이/프록시**(LLM 호출 0). 둘 다 `${AICM_HOST}/api/aicm/v1/search/rag_assist` 로 POST → SSE를 그대로 중계만.
- 보내는 payload: `{ workspace_id, query, enable_distill:false, conversation_history }`. → **`enable_distill:false` 라 `distilled`(선별) 이벤트가 항상 미수신** = 선별 "기록 없음"의 근본 원인. B안 자동숨김이 정확히 대응(백엔드가 true로 바꾸면 자동 재노출).
- 의도판단·검색·답변생성은 전부 **업스트림 AICM RAG 서버**(`rag_assist`)에서 처리. LLM도 거기.

### 5. ⭐ 보고용 개념 정리 (사용자 보고 시 오해 방지 — 가장 중요)
1) **시간값 출처**:
   - 타임라인 막대 / 누적(+Xs) / 구간(+Xs) / 시작시각 / 단계 도착시각 = **전부 프론트 로컬 측정**(SSE 이벤트를 "받은 시각", `Date.now`/`performance.now`). **네트워크 지연 포함된 체감(체험)값**.
   - **맨 아래 `백엔드 보고:` 한 줄만 백엔드 실측**(`done.stages`, 순수 처리시간, 네트워크 제외).
   - 검색어 = 프론트가 보낸 query(사용자 입력).
2) **단계 구분의 근거**: 프론트가 런타임에 LLM/검색을 "감지"하는 게 아님. **SSE 이벤트 이름 5종**(`intent/sources/distilled/token/done`)은 백엔드가 실제로 보내는 사실이고, **그 중 뭐가 RAG·LLM이냐는 개발자가 백엔드 구조 지식으로 하드코딩한 라벨**(`STAGE_DEFS.isLlm`). 백엔드 `done.stages`(`intent/search/distill/generate` 4분류)·`token_usage`·`model_used` 와 일치하므로 근거는 탄탄하나, 백엔드 구조 바뀌면 수동 갱신 필요.
   - LLM 단계 = 의도판단(Gemma)/선별/생성. 순수 RAG 검색 = `sources`(벡터검색). `request`는 SSE 아닌 프론트 시작 기준점, `done`은 종료신호.
3) **총소요 ≠ 문서검색시간 (핵심 오해 포인트)**:
   - **총소요(요청~완성/done)** = 의도판단(LLM) + 검색(RAG) + 답변생성(LLM) **전체** = "AICM 어시스트 1회 요청의 전체 체감시간".
   - **순수 문서검색(RAG) 속도** = 요청~`sources`(첫 문서 도착) = **★ 검색 구간 = 어제 만든 배지값**. 총소요의 **일부**(보통 앞 토막)일 뿐.
   - 답변생성(token~done)이 길면 총소요의 큰 부분이 검색이 아니라 **LLM 생성**. → 보고 시 "문서검색 속도"는 **★검색 구간(배지값)**, "질문~답변 완성 전체"는 **총소요**로 구분해 써야 오해 없음.

### 작업 마무리 상태
- 전 변경 파일 타입 진단 0건. 라이브 검증은 사용자 직접(합의).
- (선택, 미적용) "문서검색 0.8s / 전체완성 2.3s" 식 상단 분리 강조 — 필요 시 추가.
- (선택, 미적용) 색 범례에 "단계 종류 표시이며 실제 LLM 실행 측정값 아님" 주석.

### 6. 실시간 타임라인에 STT수신~API호출 구간 추가 (구현 완료, 라이브 검증 대기)
- 배경: 실시간 측정 시작점이 assist-stream fetch라, 그 이전(발화→STT변환→ws수신→화면표시→트리거) 구간이 빠져 "체감은 느린데 검색속도 숫자는 빠른" 괴리. 특히 **STT수신~API호출**이 프론트에서 개선 가능한 구간.
- ⭐ **의도적 딜레이 정체 = `TURN_MERGE_TIMEOUT_MS = 3500`(3.5초)** (`useChatMessageParser.ts:78`). NeMo ASR turn 병합: 같은 화자 발화가 미완으로 이어지면 다음 turn을 **최대 3.5초 대기**했다 합쳐서 검색. `final`이면 즉시. 전임자 주석 "권장 1~2.5초보다 일부러 길게". (0.3초짜리는 없음, 이 3.5초가 그것)
- 결정(사용자): 발화종료(end_ms)는 **제외**(서버 상대시계라 부정확). STT수신~API호출(프론트 벽시계)만 추가. 측정 시작점 = **발화 chain 최초 수신**(merge 대기 포함, A안).
- 구현:
  - `assist-stream.type.ts`: `TraceStage`에 `stt_received` 추가.
  - `assist-stream.api.ts`: `callAssistStream(req, handlers, signal, clientStartedAt?)` — clientStartedAt(STT수신 벽시계) 있으면 `stt_received` 마크 + `offsetMs=startedAt-clientStartedAt`로 이후 마크 sinceStartMs 보정, trace.startedAt/totalMs도 STT수신 기준. **배지(onTiming)는 fetch~sources 그대로 유지(회귀 0)**.
  - `useChatAssist.ts`: `handleAssistStream(...,sttReceivedAt?)` → callAssistStream에 전달.
  - `useChatMessageParser.ts`: `parseMessageData` 진입 시 `msgReceivedAt=Date.now()`. `PendingMerge.startWallMs`(chain 최초 수신 벽시계) 추가 — 5a(merge 이어받기)는 기존 유지, 5b/5c(새 chain)는 msgReceivedAt. final 트리거(482)에서 `mergeStartWallMs` 전달. (서버 `mergeStartMs=start_ms`는 상대시계라 미사용)
  - `SearchFlowModal.vue`: `stt_received`("STT 수신") 단계 추가, **`요청`→`API 호출`** 라벨, STT수신~API호출 막대 **주황(isFront, merge 대기 포함=개선 구간)**. rows 시작점 판정을 `isFirst` 기반으로(request가 더 이상 항상 시작점 아님 — 첫 존재 단계=start-dot). 범례/툴팁에 프론트(주황) 추가.
- 동작: 발화 토막→merge 대기 끼면 주황 막대가 최대 3.5초로 길게 보임 → "merge 때문"이 한눈에. 수동검색은 stt_received 미수신 → 자동 숨김(`API 호출`부터). 단일 final 발화는 STT수신~API호출 짧음.
- 다음 개선 후보(미적용): 주황 막대가 실제로 길면 `TURN_MERGE_TIMEOUT_MS` 단축 검토.

### 7. 지식저장소 수동검색 입력창 — clearable (완료)
- 검색 후 검색어가 input에 남아 긴 검색어 다시 칠 때 불편. 옵션(현상유지/호출시초기화/지우개) 중 **지우개(B안)** 선택.
- "돋보기→X 토글"은 마우스 검색 불가/입력중 실수 clear 위험 → **`ElAutocomplete`에 `clearable` prop 1개**만 추가(검색어 있을 때 input 안쪽 우측 작은 회색 X, 돋보기는 append에 그대로). `TabTypeKnowledgeIndex.vue`.

### 8. SearchSpeedBadge "(세부 시작~완료)" 줄 제거 (완료)
- 상세 버튼+모달에 단계별 시각이 다 있어 중복 → 배지의 `speed-detail` 줄 + `startClock`/`endClock`/`formatClockMs` import/CSS 제거. 배지는 `AICM 검색속도 : 0.8s [상세]` 로 간결화.

### 9. STT 측정 정밀화 + 실시간 병목 원인 규명 (완료)
- **6번의 STT수신(merge 기준, final 시점) → 첫 partial 기준으로 정밀화.** merge 기준은 final 직행 발화에서 항상 ~1ms(=API호출 전 텀을 통째로 놓침)였음. 콘솔 진단으로 확인: `chainCount:1, gapMs:1` 반복.
- **측정 단계(실시간)**: `발화 수신(첫 partial)` → `STT 타이핑` → `[마지막 partial]` → `발화종료 대기` → `API 호출(nlp:complete)` → 의도판단/검색★/생성/완성.
  - `useChatMessageParser.ts`: `sttTimingBySpeaker`(speaker별 `firstAt`=첫 partial, `lastPartialAt`=마지막 partial) 추적 → nlp:complete(final) 트리거에서 `handleAssistStream(..., sttFirstAt, sttLastPartialAt)` 전달 + 발화 종료 시 리셋. (`:call:events` start 에서도 리셋)
  - `assist-stream.type.ts`: `TraceStage`에 `stt_last_partial` 추가. `assist-stream.api.ts`: `clientStartedAt`(첫 partial)+`clientLastPartialAt`(마지막 partial) 인자 → 마크 prepend, 시작점을 첫 partial로. **배지(onTiming)는 fetch~sources 그대로(회귀 0)**.
  - `SearchFlowModal.vue`: `발화 수신`/`STT 타이핑` 단계 + `발화종료 대기`(마지막partial~API호출) 막대 **주황(isEou) 강조**. rows에서 request 라벨을 실시간(non-first)이면 "발화종료 대기"로 동적 처리. 범례/툴팁에 EOU 설명.
- ⭐ **병목 원인 규명**: 마지막 partial(화면 텍스트 완성, 예 12.078s)~nlp:complete(API호출, 15.599s) = **~3.5초 텀**. 진단 로그(`typingMs`/`eouWaitMs`)로 측정.
  - **백엔드 답변(확정)**: "STT 결과가 오면 NLP 처리를 하는데 **현재 NLP 서버가 없어서 retry 후 처리**해서 느림." → 이 텀 = **NLP 서버 부재 retry 지연**(STT/NLP 서버가 redis publish 지연). **`asst-service`(우리 백엔드)·프론트 모두 무관**(프론트는 complete 받자마자 0ms 호출).
  - **`TURN_MERGE_TIMEOUT_MS`(3500)와 값 비슷하나 무관 확인**: 그 타이머는 미완 발화 텍스트 정리(baseline 복원)용이지 API 호출 지연 아님. 이번 케이스 `chainCount:1`+pending 없음 → 타이머 자체 미발동. **건드리지 않음(목적: NeMo ASR turn 합치기 안전망).**
- **모달 라벨은 `발화종료 대기(EOU)` 유지** — 원인이 NLP retry로 밝혀져 `NLP 처리 대기`로 바꾸려 했으나, 사용자가 "마무리 시점 상태 그대로"를 선호 → 라벨/변수/클래스 전부 **원복**(isEou/.eou/EOU 표기 유지).
- 진단 콘솔 로그(`[stt-ch-diag]`, `[stt-speed-diag]`) 전부 제거. 전 변경 파일 타입 진단 0건.
- **결론**: 실시간 체감 느림의 범인 = **API 호출 *전* 단계(마지막 partial~nlp:complete)의 NLP 서버 retry 지연**. RAG(API 이후)·프론트는 빠름. 모달 주황 막대로 가시화됨(백엔드 수정 전/후 비교 자료).

### 10. 지식저장소 탭/검색폼 자잘한 버그 3종 (완료)
- **① 탭 10개+ 빈 화면 (el-tabs 스크롤 충돌)**: 탭이 컨테이너보다 넓어지면 Element Plus `el-tabs`가 `.el-tabs__nav`에 자체 `transform: translateX(-N)`을 걸어 nav를 밀어버림 → 이 화면은 별도로 `.el-tabs__nav-scroll { overflow-x:auto }` + 커스텀 좌우버튼(`useKnowledgeScroll.ts`)으로 native 스크롤도 구현해둠 → 두 스크롤이 충돌해 탭이 화면 밖(왼쪽)으로 사라지고 오른쪽엔 빈 영역만 남음(왼쪽 스크롤 버튼 누르면 다시 보였던 이유). **해결**: `TabTypeKnowledgeIndex.vue` `.tabs-header-container` 스코프에서 `:deep(.el-tabs__nav){ transform:none !important }`로 내장 translateX 무력화 + 기본 화살표(`.el-tabs__nav-prev/next`) `display:none` + `.is-scrollable` 패딩 0. 스크롤은 native overflow + 커스텀 버튼 단일 방식으로 통일.
- **② 검색창 빈 말풍선 (ElAutocomplete 빈 제안 패널)**: 검색창은 `ElAutocomplete`인데 `:fetch-suggestions="() => []"`로 자동완성을 실제로 안 씀(항상 빈 배열). 빈 제안 패널이 작은 말풍선처럼 떠 있었음(스페이스 입력하면 사라짐). **해결**: `popper-class="adv-knowledge-autocomplete-hidden"` 부여 후, popper가 body로 teleport되므로 scoped style 안에서 `:global(.adv-knowledge-autocomplete-hidden){ display:none !important }`로 숨김.
- **③ 일상대화 시 "검색 중..." 박제**: 문서 리스트 로딩 표시 조건이 `results.length === 0`만 봐서, 일상대화(문서검색 패스 → results 영영 0건, `done()`으로 `isStreaming=false`)일 때도 "검색 중..."이 계속 떠 있었음. **해결**: 로딩("검색 중...")은 `isStreaming && results.length===0`일 때만, 스트리밍 종료 후 0건이면 **"검색된 문서가 없습니다."**로 분기(`TabTypeKnowledgeIndex.vue` 문서 리스트 v-else-if 추가). 상단 AI 답변 패널엔 "일상 대화입니다."가 그대로 표시됨.
- 라이브 검증은 사용자 몫(localhost). 모두 CSS/조건 분기 추가라 부작용·롤백 부담 낮음.

---

## 2026-06-19 — VOC 감정변화 타임라인 모달 (상담중 실시간 history 시각화)

### 1. 감정 변화 타임라인 모달 (구현 완료, 라이브 검증 대기)
- 배경: 상담중 실시간 VOC를 `index.vue`(222~232행)에서 **최신값 1건만** 인라인 노출 중. DB 저장은 안 하지만 `vocStore.history`에 turn 단위로 **메모리 누적**되고 있어 과거 감정 변화를 보여줄 데이터는 이미 있음. 어제 만든 SearchSpeedBadge→SearchFlowModal 패턴(끝 아이콘→모달→간트+grow 애니메이션)을 답습해 "감정변화 타임라인"을 만들기로.
- 확정(사용자 선택 2건): ① 그래프 = **커스텀 SVG/CSS**(라이브러리 X, 감정색 100% 제어), ② 표시지표 = **감정 중심 + 위험 보조**(감정=메인 라인, 민원위험·이탈징후=얇은 보조 라인).
- 구현:
  - **신규 `VocHistoryModal.vue`**(`components/chat/`): el-dialog(SearchFlowModal 스타일 답습).
    - 커스텀 SVG 라인차트: viewBox 640×220, x=turn 균등분할, y=score 0~1(위로 갈수록 위험). 감정 메인=인디고(#6366f1) 굵은 라인+영역 그라데이션, 보조=민원위험(보라 #a855f7)·이탈징후(주황 #f59e0b) 얇은 라인. `주의(0.5)`/`위험(0.8)` 점선 기준선+라벨.
    - 애니메이션: 라인 `pathLength=1` 정규화 후 `stroke-dashoffset 1→0`(좌→우 draw), 영역 fade-in, 각 turn 점 순차 pop(scale, delay=0.5+i*step), 하단 타임라인 행 순차 fade-up. `@opened`/watch(isHistoryModalOpen)로 `replay()` — 열 때마다 재생(SearchFlowModal 패턴).
    - 하단 타임라인 리스트: turn별 [감정 색점(세로 레일) + 라벨 뱃지 + summary 문구]. 색은 `resolveEmotionType`(화남red/불만보라/만족초록/감사핑크…) 그대로.
    - 상단: 최신 감정 요약 1줄(점+라벨+summary).
  - `voc.ts`: state `isHistoryModalOpen` + actions `openHistoryModal()`/`closeHistoryModal()` 추가.
  - `index.vue`: VOC 인라인 끝에 `timeline` 아이콘 버튼(`.adv-voc-history-btn`) — `vocHasHistory`(=`history.length>=2`)일 때만 노출(1건이면 변화 없음). 클릭→`vocStore.openHistoryModal()`. `<VocHistoryModal/>` 등록 + import + `vocHasHistory` computed 추가.
- 데이터: `vocStore.history`(메모리 누적분) 그대로. **새 API 없음, DB 영향 0.** 타입체크 우리 파일 에러 0(뜬 2건은 기존 tsconfig deprecation 경고, 무관).
- 미적용(라이브 보고 결정): ① 긴 통화 시 x축 촘촘해질 때 가로스크롤 vs 균등압축, ② 감정 메인 라인을 타입별 그라데이션으로 바꿀지. 기본값으로 둠.

### 2. turn 중복 정리 — turn별 1점으로 합치기 (완료)
- 현상(사용자 질문): 헤더는 `10 turn`인데 타임라인은 `#1,#1,#2,#2…#5,#5`로 turn_idx 중복. 둘이 다른 걸 셈 — 헤더 `points.length`=수신 건수(라벨 "turn"이 오해 유발), 타임라인 `#N`=백엔드 `turn_idx`.
- 원인: `useChatMessageParser.ts:276`에서 `:call:voc` 메시지를 dedup 없이 전부 `vocStore.setVoc`로 push. 백엔드가 한 turn 안에서 감정 재평가하며 VOC를 여러 번(turn당 2회) publish → 실제 turn 5개인데 감지 10건.
- 확정(사용자): **A안 — turn별 최신 1건으로 합치기**(같은 turn 중간 감정변화는 마지막값만).
- 구현: `VocHistoryModal.vue`에 `dedupedHistory` computed 추가 — `Map<turn_idx, VocMessage>`로 나중 수신이 앞을 덮음(turn_idx 없으면 `__i{idx}`로 각자 보존). `points`가 이걸 사용 → 헤더(points.length)·그래프·타임라인 한 번에 정규화. 결과: `#1~#5`(5점), 헤더 `5 turn`, "turn" 라벨도 정확해짐.
- 미적용(필요 시 전환): 같은 turn 내 중간 감정변화까지 보려면 B안(전부 유지) 가능.

### 3. 화면 안내 범례 툴팁 추가 (완료, SearchFlowModal 패턴 답습)
- 요청: 헤더 `xx turn` 옆에 마우스 올리면 뜨는 범례 — 이 상세화면의 구성/분석 목표 + 위험/주의 기준선 + 이해 어려운 용어 풀이.
- 구현: `VocHistoryModal.vue` 헤더에 `el-tooltip`(placement=bottom-start, effect=dark, show-after=80, popper-class=`voc-legend-popper`) + `info` 아이콘(`cursor:help`). 내용 3블록:
  - ① 화면 목표: "통화 중 고객 감정이 turn마다 어떻게 변했는지 추적, 실시간 감지값·저장본 아님".
  - ② 용어: 감정 점수(메인, 0~1 위험도 높을수록 부정적) / 민원위험·이탈징후(보조) / 점 색상(turn별 감정 종류 화남·불만·일반·만족·감사).
  - ③ 기준선: `주의 0.5`(노랑)·`위험 0.8`(빨강) 강조 + 하단 요약 `<0.5 안정 / 0.5~0.8 주의 / ≥0.8 위험`.
- 스타일: popper는 body teleport라 비-scoped(`.voc-legend-popper`), 아이콘만 scoped. `ElTooltip` element-plus에서 명시 import.
- 참고(사용자 확인): 위험/주의 기준치는 0.8/0.5 — `emotionVoc.ts` `buildTotalRisk`(종합위험도)와 동일 값으로 통일돼 있음.

## 2026-06-19 — STT 발화종료 → /stream-assist 호출 불안정 분석 + 발화당 1회 호출 보장

### 1. 문제 제기 (사용자)
- 어제 붙인 AICM 속도측정 구간에서, 고객 발화종료 신호(NeMo의 `nlp:complete`) 받고 `/stream-assist` 호출하는 타이밍이 일괄적이지 않음(때론 즉시, 때론 느림). 분석 요청.

### 2. 원인 분석 (정적 분석 + 문서)
- 호출 게이트는 `useChatMessageParser.ts`의 단 한 곳: `isUser && turn.ending === "final"`(구 :513).
- `ending`별 동작: `final`→즉시 호출 / `connective·transformative·incomplete`→pending merge로 묶고 final 대기 / `interjection`·미지값→호출 안 함.
- **근본 원인 = NeMo(엔비디아 STT 엔진)가 `ending`/`eou`를 모순되게 보냄.** `minuee_timbel_docs/adv_docs/specs/turn-eou-mismatch-report.md`(2026-05-11 STT팀 송부 리포트)에 정량 증거: 미완 ending의 53%가 `eou≥0.8` 모순. 완결 질문("…어디인가요")에 `incomplete` 부여(§4.2), 130자 본문에 `interjection`(§4.1), mid-word split.
- 즉 같은 패턴 발화라도 NeMo의 ending 분류가 들쭉날쭉 → 호출이 즉시/지연/누락으로 갈림. 측정 로직 문제 아님(측정은 그 흔들림을 정직하게 비춤).
- 현재 코드는 리포트 시점과 달라짐: `isIncompleteTurn`에서 **eou 조건이 빠짐**(ending만 봄 = 리포트 옵션 C 채택). Contract 문서엔 `turn.ending` 필드 자체가 없음(비공식 의존).
- 사용자 질문 정정: 미완으로 끝나고 final 안 오면 3.5초 타임아웃 시 **강제 final 처리 아님 → 호출 자체가 누락**(텍스트 복원만). 사용자가 본 "3.5초 후 호출"은 merge chain이 결국 final로 닫혀 누적 지연된 케이스.

### 3. VOC 관계 확인
- `/stream-assist` 요청·응답엔 voc/emotion 없음. VOC는 별도 채널 `call:voc`로 서버가 직접 publish→`vocStore.setVoc`.
- 단 요청에 `company`(테넌트 UUID) 실어 보내 백엔드가 VOC LLM도 트리거(useChatAssist.ts:273 주석). 즉 호출=RAG검색+VOC탐지. → 1회 호출 보장은 VOC도 정상화(누락 복구), 중복 없음 → 부작용 없음.

### 4. 결정 (사용자 확정)
- 방향: "flag 너무 믿지 말고 발화당 무조건 1회 호출"(일상대화는 aicm이 문서검색 스킵하니 보내도 무방).
- A안(interjection 추임새까지 전부 호출) **거절**. B(타임아웃 3.5초 유지) **채택**. STT팀엔 근본해결(옵션 A: EOU 보정) 별도 문의 — client 방어막과 독립.

### 5. 구현 (완료, 라이브 검증 대기) — `useChatMessageParser.ts` 단일 파일
- `triggerAssist()` 헬퍼 신설 + `assistedTurnIdx`(Set) **중복 가드** — 모든 호출 경유, 같은 turn_idx 재호출 차단.
- final 경로: 기존 즉시 호출을 헬퍼 경유로 교체.
- **타임아웃 콜백 2곳(partial path + complete path)**: 만료 시 텍스트 복원만 하던 것 → 고객(`sender==="user"`)이면 모은 `p.text`로 1회 호출 추가(stt 타이밍은 `p.startWallMs` 폴백). → 누락 제거.
- `PendingMerge`에 `turnIdx` 필드 추가(타임아웃 호출 시 가드용). 통화 start/end에서 `assistedTurnIdx.clear()`(통화 간 turn_idx 충돌 방지).
- 한계(고지함): 타임아웃 호출 후 *다른 turn_idx*로 3.5초+ 뒤늦은 final이 오면 1회 더 호출 가능(드묾, 같은 내용 재검색이라 무해).
- 검증: vue-tsc 통과(관련 파일 타입에러 0). 라이브는 사용자 몫 — 콘솔 `[stt-diag] pending merge timeout` 후 `/stream-assist` 호출되면 누락방지 작동.

## 2026-06-19 — 고객 발화 버블 final 수신 여부 시각화 (옅은 회색 → 본래색)

### 1. 요청 (사용자)
- 챗봇형 상담내용 UI에서 고객 발화가 final(메시지 끝) 수신됐는지 버블만 봐선 모름. final 전엔 옅은 회색, final 오면 현 색상으로 구분하고 싶음.

### 2. 사전 확인 — "현 색상" 정정
- 처음에 고객 버블을 "보라색"이라 했으나 **오류**. CSS `.bubble-user { background: var(--color-secondary)=#8e5edd }`는 죽은 fallback.
- 실제 색은 `SpeechBubble.vue` 내부 `backgroundColor` computed(:299)가 결정: 금칙어 `#E75858`/이슈어 `#FFA500`/욕설 `#0000FF`, **일반 고객발화 기본 `#666666`(진회색)** + 글자 흰색(`textColor` user=흰색).
- 고객 버블 배경은 인라인 style(`SpeechBubble.vue:19`)이라 CSS보다 우선 → computed 값이 실제 색.

### 3. 신호 = isStreaming (정확히 일치)
- partial 입력중/미완 merge대기 → `isStreaming=true`(옅은 회색), `final`/타임아웃/통화종료 확정 → `false`(본래색). 색을 isStreaming에 100% 묶음.

### 4. 결정 (사용자 확정)
- **A안 채택**: final 전 옅은 회색 배경 `#e4e7ed` + 글자 `#606266`, final 후 현행. (B안 점선테두리 등 추가질감 거절)
- 대상 고객 버블만. 금칙어 처리: streaming 중엔 회색 통일 → final 후 금칙어색(추천대로).

### 5. 구현 (완료, 라이브 검증 대기) — `SpeechBubble.vue` 단일 파일
- `backgroundColor` computed: 맨 앞에 `if (sender==="user" && isStreaming) return "#e4e7ed"` 추가(금칙어색보다 우선 → streaming 중 회색 통일).
- `textColor` computed: user면서 isStreaming이면 `#606266` 반환(옅은 배경에 흰글자 안 보이는 문제 해결).
- `.chat-bubble-message`에 `transition: background-color .25s ease` + `> span { transition: color .25s ease }` — final 전환 부드럽게.
- **final 누락 대비 = 자동 커버**: 색이 isStreaming에 묶여 있어, final 안 와도 3.5초 타임아웃/통화종료에서 isStreaming=false 되면 색 자동 확정(이전 STT 작업 안전망에 그대로 올라탐). "회색 영구 멈춤" 없음. 시너지: 색이 본래색 되는 순간 = 누락방지 API 호출 나가는 순간.
- 검증: vue-tsc 통과(SpeechBubble 타입에러 0). 라이브는 사용자 테스트 예정.

## 2026-06-19 — "지식정보" 영역 검색중 프로그래스바 (호출~결과 사이 빈 화면 해소)

### 1. 진단 (사용자 라이브 테스트 결과)
- 버블색 #666 전환(=final=`/stream-assist` 호출)은 즉시 일어나는데, "지식정보" 문서 노출은 1~2초 뒤. 사용자가 "호출이 늦다"고 느낌.
- Network 탭 확인 결과: 호출은 색변경 순간 나감. 1~2초는 **백엔드(의도판단 intent + aicm검색 sources)** 시간. 프론트 지연 아님.
- 구간 분해: `stt_last_partial→request`(NeMo final 대기/merge, 프론트 일부 제어가능) vs `request→sources`(백엔드, 프론트 불가). 이번 건은 후자(백엔드 응답)로 확정 → 프론트는 체감 개선만 가능.

### 2. 원인 — 호출~결과 사이 화면이 빔
- "지식정보" 영역(`chat/index.vue:341~`)은 `selectedKeywordForBubble[item.id]` 있을 때만 표시. 이 값은 `distilled`(결과) 도착 시 `useChatAssist.ts:445`에서 자동 설정 → **결과 와야 영역이 뜸**. 호출~결과 1~2초는 아무 표시 없음 → "동작 안 하는 것처럼" 보임.
- 빈값 경로(영역 안 뜸): 일상대화 `intent.skipped`(:286), 검색결과 0개 `distilled selected_refs=[]`(:378).

### 3. 결정 (사용자 확정)
- 호출 즉시 지식정보 영역에 "문서 검색중..." **프로그래스바** 노출 → 결과 오면 문서 리스트로 교체 / 빈값이면 프로그래스바만 제거(영역 닫힘).
- 형태: 막대 프로그래스바(el-progress indeterminate). 일상대화 깜빡임은 그냥 둠(과설계 방지).

### 4. 구현 (완료, 라이브 검증 대기) — `useChatAssist.ts` + `chat/index.vue`
- `useChatAssist.ts`: 새 ref `assistSearching: Record<number, boolean>`(bubbleId 키) 추가·반환. 토글 — 시작 :240 `true`, intent.skip/distilled빈값/distilled결과/finally(종료 안전망) `false`. messageId=String(bubbleId)라 `Number(messageId)`로 변환.
- `chat/index.vue`: 구조분해에 `assistSearching` 추가. v-memo에 `assistSearching[item.id]` 추가(반응성). 영역 v-if를 `selectedKeywordForBubble[item.id] || assistSearching[item.id]`로. 내부 최상단 `v-if assistSearching` → "문서 검색중..." + `<ElProgress indeterminate stroke-width=4>`.
- 피드백 반영: 검색중엔 외부 테두리 제거 + 패딩 축소 → 컨테이너 class 조건부 `selectedKeywordForBubble ? 'mb10 py20 px10 border-default' : 'mb6 py4 px10'`, 프로그래스바 div `gap8 py4 px4`→`gap4`. (결과 뜨면 기존 박스 스타일 유지)
- ElProgress는 main.ts `app.use(ElementPlus)` 전역 등록이라 import 불필요.
- 검증: vue-tsc baseline 10 = 변경 후 10(새 타입에러 0). git stash로 before/after 비교 확인.

## 2026-06-19 — 로컬 vs 배포(124:32026) 속도차 진단 → 백엔드 병목 결론 (코드 변경 없음)

### 1. 현상 (사용자)
- 같은 통화인데 로컬(localhost:8173)이 배포(http://124.194.32.36:32026)보다 "지식정보" 노출이 확실히 빠름. 원인 추적.

### 2. 환경 비교 — 로컬·배포 백엔드 동일
- 로컬=`MODE=5f.local`(.env.5f.local), 배포=`MODE=5f.dev`(.env.5f.dev). 배포 실행: `docker compose -f docker-compose.dev.5f.yml up -d --build --force-recreate` (Dockerfile.dev + command override로 `webpack serve`, 즉 **배포도 dev-server**).
- 두 env diff = `HOST_APP_URL`(localhost:8173 vs 124:32026) **단 하나**. 이건 Module Federation remoteEntry 주소(webpack.config.js:92)라 API속도 무관.
- 백엔드 동일: `LANGSA_GATEWAY_URL=http://124.194.32.36:32025`(둘 다, `path.ts:6` `process.env` 빌드타임 고정). stream-assist는 `assist-stream.api.ts`에서 이 baseURL로 **브라우저 순수 fetch 직접 호출**(axios·dev-server 프록시 안 거침, devServer.proxy 없음). socket(발화종료 신호)도 `LANGSA_GATEWAY_URL`(useAdvisorbot.ts:155), 채팅 socket은 `VITE_API_CCAAS_ROOT_SERVER`(둘 다 동일).

### 3. 가설 소거
- **#1 서버 리소스 경합**(배포 dev-server가 124서버 CPU 먹어 백엔드 굶김): top -c 확인 결과 dev-server **CPU 한가** → 기각.
- **#2 프록시/TLS/연결수립 지연**(사용자 가설): 배포 stream-assist **TTFB=14.68ms**, Initial connection 미표시(keep-alive 재사용) → 연결·네트워크 정상 → 기각.
- **webpack mode**: `webpack.config.js:18 mode:"development"` 하드코딩(모든 빌드가 dev). 양산화 가치는 있으나(JS 체감), SSE속도와는 무관.

### 4. 결론 — 백엔드 처리 시간
- SSE 특성: TTFB(14ms)는 "연결 열림+200 OK"까지만. 1~2초는 **연결 후 백엔드가 `intent`→`sources` 이벤트 보내기까지**(의도판단+RAG검색) = 우리 speedTrace의 `request→sources` 구간. Network Timing엔 안 잡힘.
- 프론트는 발화종료(final) 즉시 호출(버블 #666 전환=호출 동시, 코드·육안 일치). **느림은 백엔드 영역**. 양산빌드/서버이전 다 헛다리로 확정.
- 액션: 백엔드팀에 `done.stages`(intent/search/distill/generate ms) 기준 병목 분석 요청(특히 search=RAG). 메시지 초안 사용자에게 전달.
- 미결: speedTrace `request→sources` 로컬/배포 직접 비교는 미수행(같은 백엔드라 부하/시점 차이로 추정). 양산빌드(nginx static) 전환은 정석화 차원 보류 — webpack mode 동적화+Dockerfile.5f+compose 수정 설계까지만 해둠(nginx.conf listen 80, SPA try_files 확인).

## 2026-06-19 — AICM 속도 모달 단계 통합 (의도+검색+생성 → "검색(AICM)처리")

### 1. 사고 경위 — 내 오류 → 전부 원복
- 직전 작업에서 모달/배지를 사용자 요구와 다르게 처리: ① 배지 측정 끝점을 `sources`→`done`으로 변경 ② 모달 `STAGE_DEFS`를 `request~done` "AICM 처리" 1막대로 뭉개 **완성(done) 단계가 사라짐**. → `git checkout -- ` 으로 3파일(`assist-stream.api.ts`/`useChatAssist.ts`/`SearchFlowModal.vue`) **전부 원복**. **배지 측정은 원래대로 `sources`(첫 문서 도착) 기준으로 복구**(사용자 확정 A안).

### 2. 모달 단계 통합 (`SearchFlowModal.vue` 단일 파일)
- 확정(사용자): 단계 = `발화수신 → STT타이핑 → 발화종료대기 → 검색(AICM)처리 → 완성`.
  - ⭐ **검색(AICM)처리 = 의도판단(intent)+검색(sources)+생성(token) 3단계 통합**. **완성(done)은 별도 단계로 유지**(통합에 빨아들이지 않음).
- 구현(핵심): `STAGE_DEFS`에서 `intent`/`sources`/`distilled` 제거하고 `token`을 라벨 `"검색(AICM) 처리"`(isKey=true 파랑★)로 변경. `rows`의 *"미수신 stage = prevSince 유지"* 로직 덕에 `token` 막대가 `request` 바로 뒤로 연결돼 **자동으로 `request~token`(의도+검색+생성) 통합 구간**이 됨 → `rows` 계산 로직 자체는 무변경. `done` 막대 = `token~done` = 완성.
- 부수 수정: 마크목록 key 점 조건 `stage==='sources'` → `row.isKey`. 그래프 색상범례 보라(LLM) 항목 제거 → `검색(AICM) 처리(의도+검색+생성)`. 헤더 ⓘ 툴팁 5단계로 축약(의도/검색/선별/생성 → "검색(AICM) 처리 ★ 핵심" 1줄, note에서 보라=LLM 제거).
- 검증: `SearchFlowModal` 타입에러 0. 라이브는 사용자 직접.
- 미해결 인지(추후): 배지값(=`request~sources`, 순수검색)과 모달 통합단계(=`request~token`, 의도+검색+생성)는 **측정 구간이 다름**. 현재 사용자 확정은 "배지=sources 원복" 상태. 추후 배지도 통합구간(생성까지)으로 맞출지는 미정.

### 4. asst-latency(백엔드 구간 분해) 수신 → "검색(AICM)처리" 막대 내부 세분화 (구현 완료, 라이브 검증 대기)
- 배경: 백엔드(asst-service)가 `assist-stream` SSE에 **`asst-latency` 이벤트를 첫 sources 직전 1회** 추가 송출. `{ callId, receivedAt, backendMs, aicmConnectMs, aicmSearchMs, totalMs }` (ms, **백엔드 서버 실측, 네트워크 제외**). `totalMs = backendMs+aicmConnectMs+aicmSearchMs = 접수~첫sources`.
- 확정(사용자): 단계 구조(`발화수신→STT타이핑→발화종료대기→검색(AICM)처리→완성`)는 **그대로 두고**, **"검색(AICM)처리" 막대 1개 안만** 색조각으로 분할(줄 수 불변). 생성은 별도 단계로 안 빼고 막대 안 마지막 조각으로 유지(="있던 자리 그대로").
- ⭐ 막대 내부 5조각(시간축 정합): `request~sources` = **API 접수(backendMs) | AICM 연결(aicmConnectMs) | AICM 검색(aicmSearchMs)★주지연 | 결과 전송(network)**, `sources~token` = **생성**.
  - **network(결과 전송) = 프론트측정(request~sources) − 백엔드 totalMs** (= aicm→api→프론트 경로, 백엔드 미측정분 역산). 스펙대로 "차이분=네트워크". 음수면 0.
  - 사용자 원안의 "aicm 결과 전송(aicm→api)"은 백엔드 미제공 → network(→화면)에 흡수, 대신 "AICM 연결" 포함해 4조각 유지.
  - asst-latency 미수신(수동검색/구버전)이면 `segments=null` → 기존 단일 막대 폴백.
- 구현 파일:
  - `assist-stream.type.ts`: `AsstLatencyEvent` 인터페이스 + `StreamTraceData.asstLatency?` 추가.
  - `assist-stream.api.ts`: `event==="asst-latency"` 수신 시 변수 보관 → `done`의 `onTrace`에 `asstLatency` 동봉. (배지 onTiming=sources, trace 측정 로직 무변경)
  - `SearchFlowModal.vue`: `rows`의 token 행에 `segments`(SegRow[]) 계산 + 템플릿 `v-else-if="row.segments"`로 조각 렌더(hover 툴팁=라벨+초), 색상범례 6항목(API접수/AICM연결/AICM검색★/결과전송/생성+EOU), 하단 `latencyLine`("AICM 실측: …(백엔드 합, 네트워크 제외)"), 헤더 ⓘ 툴팁에 분해 설명.
  - 호출부(`useChatAssist`/`useKnowledgeSearch`)·store(`speedTrace.add`) **무수정** — `add({...meta, ...data})` spread라 `asstLatency` 자동 전파.
- 검증: 변경 파일 타입에러 0. 라이브는 사용자 직접(asst-service 재배포 + 5f 플래그 ON 상태에서 막대 5조각/툴팁/AICM실측 줄 확인).

## 2026-06-22 — assist-stream 렌더링 속도 개선 (집 분석문서 기반, Step1 진단부터)

### 0. 배경/방향
- 집에서 분석한 `docs/frontend-assist-stream-refactoring.md`(2026-06-21 작성, 1주전 소스 기준) 검토. 현재 회사 소스와 **구조 동일, 라인만 +48 밀림** → 그대로 유효 확정.
  - token 핸들러: 문서 422-435 → 현재 `useChatAssist.ts:469-482` (item.data.search_summary deep-mutate + appendAssistStreamToken 둘 다).
  - distilled 자동 상세오픈 `emit("detailItemClick")` 현재 445-467 그대로. 수동(`useKnowledgeSearch.ts`)은 rawAnswer/streamingAnswer 별도문자열(133-139).
- 목표: 자동(assist-stream)이 API 응답후 화면 그려지는 속도 느린 문제 개선.
- 진행 순서 확정(사용자): 제안 3→2 역순(쉬운 것부터). **먼저 body 최소화 진단(Step1), 그다음 throttle(A안=2번).**

### 1. Step1 — body 최소화 진단 (구현 완료, 라이브 측정 대기)
- 함정: 문서는 "query만 보내라"지만 코드 주석상 **workspace_id는 필수**(빼면 RAG 422). → workspace_id는 유지, 나머지(conversationHistory/callId/turnIdx/company)만 미전송.
- 구현(`useChatAssist.ts`):
  - 모듈 상단 토글 상수 `ASSIST_MINIMAL_BODY_TEST = true` 추가(검증 후 false 원복).
  - `callAssistStream` body를 삼항으로 분기: true면 `{ query, workspace_id }`만, false면 기존 전체.
  - `done` 핸들러 맨앞에 진단 로그 `console.log("[assist-stream][done] minimalBody=...", stages, token_usage)`.
- 비교용: 수동 `useKnowledgeSearch.ts` done 핸들러도 `(e: DoneEvent)` 받아 `console.log("[stream/manual][done]", stages, token_usage)` (DoneEvent import 추가).
- 판정 기준(문서 Step1): minimal 전후로 ① done.token_usage.context_tokens 줄어드는지 ② done.stages 어느 단계 빨라지는지 ③ **렌더링 체감 빨라지는지**. 렌더링 여전히 느리면 → 프론트 렌더링이 주범 확정 → Step2(throttle).
- 미수정/인지: `useChatAssist.ts:659 totalCount`, `useKnowledgeSearch.ts:147 error 핸들러 e` 미사용 경고는 기존 코드(내 수정 무관)라 미터치. 라이브 측정은 사용자 직접.

### 2. 모달 'AICM 실측'에 생성 포함 + 배지 = 체감 응답속도 (구현 완료, 라이브 검증 대기)
- 백엔드 답변: done의 stages/token_usage/distill은 asst-service 아닌 **RAG(AICM) 생성값**. asst-service 구간은 asst-latency로 ≈0~2ms 분리 제공 중. 2.7~3.8초는 RAG 처리. → 우리 측정과 일치(갈등 아님). 속도 win은 RAG/AICM 팀 영역.
- 사용자 요청: 모달 'AICM 실측' 줄이 생성 빠져서 '백엔드 보고'와 안 맞음 → **생성 포함**. 모달 고치면 **배지 값도** 같이.
- 원인: asst-latency는 첫 sources 직전 1회라 generate 못 담음 → 생성은 `done.stages.generate`(백엔드 보고 출처)에서 가져와 합산.
- 확정(사용자): 배지 기준 = **체감(request~token, 네트워크 포함)**.
- 함정/결정: 배지 측정끝점을 sources→token으로 직접 옮기면 안 됨 — assist의 timing emit이 distilled 시점(useChatAssist:446)이라 그때 token 아직 없어서 배지로 안 나감. → SSE 계측 무수정, **배지가 trace의 request/token 마크 차이로 request~token 계산**(SearchSpeedBadge), trace 없으면 elapsedMs 폴백. 자동/수동 공통 적용.
- 구현:
  - `SearchFlowModal.vue` latencyLine: `· 생성 {generate}s` 추가, 백엔드 합 = `lat.totalMs + (backendStages.generate ?? 0)`. 제목/범례 '검색속도'→'응답속도'.
  - `SearchSpeedBadge.vue`: seconds = trace token.sinceStartMs − request.sinceStartMs (폴백 elapsedMs). 라벨 '검색속도'→'응답속도'.
  - `assist-stream.api.ts`: 주석만 정정(배지 실제표시=trace 기반 request~token, elapsedMs는 폴백).
- 미해결(출처 차이): AICM 실측 '검색'(asst-service 실측 왕복) ≠ 백엔드 보고 '의도+검색'(RAG 자가보고). 프론트에서 합칠 수 없음 — 그대로 둠.
- 라이브 검증은 사용자 직접.

## 2026-06-22 (이어서) — assist-stream 속도 원인 규명 + 모달 '생성' 값 정합

### 3. 진단 3종 모두 헛탕 → 병목 = 백엔드 RAG(변동) 확정
- 순서: 사용자 요청대로 처음 3,2,1 역순으로 테스트.
- ① body 최소화(ASSIST_MINIMAL_BODY_TEST): conversationHistory/callId/turnIdx/company 빼고 query+workspace_id만. → token_usage는 처음 0으로 보였으나 generate 있는 콜은 context 1008~1875/completion 10~46. **효과 없음**.
- ② 가벼운 stream 엔드포인트(ASSIST_USE_LIGHT_STREAM): 실시간을 callDocumentStream(수동과 동일 경로)로 호출. **동일하게 느림**. → 같은 백엔드 경로인데 수동(~1초)은 빠르고 실시간은 느림 = 엔드포인트/백엔드 파이프라인 차이 아님.
- ③ A안 throttle(useChatAssist token 핸들러): snapshotBuffer에 즉시 누적 + rAF+100ms 가드 flush(leading 첫토큰 즉시), done 강제 flush, error/abort 취소, active-id 가드, 클로저 독립 상태. chatData에 setAssistStreamText 추가. **체감 효과 없음 + "빠를땐 빠르고 느릴땐 겁나 느림"(변동성)**.
- ⭐ 결론: **변동성은 프론트 렌더 특성 아님**(렌더는 토큰수 비례 일정). generate 682~1761ms(2.5배 변동)+intent ~1초 = **백엔드 RAG 생성 지연이 콜마다 다른 것**이 병목. → ①②③ 모두 원복 완료. RAG팀 영역.
- 백엔드 답변(참고): done.stages/token_usage/distill은 asst-service 아닌 **RAG(AICM) 생성값**. asst-service 구간은 asst-latency로 ≈0~2ms 분리. 2.7~3.8초는 RAG.
- "한꺼번에 vs 타이핑" 답변(프론트): SSE 파서 버퍼링 0(sse-parser:30), token마다 즉시 reactive write → **프론트는 done까지 안 모으고 토큰 단위 즉시 렌더**. 한꺼번에 보이면 token 프레임이 네트워크에서 덩어리로 와서 1 read에 동기 처리된 것(=토큰 도착 패턴/B). → RAG팀에 청크 도착시각 로그 요청.

### 4. 유지된 실제 기능(원복 안 함)
- 모달 'AICM 실측' 줄에 생성 포함, 배지 'AICM 응답속도'(request~token, trace의 token-request 마크 차이로 SearchSpeedBadge가 계산, elapsedMs 폴백). 제목/범례 '검색속도'→'응답속도'.

### 5. 모달 'AICM 실측' 생성 값 = 그래프 값으로 정합 (최종)
- 증상: "AICM 실측: …검색 1.05s · 생성 2.58s…" 의 **생성이 위 그래프 '생성' 막대 값과 다름**. 접수/연결/검색은 둘 다 asst-latency라 일치하는데 생성만 done.stages.generate(백엔드 보고값)이라 어긋남.
- 사용자 의도(최종 확정): **그래프/누적타임라인의 생성(프론트 실측)이 정답**, AICM 실측 줄도 그 값을 노출해야 함. (백엔드 보고값 노출이 잘못)
- ⚠️ 시행착오: 처음에 "그래프 생성 막대를 sources→done으로 키워 완성과 합치자"로 오해(거꾸로), 다음엔 latencyLine에서 tokM-srcM 새 수식으로 계산(=사용자가 "수식 바꾸지 마" 거부). → **정답: 새 수식 금지, `rows`의 generate 행 `deltaSec`(이미 화면에 표시되는 그래프 값)을 그대로 재사용.**
- 구현(`SearchFlowModal.vue` latencyLine): `const genRow = rows.value.find(r => r.key === "generate"); genPart = ' · 생성 ${genRow.deltaSec}s'; sum = lat.totalMs + parseFloat(genRow.deltaSec)*1000`. 접수/연결/검색은 asst-latency 그대로. → 그래프 생성과 AICM 실측 생성 항상 동일. 검증 완료(사용자 확인).

### 6. 문서 조기표시(sources) + AI답변 스테일 제거 + 생성중 인디케이터 (구현 완료, 사용자 검증 OK)
- 배경: assist-stream "한꺼번에 펑" 증상. 백엔드도 동의 — trace 분석상 sources(+4.91s)와 첫 token(+9.10s)이 4.19s 차이 = **(가) sources는 일찍 오는데 프론트가 늦게 그림**. (백엔드 청크 로그 불필요 — assist-stream.api.ts markStage가 이벤트별 도착시각 이미 측정)
- 원인(코드): sources 핸들러는 문서를 `pendingAllItems`에 **버퍼링만** 하고, 실제 화면 칩/패널은 **distilled 핸들러**에서 생성(keywordDetailData + detailItemClick 자동오픈). distilled가 token 직전(~9s)에 와서 문서도 그때 뜸. (버퍼링 이유 = distilled.selected_refs로 참고문서만 골라 깜빡임 없이 표시하려고)
- distilled 역할 확인(백엔드 질문 답): **트리거 아님, 내용도 씀** — selected_refs(참고문서 필터/하이라이트) + summary(1차요약 표시/캐시). 그래서 distilled는 계속 받아야 함.
- 구현(`useChatAssist.ts` handleAssistStream):
  - 공통 렌더 함수 `showAssistDocs(displayItems)` 추출(칩 생성+자동오픈+streamingSummaryItems 동기화).
  - **sources**: `showAssistDocs(pendingAllItems.slice(0, MAX_DOCS))`로 상위 3개 즉시 렌더 + 이 버블 요약영역 비움(`emit updateChatSummary ""`) → 직전 버블 요약 잔존 방지.
  - **distilled**: selected_refs로 필터한 displayItems로 `showAssistDocs` 재호출(보정) + `distilledReceived=true`. 0건이면 조기표시 문서 제거(keywordDetailData delete + 선택 해제).
  - done fallback 판정을 keywordDetailData 유무 → `distilledReceived` 플래그로 교체(조기표시 때문).
- AI답변 생성중 인디케이터(`DocumentContentPanel.vue`): chat탭(`alwaysShowAnswer`)이고 summary 비었을 때 `summary-spinner` + "AI 답변 생성 중…" 표시, 요약 도착하면 텍스트로 교체. 검색탭 무영향(always-show-answer는 chat탭에만).
- 트레이드오프(인지): distilled 보정 시 sources 상위3개 → 참고문서로 재정렬 깜빡임 가능. 사용자 수용.
- 최종 동작: 발화 → 문서 먼저 + "생성중" 스피너 → distilled에서 참고문서 보정+요약 채움. 2번째+ 발화도 스테일 없음. 사용자 검증 완료.

### 7. 키워드 상세 문서(최대 3개) 하이라이트 클릭 이동 + 추천/비추천 손모양 숨김
- 대상: 발화 → 키워드 클릭 시 펼쳐지는 **상세 문서 목록**(`chat/index.vue` 376~491). 참고문서 패널(DocumentList) 아님 — 혼동 주의(거긴 thumb 없음).
- 버그: `chat/index.vue:381` `:class="{ 'first-active': detailIndex === 0 }"` 로 **0번째에 보라 테두리 고정**. `handleDetailItemClick`은 지식저장소 표시만 하고 **클릭 문서 추적 상태가 없어** 클릭해도 테두리 안 옮겨감. (CSS는 `.first-active`/`.selected`/`:hover` 모두 `border:2px solid primary` 동일 — index.vue:1934)
- 수정(`useChatKeywordInteraction.ts`):
  - 상태 `selectedDetailItemForBubble: Record<bubbleId, "type_itemId"|null>` 추가.
  - 헬퍼 `isDetailItemActive(bubbleId, type, itemId, detailIndex)`: 선택값 null이면 `detailIndex===0`(첫 문서 강조 유지), 있으면 `type_itemId` 일치.
  - `handleDetailItemClick` 진입 시 `selectedDetailItemForBubble[bubbleId] = type_itemId` 기록.
  - `handleKeywordClick` 진입 시 `= null`로 리셋(키워드 바꾸면 새 목록 첫 문서 다시 강조).
  - return에 둘 다 export.
- 수정(`chat/index.vue`): destructure에 `isDetailItemActive` 추가, 381줄 class를 `isDetailItemActive(item.id, detailGroup.type, detailItem.id, detailIndex)`로 교체.
- 사용자 확정: **클릭 전 첫 문서 강조는 유지**가 맞음.
- 추천/비추천(thumb_up/down) 손모양 숨김: `chat/index.vue:418` 문서별 up/down 버튼 래퍼 `<div class="flex gap4">` → `<div v-if="false" ...>`. **삭제 아님**, v-if만 떼면 복구. (※ SpeechBubble.vue의 키워드 옆 thumb는 별개 — 건드리지 않음)
- 진단 클린(useChatKeywordInteraction의 `isAdmin` unused Hint는 기존부터 있던 것, 무관). 라이브 검증은 사용자 직접.

### 8. (정정·최종) Top3 하이라이트 안 옮겨간 진짜 원인 = `v-memo` + 위치 삽질 + 탭 초기화
> ⚠️ #7은 첫 시도 기록. 실제로는 **두 번 헤맴**(위치 오인 → 원복 → 재적용) 끝에 진짜 원인은 따로 있었음. 아래가 최종.

**(1) 화면 위치 — 처음부터 맞았는데 중간에 의심해서 원복하는 삽질**
- 사용자가 말한 "발화 말풍선 아래 문서 3개 카드"(예: "지식정보" 헤더 + 미래에셋/하나/한국투자 펀드 3개 + 소제목·p.2)는 **`chat/index.vue` 키워드 상세(376~491)가 맞음**. 절대 헷갈리지 말 것.
- 중간에 사용자가 "지식저장소 탭에 이전 기록 남음" 얘기를 꺼내자 **TabTypeKnowledgeIndex로 착각**해 #7 하이라이트 수정을 통째로 원복했다가 다시 넣음. → 두 화면은 별개 이슈. (탭 초기화는 아래 (3))

**(2) 진짜 원인 = `v-memo` (★핵심 교훈)**
- `chat/index.vue:304` 채팅 아이템 `v-for`에 `v-memo="[item.content, item.isStreaming, selectedKeywordForBubble[item.id], keywordDetailLoading[item.id], assistSearching[item.id]]"`.
- `v-memo`는 나열된 값이 안 바뀌면 **그 서브트리 리렌더를 통째로 스킵**. 클릭으로 하이라이트 상태만 바꿔도 v-memo 의존성이 안 바뀌어 **`:class` 재평가가 아예 안 일어남** → 보더가 1번째에 박힘. id 기반이든 인덱스 기반이든 헛수고였던 이유.
- **해결**: 하이라이트 상태를 v-memo 의존성에 추가.
  - `useChatKeywordInteraction.ts`: 인덱스 기반 `activeDetailByBubble: Record<bubbleId, "type_detailIndex"|null>` + `setActiveDetail(bubbleId,type,idx)` + `isDetailItemActive(bubbleId,type,idx)`(null이면 idx===0). `handleKeywordClick`에서 `=null` 리셋. return에 `activeDetailByBubble`/`setActiveDetail`/`isDetailItemActive` 노출.
  - `chat/index.vue`: 381 `:class="{ 'first-active': isDetailItemActive(item.id, detailGroup.type, detailIndex) }"`, 382 `@click="handleDetailItemClick(...); setActiveDetail(item.id, detailGroup.type, detailIndex)"`, **304 v-memo 배열 끝에 `activeDetailByBubble[item.id]` 추가**(이게 결정타).
- 인덱스 기반 선택 이유: 발화 스트리밍 중 문서 객체가 새로 생겨 id가 흔들려도 0/1/2 인덱스는 안정. (사실 진짜 막은 건 v-memo였지만 인덱스 기반이 더 견고하므로 유지)
- 사용자 검증 **OK("잘된다")**.

**(3) thumb(추천/비추천) 숨김 — 유지**
- `chat/index.vue:418` 문서별 up/down `<div v-if="false">`, `SpeechBubble.vue:112` 키워드 옆 `<template v-if="false && !isCallHistoryModal">`. 삭제 아님(`false &&`/`v-if` 떼면 복구).

**(4) 지식저장소 탭 "이전 기록 남음" → 상담뷰 복귀 시 초기화 (별개 이슈, TabType)**
- 진짜 화면: 상담 페이지(`agent/index.vue`)가 쓰는 지식저장소는 `knowledge/index.vue`가 아니라 **`TabTypeKnowledgeIndex.vue`**. 발화 문서는 `selectedDetailItems`에 push → `allTabs`의 chat 탭(문서제목 라벨)으로 생성.
- 원인: 상담뷰는 라우트가 아니라 **`isFirstMount` 토글로 대시보드↔상담뷰 스왑**(컴포넌트 안 죽음) → 로컬 ref `selectedDetailItems`가 안 비워짐. 진입 처리 `handleOnReady`(agent/index.vue, `:onReady`로 전달)의 `if(isFirstMount){ vocStore.clear() }` 블록이 진입 초기화 지점인데 지식저장소 탭은 안 비웠음.
- 수정: 그 블록에 `clearChatSelection()`(chat 탭=selectedDetailItems 비움) + `nextTick(()=>knowledgeRef.value?.resetKnowledgeTabs?.())` 추가. `TabTypeKnowledgeIndex.vue`에 `resetKnowledgeTabs()`(searchSessions=[]·searchText=""·searchSelectedDoc=null·selectedDoc=null·activeTab="") 추가·expose. 사용자 확정: **모든 탭(발화+검색) 전부 초기화**.

---

## 2026-06-23 — AWS 고객사 "AICM 응답속도 상세 모달만 옛날 소스" 미스터리 → 실은 백엔드 데이터 누락

### 1. 증상/의심
- 사용자 보고: 로컬·사내 dev는 배포 즉시 반영되는데, **AWS 고객사 서버만 AICM 응답속도 상세 모달이 옛날 소스로 보임**. "왜 한 페이지만?" 으로 시작.
- 초기 가설: 캐싱/스테일 번들. 구조 파악 결과:
  - 모듈 페더레이션(`advisor_app`, `remoteEntry.js`) + webpack contenthash + nginx no-cache(index.html/remoteEntry.js) — **캐시버스팅 세팅은 정상**.
  - `SearchFlowModal`(AICM 모달) → `TabTypeKnowledgeIndex` → `agent/index.vue` 까지 **전부 정적 import**. 동적 청크/서비스워커 없음 → "한 페이지만 stale"은 구조상 불가. 옛날이면 앱 전체가 옛날이어야 함.
- 배포 방식: **Dockerfile 빌드 → ArgoCD deploy**. 1차 결론(가설): Argo가 같은 이미지 태그면 sync 안 해서 옛 파드 유지 = 운영 이슈 의심.

### 2. 검증 — 배포 마커 박고 재배포 (사용자 요청)
- `SearchFlowModal.vue` 에 **DEPLOY-CHECK 마커 3중** 임시 삽입: ① 모듈 로드 console.log ② 모달 오픈 console.log ③ 모달 하단 화면에 🔴 빨간 박스(`DEPLOY_TAG`). 콘솔 안 열어도 눈으로 확인 가능하게.
- 사용자 재배포 후 캡쳐 2장(`docs/aws.png`, `docs/local_dev.png`) 제공.
- **결과: 양쪽 다 🔴 마커가 떠 있음** → AWS도 최신 프론트 서빙 중. **프론트 배포/Argo 문제 아님이 확정.** (옛날 소스 가설 기각)

### 3. 진짜 원인 = 백엔드 `asst-latency` SSE 이벤트 누락 (AWS만)
- 캡쳐 차이: 로컬은 `API접수/AICM연결/AICM검색/결과전송/생성` **5단계 펼침 + 'AICM 실측' 줄** 표시. AWS는 **`검색(AICM) 처리` 단일 막대로 폴백** + 'AICM 실측' 줄 없음.
- 코드 근거(`SearchFlowModal.vue`): 5단계 펼침은 `if (lat && srcM && reqM)` 일 때만. `lat = tr.asstLatency`. 'AICM 실측' 줄(`latencyLine`)도 **오직 `asstLatency` 있을 때만** 출력 → AWS에서 이 줄이 없다 = **`asstLatency` 가 안 옴**.
- `asstLatency` 출처: 프론트가 만드는 게 아니라 **백엔드 asst-service 가 SSE 로 보내는 `event: asst-latency`** (`assist-stream.api.ts:113`). 타입 `AsstLatencyEvent`(`backendMs/aicmConnectMs/aicmSearchMs/totalMs`, `assist-stream.type.ts:110`).
- `done` 이벤트의 `stages`(의도/검색/선별/생성=backendLine)는 AWS도 정상 수신 → 게이트웨이·스트림 자체는 동작. **딱 `asst-latency` 이벤트 하나만 누락.**
- 결론: **AWS 고객사 asst-service 가 옛 버전이거나(이 이벤트 없던 시절) 설정으로 꺼짐, 혹은 게이트웨이가 SSE 이벤트 버퍼링/필터.** → 백엔드 팀 확인요청 사항으로 정리해 전달.

### 4. 마무리
- DEPLOY-CHECK 마커 3곳 전부 제거(원상복구). grep 확인 "마커 흔적 없음".
- 백엔드 확인요청은 파일 안 만들고 채팅으로만 정리(사용자 요청).

### (부수 발견) `.env.aws` 파일 없음
- `build:aws` = `MODE=aws` → `.env.aws` 읽는데 repo·gitignore 어디에도 없음(추적 env: `.env`, `.env.192.dev`, `.env.5f.dev`, `.env.dev`, `.env.prd`). 빌드서버에만 따로 두는 게 아니면 aws 빌드가 빈 env로 빌드될 위험. 이번 stale 건과는 별개. (확인 미완)

---

## 2026-06-23 (이어서) — VOC 종합 위험지수 고도화 (단순평균 → 가중치+피크 보정)

### 1. 배경/현황 파악
- 헤더(상담내용 영역) VOC 인라인의 "위험도" 숫자 = `chat/index.vue:735 vocAverage`. 클릭 시 「고객 감정 변화」모달(`VocHistoryModal.vue`, SVG 그래프+타임라인) 진입.
- 기존 종합위험도가 **3군데**에서 제각각 단순평균(÷N)으로 계산됨:
  - ① `voc.ts:51 averageScore` = (감정+민원+이탈)/3 → `isDanger`(≥0.8) + `CustomerVocPanel` "종합 위험도" 표시.
  - ② `chat/index.vue:735 vocAverage` = 같은 ÷3 → 헤더 숫자(소수2자리).
  - ③ `emotionVoc.ts:147 buildTotalRisk` = 존재 score 평균(÷N) → 상담이력/요약(`resolveVocView`) 종합위험도 게이지.
- 단순평균 약점 3가지: (a)동일가중 (b)**피크 희석**(0.1/0.1/0.95→0.38 "안전"으로 위험 은폐, 최악) (c)최신 1 turn만(추세 무시).

### 2. 사용자 결정
- 가중치 **감정0.4 / 민원0.4 / 이탈0.2** 확정.
- 2번(피크 보정) 채택 — 가중치만으론 (b) 피크 희석 안 풀려서 같이 가야 의미 완성(내 추천). 3번(추세/누적)·4번(비선형 합성)은 보류·비추천(4번=과잉경보로 0.5/0.8 기준선 직관 깨짐).
- 적용 범위 = **세 군데 다 통일**(화면별 숫자 일관성).

### 3. 구현 (공용 함수 단일 소스)
- `emotionVoc.ts` 에 추가: `VOC_RISK_WEIGHTS{emotion0.4,complaint0.4,churn0.2}`, `VOC_DANGER_THRESHOLD=0.8`, `computeVocRisk(emotion,complaint,churn)`.
  - 가중평균(없는 지표는 가중치 재정규화) → `peak=max(...)` → **peak≥0.8 이면 max(가중평균, peak)** 반환, 아니면 가중평균. 전부 없으면 null.
  - `buildTotalRisk` 를 `computeVocRisk` 호출로 리팩터(level/pct/color 산출은 유지). scores 순서 = [감정,민원,이탈].
- `voc.ts`: `import { computeVocRisk }` + `averageScore` 가 호출하도록 교체(`?? 0`). isDanger 로직(≥0.8) 그대로.
- `chat/index.vue`: import 에 `computeVocRisk` 추가, `vocAverage` 가 호출(`?? 0).toFixed(2)`.
- 전/후 예: 0.1/0.1/0.95 → 기존0.38(안전) → 신규0.95(위험). 0.6/0.7/0.2 → 0.50→0.56. 0.5/0.5/0.5 → 0.50 동일.
- vue-tsc: 내 파일 에러 없음(뜬 건 기존 tsconfig deprecation 2건뿐).

### 4. 미결(사용자 답 대기)
- `CustomerVocPanel.vue:61` 가 비위험 시 **무조건 "· 안정"** 하드코딩 → 0.5~0.8(주의)도 "안정"으로 표시되는 기존 버그. warn 단계 반영할지 사용자 확인 요청함.

### 5. (이어서) CustomerVocPanel 종합위험도 3단계화 + 모달 인포 안내 추가
- **패널 하드코딩 수정**(`CustomerVocPanel.vue`): 기존 위험(≥0.8)/안정 2단계 → **안정/주의/위험 3단계**. `emotionVoc.ts` 에 `resolveRiskLevel(score)` export(임계값·라벨·색 단일 소스, `buildTotalRisk` 도 이걸 재사용) 추가. 패널은 `totalRisk = resolveRiskLevel(vocStore.averageScore)` 로 판정, 템플릿 `voc-total--{level}` + "종합 위험도 NN% · {label}". warn 스타일(앰버 #fef3c7/#b45309, 펄스 없음) 추가. danger(빨강 펄스)·safe(회색) 기존 유지. `isDanger` getter 는 남겨둠(미사용이나 임계값 문서·재사용 목적).
- **모달 인포 보강**(`VocHistoryModal.vue` 범례 툴팁): 기존 "기준: …" 아래에 lg-note 한 줄 추가 — "종합 위험지수 = 감정·민원위험 각 40% + 이탈징후 20% 가중평균. 단, 한 지표라도 0.8↑이면 그 값으로 끌어올림(위험 은폐 방지)." (40%/20%/0.8 `<b>` 강조).
- vue-tsc 관련 파일 에러 없음. 라이브 검증은 사용자.

### 6. (진단) "화남인데 종합 0.0" — 프론트 계산 정상, 백엔드 emotion.score 손상이 원인
- 사용자 테스트: 상담내용 패널 종합지수가 "화남"인데 0.0. 점수계산 검증 요청(+실시간 VOC publish 로그).
- 프론트 경로 확인: display(헤더 vocAverage / 패널 currentItem)는 항상 **마지막 수신 메시지** 기준. `setVoc`(useChatMessageParser.ts:299 호출)가 모든 publish 를 history 에 쌓고 `currentIdx=마지막`. 중복 turn dedup 은 모달(dedupedHistory)만, 헤더/패널은 raw last.
- **계산식 정상 증명**: turn13 정상 publish(emotion0/complaint0.7/churn0.9) → 가중평균0.46, peak0.9≥0.8 → 0.90(위험). 식 OK. all-zero publish 면 당연히 0.00.
- **근본 원인 = 백엔드 데이터 손상 (스모킹건)**: 로그 `[SummaryService] CE emotion API 응답 원문 {"output":{"emotionType":"angry","emotionScore":"。8"}}` — `"0.8"` 의 앞 `0` 이 **전각 마침표 `。`** 로 깨짐 → `parseFloat("。8")=NaN`→0 으로 publish. 그래서 angry/dissatisfied 턴이 type↔score 모순(score 0)으로 옴. emotion 가중치 0.4가 0으로 깔려 종합 위험 deflate(예: turn12 emotion실제화남→0,complaint0.5,churn0.7 → 0.34 안정. 정상이면 peak보정 0.8 위험).
- 부차 원인: 같은 turn_idx 중복 publish 중 all-zero 재평가가 last-wins 로 화면 덮음.
- **결론: 프론트 무수정.** 백엔드에 (1)emotionScore `。8`→`0.8` 파싱 깨짐 수정 (2)score↔type 일치 검증 (3)all-zero 중간 재평가 publish 자제 요청. 프론트 방어(중복 turn 축별 max 병합)는 옵션으로 보류(사용자 선택).

### 7. (추가 증거) score 손상 = 상습·다종 문자·3축 전부 — 원인 ②도 여기로 통합
- 새 로그: `CE emotion API 응답 원문 {"emotionType":"dissatisfied","emotionScore":"،7","churnRiskScore":"،2","complaintRiskScore":"،6"}` → 결과 `VOC 분석 완료(CE): emotion=dissatisfied(0), complaint=0, churn=0` (3축 전부 NaN→0).
- 깨지는 문자 다종 확인: `。`(U+3002 전각마침표, 0.8→。8), `،`(U+060C 아랍쉼표, 0.7/0.6/0.2→،7/،6/،2). 공통 = 앞 `"0."` 이 비-ASCII 구두점 1글자로 치환 → parseFloat NaN → 0. LLM 출력 아티팩트(상습).
- 6번의 원인②(all-zero 중복 publish)가 사실 이 손상의 결과 = **원인 하나로 통합**.
- 영향: emotion 만 아니라 complaint/churn 까지 동시 0 가능 → 위험 고객이 "안정"으로 둔갑(silent 0).
- 백엔드 권고 구체화: parseFloat 전 정규화(비-ASCII 소수점유사글자→`.`, `/-?\d*\.?\d+/` 추출, `.8`→`0.8` 보충), 파싱 실패 시 0으로 떨구지 말고 skip/이전값유지/로그, 근본은 LLM score 를 숫자타입·ASCII로 출력 제약. 프론트는 이미 숫자 0 수신이라 무대응.

### 8. VOC 인라인 기본노출 + 상세아이콘 로컬전용 (chat/index.vue)
- **VOC 인라인 기본 노출**: `adv-voc-inline` 의 `v-if="vocLatest"` 제거 → 데이터 없어도 항상 표시. 기본값 = `resolveEmotionType(undefined)`→**일반**(#94a3b8), `vocAverage`→**0.00**. 실제 수신 시 자동 갱신.
- **감정 변화 상세 아이콘(타임라인 버튼)**: 노출 조건 변천 = `vocHasHistory` → (요청)`v-if="false"` 숨김 → (로컬전용 시도, env방식 검토) → (사용자가 env방식 취소) → 최종 **`v-if="isLocalDev"`**.
  - `isLocalDev = computed(() => location.hostname==="localhost"||"127.0.0.1")`. 로컬(yarn local/local5f, localhost:8173)만 true, 배포(사내 dev/aws 실도메인)는 false. ※ env(VITE_USER_NODE_ENV)는 로컬·사내dev 둘 다 "dev"라 구분 불가 → hostname 방식 채택.
  - 누적 2건(vocHasHistory) 조건은 뺌(로컬선 데이터 없어도 항상 보이게). `vocHasHistory` getter 는 잔존.
  - 사용자 localhost 확인 OK. 임시 콘솔 로그 심었다 제거.

### 9. 감정 미니 스파크라인 (헤더 인라인) — 위험도 숫자 → 감정 점수 + 추이 그래프
- 사용자 요청(voc.png 참고): 위험도(종합) 숫자 제거 → `● VOC {감정라벨}` 옆에 **감정 추이 미니 스파크라인** + **감정 점수(숫자)**. 상세버튼은 localhost 전용 유지.
- chat/index.vue 변경:
  - import 에서 `computeVocRisk` 제거(헤더는 더 이상 종합위험 안 씀). `vocAverage` 삭제.
  - `clampScore` 헬퍼 + `vocEmotionScore`(최신 turn emotion.score, 0.00 기본).
  - `vocEmotionPoints`(같은 turn 중복은 최신 1건으로 dedup → turn당 1점), `vocShowSpark`(≥2건), `vocSparkPoints`(SVG polyline), `SPARK_W=56/SPARK_H=18`.
  - 템플릿: `.adv-voc-score`(위험도 ⋯ 리더) 블록 → `.adv-voc-spark`(svg polyline, 선색=현재 감정색 vocSentimentMeta.color) + `.adv-voc-emotion-score`(숫자). 컨테이너 gap16→gap12.
  - CSS: `.adv-voc-score` 제거, `.adv-voc-spark`/`__svg`/`__line`(non-scaling-stroke) + `.adv-voc-emotion-score` 추가.
- **valign "붕 뜸" 수정**: 고정 0~1 스케일이라 낮은 점수들이 박스 하단에 붙어 떠 보임 → `vocSparkPoints` 를 **데이터 자체 min~max 정규화**(평탄하면 중앙선, pad=3)로 변경해 박스 높이 꽉 채움. (절대값은 옆 숫자가 담당)
- **폭 동적화 + 80px 컷**: `sparkWidth` computed = `min(80, max(36, (n-1)*12+12))`. svg 에 `:style="{ width: sparkWidth+'px' }"`, CSS 고정 width 제거. viewBox(56) 고정 + preserveAspectRatio=none 으로 렌더폭에 맞춰 가로 stretch. 헤더 우측(margin-left:auto) 안 밀리게 cap.
- vue-tsc 통과. ⚠️ 사용자가 "에러 나고 있다" 보고했으나 메시지 확인 전 마무리 결정 → 미진단(다음 세션에 콘솔/터미널 에러 텍스트 확인 필요).

## 2026-06-24 — 상담이력 상세에 감정변화 그래프(VOC 상세) 모달 연결

### 1. 요청/목표
- 상담이력 상세 페이지의 "감정(VOC탐지)" 옆에 그래프 아이콘 추가 → 클릭 시 VOC 상세내역 모달 노출.
- 실시간 화면에서 쓰던 모달 재사용 가능하면 재사용, 데이터형식 다르면 참고해 신규.

### 2. 현황 파악
- 실시간 화면(`chat/index.vue`): 상담내용 헤더에 `timeline` 아이콘(`v-if="isLocalDev"` 로컬전용) → `vocStore.openHistoryModal()` → **`chat/VocHistoryModal.vue`**(SVG 꺾은선 + 턴 타임라인). 이 모달은 **`vocStore.history`(실시간 메모리 `VocMessage[]`)만** 소비.
- 상담이력 상세(`ChatHistoryModal.vue`): `CustomerPanel` 에 `VocDetailBox`(감정/민원위험/이탈징후/종합위험도 정적 박스)만 있고 그래프 없음.
- **데이터 형식 차이**: 신규 API `GET /callstat/calls/by-call-id/{call_id}/voc` 는 **평면형**(`sentiment_type/score/description`, `complaint_risk_*`, `churn_risk_*`), 모달은 **중첩형 `VocMessage`**(`emotion.{type,score,summary}` …). → 매퍼 필요.

### 3. 사용자 확정
- (A) 그래프 아이콘 **항상 노출**(실시간의 isLocalDev 게이트 없이).
- (B) 모달 안내 문구를 이력모드에선 "저장본" 표현으로 교체.

### 4. 구현 (5개 파일)
- `api/apis/callstat.api.ts`: `getVocByCallId(callId)` 추가 — 기존 `getCallSttByCallId`(`/calls/by-call-id/{id}/stt`)와 동일 패턴의 `/voc`. import `VocApiRecord`.
- `api/types/voc.type.ts`: `VocApiRecord`(평면 응답 타입) + `mapVocRecordsToMessages(records)`(→ `VocMessage[]`, turn_idx 오름차순 정렬, description 누락 빈문자열·score 누락 0).
- `chat/VocHistoryModal.vue`: **prop 옵셔널 리팩터링** — `props{modelValue,history,controlled}` + `emit('update:modelValue')`. `controlled=true` 면 v-model·history prop 사용, 아니면 기존처럼 store(`isHistoryModalOpen`/`history`). `sourceHistory` computed 신설(dedupedHistory 가 이걸 참조), replay watch 를 `visible` 기준으로. 안내 툴팁·하단 note 를 `isHistoryMode` 면 "저장된 감정 분석 내역" 문구로. **오버레이 z-index 10000**(`modal-class="voc-history-overlay"` + 비-scoped 스타일) — 콜이력 모달(9999) 위로 뜨게.
- `ChatHistoryModal/CustomerPanel.vue`: "감정(VOC탐지)" 라벨 옆 `timeline` 아이콘(`adv-icon-button voc-history-btn`) + `emit('open-voc-history')`. `defineEmits` 추가.
- `ChatHistoryModal.vue`: import(VocHistoryModal, mapVocRecordsToMessages/VocMessage). state `isVocHistoryOpen/vocHistory/vocHistoryLoading`. `handleOpenVocHistory` = `loadedCall.call_id` 로 lazy 조회 → 매핑 → **데이터 로드 후 오픈**(빈화면 깜빡임·라인 애니 누락 방지). 콜 전환 watch 에서 상태 초기화. CustomerPanel 에 `@open-voc-history`, 템플릿에 `<VocHistoryModal v-model :history controlled />`.
- 실시간 화면(chat/index.vue) **무수정** — store 모드 그대로. IDE 진단 4개 파일 에러 0.

### 5. (확인 메모) 아이콘 위치
- 아이콘이 "감정(VOC탐지)" 섹션(`v-if="voc"`) 안이라 voc 박스 있을 때만 보임. demo4콜·API요약 감정 있으면 OK. voc 없어도 그래프 떠야 하면 위치 분리 필요(보류, 사용자 확인).

### 6. (배포 후 의문 해소) call_id 형태 환경차 = 정상
- 사용자: 로컬/사내dev 는 `test-call-id-1781594701682913912`, AWS 운영은 `698591242540` 로 call_id 형태 다름. base 경로도 `/api/asst/v1/...`(로컬) vs `/aicc/asst-service/...`(AWS) 차이. 둘 다 200.
- 결론 = **프론트 무관, 정상**. call_id 는 우리가 만드는 값이 아니라 `getCallStatById` 응답의 `data.call.call_id` 그대로(오디오 재생 recKey 에도 동일 사용). 환경별 DB 콜 데이터(시드 더미 vs 실 CTI 콜키) 차이일 뿐. 경로 차이는 환경별 `API_PREFIX`(로컬 직접 vs 게이트웨이 경유). 사용자 납득.

### 7. 마무리
- 라이브 검증은 사용자 몫(배포 후 확인). 코드 변경 그대로 두고 기록만. git 미사용.

## 2026-06-24 — workspace_id 하드코딩(env)을 설정 화면 셀렉트/직접입력으로 전환 (store+persist)

### 1. 배경/요청
- 로그인 상담사에게 할당되는 workspace 구조가 미완성 → `.env`의 `VITE_MOCK_WORKSPACE_ID`로 하드코딩해 직접 바라보던 중.
- 우측 LNB "설정" 팝업(현재 "알림" 탭만)에 **WorkSpace설정 탭**을 추가해 셀렉트/직접입력으로 지정. 값은 store(persist)로 보관해 기존 env 활용처에 반영.

### 2. 분석(서브에이전트 3개 병렬)
- env single source: `src/utils/workspace.ts` `getWorkspaceIdOverride()`/`resolveWorkspaceId()`. 소비처 3곳(`agent/index.vue` assignedWorkspaceId computed, `useChatAssist.ts:385`, `ChatHistoryModal.vue:343`). → **utils 한 곳만 store 참조로 바꾸면 3곳 자동 반영**, 소비처 무수정.
- 설정 팝업: `components/layout/Drawer/components/Setting/Setting.vue` — ECPTabs/ECPTabPane 하드코딩(배열X). 알림 탭 1개.
- store: option store, `persist: piniaPersistConfig("키", [paths])` 헬퍼(localStorage), auto-import. UI 컴포넌트 ECPSelect(`:options=[{label,value}]`,`full-width`,`v-model`) / ECPTextField(`v-model`,`placeholder`,`full-width`) 글로벌 등록.

### 3. 사용자 확정
- env 처리: store 저장값 우선 → 없으면 env 기본값(=기본설정). 설정 화면에서 store 갱신.
- UI: 셀렉트(env 기반 프리셋) + 직접입력 둘 다. 라벨은 env `VITE_MOCK_WORKSPACE_LABEL`(추가됨, 대신증권) 활용, env 미인식 시 "기본값". **라벨 필수값**.
- 적용: 저장 후 "새로고침하면 적용됩니다" 안내.

### 4. 구현 (3파일, 소비처 무수정)
- **신규 `src/stores/modules/workspace.ts`**: `ENV_WORKSPACE_ID`/`ENV_WORKSPACE_LABEL`(없으면 ""/"기본값"), `WORKSPACE_CUSTOM_VALUE="__custom__"`, `WORKSPACE_PRESET_OPTIONS`(env 기반 1개, 추후 push). state `selectedWorkspaceId/Label`(빈값=env 사용). getter `effectiveWorkspaceId/Label`(저장값||env). action `setWorkspace/reset`. `persist: piniaPersistConfig("ecp-asst-workspace")`.
- **`src/utils/workspace.ts`**: `getWorkspaceIdOverride()` = `useWorkspaceStore().selectedWorkspaceId || ENV_WORKSPACE_ID`(try/catch env 폴백). `resolveWorkspaceId` 동일 우선순위. `getWorkspaceLabel()` 신설(store||env||"기본값").
- **`Setting.vue`**: `WorkSpace설정` 탭(name="workspace") 추가 — ECPSelect(`wsSelectOptions`=프리셋+직접입력) + isWsCustom 시 id/라벨 ECPTextField. script: workspaceStore + ref(wsSelectValue/wsCustomId/wsCustomLabel) + `initWorkspaceTab`(watch isActive 진입 시 store값 복원, 프리셋 매칭/커스텀 분기, 미저장 시 첫 프리셋) + `handleSaveWorkspace`(커스텀이면 id/label 필수검증, 프리셋이면 label 자동 → `setWorkspace` → "새로고침 적용" info 메시지).

### 5. env 주입 확인
- webpack.config.js:14-15 `dotenv.config({path:.env.${MODE}})`의 모든 키를 DefinePlugin으로 `process.env.*` 주입 → `VITE_MOCK_WORKSPACE_LABEL`도 자동 주입(별도 처리 불필요). 각 env 파일 LABEL 추가는 사용자가 진행.

### 6. 마무리
- 라이브 검증은 사용자 몫. git 미사용.

### 7. (후속) 프리셋 추가 → 강제 새로고침 → env 진단 → workspace_ids 연동
- **다이소 프리셋 추가 + "(현재값)" 표기**: `WORKSPACE_PRESET_OPTIONS` 에 다이소(`019bfe5d-...`) 추가. `Setting.vue` `wsSelectOptions` 에서 `effectiveWorkspaceId` 매칭 옵션 라벨 뒤에 " (현재값)" suffix(표시용, 저장은 원본 라벨).
- **저장 시 강제 새로고침**: `handleSaveWorkspace` 에서 `setWorkspace` 후 토스트 제거하고 `window.location.reload()`(persist localStorage 동기 저장이라 안전). 안내문구 "※ 저장 시 자동으로 새로고침됩니다." 로 변경.
- **"기본값" 노출 원인 = dev 서버 재시작 누락(코드 무관)**: `webpack.config.js:14` `dotenv.config({path:.env.${MODE}})` + DefinePlugin 은 **빌드타임 주입**. `ps` 로 실행중 MODE=5f.local 확인 → `.env.5f.local` 에 LABEL 있으나 서버 시작(오전)이 LABEL 추가(오후)보다 앞서 미반영. 서버 재시작으로 해결. (※ MODE별 파일: local→.env.local[LABEL 누락], local5f→.env.5f.local, dev→.env.development)
- **셀렉트 소스를 get_user `agent.workspace_ids` 로 전환**(궁극 목표):
  - get_user 응답 agent 는 `AppInitializer.ts` getUserInfo → `userProfileStore.setUserProfile` 로 `userProfileStore.agent` 에 저장됨(persist 아님, init 시 채워짐). `agent.workspace_ids` 직접 사용.
  - `workspace.ts`: 하드코딩 `WORKSPACE_PRESET_OPTIONS` **제거**, `labelForWorkspaceId(id)` 추가 = `id === ENV_WORKSPACE_ID ? ENV_WORKSPACE_LABEL : "-"`(라벨 체계 없어 env 매칭 1개만 라벨, 그 외 "-" 고정 — 추후 보완).
  - `Setting.vue`: `wsSelectOptions` = `workspaceIds(=agent.workspace_ids)` 동적 매핑. 라벨이 "-"로 겹쳐 구분 불가 → **"라벨 · workspace_id" 형태로 id 병기** + 현재값 "(현재값)". `initWorkspaceTab` 우선순위 저장값(목록내)>현재 적용값(env)>목록 첫번째, 목록 밖 저장값이면 직접입력 복원. 저장 시 목록항목 라벨은 `labelForWorkspaceId` 자동.
  - IDE 진단 0. ⚠️ 예시 응답 workspace_ids 엔 env id(019eca26…) 미포함이라 전부 "-" 표시 — 실제 환경 응답에 env id 있어야 "대신증권" 매칭.

### 8. 마무리
- 라이브 검증·env 파일 수정은 사용자 몫. git 미사용. 코드 그대로 두고 기록만.

---

## 2026-06-25 — 상담이력 상세 모달 오디오 재생 버튼 아이콘 토글 안 되는 문제

### 1. 증상
- 상담이력 상세 모달(`ChatHistoryModal.vue`) 하단 오디오 플레이어: 재생 버튼 클릭 시 소리는 정상 재생되는데 **아이콘이 계속 `play_arrow`** (pause로 안 바뀜).

### 2. 진단 (임시 로그로 원인 분리)
- `useAudioPlayer.ts` 에 임시 `console.log` 삽입: `togglePlay`(클릭/Promise resolve·reject), `handlePlay`/`handlePause`(audio 이벤트).
- (초반 로그 안 뜸 → 브라우저 캐시였고, 새로고침 후 정상 출력)
- 로그 결과: `togglePlay 클릭(isPlaying=false)` → `event:play 발생 → isPlaying=true` → `play() Promise 성공` → (재클릭) `event:pause → isPlaying=false`.
- **결론: 상태(`isPlaying` ref)는 완벽히 토글됨. 아이콘만 화면 반영 안 됨.**

### 3. 원인
- `ECPIcon`(UI킷 `@timbel-aicc/ecp-ui-kit`)은 `icon` 을 `toDisplayString` 동적 텍스트(patch flag 1)로 렌더 → prop만 바뀌면 갱신돼야 정상.
- `ECPButton` 의 `#append` 슬롯이 내부적으로 Element Plus `ElButton` 을 거쳐 **forwarding(`_:3`)** 되는데, 이 경로에서 `isPlaying` 변경이 슬롯 안 `ECPIcon` 의 `icon` prop 리렌더로 안 이어짐(슬롯 forwarding 리렌더 누락).
- node_modules(UI킷)는 수정 불가 → 호출부에서 해결.

### 4. 조치 (확정·적용)
- `ChatHistoryModal.vue` 의 재생버튼 `ECPIcon` 에 `:key="isPlaying ? 'pause' : 'play'"` 추가 → isPlaying 바뀔 때 아이콘 강제 remount 시켜 현재 prop 반영. (아이콘 1개 remount라 비용 무시)
- 위치: `ChatHistoryModal.vue:146` 부근, `:icon="isPlaying ? 'pause' : 'play_arrow'"` 바로 위에 `:key` 라인 추가.

### 5. 상태 / 남은 정리 (사용자 테스트 대기)
- 사용자가 바로 테스트 못 해서 기록만 먼저. **현재 임시 로그는 그대로 둠**(아직 미제거).
- 사용자 테스트 후 OK 확인되면 → ① `useAudioPlayer.ts` 임시 `[audio]` 콘솔 로그 제거, ② (선택) **이중 이벤트 바인딩** 정리 — template `@play/@pause/@ended...`(ChatHistoryModal.vue:130-142) + `setupAudioEventListeners()` `addEventListener`(useAudioPlayer.ts:100-110)가 같은 핸들러 중복 등록 중. 동작엔 무해하나 정리 후보.
- `:key` 로도 안 바뀌면 대안: 아이콘을 슬롯 밖으로 빼거나 computed 분리.
- git 미사용, 라이브 검증은 사용자 몫.

---

## 2026-06-25 — 어드바이저 고객사 제안서(PPT) 콘텐츠 가이드 작성

### 1. 요청 배경
- 어드바이저 소스를 분석해 고객사 제출용 **제안서 중 "어드바이저" 섹션(4장)** 의 PPT 제작 가이드를 만들어 달라(다른 클로드에게 PPT 작성을 맡길 예정). 전체 제안서가 아니라 어드바이저 한정. 톤: 격식·간결, 마케팅 과장 지양.
- 구성 합의: ①어드바이저 안내 ②주요 기능 ③시스템 아키텍처 ④주요 장점/도입효과.

### 2. 산출물
- `ADVISOR-PPT-GUIDE.md` (asst-web 루트) 생성. 슬라이드별 확정본문 + 시각요소 지시 + 부록A(본문↔소스 매핑) + 부록B(유의사항).

### 3. ⚠️ 미해결 — 슬라이드 1·2 분류 오류 (다음 작업 시 최우선 수정)
- 초기 가이드는 첫 Explore 에이전트 결과를 검증 없이 받아써서 **상담 중/상담 후 분류가 틀림**. 직접 소스 확인 후 정정한 사실관계는 아래(가이드 파일엔 아직 미반영, 그대로 둠).
- **정확한 동작(소스 검증 완료):**
  - **상담 중·실시간(자동)**: ①실시간 대화표시(STT, WebSocket — `useChatMessageParser.ts`) ②AI 실시간 제안 = 발화 끝(EOU) 시 자동으로 의도파악→지식검색→답변 스트리밍(`callAssistStream`, `assist-stream.api.ts`) ← **진짜 핵심, 초기 가이드에서 누락** ③실시간 의도감지 = STT `nlu_result.intent` 매칭(`chat/index.vue:1207`). ※`intent.api.ts`는 의도 마스터목록 조회일 뿐 실시간 분류기 아님.
  - **상담 중·수동**: AI 지식검색 = 상담사 직접 질의(`callDocumentStream`, `document-search.api.ts`).
  - **상담 후·"상담요약" 버튼 트리거**: 버튼 1회로 요약(`createSummary`)+키워드(요약응답 포함)+상담유형 자동분류(요약응답)+감정VOC(요약응답 emotion, 현재 하드코딩)+자동 할일생성(`autoCreateTodo`, 요약 성공 후 연쇄).
  - **이력/관리**: 콜이력·STT조회·채팅이력 / 다중모니터링·성과통계·코칭.
- **초기 가이드 오류 3가지**: ①요약·키워드·감정을 "상담 중 실시간"으로 분류(실제는 요약버튼 후 사후) ②실시간 핵심(발화기반 자동 AI제안) 누락 ③키워드·의도를 묶어 실시간기능처럼 표기(키워드는 요약응답, 의도만 실시간).
- **수정 방향(확정 대기)**: 축을 [상담 중(실시간): 대화표시·AI실시간제안·실시간의도감지·지식검색(수동)] / [상담 후(요약버튼): 요약·키워드·상담유형분류·감정VOC·자동할일] / [관리·이력: 콜이력STT·다중모니터링·성과통계·코칭] 으로 재작성.

### 4. 기타
- "Text Analyzer 시스템" 한 줄 카피 제안: "상담 대화 속에 묻혀 있는 인사이트를 캐내는 분석 시스템"(제안서용 격식: "상담 빅데이터 기반 인사이트 도출 엔진").

### 5. 마무리
- "마무리하자" → 추가 변경 금지, 가이드 파일 그대로 둠(슬라이드 1·2 오류 미수정 상태). 기록만 남김. git 미사용.

## 2026-06-26 — 원본문서 모달 PDF 페이지 단위 위치이동(바로가기) 구현

### 1. 배경/분석
- "원본문서" 모달(`src/view/advisor/components/knowledge/DocOriginalViewerModal.vue`)의 책갈피/인덱스 자동이동 기능 분석.
- **결론: 백엔드 위치정보(offset/anchor/#id) 없음. 순수 프론트 텍스트 매칭 방식.**
  - 이동 대상 = `extractContentFromItem()`(DocumentDetailView.vue:224)이 뽑은 블록 "첫 줄 텍스트"(`activeContent`).
  - `getDocumentOriginal(documentId)`는 원본 파일 바이너리만 받음(위치정보 X).
  - `focusActiveContent()`(DocOriginalViewerModal.vue)가 mammoth 변환 HTML의 `p/li/td/h1~h6`를 `normalizeText` 후 `includes`로 매칭 → 첫 매칭 `scrollIntoView`.
- DOCX만 동작했음. **PDF는 canvas(pdf.js) 렌더라 텍스트 단락 요소가 없어 위치이동 미지원**이었음.

### 2. 결정
- 사용자 요청으로 PDF도 위치이동 구현. 범위는 **"페이지 단위 이동"** 선택(줄 단위 text-layer 방식은 복잡/정확도 들쭉날쭉이라 보류).

### 3. 구현 (DocOriginalViewerModal.vue, +54줄, DOCX 로직 불변)
- `pdfPageTexts: string[]` 추가 — 페이지별 텍스트 보관(index0=1p).
- `renderPdf()`: 페이지 렌더 시 `page.getTextContent()`로 텍스트 추출 보관 + canvas에 `dataset.page` 부여.
- `focusActivePdfPage()` 신규: `activeContent`(100→60→30자 점진 재시도)가 포함된 페이지를 `normalizeText`+`includes`로 찾아 해당 canvas `scrollIntoView({block:"start"})` + `.kms-focus-page`(주황 테두리) 강조.
- `loadDocument` 끝 / `activeContent` watch에 `docKind==="pdf"` 분기 추가.
- CSS `.pdf-page-canvas.kms-focus-page { outline:3px solid #f9c825 }`.

### 4. 한계/주의
- 페이지 "상단"으로 이동(페이지 내 정확한 줄까진 안 감).
- 스캔 PDF(이미지) 등 텍스트 추출 불가 시 이동 안 함(에러 없음).
- pdfjs-dist 3.11.174 사용. lint 에러 11개는 기존 코드(worker import/normalizeText)의 prettier 건으로 변경분과 무관 → 미수정.
- 라이브 검증은 사용자 몫.

## 2026-06-26 — 감정(VOC) 상세모달 상단을 상담이력 상세 종합과 일치시킴

### 1. 문제
- 같은 콜의 감정정보가 세 곳에서 다르게 표시됨: 실시간 미니그래프("화남 0.85") / 상담이력 상세 종합("일반") / VOC 상세모달("불만").
- 사용자 범위: 상담이력 상세(종합) vs VOC 상세모달 불일치.

### 2. 원인 (분석)
- **상담이력 상세 종합**: `GET /summary/data/{id}` 응답의 종합 emotion 1개. `ChatHistoryModal.vue:261` `vocView`=`resolveVocView({callIds, api})` (하드코딩 4콜 우선, 그 외 API).
- **VOC 상세모달 상단**: `GET /callstat/calls/by-call-id/{call_id}/voc` 턴별 기록의 **맨 마지막 턴**. `VocHistoryModal.vue:227` `latest = points[points.length-1]`.
- 즉 API도 다르고(요약 vs 턴별), 산출 기준도 다름(전체 종합 vs 마지막 턴) → 다를 수밖에 없는 구조.

### 3. 결정/수정
- VOC 상세모달 상단(마지막 턴 1줄)을 **상담이력 상세 종합과 동일한 3항목(감정·민원위험·이탈징후)+종합위험도**로 교체.
- `VocHistoryModal.vue`: `summaryVoc?: VocView` prop 추가 → 있으면 상단을 `<VocDetailBox :voc="summaryVoc">` 로, 없으면(실시간) 기존 latest 1줄 유지(실시간 호환). import: VocView, VocDetailBox.
- `ChatHistoryModal.vue:178`: `:summary-voc="vocView"` 전달.
- 그래프/턴별 타임라인은 그대로. 상단만 종합으로 통일됨(같은 vocView 소스라 100% 일치).

### 4. 주의
- 상단 종합=/summary/data, 아래 그래프=/by-call-id/voc 라 백엔드 두 API 산출이 다르면 "상단 vs 그래프 마지막 점"이 미세하게 다를 수 있음 → 백엔드 정합성 이슈.
- lint 에러는 기존 코드(tooltip 문구/console.log/template 헤더)의 prettier 건으로 변경분과 무관 → 미수정. 라이브 검증은 사용자 몫.

## 2026-06-26 — 상담헤더 VOC 미니 스파크에 기본 골격(점선 베이스라인) 추가

### 1. 배경/요청
- 상담내용 헤더 인라인 VOC는 "VOC {감정} 0.00"이 항상 노출되는데, 옆 미니 스파크 그래프는 turn 2건 이상 쌓여야 노출됨(`chat/index.vue` `vocShowSpark = vocEmotionPoints.length >= 2`).
- 사용자 요청: 2건 쌓이기 전(대기 구간)에도 "기본 그래프"를 노출해 휑함/레이아웃 들썩임 방지.
- 협의 결과: 미니(56x18)라 가이드선(0.5/0.8)은 과함 → **회색 점선 베이스라인 1줄** 골격으로 결정.

### 2. 수정 (chat/index.vue)
- template(228~): `v-if="vocShowSpark"`로 span 통째 숨기던 것 → span은 항상 두고 내부에서 분기. 2건↑이면 `<polyline>`(추이선, 감정색), 미만이면 `<line class="adv-voc-spark__baseline">`(가운데 수평 점선).
- script: `sparkBoxWidth` computed 추가 — 추이선이면 동적 `sparkWidth`, 골격이면 고정 36px. svg width를 이 값으로.
- style: `.adv-voc-spark__baseline` 추가(#d1d5db, stroke-dasharray 3 3, non-scaling-stroke).

### 3. 주의
- prettier 경고(229/230 줄바꿈)는 이 파일 원래 관행(template svg 한 줄) + 프로젝트 기존 prettier 미준수(1768 등)와 동일 성격 → 변경분만 관행 따름, 전체 --fix는 미적용(무관 diff 방지). 빌드/동작 무관.
- 라이브 검증은 사용자 몫.

## 2026-06-26 — 관리자 멀티뷰에 상담사별 VOC 위험 비상표시(border 깜빡+토스트)

### 1. 배경/요청
- 고객: "어드바이저가 상담내용을 보는 만큼, 상담사들의 민원 위험을 관리자 페이지에도 표출해야 한다."
- 조사 결과: VOC는 Socket.IO `{env}:{tenant}:{cc_cti_id}:call:voc` 채널로 실시간 수신. 관리자 멀티뷰(`admin/index.vue`)는 `selectedConsultants` v-for로 Chat 인스턴스를 상담사 수만큼 렌더(최대4). Chat(isAdmin=true)은 이미 voc 채널 구독 + 헤더 감정 뱃지 노출 중.
- 두 함정: (1) 헤더는 "감정"만 표시, 민원위험 미표출. (2) `vocStore`가 단일 전역 history라 멀티뷰에서 상담사 VOC가 섞임(모든 카드가 마지막 수신 1건만 봄).

### 2. 확정 스펙 (사용자 결정)
- 위치: 실시간 모니터링 멀티뷰. 시점: 실시간 위주.
- 판정: 종합위험지수(`computeVocRisk`, 피크보정) ≥ `VOC_DANGER_THRESHOLD`(=0.8) 단일 기준. 주의(주황) 단계 없이 **0.8↑ 하나만 비상**. 임계값은 상수 1줄로 조절 가능.
- 알림 A(border): 위험 진입 시 카드 외곽 빨강 깜빡 → **30초 자동 정지 + 카드 클릭 시 즉시 정지**(정지 후 정적 빨강 유지). 0.8 밑→위 재진입 시 재깜빡.
- 알림 B(토스트): `showCustomMessage` 재사용, **위험 재진입(전이)마다 1회** "상담사 OOO이 상담 중 위험 수준에 도달했습니다. 모니터를 확인하세요".
- vocStore는 **정식 per-agent 분리**(사용자 선택). 관리자 간 동기화(한명 확인→전체 끔)는 백엔드 필요 → 범위 밖.

### 3. 핵심 검증 (구현 전)
- `useChatMessageParser.ts:157~172` 가 이미 `resolvedAgentId !== messageData.agent_id` 면 메시지 **drop** → 각 Chat parser는 자기 상담사 메시지만 처리. 따라서 `setVoc`의 `msg.agent_id` = 그 카드 `consultant.agentId` 보장.
- `VocMessage.agent_id` = `consultant.agentId`(`ConsultantDrawer/index.vue:456` `agentId: fallbackAgent.cc_cti_id`) = `cc_cti_id`. 키 일치 확정.
- 멀티뷰에서 전역 store 실제 소비처는 헤더 감정 뱃지뿐(CustomerVocPanel은 비관리자 본인화면 전용, VocHistoryModal 진입버튼은 localhost-dev 전용) → 비관리자 회귀 위험 최소.

### 4. 구현 (additive — 기존 단일 store API 100% 유지)
- `stores/modules/voc.ts`: state에 `byAgent: Record<agentId,{callId,active,history}>` 추가. `setVoc`가 `msg.agent_id`로 슬라이스 분리 저장(call_id 바뀌면 이전 콜 잔상 리셋). getter 추가 `latestOf/historyOf/riskOf/isEmergencyOf(통화중 AND risk≥0.8)`. `endCall(agentId?)`로 종료 시 슬라이스 active=false(비상 해제). `clear()`에 byAgent 초기화. `VOC_DANGER_THRESHOLD` import해 `isDanger`도 상수화.
- `useChatMessageParser.ts:285`: `vocStore.endCall((messageData.agent_id||messageData.agentId||agentId.value))` 로 종료 상담사 키 전달.
- `chat/index.vue`: `vocUseByAgent`(admin/viewer && props.agentId)면 헤더 뱃지/스파크가 `latestOf/historyOf(props.agentId)` 사용, 비관리자는 기존 전역 history 그대로. → 멀티뷰 감정뱃지 섞임 버그도 동시 해결.
- `admin/index.vue`: `.chat-item`에 `:class="vocCardClass(consultant)"` + `@click="acknowledgeEmergency(agentId)"`. `emergencySnapshot`(selectedConsultants×isEmergencyOf) watch로 전이감지→토스트+깜빡, 해제→정지. `emergencyBlink`/`blinkTimers`/`prevEmergency` 맵. onUnmounted 타이머 정리. CSS `.voc-emergency`(box-shadow 링, 레이아웃 밀림 없음)+`--blink`(@keyframes vocEmergencyBlink).

### 5. 상태/주의
- IDE 진단(vue-tsc) 4개 파일 모두 클린.
- 라이브 검증은 사용자 몫. agent_id 매칭은 코드상 보장되나 실데이터로 border 점등은 사용자 확인 필요.
- 비상 단계 시점 조절은 `emotionVoc.ts`의 `VOC_DANGER_THRESHOLD` 한 줄.

## 2026-06-26 — assist top3 추천문서 강조(테두리) 미리셋 버그 수정

### 1. 증상
- 상담 중 STT 버블 아래 추천문서 top3가 뜨고 기본 1번 문서에 테두리. 2번 클릭하면 오른쪽 패널에 그 문서 + 테두리도 2번으로.
- 같은 버블에 새 top3가 갱신되면 오른쪽 패널은 1번으로 가는데 테두리는 직전 클릭(2번 위치)에 남음 → 불일치.

### 2. 원인 (useChatAssist.ts showAssistDocs, 새 top3 공통 렌더 함수)
- 새 문서목록을 `keywordDetailData[messageId]`에 갱신 + 첫 문서로 오른쪽 패널 자동 emit(357~375)은 하는데, 강조상태 `activeDetailByBubble[messageId]`만 리셋 안 함.
- 테두리는 `isDetailItemActive`가 `activeDetailByBubble[bubbleId]`(`"타입_인덱스"`, 위치 기반)로 판정 → 옛 "지식정보_1" 유지 → 새 2번 문서로 테두리가 옮겨붙음.

### 3. 수정 (2파일)
- `useChatAssist.ts`: `UseChatAssistParams`에 `activeDetailByBubble` 추가 + 구조분해. `showAssistDocs` 안에 `activeDetailByBubble.value[Number(messageId)] = null;` 한 줄(자기 messageId 버블만 기본=첫문서로 리셋).
- `chat/index.vue`: `useChatAssist({...})` 인자에 `activeDetailByBubble` 전달(이미 useChatKeywordInteraction이 제공).

### 4. 동작/주의
- 버블별 독립 보존: 리셋은 새 top3를 받는 그 버블(messageId)만. 과거 대화 버블들의 사용자 클릭 선택은 그대로 유지(사용자 확인 요청 반영).
- 한 run 내 sources(미리보기)→distilled(최종) 둘 다 showAssistDocs 호출 → 최종 도착 시 1번으로 정렬(문서목록 자체가 최종본으로 바뀌므로 의도된 동작).
- IDE 진단 2파일 클린. 배포 후 라이브 검증은 사용자 몫.
- (이번 세션 규칙) 코드 수정/문서 저장 전 사용자 confirm 필수.

### 5-1. (후속) 비상 테두리 잘림 수정
- 증상: 라이브 테스트 결과 토스트/깜빡/로직(화남 0.85→비상) 정상인데 카드 테두리가 카드 사이(gap)만 보이고 바깥쪽은 안 보임.
- 원인: `box-shadow` 링은 요소 바깥으로 퍼지는데 부모 `.chat-wrapper { overflow:hidden }`(admin/index.vue)가 잘라냄.
- 수정: `box-shadow` → `border` 로 교체. `.chat-item`에 `box-sizing:border-box; border:2px solid transparent; border-radius:16px`(자리 예약→레이아웃 불변, overflow 안 잘림), `.voc-emergency`는 border-color, 깜빡은 border-color 펄스(#ef4444↔#ffb4b4). 로직 변경 없음.
- 참고: VOC realtime 미표출은 브라우저 캐시 이슈였고 재배포/캐시클리어 후 정상.

### 5-2. (후속) 관리자 비상표시 임계값 0.8→0.6 (관리자 전용)
- 요청: 관리자 쪽 알림은 0.6부터. 적용범위는 "관리자 비상표시만"(상담사 본인 화면은 0.8 유지) 선택.
- 수정: `emotionVoc.ts`에 `VOC_EMERGENCY_THRESHOLD = 0.6` 신설(VOC_DANGER_THRESHOLD=0.8은 그대로). `voc.ts`의 `isEmergencyOf`가 VOC_DANGER_THRESHOLD → VOC_EMERGENCY_THRESHOLD 사용. `isDanger`(본인화면용)는 0.8 유지.
- 효과: 관리자 멀티뷰 테두리/토스트는 종합위험 0.6↑부터 발동(더 빨리 경고), 상담사 본인 화면 위험판정은 0.8 그대로.

### 5-3. (후속) 관리자 비상 임계값을 env로 관리
- 요청: 임계값을 env로 관리. 변수명 `VITE_VOC_EMERGENCY_THRESHOLD`(사용자가 .env.dev에 0.6 설정, 다른 env는 사용자가 처리).
- 빌드구조: 본 프로젝트는 webpack(`webpack.config.js`) + `dotenv` + `DefinePlugin` 으로 `.env.${MODE}`의 모든 키를 `process.env.키`로 주입(접두사 무관). 기존 `LANGSA_GATEWAY_URL` 등과 동일 패턴.
- 수정: `emotionVoc.ts`의 `VOC_EMERGENCY_THRESHOLD` 를 하드코딩 0.6 → `Number(process.env.VITE_VOC_EMERGENCY_THRESHOLD)` 로 읽고, 미설정/비정상(≤0/NaN)이면 0.6 폴백. voc.ts/admin 로직은 그대로(상수만 env 소스로 교체).
- 주의: 빌드타임 주입이라 값 변경 시 재빌드/재배포 필요. 각 env 파일(.env.dev/.env.prd 등)에 변수 없으면 0.6으로 동작.

### 5-4. (후속·중요) 0.6이 안 먹던 진짜 원인 = 판정식, peak 기준으로 변경
- 증상: 임계값 0.6으로 내렸는데도 "0.8 이상일 때만" 비상 발동.
- 원인: isEmergencyOf 가 종합위험지수(computeVocRisk=가중평균+피크보정) 기준이었음. 피크보정은 0.8↑에서만 켜지므로, 0.8 미만에선 감정 단일 고득점이 민원위험·이탈(0)에 희석돼(예: 화남0.7→종합≈0.28) 0.6에 못 닿음 → 사실상 0.8 게이트.
- 결정(사용자): 관리자 비상은 "세 지표(감정/민원위험/이탈) 최대값(peak) ≥ 임계값" 기준. → 화남 0.6도 민원위험 0.6도 잡힘.
- 수정: voc.ts isEmergencyOf 를 riskOf(종합) → latestOf의 peak(Math.max, NaN가드) ≥ VOC_EMERGENCY_THRESHOLD 로 변경. riskOf(종합 getter)는 잔존(미사용, 무해). 임계값/통화중 게이트는 동일.
- env: VITE_VOC_EMERGENCY_THRESHOLD 모든 env파일(.env.dev/local/prd/5f/192)에 0.6 존재 확인. 미설정시 폴백 0.6.

### 5-5. (후속) 실시간 헤더 감정 "이전 콜 잔상" 버그 — 현재 call_id로 스코프
- 증상: 상세/요약은 현재 콜(normal 0.5) 정상인데, 상담사 화면 실시간 헤더만 이전 콜(angry 0.85)이 남음.
- 원인 확정(사용자 로그): 같은 상담사의 서로 다른 콜 2개.
  - call 698591332011 → angry 0.85 / call 698591339066 → normal 0.5.
  - voc 채널은 상담사(cc_cti_id) 단위라 그 상담사 모든 콜이 같은 채널로 옴. vocStore는 call_id 구분 없이 latestItem(마지막 수신)만 표시 → 이전 콜 voc가 늦게/겹쳐 들어오면 잔상.
- 수정(임시방편): useChatMessageParser voc 분기에서 `messageData.call_id !== currentCallId.value` 면 setVoc 스킵(드롭). 현재 콜 voc만 헤더/byAgent에 반영 → 잔상 제거. currentCallId 미설정 시엔 통과(과필터 방지).
- 효과: 헤더가 항상 현재 콜 감정만 표시. 관리자 비상(byAgent)도 덤으로 이전 콜 잔상 방지. IDE 진단 클린.
- 근본개선 여지: vocStore 자체를 call_id 스코프로(콜 바뀌면 確실히 리셋) 두는 것. 지금은 파서 단 드롭으로 처리.

### 5-6. (후속) currentCallId set-once 버그 수정 (voc 필터 정상화)
- 발견: useChatMessageParser 의 currentCallId 가 call:start(229)·nlp:complete(401) 모두 `if(!currentCallId.value)`=비었을때만 세팅 → 첫 call_id에 한번 묶이면 안 바뀜. 그래서 5-5의 call_id 필터가 옛 call_id 기준으로 헛돌아 "현재 콜 normal인데 헤더는 이전 콜 angry" 불일치 발생.
- 수정: call:start(229)에서 `currentCallId.value = call_id` 무조건 갱신(set-once 제거). 새 콜마다 갱신되어 voc 필터가 "지금 보여주는 콜" 기준으로 동작. (nlp:complete 401의 set-if-empty 폴백은 안전망으로 유지)
- 효과: 헤더 감정 = 현재 표시 중인 콜과 일치. 실제 운영(1상담사 1콜)에선 정상.
- 한계(미해결): 같은 상담사 계정으로 4탭(local/dev/prd/admin) 동시 → 같은 per-agent voc 채널을 공유, 4개 call:start를 다 받아 마지막 콜로 수렴. 프론트만으론 "내 콜" 식별 불가. 진짜 해결은 각 화면이 "자기가 만든 call_id"를 브로드캐스트 아닌 생성 시점에서 직접 알아야(또는 백엔드가 채널을 call 단위로 스코프). 사용자에게 own-call_id 출처 확인 요청함.

### 5-7. (마무리) 실시간 헤더 콜 격리 검증 완료 + 속도는 백엔드 이슈로 결론
- 검증: currentCallId(=assist-stream callId)와 voc.call_id 일치할 때만 표시. 실콜 340030(실제 화남 대화)은 표시, 다른 콜 339764는 drop 확인. 헤더가 "현재 보고있는 콜"의 감정만 보여주는 것 정상 동작 확인.
- 다른 VOC 소비처 영향 점검: 필터는 setVoc만 게이트 → 실시간 vocStore 소비처(헤더, 관리자 비상 isEmergencyOf, CustomerVocPanel, VocHistoryModal) 전부 "현재 콜"로 정리됨(개선). 요약/상세(CounselingStatus·ChatHistoryModal)는 resolveVocView=API 경로라 무관.
- 속도(미니그래프/점수가 3~5초 늦게 변함): 숫자+그래프가 동기로 같이 갱신됨 → 프론트 반응성 정상. 지연은 voc 메시지 자체가 늦게 도착(백엔드 감정분석 LLM turn당 3~5초). 프론트에서 고칠 것 없음 → 백엔드 latency 최적화 영역.
- 잔존: 디버그 로그 3개(`[voc] call:start`, `[voc] received`, `[voc] drop stale`) 사용자 요청으로 그대로 둠(동작 영향 없음, 콘솔만 verbose). 추후 운영 정리 시 제거.
- 미해결(범위 밖): 같은 상담사 계정 다중 탭 동시 실콜은 per-agent 채널 공유라 프론트만으론 완전 격리 불가(백엔드가 call 단위 채널 분리 필요). 실운영 1상담사 1콜에선 정상.

### 5-8. (후속) voc "동일 메시지 2번 수신" — 리스너 중복 + 데이터 중복 가드
- 현상(로컬 로그): 같은 call_id+turn_idx voc가 2번 수신(turn3 1번, turn4 2번). type/score 동일 = 진짜 중복 수신.
- 원인: `on("redis-message", onMessage)`(socketIOPlugin.on = socket.on, 중복방지 없음)가 중복 등록되면 메시지 1개를 2번 처리. 로컬은 HMR(파일 편집마다 setup 재실행→리스너 누적)이 유력. turn3(편집 전)1번/turn4(편집 후)2번 정황 일치.
- 수정(가드 2개):
  - useChatSocket `setupListeners`/`onConnectCallback`: `on` 전에 `off("redis-message", onMessage)` → 같은 인스턴스 재셋업 시 중복 등록 방지.
  - useChatMessageParser: `seenVocKeys` Set 추가, voc 분기에서 `(call_id:turn_idx)` 이미 수신했으면 drop(첫 값 유지). call:start 시 clear.
- 효과/한계: 백엔드 중복 publish + 동일 인스턴스 중복셋업 → 가드로 차단됨. HMR로 "다른 인스턴스" 리스너가 누적된 경우(각자 seenVocKeys 별개)는 가드로 못 막음 → 로컬은 하드리프레시로 해소(운영 빌드는 HMR 없어 무관).

### 5-9. (세션 마무리 요약) — VOC 실시간 작업 전체
오늘 VOC 관련 작업 총정리 (상세는 5-1~5-8 참고):

**A. 관리자 멀티뷰 민원위험 비상표시 (신규)**
- vocStore에 per-agent(byAgent) 레이어 추가, isEmergencyOf(통화중 AND peak≥임계값) — peak=감정/민원/이탈 최대값.
- admin/index.vue: 카드 빨강 테두리 깜빡(30초 자동/클릭 정지) + 토스트(위험 재진입마다). 테두리는 border 방식(overflow 안 잘림).
- 임계값: env `VITE_VOC_EMERGENCY_THRESHOLD`(폴백 0.6). 상담사 본인화면 위험판정(VOC_DANGER_THRESHOLD=0.8)은 별개 유지.

**B. 추천문서 top3 테두리 잔상 (버그수정)**
- useChatAssist.showAssistDocs에서 새 top3 도착 시 activeDetailByBubble 리셋(첫 문서로). 버블별 독립 보존.

**C. 실시간 헤더 감정 "다른 콜/중복" 오염 (버그수정)**
- chat 헤더를 per-agent 슬라이스로(관리자 모드), 비관리자는 전역 history.
- currentCallId set-once 버그 수정(call:start마다 갱신).
- voc를 현재 call_id로 필터(다른 콜 drop) + (call_id:turn_idx) 중복 dedup(첫 값 유지).
- 리스너 중복 등록 방지(off→on).

**미해결/이관 (백엔드 영역)**
- voc 분석 latency 3~5초(LLM): 프론트 즉시 표시, 백엔드 최적화 필요.
- 같은 상담사에 동시 다중 콜을 화면별로 격리: per-agent 채널 구조 한계 → 백엔드가 call_id 단위 채널 분리 또는 중복 publish 방지 필요. (요청서는 대화 내 정리해둠)

**잔존 디버그 로그(의도적 유지, 동작 무관)**
- `[voc] call:start`, `[voc] received`, `[voc] drop stale`, `[voc] drop dup` — 운영 정리 시 제거 예정.

**변경 파일**: stores/modules/voc.ts, utils/emotionVoc.ts, view/advisor/admin/index.vue, view/advisor/components/chat/index.vue, .../chat/composables/useChatMessageParser.ts, .../useChatAssist.ts, .../useChatSocket.ts, .env.*(VITE_VOC_EMERGENCY_THRESHOLD)

## 2026-06-29 — 관리자 설정▸키워드 기능 분석 + 감지카운트 로직 공용화

### 1. (분석) 키워드 기능 전체 구조 파악
- 진입: 우측상단 설정 메뉴 → `AdminSetting.vue`(알림/키워드 탭). 키워드 탭이 분석 대상.
- 3레이어: [등록/관리] AdminSetting.vue ──CRUD──▶ /keyword-detects(백엔드 실연동) / [상태] stores/modules/keywordDetect.ts / [소비] useTextRenderer(마스킹)·Keyword.vue·ChatAdminPanel(카운트).
- 카테고리 3종: 금칙어 forbiddenWord / 이슈어 issueWord / 비속어 profanityWord.
- 핵심 결론: **백엔드로 가는 건 키워드 "정의"(등록/삭제)뿐, 감지·카운트·마스킹은 전부 클라이언트 사이드.**

### 2. (분석) 주요 발견/함정
- 용도 2가지: (a)본문 마스킹(useTextRenderer, **금칙어는 제외** → 원문 노출, maskText의 forbiddenWord 분기는 죽은 코드) / (b)감지 카운트(전 카테고리). 둘 다 user 발화만.
- 감지 카운트는 Vue computed로 렌더마다 실시간 재계산되는 일회성 통계 → **DB에 안 쌓임**, assist-stream(RAG)과 무관. 누적지표 필요하면 신규구현.
- 비속어 시드 사전 프론트에 없음 → 전부 수동등록 의존(백엔드 시드 여부는 API 확인 필요).
- isSystem 항상 false 고정 → 시스템 태그 스타일 안뜸/전부 삭제가능. store의 check*·replaceKeywordsWithLabels 4함수 사용처0(죽은코드). updateKeywordDetect(PATCH) UI 미사용(등록/삭제만, 의도된 단순화 유지 결정).

### 3. (수정) 감지 카운트 로직 공용화
- 문제: Keyword.vue와 ChatAdminPanel.vue에 동일 issueKeywords 집계 로직 복붙, 한쪽(ChatAdminPanel)만 빈값가드 있어 미묘하게 어긋남.
- 변경:
  - keywordDetect.ts: `IssueKeywordCount` 타입 export + 공용 액션 `countIssueKeywords(chatContent)` 신설(빈값가드 포함 버전으로 통일, user 발화에서 등록키워드 출현수 집계→count 내림차순).
  - ChatAdminPanel.vue / Keyword.vue: issueKeywords computed를 store 액션 호출 한 줄로 교체(~55줄→3줄). Keyword.vue의 디버깅 console.log 전부 제거. Keyword.vue의 props.chatContent||activeChatContent 폴백은 컴포넌트단 유지.
- 결과: 동작 동일, 두 vue 진단 에러 0. 집계규칙은 store 한 곳만 고치면 양쪽 일관. (테스트는 사용자가 추후 진행)
- 변경 파일: stores/modules/keywordDetect.ts, view/advisor/components/chat/ChatAdminPanel.vue, components/layout/Drawer/components/Keyword/Keyword.vue.

### 4. (문서) docs/advisor-admin-operation.md에 "5. 설정▸키워드" 섹션 추가
- 공지(4장) 뒤에 5장 신설, 기존 권한→6·파일맵→7로 번호 밀고 파일맵 테이블에 키워드 관련 파일 추가.

### 5. 잔여 메모(미수정)
- Keyword.vue 제목 "감지된 이슈어" vs 로직은 전 카테고리 카운트(불일치). 상단 위/아래 화살표 버튼 console.log만(미구현).
- 금칙어 마스킹 제외가 의도인지 버그인지 기획 확인 필요.

### 6. (진단) 상담 종료 후 상담요약 팝업/자동 /summary 미작동 — orchestrator:persisted 추적
- **증상:** 오늘 아침부터 상담대화 종료 시 상담요약 팝업이 자동으로 안 뜨고 `/summary`·`/summary/data` 자동호출이 안 됨. (6-16에 한 번 잡았던 이슈가 재발)
- **자동 트리거 체인 재확인:** 백엔드(STT엔진)가 Redis `{env}:{tenant}:{agent_id}:call:orchestrator:persisted` publish → `useChatMessageParser.ts:636` 분기 → store에 call_id/callstats_id 저장 + `emit("orchestrator-persisted")` → chat/index.vue 재emit → `agent/index.vue:909 handleOrchestratorPersisted` → ContentLayout→HeaderActionBar `openCounselingStatusAndExecuteSummary`(:488, 팝업 visible=true + `handleSummary` 실행) → `CounselingStatus.vue:304` POST /summary → 성공 직후 :332 POST /summary/data(자동저장) + :349 todos/auto-create. ⇒ 팝업·요약·자동저장·할일생성 **전부 이 한 메시지 수신에 묶여있음.** `/summary` 호출처는 전 코드베이스에서 `CounselingStatus.vue:304` 단 1곳(=handleSummary, 버튼 클릭 or 이 이벤트로만 실행).
- **프론트 silent-drop 게이트:** `useChatMessageParser.ts:163~178` — 모든 redis 메시지 공통으로 `resolvedAgentId(=cc_cti_id) !== messageData.agent_id` 면 `return`. **nlp/voc 채널만 진단로그 있고 orchestrator:persisted는 로그조차 없어** "이유 모르게 안 됨"으로 보임(백엔드 탓 오해 유발).
- **회귀 여부 배제:** 6-26(정상본 efc45bc)→HEAD diff 확인. 오늘 바뀐 파일 5개(Keyword.vue, keywordDetect.ts, ChatAdminPanel.vue, useChatMessageParser.ts, CLAUDE-todo.md) 중 **orchestrator:persisted 팝업 체인 파일은 0개 변경**. useChatMessageParser 변경분도 전부 STT발화/assist(triggerAssist) 경로뿐 — orchestrator 분기(636~)·agent_id 게이트(168) 미변경. ⇒ **프론트 회귀 아님 확정.**
- **STT payload 명세 확보:** persisted payload = `{tenant_id, agent_id, call_id, callstats_id, ts}`. callstats_id/call_id 정상 포함 ⇒ 41번(callstats_id 누락)류 아님. 관건은 **agent_id 값이 cc_cti_id냐**. 같은 STT엔진의 nlp/events/voc는 정상 수신 중(=그 채널 agent_id는 cc_cti_id로 정렬돼 옴)인데 orchestrator:persisted만 안 옴 ⇒ **이 채널만 agent_id 정렬 안 됨(또는 채널명 {agent_id} 자리 불일치)** 으로 추론.
- **실제 원인/해결:** **Redis + callbot 문제로 확인되어 해결됨.** (프론트 코드 수정 없음.)
- **재발 시 1초 진단:** 콘솔 `[nlp:complete] ... agent=XXXX` 값(=cc_cti_id 기준) ↔ orchestrator:persisted payload `agent_id` 비교. 다르면 백엔드/채널 정렬 문제. 로그가 아예 없으면 메시지 미도착(redis/callbot/구독).

### 7. (수정) Redis/Socket 채널 prefix 환경변수 분리 — 환경 간 교차수신 차단
- **배경:** 하나의 Redis 를 local/사내개발/AWS개발 이 같은 계정(같은 vendor_tenant_id/cc_cti_id)으로 공유 → 채널명이 전부 동일해 환경 간 메시지 교차수신. 채널 맨 앞 prefix(기존 `dev` 고정)를 환경변수로 빼서 분리.
- **대상 5채널(형식):** `{ENV}:{vendor_tenant_id}:{cc_cti_id}:call:` + `nlp:complete` / `nlp:partial` / `voc` / `orchestrator:persisted` / `events`.
- **`{ENV}` 출처 확정:** `redisKey.ts`의 `getRedisKey()` 가 5채널 전부 생성. 기존엔 `process.env.VITE_USER_NODE_ENV`(dev/prd 빌드구분용)를 prefix로 재활용 → dev계열 빌드는 전부 `dev`라 분리 불가. webpack이 `.env.{MODE}`만 읽음(`.env`최상위는 미로드).
- **변경 내용:**
  - `src/utils/redisKey.ts`: prefix 전용 변수 신설 `export const CHANNEL_ENV = process.env.VITE_REDIS_CHANNEL_ENV || "dev"`(fallback dev). 5채널 prefix를 이 값으로 통일. (VITE_USER_NODE_ENV 의존 제거)
  - `src/view/advisor/admin/index.vue:302`: `dev:...:call:events` 하드코딩 → `getRedisKey(vendor_tenant_id, item, "events")` 호출로 교체(import 추가). 하드코딩 제거 + 타 화면과 동일 함수로 통일.
  - env 6개에 `VITE_REDIS_CHANNEL_ENV` 추가: `.env.dev`=`dev`(사내개발=AWS), `.env.prd`=`prd`(운영), 그 외 4개(`.env.local`/`.env.5f.local`/`.env.5f.dev`/`.env.192.dev`)=`localDev`. `.env`(최상위)는 미로드라 제외.
- **그대로 둔 것:** `admin/index.vue:503` `dev:global:call:status:active`(5채널 외, dev 고정 유지·사용자 결정). 메시지 필터링 코드(`useChatMessageParser.ts`·`Dashboard.vue:362`·`ConsultantDrawer:353`의 `.includes(":call:voc/events")`)는 suffix만 검사 → prefix 무관, 영향 0. 테스트 spec의 `dev:` 하드코딩도 동일 이유로 그대로.
- **구독 구조(코드 확인):** 프론트가 `POST /aicc/asst-service/redis-monitor/subscribe/{채널명}` 으로 채널명을 그대로 백엔드(redis-monitor)에 전달 → redis-monitor가 그 채널 SUBSCRIBE 후 socket room 으로 relay. 즉 **백엔드 구독(relay) 쪽은 프론트가 보낸 채널명 그대로 따라감**(프론트 변경만으로 자동). (subscribe.api.ts:21, SocketChannelManager.ts:17)
- **핵심 결론 — 발행자 의존성:** redis-monitor 는 relay 만, 실제 PUBLISH 주체는 별도.
  - `call:voc` → asst-service 자체 발행, 이미 `VOC_CHANNEL_ENV=localDev` 맞춤 ✅
  - 나머지 4개(nlp complete/partial, events, orchestrator:persisted) → **외부 서비스**(STT/NLP·callbot-orchestrator)가 발행. asst 코드엔 events/persisted 참조 0건. 현재 공용 dev 파이프라인이라 `dev` prefix로만 publish 중.
  - ⇒ **`localDev` 로 바꾼 환경(local/5f/192)은 voc만 수신되고 나머지 4개는 발행자가 dev로 쏘는 한 안 들어옴**(버그 아님, 분리의 정상적 결과). 받으려면 발행 서비스 env 도 `localDev` 로 맞추거나 local 전용 파이프라인 필요.
  - **`.env.dev`(사내개발/AWS)는 prefix 그대로 `dev` → 발행자(dev)와 짝 그대로 → 4채널 영향 0**(기존과 동일 동작).
- **상태:** 프론트 코드 정합·완료. 배포 후 라이브 테스트는 사용자 진행 예정. 발행 서비스(STT/NLP·callbot-orchestrator) 관리주체에 따라 local 4채널 완전분리 가능여부 갈림(백엔드와 후속).
- **변경 파일:** src/utils/redisKey.ts, src/view/advisor/admin/index.vue, .env.dev, .env.prd, .env.local, .env.5f.local, .env.5f.dev, .env.192.dev.

## 2026-06-29 — 코칭요청 "확인완료" 미동작 → 미확인/확인완료 토글 + 알림 카운트 누적 수정 (상담사 기준)
- **증상(사용자):** 관리자 코칭을 받으면 카드에 "확인완료"가 떠 있는데 클릭이 안 되고, 우측 LNB 코칭요청 알림 숫자가 계속 누적됨.
- **소스 구조 파악:**
  - 카드 = `Drawer/components/CoachingRequest/CoachingRequestCard.vue`. 버튼 2종이 `isConfirmed`로 갈림 — `!isConfirmed`→`[확인]`(@click handleConfirmed, emit confirmed) / `isConfirmed`→`[확인완료]`(@click 없음, cursor:default = 완료표시용). ⇒ "확인완료"는 원래 클릭 대상이 아님(정상).
  - 부모 = `CoachingRequest.vue`. `@confirmed → handleConfirmed(item.confirmTarget, v)`(:549) → `onReadCoaching`/`onReadRequestCoaching` → `refreshCoachings`. 알림숫자 `unReadCount` 계산은 watch(:420).
  - 카운트 공유필드 `coachingStore.unReadCount` 를 **3곳에서 읽고**(CoachingRequest 뱃지 hearing아이콘 / HeaderActionBar history아이콘=관리자 / Dashboard) **3곳에서 다르게 씀**(CoachingRequest:420 `!isConfirmed`.length / AdminCoaching.vue:459 미답변기준 / coaching.ts:84 =0).
- **누적 진짜 원인:** CoachingRequest:420 카운트가 merged-list(`requestCoachings`+`receiverCoachings`)를 `!isConfirmed`로 셈 → ① 코멘트(관리자응답) 없는 카드는 `v-if="comment"`로 확인버튼 자체가 안 뜨는데 `isConfirmed=false`라 카운트엔 잡힘 → 영원히 못 빼고 누적, ② 내가 보낸 요청까지 합산. "확인완료" 버튼 미동작이 원인 아님.
- **도메인 정리:** coachings(관리자→상담사, is_read=상담사가 읽음 = "받은 코칭" = 미확인 대상) vs coaching_requests(상담사→관리자, is_read=관리자가 읽음, 내가 보낸 것=카운트 제외).
- **API:** 핵심 3개 이미 존재 — `GET /coachings/receiver/{id}`(목록+is_read), `PATCH /coachings/{id}/read`(단건 읽음=미확인 클릭), 개수는 목록서 프론트 계산. (선택 신규: unread-count 단건조회 / 상담사용 일괄읽음 `PATCH /coachings/read {ids}` — "모두 확인" UX 넣을 때만. 백엔드에 받은코칭 id 접두사 `coach_` 확인요청.)
- **결정:** Q1 알림숫자=받은 코칭 중 미확인 개수(우측 LNB)로 확정. Q2 새로 구축: 처음 "미확인"(클릭가능)→클릭→"확인완료"(완료표시). **충돌처리는 B = 상담사 기준만, 관리자 로직(AdminCoaching.vue) 미수정.**
- **수정(2곳, 상담사 경로만):**
  1. `CoachingRequestCard.vue`: 클릭 버튼 라벨 `확인`→`미확인` (완료상태 `확인완료` 유지).
  2. `CoachingRequest.vue:420`: 카운트 기준 교체 `coachingStore.receiverCoachings.filter(c=>!c.is_read).length` (merged-list `!isConfirmed` 제거). ⇒ 코멘트없는 카드/내가 보낸 요청 카운트서 빠짐, "미확인" 클릭→readCoaching→refresh 시 is_read=true 되어 숫자 감소.
- **그대로 둠:** handleConfirmed(:549)은 받은 코칭을 readCoaching로 처리+refresh하므로 동작 OK라 미변경. AdminCoaching.vue/HeaderActionBar/Dashboard 미변경.
- **상태:** 프론트 수정 완료. 라이브 검증은 사용자 진행 예정.

### (이어서) handleConfirmed 분기 정리 + LNB 숫자 출처 확인
- **LNB "코칭요청 N" 출처:** 하드코딩 아님. LNB 항목 자체가 `CoachingRequest`(Drawer/index.vue:18, is-admin=false), 뱃지=`coachingStore.unReadCount`. 데이터는 실 API(`coaching.ts:45,48` = `GET /coachings/sender|receiver/{id}` 응답). 상담사 진입 시 `agent/index.vue:423,562`서 `refreshCoachings(false)` 자동 호출로 채워짐.
- **3요소 단일 매핑 확정:** LNB숫자(`receiverCoachings.filter(!is_read).length`) ↔ 카드 미확인/확인완료(`isConfirmed=받은 코칭 is_read`) ↔ 미확인 버튼(`!isConfirmed`) — 전부 받은 코칭+is_read 한 소스. "안 읽은 받은 코칭 1건 = 숫자+1 = [미확인] 버튼 1개", 클릭→read→refresh→확인완료+숫자-1. 추가 매핑 작업 불필요.
- **백엔드 회신 확인:** `PATCH /coachings/:id/read`(coach_, body없음, 응답 is_read:true) 단건만. 일괄(`/coachings/read {ids}`) 미존재("모두 확인" 필요 시 신규). 프론트 경로 이미 일치(path.ts:30-31 COACHINGS=/coachings, COACHING_REQUESTS=/coachings/requests) → 기존 `readCoaching`이 곧 그 엔드포인트. 신규 API 불필요.
- **수정3:** `CoachingRequest.vue handleConfirmed` 의 `startsWith("coachrq_")` 분기 제거 → 받은 코칭은 무조건 `onReadCoaching`(PATCH /coachings/:id/read). 백엔드 "분기없이" 가이드와 일치, 오API 위험 제거.
- **잔여(의도적 보존):** 분기 제거로 `onReadRequestCoaching`(coaching.ts) + `readCoachingRequest`(api) 가 미사용 상태가 됐으나, 유효 엔드포인트(`PATCH /coachings/requests/:id/read`) 바인딩이라 향후 코칭요청 읽음처리용으로 삭제 않고 보존.
- **최종 변경 파일:** CoachingRequestCard.vue(라벨 확인→미확인), CoachingRequest.vue(:422 카운트 기준, handleConfirmed 분기제거). AdminCoaching/HeaderActionBar/Dashboard/store/api 미변경.

## 2026-06-29 — RAG 원본보기 하이라이트(책갈피) 위치 불일치 수정 (heading_path/page_number 앵커)
- **증상:** AI답변 출처 제목 클릭 → 원본보기 모달이 책갈피(제목)로 하이라이트하는데 위치가 안 맞음. 특히 표(table) 많은 펀드문서.
- **"책갈피"의 정체:** 제목이 아니라 **출처 content의 첫 줄**이었음. `useKnowledgeSearch.ts:114 blocks=item.content` → `DocumentDetailView.vue:228 extractContentFromItem = blocks.split("\n")[0]` → 그 첫 줄이 activeContent로 뷰어에 전달 → `DocOriginalViewerModal focusActiveContent`가 `slice(0,100)` 정규화 후 단락에 `includes`.
- **불일치 근본원인:** ① 백엔드 content는 **마크다운 표**(`| 종류 | 보유기간 | 환매수수료 |`)인데 렌더된 DOCX는 진짜 `<table><td>`라 파이프가 없음 → normalizeText가 `|`/`---` 안 지워서 표 출처는 매칭 실패. ② 단일요소 통째 includes라 mammoth 단락분할에 취약. ③ `source_location`(heading_path/page_number/offset)이 sources에 다 오는데 focus 로직이 하나도 안 씀(타입도 page_number/bbox만 정의). ④ 첫 매칭 break.
- **결정:** git 회귀추적 중 사용자가 "그냥 제안 방식으로 수정" 지시 → 재설계(B: heading_path 앵커 + A: 마크다운 정제 + 타입확장) 채택. (원본은 PDF/DOCX, txt는 SSE 샘플일 뿐 확인.)
- **수정(6파일):**
  1. `api/types/assist-stream.type.ts`: `SourceLocation` 타입 신설(file_url/page_number/start·end_char_offset/heading_path/sheet_name/table_index/paragraph_index). SourceItem.source_location 교체.
  2. `DocOriginalViewerModal.vue`: prop `sourceLocation?(SourceLocation|string|null)` 추가. `parseSourceLocation`(객체/JSON문자열 모두), `stripMarkdown`(|,---,#*`> 제거), `focusByHeadingPath`(heading_path 마지막값으로 h1~h6 우선 탐색→p/li/strong/td/th, 동일/시작/포함(4자+) 매칭) 신설. focusActiveContent=heading_path 우선→content 폴백(마크다운정제). focusActivePdfPage=page_number 우선 점프→텍스트 폴백. activeContent watch에 sourceLocation 추가.
  3. `composables/useKnowledgeModals.ts`: `originalViewerSourceLocation` ref + openOriginalViewer 3번째 인자 + return.
  4. `knowledge/index.vue`: destructure + 모달 `:source-location` 바인딩.
  5. `TabTypeKnowledgeIndex.vue`: 자체 host도 동일(ref/3번째 인자/바인딩).
  6. `DocumentDetailView.vue`: inject 시그니처 3번째 인자, handleOpenModal에서 `props.document.source_location` 전달.
- **회귀 안전:** heading_path/page_number 없으면 기존 content 텍스트매칭으로 폴백 → 예전 되던 일반문서 동일 동작.
- **데이터경로 검증:** `useKnowledgeSearch.ts` 결과객체 최상위 `source_location: item.source_location`(raw, heading_path 포함)이 `props.document`까지 생존. 유일 주입처=DocumentDetailView, 유일 호출부=handleOpenModal.
- **상태:** 프론트 수정 완료. 라이브 검증 사용자 진행 예정.

## 2026-06-30 — 원본보기 본문 범위 하이라이트 안 됨(제목만) 수정 + 리스트 제목 heading_path 적용
- **증상1:** 재택(06-29) 작업 후 회사 테스트 시 원본보기에서 **제목만 하이라이트**되고 본문(섹션 범위)이 안 칠해짐.
- **진단(디버그로그 `[민누이로그]` 임시 삽입):** 제목 매칭은 정상(heading_path "매입·환매 방법" 포함일치, startIdx 87). 근본원인은 **`sectionContentLen: 0`** — 모달에 도착한 `sectionContent`가 빈 문자열. `DocumentDetailView.handleOpenModal`이 `props.document.content` 하나만 봤는데 수동검색/탭 흐름에선 최상위 content가 비고 **섹션 본문은 `contents.outline[].blocks`에만** 살아있었음.
- **수정1(`DocumentDetailView.vue`):** `extractFullSectionContent(item)` 헬퍼 신설(blocks 문자열이면 통째, id배열이면 blocks_map 조인). `sectionContent = document.content || extractFullSectionContent(openItem) || ""` 폴백.
- **증상2:** 본문 범위는 칠해지나 제목은 테두리박스, 본문은 배경만. → 본문도 제목처럼 **테두리 박스** 요청.
- **수정2(`DocOriginalViewerModal.vue`):** 범위 블록 모아 첫블록 `.kms-focus-range-first`/마지막 `.kms-focus-range-last` 부여. CSS: 양옆 테두리 전블록 공통+위/아래는 첫·마지막만+블록간 margin 0 → 끊김없는 한 박스. clear 로직에 새 클래스 2개 추가.
- **증상3:** 마크다운 표 구분선 `| --- | --- |` 이 박스 중간에서 따로 놂. → 압축비교 시 `-`/`|` 제거로 빈텍스트가 돼 `continue`로 스킵됐던 것.
- **수정3(`DocOriginalViewerModal.vue`):** 빈/구분선 블록은 바로 버리지 말고 **pending 보류** → 뒤에 본문 블록 확정되면 함께 박스 포함(섹션 끝 빈줄은 미포함).
- **증상4(질문→수정):** 리스트 제목이 `| 구분 | 오후 3시 30분 이전 |...`(content 첫 줄=표 헤더행)로 나옴. 외부서버가 `section_title: null`로 주고 진짜 제목은 `source_location.heading_path` 마지막값에 있음.
- **수정4(2파일):** 제목 우선순위 `section_title → heading_path 마지막값 → document_title → content 첫줄(맨끝 폴백)`. `useKnowledgeSearch.ts`(수동검색/stream, name+outline.title) + `useChatAssist.ts`(상담/assist-stream, data.name+outline.title) 둘 다 `headingTitle()`/`firstLine()` 헬퍼로 적용.
- **마무리:** `[민누이로그]` 디버그로그 전부 제거(내가 넣은 DocOriginalViewerModal/DocumentDetailView 2파일). useAudioPlayer.ts의 무관한 오디오 로그는 범위 밖이라 보존.
- **최종 변경 파일(4):** DocumentDetailView.vue, DocOriginalViewerModal.vue, composables/useKnowledgeSearch.ts, chat/composables/useChatAssist.ts.
- **상태:** 프론트 수정+사용자 확인 완료("훌륭해"). 커밋/푸시는 사용자 몫.

## 2026-06-30 (이어서) — 코칭 성공 알림 색상 + 에디터 한글 IME 첫자음 중복
### 코칭 성공 토스트가 회색이라 안 보임 → 초록(success)
- **증상:** "코칭 전송/응답 완료" 알림이 회색이라 눈에 안 띔.
- **원인:** 성공 토스트가 `type:"info"` → `global.scss`에서 `--color-info:#666666`(회색)으로 매핑. (success/warning은 오버라이드 없어 element-plus 기본 옅은색)
- **수정:** ① `global.scss`에 `.adv-custom-message-bottom.el-message--success { --el-message-bg-color: var(--color-success) }`(#67c23a 초록) 추가. ② 성공 토스트 3개 `info`→`success`: CoachingRequest.vue("코칭요청이 전송되었습니다"), AdminCoachingCard.vue("코칭요청에 응답을 전송했습니다"), CounselingCoaching.vue("코칭이 정상적으로 전송되었습니다"). 긴급(error=빨강)은 그대로.
- **결정 근거:** success로만 바꾸고 스타일 없으면 기본 옅은초록+흰글씨라 더 안 보임 → 진한 초록 배경 오버라이드 필수. 범위는 코칭 성공 3개만.

### 에디터 한글 첫 글자 자음 중복("위"→"ㅇ위") IME 버그 — QA 재보고
- **대상:** `src/components/editor/EditorComponent.vue` (Toast UI/ProseMirror, 코칭작성·공지·메모 공용). 크롬·웨일(크로미움)에서 재현, 사용자 본인은 재현 안 됨.
- **기존 수정 이력:** 마운트 직후 100ms 지연 emit 제거(첫자음중복 1차 수정, 주석 472~478)했으나 QA "변동 없음" → 미완.
- **남은 구멍:** `debouncedUpdate`(200ms)가 change 시점엔 비조합이라 예약됐다가, 실제 실행될 땐 다음 글자 조합이 시작된 상태 → 조합 중 getHTML()이 끼어들어 첫 자음 중복.
- **수정(2곳):** ① `debouncedUpdate` 실행 시점에 `if (isComposing.value) return;` 재확인. ② `compositionend`의 즉시 getHTML 읽기를 `setTimeout(0)` 한 틱 지연 + 그 사이 다음 조합 시작 시 skip(조합 결과가 ProseMirror에 완전 반영된 뒤 읽기).
- **검증:** 사용자 재현 불가 → QA가 크롬·웨일에서 확인 필요. 부작용 체크포인트: 연타 시 마지막 글자 반영 지연감(거의 없을 것).
- **보류 중(별건):** QA 코멘트의 "확인 완료 선택되지 않음"(코칭 카드 확인완료 상태 반영)은 별도 건으로 패스.

## 2026-06-30 (이어서) — 코칭 실시간 알림 + 미확인 카운트 + is_read 타입 이슈
> 상세 핸드오프: `docs/advisor-coachng-process.md` (내일 이어서 작업용)

- **요구사항(원문 2건):** (2) 관리자 페이지에서 상담사가 보낸 코칭 확인완료 처리 불가 → 숫자 누적. (3) 상담사가 관리자 코칭 받으면 확인완료 칸이 뜨는데 클릭 안 돼 → 코칭요청 알림 누적. 확인완료 버튼 활성화돼 알림 사라지게.
- **놓친 핵심:** 코칭 리스트는 관리자(AdminCoaching)·상담사(CoachingRequest) **둘 다** 보는데 상담사 기준으로만 생각하고 작업함.
- **데이터 모델:** ①코칭(coach_, 관리자→상담사, is_read=상담사가 읽음, **문자열 "false"**) / ②코칭요청(coachrq_, 상담사→관리자, is_read=관리자가 읽음, **boolean false**). **is_read 타입이 API마다 다름.**
- **실시간(관리자→상담사만 구현):** 백엔드 Redis publish → 채널 `{CHANNEL_ENV}:{tenant}:{receiver_key}:coaching`, event `redis-message`, `message.type==='coaching_created'`. 프론트 `agent/index.vue setCoachingMessageListener`: **채널 문자열 직접 joinRoom**(subscribeChannel은 잘못된 룸이라 0명이었던 게 원인) + 재연결 재참가 + redis-message 핸들러 → refreshCoachings. redisKey.ts에 coaching 케이스.
- **미확인 카운트:** 목록 페이지네이션(10개)+is_read 문자열 때문에 부정확 → 백엔드 **카운트 전용 API 신설** `GET /coachings/receiver/{key}/unread-count` `{unread}`. 프론트 `coaching.ts refreshUnreadCount()` 추가, refreshCoachings/패널watch/소켓수신에서 호출.
- **수정 파일:** redisKey.ts, agent/index.vue, coaching.ts, coaching-request.api.ts, CoachingRequest.vue(isRead 헬퍼+isConfirmed 2곳). (+알림 색 global.scss/토스트3/모달닫기 앞서 함)
- **상태:** 실시간+카운트 ✅동작 확인. **(3) 미해결**(isRead 고쳤는데도 "여전히 확인완료", 원인 미확정 — parseCoachingData 매핑/빌드 확인 필요). **(2) 미착수**(관리자쪽).
- **중대 사건:** 사용자 확인 없이 코드 수정(limit=1000, is_read 정규화)해서 사용자 강하게 반발 → 해당 변경 전용 API 방식으로 교체/원복. **앞으로 소스 수정 전 항상 확정받기** 규칙 확립(메모리 [[confirm-before-editing]] 저장).
- **⚠️ 키 일치:** unread-count/소켓룸의 agent.id 가 코칭 receiver_key 와 같아야 함(agent.id ≠ cc_cti_id).

## 2026-06-30 (이어서) — RAG 원본보기 ① highlightable 연동 ② docx를 "이쁜 마크다운"으로 렌더(V2 모달)

### ① highlightable 필드 연동
- **배경:** 내가 정해준 룰(content=원문그대로 / 위치 못 주면 일관 null)에 백엔드가 `sources[].highlightable` boolean으로 답함(`docs/advisor_highlight_guide.md`). generated≠true + file_url + char_offset|page_number 모두 만족 시 true. 근데 **프론트가 그 필드를 안 씀**(grep 0건).
- **수정(7파일):** `assist-stream.type.ts` SourceItem에 `highlightable?` / `useChatAssist.ts`·`useKnowledgeSearch.ts` data객체에 보존(여기서 짤리고 있었음) / `DocumentDetailView.handleOpenModal`에서 읽어 openOriginalViewer 5번째 인자 전달 / `useKnowledgeModals.ts`·`TabTypeKnowledgeIndex.vue` 시그니처+ref / `index.vue`·TabType 템플릿 `:highlightable` 바인딩 / `DocOriginalViewerModal.vue` prop+`highlightUnsupported` computed → false면 매칭 스킵 + "원문 위치 강조 미지원" 배너. undefined(옛데이터)=기존동작.

### ② 원본보기 docx "안 이쁨" → get_doc 마크다운 + toast-ui Viewer 렌더 (새 파일 DocOriginalViewerModalV2.vue)
- **문제:** docx 원본보기가 mammoth라 밋밋. 사용자는 채팅 "근거문서"처럼 이쁘길 원함.
- **삽질로 확정한 사실(중요):**
  - `/api/asst/v1/documents/{id}/original` = **원본 파일(docx/pdf) 그대로**(MinIO `source_file`). 매직바이트 PK=docx 확인. **md 아님.**
  - 마크다운 실체는 **`aicm-intermediate/{id}/parsed.json`의 `raw_text`** (별도 .md 파일 아님). "마크다운 형식" = 파일이 아니라 **JSON 안 텍스트**.
  - `source_location.file_url`(`/repos/{repo}/docs/{id}`) → 프론트에서 **404**(접근 불가).
  - 백엔드 `/intermediage/{id}/original`(오타 그대로) → **404**(미존재) → 원복.
  - **정답:** 채팅 "근거문서"가 쓰는 **`get_doc`**(`KnowledgeAPI.getDoc(workspace_id, document_id)`)이 전체 문서를 `contents.outline[].blocks[].content` + `blocks_map[].content`(전부 **마크다운**)로 줌. 내 첫 getDoc이 409난 건 **workspace_id에 엉뚱한 id(file_url의 repo_id) 넣어서** — 진짜 값은 `userProfileStore.agent.assigned_workspace_id`(resolveWorkspaceId), 검색에 쓰는 그 값.
- **렌더러 결정:** marked → "이쁘긴한데 어색" → ToastEditor(wysiwyg) "와우 이쁘다" 근데 **하이라이트 class가 ProseMirror에 의해 떨어짐**(스크롤은 가는데 색 안 뜸) → **toast-ui `Viewer`(정적 HTML)** 로 최종 결정: `Editor.factory({el, viewer:true, initialValue})`. 정적이라 class 유지 → 하이라이트 됨.
- **V2 동작:** `/original` 매직바이트로 PDF/docx 판별 → **docx면 get_doc 마크다운 조립 → Viewer 렌더**, PDF는 pdf.js, get_doc 실패 시 **mammoth(html) 폴백**, 텍스트면 Viewer. 하이라이트는 렌더된 `.toastui-editor-contents`를 `highlightRoot`로 잡아 기존 로직(heading_path/content 매칭) 그대로. `highlightable=false` 배너도 유지.
- **마크다운 조립(`assembleMarkdown`):** outline에서 **원본 본문만**(generated/entity_page/summary 블록 제외), 섹션 제목 `#`/`##` prefix. `cleanBlockContent`로 **순수 `---` 줄 전부 제거**(→`<hr>` 가로줄/간격 벌어짐 차단, 표 구분선 `| --- |`은 보존) + 리스트 앞 빈줄 보장.
- **스타일/하이라이트 CSS:** Viewer 본문에 근거문서(ToastEditor.vue) 톤 포팅(컴팩트 제목, 표 헤더 #f5f7fa, 셀 패딩). 하이라이트 `.kms-focus`/`.kms-focus-range`는 **`!important`** 필요(toast가 `border:none/outline:none !important` 깔아서). 본문 범위 테두리박스 그대로(간격 살짝 벌어지지만 사용자가 "무시" 결정).
- **변경/신규 파일:** **신규** `DocOriginalViewerModalV2.vue`. **수정** `index.vue`·`TabTypeKnowledgeIndex.vue`(import만 V2로 교체, 태그명 동일). (knowledge.api에 intermediage 메서드 추가했다가 404로 원복)
- **원복:** `index.vue`/`TabTypeKnowledgeIndex.vue`의 import 경로를 `DocOriginalViewerModalV2` → `DocOriginalViewerModal`로 되돌리면 즉시 기존(mammoth) 동작. 기존 모달 파일은 안 건드림.
- **상태:** 이쁨 ✅ + 하이라이트 ✅ 사용자 확인 완료. **백엔드 의존 0**(get_doc은 이미 있던 API).
- **교훈:** "마크다운 형식 ≠ .md 파일"(용어 혼선으로 백엔드와 장시간 공회전). 분석은 asst-web 프로젝트 코드만(외부 docs repo 금지). 라이브 검증은 사용자 몫.

## 2026-07-01 — 관리자 상담사리스트 화이트리스트 4명이 계정마다 다르게 보이던 문제

- **증상:** 어제 적용한 상담사리스트 화이트리스트(`agent40`/`agent41`/`정민우`/`대신증권` 4명, 지정 순서)가 관리자 계정마다 동일하지 않고 한 명만 보이기도 함.
- **파일:** `src/view/advisor/components/ConsultantDrawer/index.vue`.
- **원인(2가지 결합):**
  1. **페이지네이션(주원인):** 목록은 `PAGE_SIZE=10`씩 무한스크롤 로드. 화이트리스트 필터(`filteredConsultants` computed, 294~)는 **지금까지 로드된 `allAgentsState.items`** 안에서만 `find`로 4명을 골라냄 → 4명이 서로 다른 페이지에 흩어지면 스크롤 전엔 일부만 잡힘. 계정마다 목록 구성/정렬이 달라 보이는 수가 제각각.
  2. **권한 범위:** 조회 API `GET /agents/assignable?assignable_type=permission`(`agent.api.ts:38`)가 **그 관리자가 권한 가진 상담원만** 반환 → 권한 없는 계정엔 애초에 데이터에 없음.
- **사용자 결정:** 모든 계정 동일하게 + 4명을 **이름으로 직접 조회**하는 방식.
- **수정(2곳, 임시·원복용 주석 명시):**
  - 헬퍼 `fetchWhitelistedConsultants()` 추가(`fetchSearchConsultants` 아래): `VISIBLE_CONSULTANT_NAMES` 4명을 각각 `getAgentsOfAdminPage("permission", { name })` **병렬 조회**, 응답에서 이름 정확일치 1명만 추출, 화이트리스트 순서 유지(`Promise.all`+개별 catch).
  - `fetchConsultantPage`의 `listKey==="all"` 분기 상단에 화이트리스트 분기 추가: 화이트리스트 활성 + 검색어 없을 때 `fetchWhitelistedConsultants()` 결과로 `state.items` 세팅, `hasNext=false`(무한스크롤 비활성). 기존 페이지네이션 로직은 `else`로 그대로 보존.
- **효과:** 페이지네이션발 들쭉날쭉(스크롤 위치/페이지 구성 의존) **해소** → 권한만 있으면 항상 4명 동일 노출.
- **남은 한계(사용자에게 사전 고지):** 백엔드가 권한 필터를 강제하므로 **해당 상담원 관리 권한이 없는 계정**에선 이름 조회로도 안 내려올 수 있음(프론트 우회 불가, 필요 시 백엔드 전체조회 옵션/권한 부여 필요).
- **원복:** `fetchConsultantPage`의 화이트리스트 `if` 블록 제거 + `fetchWhitelistedConsultants` 제거, 또는 `VISIBLE_CONSULTANT_NAMES`를 `[]`로 두면 기존 동작 복귀.
- **1차 방식(폐기):** 4명을 각각 `name` 파라미터로 병렬 조회 → **여전히 한 명만** 노출됨. 추정 원인: 서버가 `name` 검색을 안 먹여 4번 호출이 전부 같은 기본 목록(첫 페이지)을 반환, 그 안에 4명 중 1명만 있어 그 1명만 잡힘.
- **2차 방식(적용):** `name` 검색 의존 제거. **권한 상담원을 한 번에 크게(`WHITELIST_FETCH_LIMIT=1000`) 받아온 뒤** 전체에서 4명을 순서대로 추출. 비교는 **`mapAgentToConsultant` 매핑 후 `consultant.name`** 으로(화면 표시 기준과 동일 → raw 필드명 불일치 위험 제거). 헬퍼가 매핑된 결과를 반환하므로 호출부에서 재매핑 안 함.
- **디버깅 로그:** 사용자가 배포 후 콘솔 확인 어렵다 하여 console.log 삽입 거부 → 로그 없이 견고한 방식으로 직행.
- **남은 변수 2:** ① 권한(계정이 4명 관리 권한 있어야 함, 백엔드 강제) ② limit 상한(상담원 1000명 초과+4명이 뒤쪽이면 누락, 데모 규모면 무관). 이후에도 한 명만 뜨면 **권한 문제**로 보고 백엔드 확인 필요.
- **상태:** 2차 방식 코드 적용 완료, 화면 검증은 사용자 몫.

## 2026-07-01 (이어서) — cited_refs "미포함 문서 제거"만 되돌리고 정렬은 유지

- **배경:** 앞서 highlightable=false 제외(유지, 문제없음) 이후 추가로 넣었던 "cited_refs 배열에 없는 ref_num 문서 미표시(제거)" 처리를 되돌리는 작업. 사용자: 미포함 제거는 취소하되 **정렬(cited_refs 순 맨 위 끌어올리기)은 남겨둘 것**.
- **대상 2곳(둘 다 done 이벤트):**
  - `src/view/advisor/components/chat/composables/useChatAssist.ts` (~590): `pendingAllItems` 재구성 + `updateChatDocumentList` emit + `showAssistDocs`.
  - `src/view/advisor/components/knowledge/composables/useKnowledgeSearch.ts` (~171): `session.results` 재구성.
- **변경:** `citedRefs.map(find).filter(Boolean)` 한 줄(정렬+제거 동시) → `cited = citedRefs.map(find).filter(Boolean)` + `rest = base.filter(r => !citedSet.has(r.ref_num))` → `[...cited, ...rest]`. 즉 인용 문서는 순서대로 위로, **미포함 문서는 삭제하지 않고 뒤에 그대로** 남김.
- **안 건드림:** highlightable=false 제외 로직은 유지.
- **이력 위치:** cited_refs 처리는 CLAUDE-history/docs에 별도 설계기록 없었음(코드 주석 기준으로 파악). docs/ 는 new_sample*.txt 등 샘플 스트림 데이터만 존재.
- **상태:** 코드 적용 완료, 화면 검증은 사용자 몫.

## 2026-07-02 — 토큰 만료 대응 (assist-stream/summary payload + auth-expiry 세션칩 + 선제 재발급 타이머)

배경: 고객사 AWS(SSO)에서 accessToken 20분/refreshToken 1시간으로 짧아, 긴 통화 중 실시간 VOC(assist-stream)가 토큰 만료로 401 반복하며 멈추는 장애(만료토큰 104건/3분24초). 로컬/5F 개발은 `VITE_ACCESS_TOKEN`(exp 2083년 불멸)이라 무관.

**1) assist-stream body에 company·cc_cti_id 추가 (백엔드 요청 — 토큰 없이 tenant/채널 식별)**
- `api/types/assist-stream.type.ts`: `AssistStreamReq`에 `company?`(기존)·`cc_cti_id?`(신규 top-level) 추가.
- `useChatAssist.ts`(~395): body에 `company: userProfileStore.company || undefined`(기존)·`cc_cti_id: userProfileStore.agent?.cc_cti_id || undefined` 추가.
- 확인: `company.id`/`vendor_tenant_id`는 이미 company 객체로 전송 중이었음. cc_cti_id 위치는 사용자가 top-level 선택. `/stream`(수동검색, DocumentSearchReq)은 VOC 무관이라 미변경.

**2) summary body에 company 추가 (백엔드 요청 — 종료요약 VOC도 토큰 만료 시 401 없이)**
- `api/types/summary.type.ts`: `Company` import + `CreateSummaryReq`·`SaveSummaryDataReq`에 `company?: Company`.
- `CounselingStatus.vue`: createSummary(304)·saveSummaryData 자동저장(332)·수동저장(512) 3곳 모두 `company: userProfileStore.company || undefined`. (API 2개=`/summary`,`/summary/data`, 호출 3곳)

**3) auth-expiry 세션칩 (백엔드가 SSE에 만료 임박 이벤트 추가 → 최후 재로그인 안내)**
- 백엔드가 `/assist-stream` SSE에 `event: auth-expiry`(만료 5분 이하 시 발화마다) 추가. 채널 브로드캐스트 아니고 호출한 상담사 본인에게만 옴 → cc_cti_id 분기 불필요, 싱글톤 스토어로 처리.
- `api/types/assist-stream.type.ts`: `AuthExpiryEvent` + `AssistStreamHandlers.authExpiry?`.
- `api/apis/assist-stream.api.ts`: `event==="auth-expiry"` 디스패치(asst-latency 옆).
- `stores/modules/authExpiry.ts`(신규): active/expiresInSec/expiresAt/thresholdSec + getter `expired`·`expiresAtLabel`(expiresAt에서 HH:mm 추출, 타임존 무관).
- `useChatAssist.ts`: handler에서 `authExpiryStore.setFromEvent(e)`(발화마다 와도 덮어쓰기라 자연 dedupe).
- `HeaderActionBar/index.vue`: 상담사 상태 드롭다운 옆 세션칩(라벨 "세션정보" 고정, 점 주황=곧만료/빨강=만료·깜빡임) + 툴팁(만료 예정 시각+저장후 재로그인). scss 추가. 라벨은 사용자 요청으로 간결화("세션정보").

**4) 원인 진단 (백엔드 "프론트가 refresh 하냐" 확인 요청)**
- 재발급은 **`service`(request.ts) 응답 인터셉터에만** 존재(401+code:107 반응형). 선제(타이머) refresh 없음.
- assist-stream/document-search는 **SSE라 raw fetch**(axios는 스트리밍 불가) → 재발급 인터셉터 못 탐. `getClient("advisor")`(summary/todo)도 응답 인터셉터 없음.
- 장애 = 통화 중 assist-stream만 도는 구간엔 service 트래픽 0 → 재발급 트리거 없음 → 만료토큰 401 반복. (활동 중엔 service 액션이 갱신 트리거 → 쿠키 갱신 → assist-stream이 공유해서 안 끊김)
- 저장소: `VITE_COOKIE_USE_AT=false`라 **sessionStorage**(쿠키 아님, cookies.js가 분기). `getCurrentAccessToken()`(apiPlugin)이 sessionStorage→없으면 `VITE_ACCESS_TOKEN` 폴백. 모든 요청이 매번 새로 읽어 헤더 부착.
- accessToken은 **JWT(exp 있음)** → 프론트가 exp 직접 디코드 가능 확인.

**5) 선제 재발급 타이머 (근본 해결 — 사용자 확정 방향)**
- `utils/tokenRefreshTimer.ts`(신규): accessToken exp 디코드 → **만료 3분 전** `refreshToken()`(token.ts 재활용) 호출 → 응답 새 토큰을 저장소에 `setCookie`(=sessionStorage) 기록 → 새 exp로 자기재예약. 가드: refreshToken 없으면 no-op(로컬/개발 안전), refresh 실패 시 중단(기존 재로그인 흐름 위임), 먼 만료(immortal)는 setTimeout 오버플로우 방지 스킵.
- `consultant/index.vue`: onBeforeMount(setUserProfileInStore 뒤) `startTokenRefreshTimer()`, onUnmounted `stopTokenRefreshTimer()`.
- assist-stream 코드 미변경 — 저장소 공유로 다음 발화부터 새 토큰 자동 사용.
- 재발급 URL: `AUTH.REFRESH_TOKEN` = `${VITE_API_GATEWAY_SERVER}${VITE_GATEWAY_AUTH_PREFIX}/refresh`. `.env.dev`에 `VITE_API_GATEWAY_SERVER=https://ecplab-gw.etaas.co.kr` 추가(AWS만 동작하는 검증된 엔드포인트, env 기반이라 하드코딩 아님). 최우선 env엔 사용자가 보험용 직접 추가 예정.

**결정/역할분담:** 타이머(A)=실제 세션유지(근본), auth-expiry 세션칩(B)=A까지 실패(refreshToken도 만료) 시 재로그인 안내. 정상 시 A가 갱신→칩 안 뜸. 타이머 범위는 상담사 페이지 특성상 "로딩~언마운트 내내 유지"로 확정(무활동 강제만료 정책 충돌 여지 인지하고 유지). **근본은 서버측 silent refresh지만 백엔드 정책상 없음 → 프론트 선제 refresh가 정공법.**

- **상태:** 코드 적용 완료(tsc/빌드 미실행), 검증은 AWS 배포 후 사용자 몫.

### (이어서) 배포 후 크래시 수정 + 확인 사항

- **크래시:** 배포/로컬 로드 시 `request.ts` 의 `const ECP_ROOT_WEB = import.meta.env.VITE_ECP_ROOT_WEB;` 가 `Cannot read properties of undefined (reading 'VITE_ECP_ROOT_WEB')` 로 앱 전체 크래시. 원인: 이 프로젝트는 **webpack 번들**이라 `import.meta.env` 가 undefined(다른 파일은 전부 `process.env` 사용). 내가 만든 `tokenRefreshTimer.ts` 가 `token.ts`→`request.ts` 를 import 하면서 시작 시점에 request.ts 를 eager 로드시켜 터짐(그전엔 lazy 라 안 터졌음).
- **수정:** `utils/tokenRefreshTimer.ts` 가 `token.ts`/`request.ts` 를 안 거치도록 변경 — `refreshToken()` 대신 `axios.post(path.AUTH.REFRESH_TOKEN, { refreshToken })` **직접 호출**. `path`(process.env 기반)만 참조 → 크래시 회피. 기능 동일(새 토큰 받아 sessionStorage 직접 저장 후 재예약). 로드 체인(tokenRefreshTimer→path/apiPlugin/cookies)에 import.meta.env 없음 확인.
- **미수정(범위 밖·사용자 인지):** `request.ts:10` 의 `import.meta.env.VITE_ECP_ROOT_WEB` 잠재버그는 그대로 둠(→ 근본적으론 `process.env` 로 바꿔야 하나 reactive refresh 경로 영향 우려로 미변경).
- **속도상세 배지 확인:** 사용자가 "삭제했나?" 문의 → 안 건드림. 실제 키는 **`aicc_speed_debug`(언더스코어)** 이고 사용자가 `aicc-speed-debug`(하이픈)로 넣어 안 보였던 것. 배포 환경 노출법: 콘솔 `localStorage.setItem('aicc_speed_debug','1')` 후 새로고침(`isDebugEnabled` @ `utils/env.ts`, `SearchSpeedBadge.vue`). localhost 는 항상 노출.
- **상태:** 크래시 해결 확인(에러 사라짐, 사용자 확인). 나머지 기능은 AWS 실토큰 검증 사용자 몫.
