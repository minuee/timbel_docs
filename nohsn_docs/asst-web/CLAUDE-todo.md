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
