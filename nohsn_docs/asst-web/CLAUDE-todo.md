# 미적용 작업 (TODO)

> 완료되면 해당 항목 삭제. 전부 비면 이 파일도 삭제 가능.

## 2026-06-23 등록

### 1. 설정 토글 실제 연동 — "코칭 알림" / "지식 자동 검색"
**배경:** 두 설정 모두 UI 토글 → 서버 저장(`Setting.vue` → `ConfigAPI.upsertConfig`)까지는 되는데, 실제 기능 동작 시점에 설정값을 안 봐서 **현재는 죽은 설정**임. 토글을 꺼도 동작이 그대로 일어남.

**할 일:** 아래 두 군데에 가드 추가.

1. **코칭 알림** (`coachingAlarm`)
   - 위치: `src/view/advisor/admin/index.vue:401~455` (`onReceivedCoachingRequestMessage`, `onReceivedCoachingMessage`)
   - 동작: 소켓 이벤트(`coaching_request`, `coaching`) 수신 → `showCustomMessage()` 토스트
   - 수정: `showCustomMessage()` 호출 전에 `getSettingValue("코칭 알림")` 체크 → false면 알림 skip

2. **지식 자동 검색** (`autoIntentSearch`)
   - 위치: `src/view/advisor/components/chat/composables/useChatMessageParser.ts:562~573` (`isFinalEnding` 시 `triggerAssist()` 호출 → `/assist-stream`)
   - 참고: 설정값 읽는 `isAutoSearch` computed 가 `chat/index.vue:973` 에 정의돼 있으나 **아무 데서도 참조 안 됨**(죽은 computed)
   - 수정: `triggerAssist()` 호출 전에 `isAutoSearch`(= `getSettingValue("지식 자동 검색")`) 체크 → false면 호출 skip

## 2026-06-29 등록

### 2. 코칭 — "접속 중인 관리자" 목록 필터 (백엔드 presence 의존)
**배경:** 상담사 코칭요청 시 "관리자 선택" 드롭다운이 `/get_managers`(조직 명단)만 써서 **로그인 안 한 관리자도 노출**됨. 접속여부 필터하려면 백엔드 presence 필요. 문의 초안: `docs/advisor-coaching-online-managers-inquiry.md`.

**백엔드 Q&A 확정 사실 (presence 키 설계 근거):**
- ⭐ **코칭 `sender_key` / `receiver_key` / 룸키 = 전부 `Agent.id`** (asst-service 에이전트 엔티티 자체 `id`, string). `common/interface/user.ts:25~26`.
  - **`ecp_account_id`(=1462) 아님, `ecp_account`("minuee") 아님, `cc_cti_id` 아님, `agent_id` 아님.** 전부 별도 필드로 공존.
  - 출처: sender_key=`/get_user`→`agent.id`, receiver_key=`/get_managers`→`managers[].id`, 룸키=`coaching_${agent.id}`.
- ⚠️ **식별자 공간이 2개**: 상담사 상태(agent-status)는 `cc_cti_id`로 매칭(`ConsultantDrawer/index.vue:231`), **코칭은 `Agent.id`로 매칭**. → 관리자 presence는 반드시 **`Agent.id` 기준**으로 만들어야 코칭과 맞음.
- 소켓 handshake: 현재 **익명**(`socketIOPlugin.ts:21`, auth/query 없음). `io(url,{auth})` 추가 가능하나 **connect()가 getUser()보다 먼저**(`consultant/index.vue:54~56`) 실행돼 핸드셰이크 시점엔 `Agent.id`가 아직 없음 → 택1: (a)핸드셰이크엔 ecp accountId 싣고 백엔드가 `ecp_account_id↔Agent.id` 매핑, (b)프론트가 getUser를 connect 앞으로 당겨 Agent.id 직접 전달(순서변경 리스크).

**할 일(백엔드 회신 후):** `/get_managers` 응답에 `is_online`(또는 last_seen) 추가되면 → `CoachingRequest.vue`의 `coachingRequestAdvisorOptions` computed에 필터/정렬 + (오프라인) 라벨 한 곳 추가.

**UX 결정 필요:** 오프라인 관리자 숨김 vs 표시만(권장: 표시만 — 밀린 요청 메시지함 동작 유지). 밀린 코칭은 관리자 페이지 진입 즉시 `refreshCoachings(true)`로 자동조회됨(모니터링 시작과 무관).

### 3. RAG 원본보기 하이라이트(책갈피) 재설계 — 검증/원복 대기
**상태:** 코드 적용 완료, **배포 후 라이브 검증 중** (사용자). 문제 시 원복 가능하도록 기록.

**배경/원인:** 출처 원본보기 하이라이트가 "content 첫 줄"을 단락에 `includes` 매칭 → 표 문서는 백엔드 content가 마크다운 표(`| ... |`)인데 렌더 DOCX는 `<td>`라 매칭 실패. `source_location`(heading_path/page_number)을 안 씀. (상세: CLAUDE-history.md 2026-06-29 "RAG 원본보기 하이라이트" 항목)

**적용한 변경 (6파일) — 핵심:**
- DOCX: `heading_path` 마지막값으로 제목 요소 찾아 하이라이트(`focusByHeadingPath`), 실패 시 content 텍스트 폴백(+마크다운 정제 `stripMarkdown`).
- PDF: `source_location.page_number`로 페이지 점프, 실패 시 텍스트 폴백.
- `source_location`을 뷰어까지 배선(prop `sourceLocation`).

**변경 파일:**
1. `src/api/types/assist-stream.type.ts` — `SourceLocation` 타입 신설 + `SourceItem.source_location` 교체
2. `src/view/advisor/components/knowledge/DocOriginalViewerModal.vue` — prop `sourceLocation`, `parseSourceLocation`/`stripMarkdown`/`focusByHeadingPath` 신설, focusActiveContent·focusActivePdfPage 재작성, activeContent watch에 sourceLocation 추가
3. `src/view/advisor/components/knowledge/composables/useKnowledgeModals.ts` — `originalViewerSourceLocation` ref + openOriginalViewer 3번째 인자/return
4. `src/view/advisor/components/knowledge/index.vue` — destructure + `:source-location` 바인딩
5. `src/view/advisor/components/knowledge/TabTypeKnowledgeIndex.vue` — ref/3번째 인자/`:source-location` 바인딩
6. `src/view/advisor/components/knowledge/DocumentDetailView.vue` — inject 시그니처 3번째 인자 + handleOpenModal에서 `props.document.source_location` 전달

**원복 방법:**
- (간단) git: 위 6파일을 직전 커밋 상태로 되돌림 (`git checkout -- <파일>`은 사용자 몫).
- (수동 최소복원) 동작만 원복하려면 `DocOriginalViewerModal.vue`에서 `focusActiveContent`가 heading_path 분기 없이 기존 `normalizeText + includes`만 쓰도록, `focusActivePdfPage`가 page_number 분기 없이 텍스트매칭만 쓰도록 되돌리면 됨(나머지 prop 배선은 무해하게 남겨둬도 됨).

**회귀 안전장치:** heading_path/page_number 없으면 기존 content 텍스트매칭으로 폴백하므로, 일반(비표) 문서는 기존과 동일 동작이어야 함. 검증 시 ①표 문서(예: 하나코리아 환매수수료) 제목 클릭→"9. 환매수수료" 위치로 가는지 ②일반 문서가 예전처럼 되는지 둘 다 확인.

**검증 결과 따라:** 정상이면 이 항목 삭제, 문제면 위 "원복 방법" 적용.

## 2026-06-30 등록

### 4. RAG 원본보기 — highlightable 연동 + docx 마크다운 렌더(V2) [검증 완료]
- **요약:** 출처 `highlightable=false`면 매칭 스킵+안내배너(7파일). docx 원본보기를 `get_doc` 마크다운→toast-ui Viewer로 렌더하는 **새 모달 `DocOriginalViewerModalV2.vue`** 신설(이쁨+하이라이트 유지, 백엔드 의존 0). 상세는 CLAUDE-history.md 2026-06-30.
- **원복:** `index.vue`/`TabTypeKnowledgeIndex.vue` import를 `DocOriginalViewerModalV2`→`DocOriginalViewerModal`로 되돌리면 기존 mammoth 동작(기존 파일 그대로 보존됨).

### 5. 문서 노출 순서 — "AI 요약 문서" 상단 핀 [백엔드 필드 대기]
- **요구:** 출처 문서 노출을 ref_num 순이 아니라 **"AI 요약에 해당하는 문서(1개~여러개)를 맨 위로 핀 + 나머지 ref_num 순"**. assist-stream(실시간 Top3) / stream(수동검색) **둘 다**. → isMain/Top3/오른쪽 패널/이력 자동 반영.
- **막힌 점:** 그 "요약 문서" 식별 필드가 **미확정**(hit_num 아님). `distilled.selected_refs`는 distill 스킵 시 안 와서(샘플 `stages.distill:0`) 의존 불가 → 별도 필드 필요.
- **확정되면:** `useChatAssist.ts`·`useKnowledgeSearch.ts`의 `e.sources.map` 직전에 핀 로직(`[요약소스들, ...나머지(ref_num순)]`) 추가 + `SourceItem`/`SourcesEvent` 타입에 필드 추가. (~10줄)
- **백엔드 확인:** 필드명 + 값 형태(ref_num 배열 vs document_id 배열) + 위치(이벤트 최상위).

## 2026-07-01 등록

### 6. 관리자 코칭 — "답변처리"(답변 없이 미답변 종료) 기능 [설계 확정, 방식 택1 대기]
**배경:** 관리자 코칭 모달의 **미답변 탭**은 `!isConfirmed`로 필터되는데, `isConfirmed`는 독립 플래그가 아니라 **"코칭 답변 레코드(coachings, coaching_request_id로 연결) 존재 여부"로 계산**됨(`AdminCoaching.vue` `processCoachingData` L358·L376). 그래서 "너무 늦어서/답변 불필요한 오래된 요청"을 **답변 없이 미답변에서 정리할 방법이 없음**. (미확인→확인완료 버튼은 `is_read`(읽음)만 바꿔서 미답변 갯수엔 영향 X — 읽음축/답변축이 별개)

**결정 사항:** 방안2(읽음 버튼과 **별도의 "답변처리" 버튼** 신설)로 진행. 방안1(확인완료=답변처리 통합)은 읽음/답변 2축이 뭉개져서 폐기.

**구현 방식 A/B 중 택1 필요 (사용자 결정 대기):**
- **A. 백엔드 없이 sentinel 코칭 생성** — "답변처리" 클릭 시 `createCoaching`(POST /coachings)에 content=`"관리자 확인 완료"` 같은 sentinel 보냄 → responseItem 생겨서 미답변에서 빠지고 재로그인해도 유지.
  - ⚠️ **부작용:** `createCoaching`은 receiver=**상담사**라 **상담사에게 실제 코칭으로 전송됨** — 상담사 코칭목록에 뜨고 미확인배지(`unReadCoachingCount`)+1, sentinel 문구도 상담사에게 노출. "전송 안 했으나 처리"라는 의도와 반대.
- **B. 백엔드 필드+API 1개 추가 (의도에 맞음, 권장)** — 상담사에게 안 뜨고 관리자 화면에서만 정리.
  - 백엔드 요청: ①`coaching_requests`에 상태필드 `is_answered`(bool, 또는 `answered_at`) 추가 — **`GET /coaching_requests/receiver/{id}` 목록 응답에도 포함**돼야 재로그인 후 유지됨. ②`PATCH /coaching_requests/{id}/answer` (이름 협의) → `is_answered=true`, 응답 200. `is_read`와 **별개 필드**로.
  - 프론트 변경: `answerCoachingRequest(id)` API + store `onAnswerCoachingRequest` + 카드에 "답변처리" 버튼(읽음 버튼과 별도) + `processCoachingData`의 `isConfirmed: !!responseItem || isRead(item.is_answered)`로 확장.

**UX 결정:** 답변처리된 항목 표시(예: 버튼 `답변처리`→`답변완료(비활성)`, 미답변 탭에서만 제거하고 전체콜 탭엔 유지).

**관련 파일:** `AdminCoaching.vue`(processCoachingData/handleConfirmed/탭), `AdminCoachingCard.vue`(버튼/핸들러), `coaching.ts`(store 액션), `coaching-request.api.ts`(API).

## 2026-07-02 등록

### 7. 세션 만료 칩 클릭 → 수동 토큰 재발급 [구현·실서버 검증 완료 후 원복, 재활용 대기]
**상태:** 실서버에서 **동작·검증 100% 성공** 확인 후 원복함(임시 테스트였기 때문). 아깝다는 판단으로 재활용 위해 기록. → 필요 시 아래 diff 그대로 다시 적용하면 됨. **(주의: 이 repo는 git 명령 사용 금지 — 원복/재적용 모두 파일 직접 편집으로 처리)**

**배경 — 현재 토큰 갱신 2경로(둘 다 유지, 이건 건드리지 않음):**
- **경로① 선제 재발급 타이머** `src/utils/tokenRefreshTimer.ts` — 어드바이저 접속 시 `startTokenRefreshTimer()` 1회. accessToken JWT `exp` 디코드 → 만료 3분 전(`LEAD_MS`) **setTimeout 1회 예약**(폴링 아님) → `auth/refresh` 직접 호출 → 새 토큰 sessionStorage 저장 → 새 토큰 기준 재예약. refreshToken 없으면(로컬) no-op. **발동 시 현재 토큰 exp 재검증 없이 무조건 refresh**.
- **경로② SSE `auth-expiry` 칩** — 서버가 만료 5분(`thresholdSec:300`) 이하 시 발화마다 이벤트 → `authExpiry.ts` store → `HeaderActionBar` 칩 노출. **안내 전용(클릭·자동 refresh 없음)**.

**추가했던 기능(=재활용 대상):** 세션 칩을 **클릭하면 경로①과 동일 경로로 즉시 수동 재발급**. 성공 시 칩 제거 + 토스트.

**정확한 diff (재적용용):**
1. `src/utils/tokenRefreshTimer.ts`
   - `doRefreshAndReschedule`를 `Promise<boolean>`로 변경: 성공 끝에 `return true`, 각 실패(`!rt`/`!newAccess`/`catch`)에 `return false`.
   - `stopTokenRefreshTimer` 위에 export 추가:
     ```ts
     /** 수동 토큰 재발급 트리거(세션 칩 클릭용). 성공 true / 실패 false. */
     export function refreshTokenNow(): Promise<boolean> {
       return doRefreshAndReschedule();
     }
     ```
2. `src/components/layout/HeaderActionBar/index.vue`
   - import 추가: `import { refreshTokenNow } from "@/utils/tokenRefreshTimer";` + `import { ElMessage } from "element-plus";` (ElMessage는 element-plus에서 명시적 import 필요)
   - `sessionExpiryTooltip` computed 아래에 핸들러 추가:
     ```ts
     const handleSessionChipClick = async () => {
       const ok = await refreshTokenNow();
       if (ok) { authExpiryStore.clear(); ElMessage.success("세션이 갱신되었습니다."); }
       else { ElMessage.error("세션 갱신에 실패했습니다. 저장 후 재로그인 해주세요."); }
     };
     ```
   - 칩 div에 `@click="handleSessionChipClick"` 추가
   - `.session-expiry-chip` 스타일 `cursor: default` → `cursor: pointer`
   - (테스트 편의) 칩 강제노출: `v-if="authExpiryStore.active"` → `v-if="true"`. **정식 적용 시엔 이건 하지 말 것**(active일 때만 뜨는 게 맞음). 강제노출은 SSE 없이 테스트하려던 임시조치였음.

**실서버 검증 결과(2026-07-02 밤):**
- 재발급마다 JWT `exp` 정상적으로 뒤로 밀림(예: 20:56:13 → 21:04:05 → 21:07:11).
- sessionStorage accessToken == assist-stream/VOC API 요청헤더 `Authorization: Bearer` **100% 일치** → 저장→요청반영 정상.
- **VOC 탐지 API 정상 동작**.
- ⚠️ 토큰 payload `ad` 값이 재발급마다 바뀜(549596→189144→436188…). `sub/acc/cId/cd/role`은 고정. **VOC엔 영향 없음 확인**(무해한 세션/발급 식별자로 추정).
- (무관) `asst-service/summary`에서 뜬 `503 "LLM Orchestrator 서비스에 연결할 수 없습니다"`는 **토큰과 무관한 백엔드 이슈**(401 아님=인증 통과). 별건.

**정식화 시 고민:** 이 수동 버튼은 경로①(자동)이 실패했거나 refreshToken 만료 직전 백업 용도로 유용. 칩은 `active`일 때만 뜨게 유지하고, 성공 후 `authExpiryStore.clear()`로 칩 제거되는 UX가 자연스러움(경로① 성공 후에도 칩이 안 사라지는 기존 미세버그 함께 해소됨).

## 2026-07-06 등록

### 8. "이전대화 불러오기" — 문서/오른쪽 패널(AI요약·문서 탭)까지 복원 [대화복원 후속, 요청 시 착수]
**배경:** 실시간 상담 중 이탈→복귀 시 유실되는 데이터 복원 기능. 이번(2026-07-06)에 **대화(turn)만** 복원 구현 완료(상세: CLAUDE-history.md 2026-07-06 "이전대화 불러오기"). 오른쪽 화면의 **문서/AI요약(탭 형태 패널)은 이번 범위에서 제외** — 사용자 판단으로 "대화만" 확정, 문서 복원은 요청 시 후속.

**왜 대화보다 복잡한가:** 문서/요약은 "고객 발화(turn) → assist-stream 검색 → 결과 문서·요약"의 **파생물**이라 ①turn 종속(어느 turn에 어떤 문서 붙었는지 매핑 복원) ②탭 UI 상태(열린 탭/선택 문서)까지 신경 써야 함.

**백엔드 확인 완료된 사실 (복원 가능 전제 = 통과):**
- assist 결과(문서/요약)는 **DB에 저장됨 + 턴별 저장**.
- ⭐ **백엔드 자동 저장이 아니라 프론트가 `POST /assist-stream/snapshot`(`path.ADVISOR.API.ASSIST_STREAM_SNAPSHOT`, path.ts:57) 호출해서 저장**함. 저장 진입점은 백엔드 컨트롤러 하나(`AssistSnapshotService.save()`). → **문서 뜰 때마다 실시간 저장이라 진행 중 통화도 DB에 원본 존재** = 복원 재료 있음.
- **상담 종료 후 이력에서 문서 클릭해서 보는 기능이 이미 존재** → 조회 API + 렌더 로직이 이미 있음 = **재활용 발판**(난이도 낮추는 핵심).

**착수 시 프론트에서 확인할 3가지 (미조사):**
1. **저장 호출부** — 프론트 어디서 `POST /assist-stream/snapshot` 부르나 + payload에 **turn 연결키(turn_idx/call_id)** 포함되나.
2. **조회 경로** — snapshot GET API + 상담이력 모달의 문서/요약 렌더 로직 위치(재활용 대상).
3. **실시간 오른쪽 패널 데이터** — 지금 문서/요약이 화면에서 어디 보관되나(store? `chatContent` 항목 필드? `chatData.ts`의 `assistStreamText`/`assistStreamSummary` 등).

**예상 접근:** 대화 복원(`loadPreviousTurns`)과 동일 궤 — 복귀 시 call_id로 snapshot 조회 → turn 매핑해 오른쪽 패널/탭 재구성. 실시간 무영향(try/catch 격리) 원칙 동일 적용.

## 2026-07-08 등록

### 9. RAG 원본보기(V2) — 계층형 청킹 대응 + 하이라이트 제목/본문 보정 [배포 후 라이브 검증 중]
**상태:** 코드 적용 완료, **배포 후 사용자 라이브 검증 중**. 문제 시 직전으로 원복 가능하도록 기록. **(이 repo는 git 명령 금지 — 원복은 파일 직접 편집)**

**배경/원인:** 한투 적용되면서 aicm의 청킹이 **서브청킹(계층형)** 으로 바뀜(2026-07-03 무렵 `_blocks_to_outline` 목차 계층화, "앞으로 이 구조가 표준"). 그 결과 원본보기(docx=`get_doc` 마크다운 렌더, `DocOriginalViewerModalV2.vue`)에서 두 가지 문제 발생:
1. **본문 잘림** — `assembleMarkdown`이 top-level `section.blocks`만 읽고 `section.children`을 재귀 안 해서, children에 중첩된 본문(대부분)이 조립에서 빠짐 → "앞 몇 개만" 보임.
2. **제목만 하이라이트** — 계층형에선 `source_location.heading_path`가 실제 섹션 제목이 아니라 **상위 카테고리 하나**(예: `["CMA"]`)만 담음. `focusByHeadingPath`가 그 "CMA" 부모 제목에 매칭 → 제목만 칠해지고 본문 못 잡음. (1번 수정으로 부모 카테고리 제목이 렌더되기 시작하면서 표면화된 부작용)

**적용한 변경 (1파일 · `DocOriginalViewerModalV2.vue`):**
- **① `assembleMarkdown` 재귀화** — 기존 flat `for (section of outline)` → 내부 `walk(sections, depth)`로 `section.children`까지 재귀. heading 레벨은 depth 기반(`"#".repeat(depth+1)`), 직접 블록 없는 상위 섹션도 `if (heading || body.trim())`로 제목만 넣고 자식 진입. → 계층형 전체 조립(평탄 구조도 그대로 동작 = 범용).
- **② `headingHasBody(startEl)` 헬퍼 신설 + `focusByHeadingPath` 매칭 가드** — 매칭된 게 heading인데 그 아래 청크 본문이 안 붙으면(`/^H[1-6]$/.test(el.tagName) && !headingHasBody(el)`) 그 매칭 버리고 continue → 본문 텍스트 폴백(`focusActiveContent`)으로 넘어가 실제 답변 문단 하이라이트.
- **③ `highlightSectionRange` 양방향 확장** — 기존 "앞으로만" 확장 → 앵커 기준 **앞뒤 양방향**으로 청크(content) 속 블록 확장. 본문 앵커면 위 섹션 제목까지(`kms-focus`) 강조. → 긴 답변에서 앵커가 중간에 걸려도 앞부분까지 다 칠해짐("일부만 하이라이트" 방지) + 제목+본문 끊김 없이 강조. (heading 앵커면 뒤로 확장 안 함 = 정상 케이스 무변경)
- **④ `focusByContentAnchor` 신설 + `focusActiveContent` 우선순위 재정렬 (content 우선)** — 기존은 heading_path를 먼저 써서, heading_path가 거친 카테고리("계좌개설")일 때 **같은 카테고리의 다른 섹션(예: "스마트폰 계좌개설 중 신분증 촬영")에 오매칭**(substring 매칭 + "대분류/세부분류" 공통 접두로 본문검사까지 통과)됐음. → 이제 ①청크 본문(`sectionContent`)의 **템플릿 접두 제외한 '구별되는 줄'로 실제 블록을 먼저 찾고** ②실패 시 heading_path(표 문서용) ③최후 activeContent 순. 특정성 높은 content 우선이라 오섹션 방지.

**원복 방법 (파일 직접 편집, 셋 다 `DocOriginalViewerModalV2.vue`):**
- **①** `walk` 재귀 제거 → 원래 `for (const section of outline)` flat 루프로. 핵심 원형: `if (!blocks.length) continue;` / `const level = section?.title_block_type === "heading_1" ? "# " : "## ";` / `if (body.trim()) parts.push(heading + body);`.
- **②** `headingHasBody` 함수 삭제 + `focusByHeadingPath` 매칭 블록의 `if (/^H[1-6]$/.test(el.tagName) && !headingHasBody(el)) continue;` 한 줄 삭제.
- **③** `highlightSectionRange`를 "앞으로만 확장" 원형으로 되돌림: 제목 매칭 요소(startBlock)에 `kms-focus` → `startIdx+1`부터 `isCoveredByContent` 참인 동안 `kms-focus-range`로 forward 확장(양방향/뒤로-제목 로직 삭제), `!contentCompact || startIdx===-1` 조기 return.
- **④** `focusByContentAnchor` 함수 삭제 + `focusActiveContent`에서 호출부(`if (focusByContentAnchor()) return;`) 삭제 → `focusByHeadingPath` 먼저 호출하던 순서로 복귀.

**회귀 안전장치:** ②는 heading 매칭에만 적용(본문/폴백 무관), ③은 앵커가 heading이면 안 탐 → 제목=실제 섹션이라 원래 잘 되던 케이스는 무변경. ①은 평탄/계층형 둘 다 처리(범용).

**검증 체크포인트:** "CMA유형을 변경하고 싶어요" 케이스로 ①본문 뒷부분까지 다 나오나 ②하이라이트가 "CMA" 제목이 아니라 실제 답변 문단에 칠해지나 ③폴백 케이스(예: ISA 공모주)에서 제목~본문 사이 구멍 없이 이어지나 ④정상(제목=섹션) 케이스 회귀 없나.

**검증 결과 따라:** 정상이면 이 항목 삭제, 문제면 위 "원복 방법" 적용.
