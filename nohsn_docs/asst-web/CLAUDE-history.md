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

---

## 2026-07-06 상담 "이전대화 불러오기" 기능 (실시간 대화 유실 복원)

**배경:** 실시간 상담 중 뒤로가기/페이지이동 후 복귀하면 STT 대화(인메모리 `chatContent` ref)가 유실됨. 상담사가 이전 대화를 못 봄 → 저장된 과거 발화를 버튼으로 복원.

**설계 (사용자 2안 채택):** 화면 대화가 최초(turn_idx=0)부터가 아니면 "이전대화 불러오기" 버튼 노출 → 클릭 시 저장된 과거 turn 을 대화 앞에 prepend. (1안 "상담중 뒤로가기 차단"은 증상만 막고 부작용 커서 폐기)

**백엔드 API (신설, 사용자↔백엔드 협의):**
- `GET /aicc/asst-service/callstat/calls/realtime-by-callid/{callId}/turns`
- 응답: `{ call_id, turns: [{ callstats_id, turn_idx(0-based), role(customer/agent/system), utterance, masked_utterance, created_at }] }`, turn_idx ASC(오래된순).
- 소스 테이블 `raw_call.callstats_turn`(callstats_id=callstats_call.id FK). 기존 `/by-call-id/{callId}/stt`(getCallStt) 재활용 가능했으나 **전용 신설** — 실시간 격리/의도명확/백엔드 에러핸들링 이유.

**구현 (파일 3):**
- `api/types/callstat.type.ts`: `RealtimeCallTurn`(turn_idx 외 전부 optional — 필드 변형 대비).
- `api/apis/callstat.api.ts`: `getRealtimeTurnsByCallId()`.
- `chat/index.vue`:
  - `minVisibleTurnIdx`(computed, O(1) — 앞에서 첫 유효 turnIdx만. chatContent 오름차순 전제), `hasPreviousTurns`(`>0`, 0-based).
  - `loadPreviousTurns`: callId(`callSummaryInfoStore.callId||props.callId`) → API → `turn_idx<beforeIdx` 필터 + 재정렬 → role→sender·utterance→content·created_at→time 매핑 → prepend + **스크롤 앵커 유지**(expandChatWindow 패턴 재활용). 전 과정 try/catch 격리(실패시 console.warn만).
  - 버튼: `v-if="hasPreviousTurns && !isAdmin && !isViewer"` (상담사 실시간 화면에서만).

**핵심 함정/해결:**
- ⭐ **0-based**: 초기 `>1`(사용자가 "1부터"라 해서 1-based 가정) → 실제 API turn_idx 0부터 → `>0`으로 수정. 안 그러면 "0번만 사라진 경우" 버튼 안 떠서 영구 유실. 실시간 소켓도 0-based 확정 — `useChatMessageParser.ts` 가공없이 그대로 매핑 + 119행 주석 "통화 바뀌면 turn_idx 0부터 재사용"이 증거(실통화 없이 코드로 확정).
- **flex-center 없음**: common.scss엔 `flx-center`만 → `flex justify-center`로 교체(CLAUDE.md 기존 함정과 동일계열).
- **응답 래핑**: `{turns:[]}` 형태 → `Array.isArray(raw)?raw:raw.turns` 방어 파싱.

**실시간 무영향 4중 점검(통과):** ①렌더안전(SpeechBubble `content||""` 방어+기존 props.callId watch 동일 최소필드 패턴) ②prepend중 새발화(최신배열 spread/turnIdx 겹침없음) ③노출범위(관리자·뷰어 차단) ④격리(try/catch).

**상태:** 코드 완료. lint 내 추가분 에러0(파일 전체 기존 prettier 이슈만 잔존). 실통화 화면검증은 사용자 몫(선택, 백엔드 이미 배포).

## 2026-07-06 (이어서) — 어드바이저 리뉴얼: 모달→페이지화 스캐폴드 착수 (advisor-renual)

**배경/방식 확정:** CLAUDE-renual-todo.md 브레인스토밍 기반. 모달/팝레이어 기능을 독립 페이지로. 이번 단계는 **껍데기(뷰)+주석만**, 로직은 확정 후 기존 코어(store/api) 재사용(복제금지). 뷰만 `src/view/advisor-renual/`로 분리(안전), 코어는 기존 것 import 방침.

**주석 3블록 형식(공지사항 샘플로 확정):** ①참고소스(모달 경로+코어 store/api/types 위치) ②리뉴얼 타겟 UI(배포 목업 URL+구성) ③구성가능성 %분석(갭 지점 ★표시). 배포 UI는 MCP(Playwright)로 분석해 주석에 기록.

**공지사항 샘플 완료:** `src/view/advisor-renual/notice/index.vue`. 분석결과=코어가 useNoticeStore/NoticeAPI에 잘 분리→**약 85% 재사용가능**, 유일 갭=배포UI 유형4종(긴급/일반/정책/점검) vs 기존모델 2종(urgent/general) → API확장 or 프론트매핑 확정필요.

**허브 방식(A) 확정 — GNB 4뎁스 제약 회피:** `makeMenuOfTree`가 3뎁스까지만 지원 → gnb_menu.png "94리뉴얼>3그룹>항목"(4뎁스) 불가. 대신 **허브 페이지가 3그룹 nav를 콘텐츠로 렌더**(`advisor-renual/index.vue`), 리프는 클릭 이동.

**배선(상담사/관리자 무영향 확인 후 진행):**
- `mockupMenuList.ts`: 94 routePath `example/agentRenewal`→`advisor-renual`(허브). 리프10개 추가(parentId:0, **isHide:true**, routePath `advisor-renual/<기능>`, id 941~950).
- `auth.ts` buildMenuItem: `isHide: rawItem.isHide ?? false`(하드코딩 false→목업플래그 존중, 기본 false라 하위호환).
- 라우팅 근거: 가드(routers/index.ts:68)가 메뉴에 있는 path만 통과 → 리프도 메뉴등록 필요. isHide는 사이드바만 제외(getShowMenuList), flat(getFlatMenuList)엔 포함→라우트/딥링크 OK.

**생성 파일(11개):** 허브 `advisor-renual/index.vue` + 리프10 `dashboard/chat/call-history/bookmark/memo/todo/notice/coaching/detect-word/settings`. 공지사항만 풀 분석주석, 나머지9는 최소껍데기(분석주석 순서대로 채울 예정).

**다음:** 배포 URL 목록 받아 순서대로(북마크→메모→할일→감지어→코칭→설정→통화이력, 워크스페이스3개 포함) 분석주석 채우기.

## 2026-07-06 (이어서) — 리뉴얼 방식 전환: 콘텐츠 허브(A) → 플라이아웃 그룹메뉴(B2)

**재파악:** 사용자가 가리킨 "우측"은 페이지 콘텐츠가 아니라 **메뉴 플라이아웃(NewSubMenu.vue)의 three-depth 컬럼**. 흐름=상담어드바이저(0)→[hover]91~94→[94 hover]94의 자식(그룹렌더). NewSubMenu는 이미 `three-depth-menu-parent`로 **그룹헤더+항목(제목·설명·카운트)** 렌더 가능 = gnb_menu.png 모양 코드추가 없이 지원. 유일 블로커=makeMenuOfTree 3뎁스 한계.

**B2 확정·구현:**
- `mockupMenu.ts` makeMenuOfTree에 **4뎁스 루프 1개 추가**(기존 3뎁스 그대로, 순수 추가). node 시뮬로 검증: 94→3그룹→10항목 정상, 91/92/93 자식0(무영향).
- `mockupMenuList.ts` 재구성: 이전 parentId:0 isHide 리프10 제거 → **94 → 그룹3(951 워크스페이스/952 내도구/953 코칭·설정) → 항목10**. 그룹은 children 보유→페이지없음(플라이아웃 헤더역할), 항목은 routePath advisor-renual/<기능>→기존 껍데기.
- 콘텐츠 허브 `advisor-renual/index.vue`는 **남겨둠**(94가 자식생겨 라우트 연결은 끊김, 참고용).
- 진단(getDiagnostics) 3파일 클린. require.context는 빌드타임이라 새 .vue 인식엔 dev 재시작/HMR 필요(사용자).

**무영향 재확인:** auth.ts isHide 1줄(기본 false), 4뎁스 루프 additive, 메뉴변경 리뉴얼(94) 서브트리 한정 → 상담사(91)/관리자(92) 그대로.

**다음:** 배포 URL 목록 받아 리프 껍데기에 분석주석 순서대로.

## 2026-07-07 — 리뉴얼 상담화면(chat) 리프 구현 (하이브리드: 복사 후 UI 리뉴얼)

**방식 확정:** 기존 상담화면 프로세스 재사용 + 실시간 살림. **원본 무수정** 대전제.
- 로직·데이터(store/api/service/composable)는 기존 것 **import만**, **화면 UI(component)는 복사 후 리뉴얼**.
- 하위 컴포넌트 import가 `@/` 절대경로면 복사본을 딴 위치에 둬도 원본 재사용(복제 아님). 상대경로(`./`)면 복사 후 sed로 절대화.

**신규 파일 (전부 `src/view/advisor-renual/chat/`):**
- `index.vue` — 부모 오케스트레이터(`advisor/agent/index.vue`의 상담뷰 배선 발췌 재현) + 리뉴얼 프레임. RenualPageHeader + 좌1:우2 grid + 우측레일.
- `components/ChatRightRail.vue` — 우측 아이콘 레일 6개(코칭요청/콜이력/메모/북마크/할일/설정). 아이콘만, 모달연동 나중. hover=테마색.
- `components/RenualChatPanel.vue` — 상담내용(원본 `chat/index.vue` 복사, 2340줄). @/ 절대경로라 composable/SpeechBubble/store 원본 재사용.
- `components/RenualKnowledgePanel.vue` — 지식저장소(원본 `knowledge/TabTypeKnowledgeIndex.vue` 복사, 상대경로 8개 절대화).
- `components/RenualDocumentCard/ContentPanel/DetailView.vue` + `RenualContentCollapse.vue`(재귀) — 지식저장소 하위 4개 복사, 상호참조 복사본끼리 연결. SearchSpeedBadge 등 리뉴얼 대상 아닌 건 원본 재사용.

**실시간 재현:** 리뉴얼 index.vue 가 Chat emit 4종(updateChatDocumentList/Summary/Timing/SelectedRefs) + detailItemClick/clearChatSelection 를 받아 로컬 ref→Knowledge props 로 배선(agent/index.vue 발췌). 식별자(cc_cti_id/assigned_workspace_id/botId)는 userProfileStore. onMounted 에 ensureBootstrapped()+refreshKeywordDetect(), onUnmounted vocStore.clear().

**UI 리뉴얼 완료분:**
- 4등분 레이아웃: 좌(상담내용)/우(지식저장소) 하나의 카드처럼 — 공유 보더 + 바깥4모서리 radius + 가운데 세로선(`__know border-left`) + 제목 아래 가로선(전체폭, 음수마진 -20으로 카드끝~세로선 꽉참) + 좌우 제목영역 높이 44px 통일.
- 헤더 아이콘: 상담내용 `forum` / 지식저장소 `menu_book`, 색=텍스트와 동일(`info`).
- VOC 헤더 반응형: 좁아지면 wrap→nowrap(높이 44 고정), 스파크라인만 flex-shrink 축소(등급·score 보존).
- 상담원 말풍선 배경: `:deep(.bubble-consultant)` → `--color-primary-10`(테마색). 고객 말풍선은 인라인 로직이라 나중.
- 지식저장소: 검색input(radius 6px·placeholder·포커스 테마색), AI요약 박스 배경 `--color-primary-10`+"AI 요약" 라벨(search 탭·상세 둘 다), 탭(상단 card + 활성 하단 2px `--color-primary` 밑줄), 탭 영역 꽉참(음수마진 -20)+하단 분리선(탭 있을때만 렌더=빈상태 라인 제거)+탭위여백 3px+탭↔AI 20px, AI/문서 padding=탭의 2배.

**중요 원칙(메모리 저장):** 색은 하드코딩 말고 테마변수(`--color-primary` 계열, `--color-gNN`). 특히 hover. → `theme-color-over-hardcode` 메모.

**검증:** 로컬(localhost:8173) 검색 실제 동작 확인(useKnowledgeSearch API 정상). 좌표 측정으로 레이아웃 검증. 발화 말풍선은 통화 필요라 사용자 검증.

**남음:** 3번 상세 UI(문서카드 클릭→`[규정]/[FAQ]`배지+문서명+`☆북마크/⭐북마크됨` 상세헤더+뒤로가기+원본보기, new_knowledge_1/2.png 참고) / 우측레일 모달연동 / 고객 말풍선(SpeechBubble 복사) / 상담원 배경색 실측 조정.

## 2026-07-07 — 리뉴얼 대시보드(dashboard) 리프 구현 (UI + 실데이터 1차)

**흐름:** 배포 목업(`/agent/dashboard`)과 현 운영 대시보드(`/advisor/consultant`)를 MCP로 대조 → 껍데기였던 `advisor-renual/dashboard/index.vue`를 목업 UI로 채우고, 실데이터 4개를 기존 소스 재사용으로 연결. **원본 무수정.**

**확정 사항(대화):**
- 종합(집계) API 신설 안 함 → 기존 전용 스토어/API 그대로 재사용. 진입마다 4콜 병렬(현 운영 대시보드가 이미 하는 패턴, 훨씬 가벼움). 로그인 1회가 아니라 대시보드 진입마다 갱신이 맞음(숫자는 최신이어야 의미).
- 미구현 3개는 배지 말고 심플하게 제목 텍스트로만 표기.
- 데이터는 목업으로 두되 주석에 "실데이터 연동 시 목업 제거" 명시. 색은 테마변수. 카드 링크는 리뉴얼 라우트 연결.

**조사(Explore 에이전트 + 직접):** 현 대시보드 `Dashboard.vue`는 자식이고 부모 `agent/index.vue`가 데이터 로드. 소스 확정 — 공지=`noticeStore.dashboardNotices`, 코칭=`coachingStore.unReadCoachingCount`+`receiverCoachings[0].content`, 오늘통화=`CallStatAPI.getAgentSummaryStats.total_calls`+`callHistoryStore` 최근콜, 지식=`DashboardAPI.getPopularDocuments`.

**✅ 실연결 4개:** ①긴급공지(최신1건, 긴급/일반무관) ②코칭(미확인수+최근문구) ③오늘통화(건수+마지막callId) ⑥자주열람지식(문서명+저장소명, max5, 없을수있음). 각각 빈상태 처리 + 카드클릭→리뉴얼 라우트.
**⛔ 미구현 3개:** ④이슈어 ⑤자주하는질문 ⑦오늘KPI — 제목에 `· 미구현` 텍스트만, 내용은 `[MOCK]` 플레이스홀더.

**버그픽스:** 자주열람지식 0건 → 원인=`assigned_workspace_id`만 봐서 목업/mock 계정(workspace 미할당)에서 빈값. `resolveWorkspaceId()`(설정/env override 우선) 로 교체해 해결. chat 리뉴얼·운영 대시보드와 동일 우선순위.

**상태:** IDE 진단 0. UI+실연결 1차 완료. 대시보드 세부 보완은 **나중에** 하기로(사용자: "일단 정리, 나중에 보완마무리"). 상세는 renual-todo 7-7 대시보드 항목 참고.

## 2026-07-08 — AICM 검색 카테고리(category_ids) 기능 + highlightable boolean/string 정규화

> 리뉴얼(renual)은 홀드하고 **기존 소스 수정**. 백엔드가 workspace별 카테고리 트리를 제공 → 상담사가 선택하면 RAG 검색범위를 그 카테고리로 제한.

**흐름:** ① 카테고리 조회(`GET /aicc/asst-service/categories?workspace_id=`) → ② 설정 모달에서 선택 → ③ assist-stream/문서검색 호출 시 `category_ids` 전달. 선택 안 하면 빈 배열 `[]`(제한 없음, 하위호환).

**확정 사항(대화):**
- 선택 안 함 → `[]` 로 전송(undefined 아님).
- 선택은 **workspace별로** persist store 저장(workspace 바뀌면 API 재조회).
- 응답이 **트리 구조**(부모=봇그룹 한투_챗봇/한투_콜봇, children=실제 카테고리 FAQ/KMS/의도분류…). `category_ids` 로 보내는 값 = **리프(자식) UUID만**. **부모 선택 = 하위 자식 전체 펼침 토글**. UI = 트리(그룹헤더+자식 체크박스).
- 응답형식 미확정 기간엔 파싱을 `normalizeNode` 한 곳에 격리(방어적). 실제 형식 확정되어 트리 재귀 파싱으로 교체.

**신규 파일(3):**
- `src/api/types/category.type.ts` — `CategoryNode`(id/name/parent_id/path/children[] 트리).
- `src/api/apis/categories.api.ts` — `getCategories(workspaceId)` + 재귀 `normalizeNode`(id|category_id|uuid, name|label|title, {categories|data|items} 감쌈 방어) + `collectLeafIds` export.
- `src/stores/modules/category.ts` — persist store, `selectedByWorkspace: Record<wsId, string[]>`, getter `selectedIdsFor(wsId)`, action `setSelected`.

**수정 파일:**
- `src/api/config/path.ts` — `CATEGORIES: "/categories"` 추가.
- `src/api/types/assist-stream.type.ts` — `AssistStreamReq.category_ids?: string[]` 추가. (+ 뒤에서 `SourceItem.highlightable` widen)
- `src/api/types/ce.type.ts` — `DocumentSearchReq.category_ids?: string[]` 추가.
- `Setting.vue`(`components/layout/Drawer/components/Setting/`) — **카테고리설정 탭 신규**. 트리 UI(부모 그룹헤더=하위 전체토글+indeterminate, 자식 들여쓴 체크박스), 탭 진입 시 `effectiveWorkspaceId`로 조회, 저장은 리프 UUID만 store 반영. **저장 성공 시에만** 알럿 "AICM 검색 카테고리가 정상적으로 변경되었습니다" → `setTimeout 1000ms` 후 모달 닫힘.

**category_ids 전달 3곳(전부 workspace_id 1회 해석 후 `selectedIdsFor(wsId)`):**
- ① 실시간 발화: `useChatAssist.ts` (`/assist-stream`).
- ② 지식패널 수동검색: `useKnowledgeSearch.ts` (`/stream`).
- ③ 상담이력 모달 키워드→문서조회: `useKeywordDetail.ts` (`/stream`). ← 사용자가 처음 놓쳤다가 추가.
- store/전달값이 `string[]`이라 3곳 전달부는 값 그대로. 리뉴얼 chat/knowledge 는 ①②composable 재사용이라 **자동 반영**(리뉴얼 설정 리프는 미착수라 선택 UI는 나중).

**highlightable boolean/string 정규화(별건 요청):**
- 문제: 기존 `highlightable !== false` 는 엄격한 boolean `false`만 제외 → 백엔드가 문자열 `'false'`로 주면 못 걸러 노출되는 버그. (`true`/`'true'` 혼용도 들어옴)
- 신규 `src/utils/highlightable.ts`: `isHighlightableFalse(v)=v===false||v==='false'`, `isSourceVisible(v)=!isHighlightableFalse(v)`. `undefined`(옛데이터)는 노출 유지.
- 적용: `useChatAssist.ts`·`useKnowledgeSearch.ts` 문서필터 → `isSourceVisible`. `DocOriginalViewerModal.vue`(V1)·`DocOriginalViewerModalV2.vue`(실사용) 안내배너 `highlightUnsupported` → `isHighlightableFalse`. `SourceItem.highlightable` 타입 `boolean` → `boolean|string`. 리뉴얼도 공유 V2+composable이라 자동 커버.

**상태:** 사용자 라이브 검증 완료(카테고리 트리 정상, 저장 알럿·1초 닫힘, highlightable 필터 정상). IDE 진단 0. 응답형식 또 바뀌면 `normalizeNode` 한 곳만 수정.

---

## 2026-07-09 — 리뉴얼 설정(settings) 리프 구현 (데모 UI 재현 + 코어 재사용)

**요청:** 리뉴얼 리프 중 "설정" 착수. 목업 `/agent/settings` 기준, 일단 UI만. 단 **테마 섹션은 제외**(여기서 설정할 성격이 아님).

**⚠️ 내가 한 실수 (기록):** "일단 UI만"이라는 명확한 지시가 있었는데도, 내가 "실동작 되는 것만 노출할까요?"라는 선택지를 던져 사용자가 그걸 고름 → 결과물에 데모 기능이 하나도 안 남아 사용자가 당황("mcp로 본 기능들은 하나도 없네"). 즉시 되돌려 데모 항목 전부 재현. **교훈: 목업 재현 작업에서 "미구현 항목 뺄까요" 류 질문 금지.** (memory `demo-mockup-ui-fidelity` 저장함)

**파일:** `src/view/advisor-renual/settings/index.vue` (스캐폴드 → 실구현)

**참고 코어(복제 금지, 그대로 구독):** 기존 설정 모달 `components/layout/Drawer/components/Setting/Setting.vue` 의 탭 3개 로직.
- `settingsStore`(`stores/modules/settings.ts`) + `ConfigAPI.upsertConfig` — 서버 저장
- `workspaceStore`(persist/localStorage) + `WORKSPACE_PRESET_OPTIONS` / `WORKSPACE_CUSTOM_VALUE`
- `categoryStore`(persist/localStorage) + `CategoriesAPI.getCategories` / `collectLeafIds`

**섹션 6개 (데모 순서 + 뒤에 2개 추가):**
1. 알림 — 코칭 메시지 도착 알림 / 지식 자동 검색 / 공지 도착 알림 / 통화 종료(wrap-up) 알림 + 저장버튼
2. 소리 — 알림 사운드(전체) / 코칭 도착 시 소리 / SOS 응답 시 소리
3. 통화 중 화면 — 발화 자동 스크롤 / 코칭 위스퍼 음성 (+ 센터 설정 안내문)
4. 단축키 — Ctrl+M/I/K/F// 표(읽기전용, `<kbd>` 스타일)
5. **WorkSpace** (데모엔 없음) — 프리셋 셀렉트 + 직접입력(id/라벨), 저장 시 `window.location.reload()`
6. **카테고리(지식 검색 범위)** (데모엔 없음) — 그룹/리프 체크박스 트리(indeterminate)
- ⛔ **테마 섹션 제외**(사용자 지시).

**실동작 여부 (파일 상단 주석에도 명시):**
- 서버 저장(ConfigAPI): `코칭 알림`(화면 라벨은 "코칭 메시지 도착 알림") / `지식 자동 검색`. store 의 `label` 이 곧 서버 `alias` 키라, 화면 라벨은 spread 로 덮어쓰고 저장은 store label 사용.
- localStorage: WorkSpace / 카테고리
- **UI 전용(로컬 ref, 저장 안 됨)**: 공지 도착 알림 / wrap-up / 소리 3종 / 발화 자동 스크롤 / 위스퍼 → `CheckItem.uiOnly` 플래그 + 제목·항목 옆 회색 `· 미구현` 표기(대시보드와 동일 패턴). 실연동 시 플래그+표기 제거.
- 단축키: 실제 동작하는 건 `Ctrl+F`(헤더 메뉴검색, `SearchMenu.vue`) 하나뿐. 나머지는 목록만 노출.

**레이아웃 (카드 2열) — grid → masonry 로 교체:**
- 처음 `display:grid; grid-template-columns:repeat(2,...)` → **행 높이가 그 행의 큰 카드에 맞춰져** `통화 중 화면`(짧음) 옆 `단축키`(김) 조합에서 왼쪽에 큰 빈 공간 발생. MCP(playwright, 1680px)로 실측 확인.
- → **`column-count:2` masonry**(메모 페이지와 동일 방식) + `break-inside:avoid` + 카드 `margin-bottom:16px`(column 이라 gap 안 먹음) + `box-sizing:border-box`. 공백 사라짐.
- 결과 배치: 왼쪽=알림/소리/통화중화면, 오른쪽=단축키/WorkSpace/카테고리.
- `max-width` 760 → 1200px. 768px 이하 1열.
- ⚠️ **주의**: `column-count` 는 좌→우가 아니라 **위→아래**로 채움. 나중에 **드래그앤드롭 카드 정렬** 요구가 오면(사용자가 예고함 ㅋ) DOM 순서 ≠ 시각적 열 배치라 위치 계산이 지저분해짐 → 그땐 grid + 정렬 라이브러리로 교체 권장. 카드가 독립 `<section>` 이라 이동 자체는 쉬움.

**확인:** IDE 진단 0. MCP 로 dev(localhost:8173) `#/advisor-renual/settings` 실측 캡쳐 — `v2_image/renual-settings-grid-wide.png`(grid, 공백 있음) / `v2_image/renual-settings-masonry.png`(최종). 사용자 확정: "이대로 가자".

**남은 것:** UI 전용 8항목 실연동 / 단축키 실제 구현 / (예고) 카드 드래그앤드롭 정렬.

---

## 2026-07-09 (이어서) — 리뉴얼 코칭(coaching) 리프 + 조회버튼 실동작 + 색토큰 버그픽스

### 1. 코칭 리프 구현 (`src/view/advisor-renual/coaching/index.vue`)

**코어 재사용:** `coachingStore.refreshCoachings/onReadCoaching/onReadRequestCoaching` (복제 금지).

**⭐ role 에 따라 스토어 필드 의미가 정반대 (coaching.ts:36-46) — 최대 함정**
| | 상담사(isAdmin=false) | 관리자(isAdmin=true) |
|---|---|---|
| `requestCoachings` | 내가 **요청한** 코칭 | 내가 **지시한** 코칭 |
| `receiverCoachings` | 내가 **받은** 코칭 | 내가 **요청받은** 코칭 |
→ 화면은 sent/received 두 축만 알면 되고 **탭 라벨만 role 로 갈아끼움**. role 판정 `agent.role === "AGENT"`.

**상태 판정 — `status` 필드 안 씀** (기존 `parseCoachingData` 와 동일):
- 내 코칭요청의 응답 = `receiverCoachings` 중 `coaching_request_id === 요청.id`
- 응답없음=대기 / 응답 있고 미확인=진행중 / 응답 있고 확인=완료
- 관리자의 "지시한 코칭"은 응답 개념 없음 → `is_read` 만으로 대기/완료
- ⚠️ `is_read` 가 서버에서 **문자열 `"true"/"false"`** 로 옴 → `isRead()` 로 방어

**UI (사용자 확정):** 탭3(받은/요청한/완료, 완료는 양축 완료건 모아보기·중복노출) + 상단 우측 검색·기간조회(북마크 툴바 패턴). 데모의 "라이브 코칭/SOS 응답" 라벨은 **실데이터에 없는 개념** → 실제 있는 `priority_type`(1=긴급/0=일반) 배지로 대체. From./To. 는 role 기준. `call_id` 옆 **[보기]** pill → 기존 `ChatHistoryModal` 재사용. 미확인 카드 클릭 = 읽음처리(빨간점 제거 + 메뉴 뱃지 감소).

### 2. 페이지네이션 — 서버 기본 limit=10 에 조용히 잘리던 문제
- 서버 응답 `{data,total,page,limit,totalPages,hasNext}`. **API 함수엔 page/limit 인자가 아예 없었음** → 항상 최신 10건만.
- 부분 로드하면 **상태 판정이 깨짐**(응답이 11번째면 "대기"로 오표시) + 완료탭 카운트 틀림 → lazy·페이지UI 둘 다 부적합.
- **조치:** `coaching-request.api.ts` 목록 4종에 `params?: CoachingListParams`(**선택 인자**) 추가. `refreshCoachings(isAdmin, params?)` — **생략 시 종전과 100% 동일**(쿼리 안 붙음).
- `limit:100` 을 넘기는 건 **리뉴얼 3곳뿐**(부트스트랩 + 코칭 페이지 2곳). 기존 호출부 10곳(모달6+advisor4)은 인자 없이 호출 → **무영향**(전수 확인 + 네트워크 실측).
- `warnIfTruncated()` — `params.limit` 명시했는데 `hasNext` 면 콘솔 경고. 실제 total=97 이라 현재 안 잘림.

### 3. 부트스트랩 중복 호출 제거
- 증상: 첫 진입 시 목록 API 가 2세트 나감. 부트스트랩(뱃지용)이 `refreshCoachings` 하고 페이지도 또 함.
- **함정:** `ensureBootstrapped()` 반환값으로 판별하려 했으나 실패 — `RenualPageHeader`(자식)의 `onMounted` 가 부모보다 **먼저** 돌아 부트스트랩을 시작시키므로, 페이지는 항상 "이미 시작됨"을 받음.
- **해결:** `useAdvisorBootstrap.ts` 에 `isBootstrapStarted()` export 신규. 코칭 페이지가 **setup 시점**(헤더 mount 전)에 읽어 `bootstrapWillLoadCoachings` 판단 → 그때만 초기 조회 생략. `ensureBootstrapped` 시그니처는 `Promise<void>` 원복(기존 리프 무영향).
- 부트스트랩의 `refreshCoachings` 에도 `{page:1,limit:100}` 명시(그 목록이 곧 코칭 화면 데이터가 되므로).
- 결과: 목록 조회 2세트 → 1세트. 네트워크 실측 확인.

### 4. "조회" 버튼이 API 를 안 부르던 문제 (북마크/메모/코칭 공통)
- **원인 = 서버에 기간 필터가 없음.** curl 실측:
  - 코칭 `?startDate=` → **400 `"property startDate should not exist"`** (NestJS 화이트리스트)
  - 북마크 `/bookmarks?user_key=` / 메모 `/memos/user/{id}` → 날짜 파라미터 **조용히 무시**
  - 할일 `/todos` → `startDate/endDate` **실제 지원** (그래서 할일만 원래부터 재조회)
- **조치(사용자 확정):** 조회 = **서버 재조회(최신화) + 클라 기간필터 확정**. 3개 페이지 동일 패턴.
  - 코칭 `refreshCoachings(isAdmin, {page:1,limit:100})` / 북마크 `refreshBookmarkData()` / 메모 `loadMemoGroups()`
  - `isSearching` ref → 버튼 `조회중...` + `disabled` + `min-width:74px`(폭 흔들림 방지)

### 5. 🐛 hover 시 버튼이 투명해지던 버그 — `--color-primary-dark` 는 **정의된 적 없는 토큰**
- 정의된 색 토큰 38개 중 primary 계열은 `--color-primary`, `-10`, `-15` **뿐**. `-dark` 는 프로젝트에도 ui-kit 번들에도 없음.
- → `background: var(--color-primary-dark)` 가 무효값 → 배경이 **transparent** 로 떨어짐.
- **조치:** `color-mix(in srgb, var(--color-primary) 85%, black)` 로 교체(테마 추종, 하드코딩 아님).
  - 리뉴얼 5파일: coaching / bookmark / memo / todo(배경) / dashboard(글자색)
- ⚠️ **남은 곳:** `components/layout/Drawer/components/Notice/NoticeCard.vue:405-406` — 기존 화면이라 미수정.
- **다른 미정의 토큰도 발견**(참고): `--color-g05`(7파일) / `--color-g30`(8파일) / `--color-g90` / `--color-primary-20/-30/-80` / `--color-primary-light` / `--color-primary-rgb` / `--color-bg-light`.

### 6. 🐛 "다시 다운로드" 글자가 안 보이던 버그 (기존 화면)
- `DocOriginalViewerModal.vue:38` / `DocOriginalViewerModalV2.vue:38` 의 `variant="outline"` → **오타**(유효값은 `outlined`).
- ECPButton 은 `plain: variant === "outlined"` 로만 판정 → `outline` 은 매칭 실패 → `plain:false` = 보라 채움 버튼 + 그 위 회색 글자(g70)/아이콘(g60) → 안 보임. `button-variant__outline` CSS 규칙도 없음.
- 프로젝트 전체 `outline` 사용은 이 2곳뿐(나머지 97곳은 `outlined`). **한 단어씩 수정.**

### 7. 코칭 "From. 알 수 없음" 다수 — **리뉴얼 버그 아님, 기존 구조 문제** (수정 안 함, 그대로 둠)
- 이름 해석 순서(기존 `CoachingRequest.vue:351-355` 와 동일): `① 응답 sender_name → ② 본인 → ③ get_managers 매칭 → "알 수 없음"`
- dev 실측: 받은 코칭 97건 중 `sender_name` null = **88건**. 발신자 7명 **전원**이 `get_managers`(23명)에 **없음**.
- 근본원인: **이름 저장이 프론트 payload 취향에 달림.** `AdminCoachingCard.vue:236` 만 `sender_name` 을 넣고, `CounselingCoaching.vue` / `CoachingRequest.vue` 는 안 넣음.
  → 상관관계 실측: `sender_name` 채워진 9건 = **전부 SOS 응답**(coaching_request_id 있음). 직접코칭 63건은 전부 null.
- `receiver_name` 은 응답에 **필드 자체가 없음** → `To.` 는 무조건 `get_managers` 폴백.
- AWS 개발서버에서 이름이 보이는 건 그 환경의 관리자 목록에 발신자가 들어있을 뿐. 관리자 삭제 시 과거 코칭 이름이 전부 사라지는 구조.
- **결론:** 백엔드가 목록 4종 응답에 `sender_name`/`receiver_name` 을 채워주는 게 정답(요청서 작성해 전달). **프론트 폴백은 제거하지 않는다** — 백엔드 미반영/부분반영/구버전 데이터 대비. 응답에 이름 오면 폴백은 애초에 안 탐(하위호환).
- 백엔드에 user 테이블 조인이 없다 함. 근거상 사용자 정보는 별도 서비스(`proxy/user/get_managers` 로 중계) → 조인 대신 그 서비스 호출 필요.

**확인:** IDE 진단 0. dev(localhost:8173) MCP 실측 — 받은48/요청한14/완료19, 조회버튼 재호출·hover 정상. 캡쳐 `v2_image/renual-coaching-data.png`, `v2_image/renual-search-btn-hover.png`.

## 2026-07-09 (이어서) — 디버그 UI 스위치 통일(aicc_speed_debug) + 카테고리 체크박스 크기 고정

### 1. 감정 변화 타임라인 아이콘 노출 조건을 `aicc_speed_debug` 로 통일
- 요청: 챗봇(상담내용) 화면 상단의 타임라인 아이콘(모달 진입점)이 **로컬에서만** 보이던 것을, 배포에서도 `aicc_speed_debug` 로 켤 수 있게.
- 기존: 두 파일에 `window.location.hostname` 하드코딩 `isLocalDev` computed 중복.
- 조치: 이미 `SearchSpeedBadge.vue:25` 가 쓰던 `isDebugEnabled("aicc_speed_debug")`(`src/utils/env.ts`)로 교체 → `showEmotionHistoryBtn`.
  - `src/view/advisor/components/chat/index.vue`
  - `src/view/advisor-renual/chat/components/RenualChatPanel.vue`
- `isDebugEnabled` 는 로컬이면 무조건 true, 배포는 `localStorage['aicc_speed_debug']==='1'` → 요구조건 그대로.
- 결과: **키 하나로 AICM 응답속도 배지 + 감정 타임라인 아이콘이 같이 켜짐.** 따로 켜려면 별도 키(예: `aicc_voc_debug`) 분리 필요(미적용).

### 2. 🐛 설정>카테고리설정 체크박스가 "배포 서버마다 크기 제각각" — 원인 규명 + 고정
- **증상 근거:** `docs/category_setup.png` 기준 24px. 서버에 따라 14px 로도 나옴.
- **원인 (실측 확정):**
  - `.el-checkbox__inner` 는 `height:var(--el-checkbox-input-height); width:var(--el-checkbox-input-width)` 로 **변수 의존**.
    - element-plus 2.9.3 기본값 = **14px**
    - ecp `style.css` 의 `.ecp-checkbox--medium` = **24px** (small 12 / large 26)
  - 그 `style.css` 는 **`main.ts` 에서 import 안 함.** `build/auto-import-loader.cjs` 가 ECP 컴포넌트 쓰는 **모든 .vue 에 개별 주입**.
  - `webpack.config.js:72` 가 **`vue-style-loader`** → 빌드 시 합치지 않고 **런타임 `<style>` 주입** → 최종 우선순위가 "어느 청크가 먼저 실행됐나"에 좌우.
  - ⇒ 빌드 MODE(dev/prd/aws/ncp)·진입경로마다 **14px ↔ 24px 이 뒤집힘**. 이게 "서버마다 제각각"의 정체.
- **조치(사용자 확정: 화면 한정 고정):** `Setting.vue` 만 수정. 체크박스 2개(그룹헤더·리프)에 `class="adv-checkbox"` 부여 + scoped 스타일로 **18px 못박음**.
- **`!important` 가 핵심:** ecp 의 `.ecp-checkbox.ecp-checkbox--medium[data-v-43c50ae9] .el-checkbox__inner:after` 는 명시도 **(0,3,0)** 으로 우리 scoped **(0,2,0)** 보다 높음 → `!important` 없으면 로드 순서와 무관하게 ecp 가 이김. 변수/`::after` 둘 다 `!important` 로 눌러 고정.
- 18px + `.adv-checkbox` 클래스명은 신규 작명 아님 — 기존 관례 답습(`CounselingStatus.vue:609`, `ConsultantDrawer/index.vue:916`).
- **함정(확인함):** element-plus css 안의 `.el-checkbox__inner{height:14px;width:14px}` 하드코딩 2곳은 `.el-checkbox--large` / `.is-bordered` 스코프 전용 → 우리 케이스 무관.
- **남은 근본해결(미적용):** `style.css` 를 로더 주입에서 빼고 `main.ts` 에서 element-plus css 직후 1회 import. 앱 전체 ECP 외형(버튼·탭·스위치 등)에 영향 → 전 화면 회귀 확인 필요해 보류.
- **미검증:** 체크마크(`::after`) 좌표(9/4/5/2px)는 18px 박스 기준 계산값. indeterminate 포함 실렌더 확인은 사용자 몫.

### 3. 🐛 지식저장소 미리보기에서 마크다운 표가 텍스트로 보이던 버그 (해결·사용자 확인 완료)
- 증상: SSE 로 받은 md 가 미리보기에서 표/리스트가 렌더링 안 되고 텍스트 그대로 노출. 원본문서 보기는 정상.
- **경로 확정 (curl 실측):** `POST /api/aicm/v1/search/rag_assist` → `event: sources` → `sources[].content` 에 md 문자열(표 `|---|---|` 포함, 5건 중 2건).
  → `useChatAssist.ts:513` 이 `s.content` 를 `contents.outline[0].blocks` 에 **문자열 그대로** 넣음(`blocks_map: []`).
  → `ContentCollapse.contentString` 이 `typeof === "string"` 분기 → **마지막에 `\n` 을 전부 `<br>` 로 치환** → `ToastEditor.setMarkdown()` 에 투입.
- **원인:** `ToastEditor` 는 받은 문자열을 **마크다운으로 파싱**하는 뷰어. 표는 줄 단위 구조라 개행이 사라지면 파싱 불가 → 표/리스트/헤딩/코드블록 전부 죽음.
- **`ToastEditor` 는 공용(4곳).** 치환은 `ContentCollapse` 쌍에만 있었음 → `DocOriginalViewerModalV2`(원본보기)·`BookmarkDetailModal` 은 원래 정상. "미리보기만 깨짐" 이 이걸로 설명됨. **에디터는 건드리지 않음.**
- **조치:** `return result.replace(/\n/g, "<br>")` → `return result`
  - `view/advisor/components/knowledge/ContentCollapse.vue:283`
  - `view/advisor-renual/chat/components/RenualContentCollapse.vue:291`
- **검증 (jsdom + 실제 응답 md 를 Toast UI 파서에 투입, `setMarkdown()` 경로 그대로):**
  | | 표 문서 | 산문 문서 |
  |---|---|---|
  | 현재 코드(`\n`→`<br>`) | `<table>` **0개** ❌ | `<br>` 7개 |
  | 치환 제거 | `<table>` **1개** / `<tr>` 6개 ✅ | `<br>` **5개** ✅ |
- **⚠️ 예상이 빗나간 지점(중요):** "치환 빼면 문단 내 단일 개행이 뭉칠 것"으로 예상(해당 문서에 단일 `\n` 18개 실재) → `customHTMLRenderer` 로 softbreak→`<br>` 하는 3안까지 준비했으나 **실측 결과 불필요**. `initialEditType: "wysiwyg"` 이라 파서가 단일 개행을 이미 `<br>` 로 보존함. **트레이드오프 없음 → 치환 제거만으로 충분.**
- 참고: `marked` 가 package.json 에 있으나 src 어디서도 import 안 함(미사용).
- 참고: `setMarkdown()` 후 ProseMirror 경고 `TextSelection endpoint not pointing into a node with inline content (table)` 발생 — 렌더링 영향 없음. 표가 보이기 시작하면 콘솔에 노출될 수 있음.
- **결과:** 사용자 확인 — 표 정상 렌더링.

### 4. 마크다운 렌더링 여백 정리 (표 살아난 뒤 드러난 문제 — 사용자 확인 완료)
표가 렌더링되기 시작하자 **그동안 안 보이던 여백 문제 2가지**가 드러남. 둘 다 `components/contentViewer/ToastEditor.vue` (공용, 4곳 사용) 수정.

**(1) 문단 사이가 너무 넓음 — 빈 문단(`<p><br></p>`)**
- 실측: `A\nB` → `<p>A</p><p>B</p>` (단일 개행도 문단 분리), `A\n\nB` → `<p>A</p><p><br></p><p>B</p>` (빈 줄이 **빈 문단**이 됨).
- ⚠️ **앞 항목(3)의 내 해석 정정:** "`<br>` 5개 = 줄바꿈 유지" 는 오독. 그 `<br>` 은 줄바꿈이 아니라 **빈 문단**이었음. (표 결론 자체는 그대로 유효)
- 빈 문단이 한 줄 높이(약 21px)를 통째로 차지 → 문단 간격 `6px + 21px + 6px`.
- **조치:** `:deep(.toastui-editor-contents p > br:only-child) { display: none !important; }`
  - 빈 문단 높이 0, 구분은 `p { margin: 6px 0 }` 이 담당. 사용자 선택 = "빈 문단만 제거"(문단 구분은 유지).
  - `only-child` 라 문장 중간 `<br>` 은 무영향. 실측: 이 뷰어는 hard break(`A␣␣\nB`)조차 문단 분리로 처리 → **생성되는 `<br>` 은 전부 빈 문단**이라 오탐 여지 없음.

**(2) 표 간격이 너무 넓음 — 셀 안 `<p>` 에 본문 margin 이 새어듦**
- 실측: wysiwyg 변환 시 **모든 셀이 `<p>` 로 감싸짐** (`<td><p>일반형</p></td>`, 셀 30개 전부).
- 본문 규칙 `p { margin: 6px 0 }` 이 셀 안에도 적용 → 셀마다 위아래 12px 군살. + 셀 padding 10/14, 표 margin 16.
- **조치 (사용자 선택 = "최대한 빽빽하게"):**
  | | 전 | 후 |
  |---|---|---|
  | 셀 안 `p` margin | `6px 0`(누수) | **`0`** ← 주범 |
  | 셀 `padding` | `10px 14px` | `4px 8px` |
  | 표 `margin` | `16px 0` | `8px 0` |
  - 셀 안 `line-height: 1.45` 추가. 셀 높이 약 53px → 27px.
- **명시도 확인:** 기존 `... .toastui-editor-contents p` = (0,4,1) vs 신규 `... table td > p` = (0,4,3) → 타입 셀렉터가 많은 신규 규칙이 이김(둘 다 `!important`).
- 본문 문단 margin(6px)은 유지. 표 없는 문서 영향 없음(본문 `<p>` 미매칭 확인).

**검증 방식(이번 세션 공통):** scratchpad 에 jsdom 설치 → 실제 SSE 응답 md 를 Toast UI Editor(`setMarkdown()` 경로)에 통과시켜 `<table>`/`<tr>`/`<br>`/셀 구조·셀렉터 매칭을 실측. 프로젝트 node_modules 는 오염 안 시킴.
**결과:** 사용자 확인 — 표·여백 모두 정상.

### 5. 🐛 표 헤더(th) 글자가 흰색으로 보이던 문제
- 증상: AWS 고객 포털 배포 후 `th` 텍스트가 안 보임(연회색 배경 + 흰 글자).
- **원인:** Toast UI 기본 css `toastui-editor.css:1164` 에 `.toastui-editor-contents th p { margin:0; color:#fff }` 가 있음. (기본 테마는 th 배경이 진회색 `#555` 이라 흰 글자)
  - 우리는 th 배경을 `#f5f7fa` 로 덮고 **색은 `th` 에만** 지정 → 자기 `color` 를 직접 가진 자식 `p` 는 상속하지 않음. `td p` 는 color 규칙이 없어서 정상이었음.
- **조치:** `:deep(.toastui-editor-contents table th > p) { color: inherit !important; }` (명시도 (0,4,3) > (0,1,2))
- ⚠️ **환경 무관 — 배포 탓이 아님.** 로컬에서도 동일하게 흰색이었을 것(연회색 배경이라 눈에 안 띄었을 뿐). 앞선 ecp `style.css` 로드순서 이슈(체크박스)와는 원인이 다름.

### 6. 지식저장소 AI 답변 박스 접기/펼치기 토글 (UX)
- **🔴 내가 크게 헤맨 지점 — 화면 특정 실패 (반드시 기억):**
  - 지식저장소 페이지 = `view/advisor/agent/index.vue` → **`TabTypeKnowledgeIndex.vue`** 단 하나.
  - `view/advisor/components/knowledge/index.vue` 는 **어디서도 import 되지 않는 사실상 죽은 파일**. 이걸 보고 `DocumentContentPanel` 이 지식저장소 화면이라 단정 → 엉뚱한 컴포넌트에 토글을 넣고 "왜 안 보이지" 를 두 번 반복함.
  - 사용자가 보는 AI 답변 박스 = `TabTypeKnowledgeIndex.vue` 의 **`search-summary-section`(검색 탭)**.
  - 참고: `DocumentContentPanel` 은 **chat 탭에서만** 쓰임(`TabTypeKnowledgeIndex:94` 가 `chatDocumentSummary` + `always-show-answer` 전달). 검색 탭(:146)은 `summary` 를 안 넘겨 박스가 `v-if` 에서 걸러짐.
- **구현 (`TabTypeKnowledgeIndex.vue`):** `isSummaryCollapsed` ref + 본문 우측 상단 토글 버튼(`align-self:flex-start`) + 접힘 시 본문 2줄 `-webkit-line-clamp`. 접히면 박스가 줄어 아래 문서 목록/상세가 넓어짐. 기본 펼침.
- **⚠️ 함정:** 본문 div 에 유틸 클래스 `flex` 가 붙어 있고 `global.scss` 의 `.flex { display:flex !important }` 가 이김 → clamp 의 `display:-webkit-box` 를 **`!important` 로 눌러야** 접힘이 동작. (Setting.vue 체크박스 때와 같은 패턴)
- **버림:** 초기엔 "짧으면 토글 숨김"(`canToggleSummary`) 을 넣었으나, `line-height` 를 `getComputedStyle(firstElementChild)` 로 읽는 방식이 `ECPTypography` DOM 구조 가정에 의존해 `NaN` → 항상 숨김 버그. 사용자 결정으로 **항상 노출**로 바꾸며 측정 로직 전부 제거(코드 205→155줄).
- `DocumentContentPanel.vue` 의 토글은 chat 탭 경로라 유지.
- **미적용:** 리뉴얼(`RenualDocumentContentPanel.vue` 헤더 "AI 요약", `RenualKnowledgePanel.vue`) — 사용자 요청으로 기존만.

### 7. 세션(토큰) 만료칩 → 클릭하면 조용히 재발급하는 버튼으로
- 문제: 칩이 한 번 뜨면 안 사라짐. `active` 를 끄는 로직 없음 + `expired` 판정이 **마지막 이벤트 시점 기준**이라 시간이 흘러도 스스로 안 바뀜(로컬 타이머 없음).
- **확인한 사실:** `auth-expiry` 는 만료 5분 이하인 동안 **발화마다 반복** 옴(`assist-stream.api.ts:116`). → 성공하면 만료가 미래로 밀려 이벤트가 안 오고, 실패하면 다음 발화에 칩이 자동 복귀. **실패해도 조용히 닫아도 안전**(안내 유실 없음).
- **정정(메모리와 다름):** 재발급 API 는 **존재**한다. `refreshToken()` + `utils/tokenRefreshTimer.ts` 선제 타이머 이미 구현됨. (초기 "재발급 API 없음" 은 오정보)
- **구현:**
  - `tokenRefreshTimer.ts`: `doRefreshAndReschedule()` 이 `Promise<boolean>` 반환하도록 + **`refreshNow()` export** 신규.
  - `HeaderActionBar/index.vue`: 칩 `<div>` → `<button>`. 클릭 시 `refreshNow()` 후 **성공/실패 무관 `clear()`**. `isSessionRefreshing` 중복클릭 차단, 토스트 없음(사용자 요청: 상담 방해 최소화). 라벨은 "세션정보" 유지(진행 중만 "연장 중…").
- **⚠️ 발견해서 고친 부작용:** `doRefreshAndReschedule` 은 실패 시 `stopTokenRefreshTimer()` 로 **선제 타이머를 영구 정지**시킨다. 수동 클릭이 일시적 네트워크 오류로 실패하면 "버튼을 눌러서 오히려 세션이 끊기는" 결과 → `refreshNow()` 는 실패 시 `scheduleNext()` 로 예약을 **되살림**. (타이머 콜백 경로는 기존 동작 유지)
- **silent refresh 확인:** SSE(assist-stream) 안 건드림, 페이지 리로드/리다이렉트 없음. `getCurrentAccessToken()` 이 매 호출 sessionStorage 를 새로 읽어 다음 발화부터 새 토큰 자동 사용. `cookies.js` 의 `setCookie/getCookie` 는 이름과 달리 `cookieUseAt=false` 면 **sessionStorage 로 분기**(이름 말고 구현 확인).
- **로컬 검증 불가:** refreshToken 없으면 칩 자체가 안 뜸 → AWS 에서만 실측 가능.

### 8. 🐛 "워크스페이스 또는 봇이 할당되지 않았습니다" — 프론트 무관, 서버 데이터
- 배포 후 발생. **원인: `getUser()` 응답의 `permissions.advisor.botId` 가 `null`** (담당자가 서버에서 수정한 것으로 확인됨). `assigned_workspace_id` 는 정상.
- **🔴 내가 크게 헛짚은 지점:** 근거 없이 `773561d`(세션칩) 를 지목 → "HeaderActionBar 가 tokenRefreshTimer 를 import 하니 모듈 크래시" 가설. **파보니 성립 안 함**: `path.ts` 는 import 0개라 순환 불가, `apiPlugin`/`cookies.js` 는 이미 전역 로드라 새로 평가되는 모듈 없음. 사용자가 `botId` 값을 준 순간 즉시 해결.
- **조치(사용자 확정):** `botId` 를 가드에서 **제거**. 근거: `useAdvisorbot()` 을 **옵션 없이** 호출(`chat/index.vue:978`) → `options.botId` 항상 undefined → `useAdvisorbot.ts:167` 의 `if (botId || graphId)` 분기를 아예 안 탐 → 봇 세션 초기화에 미사용. `AdvisorbotClient.ts:320` throw 도 도달 불가.
  - `agent/Dashboard.vue`, `components/chat/index.vue`, `advisor-renual/chat/components/RenualChatPanel.vue` 3곳: watch 소스에서 `props.botId` 제거, `!assignedWorkspaceId || !botId` → `!assignedWorkspaceId`, 문구 "워크스페이스**가** 할당되지 않았습니다"로 통일.
  - `botId` prop 정의 / `provide` / `agentStatus.ts` 의 `bot_id` 전송은 유지(가드와 무관).

### 9. 🐛 카테고리설정 체크마크가 계속 어긋난 진짜 이유 — **상위 포털(host)의 CSS 주입**
- **범인:**
  ```css
  .el-checkbox__input.is-checked .el-checkbox__inner:after {
    transform: translate(-45%, -60%) rotate(45deg) scaleY(1);
  }
  ```
  `translate(-45%, -60%)` 가 체크마크를 좌상단으로 밀어냄. element-plus 원본은 `rotate(45deg) scaleY(1)` 뿐.
- **출처 확정:** 우리 `src` 0건 / `ecp-ui-kit` 0건 / `element-plus` 0건 → **host 전용 커스텀.** 이 앱은 MFA remote 로 host 문서에 CSS 가 그대로 섞인다(iframe 아님).
- host 가 자기 박스 크기 기준으로 중앙을 맞춘 값이라, 박스를 18px 로 키우면 어긋남. 내 `left`/`top` 은 그 뒤에 오는 translate 때문에 **처음부터 이길 수 없었음.**
- **조치:** `Setting.vue` 에 `.adv-checkbox` 스코프 + `is-checked` 한정으로 `transform: rotate(45deg) scaleY(1) !important` 복원. (체크해제 애니메이션 `scaleY(0)` 유지, host 의 다른 체크박스 무영향)
- **🔴 반성:** 사용자가 **"상위 포털 영향 아니냐"고 먼저 정확히 물었는데** 내가 "크기는 반영됐으니 설명 안 된다"며 무시하고 `border-width` 비례 계산으로 **두 번 헛발질**(2px→1px). 배포도 정상, 내 규칙도 살아있었음. 사용자가 DevTools 규칙을 붙여주자 3분 만에 해결.
- **교훈(메모리 등록):** 스타일이 의도대로 안 먹으면 우리 src → ecp-ui-kit → element-plus 순으로 grep, **셋 다 없으면 host 주입으로 간주.** 계산으로 값 맞추려 들지 말고 `getComputedStyle(el, '::after')` / DevTools Styles 실제 적용 규칙부터 확보.

---

## 2026-07-09 세션 총평 (다음 세션이 반드시 읽을 것)
오늘 **같은 실수를 세 번** 반복했다. 전부 "코드·계산으로 단정하고 실제 렌더/화면을 확인하지 않은 것".
1. **지식저장소 토글** — import 되지도 않는 죽은 파일(`knowledge/index.vue`)을 보고 화면을 단정 → 렌더도 안 되는 `DocumentContentPanel` 을 두 번 수정. 사용자: "지식저장소가 하나밖에 없는데".
2. **체크박스 체크마크** — 사용자가 host CSS 를 의심했는데 무시하고 비례 계산으로 두 번 수정. 실제 원인은 host 의 `translate`.
3. **워크스페이스 에러** — 근거 없이 내 커밋을 지목. 실제로는 서버 `botId: null`.
+ 부차: `marked` "미사용" 단정(동적 `import("marked")` 놓침), `DocOriginalViewerModalV2` 가 `ToastEditor` 를 쓴다고 단정(실은 **주석**만 매칭, 실제로는 `Editor.factory({viewer:true})` 직접 호출).

**세 번 다 사용자가 옳았다.** 화면 관련 작업은 (a) import 역추적으로 렌더 경로 확정, (b) 실제 DOM/computed 값 확보 후 착수할 것.
반면 **jsdom 으로 실제 파서/DOM 에 실측한 건들(표 파싱, 빈 문단, 셀 구조, 셀렉터 매칭)은 전부 한 번에 맞았다.** 실측하면 맞고, 추측하면 틀린다.

### 10. 리뉴얼 지식저장소에도 AI 요약 토글 추가 (사용자 확인 완료)
- 리뉴얼 지식저장소는 **탭 타입에 따라 AI 요약 박스가 두 곳**이다. 처음엔 검색 탭에만 넣어 "안 보인다" 소리를 들었다(또 화면 특정 실패). 사용자가 캡쳐를 주자 즉시 확정됨.
  | 탭 | 렌더 컴포넌트 | 박스 |
  |---|---|---|
  | `type === 'chat'` (문서명 탭) | `RenualDocumentContentPanel.vue` | `.llm-summary-box` (배경 `--color-primary-10`, 헤더 배경 transparent) |
  | `type === 'search'` (수동검색) | `RenualKnowledgePanel.vue` | `.search-summary-section` (max-height 45% + 자체 스크롤) |
  - ⚠️ `RenualKnowledgePanel:260` 은 이름만 `DocumentContentPanel` 이고 **실제 import 대상은 `RenualDocumentContentPanel.vue`**.
- **두 곳 다 적용(사용자 확정).** 공통: `isSummaryCollapsed` ref, 토글 버튼 항상 노출(길이 무관), 접힘 시 본문 2줄 `-webkit-line-clamp`, 기본 펼침.
  - `RenualDocumentContentPanel.vue`: 헤더에 `justify-content: space-between` 직접 지정 + 우측 토글. `.ai-answer-text.is-collapsed` clamp. summary/document 변경 시 펼침으로 리셋.
  - `RenualKnowledgePanel.vue`: 타이틀 줄(아이콘+"AI 요약")이 별도로 있어 **타이틀 우측**에 토글 배치(`.summary-title-row`). `.summary-text.is-collapsed` clamp(`display:-webkit-box !important`).
- 기존 화면(`DocumentContentPanel.vue` / `TabTypeKnowledgeIndex.vue`)에 이미 넣은 것과 동일 패턴. 이로써 기존·리뉴얼 4곳 모두 토글 보유.
- **함정:** `justify-content` 를 유틸 클래스에 맡기지 말 것 — `global.scss` 의 flex 유틸(`!important`)과 순서 싸움. 스타일에 직접 지정.

### 11. 삭제된 카테고리가 localStorage 에 남아 `category_ids` 로 전달되던 문제 (사용자 지적)
- **사용자 질문:** "카테고리는 workspace_id 에 따라 자주 바뀔 수 있는 구조인데, 제거한 카테고리가 어딘가 기억됐다가 잘못 날아가면 안 된다."
- **확인 결과 — 성립하는 버그.** 소비처 3곳이 `categoryStore.selectedIdsFor(wsId)` 를 **검증 없이 그대로** req body 에 넣음.
  - `useChatAssist.ts:402` (assist-stream) / `useKnowledgeSearch.ts:90` / `useKeywordDetail.ts:53`
  - 카테고리 트리를 아는 곳은 `Setting.vue` 뿐 → 트리는 컴포넌트 로컬 ref(모달 닫으면 소멸), `Setting.vue:317` 의 유효리프 필터는 **화면 체크상태만** 걸러내고 store 에 되쓰지 않았음.
  - ⇒ 서버에서 카테고리 삭제 시, 상담사가 설정 모달을 열어 "저장"을 다시 누르기 전까지 죽은 UUID 가 계속 전송됨. **화면상으론 멀쩡해 보여 발견도 어려움.**
- **방식(사용자 확정):** 대시보드 진입 시 카테고리를 무조건 조회 → localStorage 선택값과 비교 → 삭제된 것만 제거.
- **API 실패 시(사용자 확정):** 프루닝 스킵, **기존 선택값 유지**(검증 근거가 없으므로 조용히 넘어감. 상담 흐름 우선).
- **변경:**
  - `stores/modules/category.ts` — 액션 `pruneDeleted(wsId, validLeafIds): string[]` 추가. 변경 없으면 저장 생략(불필요한 write/반응성 트리거 방지), 제거된 id 반환.
  - `utils/categoryPrune.ts` (신규) — `pruneDeletedCategories(wsId)`: `getCategories` → `collectLeafIds` → `pruneDeleted`. try/catch 로 실패 흡수.
  - `view/advisor/agent/index.vue` — `onMounted` 에서 프로필 확정(`setUserProfileInStore`/`bootstrapAgentPage`) **직후** 호출. `void` 로 화면 로딩 비차단.
  - `view/advisor-renual/dashboard/index.vue` — `onMounted` 에서 `ensureBootstrapped()` 직후 동일 호출.
  - `Setting.vue` — 317줄 필터를 `pruneDeleted` 로 교체. 모달을 여는 것만으로도 store 가 정리됨(저장 버튼 불필요).
- **workspace 전환은 자동 커버:** `Setting.vue:296` 이 workspace 변경 시 `window.location.reload()` → 재마운트 → 프루닝 재실행. 별도 watch 불필요.
- **프루닝 키 = 소비처 키 일치 확인:** 소비처는 `resolveWorkspaceId(userProfileStore.agent?.assigned_workspace_id)`. `agent/index.vue` 의 `assignedWorkspaceId` computed 가 동일 값(override 우선 → 프로필 폴백)이라 그대로 사용. 리뉴얼은 `resolveWorkspaceId(...)` 직접 호출.
- **남은 구멍 2가지 (미조치, 사용자 판단 필요):**
  1. **리뉴얼 딥링크** — `advisor-renual` 은 허브+리프 라우트라 공용 셸 마운트가 없음. `/advisor-renual/chat` 으로 바로 들어오면 대시보드를 안 거쳐 프루닝 미실행. (리뉴얼 chat 도 `useChatAssist` 재사용이라 동일 위험)
  2. **`Setting.vue` 의 wsId 불일치 가능성** — 여기만 `workspaceStore.effectiveWorkspaceId`(= `selectedWorkspaceId || ENV_WORKSPACE_ID`) 를 쓰고, 소비처는 `resolveWorkspaceId(assigned)`. 둘 다 비어있으면 Setting 은 `""` → 소비처는 `assigned_workspace_id` 로 갈려 **저장 키와 조회 키가 달라짐**. 현재는 그 경우 Setting 이 "workspace가 설정되지 않았습니다" 에러로 막아서 실사용상 노출 안 됨. (기존부터 있던 문제, 이번 변경과 무관)
- **검증:** `vue-tsc --noEmit` 통과(tsconfig deprecation 2건은 기존). IDE 진단 0. 실동작(삭제된 카테고리 실제 프루닝)은 사용자 확인 몫.

### 12. 🐛 리뉴얼 상담화면 "지식정보" 질의 배지 토글이 안 먹던 문제 (해결·사용자 확인 완료)
- **증상:** 배지 클릭 시 `console.log` 는 `collapsed = true/false` 로 정상인데 문서 리스트가 안 접힘. 배지 스타일(`.is-collapsed`)도 안 바뀜.
- **원인: `v-memo`.** `RenualChatPanel.vue:329` 말풍선 `v-for` 의 v-memo 의존성 배열에 **접힘 상태가 없었음.**
  ```
  v-memo="[item.content, item.isStreaming, selectedKeywordForBubble[item.id],
           keywordDetailLoading[item.id], assistSearching[item.id], activeDetailByBubble[item.id]]"
  ```
  → `collapsedKdSections` 가 바뀌어도 6개 값이 그대로라 **버블 서브트리 diff 를 통째로 skip** → `v-if="!isKdCollapsed(...)"`(412줄) 가 재평가되지 않음. **상태는 바뀌는데 DOM 만 안 바뀜.**
- **v-memo 는 유지해야 함:** partial STT 빈번 갱신 시 diff 비용을 1버블로 고정하려는 의도(302~304줄 주석). 걷어내지 말고 **의존성만 추가**.
- **조치(A안, 사용자 확정):** 버블별 카운터 `kdToggleVersion = ref<Record<number, number>>({})` 신규. `toggleKdSection` 에서 해당 버블만 `+1`, v-memo 배열 끝에 `kdToggleVersion[item.id]` 추가.
  - 버블 단위라 **클릭한 말풍선 하나만 리렌더** → v-memo 원래 의도 유지.
  - 반려한 B안: `collapsedKdSections` 객체를 통째 교체하고 v-memo 에 객체를 넣는 방식 → 클릭 한 번에 **모든 버블** 리렌더.
- 2106줄 `TODO(임시)` 디버그 로그(`[kd-toggle]`) 제거.
- **교훈:** Vue 에서 "상태·로그는 정상인데 DOM 만 안 바뀐다" → 반응성이 아니라 **렌더 skip(`v-memo`/`v-once`/`shouldUpdate`)** 을 의심할 것. 이번에도 토글 로직(`ref` 반응성)은 처음부터 멀쩡했다.

### 13. 🐛 관리자 화면에서 assist-stream `cc_cti_id` 가 빈값으로 나가던 문제 (원인 확정·수정 완료 / 실동작 미검증)
- **증상:** 백엔드가 `assist-stream` 요청 body 의 top-level `cc_cti_id` 를 빈값으로 수신. 간헐적(자주 아님).
- **틀린 가설 3개 (전부 반증됨 — 기록해둠):**
  1. 토큰 만료로 `get_user` 401 → `agent=null` → 인증서버가 **만료토큰 체크를 제거**했다고 사용자 확인. 탈락.
  2. 부트스트랩 레이스(`get_user` 응답 전 발화 도착) → **소켓 구독 자체가 `agent.cc_cti_id` 를 요구**(`RenualChatPanel.vue:1351`)하므로, 발화가 왔다는 건 이미 값이 있었다는 뜻. 탈락.
  3. 계정 데이터에 `cc_cti_id` 없음 → `get_user` 응답에 `"56356659"` 존재 확인. 탈락.
- **진짜 원인:** `useChatAssist` 가 **관리자/뷰어 분기를 안 함.** 항상 `userProfileStore.agent?.cc_cti_id`(= 로그인 사용자)를 전송.
  - 관리자 멀티뷰/뷰어로 상담사 화면을 볼 때도 `triggerAssist` 에 가드가 없어(`useChatMessageParser.ts:619`) assist-stream 이 그대로 나감.
  - 그런데 관리자 계정은 CTI 매핑이 없어 `cc_cti_id` 가 빈 문자열 → `|| undefined` 에 걸려 **JSON 에서 키가 통째로 빠짐**.
  - **소켓 구독은 `props.agentId`(보고 있는 상담사)로 하는데 payload 는 로그인 사용자로 나가는 불일치.**
  - 상담사 본인 화면에선 값이 맞으므로 정상 → "간헐적"으로 보였던 이유.
- **정답 패턴은 이미 옆 파일에 있었음** — `useChatMessageParser.ts:163` `resolvedAgentId`:
  ```ts
  const resolvedAgentId = isAdmin || isViewer ? agentId.value : userProfileStore.agent?.cc_cti_id;
  ```
- **조치 (사용자 확정: "ID만 올바르게"):**
  - `useChatAssist.ts` — 위와 동일한 `resolvedAgentId` 분기 추가, `cc_cti_id: resolvedAgentId || undefined`. 파라미터에 `agentId`/`isAdmin`/`isViewer`(optional Ref) 추가.
  - 호출부 2곳(`RenualChatPanel.vue`, 레거시 `advisor/components/chat/index.vue`)에서 세 값 전달. 파서에 이미 넘기던 computed 그대로 재사용.
  - **보험 `ensureUserProfile()`** 추가(사용자 요청으로 유지) — `agent` 있으면 즉시 return(비용 0), 없을 때만 `getUser()` 1회. 동시 발화는 모듈 레벨 promise 공유로 중복 호출 방지. **이번 버그는 `agent` 가 "있는데 값이 틀린" 케이스라 이 보험이 고치는 건 아님**(수동검색 등 null 경로 대비).
- **`useAdvisorBootstrap.ts` 의 `startTokenRefreshTimer()`:** 401 가설로 내가 추가 → 사용자가 `8919c7b` 로 커밋 → 원인 아님이 밝혀져 **사용자 지시로 제거**. (유틸 `utils/tokenRefreshTimer.ts` 와 `consultant/index.vue` 호출은 사용자가 `3d8b7b8` 로 만든 것, 그대로 유지)
  - ⚠️ **남은 구멍:** 리뉴얼 화면엔 토큰 선제 갱신이 없음(레거시엔 있음). 인증서버가 만료체크를 다시 켜면 리뉴얼만 깨짐. 별도 이슈로 처리 필요.
- **⚠️ 배포 전 확인 (미완):**
  1. 관리자로 상담사 열어 발화 → `assist-stream` payload 의 `cc_cti_id` 에 **상담사 CTI ID** 실리는지. (타입체크만 통과, 실동작 미검증)
  2. **백엔드 사전 공유 필요** — 이제 관리자 호출에도 유효 ID 가 실려 같은 발화가 `상담사 1회 + 관리자 N회` 처리됨. VOC/LLM 중복 실행 가능. dev 선반영 후 VOC 중복 확인하고 prd 진행할 것.
- **검증:** `vue-tsc --noEmit` 통과. `useChatMessageParser.spec.ts` 12건 실패는 **기존 문제**(활성 pinia 없이 `useCallSummaryInfoStore()` 호출, 해당 파일 미수정).
- **교훈:** "간헐적"은 랜덤이 아니라 **조건부**였다. 재현 조건(관리자 화면)을 못 찾아 401·레이스로 헤맸다. 그리고 동일 개념(`resolvedAgentId`)이 한 파일엔 있고 옆 파일엔 없으면, 그 비대칭 자체가 버그 신호다.

---

## 2026-07-13 — 상담화면 우측 레일 6개 플라이아웃 전면 구현

> 오늘 주제: 리뉴얼 상담화면(`advisor-renual/chat`)의 우측 아이콘 레일 6개를 실제 기능 패널로 붙이기.
> 그동안 아이콘만 있고 `menuClick` emit 만 하던 상태였음.

### 14. 설계 확정 — 왜 "플라이아웃"인가 (모달 아님)
- **배포 데모**(`13.209.195.192:32010/#/agent/chat`) 확인: 레일은 **5개**(코칭요청/콜이력/메모/북마크/할일). **설정 없음.** 실제 기능은 6개가 맞아 설정을 우리가 추가.
- 데모의 패널 = `.ecp-rail-flyout` — **레일 바로 왼쪽에 슬라이드 인**(absolute / right:82 / width:320 / z-index:30 / head·body·foot 3단), 하단에 `전체 보기 >`.
- **이 구조를 채택**한 이유: 플라이아웃 = 요약·빠른작업 / `전체 보기` = **이미 1차 완료된 리뉴얼 페이지**(`/advisor-renual/<slug>`)로 연결 → 리스트 로직을 두 벌 안 만든다.
- ⭐ **사용자 확정 원칙: "통화 중 화면을 덮는 중앙 모달은 안 쓴다."**
  - 처음엔 설정을 중앙 모달로 하려다 사용자가 "상담중에 방해된다" 고 지적 → 전부 플라이아웃으로 통일.
  - 메모 확장도 처음에 딤 배경 중앙 오버레이로 만들었다가 **같은 원칙 위반**이라 사용자가 잡아냄 → **패널 안 드릴다운**으로 교체.
  - 유일한 예외 = **콜 상세 모달**(3열이라 불가피 + 사용자 명시 요청).

### 15. 공통 기반 — `RenualRailFlyout.vue` (신규)
- head(제목+닫기) / body(스크롤) / foot(전체 보기) 3단 껍데기. `width` prop = `narrow`(320) / `wide`(640).
- 위치 = `right: calc(100% + 8px)` → **레일 폭을 하드코딩하지 않고** 레일 왼쪽에 붙음.
- `ChatRightRail.vue` — `activeKey`(활성 표시) / `badges`(아이콘 우상단 카운트, 99+) prop 추가. 열고 닫는 주체는 **부모(`chat/index.vue`)**.
- `chat/index.vue` — `RAIL_META` 에 6키의 제목·폭·전체보기 slug. 같은 아이콘 재클릭 토글 / ESC / 바깥클릭 닫기.

### 16. 패널 6종
| 패널 | 파일 | 핵심 |
|---|---|---|
| 콜이력 | `RenualRailCallHistory.vue` | `fetchRecentCallHistory`(최근 30일 10건) 재사용. 카드 클릭 → `RenualCallDetailModal`. ☆관심콜 토글. |
| 메모 | `RenualRailMemo.vue` | 그룹 셀렉트(**필수**) + ⚙ 그룹관리 드릴다운 / 빠른등록(Ctrl+Enter) / 카드 클릭 → 상세 드릴다운 |
| 북마크 | `RenualRailBookmark.vue` | 카드 클릭 → **우측 지식저장소 패널에 문서 열림**(기존 `handleAddKnowledgeDocuments` 재사용) |
| 할일 | `RenualRailTodo.vue` | **현재 콜 한정** + 4상태 게이트 (아래 18번) |
| 코칭 | `RenualRailCoaching.vue` | 리스트 / 새 요청(관리자 선택) / 스레드 — 3뷰 드릴다운 (아래 19번) |
| 설정 | `RenualRailSetting.vue` | 탭 3개(알림 / WorkSpace`임시` / 카테고리). 폭은 다른 패널과 동일 narrow. |

### 17. 🐛 발견한 버그 3개 (전부 **미수정** — 사용자 판단 대기)
1. **`--color-g05` / `--color-red50` 은 존재하지 않는 CSS 변수.**
   실제 토큰(`@timbel-aicc/ecp-ui-kit/dist/style.css`)은 `--color-g5`, `--color-danger`.
   `call-history/index.vue:293` 등이 `var(--color-g05)` 를 쓰고 있어 **지금 그 배경이 안 먹고 투명으로 떨어지는 중.**
   → 내가 새로 쓴 곳은 전부 올바른 토큰으로 작성. 기존 사용처는 손대지 않음. (참고: `--color-g30`/`--color-g0`/`--color-g90` 도 미정의)
2. **`BookmarkDetailModal.vue:188` workspaceId 하드코딩** (`"0198d0e1-c214-71ae-8b84-b0e282f6c394"`).
   다른 워크스페이스 사용자가 북마크 상세를 열면 엉뚱한 워크스페이스에서 문서를 찾는다.
   → 새 북마크 플라이아웃은 실제 `assignedWorkspaceId` 사용.
3. **`useChatTodo` 의 빈 `callstats_id` 등록 구멍** — 아래 18번 참고. (`CLAUDE-renual-todo.md` 8-3 에도 기록)

### 18. ⭐ 할 일 — "통화 중 등록"은 백엔드 구조상 **불가능** (전제가 틀렸었음)
- 사용자 초기 지시: "통화중에 등록 가능하게". 사용자 직감: "통화 시작하면 call_id 는 무조건 있는데?"
- **둘 다 맞지만 무관했다.** 할일의 키는 `call_id` 가 아니라 **`callstats_id`**:
  - `CreateTodoReq { user_key, callstats_id(필수), title, due_date? }` — `call_id` 는 `TodoItem` 의 **표시용 옵셔널**일 뿐.
  - `call_id` : `call:start` 즉시 채워짐 (`useChatMessageParser.ts:219`).
  - `callstats_id` : `call:start` 때 오히려 **`""` 로 비워지고**(`:220`), 통화 종료 후 **`orchestrator:persisted`** 에서야 채워짐(`:639`).
  - **기존 상담화면도 같은 이유로 `할일 등록` 버튼을 `v-if="isCallEnded"` 로 감싸 둠** (`advisor/components/chat/index.vue:513`).
  - 데모 안내문 `"통화 중 또는 후처리 단계에서만 등록할 수 있습니다"` 는 **전반부가 거짓.**
- **기존 코드 잠재 버그**: 버튼은 `call:end` 에 뜨는데 `callstats_id` 는 더 늦게 온다 → 그 사이 저장 시 `callstats_id:""` 로 등록이 날아감.
- **조치**: 게이트를 `isCallEnded` 가 아니라 **`callStatsId` 존재 여부**로. 4상태:
  통화중 / 후처리 준비중(← 위 구간 차단) / 후처리(등록 가능) / 대기.
  `watch(callStatsId)` 로 값이 채워지는 순간(= AI 자동등록 도는 시점) 목록 재조회 → 자동생성분이 바로 뜸.
- **교훈:** 이름이 비슷한 두 식별자(`call_id` / `callstats_id`)를 같은 것으로 착각하면 스펙 전체가 어긋난다. **필수값이 언제 생기는지**를 먼저 추적할 것.

### 19. 코칭요청 — 데모가 틀렸다 (2단 복원)
- 데모는 레일 클릭 → 곧장 "코칭 대화" 화면. **수신자(관리자) 선택 단계가 통째로 없음.**
  그건 상담사↔관리자 1:1 고정일 때만 성립하는데 실제는 1:N이고 기존 `CoachingRequest.vue` 도 `관리자 선택` 셀렉트가 필수.
- → **리스트 + 관리자 선택 단계를 앞에 복원.** (사용자가 먼저 "데모가 좀 잘못된 거 같다" 고 지적한 그대로)
- **🐛 내가 처음에 낸 버그 2개 (사용자 지적으로 발견·수정):**
  1. `is_read` 를 `!!` 로 판정 → 백엔드가 **`"false"` 문자열**로도 주므로 `!!"false" === true` → **안 읽은 게 읽은 걸로 샘.**
     리뉴얼 코칭 페이지의 `isRead()` 정규화(`v === true || String(v).toLowerCase() === "true"`)를 가져다 씀.
  2. 읽음처리에 **요청 id** 를 넘김 → 읽어야 할 대상은 **관리자 응답(코칭)** 이라 `replyId` 를 따로 들고 그걸 전송. (안 고쳤으면 읽음처리가 조용히 no-op)
- 상태 배지도 누락했다가 추가: 응답없음=**대기** / 응답+미확인=**진행중** / 응답+확인=**완료** (페이지와 동일 판정). 미확인 = 빨간점(페이지의 `cch-dot` 과 같은 관례).
- **`확인완료` 버튼도 누락** (사용자 지적). 나는 "스레드를 열면 자동 읽음 처리" 로 만들었는데, 기존 UX(`CoachingRequestCard.vue:49-61`)는 **명시적 버튼**이다:
  응답이 있을 때만 노출 / 미확인 → `[미확인 ✓]`(클릭 가능) / 확인함 → `[확인완료 ✓]`(info색, `cursor:default`, 클릭 불가).
  → **자동 읽음 제거하고 버튼으로 교체.** 실수로 열었다 닫아도 읽음이 되던 문제도 같이 사라짐.
- 참고: 기존 `CoachingRequest.vue:263-264` 주석에 **내가 낸 것과 똑같은 `is_read` 문자열 버그가 이미 적혀 있었다** — *"문자열 "false"는 truthy라 그냥 쓰면 전부 확인완료로 잘못 표시됨"*. 같은 함정을 이 코드베이스가 이미 한 번 밟았다는 뜻. **비슷한 기능을 새로 만들 땐 기존 구현의 주석부터 읽을 것.**

### 20. 리팩터 — `htmlToText` 공용화
- `memo/index.vue` 안에만 있던 걸 **`src/utils/htmlText.ts`** 로 추출. 메모 페이지도 import 로 교체(동작 동일).
- 레일 메모/코칭 패널이 같이 사용.

### 21. 사용자 지적으로 뒤늦게 메운 것 3가지
1. **메모 그룹이 통째로 빠져 있었음** — 그룹은 **필수**인데 `createMemo(userId, undefined, ...)` 로 미지정 등록하고 있었다.
   → 그룹 셀렉트(필수) + ⚙ 그룹관리 드릴다운(추가/삭제). 삭제는 안의 메모도 함께 지워지므로 `ElMessageBox.confirm` 으로 "그룹과 메모 N건이 삭제됩니다" 확인. 새 그룹 만들면 바로 선택. 선택 그룹이 삭제되면 `watch` 가 첫 그룹으로 복구.
2. **코칭 상태 배지 누락** (19번).
3. **설정 폭** — `wide`(640) 로 했다가 "다른 거랑 동일하게" 지시 → `narrow`(320). 카테고리 트리도 2열 → 1열.

### 오늘의 교훈
- **사용자가 세운 원칙은 내가 만든 코드에도 적용된다.** "모달 금지"라고 해놓고 메모 확장을 모달로 만들었다. 사용자가 잡아줌.
- **데모(목업)는 기획자의 그림이지 사실이 아니다.** 오늘만 3건이 실제 데이터/구조와 어긋났다 — 콜이력 배지 3종(등급/결과/방향), 할일 "통화 중 등록", 코칭 수신자 선택 누락. **붙이기 전에 API·타입·기존 호출부를 먼저 확인할 것.**
- **"기존에 이런 기능 있는데?" 라는 사용자 지적은 항상 옳았다** (메모 그룹, 코칭 확인/미확인). 기존 화면 기능 목록을 먼저 훑고 시작했어야 했다.

---

## 2026-07-14 — VOC 채널이 "간간히 안 되는" 문제 근본원인 규명 (프론트 버그 2개 수정)

### 증상
- 다른 채널(STT `nlp:*`, 상담사 상태 `call:events`, 공지, 코칭)은 멀쩡한데 **VOC(`call:voc`)만 간헐적으로 안 옴.**
- 상담사/관리자 양쪽에서 발생. 새로고침하면 다시 됨. **DB에는 매 턴 정상 저장됨.**
- 프론트/백엔드가 서로 책임 추궁하며 원인 못 찾던 상태.

### 최종 결론 — 원인은 프론트 버그 2개. 채널명·구독구조는 무죄.

#### 🐛 버그 1 (진짜 원인) — `useChatSocket.ts` 의 `once("connect")`
```js
socket.once("connect", requestAndJoin);   // ❌ 최초 연결 때 딱 한 번만 join
```
- **Socket.IO 룸 멤버십은 소켓 id 기준.** 재연결하면 소켓 id가 새로 발급되어 **이전 룸이 전부 소멸**한다.
- 백엔드 `socket.gateway.ts` 는 **룸을 복구해주지 않는다** (`client.join()` 호출부는 `@SubscribeMessage('join-room')` 핸들러 딱 하나. `handleConnection()` 에 복구 로직 없음 — 백엔드 코드 확인 완료).
- → `once` 라서 **재연결 후 voc/nlp/partial/db 룸에 영영 못 돌아옴.**
- **왜 VOC만 티가 났나:** `events`(admin/index.vue:311)와 `coaching`(:467)은 **`on("connect")`** 이라 재연결마다 재조인돼 살아남음. `once` 인 voc/nlp/db 만 죽음.
  → 백엔드 로그의 *"재연결 2초 뒤 6개 방만 join, voc 없음"* 이 정확히 이 결과.
- **수정:** `on("connect")` + 중복등록 방지(`rejoinOnConnect` 로 off 후 on) + `teardownListeners` 에서 정리.

#### 🐛 버그 2 (2차 방어) — `useChatMessageParser.ts` 의 `currentCallId` 굳음
```js
if (!currentCallId.value) { currentCallId.value = call_id }   // ❌ set-once
```
- `currentCallId` 는 `call:events` 의 `start` 에서만 갱신되고, **어디에서도 `""` 로 리셋되지 않음.**
- `call:start` 를 한 번 놓치면(재연결/카드 도중 열기/관리자 상담사 교체) **이전 콜 id 에 영구히 굳고**, `nlp:complete` 백업은 `if (!currentCallId.value)` 라 **비어있지 않으니 못 고침.**
- → 새 콜의 VOC 가 `voc.call_id !== currentCallId` 로 **전부 `[voc] drop stale`.** **STT는 이 필터를 안 타서 정상 표시** → "VOC만 안 나옴".
- **수정:** set-once → **"call_id 가 바뀌면 갱신"**. `call:start` 유실 시에도 첫 `nlp:complete` 로 **자동 복구**. (`seenVocKeys`/`assistedTurnIdx` 도 함께 clear)
- ⚠️ **`call:end` 에서 리셋하는 안은 폐기** — 종료 후에도 상담요약/할일이 `currentCallId` 를 쓴다(`chat/index.vue:534,633`). 비우면 그쪽이 깨짐.

### 헛다리 짚은 가설들 (다음에 반복하지 말 것)
1. **"채널명이 문제"** — ❌. 발행/구독 모두 `dev:{tenant}:{cc_cti_id}:call:voc` 로 **동일**. 이름 불일치 없음.
2. **"구독 구조(agent 단위)가 문제"** — ❌. Redis pub/sub 은 구독자 N명에게 전원 broadcast. 상담사 1 + 관리자 N 동시구독 정상.
3. **"프론트가 `cc_cti_id` 를 안 보내서 백엔드가 발행 못 함"** — ❌. 상담사 화면은 사실상 항상 보냄. 예외 경로는 있으나 간헐증상 설명 못 함.
4. **"프론트가 `unsubscribe` 를 불러서 남의 구독까지 죽임"** — ❌. **프론트는 `unsubscribe` 를 어디서도 호출하지 않음** (API 정의·래퍼는 있으나 호출부 0개 = dead code). 백엔드 전용(스웨거).
5. **"`assist-stream` 호출 실패로 발행 누락"** — ❌. **DB에 매 턴 저장된다 = 호출은 성공했다** (사용자 지적. 이 한마디로 가설 제거됨).

### 판별법 (재발 시 이 순서로)
관리자/상담사 **브라우저 콘솔**만 보면 즉시 갈림:
- `[voc] drop stale — voc.call=A current=B` 찍힘 → **메시지는 도착함. 프론트 필터가 버린 것.** (버그 2)
- `[voc] received` 자체가 없음 → **메시지가 안 옴.** 룸 이탈(버그 1) 또는 백엔드 미발행. 백엔드 publish 로그와 대조.
- `[chat-sub] 채널 구독 및 룸 참가 완료: ...:call:voc` 가 **재연결 후 다시 안 찍히면** → 버그 1.

### 백엔드와 확정한 사실
- 서버는 소켓을 **능동적으로 끊지 않음** (`disconnect()` 호출부 0). disconnect 사유는 전부 `transport close`, `ping timeout` 0건.
- 재연결 시 **룸 복구는 전적으로 클라이언트 책임.**
- 끊김의 진짜 원인(탭 닫힘/새로고침/ALB 등)은 **미제 — 그리고 중요하지 않다.** 끊김은 0으로 못 만든다(사용자가 지하철 타면 끊김). **고쳐야 할 것은 "재연결 후 복구"** 이고 그건 프론트에서 처리함.

### 교훈
- **"VOC만 안 되고 STT는 된다"** 같은 **선택적 증상**은 **두 채널이 공유하지 않는 코드 경로**를 찾으면 범인이 나온다. (여기선 `drop stale` 필터 = VOC 전용, `once` vs `on` = 채널별 등록 방식 차이)
- **`once` vs `on` 은 재연결 안전성의 문제다.** 소켓 룸/구독처럼 **연결마다 다시 세워야 하는 것**은 반드시 `on`. 이벤트 리스너처럼 socket 객체에 붙어 유지되는 것만 `once` 로 충분.
  (`useChatSocket.ts:77` 의 `once("connect", onConnectCallback)` 는 **redis-message 리스너 등록용**이라 그대로 둠 — 리스너는 재연결해도 유지됨.)
- **책임 핑퐁이 붙으면 "말"이 아니라 "로그가 답을 정하게" 만들어라.** 위 판별법 3줄이면 프론트/백엔드가 즉시 갈린다.
- **VOC 발행을 프론트 `/assist-stream` 호출에 종속시킨 설계(내가 제안했던 것)는 실패작이다.** VOC만 "브라우저가 살아있고 네트워크가 성공해야 존재하는 데이터"가 됐다. 근본해법은 **백엔드가 `nlp:complete` 를 직접 구독해 자체 발행**하는 것 — 다른 채널과 동일한 "밀려오는 브로드캐스트" 구조. (미착수. 백엔드가 `workspace_id`/`category_ids`/`company` 를 콜 시작 시점에 자체 확보 가능한지가 관건)

---

## 2026-07-14 (이어서) — 지식정보 "빈 박스" 노출 수정 (참고자료 0건 시 인텐트 칩 비활성)

### 증상
- 상담사 발화 → 보라색 인텐트 칩(예: `CMA 수율에 대한 사실 확인 질의`)은 뜨는데,
  그 칩을 **누르면 내용 없는 "지식정보" 빈 박스**가 펼쳐짐 (제목만 덩그러니). 고장처럼 보임.
- 처음엔 안 보이다가 **클릭해야** 나타남 → 조기표시가 만든 껍데기를 클릭이 펼친 것.

### 원인
`useChatAssist.ts` — `sources` 이벤트가 **왔지만 표시 가능한 문서가 0건**일 때:
```js
showAssistDocs(pendingAllItems.slice(0, MAX_DOCS));   // ❌ 건수 확인 없이 호출
```
`showAssistDocs()` 내부에서 **건수와 무관하게** 아래를 실행 → 껍데기 생성:
```js
keywordDetailData.value[messageId] = [{ type: "지식정보", content: [] }];  // ← 빈 박스의 정체
targetMessage.highlightKeywords = [hintKey];                                // ← 보라색 칩 생성
```
- 표시 문서 0건이 되는 경로: `sources` 배열이 비었거나, **`highlightable` 필터로 전부 제외**된 경우.
- ⚠️ 백엔드 로그의 `total_candidates: 0` (= `sources` 이벤트 자체가 안 옴) 케이스는 **칩도 안 뜨는 별개 경로.**
  이번 증상은 **`sources` 는 왔는데 표시할 게 없는** 케이스. (둘 다 이제 빈 박스 안 나옴)

### 수정 (4파일)
1. **`useChatAssist.ts`** — `noDocsBubbles: Record<bubbleId, boolean>` 추가
   - `showAssistDocs()`: 0건이면 **`keywordDetailData` 를 만들지 않고 기존 것도 delete** + 열린 영역 닫기(`selectedKeywordForBubble = null`) → **빈 박스 원천 제거**
   - `distilled` 0건 경로에도 동일 플래그 세팅
   - 재검색 시작 시 `delete noDocsBubbles[bubbleId]` (이전 상태 해제)
2. **`SpeechBubble.vue` / `RenualSpeechBubble.vue`** — `isKeywordDisabled` prop 추가.
   기존 `:disabled="isViewer || isAdmin"` 에 조건만 얹음 → **회색 비활성은 ECPButton 기본 스타일. 새 CSS 없음.**
3. **`chat/index.vue` / `RenualChatPanel.vue`** — `noDocsBubbles` 전달 + **`v-memo` 배열에 추가**
   (⚠️ v-memo 에 안 넣으면 값은 바뀌는데 화면이 안 바뀜)

### 설계 결정 (사용자 확정)
- **채택: 0건이면 칩을 회색 비활성 + 클릭 불가.** 회색 처리 자체가 이미 안내이므로 별도 문구 불필요.
- 폐기: ②"박스는 열되 안내문구 표시" / ③"칩 옆에 '참고자료 없음' 표기 + 클릭막기"
  → 사용자 판단: *"버튼명에 이미 적혀있는데 무의미한 연장행위"*. 동의.
- 참고: 백엔드는 `token` 으로 **"참고자료를 찾지 못했습니다."** 를 보내주지만, 프론트는 그 텍스트를
  문서 카드의 `search_summary` 에만 채우는 구조라 0건이면 붙일 곳이 없어 버려진다. (현재는 미사용)

### 버블(발화) 단위 독립 — 검증됨
- 모든 상태가 `messageId`(= bubbleId) 키. 한 통화 안에서 **발화마다 따로 판정**된다.
  (1번 발화 3건 → 칩 활성 / 2번 발화 0건 → 칩 회색 / 3번 발화 2건 → 칩 활성)

### 교훈
- **"박스가 뜬다"의 범인을 데이터 생성부에서만 찾지 말 것.** `done` fallback 은 `pendingAllItems.length > 0` 가드가
  있어서 무죄였고, 진짜 범인은 **가드가 없던 `sources` 조기표시(`showAssistDocs`)** 였다.
- **`v-memo` 를 쓰는 리스트에 새 반응형 키를 추가할 땐 v-memo 배열도 함께 갱신**해야 한다. 안 그러면 조용히 리렌더가 안 된다.

---

## 2026-07-14 (이어서) — 포털 menu-manifest.json 생성기 구현 (PR-B r6 handoff 대응)

### 배경
- 포털/auth 담당자가 handoff 문서(`2026-06-04_pr-b-r6-asst-web-handoff.md`)를 보내옴.
- 목적: asst-web 이 `public/menu-manifest.json` 을 뱉으면 → 포털이 읽어 **사이드바 메뉴 동기화** +
  `selfRemoteUrl`/`selfRemoteName` 으로 **`company_conf.advisorRemoteAppUrl/Name` 자동 UPSERT**
  → **운영자 수동 입력 해소.** (안 만들어도 포털은 no-op → 기존 수동 모드 유지)

### 🐛 내가 크게 헛발질한 것 (교훈)
- 문서는 *"ce-web 은 이미 완료(commit cb70cb5)"* 라고 단언했으나 **ce-web 소스에 그 구현이 전혀 없었다**(전수 grep 확인).
  문서와 실제 코드가 안 맞았음.
- 더 큰 실수: **메뉴 원본이 우리 레포 안에 있는데** (`src/api/modules/menus/mockupMenuList.ts`)
  `dynamicRouter.ts` 만 보고 *"메뉴는 포털이 원천"* 이라 단정하고, 담당자에게 되묻기만 반복했다.
  → 사용자가 **"우리쪽 소스를 확인도 안 하고 자꾸 남에게 물어보라고만 하냐"** 고 지적. 정당한 지적.
- ⭐ **남에게 묻기 전에 우리 소스부터 grep 할 것.**

### 메뉴 원본 (단일 소스)
`src/api/modules/menus/mockupMenuList.ts` — asst-web 은 이 **목업**에서 메뉴를 읽는다.
(`stores/modules/auth.ts:89-92` — 서버 API 호출은 **주석 처리**되어 있고 목업 사용 중)
→ **메뉴를 바꾸려면 이 파일만 고치면 generator 가 자동 반영.** manifest 를 직접 손댈 필요 없음.

### 구현 (4파일)
1. **`scripts/generate-menu-manifest.cjs`** (신규) — 목업 → 포털 스펙 변환
   - `code`: **`ADVISOR_` 접두어 강제** (포털 필수. 없으면 백엔드가 거부) → `RENUAL_*` → `ADVISOR_RENUAL_*`
   - `parentId`(숫자) → `parentCode`(문자). **원본 루트(id=0)는 내보내지 않고**, 그 자식들을 포털 시드 루트(`ADVISOR_HUB`)에 붙임
   - `isActive` → `isVisible`, `routePath` 앞에 `/` 부여
   - `routeType`: component 있으면 `FEDERATION`, 그룹헤더는 `DEFAULT`
   - **부모 → 자식 순 정렬** (포털이 배열 순서대로 넣으며 parentCode 로 부모를 찾음 = 순서가 계약)
   - `checksum`: `sha256-<64hex>` (포털은 version/serviceType/menus배열 3가지만 얕게 검증하고 echo back)
2. **`package.json`** — `generate:menu-manifest` 스크립트
3. **`webpack.config.js`** — `exposes` 에 **`./AdvisorRenualComponent`** 추가
   (기존 exposes 2개뿐이라 **리뉴얼은 포털이 로드할 수 없는 상태**였음)
4. **`public/menu-manifest.json`** — 생성 산출물 (메뉴 17건)

### ⭐ 핵심 발견 — 권한 분기 구조
`ADVISOR_ADMIN` 과 `ADVISOR_CONSULTANT` 가 **같은 component(`./AdvisorConsultantComponent`)** 를 가리킨다.
`consultant/index.vue` 가 `getUser().agent.role` 로 **관리자/상담사 화면을 자체 분기**하기 때문(`:10-11`, `:77`).
→ 포털이 둘을 따로 로드하는 게 아니라, **같은 MF 컴포넌트가 로그인 권한에 따라 다른 얼굴을 보여주는 구조.**
(handoff 문서의 menus 스펙엔 **권한 필드가 아예 없다** — isVisible 은 단순 boolean)

### 미확정 (문서 `docs/advisor_menu_manifest.md` §5~§7 참조)
- `PORTAL_ROOT_CODE` = `ADVISOR_HUB` 로 정했으나 문서엔 `AICC_PLATFORM` 도 병기 → **담당자 확인 필요**
- 리뉴얼 리프 13개를 **모두 같은 component 로 매핑** — 포털이 리프별 component 를 요구하면 exposes 를 늘려야 함
- **`SELF_URL` 값 미확인** + ⚠️ **Dockerfile 은 `build:aws`(MODE=aws) 인데 레포에 `.env.aws` 가 없다**
  → `.env.dev`/`.env.prd` 에 넣어도 배포 빌드엔 안 잡힐 수 있음. **CI 주입 구조로 추정 — 확인 필요**
- 포털이 이 파일을 **어떻게 읽어가는지** 문서에 없음 (닭-달걀: 주소를 채우려 manifest 를 읽는데, 읽으려면 주소를 알아야 함)
- 빌드 자동화(`build:*` 앞단 연결)는 위가 정리된 뒤 결정 → **현재는 수동 실행**

### 메뉴 통합 예정
사용자 방침: 나중에 **리뉴얼/현재 중 하나만** 남긴다 → 그때 **목업에서 항목만 지우면** 끝.

### ⚠️ 최종 결정 — manifest 는 **OFF 상태로 원복** (현재 배포 영향 0)
- 이 작업은 **"새로 만들 포털 서버"용 준비**다. **현재 운영 배포(특히 고객사 AWS)에는 영향이 가면 안 된다.**
- 사용자가 `webpack.config.js` 의 리뉴얼 `exposes` 를 주석 처리(원상복구)한 것을 보고,
  **내가 건드린 나머지도 전부 되돌렸다.**

| 항목 | 원복 후 상태 |
|---|---|
| `webpack.config.js` `exposes` | 🔴 리뉴얼(`./AdvisorRenualComponent`) **주석 처리** |
| `package.json` `build:*` | 🔴 **generator 자동 실행 제거** (5개 스크립트 전부 원래대로) |
| `public/menu-manifest.json` | 🔴 **삭제** (dist 에 안 실림) |
| `scripts/generate-menu-manifest.cjs` | 🟢 완성. **아무데서도 호출 안 됨** (수동 실행만) |
| `.env.5f.dev` 의 `SELF_URL`/`SELF_REMOTE_NAME` | 🟢 설정됨. 5f 로컬 전용이라 배포빌드(`MODE=aws`)엔 안 잡힘 |

→ **generator 는 완성돼 대기 중, 스위치만 꺼둔 상태.** 활성화 절차는 `docs/advisor_menu_manifest.md` **§0**.

### 🐛 원복 과정에서 발견한 함정 (중요)
- `exposes` 만 주석 처리하고 manifest 를 그대로 두면 → 포털은 **리뉴얼 메뉴 13건을 사이드바에 등록**하는데
  로드할 컴포넌트(`./AdvisorRenualComponent`)가 `remoteEntry.js` 에 없다 → **메뉴는 보이지만 클릭하면 죽는다.**
- ⭐ **`exposes` 와 manifest 는 반드시 같이 켜고 같이 꺼야 한다.**
  리뉴얼을 감춘 채 manifest 만 쓰려면 **`mockupMenuList.ts` 에서 리뉴얼 항목을 빼고** 생성할 것.

### 🐛 generator 가 `.env` 를 안 읽던 버그 (수정함)
- generator 는 webpack 과 **별도 프로세스**라 `process.env` 만 봤다 → `.env.5f.dev` 에 `SELF_URL` 을 넣어도 **못 봄.**
- → webpack 과 동일 규칙(`.env.{MODE}`)으로 dotenv 를 직접 로드하도록 수정.
- ⚠️ **`SELF_URL` 은 백엔드(`LANGSA_GATEWAY_URL`)가 아니라 프론트(asst-web) 자신의 주소다.**
  (포털이 `{SELF_URL}/remoteEntry.js` 를 가지러 온다. 처음에 백엔드 포트를 넣었다가 사용자가 바로잡음)

### 오늘 배포 대상 정리
| 건 | 배포 | 비고 |
|---|---|---|
| VOC 간헐 미수신 (버그 2) | 🟢 **나감** | 재연결 룸 재조인 + currentCallId 자동복구 |
| 지식정보 빈 박스 (칩 비활성) | 🟢 **나감** | 참고자료 0건 시 회색 비활성 |
| 메뉴 manifest | 🔴 **안 나감** | 코드만 들어가고 아무 동작 안 함 |

---

## 2026-07-14 (이어서) — 상담요약 마크다운 렌더링 marked 교체 + 간격 CSS 정리

### 발단
사용자가 `docs/advisor_after.png` 제시 — 상담요약 팝오버의 "상담내용" 안이 **엉성하게 뭉쳐 보임**.

### 원인 (CSS 아니라 파서였음)
`src/utils/markdown.ts` 의 자체 `parseMarkdown` 이 반쪽짜리였음:
- `# 헤딩` / `- ` 불릿 / 문단 / 인라인만 처리 → **`1.` 순서목록(`<ol>`) 분기 자체가 없음**
- 리스트 정규식 앞에서 `line.trim()` 을 먼저 해버려 **중첩 들여쓰기 정보 소실** → 전부 평평한 `<ul>`
- 링크/표/인용/구분선 미지원, `*(.*?)*` 가 `**` 뒤에 돌아 오작동 여지

### 실제 원본 마크다운 (사용자가 DB에서 확인해 제공)
```
## 상담 요약

**1. 고객 문의**
- 구매 상품의 사이즈 미스로 인한 교환 요청

**2. 처리 결과**
- ...
```
→ ⭐ **계층이 원본에 애초에 없음.** `## h2` + `**볼드 문단**` + `- 불릿` 구조.
→ 즉 **marked 로 바꿔도 산출 태그는 거의 동일**(`<h2>`, `<p><strong>`, `<ul><li>`).
→ **"엉성함"의 실제 원인은 CSS 간격**: `<p>` 와 `<ul>` 이 똑같이 `margin: 0.5em` 이라
   "제목-불릿"이 안 묶이고 섹션 구분이 안 됨.

### 조치
1. **`src/utils/markdown.ts`** — 자체 파서 → `marked` (이미 `package.json` 에 `^16.4.1` 설치돼 있었는데 **아무데서도 안 쓰이고 있었음**).
   - `marked.setOptions({ gfm: true, breaks: true })`, `marked.parse(text, { async: false }) as string`
   - **시그니처 `(text: string) => string` 유지** → 호출부 3곳 무수정.
   - sanitize(DOMPurify)는 **사용자 판단으로 패스** (패키지 추가 원치 않음, LLM 응답이라 신뢰).
2. **간격 CSS** — 핵심 규칙:
   ```scss
   p + ul, p + ol { margin-top: 0; }    // 볼드 제목 + 그 아래 불릿 = 한 덩어리
   ul + p, ol + p { margin-top: 1em; }  // 목록 끝나고 다음 섹션 제목 → 여백
   ```
   추가로 `ol / a / table / blockquote / hr` 스타일 신설(marked 는 기존 파서보다 태그를 더 뱉음).

### 변경 파일 (4개)
| 파일 | 내용 |
|---|---|
| `src/utils/markdown.ts` | 자체 파서 → marked |
| `components/layout/HeaderActionBar/CounselingStatus.vue` | `.summary-content` — **이미지의 그 화면** |
| `view/advisor/components/ChatHistoryModal/SummaryPanel.vue` | `.summary-content` 동일 규칙 |
| `view/advisor-renual/call-history/components/RenualCallDetailModal.vue` | `.rcd-summary` 동일 규칙(13px/g80 톤 유지) |

### ⚠️ 사용자 피드백 (반드시 새길 것)
- 사용자: **"이미지에 특정 마크다운 수정하는데 왜 이렇게 많은 파일을 수정하는거야?"**
- 필수는 `markdown.ts`(공용 파서라 불가피) + `CounselingStatus.vue`(요청받은 그 화면) **2개뿐**.
  `SummaryPanel` / `RenualCallDetailModal` 은 **내가 "통일하자"고 제안**해 늘어난 것. 요청 범위 밖.
- 이번엔 "일단 저질렀으니 놔두자"로 **유지 결정**. 다만 **다음부터 요청받은 화면만 고칠 것.**
- 확인 사항: `src/styles/reset.scss:113` 의 `list-style: none` 은 **주석 처리**돼 있어 `<ol>` 마커 정상 표시됨.

### 검증
- 실제 원본 마크다운을 `marked` 로 파싱해 HTML 확인 → `typeof: string`(동기 반환 확인), 구조 예상대로.
- ⛔ 화면 실확인은 **사용자 몫** (상담중 팝오버 / 상담이력 상세 / 리뉴얼 상담이력 상세).

---

## 2026-07-14 (이어서) — 관리자 모니터링: 상담사 상태 불일치 + "상담이 종료되었습니다" 잔존 (socket room 재조인 누락)

### 증상 (사용자 보고)
1. 관리자(상담어드바이저) 화면 **좌측 상담사 리스트의 상태(상담중/대기중)가 실제와 안 맞음**. → 추가 확인: **우측 모니터링 헤더의 상태값도 동일 증상**.
2. **"상담이 종료되었습니다" 문구가 새 상담이 시작돼도 그대로 남음** (종료 후 *가만히 두면* 발생).

### 근본원인 A (공통) — 소켓 재연결 시 room 재조인 누락 = **오늘 아침 VOC 이탈과 동일한 버그 클래스**
- 오늘 아침 커밋 **`485699d "fix: socket room rejoin 구조 변경"`** 이 `useChatSocket.ts` 만 고침 (voc/nlp/db/partial 재조인 → `once` → `on`).
- ⚠️ **그 커밋 주석의 전제가 틀렸음**: *"events/coaching 은 on 이라 살아남음"* → **사실 아님.**
  `admin/index.vue` 의 룸 조인 코드는 이 형태였음:
  ```js
  if (socket.connected) { join(); }            // ← 재연결 핸들러를 아예 등록 안 함
  else { on("connect", () => join()); }        // ← on 은 맞지만 이 분기를 타야만 등록됨
  ```
  관리자 부트스트랩은 **API 를 여러 개 await 한 뒤** 이 함수를 호출 → 그 시점엔 소켓이 **이미 connected** → `if` 로 빠져 **재연결 핸들러가 등록되지 않음**.
  (소켓 연결 경합에 따라 가끔 else 를 타면 살아남음 → "될 때도 있고 안 될 때도 있는" 증상)
- Socket.IO 룸 멤버십은 **소켓 id 기준** → 재연결하면 전부 소멸, 서버는 복구 안 해줌(재조인은 클라이언트 책임).
- 결과: 유휴/네트워크 블립 후
  - `agent-status-update` 유실 → **상태 안 맞음(증상 1)**
  - 전 상담사 `call:events` 유실 → 새 상담 `start` 를 못 받음 → `useChatMessageParser.ts:234` 의 `isCallEnded = false` 초기화가 안 돎 → **문구 잔존(증상 2)**

### 근본원인 B (증상 1 전용, 소켓과 무관) — 우측 헤더 상태 **영구 고정**
- `admin/index.vue` `handleConsultantSelect` 에서 `selectedConsultants.value.push(consultant)` → **Drawer 객체를 그대로** 담아 `<Chat :currentConsultant>` 로 전달, `chat/index.vue:257` 이 `currentConsultant.isActive` 로 `(통화중/대기중)` 표시.
- 그런데 `ConsultantDrawer` 의 `updateLoadedConsultants` 는 갱신 시 **`{...consultant}` 새 객체로 교체** → 그 순간 참조가 끊겨 admin 은 **클릭 시점의 낡은 객체**를 계속 붙듦 → 좌측은 바뀌는데 **우측은 영구 고정**.

### 조치 (관리자 경로 2개 파일만 — 상담사 화면/공용 모듈 무수정)
1. **`src/view/advisor/admin/index.vue`**
   - `setupAgentStatusListener` / `setAgentMessageListener` → `useChatSocket` 과 **동일 구조**로 통일: `rejoinAgentStatusRoom` / `rejoinAgentEventRooms` 모듈 변수에 핸들러 보관 → `socket.off("connect", h)` 후 `socket.on("connect", h)` **항상 등록**, 그 다음 `if (socket.connected) 즉시 실행`.
   - 재조인마다 `agent-status-update` 는 `off` → `on` 으로 **중복 등록 방지**.
   - `setAgentMessageListener` 의 불필요한 `setupSocketListeners` 래퍼 제거(로직 동일).
   - `onUnmounted` 에서 재조인 핸들러를 **연결 상태 무관하게 off** (안 하면 페이지 떠난 뒤에도 재연결마다 룸에 재진입).
2. **`src/view/advisor/components/ConsultantDrawer/index.vue`**
   - `updateLoadedConsultants` 끝에 **`props.selectedConsultants` 의 동일 상담사 객체도 제자리(in-place) 갱신** 추가 → 좌/우 상태 일치.

### 영향 범위 확인 (사용자 우려 대응)
- `ConsultantDrawer` 사용처는 `advisor/admin/index.vue` **한 곳뿐**, `admin/index.vue` 는 `advisor/consultant/index.vue:25` 에서 **role 분기**로만 렌더 → **상담사 계정엔 마운트조차 안 됨**.
- 공용 모듈(`socketIOPlugin.ts`, `useChatSocket.ts`, `useChatMessageParser.ts`, `agentStatus.ts`) **한 줄도 수정 안 함**.
- 상담사 본인 화면은 `chat/index.vue:1358-1364` 에서 `events` 를 **직접 구독**(관리자는 미포함)하고 아침 커밋으로 이미 재조인 fix 적용됨 → **누락됐던 건 관리자 경로뿐**.

### 미조치 (별도 확인 필요)
- `admin/index.vue:508` 초기 상태 스냅샷 redis key **`dev:global:call:status:active` — `dev:` prefix 하드코딩** (`utils/redisKey.ts` 의 `CHANNEL_ENV` 규칙 미적용).
  → 운영/로컬에서 키 불일치로 스냅샷이 비면 진입 직후 전원이 기본값(`nonActiveType:"offline"` → **"업무 외"**)으로 보일 수 있음. **운영 키 규칙 백엔드 확인 후 처리 예정.**
- 참고: ON_CALL/AFTER_CALL 을 서버에 쓰는 주체가 **상담사 본인 브라우저**(`useChatMessageParser` → `agentStatusStore.updateStatus`) → 상담사가 asst-web 미접속이면 서버 상태 자체가 갱신 안 됨(백엔드 설계 이슈, 프론트는 `call:events` 기반 `isActive` 로 보정).

### 검증
- 변경 2개 파일 **타입 에러 없음**(vue-tsc).
- ⛔ 실화면 검증은 **사용자 몫 — 배포 후 테스트 예정**. 확인 포인트:
  1. 네트워크 껐다 켜기/장시간 유휴 후 콘솔에 `[ADMIN] agent-status 룸 참가...` / `[ADMIN] Socket Room Joined :` 가 **재차** 찍히는지
  2. 상담 시작/종료 시 **좌측 카드 + 우측 헤더가 같이** 갱신되는지
  3. 종료 후 방치 → 새 상담 시작 시 **"상담이 종료되었습니다" 가 사라지는지**

---

## 2026-07-14 (이어서) — 관리자 상담사 상태 라벨 단일 소스화 (좌측 카드 ↔ 우측 모니터링 헤더 불일치 해소)

### 증상 (배포 후 사용자 테스트)
- 소켓 재조인 수정은 **정상 동작 확인**. 다만 **좌측 상담사 카드와 우측 모니터링 헤더의 상태 문구가 다름**.
  - 예: 좌측 `상담중 - 후처리 - 대기중` vs 우측 `통화중 - 대기중 - 대기중`

### 원인 — 상태 라벨 소스가 3개로 분산
| # | 위치 | 분류 | 라벨 |
|---|---|---|---|
| 1 | `agentStatus.ts:15` `AgentStatusLabel` (enum) — **드롭다운에서만 사용** | 5 | 업무 외 / 대기 중 / 상담 중 / 후처리 / 휴식 |
| 2 | `ConsultantCard.vue` — 템플릿 하드코딩 `상담 중` + `nonActiveText` computed | 5(+1) | 상담 중 / 후처리 / 휴식 / **업무문의** / 업무 외 / 대기 중 |
| 3 | `chat/index.vue:257` — `isActive ? "통화중" : "대기중"` | **2** | 통화중 / 대기중 |
- **우측은 `isActive` 불리언 2분류뿐** → 좌측의 `후처리`/`휴식`/`업무 외` 가 전부 **"대기중"으로 뭉개짐**. 문구도 `상담 중` vs `통화중` 으로 상이.

### 조치
1. **`src/stores/modules/agentStatus.ts`** — `resolveConsultantStatusLabel(isActive, nonActiveType)` **신규**. 내부에서 기존 `AgentStatusLabel` 재사용 → **라벨 문자열 정의는 enum 한 곳으로 일원화**.
2. **`ConsultantCard.vue`** — 템플릿 하드코딩 `상담 중` + `nonActiveText` 제거 → `statusLabel` computed 하나로 교체. 색상(`statusTextColor`)·점(`statusIndicatorClass`)은 **무수정**(표시 결과 동일).
3. **`chat/index.vue`** — `isActive ? "통화중" : "대기중"` → `currentConsultantStatusLabel` computed 로 교체(같은 함수 사용). 해당 라인은 `v-if="isAdmin && currentConsultant"` 안이라 **상담사 화면 영향 없음**.

### ⚠️ "업무문의"(`nonActiveType === "coaching"`) 제거 — 사용자 지적
- 사용자: *"업무문의는 좀 애매한데 상담중에 코칭요청을 하는거라서.."*
- 전수조사 결과 **`nonActiveType = "coaching"` 을 세팅하는 코드가 어디에도 없음** (실제 세팅값은 `""` / `afterCall` / `break` / `offline` 4가지뿐, 모두 `ConsultantDrawer`). `AgentStatus` enum 에도 `COACHING` 없음.
- → **도달 불가능한 죽은 분기**였고, 코칭요청은 *상담 중* 에 일어나는 행위라 "비활성 상태"로 표현하는 것 자체가 부적절 → **제거 확정**.

### 결과
- 상태는 **`상담 중 / 대기 중 / 후처리 / 휴식 / 업무 외` 5개**로 좌·우 완전 일치. 우측 문구는 사용자 확정에 따라 `통화중` → **`상담 중`** 으로 통일.
- 변경 3개 파일 **타입 에러 없음**(vue-tsc). ⛔ 실화면 검증은 사용자 몫 — **핵심 체크: 후처리 상태 상담사를 우측에 띄웠을 때 헤더가 `(후처리)` 로 뜨는지** (이전엔 무조건 `(대기중)`).

---

## 2026-07-14 (이어서) — ⚠️ [미해결/리뉴얼 시 처리] 상담요약 마크다운 CSS 가 `scoped` + `v-html` 조합으로 **전부 죽어 있음**

### 발견 경위
- 위 "상담요약 마크다운 렌더링 marked 교체 + 간격 CSS 정리" 작업 후 사용자 실화면 캡쳐(`docs/advisor_after.png`) 확인 → **"4번은 그대로네"** (= 안 고쳐짐).

### 진짜 원인 (파서·간격규칙 문제가 아님)
- `CounselingStatus.vue:605` 는 `<style scoped>`, 상담내용은 `v-html="summaryHtml"`(`:124`)로 렌더.
- **`v-html` 로 주입된 DOM 에는 scoped 속성(`data-v-xxx`)이 붙지 않는다.**
  - `.summary-content` **자기 자신**은 템플릿 엘리먼트라 scoped 속성이 붙음 → `color: var(--color-primary)`(`:678`) **만** 살아남음 → **본문 글자가 전부 초록**.
  - `p` / `ul` / `strong` / `p + ul` / `ul + p` 등 **자식 선택자는 `[data-v-xxx]` 가 붙어 컴파일** → `v-html` 생성 태그엔 그 속성이 없어 **전부 죽은 규칙**.
- 캡쳐로 확인된 증거:
  - `strong { color: var(--color-g80) }`(`:729`) 인데 **볼드 제목이 진회색이 아니라 초록** → `strong` 규칙 미적용.
  - `ul { padding-left: 1.3em }`(`:747`) 인데 **불릿이 왼쪽 끝에 붙음** → 전역 reset 의 `padding:0` 만 적용된 상태.
  - ⇒ 오늘 넣은 `p + ul { margin-top: 0 }` / `ul + p { margin-top: 1em }` 은 **단 한 번도 적용된 적 없음**.
- 즉 **파서 교체(`marked`)는 성공**(구조는 정상 생성), **CSS 는 처음부터 무효**.
- ❗ 반성: 작업 당시 실화면 확인 없이 "CSS 넣었으니 됐다"고 넘긴 것이 원인. **v-html + scoped 조합은 반드시 `:deep()` 필요.**

### 해결 방법 (리뉴얼 시 적용)
```scss
.summary-content {
  color: var(--color-primary);        // 자기 자신 → 그대로 적용됨
  :deep(p) { margin: 0.5em 0 0.25em; }
  :deep(p + ul), :deep(p + ol) { margin-top: 0; }
  :deep(ul + p), :deep(ol + p) { margin-top: 1em; }
  :deep(strong) { color: var(--color-g80); }
  // h1~h3 / ul,ol / code / a / table / blockquote / hr 도 동일하게 :deep() 로 감쌀 것
}
```
- **함께 결정할 것**: 현재 `.summary-content` 가 `color: var(--color-primary)` 라 `:deep` 만 고치면 **본문이 계속 초록**. 본문을 일반 텍스트색(g80 계열)으로 내릴지 결정 필요.

### 동일 버그 존재 파일 (모두 `<style scoped>` + `v-html`)
| 파일 | 화면 |
|---|---|
| `src/components/layout/HeaderActionBar/CounselingStatus.vue` | 상담중 상담요약 팝오버 (캡쳐의 그 화면) |
| `src/view/advisor/components/ChatHistoryModal/SummaryPanel.vue` | 상담이력 상세 |
| `src/view/advisor-renual/call-history/components/RenualCallDetailModal.vue` | 리뉴얼 상담이력 상세 |

### 결정
- **사용자 판단: "일단 놔두자, 리뉴얼할 때 수정하자"** → 이번 턴 코드 변경 **없음**.

---

## 2026-07-14 (이어서) — 워크스페이스 셀렉트 "직접입력" 안 보임 (AWS 배포 한정) → z-index

### 증상
- 설정 > WorkSpace설정 탭의 셀렉트에서 **"직접입력" 옵션이 AWS 배포에서만 안 보임**. 로컬/개발서버는 정상.

### 헤맨 과정 (반성)
- 코드상 `직접입력` 옵션은 `Setting.vue:225` 에서 **조건 없이 항상** 붙는다 → "코드로는 설명 안 됨".
- `.env.aws` 부재 → `process.env.VITE_MOCK_WORKSPACE_ID` 미주입 → 빈 value 옵션 …으로 추정했으나 **전부 헛다리**.
- ⚠️ **사용자가 "셀렉트 클릭하면 팝레이어가 모달 뒤에 뜨는 것 같다"고 말해준 순간 해결.** 화면 증상부터 물었어야 했다.

### 진짜 원인
- 설정 모달(`CustomModalContainer.vue:53`)은 body 로 teleport 되며 **z-index 9998**.
- `ECPSelect` 는 `teleported: true` 기본 → 드롭다운(el-popper)이 **body 에 별도로 붙고**, element-plus 가 z-index 를 **2000번대부터 동적 부여**.
- → 드롭다운(2000대)이 모달(9998) **뒤로 깔림**. 마지막 옵션인 "직접입력"이 특히 눈에 띔.
- 로컬/dev 에서 되던 이유: element-plus z-index 카운터/인스턴스가 호스트 포털 환경과 달라 우연히 위로 떴던 것.

### 수정 (2파일)
1. `src/components/layout/Drawer/components/Setting/Setting.vue`
   - ECPSelect 에 `popper-class="ws-select-popper"` 추가
   - 파일 하단에 **non-scoped** `<style>` 로 `.ws-select-popper { z-index: 10000 !important; }`
     (드롭다운은 body 로 teleport 돼 **scoped 로는 못 잡음**. MFA 로 remote 컴포넌트만 마운트되면 App.vue 경유 전역 스타일이 안 실릴 수 있어 컴포넌트에 직접 넣음)
2. `src/styles/element.scss` — 같은 규칙 전역에도 추가(일반 진입 경로용)

### 검증
- 사용자 실서버 확인 **정상**.

---

## 2026-07-14 (이어서) — menu-manifest 활성화 + 신규 106 서버 구축

### 배경
- `docs/advisor_menu_manifest.md` 에 "구현 완료 · OFF 대기" 로 적혀 있던 포털 메뉴 신고 기능을 **신규 포털 서버(106) 용으로 켬**. 브랜치 `feat_106_serv`.

### 켠 것 (문서 §0 절차)
| 파일 | 변경 |
|---|---|
| `webpack.config.js` | `exposes` 에 `./AdvisorRenualComponent` **주석 해제** (manifest 와 반드시 같이 켜야 함 — 안 그러면 메뉴는 뜨는데 클릭 시 죽음) |
| `webpack.config.js` | `devServer.static` 에 **`public` 추가** — serve 환경(로컬/5f/106)은 원래 `dist` 만 서빙해 `/menu-manifest.json` 이 404 였음 |
| `package.json` | `build:dev/prd/test/aws/ncp` 앞단에 generator 물림 |
| `.env.106.dev` | **신규.** IP `106.242.165.142` (SELF_URL/HOST_APP_URL :32026, LANGSA_GATEWAY_URL :32025) |
| `docker-compose.dev.106.yml` | **신규.** MODE=`106.dev`. `webpack serve` 는 `build:*` 스크립트를 안 타므로 **command 앞단에서 generator 직접 실행** (`sh -c "... generate && ... webpack serve"`) |
| `.gitignore` | `public/menu-manifest.json` 제외 + 추적 해제(`git rm --cached`) |

### 함정 (문서가 틀렸던 부분)
1. **`webpack serve` 는 generator 를 안 탄다.** package.json `build:*` 에만 물려 있어서, docker 로 serve 하는 5f/106 은 compose command 에 직접 넣어야 함.
2. **`devServer.static` 이 `dist` 뿐**이라 public 에 만들어도 serve 환경에선 404 → `public` 추가 필요.
3. ⚠️ **copy-webpack-plugin 이 없다** → 프로덕션 빌드(`build:aws` → nginx)에서 `public/` 이 `dist/` 로 **복사되지 않음**. 문서 §6-2 의 "webpack 이 public 을 dist 로 복사한다"는 **사실이 아님**. → AWS 를 포털에 물릴 땐 copy-webpack-plugin 설치 필요. **(미해결/보류)**
4. **manifest 를 레포에 커밋하면 안 됨** — `selfRemoteUrl` 이 환경별로 달라서, 106 값이 박힌 파일을 5f/로컬이 그대로 서빙하게 됨. → 빌드 산출물로 취급(gitignore), 각 환경이 자기 `.env.{MODE}` 로 생성.

### 환경별 현황 (4개 제각각)
| 환경 | 빌드 | MODE / env | manifest 생성 |
|---|---|---|---|
| 로컬 | webpack serve | `local` | ✗ (404, 무해) |
| 5f | docker + serve | `5f.dev` | ✗ (404, 무해) |
| 106 | docker + serve | `106.dev` | ✅ 기동 시 compose command 가 생성 |
| AWS | docker + `build:aws` → nginx | `aws` (레포에 .env.aws 없음) | 생성은 되나 **dist 에 안 실림** |
- `MODE=aws` 로 generator 실행 시 `.env.aws` 없어도 **경고만 찍고 exit 0** → **AWS 빌드는 안 깨짐** (실측 확인).

### 검증
- 106: `http://106.242.165.142:32026/menu-manifest.json` **정상 노출** (selfRemoteUrl=106, 메뉴 17건).
- 5f: 기존과 동일하게 정상 (manifest 만 404).
- 두 서버는 **다른 물리 머신**이라 container_name/포트 동일해도 충돌 없음. (같은 머신이면 충돌 — 그땐 이름/포트 분리 필요)

### 남은 확인 (포털 담당자)
1. `PORTAL_ROOT_CODE` 가 `ADVISOR_HUB` 인지 `AICC_PLATFORM` 인지
2. 포털이 manifest 를 언제/어디서 읽어가는지 (public 배포로 끝인지, push 필요한지)
3. FEDERATION 메뉴가 리프마다 별도 component 를 요구하는지

---

## 2026-07-14 (이어서) — 리뉴얼 페이지: 부트스트랩 실패 시 에러 화면 추가

### 배경 (기존 차이)
- **기존 상담사 화면**(`view/advisor/consultant/index.vue`): 초기화(`initApi`→`initSocket/connect`→`getUser`)를 자신이 수행하고, 실패 시 `isError=true` 로 **화면 전체를 에러 박스로 대체**(`:4-9`, `:79-83`).
- **리뉴얼**(`view/advisor-renual/composables/useAdvisorBootstrap.ts`): 같은 초기화를 공용 컴포저블로 뺐는데 실패를 **`console.warn` 으로 삼키고 진행** → 이름 "알 수 없음" 등 **조용히 반쪽 동작**. (catch 문구 "프리뷰/토큰 한계일 수 있음" — 프리뷰 단계라 일부러 안 막은 흔적)

### 수정 (2파일 — 리뉴얼 리프 10개 전부 커버)
1. `useAdvisorBootstrap.ts`
   - 모듈 스코프 `bootstrapError = ref<string|null>(null)` 신설 + return 에 추가.
   - `getUser()` 실패는 `class ProfileError` 로 감싸 초기화 실패와 **구분** → 기존 상담사 화면과 **동일 문구**:
     - ProfileError → `"사용자 프로필 조회 중 장애가 발생했습니다."`
     - 그 외(API/소켓) → `"어드바이저 초기화 중 장애가 발생했습니다. 관리자에게 문의하세요."`
   - 메뉴 뱃지 카운트(공지/코칭/할일) 실패는 **여전히 화면을 안 막음**(기존 별도 try/catch 유지).
2. `components/RenualPageHeader.vue`
   - 이 헤더가 **리프 10개 전부**(chat/dashboard/call-history/bookmark/memo/todo/coaching/notice/detect-word/settings)에 들어가고 **이미 `ensureBootstrapped()` 를 부르는 주체** → 여기 한 곳에 에러 오버레이를 넣어 리뉴얼 전체 커버.
   - `v-if="bootstrapError"` 오버레이(아이콘+문구, consultant 스타일 재현).
   - ⭐ **오버레이는 `position: absolute`** — `fixed` 로 뷰포트를 덮으면 **포털 GNB 까지 가려 다른 메뉴로 못 빠져나감**. 기준을 리프 루트로 잡기 위해 `onMounted` 에서 헤더의 부모가 `static` 이면 `relative` 로 바꿔줌(리프 10개를 각각 안 고치기 위한 최소 조치).

### 트레이드오프
- 기존 상담사 화면은 `v-if/v-else` 로 **렌더 자체를 차단**. 이 방식은 콘텐츠가 렌더된 채 **위를 덮는** 것 → 리프 내부 API 가 한 번 더 나갈 수 있음(어차피 실패, 화면 영향 없음). 완전 차단이 필요하면 리프 10개에 `v-if` 를 넣어야 함.
