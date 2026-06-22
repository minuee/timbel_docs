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
