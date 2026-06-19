# 대화 기록 (Conversation Log)

> 규칙: 클로드와 사용자의 모든 대화를 이 파일에 순차 기록한다.
> `CLAUDE.md` 에는 사용자가 별도로 지정할 때만 저장한다.

## 2026-06-10

### 1. 인사
- **사용자:** 오늘 작업할 게 있으니 잘 부탁한다는 인사.
- **클로드:** 인사. 최근 감정(VOC탐지) 작업 진행 중임을 언급하며 무엇을 도울지 질문.

### 2. `POST /assist-stream` 요청부 분석 요청
- **사용자:** 감정 기능 작업 전 사전 분석. 이 프론트엔드 프로젝트에서 `POST /assist-stream` 을 요청하는 부분을 찾아달라.
- **클로드:** 분석 결과 정리.
  - **단일 진입점:** `src/api/apis/assist-stream.api.ts:17` `callAssistStream()`
  - **엔드포인트:** `path.ADVISOR.API_PREFIX` + `/assist-stream` = `/aicc/asst-service/assist-stream` (`path.ts:56`)
  - **HTTP 클라이언트:** axios 아님 → **`fetch`** 직접 사용 (SSE 스트리밍). `Accept: text/event-stream`, `x-auth-token` + `Authorization: Bearer` 헤더.
  - **응답 처리:** `parseSseStream()`(`src/api/apis/sse-parser.ts`) 로 SSE 이벤트 파싱 → `handlers[event](data)` 디스패치.
  - **실제 사용처:** `src/view/advisor/components/chat/composables/useChatAssist.ts` (메시지 ID별 `AbortController` 로 스트림 관리, `assistStreamControllers` 맵, 215~558 라인).
  - **SSE → 상태 반영:** `src/stores/modules/chatData.ts` (`assistStreamText` 토큰 누적, `assistStreamSummary` distilled 저장).
  - **타입:** `src/api/types/assist-stream.type.ts` (`AssistStreamReq`, `AssistStreamHandlers`, `SourcesEvent`, `DistilledEvent`, `TokenEvent`, `AssistStreamErrorEvent`).
  - **스냅샷 저장:** `src/api/apis/assist-snapshot.api.ts` (`POST /assist-stream/snapshot`).

### 3. 대화 기록 규칙 설정
- **사용자:** 앞으로 모든 대화를 `CLAUDE-history.md` 에 순차 저장. `CLAUDE.md` 에는 별도 지정 시에만 저장.
- **클로드:** 규칙 확인. 사용자가 파일을 초기화한 뒤 이 대화 기록 파일을 새로 작성.

### 4. SSE 수신·처리 방식 분석
- **사용자:** 백엔드 swagger 의 `{ query, conversationHistory[{speaker,content}], repositoryId, callId }` 를 SSE 에서 어떻게 받아 처리하는지. SSE 단방향이라 수신 끝날 때까지 받아 처리하는 부분이 어떻게 되어 있나.
- **클로드:** 분석 결과.
  - **중요 정정:** swagger 의 그 스키마는 **응답이 아니라 요청(Request) 본문**. 응답은 JSON 단일 객체가 아니라 **SSE 이벤트 스트림**.
  - **요청:** `useChatAssist.ts:246` 에서 `{ query, conversationHistory, callId }` 전송. `conversationHistory` 는 `extractRecentConversation()`(`:213` 부근)이 직전 메시지 최대 2개를 `{speaker:'customer'|'agent', content}` 로 변환. `repositoryId` 는 현재 미전송(optional).
  - **응답 SSE 프레임:** `event: <name>\ndata: <json>\n\n` 형식. 프레임 구분자는 빈 줄(`\n\n`).
  - **수신 루프 (`src/api/apis/sse-parser.ts`):** `res.body.getReader()` → `while(true){ await reader.read() }`. `done` 이면 탈출. `buffer.split("\n\n")` 로 완성 프레임만 처리하고 `frames.pop()` 으로 미완성 꼬리는 버퍼에 보존(다음 청크와 이어붙임). `event:`/`data:` 파싱 후 `JSON.parse` → `onEvent(event,data)`. **`event === "done" || "error"` 이면 `return` 으로 능동 종료.**
  - **SSE 단방향 처리 3대 포인트:** ① 언제까지 받나 = `while+await reader.read()` (I/O 블로킹, CPU 미점유) ② 끝 판단 = 백엔드의 `done`/`error` 이벤트(또는 TCP 종료 시 reader `done`) ③ 쪼개진 청크 조립 = `\n\n` split + 마지막 조각 버퍼 보존.
  - **이벤트별 핸들러 (`useChatAssist.ts` 245~533, 순차 점진 처리):**
    - `intent`(`:249`): 검색 여부 판단. `skipped:true`(일상대화) → 이후 전부 무시 + 스트림 정리.
    - `sources`(`:267`): 문서 5개 `pendingAllItems` 버퍼링(칩 아직 미생성), 원본은 `snapshotBuffer.sources` 보존.
    - `distilled`(`:334`): LLM 선택 `selected_refs` 로 필터링 → 칩 생성 + 첫 문서 자동선택 + 요약 표시. 빈 배열이면 종료.
    - `token`(`:422`): 답변 텍스트 조각 누적(`snapshotBuffer.answer += e.text`) + `appendAssistStreamToken()` 실시간 타이핑. 참조번호 `[1,3]` 정규식 제거.
    - `done`(`:436`): 로딩 종료, distilled 없이 sources 만 온 경우 fallback, 마지막에 `snapshotBuffer` 를 `POST /assist-stream/snapshot` 저장(fire-and-forget).
    - `error`(`:518`): 로딩 해제 + 로깅.
  - **취소/중복 방어:** 메시지ID별 `AbortController` 를 `assistStreamControllers` Map 보관. 같은 메시지 새 스트림 시작 시 `prev?.abort()`(`:215`). `finally` 에서 Map 정리하되 이미 교체됐으면 미터치(`:557`).
  - **한 줄 요약:** 백엔드가 `intent → sources → distilled → token(N) → done` 순차 전송, 프론트는 reader 루프로 `\n\n` 단위 프레임 조립·이벤트 핸들러 호출, `done`/`error` 가 종료 신호.

### 5. "미완성 꼬리 버퍼링" 트릭과 화면 짤림 방어
- **사용자:** 미완성 꼬리를 버퍼에 남겼다 이어붙이는 게 SSE 수신 핵심 트릭인가? 그러면 화면에 짤린/이상한 내용이 안 나오겠네? URL 일부만 와서 이미지가 안 보이거나 하지 않나?
- **클로드:** **두 레벨을 구분해야 함.** 버퍼링이 보장하는 건 "전송 프레임 무결성"이지 "의미 내용 완성도"가 아님.
  - **레벨 1 (버퍼링이 막는 것):** 반쪽 JSON 을 `JSON.parse` 하는 사고만 방지. 핸들러엔 항상 완성된 유효 JSON 1개만 도착. ✅
  - **레벨 2 (버퍼링이 못 막는 것):** `token` 이벤트는 **설계상 일부러 글자를 쪼개 전송**(타이핑 효과). 각 프레임은 멀쩡하나 누적 답변은 스트리밍 도중 미완성 문장. → URL/참조번호가 토막난 상태가 실제로 존재함.
  - **앱 레벨 방어 (레벨 2 별도 처리):** `useChatAssist.ts:426` 와 `knowledge/index.vue:534` 에 동일 정규식 쌍 —
    - `replace(/\s*\[\s*\d+(?:\s*,\s*\d+)*\s*\]/g, "")` : 완성된 참조번호 `[1,3]` 제거.
    - `replace(/\s*\[[\s\d,]*$/, "")` : **끝에 매달린 미완성 `[1, 2` 제거** ★ → `[1` `[1,` 깜빡임 방지.
  - **이미지 깨짐 방어:** 스트리밍 답변(`aiSearchResultText`, `index.vue:535`)은 **`v-html` 마크다운이 아니라 평문 텍스트로 렌더**. 반쪽 URL 와도 평문 글자로만 보이고 깨진 이미지 아이콘 안 뜸. (마크다운 실시간 렌더였다면 미완성 `![](https://exa` 가 깨진 이미지로 깜빡였을 것 → 평문 렌더가 안전한 선택). `v-html` 은 검색결과 키워드 하이라이트(`:63`) 에만 사용, 스트리밍 대상 아님.
  - **결론:** 버퍼링 트릭 = 전송 레벨 핵심(O). 화면 내용 안정성은 별개로 정규식 트림 + 평문 렌더로 따로 방어.

### 6. VOC 탐지 — 기존 assist-stream 에 얹을지 신규 개발할지 (논의 진행 중)
- **사용자:** 현재 SSE 는 상담사가 참고할 문서정보/내용을 실시간 노출. VOC 탐지(감정 + 기타 체크사항 통칭)도 실시간으로 넘어와 상담사가 고객 감정 파악을 돕는 기능. 기존에 얹어 개발할지 새로 개발할지 고민.
- **클로드:** 트리거 시점 확인 결과 — `handleAssistStream` 은 `useChatMessageParser.ts:466` 에서 `isUser && isFinalEnding`(고객 발화 final) 시 호출. VOC 도 같은 순간 실행 대상.
  - **공통점:** 트리거 시점 동일, 입력 동일(callId+conversationHistory+발화), SSE 실시간.
  - **차이점:** ① 출력 성격 — assist 는 무거움(문서N+토큰스트림), VOC 는 가벼움(분류1+플래그). ② **실행 조건 — assist 는 조건부(`intent.skipped`/`selected_refs` 빈 경우 중단), VOC 는 무조건(모든 발화)**. ③ 실패 도메인 독립 필요.
  - **결정 핵심 질문:** "VOC 를 문서검색이 안 일어나는 발화(일상대화/intent.skipped)에서도 돌려야 하나?" → 화난 고객 푸념이 바로 그런 케이스라 감정은 오히려 더 중요할 수 있음.
  - **클로드 추천:** **인프라 재사용 + 채널 분리(전용 엔드포인트 신규).** `sse-parser.ts`·fetch+auth 패턴 재사용해 비용 낮음. `voc-stream.api.ts`(assist 복제+엔드포인트 교체) / `voc-stream.type.ts` / voc 핸들러 추가. 이유: 독립 cadence(skip 게이트 회피), 독립 실패도메인, 가벼운 페이로드(`event: voc` 한 방), 독립 진화. — 단 백엔드가 한 추론으로 docs+VOC 같이 계산하는 게 이득이면 기존 응답에 `event: voc` 얹고 프론트가 `skipped` 무시(백엔드가 intent 게이트 이전에 emit 필요).
  - **참고:** 통화 *종료 후* 감정은 이미 `/summary` 응답 `emotion`(현재 하드코딩) 경로 존재. 지금은 통화 *중 실시간* 이라 별개 작업.
  - (사용자가 방향 확정 전에 다음 질문으로 전환 → 결정 보류)

### 7. `query` ↔ `conversationHistory` 파라미터 관계 확인
- **사용자:** `POST /assist-stream` 의 `query` 와 `conversationHistory` 관계. query 는 지금 메시지? history 는 언제까지의 내역?
- **클로드:** 호출부(`useChatMessageParser.ts:466~469`)+`extractRecentConversation`(`useChatAssist.ts:195`) 연결 결과.
  - **`query`** = 지금 막 final 로 끝난 **고객의 현재 발화** 1건 (`displayText`).
  - **`conversationHistory`** = **현재 발화를 제외한 직전 최근 2개 메시지** (슬라이딩 윈도우, 전체 통화 이력 아님).
  - **핵심 4가지:** ① 현재 메시지는 history 에서 `continue` 로 제외 → query/history 중복 없음(`:201`). ② `history.length>=2 break` → 직전 2건만(`:207`). ③ `unshift` 로 과거→현재 시간순 정렬. ④ ⚠️ 주석은 "2턴"이나 실제로는 화자 무관 **2개 메시지** 카운트(user/consultant 혼합 가능). speaker 매핑 `user→customer`, `consultant→agent`.
  - **곁가지:** assist 의 `query` 는 `displayText`(마스킹 안 된 원문), 스냅샷용 `customerQuery` 는 `masked_text ?? displayText`(마스킹 우선)(`:468`).

### 8. 히스토리 2건 제한이 하드코딩인지 + 백엔드 누적 확인 예정
- **사용자:** conversationHistory 2건 제한이 소스에 하드코딩인가? 그리고 총 최근 3건만 보내니 전체 이력 아님 → 백엔드가 누적 관리하는지 확인하고 오겠다.
- **클로드:** `useChatAssist.ts:207` 의 `if (history.length >= 2) break;` — **리터럴 `2`, 상수 아님(매직넘버)**. 주석(`:194`)에도 "2턴" 적혀 있어 변경 시 코드+주석 둘 다 수정 필요. 이 함수는 `useChatAssist.ts` 내부에서만 사용(다른 SSE 사용처 없음). → **결정 보류: 백엔드가 callId 로 전체이력 누적하면 프론트 3건으로 충분, stateless 면 윈도우 확대 검토.** (사용자 백엔드 확인하러 감)

### 9. 스냅샷 저장 API(`POST /assist-stream/snapshot`) 실제 진행 여부
- **사용자:** 스냅샷 저장 별도 엔드포인트 `POST /assist-stream/snapshot` 실제 진행되는 API 인가?
- **클로드:** **✅ 실제 호출됨.** `useChatAssist.ts:509` `done` 핸들러에서 `if (currentCallId.value && turnIdx != null)` 조건으로 호출. **환경 게이팅 없음(dev/prd/local 전부)** — QA 집계 엔드포인트와 다름.
  - **엔드포인트:** `/aicc/asst-service/assist-stream/snapshot`, POST, **axios**(`super("advisor")`) — 본체(fetch)와 달리 일반 axios.
  - **특징:** ① `done` 시점에 `snapshotBuffer`(hint+sources+distilled+answer) **한 방 저장**(스트리밍 아님, SSE 최종결과 영속화). ② **fire-and-forget + silent fail** — `void` 호출(UI 안 막음), 실패해도 화면 영향 없음, **최대 3회 재시도**(초기1+500ms→1s 백오프) 후 `console.warn`(`assist-snapshot.api.ts:24~41`). ③ **upsert** — `callId`+`turnIdx` 키로 턴별 저장/갱신, `customerQuery`(마스킹) 동봉.
  - **VOC 시사점:** 이미 **턴별(`turnIdx`) 결과 영속화 패턴**이 존재 → VOC 도 `payload` 에 `voc` 필드 추가하거나 별도 스냅샷 엔드포인트 선택 가능. 얹으면 snapshot 에 같이 저장 가능, 분리하면 VOC 스냅샷 별도 고민.

### 10. turn_idx 출처 — VOC 턴별 저장 위해 확인
- **사용자:** `/assist-stream` 파라미터(query/conversationHistory/repositoryId/callId)가 서버로 갈 때 `turn_idx` 는 어떻게 정해지나? 백엔드가 `/assist-stream` 호출 시 VOC 감지 후 턴별 저장하려는데 turn_idx 필수.
- **클로드:** 추적 결과 **두 가지 핵심 사실**.
  - **① turn_idx 는 프론트 생성값 아님 → 백엔드(오케스트레이터)가 STT/NLP 메시지(redis `nlp:complete`/`nlp:partial`)에 실어 내려주는 단조증가 정수.** 발화(턴)마다 부여, 고객/상담사 각각 다른 번호(픽스처상 customer=10, agent=11…). 프론트는 `messageData.turn_idx` 를 읽기만 함(`useChatMessageParser.ts:467`). 용도: 버블 dedup(`:391`), 스트리밍 추적, 스냅샷 저장 키.
  - **② ⚠️ 현재 `/assist-stream` 요청 본문엔 turn_idx 가 안 실림.** `useChatAssist.ts:247` 은 `{ query, conversationHistory, callId }` 만 전송. turn_idx 는 함수 인자로만 받아 **`done` 시점 스냅샷 저장(`/assist-stream/snapshot`)에만** 사용. → 지금 구조상 백엔드는 `/assist-stream` 호출 시점에 turn_idx 모름.
  - **VOC 턴별 저장 위한 선택지:**
    - **옵션 A (추천, 비용≈0):** 프론트가 `/assist-stream` 요청 본문에 `turnIdx` 추가. `handleAssistStream` 이 이미 `turnIdx` 인자 보유 → `callAssistStream({ query, conversationHistory, callId, turnIdx })` 한 줄. 백엔드 스키마에 필드 추가하면 VOC 를 그 자리서 turn_idx 묶어 저장. 백엔드가 "최신 턴" 추정 불필요.
    - **옵션 B:** 백엔드가 `callId` 로 오케스트레이터 상태 조회해 자체 결정. 프론트 무변경이나 요청에 턴 식별자 없어 매칭 타이밍/경합 리스크.
  - **→ 추천 A.** 프론트가 정확한 turn_idx 보유(스냅샷에 이미 사용), 본문 추가 한 줄로 안전·명확.
  - **표기 주의:** 백엔드 STT/스냅샷응답 = `turn_idx`(snake), 프론트 변수/스냅샷저장본문 = `turnIdx`(camel, `assist-snapshot.type.ts:30`). `/assist-stream` 에 추가 시 snake/camel 합의 필요.

### 11. turn_idx 수신 경로 전체 추적 (STT 발급값 — 자동생성 아님)
- **사용자:** 스냅샷 스키마에 `turn_idx IS 'STT 발급 턴 인덱스'` 코멘트 발견 → 자동생성 아님, 어디선가 받아 처리. 분석 요청.
- **클로드:** **turn_idx 는 프론트 어디서도 생성 안 함. STT 백엔드에서 두 경로로 들어옴.**
  - **경로 1 — 실시간 통화(Socket.IO):** `[STT엔진/오케스트레이터] turn_idx 발급 → redis pub/sub(채널 nlp:complete/nlp:partial) → 백엔드 socket 게이트웨이가 Socket.IO event "redis-message" 로 푸시 → socketIOPlugin → useChatSocket.ts:54 on("redis-message", onMessage) → chat/index.vue:1068 parseMessageData(data) → useChatMessageParser.ts:104 messageData = raw.message.message(문자열이면 JSON.parse) → messageData.turn_idx 추출`.
    - **중요:** 전송 계층이 **SSE 아님 → Socket.IO**. STT 자막은 socket.io `redis-message`, 문서검색은 SSE `/assist-stream` — **두 파이프라인 완전 별개**.
    - raw 구조 = `{ message: { message: <STT payload>, channel }, timestamp }`. 실제 데이터는 **이중 중첩 `raw.message.message`**(문자열이면 `JSON.parse`, `:104~107`). 채널명으로 종류 구분(nlp:complete=완료발화, nlp:partial=부분발화, :call:events=통화시작/종료).
  - **경로 2 — 통화 복원/이어보기(REST):** `AgentAPI.getCallStt(callId)` → `response.data[].turn_idx` → `addChatMessage({turnIdx: stt.turn_idx})` (`chat/index.vue:1084, 1130`).
  - **결론:** 두 경로 모두 백엔드 발급값을 프론트가 받아 쓰기만 함. 계산/자동생성 없음. 스키마 코멘트와 코드 일치.
  - **VOC 시사점:** 옵션 A(프론트가 `/assist-stream` 요청에 turn_idx 추가)가 더 탄탄 — 프론트는 `handleAssistStream` 트리거 시점에 **그 발화의 STT 발급 `messageData.turn_idx` 를 이미 보유** → 요청 본문에 그대로 넣으면 백엔드가 VOC 를 STT turn_idx 와 1:1 정확 매칭 저장 가능, 턴 추정 불필요. (옵션 B 는 백엔드가 STT 상태 재조회 필요 → A 가 단순·정확)

### 12. [작업완료] `/assist-stream` 요청 본문에 `turnIdx` 추가 (옵션 A 구현)
- **사용자:** 가능한 구조 확인. `/assist-stream` 요청에 turn_idx 추가하되 **필수 아님(기본 null, 값 있으면 전송)**. 작업 후 백엔드 클로드용 설명 정리 요청.
- **클로드 작업 (2개 파일 수정):**
  - `src/api/types/assist-stream.type.ts` — `AssistStreamReq` 에 `turnIdx?: number | null` 추가(주석 포함).
  - `src/view/advisor/components/chat/composables/useChatAssist.ts:247` — `callAssistStream({ query, conversationHistory, callId, turnIdx: turnIdx ?? null })`. `handleAssistStream` 이 이미 받던 STT turnIdx 전달. **값 없으면 null** (키는 항상 존재 → 백엔드 파싱 안정성, `undefined` 로 키 누락 방지). 필수 아님 → 값 없어도 오류 X.
  - `npx tsc --noEmit` 관련 에러 없음(통과).
- **백엔드 클로드 전달 설명 요지:**
  - `/assist-stream` 요청 본문에 `turnIdx`(number|null, optional) 추가. null 허용 필수(null 와도 400 금지).
  - 의미 = **STT 발급 turn_idx 와 동일값**(프론트가 트리거 발화 `messageData.turn_idx` 가공없이 전달). 스냅샷 테이블 `turn_idx` 와 완전 동일.
  - 백엔드 할일: ① DTO 에 nullable `turnIdx` 추가 ② VOC 결과를 `(callId, turn_idx)` 키로 저장(스냅샷과 동일 매칭) ③ null 이면 턴별저장 스킵/별도처리.
  - ⚠️ **네이밍:** 프론트는 요청 컨벤션(conversationHistory/callId 등 camelCase) 맞춰 **camelCase `turnIdx`** 전송. STT/스냅샷 원본은 snake `turn_idx`. 백엔드가 `turnIdx`(camel) 받아 내부 `turn_idx`(snake) 매핑하거나, snake 원하면 프론트 필드명 변경 가능.

### 13. VOC 실시간 소켓 채널 신설 — 기존 소켓 인프라 분석
- **사용자:** VOC 실시간 탐지를 `/assist-stream` 요청 시 1회 + 이후 3턴마다 소켓으로 프론트 푸시 예정. 상담사 조회화면이 소켓통신(공지/코칭 등)으로 됨. 새 소켓채널 만들 계획, 분석 정리 요청(백엔드와 나중에 추가).
- **클로드 분석 — 기존 소켓 인프라 핵심 구조:**
  - **① 단일 소켓 + 단일 이벤트:** 앱 전체가 socket.io 연결 1개 공유(`socketIOPlugin.ts` 모듈 전역 싱글톤). 백엔드→프론트 **모든 메시지가 `"redis-message"` 이벤트 하나로** 들어옴(STT/통화이벤트/공지/코칭 전부). 종류 구분은 이벤트가 아니라 **채널 문자열**: `raw.message.channel.includes("nlp:complete"|"nlp:partial"|"call:events"|"orchestrator:persisted")`.
    - ⭐ **핵심: "새 소켓 채널" = 새 socket.io 이벤트 아님 → 새 Redis 채널명 + 구독 + `channel.includes()` 분기.** 기존 `redis-message` 버스 재사용이 정석.
  - **② 메시지 봉투:** `raw = { message: { message: <payload, 문자열이면 JSON.parse>, channel }, timestamp }` (payload 이중중첩).
  - **③ 채널명 규칙(`src/utils/redisKey.ts`):** `${env}:${tenantId}:${agentId}:call:${service}`. nlp→`:call:nlp:complete`, partial→`:call:nlp:partial`, events→`:call:events`, db→`:call:orchestrator:persisted`.
  - **④ 구독 라이프사이클(`useChatSocket.ts`+`subscribe.api.ts`):** `subscribeChannels([채널]) → REST POST /redis-monitor/subscribe/{encodeURIComponent(채널)} → 응답 {room} → socket.emit("join-room", room) → on("redis-message", onMessage)`. **⚠️ 공유소켓 주의:** `teardownListeners` 는 리스너만 제거, unsubscribe/leaveRoom 안 함(단일소켓 공유라 한 곳이 해제하면 admin/drawer 구독까지 파괴, `:71~74`).
  - **⑤ 같은 버스 구독처:** chat/index.vue:1068(`parseMessageData`, STT), Dashboard.vue:377(`handleRedisMessage`, 전화수신 화면전환), ConsultantDrawer/index.vue:212(`parseRedisMessage`, 코칭/통화). 구독 채널 배열은 화면마다 다름 → VOC 채널은 필요한 화면 배열에만 추가.
- **클로드 — VOC 채널 신설 방안:**
  - **프론트 추가(4곳):** ① `redisKey.ts` 에 `case "voc": return ...:call:voc` ② 구독배열(`chat/index.vue:1218~1223` 등)에 `getRedisKey(...,"voc")` 추가 ③ `useChatMessageParser.ts` 분기 `else if (channel.includes("call:voc")) { messageData={turn_idx,emotion,...} → 스토어 turn_idx 키 저장 → 노출 }` ④ VOC 상태 스토어 신설/확장(`chatData.ts` 패턴).
  - **백엔드 할일:** ① VOC 결과를 redis 채널 `{env}:{tenant}:{agent}:call:voc` 로 publish(봉투는 bridge가 감쌈) ② payload 에 `turn_idx` 포함(턴별 매칭) ③ cadence(`/assist-stream` 1회 + 3턴마다)는 **백엔드 타이밍 로직 전담**, 프론트는 오는대로 렌더라 무관.
  - **합의 포인트:** 전송=기존 `redis-message` 재사용(새 이벤트 불필요) / 채널명 `:call:voc` 네이밍 / payload `turn_idx`(snake) 포함 / 턴별 누적(turn_idx 키 맵)으로 감정추이 표시 권장.

### 14. 채널 prefix env — 프론트는 하드코딩 아님(VITE_USER_NODE_ENV) + prd 불일치 이슈
- **배경(백엔드 클로드):** Redis publish 인프라 파악 — `redisService.publish(channel, JSON.stringify(payload))`, 채널 `{env}:{tenant}:{agent}:call:...` (agent-call-setting.service 가 `{env}:{vendorTenantId}:{agentId}:call:setting` 사용, **env 'dev' 하드코딩**). 소켓 bridge 여부와 토큰에서 agent/tenant 얻는 법 확인 예정.
- **사용자:** 'dev'는 하드코딩 아니라 프론트에선 env 파일의 `VITE_USER_NODE_ENV` 쓰는 거 아닌가?
- **클로드:** **맞음 — 프론트는 `VITE_USER_NODE_ENV` 사용(하드코딩 아님).** 단 이 때문에 **운영(prd) 채널 불일치 이슈** 발견.
  - **해석 체인:** npm script(MODE=xxx) → `webpack.config.js:14` `dotenv.config({path:.env.${MODE}})` → `:78` DefinePlugin 빌드시 문자열 치환 → `redisKey.ts:4` `process.env.VITE_USER_NODE_ENV` → 채널 prefix. (런타임 아니라 **빌드시 리터럴**).
  - **빌드별 값:** `build:dev`(.env.dev)=`dev`, `local`(.env.local)=`dev`, **`build:prd`(.env.prd)=`prd`** ⚠️. 타입은 `"dev"|"prd"` 고정(`global.d.ts:53`, prod/aws 아님).
  - **⚠️ 핵심(백엔드 전달):** 백엔드 env 'dev' 하드코딩 시 — dev/local 은 우연히 일치하나 **운영에선 프론트가 `prd:...:call:voc` 구독, 백엔드는 `dev:...` publish → 프론트 영영 수신 못 함.** 백엔드도 하드코딩 말고 프론트 `VITE_USER_NODE_ENV`(dev/prd)와 동일하게 prefix 생성 필요. (기존 `:call:setting` 채널도 동일 잠재버그, dev에서만 돌아 안 드러난 듯.)
  - **참고(프론트 내부):** `npm run dev`(MODE=development)는 `.env.development` 파일 없어서 `VITE_USER_NODE_ENV` undefined → 채널 `undefined:...`. 로컬은 `npm run local`(MODE=local) 사용해야 정상.

### 15. 백엔드 질문 — 구독→relay bridge 직접 넣나, publish만 하나?
- **백엔드 클로드 질문:** 구독→relay(B)도 내가 이 서비스에 넣나, 아니면 별도 bridge가 구독 담당이라 나는 publish만?
- **클로드 답: publish 만 하면 됨. bridge 는 이미 존재·가동 중 → 만들지 말 것.**
  - **결정적 증거:** STT 자막(nlp:complete/partial)·call:events·orchestrator:persisted 가 **지금 이미 프론트 정상 수신** → 구독→relay→socket.io 경로가 이미 완성·가동 중이라는 증거.
  - **프론트가 보는 bridge 실체(전부 `/aicc/asst-service` prefix 아래):** 구독 REST `POST /aicc/asst-service/redis-monitor/subscribe/{channel}`(`subscribe.api.ts`), 해제 `DELETE .../unsubscribe/{channel}`, **socket.io 서버 path=`/aicc/asst-service/socket.io`**(`consultant/index.vue:49`, baseUrl=LANGSA_GATEWAY_URL), 룸 이벤트 `join-room`/`leave-room`, 푸시 이벤트 `redis-message`. → redis-monitor+socket.io 둘 다 asst-service 라우트 아래.
  - **channel-agnostic:** relay 는 프론트가 구독한 어떤 redis 채널이든 그대로 중계 → 새 `:call:voc` 도 **프론트 구독만 추가하면 bridge 수정 0으로 자동 흐름.**
  - **⭐ relay 봉투(envelope) 계약:** 프론트 수신형태 `{ message: { message: <백엔드가 publish한 payload>, channel }, timestamp }`. **백엔드는 VOC payload 원본만 `redisService.publish(channel, JSON.stringify(payload))`** — 바깥 봉투(message/channel/timestamp)는 relay 가 자동 부착(channel 도 relay 가 채움). 봉투 직접 생성 불필요. payload(=프론트 `messageData`) 안에 **`turn_idx` 필수 포함.**
  - **채널명:** `{env}:{vendorTenantId}:{agentId}:call:voc`. env 하드코딩 금지(프론트 `VITE_USER_NODE_ENV` dev/prd 일치 필요).
  - **백엔드가 코드베이스서 확인할 것:** `POST /redis-monitor/subscribe/:channel` 핸들러 + `join-room`/`leave-room` 처리하고 redis SUBSCRIBE 메시지를 `redis-message` 로 emit 하는 socket.io 게이트웨이 존재 여부. 있으면 끝(publish만), sibling 서비스가 담당해도 어차피 publish만.
  - **토큰→agent/tenant:** 프론트는 `agentId = agent.cc_cti_id`, `tenantId = company.vendor_tenant_id` 사용. 채널명 `{tenant}`/`{agent}` 자리에 들어가니 백엔드도 동일값으로 publish 해야 매칭.

### 16. 채널 {agent}=cc_cti_id 확인 + payload agent_id 전역필터 함정
- **백엔드 클로드:** 채널 `{agent}` 는 agent_id 아니라 `cc_cti_id`, `{tenant}` 는 `company.vendor_tenant_id`. 백엔드도 동일값 publish 해야 매칭. cc_cti_id 토큰에서 얻을 수 있는지 확인 예정.
- **클로드: 맞음. + 두 번째 함정(silent drop) 발견.**
  - **① 채널명 확인:** `chat/index.vue:1208~1209` — `agentId = (isAdmin/isViewer && props.agentId) || agent?.cc_cti_id`, `tenantId = company?.vendor_tenant_id` → `{env}:{vendor_tenant_id}:{cc_cti_id}:call:...`. 백엔드 말 정확.
  - **② ⚠️ 두 번째 함정 — payload `agent_id` 전역필터:** `useChatMessageParser.ts:119` 에 **모든 redis-message 에 걸리는 전역 필터**(채널 분기 `:127` 보다 먼저). `resolvedAgentId`(=normal 은 `cc_cti_id`, admin/viewer 는 `agentId.value`)를 메시지 payload 의 **`agent_id`(또는 `agentId`) 필드**와 비교 → 불일치면 `return`(조용히 버림). 기존 STT payload 는 `agent_id` 자리에 **cc_cti_id 값**을 담아 보내서 통과(필드명 agent_id, 값은 cc_cti_id 함정).
  - **→ VOC payload 에 `agent_id`(또는 `agentId`) = cc_cti_id 포함 필수.** 빠지면 채널 맞아도 프론트가 안 받음. (프론트 VOC 핸들러를 전역필터 우회하게 별도구성하면 예외이나, 현 패턴 따르면 포함이 안전.) payload 예: `{ agent_id: <cc_cti_id>, turn_idx, emotion, ... }`.
  - **요약:** cc_cti_id 가 **채널명 {agent} + payload agent_id 양쪽** 다 필요 → 토큰에서 한 번 얻어 두 곳에 사용.

### 17. [방향정리] 핑퐁 그만 — 이미 도는 STT 푸시 파이프 복제하면 끝
- **사용자(짜증):** 두 Claude 가 서로 확인만 핑퐁하지 말고 **기존 잘 되던 서비스 활용**해라. 프론트는 코칭요청→관리자 응답 등 이미 구축된 실시간 서비스 있는데 답답.
- **클로드 — 확인 결과:** 코칭은 보내기가 **REST**(`CoachingAPI.createCoaching`)이고 소켓은 상태갱신용 → VOC(서버가 상담사별 실시간 데이터 푸시)에 1:1 본보기는 **코칭 아니라 STT/call:events 흐름**. 결론은 동일 — **이미 도는 거 복제.**
  - **핵심:** STT 자막 푸시가 프로덕션 동작 중 = relay/bridge·env/tenant/agent·구독·payload `agent_id` 필터가 **전부 이미 검증됨**. 두 Claude 가 핑퐁하던 질문(누가 relay 만드나/env 맞추기/cc_cti_id 토큰획득/agent_id 필터)의 답이 **STT 동작 자체로 증명됨.**
  - **백엔드 전달(복붙):** VOC = STT 푸시 복제. STT 현재: `redisService.publish('${env}:${vendorTenantId}:${ccCtiId}:call:nlp:complete', JSON.stringify({ agent_id: ccCtiId, turn_idx, ... }))`. VOC: 채널 suffix `nlp:complete`→`voc`, payload `{ agent_id: ccCtiId, turn_idx, emotion:{...}, ... }`. cc_cti_id 토큰획득? → **STT 발행코드가 이미 그 값으로 publish 중 → 그 방식 그대로.** 봉투는 relay 자동. agent_id(=cc_cti_id)+turn_idx 만 필수. 이상 프론트 확인요청 불필요.
  - **프론트 몫(나중):** STT 배선 방식 그대로 미러링 — `redisKey.ts` 에 `voc` case + 구독배열 추가 + 파서 분기. (때 되면 처리)

### 18. [작업완료] 고객 VOC 감지 실시간 노출 — 5스텝 구현
- **백엔드 적용완료 공유:** 채널 `{env}:{vendor_tenant_id}:{cc_cti_id}:call:voc`, 기존 `POST /redis-monitor/subscribe/{channel}` 구독. payload: `{ agent_id:<cc_cti_id>, call_id, turn_idx, emotion:{type(5종),sentiment_type(4종),score,summary}, complaintRisk:{score,summary}, churnRisk:{score,summary} }`. emotion.type 5종(calm/neutral/angry/sad/happy), risk는 score(0~1).
- **사용자 추가지시:** 감정은 **4종 `sentiment_type`(negative/neutral/positive/etc) 프론트 표준 사용**(type 5종은 참고용). 기존 "고객감정" 화면은 나중에. 작업순서 5스텝 지정.
- **클로드 구현(스텝바이스텝):**
  - **Step1 구독:** `redisKey.ts` `case "voc"` → `...:call:voc`. `chat/index.vue` 구독배열(admin/비admin 양쪽)에 `getRedisKey(...,"voc")` 추가.
  - **타입:** `src/api/types/voc.type.ts` — `VocSentimentType`(4종) + `VocEmotionType`(5종 참고) + `VocEmotion{type,sentiment_type,score,summary}` + `VocRisk{score,summary}` + `VocMessage`.
  - **스토어:** `src/stores/modules/voc.ts` — state `{current, isCallActive}`, getters `averageScore`(3영역 평균)·`isDanger`(>0.8)·`visible`(통화중), actions `setVoc`(교체+isCallActive 방어적 true)·`startCall`(활성+초기화)·`endCall`(비활성+초기화)·`clear`.
  - **파서(`useChatMessageParser.ts`):** import vocStore. 콜 start 시 `vocStore.startCall()`, 콜 end 시 `vocStore.endCall()`, 채널 분기 `else if (channel.includes(":call:voc")) vocStore.setVoc(messageData)`.
  - **Step2·3 UI:** `src/view/advisor/components/voc/CustomerVocPanel.vue` 신규 — 타이틀 "고객 VOC 감지" + 3행(감정[sentiment 4종 라벨 부정/중립/긍정/기타+색점+바], 민원위험, 이탈징후[score≥0.7 시 빨강 하이라이트+⚠위험]) + 종합(평균>0.8 시 빨강 펄스 경고 "대화가 위험 상태로 진입하였으니 상위 관리자 또는 코칭요청을 하세요"). 통화중 데이터 전엔 "감지 대기중" placeholder.
  - **Step2 배선:** `agent/index.vue` 우(3) 영역을 `.adv-right-column`(flex column)로 감싸 `<CustomerVocPanel class="adv-voc-area"/>`(flex:1, min-height:100px, max-height:34%) + `<TabTypeKnowledgeIndex class="adv-knowledge-area"/>`(flex:9). VOC:지식 = 1:9.
  - **Step4 교체:** `setVoc` 가 `current` 통째 교체(누적 X).
  - **Step5 통화중만:** 패널 `v-if="vocStore.visible"`(=isCallActive). 콜 end 시 endCall→숨김. 통화중 진입(start 놓침) 대비 setVoc 에서 isCallActive 방어적 true.
  - **검증:** `tsc --noEmit` VOC 관련 에러 0건(기존 무관 에러 35건만). 시각 확인은 `npm run local` 권장(`npm run dev` 는 .env.development 없어 채널 prefix undefined).
  - **남은 일:** 기존 "고객감정"(emotionVoc.ts 하드코딩) 화면과의 통합/대체는 추후.

### 19. VOC 패널 — local 환경에선 통화 무관 항상 노출
- **사용자:** 새 VOC UI 가 통화중에만 노출되는데, 배포환경이 local 일 때는 무조건 노출되게.
- **클로드:** local 판별은 `LANGSA_GATEWAY_URL` 로 (`.env.local` 만 `http://localhost:8080`, dev/prd 는 etaas 도메인. VITE_USER_NODE_ENV 는 local/dev 둘 다 'dev' 라 구분 불가). `voc.ts` 에 `const IS_LOCAL = (process.env.LANGSA_GATEWAY_URL ?? "").includes("localhost")` 추가, `visible` 게터를 `if (IS_LOCAL) return true; return state.isCallActive` 로 수정. 게터 한 곳만 변경(컴포넌트/파서 무변경). local 은 통화 안 해도 패널 노출(데이터 없으면 "감지 대기중" placeholder), dev/prd 는 기존대로 통화중에만. tsc VOC 에러 0건.

### 20. VOC 패널 타이틀 아이콘 + border-radius 지식저장소와 동일하게
- **사용자:** "고객 VOC 감지" 타이틀 앞에 다른 데처럼 `crop_square` 아이콘 붙이고, border-radius 도 지식저장소와 동일하게.
- **클로드:** 지식저장소(`TabTypeKnowledgeIndex.vue`) 헤더 = `<ECPIcon icon="crop_square" filled color="g60" />` + `<ECPTypography variant="subtitle3" tag="span" color="info">`, root = `<ECPContainer class="adv-page-content">`. `.ecp-container` 는 `border:none`+자체 radius 없음 → 지식저장소는 flush 패널.
  - **수정:** `CustomerVocPanel.vue` root 를 `<ECPContainer class="adv-page-content voc-panel">` 로 교체(동일 셸 상속 → border/radius/padding 1:1 일치), 헤더를 동일 마크업(`.adv-page-content-header` + crop_square + ECPTypography "고객 VOC 감지")으로. 기존 임의 border-radius:8px+border+배경 제거. 3행·종합 UI 유지. ECP 컴포넌트 전역등록(import 불필요). tsc VOC 에러 0건.

### 21. 라이브 테스트 — "감지 대기중" 전환 시점 + 진단 로그 추가
- **사용자:** 실제 전화 테스트. 구독 정상(`dev:4609686:56356659:call:voc → 1명`)인데 ① "감지 대기중" 언제 바뀌나(소켓 데이터 오면?) ② 백엔드가 아직 publish 못함(작업중).
- **클로드 답:**
  - **① "감지 대기중" 전환:** 패널 visible(local 항상/dev·prd 통화중), placeholder 는 `current===null` 일 때. 소켓 VOC 수신 → 전역 agent_id 필터 통과(★payload.agent_id==cc_cti_id) → `:call:voc` 분기 → `vocStore.setVoc` → `current` 채워짐 → 3행 데이터뷰로 전환. 지금은 백엔드 미전송이라 대기중.
  - **② 구독 `→1명` = 프론트 구독 정상(Step1 성공).** 백엔드 publish 대기.
  - **⚠️ 함정 재강조:** 채널 맞아도 payload.agent_id ≠ cc_cti_id(56356659) 면 전역 필터 silent drop → UI 안 바뀜.
  - **진단 로그 2개 추가(`useChatMessageParser.ts`):** ① 필터 drop 시 `[voc-diag] agent_id mismatch drop …`(voc 채널 한정) ② voc 분기 진입 시 `[voc] received — turn=… sentiment=…`. → 콘솔로 "안 옴 / 와도 필터 drop / 정상수신" 즉시 구분.
  - **제안(미적용):** 백엔드 작업 동안 프론트 렌더 독립검증용 local 전용 "테스트 데이터 주입" 버튼 추가 가능 — 사용자 응답 대기.

### 22. 타이틀 오타수정 + "감지 대기중" 텍스트 자체 shimmer
- **경위:** 클로드가 처음에 별도 스켈레톤 블록(3행 미리보기)을 추가했으나, 사용자 의도는 "감지 대기중…" **텍스트(폰트) 자체에 shimmer 가능한지** 물은 것 → 별도 스켈레톤 원치 않음.
- **클로드:** ① 추가했던 스켈레톤 블록/스타일 제거 → 이전 `.voc-panel__waiting` placeholder 복원. ② 타이틀 오타 "고객 VOC 감지" → **"고객 VOC 탐지"**. ③ 헤더 "감지 대기중…"(`.voc-panel__turn--wait`) 에 **텍스트 shimmer** — `background: linear-gradient` + `background-size:200%` + `background-clip:text` + `color:transparent` + `@keyframes voc-text-shimmer`(background-position 좌→우, 1.5s). 글자 모양 그대로 빛이 흐름, 라이브러리 불필요. (질문답: 폰트 자체 shimmer 가능 = background-clip:text 기법)

### 23. 실시간 VOC 소켓 무반응 진단 — 3관문 + chat 구독 성공로그 추가
- **사용자:** 서버에서 `${env}:${tenant}:${agent}:call:voc` 소켓통신 되는데 프론트 반응 없음. 왜?
- **클로드 — 프론트 배선은 전부 정상(코드 누락 아님), 런타임 데이터가 관문에서 걸러지는 문제로 진단.** VOC 한 건이 화면에 뜨려면: `소켓 redis-message 도착 → channel ":call:voc" 포함 → ★전역 agent_id 필터(useChatMessageParser.ts:122) → ":call:voc" 분기(:252) → vocStore.setVoc → 컴포넌트 렌더`.
  - **이미 박힌 진단 로그 2개:** 필터 drop 시 `[voc-diag] agent_id mismatch drop`(:129), 분기 진입 시 `[voc] received`(:254). → 둘 다 안 뜸=안옴 / diag=필터drop / received=정상.
  - **백엔드 "프론트가 구독+join-room만 추가하면 됨(A안)" 주장 → 프론트는 이미 100% 충족.** `useChatSocket.ts:15~40` 가 STT 채널과 동일 루프로 voc 도 REST 구독+joinRoom 처리, 구독배열(`chat/index.vue:1217,1224`)에 admin/비admin 양쪽 `getRedisKey(...,"voc")` 포함.
  - **사용자 콘솔 관찰:** `채널 구독 및 룸 참가 완료: …nlp:complete, …nlp:complete` 는 떴으나 voc 없음. → 이 로그는 **Dashboard.vue:337**(대기화면) 것이고 거긴 구독배열에 voc 없음(events/nlp/db만). voc 구독은 **chat/index.vue(통화화면)** 의 `useChatSocket` 인데 **성공 로그가 없어서**(실패 warn만 있었음) 콘솔로 확인 불가였음.
  - **조치:** `useChatSocket.ts` 구독 성공 시 `console.log("[chat-sub] 채널 구독 및 룸 참가 완료: ${channel}, ${room}")` 추가(실패 warn 도 `[chat-sub]` prefix). → 통화화면에서 voc 구독 여부 콘솔 확정 가능.
  - **전제조건 확인:** `chat/index.vue:1265` 마운트 시 `setupListeners()` → `on("redis-message", parseMessageData)` 등록됨. console.log 안 잘림(`[chat-sub]` 떴으니 증명). 두 로그가 유일한 조기 return(필터) 양쪽에 있어 **voc 도착 시 반드시 둘 중 하나 출력 보장.**

### 24. [확인완료] voc 구독·수신 정상 + 감정 payload에 sentiment_type 누락 발견
- **사용자:** `[chat-sub] …:call:voc …` 정상 출력 확인 → 구독·join OK. 이후 실제 payload 수신: `{ agent_id:"56356659", call_id, turn_idx:5, emotion:{type:"neutral",score:0,summary:"감정 분석을 수행할 수 없습니다."}, complaintRisk:{score:0,summary}, churnRisk:{score:0,summary} }`. "잘 오고 잘 노출됨, 만족."
- **클로드 — 데이터 흐름 완성 확인 + 함정 발견:** 이 payload엔 **`sentiment_type`(4종)이 없고 `type`(5종)만 옴.** 컴포넌트는 `emotion.sentiment_type` 으로 라벨/색 결정(SENTIMENT_META 4종) → 항상 fallback "기타"로 뜨는 상태. (score 0 + "분석 불가" = 백엔드 degraded 응답)
  - **§18 합의 재확인:** 백엔드가 type(5종)+sentiment_type(4종) 둘 다 주기로 했으나 실제론 sentiment_type 미포함. → 프론트 매핑은 정상, 백엔드가 sentiment_type 안 보내는 게 원인.

### 25. [작업완료] VOC 패널 UI 개편 — 3행(감정 색3가지+summary / 민원·이탈 텍스트만)
- **사용자 지시:** 감정은 `sentiment_type`(negative/neutral/positive/etc)만 옴 → 부정적/중립/긍정적/중립 매핑, **etc=neutral 동일 회색**(색상 총 3가지). `emotionVoc.ts` 표시 포맷(`● 라벨: 내용`) 동일하게. 3행: ①감정=`● 라벨(3색): summary` ②민원위험=`민원위험 : summary` ③이탈징후=`이탈징후 : summary`. 막대바·점수·⚠·종합박스 전부 제거.
- **클로드 작업 (`CustomerVocPanel.vue`):**
  - `SENTIMENT_META` 라벨/색 변경: negative=부정적/`#ef4444`, neutral=중립/`#94a3b8`, positive=긍정적/`#22c55e`, **etc=중립/`#94a3b8`**(neutral 동일). fallback 도 `SENTIMENT_META.neutral`.
  - 템플릿 3행으로 단순화(`.voc-line` 한 줄 = (색점)라벨/이름 + `: summary`). 막대바(`voc-bar`)·% 점수(`voc-row__score`)·⚠위험(`voc-row__flag`)·종합(`voc-total`) 마크업/스타일 제거.
  - **함정:** store getter `averageScore`/`isDanger` 는 종합박스에서만 쓰던 것 → 컴포넌트에서 제거되어 dead. (이후 §26 store 개편 때 같이 제거)
  - 검증: tsc VOC 에러 0건. (참고: 이 사이 사용자/린터가 헤더 "감지 대기중…"→"탐지 대기중…" 문구 수정)

### 26. [작업완료] VOC 캐러셀(히스토리) 방식 개편 — 좌우 커서 + 새통화 초기화
- **사용자 아이디어:** 지금은 마지막 1건만 보이고 통화 끝나면 사라짐. **히스토리처럼 좌우 커서로 한 건씩** 순차 탐색하게. 1건뿐이면 커서 없음, 2건↑이면 자동 최신 표시+왼쪽 커서. **새 VOC 오면 무조건 최신으로 강제이동**(상담사 정신없어도 OK). **새 통화 시작 시 초기화**, 통화 끝나도 유지(DB 저장본은 콜이력에서 별도 호출).
- **클로드 작업 (2파일):**
  - **`voc.ts` store 개편:** state `current` 단건 → **`history: VocMessage[]` + `currentIdx`** (+isCallActive). getters: `currentItem`(history[currentIdx]), `total`, `hasPrev`(idx>0), `hasNext`(idx<last), `visible`(IS_LOCAL || isCallActive || **history.length>0** → 통화 종료 후에도 내역 있으면 노출). actions: `setVoc`(push + **currentIdx=last 강제이동** + isCallActive true), `startCall`(history=[],idx=0,active), `endCall`(**active=false만, history 유지**), `prev`/`next`, `clear`. **제거:** `averageScore`/`isDanger`(state.current 참조 → 개편으로 삭제 필요했음).
  - **`CustomerVocPanel.vue`:** `current = vocStore.currentItem`. 헤더 우측 `turn N` 자리에 **좌우 커서 네비**(`.voc-nav`): `hasPrev` 시 `chevron_left`(prev), `현재/전체`(`{{currentIdx+1}} / {{total}}`, tabular-nums), `hasNext` 시 `chevron_right`(next). 1건이면 화살표 둘 다 미노출. ECPIcon 은 클릭용 `<span @click>` 래핑. 화살표 아이콘명은 코드베이스 기존 사용(`chevron_left`/`chevron_right`) 확인 후 채택.
  - 검증: tsc VOC 에러 0건. 파서 호출(setVoc/startCall/endCall) 시그니처 동일 → 파서 무수정.
  - **남은 일:** 사용자 라이브 테스트 예정(여러 번 수신 시 커서 동작 + 위치표기/여백 디테일).

### 27. [작업완료] 기존 하드코딩 감정(VOC) 2화면을 API 연동 — 하드코딩 4개 우선 + API 3행
- **배경:** 통화종료 후 팝업 / 콜이력 상세 두 곳에 하드코딩(`emotionVoc.ts` `EMOTION_BY_CALL_ID` 4개)으로 감정 노출 중이던 걸 API 연동으로 확대. API 응답은 실시간 VOC와 거의 동일 구조: `{ emotion:{type,score,summary}, complaintRisk:{score,summary}, churnRisk:{score,summary} }`. ⚠️ 단 `emotion.type` 이 **곧 4종 값**("negative"…)이고 `sentiment_type` 필드는 없음(실시간은 type 5종+sentiment_type 4종).
- **사용자 요구:** "하드코딩도 살리고 API도 적용". 하드코딩은 특정 4개 콜뿐 → **그 4개는 하드코딩 우선, 나머지는 API**. `summary/data/{id}`(콜이력)도 동일 포맷으로 내려올 예정.
- **데이터 출처 확인:** 팝업=`createSummary`(POST /summary) 응답 라이브 / 콜이력 상세=`getSummaryData`(GET /summary/data/{id}) 저장본. 둘 다 동일 VOC 포맷.
- **클로드 구현 (5파일):**
  - **`emotionVoc.ts`:** `VOC_SENTIMENT_META`(부정적/중립/긍정적, etc=중립 회색 — 실시간과 동일) + `toSentiment`(4종 직통, 5종 방어매핑) + 통일 뷰모델 `VocView{emotion,complaintRisk|null,churnRisk|null,source}` + `VocApiPayload` + **`resolveVocView({callIds,api})`**(하드코딩 4개 우선 → 감정1행 / 그 외 API → 3행). 기존 `EMOTION_BY_CALL_ID`/`resolveEmotionByCallIds` 보존.
  - **`voc/VocDetailBox.vue`(신규):** 공용 표시. 감정 `●라벨(3색): summary` + 민원위험/이탈징후 `이름 : summary`(risk 있을 때만). 팝업·콜이력 공용.
  - **`CounselingStatus.vue`(팝업):** `apiEmotion`(emotion만 보관) → `apiVoc`(응답 전체) 로 교체. `emotionDef` ref 제거 → `vocView` computed(`resolveVocView` callIds=[callId,callStatsId]). 템플릿 감정블록 → `<VocDetailBox :voc="vocView">`.
  - **`ChatHistoryModal.vue`(콜이력):** `emotionDef` computed → `apiVoc` ref + `vocView` computed(callIds=[callStatsId,call_id,id]). 로드 시작 시 `apiVoc=null`, `summaryData` 로드 시 `apiVoc=summaryData`. `CustomerPanel` prop `:emotion` → `:voc`.
  - **`ChatHistoryModal/CustomerPanel.vue`:** prop `emotion:EmotionDef` → `voc:VocView`, 감정 표시블록 → `<VocDetailBox :voc="voc">`. (SummaryPanel 은 주석 유지, 무수정)
  - **동작:** 등록된 4개 콜=하드코딩 유지(데모 보존), 나머지=API 실데이터 3행. 콜이력은 백엔드가 `summary/data` 에 emotion/risk 실어주는 순간 자동 점등.
  - 검증: tsc VOC/감정 관련 에러 0건.

### 28. [작업완료] 실시간 VOC 패널 종합 위험도 박스 복원 (평균 ≥ 0.8 경고)
- **경위:** §18 에 있던 "종합(평균>0.8 빨강 펄스 경고)" 기능이 §25(종합박스 제거 지시)+§26(store 개편 시 `averageScore`/`isDanger` 게터 삭제)으로 사라져 있었음. 사용자가 A안(예전 종합박스) 복원 요청.
- **기준 확정:** 평균 = `(emotion.score + complaintRisk.score + churnRisk.score)/3 ≥ 0.8`. **무조건 마지막 수신 데이터 기준**(캐러셀로 과거를 보고 있어도 최신 기준).
- **클로드 구현:**
  - `voc.ts`: `latestItem`(history 마지막) 게터 + `averageScore`(latestItem 기준) + `isDanger`(≥0.8) 복원.
  - `CustomerVocPanel.vue`: 3행 아래 종합박스 복원 — 위험 시 빨강 펄스+⚠ "대화가 위험 상태로 진입하였으니 상위 관리자 또는 코칭요청을 하세요", 안정 시 "종합 위험도 NN% · 안정". `pct` 헬퍼 + `.voc-total`/`voc-pulse` 스타일 복원.
  - 검증: tsc VOC 에러 0건. **남은 일:** 이상하면 표시 형태 고도화.
- **(추가)** 사용자 피드백 — 존댓말 사용 요청 → `CLAUDE.md` 대화 지시사항 "한국어 존댓말(반말 금지)"로 갱신.

### 29. [분석/문서화] 상담사 화면 지식·문서 검색(RAG) 프로세스 분석 — `docs/advisor-minuee-docs-rag.md` (2026-06-11)
- **목적:** 코드 수정 없이 상담사 화면의 RAG 파이프라인 전체를 분석·문서화. 결과를 신규 파일 `docs/advisor-minuee-docs-rag.md`(11개 섹션)에 누적 저장.
- **분석 핵심:**
  - **프론트엔드 LLM 직접 호출 0** (grep 확인). `query`만 백엔드 `asst-service`에 전달 → SSE 단계별 스트리밍 수신(백엔드 프록시 패턴).
  - **RAG 진입 2경로 (동일 SSE 규약):** ①자동 어시스턴트 `callAssistStream`→`POST /assist-stream`(고객 발화 STT final 시 자동) / ②수동 검색 `callDocumentStream`→`POST /stream`(지식저장소 검색바). 파서 `sse-parser.ts`, `done`/`error`서 종료.
  - **백엔드 RAG 단계 = SSE 이벤트:** `intent`(검색 필요판단·skipped) → `sources`(top-N 후보) → `distilled`(LLM 선별 selected_refs+summary) → `token`(답변 스트림) → `done`(model/token_usage/stages). 타입: `assist-stream.type.ts`.
  - **트리거 지점:** `useChatMessageParser.ts:482` — 고객 발화(isUser)·final 턴만 `handleAssistStream` 호출. partial은 머지 후 1회만.
  - **화면 공존 구조:** STT 버블(`chatContent` v-for)과 RAG 결과가 **같은 `item.id`로 묶여** 버블 아래 인라인 표시(`chat/index.vue:313` `selectedKeywordForBubble[item.id]`). 동시에 부모로 emit(`updateChatDocumentList/SelectedRefs/Summary`, `detailItemClick`) → 우측 지식저장소 패널에도 이중 출력.
  - **ID 체계(혼동 정리):** 실은 3종+이력1 — `callId`(통화1건)/`turn_idx`(서버STT 발화턴)/`bubbleId==messageId`(프론트 `messageIdCounter++` 화면순번)/`callStatsId`(이력). 포함관계 callId→turn_idx→bubbleId→RAG결과. turn_idx=백엔드 저장키(snapshot/VOC), bubbleId=화면 표시키.
  - **지식저장소 패널:** 실사용 컴포넌트는 `TabTypeKnowledgeIndex.vue`(VOC `CustomerVocPanel` 아래, `agent/index.vue:55-67`). 탭 type chat/search. 토글=`ContentCollapse.vue` 재귀 아코디언 + `useKnowledgeContentItems.shouldBeOpen`(RAG 힌트 키워드 일치 섹션만 자동 펼침). 문서연결=`DocumentDetailModal`/`DocOriginalViewerModal`(원본 DOCX/PDF). ⚠️ **`knowledge/index.vue`는 미사용 레거시(import 0)** — 정리 후보.
  - **(혼동 정정) "자주 열람 되는 지식"**: 이건 RAG 아님 — 대시보드(`Dashboard.vue`) 열람수(hit_count) 랭킹 위젯(`DashboardAPI.getPopularDocuments`, REST). 같은 Knowledge 문서 공유라 겹쳐 보였을 뿐. (사용자 정정으로 분석 대상은 지식저장소 패널로 확정)
  - **리스크 메모:** 자동/수동 검색 파라미터 비대칭(top_k/mode 백엔드 기본값 의존), 멀티턴 맥락 직전 2턴만(`extractRecentConversation`), 검색범위 격리(repositoryId/workspaceId 미전달) 백엔드 의존, 가공 로직 중복(인용제거 정규식 등).
- **환경설정:** 별도 문서 레포(`/Users/seongnamnoh/Documents/WorkSpaces/gitlab/minuee_timbel_docs`) 직접 수정용으로 `.claude/settings.local.json`의 `permissions.additionalDirectories`에 경로 영구 등록(다음 세션부터 자동 접근). 작업 대상 폴더는 `…/minuee_timbel_docs/nohsn_docs/asst-web`. 이번 세션 즉시반영(`/add-dir`)은 미완 → 다음 세션에서 진행 예정.

### 30. [작업완료] popular 지식(대시보드) workspace_id를 mock env로 override — 새 서버 409 해소 (2026-06-11)
- **증상:** 새 서버(192.168.101.192, mock 단계) 연동 테스트 중 `GET /aicc/asst-service/proxy/knowledge/dashboard/popular?workspace_id=019d65ea-...` 가 **409 Conflict**. 원인은 앱이 보내는 `workspace_id`가 새 서버에 없는 워크스페이스라서.
- **호출 경로 분석(하드코딩 아님 확인):** `agent/index.vue:477` `getPopularDocuments(workspaceId,10)` ← `loadPopularDocs`의 `workspaceId = assignedWorkspaceId.value`(469) ← computed `assignedWorkspaceId`(183). 일반 상담사일 때 `userProfileStore.agent?.assigned_workspace_id`(205), 관리자/뷰어면 `userListStore.agents`에서 찾은 대상의 `assigned_workspace_id`. 즉 **로그인 계정 프로필의 `assigned_workspace_id`(`019d65ea-...`)가 그대로 전달**되던 것.
- **문서 근거:** 개발담당자 문서 `docs/callbot_advisor_api.md` §9.2 — 새 서버 mock workspace_id = `019bfe5d-d00f-74c9-b6f6-416a9bfa1dc6`, "하드코딩 금지 → 설정값"으로 명시.
- **사용자 결정:** `.env.local`에 `VITE_MOCK_WORKSPACE_ID=019bfe5d-...` 추가 후, "이 항목이 있을 때만" override 적용 요청.
- **클로드 구현 (1파일):** `agent/index.vue` `assignedWorkspaceId` computed **맨 앞**에 가드 추가 — `const mockWorkspaceId = process.env.VITE_MOCK_WORKSPACE_ID; if (mockWorkspaceId) return mockWorkspaceId;`. (env 접근은 이 프로젝트 관행대로 `process.env.VITE_*` 사용 — `apiPlugin.ts`/`AdvisorbotClient.ts` 등과 동일. 타입선언 불필요 확인.)
- **동작:** `.env.local`에 항목 있으면 무조건 그 값 사용(mock 검증) / 항목 지우면 기존 프로필 `assigned_workspace_id` 자동 복귀(운영 무영향). ⚠️ `process.env`는 빌드타임 주입이라 **dev 서버 재시작 필요**.
- **검증:** 사용자 재시작 후 재호출 → `workspace_id=019bfe5d-...&limit=10` **200 OK**, "자주 열람 되는 지식" 화면 정상 표시 확인.

### 31. [작업완료] `/stream`(문서검색 RAG) 요청에 `workspace_id`(snake) 추가 + mock override 일원화 (2026-06-11)
- **배경:** 백엔드 서비스 교체로 `POST /aicc/asst-service/stream` 도 popular처럼 `workspace_id`가 필요해짐. 기존엔 body가 `{"query":"적금"}`만 전송됨. 사용자 확정: **키는 snake `workspace_id`로 통일**(백엔드도 snake로 수신).
- **호출 구조 분석:** `document-search.api.ts:32` `body: JSON.stringify(req)`(req=`DocumentSearchReq`) — 객체 그대로 전송이라 **필드만 추가하면 됨**. 호출부 2곳:
  - ① 지식저장소 검색바 `useKnowledgeSearch.ts:82`(실사용 `TabTypeKnowledgeIndex.vue`) — **이미 `getAssignedWorkspaceId()`로 workspaceId 보유**(라인45 검증까지)하나 body엔 미포함이었음. 출처 체인: props.assignedWorkspaceId ← `agent/index.vue` computed(=mock override 적용된 그것).
  - ② 콜이력 모달 키워드 클릭 `useKeywordDetail.ts:47` — workspace 접근 없던 composable(인자 0). threading 필요.
- **클로드 구현 (6파일):**
  - **`src/utils/workspace.ts`(신규):** mock override 단일 소스화 — `getWorkspaceIdOverride()`(`process.env.VITE_MOCK_WORKSPACE_ID || undefined`) + `resolveWorkspaceId(base)`(override || base || "").
  - **`ce.type.ts`:** `DocumentSearchReq`에 `workspace_id?: string` 추가.
  - **`agent/index.vue`:** §30에서 넣은 인라인 `process.env.VITE_MOCK_WORKSPACE_ID` 읽기 → `getWorkspaceIdOverride()` 호출로 일원화(동작 동일). import 추가.
  - **`useKnowledgeSearch.ts`:** `callDocumentStream({ query, workspace_id: workspaceId }, …)` — 이미 보유값 그대로.
  - **`useKeywordDetail.ts`:** 시그니처 `useKeywordDetail(getWorkspaceId?: () => string|undefined)` + body `workspace_id: getWorkspaceId?.()`.
  - **`ChatHistoryModal.vue`:** `useUserProfileStore` import+인스턴스 추가, `useKeywordDetail(() => resolveWorkspaceId(userProfileStore.agent?.assigned_workspace_id))` 주입.
- **동작:** `/stream` 두 경로 모두 `{"query":...,"workspace_id":...}` 전송. mock override 자동 반영(popular와 동일 소스 `workspace.ts`) → `.env.local`에 `VITE_MOCK_WORKSPACE_ID` 있으면 `019bfe5d-...`, 지우면 프로필 값 복귀.
- **검증:** vue-tsc 관련 파일 에러 0건. ⚠️ `process.env` 빌드타임 주입 → dev 재시작 후 네트워크 payload 확인 필요(사용자 라이브 테스트 예정). 참고: 자동 어시스턴트 `/assist-stream`도 구조 동일해 동일 방식 확장 가능(이번 범위 외).

### 32. [작업완료] 지식저장소 검색결과 패널 — AI답변(요약) vs 문서목록 세로비율 개선 (B안) (2026-06-11)
- **증상:** 상담화면 우측 지식저장소(`TabTypeKnowledgeIndex.vue`)에서 검색바로 §31 `/stream` 호출 시, 위=AI답변(요약)/아래=문서목록으로 나뉘는데 **요약이 길면 문서목록이 쪼그라들어** 스크롤이 자잘하게 생겨 보기 불편. (사용자는 VOC min-height 190px을 의심했으나 실제 원인 아님 — 외곽은 VOC:지식 = flex 1:9 라 영향 작음.)
- **원인:** 검색탭 컨텐츠(`:104` AI답변 박스 `search-summary-section`)에 **`flex-shrink-0`** 가 걸려 내용만큼 무한정 세로로 커짐(스크롤 없음) → 아래 문서목록(`flex-1 min-h-0 overflow-y-auto`)이 남는 공간만 차지해 좁아짐.
- **선택지 제시 → 사용자 결정:** A(정확히 1:1 고정) vs **B(요약 최대 ~45%, 평소엔 내용만큼·문서목록 우선)**. 사용자: **B로 먼저, 안되면 A**. → B 적용, 결과 만족.
- **클로드 구현 (`TabTypeKnowledgeIndex.vue` 1파일):**
  - 템플릿(`:106`): `search-summary-section` 클래스에서 **`flex-shrink-0` 제거**.
  - 스코프 스타일 신규: `.search-summary-section { flex:0 1 auto; max-height:45%; min-height:0; overflow-y:auto; }`.
  - 결과: 답변 짧으면 요약 작게+문서목록 넓게 / 답변 길면 요약 45%에서 멈추고 자체 스크롤+문서목록 55% 자체 스크롤. **상·하 독립 스크롤**, 문서영역 안 쪼그라듦.
- **검증:** vue-tsc 에러 0건. 사용자 라이브 확인 "훌륭, 맘에 듦". **폴백 메모:** 45% 과하면 숫자↓(40/35%), 퍼센트 높이 미해석 시 A안(요약 `flex:1 1 0`)으로 전환.

### 33. [작업완료] 원본 문서 뷰어 — PDF 인라인 표시(pdf.js) + 포맷별 분기(DOCX/다운로드) (2026-06-11)
- **증상:** 지식저장소 원본보기(`DocOriginalViewerModal.vue`)에서 PDF 문서가 "문서를 불러오지 못했습니다" 에러. API(`GET /aicc/asst-service/documents/{id}/original`)는 **200 정상**.
- **진단(프론트 문제 확정):** curl 실측 — 응답 매직바이트 `25 50 44 46`=**`%PDF-1.4`**(PDF), `Content-Type: application/octet-stream`(파일종류 메타 없음, Content-Disposition도 없음). 그런데 컴포넌트가 파일종류 무관하게 **무조건 `convertDocx()`(mammoth=DOCX전용)** 실행 → PDF에서 throw → catch 에러. (API 정상, 프론트가 PDF를 DOCX변환기로 처리하던 것.)
- **1차 시도(A안, iframe) → 폐기:** PDF를 `Blob({type:'application/pdf'})` + `<iframe>` 네이티브 뷰어로. 그러나 사용자 환경 브라우저가 iframe 내 PDF 인라인 뷰어 부재 → "PDF아이콘+파일ID+열기버튼" 다운로드 fallback만 뜨고 다운로드됨. **사용자: 원복 후 바로보기 제대로**. → `git checkout`으로 mammoth-only 원복.
- **포맷 다양성 확인(사용자 협의):** PDF만 있는 게 아님(docx 등). mammoth=docx전용/pdf.js=pdf전용 → 둘 합쳐도 PDF+DOCX만 인라인. zip계열(docx/xlsx/pptx) 매직바이트 동일(`PK`)이라 겉구분 불가. **확정 전략:** PDF→pdf.js 인라인 / DOCX→mammoth 인라인 / **그 외→바로 다운로드**.
- **2차(B안, pdf.js) 구현 — 채택:**
  - **설치:** `pdfjs-dist@3.11.174` (`--legacy-peer-deps` — 기존 tiptap peer 충돌 우회, pdf와 무관). webpack5 호환 위해 3.x legacy build 선택.
  - **`DocOriginalViewerModal.vue` 전면 재작성:**
    - `detectKind(bytes)`: `%PDF`→pdf / `PK`→zip / 그외→other.
    - **PDF:** `getPdfjs()`(동적 import `pdfjs-dist/legacy/build/pdf` + worker 설정) → `getDocument({data})` → 페이지별 `<canvas>` 생성·세로 스택. 폭=컨테이너 맞춤, 해상도=`devicePixelRatio` 반영(선명).
    - **worker:** 사내 폐쇄망 고려 CDN 대신 **로컬 번들** `GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/legacy/build/pdf.worker.min.js", import.meta.url)`(webpack5 asset URL).
    - **zip:** `convertDocx` 시도→성공 HTML 인라인+기존 `focusActiveContent` 하이라이트 / 빈결과·throw시 다운로드 fallback.
    - **other/docx실패:** `triggerDownload()` — Blob+`a.download`(`원본문서_{id}{확장자추정}`) 자동 다운로드 + 모달 "미리보기 미지원, 다운로드됨" 안내+[다시 다운로드] 버튼. `guessExt`는 best-effort(jpg/png/OLE).
    - docKind ref(`''|'html'|'pdf'|'download'`)로 템플릿 분기. DOCX HTML만 캐시(PDF·다운로드 제외). pdf.js도 mammoth처럼 동적 import(첫 PDF시 로드).
  - 검증: vue-tsc 에러 0건. pdfjs export(getDocument/GlobalWorkerOptions/v3.11.174)·worker파일(1.1MB) 확인. **사용자 라이브 확인 "아주 훌륭, PDF 바로 보임".**
- **참고:** ① 백엔드가 `Content-Disposition: filename="…"` 주면 매직바이트 추정 없이 확장자 분기 가능(다운로드 파일명도 정확) — 개선 여지. ② PDF는 네이티브 뷰어가 아니라 canvas라 `activeContent` 자동 스크롤·하이라이트는 미적용(DOCX만). 필요시 pdf.js text layer로 고도화 가능. ③ worker 로딩 백업안: copy-webpack-plugin 복사 / asset·Blob URL import.

### 34. [작업완료] 192 개발기 직결 — 게이트웨이 제거(asst-service 직접 호출) + Docker(.env.dev/docker-compose.dev.yml) (2026-06-11)
- **목표:** 배포시스템 없이 192 개발기에 git clone → Docker 로 직접 실행. 192엔 API Gateway 미설치 → 프론트가 **asst-service 백엔드(`http://192.168.101.192:32025`)로 직접** 호출하도록 전환.
- **라우팅 구조 분석:**
  - 프론트 백엔드 호출은 axios 3클라이언트(advisor/auth/audio)지만 **API 32개 전부 `super("advisor")`** + knowledge/ce/qa 도 advisor 의 `/proxy/...` 경유 → **실사용 클라이언트는 advisor + socket.io 둘뿐**. (`getAuthApi`/audio/CCAAS websocket 은 정의만 있고 호출처 없음 = 미사용.)
  - advisor baseURL = `LANGSA_GATEWAY_URL`, 호출경로 = `path.ADVISOR.API_PREFIX(=ASST_API_PREFIX)` + endpoint. 소켓 = `LANGSA_GATEWAY_URL` + `API_PREFIX/socket.io`.
  - **게이트웨이 동작:** `/aicc/asst-service/*` 받아서 StripPrefix=2 → PrefixPath=`/api/asst/v1` 로 리라이트해 백엔드 전달. 백엔드는 `setGlobalPrefix('/api/asst/v1')`(main.ts:88)이라 **`/api/asst/v1/...` 만 받음**.
  - 그래서 직결 시 prefix를 `/aicc/asst-service` → **`/api/asst/v1`** 로 바꿔야 함(안 바꾸면 404). 사용자 검증: `curl localhost:32025/api/asst/v1/health/check`=200, swagger=`/api/asst/v1/doc`.
- **수정 ①  `.env.dev`(2줄):** `LANGSA_GATEWAY_URL = http://192.168.101.192:32025`, `ASST_API_PREFIX = /api/asst/v1`. → REST·소켓·프록시(`/proxy/knowledge`·`/proxy/ce`·`/proxy/qa`) 전부 `http://192.168.101.192:32025/api/asst/v1/...` 로 자동 정렬.
- **수정 ② `docker-compose.dev.yml`:** Dockerfile.dev 의 CMD(`MODE=development`→없는 `.env.development`, 포트 32082)를 compose `command` 로 덮어씀 → `MODE=dev`(→`.env.dev`), `--host 0.0.0.0 --port 32026 --allowed-hosts all`. ports `32026:32026`, container `asst-web-dev`. (Dockerfile.dev 원본 미수정.) ※포트 처음 32025로 잡았다 백엔드와 겹쳐 32026으로 정정(사용자 오타).
- **검증한 함정:**
  - webpack 은 `.env.${MODE}` **단일 파일만** 로드(베이스 `.env` 병합 안 함). Dockerfile.dev=MODE=development, Dockerfile=build:aws=MODE=aws **둘 다 해당 env파일 없음** → 그대로 띄우면 env 비어 깨짐. 그래서 MODE=dev 로 맞춤.
  - `host_app/router` 동적 import(`routers/index.ts:12 loadHostRoutes`) 있지만 **호출처 없는 죽은 코드** → `HOST_APP_URL` 미설정 무해.
  - webpack-dev-server **v5.2.2** → `--allowed-hosts all` 정상(IP 접속 "Invalid Host header" 방지).
- **미해결/주의(사용자 판단 필요):**
  - ① ~~포트 32025 중복~~ → 32026 으로 정정해 해소(백엔드 32025와 안 겹침).
  - ② **인증토큰**: `.env.dev` 엔 `VITE_ACCESS_TOKEN` 폴백 없음 → 단독 실행 시 `accessToken` 쿠키 의존. 192 직접 IP 접속이면 쿠키 도메인 불일치로 401 가능 → 테스트용이면 `.env.local` 처럼 `VITE_ACCESS_TOKEN` 추가 고려.
  - ③ **CORS**: 백엔드 asst-service 가 프론트 origin 허용해야 함(사용자 인지함, dev라 전체허용일 수 있음).

#### 34-추가. Docker 빌드 실전 트러블슈팅 (2026-06-11, 192 개발기 `aicc-dev:~/workspace/aicc-web`)
- **node 24 / npm 전환:** 사용자 요청으로 `Dockerfile.dev` `FROM node:20→node:24`. yarn `Resolving packages...` 무한대기 = **yarn.lock 없고 `package-lock.json`(npm락)만 존재** → yarn이 락 못 쓰고 전부 resolve. **`RUN yarn install` → `RUN npm ci`** 로 전환(백엔드도 npm).
- **compose:** `version` 줄 삭제(obsolete 경고), `build.network: host`(빌드 컨테이너가 호스트 DNS/프록시 사용 → registry 접속 실패 방지), 포트 32026, `command`로 `MODE=dev`+`--allowed-hosts all` 덮어씀.
- **함정 ①(시간낭비):** 파일 고쳐도 빌드가 계속 `node:20`+`yarn install` → **서버가 잘못된 git 브랜치** 체크아웃 상태였음(파일이 안 바뀐 게 아니라 딴 브랜치 봄). 브랜치 정정 후 해결. ※로컬 수정분은 git 무관하게 서버에 반영되는 구조(사용자가 직접 관리, "깃 신경쓰지 말라").
- **함정 ②:** `npm ci` → **ERESOLVE**: `@tiptap/core@3.x` vs `@tiptap/extension-document@^2.14.0`(peer `@tiptap/core@^2.7.0`) **tiptap v2/v3 혼용 충돌**. lock 자체가 `--legacy-peer-deps`로 생성됨(#33 pdfjs 설치 때와 동일) → **`RUN npm ci --legacy-peer-deps`** 로 해결.
- **상태(미검증, 내일):** 위 수정 후 재빌드 미실행. `build --no-cache` → `up -d` → `webpack compiled successfully` → `http://192.168.101.192:32026` 접속 확인 남음.
- **접속 후 잠재이슈 3:** ①API 401=토큰(`.env.dev`에 `VITE_ACCESS_TOKEN` 폴백 없음, 단독실행시 추가) ②CORS=백엔드에 `http://192.168.101.192:32026` origin 허용 ③404=경로 `/api/asst/v1/...` 확인.

#### 34-추가2. 배포 후 런타임 이슈 3종 해결 (2026-06-12)
- **① `/undefined/remoteEntry.js` 404 (Module Federation):** webpack `remotes: { host_app: "host_app@"+process.env.HOST_APP_URL+"/remoteEntry.js" }` 인데 `.env.dev`에 `HOST_APP_URL` 없어서 `undefined` 박힘. `loadHostRoutes`(routers/index.ts:12, host_app/router import)는 **호출처 없는 죽은 코드**, 메뉴/라우팅은 API(`initDynamicRouter`)로 받음 → host_app 실제 불필요. **`.env.dev`에 `HOST_APP_URL = http://192.168.101.192:32026`(자기주소, 단독실행) 추가** → 200 받아 404 해소. (host 포털 별도 배포 시 그 주소로 교체.) ※webpack이 시작 시 1회만 `.env.dev` 읽으므로 컨테이너 **재시작** 필요.
- **② 강제 로그인 토큰:** host 포털 쿠키 없이 단독 실행 → `apiPlugin.getCurrentAccessToken`이 쿠키 없으면 `process.env.VITE_ACCESS_TOKEN` 폴백. `.env.dev`에 **`VITE_ACCESS_TOKEN`(.env.local 35행, exp 2083 사실상 무기한) + `VITE_MOCK_WORKSPACE_ID`** 추가. (`VITE_ACCESS_TOKEN2`/`ADVISOR_API_BASE`/`VITE_AUDIO_SERVICE_API_URL`는 src 미사용 → 생략.) 토큰은 RS256 서명 → 192 백엔드가 같은 키 신뢰해야 통과(통과 확인됨).
- **③ CORS:** 프론트(32026)→백엔드(32025) cross-origin. `Authorization`+`X-Auth-token` 커스텀 헤더라 프리플라이트(OPTIONS) 탐 → "Authorization 안 감"은 사실 OPTIONS(스펙상 미포함)였고 본 요청은 CORS로 차단된 것. **192 백엔드 asst-service `enableCors`로 해결**(origin 32026 + Authorization/X-Auth-token 허용). → **192 get_user 정상.**
- **로컬(localhost:8173→8080) CORS 중복(미해결, 백엔드 A안 진행중):** `Access-Control-Allow-Origin: http://localhost:8173, http://localhost:8173` **값 2개** → 차단. 원인=**게이트웨이(8080)+asst-service 이중 CORS**. 192는 게이트웨이 없어 단일 소스라 정상. **해결: CORS를 한 곳만**(게이트웨이 뒤 asst-service enableCors 끄기 등) — 백엔드 수정 예정. (대안 B: webpack devServer `/aicc`→8080 프록시로 same-origin 우회, 192엔 영향 없음 — 미적용.) 증상 디버깅: axios `ERR_NETWORK`/`Network Error`인데 네트워크탭 200 = 서버는 응답했으나 브라우저가 CORS로 JS 읽기 차단.
- **상태:** 192 개발기 = get_user 포함 정상 동작 ✅. 로컬 = 백엔드 CORS 중복만 해결하면 됨.

#### 35. 지식저장소 검색 한글 IME 엔터 중복 호출 수정 (2026-06-15)
- **증상:** `TabTypeKnowledgeIndex.vue` 지식저장소 검색바에서 **한글 검색어** 입력 후 엔터 1회 → 탭 2개 생성 + `POST /stream` 2번 발사. (영문은 정상 1회 → 한글 IME 확정)
- **원인:** `handleSearch` 1회 = `searchSessions.push`(탭+1) + `callDocumentStream`(fetch POST 1) (`useKnowledgeSearch.ts:72`, `document-search.api.ts:29`). 한글 조합(IME) 중 엔터로 `@keyup.enter` 가 2번 발화 → 핸들러 2번 실행. in-flight 중복 가드도 없음.
- **수정(`TabTypeKnowledgeIndex.vue`):** ElAutocomplete `@keyup.enter="handleSearch"` → **`@keydown.enter="handleSearchEnter"`**. 가드 함수 추가: `if (e.isComposing || e.keyCode === 229) return; handleSearch();` (조합 확정용 엔터 무시, keyup 대신 keydown 써야 isComposing 플래그가 살아있음). 돋보기 버튼 `@click="handleSearch"` 는 유지(클릭은 IME 무관).

#### 36. assist-stream 422 `workspace_id` 누락 수정 (2026-06-15)
- **증상:** `/assist-stream` 호출 시 RAG(AICM, FastAPI) 422 — `{loc:[body,workspace_id], msg:"Field required"}`. 업스트림이 받은 body는 `query`/`enable_distill:false`/`conversation_history(role/content)` 뿐(workspace_id 없음).
- **흐름 재확인:** 프론트(camelCase) → 게이트웨이 asst-service `AssistStreamService.buildUpstreamPayload`가 snake 변환(`conversationHistory`→`conversation_history`, `customer/agent`→`user/assistant`, `enable_distill:false` 고정) → `${AICM_HOST}/api/aicm/v1/search/rag_assist`. 422는 **RAG가 던진 것**.
- **원인:** AICM rag_assist가 `workspace_id`를 **필수**로 요구하게 바뀜. 게이트웨이 DTO(`assist-stream-request.dto.ts:65-72`)·서비스(`assist-stream.service.ts:51`)는 이미 `dto.workspace_id`를 snake 그대로 받아 forward하도록 준비돼 있었으나, **프론트가 workspace_id를 안 보냄** → undefined → 페이로드에서 빠져 422.
- **수정(순수 프론트, asst-web):**
  - `api/types/assist-stream.type.ts` `AssistStreamReq`에 `workspace_id?: string` 추가(주석: 게이트웨이가 snake 그대로 forward하므로 키명 반드시 snake_case).
  - `useChatAssist.ts` callAssistStream 호출에 `workspace_id: resolveWorkspaceId(userProfileStore.agent?.assigned_workspace_id) || undefined` 추가 + `@/utils/workspace`의 `resolveWorkspaceId` import. (ChatHistoryModal:309와 동일 패턴 — `VITE_MOCK_WORKSPACE_ID` override 우선, 없으면 프로필 assigned_workspace_id.)
- **주의:** 이 필드만 유독 snake_case(`workspace_id`)다. 나머지 요청 필드(conversationHistory/callId/turnIdx/company)는 camelCase로 보내고 게이트웨이가 변환. workspace_id는 게이트웨이가 변환 안 하고 통과시키므로 프론트가 처음부터 snake로 줘야 함.

#### 37. 상담화면 지식저장소 탭 늘어날 때 좌측 상담내용 폭 줄어드는 버그 (2026-06-16)
- **증상:** advisor 상담화면(좌: 상담내용 / 우: VOC+지식저장소). 지식저장소 탭이 쌓이면 탭 영역 안에서 가로 스크롤이 생겨야 하는데, 대신 **좌측 상담내용 컬럼이 쪼그라듦**.
- **원인:** `src/styles/global.scss:547` `.adv-page-layout { grid-template-columns: 1fr 2fr }`. CSS grid의 `1fr`은 `minmax(auto, 1fr)`이라 트랙 최소값=콘텐츠 min-content. 지식저장소 탭(`TabTypeKnowledgeIndex`)은 탭이 `flex-shrink:0`+`white-space:nowrap`라 탭이 쌓이면 우측 컬럼 min-content 폭이 커지고 → grid가 우측 트랙을 강제로 넓혀 좌측 `1fr`이 자기 min-content까지 줄어듦. `.el-tabs__nav-scroll`의 `overflow-x:auto`가 있어도 컨테이너가 콘텐츠에 맞춰 늘어나니 스크롤 안 걸림.
- **수정:** `grid-template-columns: minmax(0, 1fr) minmax(0, 2fr)` (트랙 최소값 0 고정). 비율 1:2 유지되고 탭은 의도대로 탭 영역 안 가로 스크롤. admin은 `.adv-admin-page-grid`(scoped, `382px 1fr`)로 자기 컬럼을 항상 덮어써서 영향 없음(agent 화면만 적용).

#### 38. local5f 스크립트 + .env.5f.local 추가 (2026-06-16)
- **목적:** 로컬에서 5f 백엔드(`http://124.194.32.36:32025`)로 붙는 dev 서버 실행.
- **메커니즘:** `webpack.config.js:14` `dotenv.config({ path: \`.env.${process.env.MODE}\` })` → MODE 값이 곧 env 파일 접미사. (webpack에서 MODE 다른 분기 없음, env 경로용으로만 씀.)
- **package.json:** `"local5f": "cross-env MODE=5f.local webpack serve --config webpack.config.js"` 추가. (처음엔 `MODE=5f.dev`로 했다가 사용자가 로컬용 별도 파일 원해 `5f.local`로 변경.)
- **함정:** MODE를 `5f.local`로 바꿨는데 `.env.5f.local` 파일이 없으면 env가 통째로 빈 객체 → `HOST_APP_URL`/`LANGSA_GATEWAY_URL` 등 전부 undefined → localhost:8173 앱 깨짐. **MODE 접미사와 .env 파일명이 정확히 일치해야 함.**
- **`.env.5f.local`(사용자가 생성, B안):** `.env.5f.dev` 베이스 + 로컬 친화로 `HOST_APP_URL = http://localhost:8173` (원격 124.x 대신 자기주소). 백엔드는 5f 그대로. CORS는 별도로 백엔드에서 해결함.

#### 39. 상담사 본인 화면 agent-status 실시간 수신 누락 수정 (2026-06-16)
- **증상(백엔드 제보):** 서버는 상담사 상태 변경 시 `agent-status` 룸으로 정상 emit하는데 **상담사 본인 클라이언트가 룸 join을 안 해서** 못 받음. (coaching/notices는 join돼 있어 정상.)
- **원인:** 이 소켓 서버는 자동 join이 아니라 클라가 `join-room` 이벤트를 직접 보내야 입장. `agent/index.vue`는 `setNoticesListener`/`setCoachingMessageListener`만 있고 agent-status는 빠짐. (admin/index.vue는 이미 `setupAgentStatusListener`로 join+listen 함.)
- **수정(`src/view/advisor/agent/index.vue`):**
  - socket import에 `off`, `leaveRoom` 추가.
  - `setupAgentStatusListener()` 추가 — admin 패턴 그대로. `joinRoom("agent-status","join-room")` + `on("agent-status-update", onAgentStatusUpdate)`. socket.connected면 즉시, 아니면 `on("connect", ...)` 안에서(재연결 시 룸 멤버십 날아가므로 connect 콜백에 둠).
  - `onAgentStatusUpdate(data)` — **본인 cc_cti_id 일치할 때만** `agentStatusStore.setStatus(data.status)`로 자기 상태 갱신(admin은 전체 목록 갱신이지만 본인 화면은 자기 것만).
  - `bootstrapAgentPage`에서 `setupAgentStatusListener()` 호출, `onUnmounted`에서 `off("agent-status-update", onAgentStatusUpdate)`+`leaveRoom("agent-status")` 정리(connected일 때만).
- **이벤트/룸명:** 룸 `agent-status`, 이벤트 `agent-status-update` (백엔드 `agent-status-socket.handler.ts:27,53`). 프론트도 동일 사용 — 불일치 없음.

#### 40. 상담요약 팝업 트리거(orchestrator:persisted) 미수신 → 채널/필터 진단 (2026-06-16)
- **증상:** 상담 종료 시 상담요약 팝업이 안 뜸. 다른 건(상담사 상태 후처리 전환, 할일 등록 버튼) 다 노출.
- **팝업 트리거 체인:** redis `...:call:orchestrator:persisted` 수신 → `useChatMessageParser.ts:498` 분기 → `emit("orchestrator-persisted")` → chat/index.vue 재emit → `agent/index.vue:handleOrchestratorPersisted` → `contentLayoutRef.openCounselingStatusAndExecuteSummary()` (ContentLayout→HeaderActionBar). 채널키는 `redisKey.ts` "db" case = `${VITE_USER_NODE_ENV}:${tenantId}:${cc_cti_id}:call:orchestrator:persisted`, 구독은 `chat/index.vue:1216,1223`.
- **1순위 원인(필터 silent drop):** `useChatMessageParser.ts:117~132` agent_id 관문 — `resolvedAgentId(=cc_cti_id) !== messageData.agent_id` 면 `return`. nlp/voc만 진단로그 있고 **db채널은 로그조차 없어 "이유 모르게 안 됨"**. orchestrator payload의 agent_id가 긴 형식(`agent_xxx`)이면 cc_cti_id(`56356659`)와 불일치로 버려짐.
- **2순위 원인(채널 문자열 불일치):** 구독 채널의 `${AGENT_ID}` 자리 = cc_cti_id. 백엔드가 publish 채널의 `${AGENT_ID}`에 긴 agent_id를 넣으면 채널 자체가 달라 영영 못 받음. (env prefix `dev`·tenant_id·뒷부분 `:call:orchestrator:persisted`는 일치 확인.)
- **해결:** 백엔드(테스트환경)에서 orchestrator:persisted 채널/형식을 nlp/events/voc와 동일하게(cc_cti_id·동일 tenant) 맞춰줌 → **팝업 정상 노출**. (프론트 수정 없이 백엔드 정렬로 해결.)

#### 41. 팝업 떴으나 "상담한 콜이 없습니다" + 요약버튼 비활성 → callstats_id 누락 (2026-06-16)
- **버튼 활성 게이트(단일):** `CounselingStatus.vue:255~264` `watch(callSummaryInfoStore.callStatsId)` → 값 있으면 `isAvailableSummary=true`. 버튼 `:disabled="isLoading || !isAvailableSummary"`(:38). 즉 **`callStatsId` 비면 무조건 비활성**.
- **callStatsId 출처:** orchestrator:persisted 처리 `useChatMessageParser.ts:501` `setCallStatsId(messageData.callstats_id)`. → **persisted payload에 `callstats_id`(snake) 없거나 빈값이면 버튼 막힘.**
- **"상담한 콜이 없습니다" 문구:** `isInit` 기준(`callSummaryInfo` store 기본 `isInit:true`). 콜 시작(events:start)에서 `setIsInit(false)` 되는데, 이 문구가 떴다 = **events:start 라이프사이클 없이 persisted만 단독 발화**(테스트환경). 실제 콜이면 "콜 집계 중...". 부가 증상일 뿐 버튼 막는 본질은 callstats_id.
- **조치(백엔드):** persisted payload에 `callstats_id` 실제값 + `call_id`(또는 `callId`) 채워달라 요청. 그 값이 `/summary` API의 `callstats_id`로 쓰임. (프론트 수정 아님 — 백엔드 대기.)

#### 42. 로컬-개발 환경 매트릭스 정리 (REST vs 소켓 분리 주의) (2026-06-16)
- **`.env.5f.local` 현황:** REST=`LANGSA_GATEWAY_URL=http://124.194.32.36:32025`(5f 원격), `VITE_USER_NODE_ENV=dev`(redis prefix `dev:`), `HOST_APP_URL=http://localhost:8173`, 토큰/workspace override 포함. 프론트는 localhost:8173.
- **핵심 함정:** 한 화면이 **REST(axios=LANGSA_GATEWAY_URL)** 와 **실시간 소켓(Socket.IO)** 두 갈래로 백엔드에 붙음. 상담요약팝업/상담내용/agent-status/VOC = 전부 **소켓(redis-message)**, 요약버튼→/summary = **REST**. → `LANGSA_GATEWAY_URL`만 바꾸면 **REST만 로컬·소켓은 원격**인 반쪽 상태 위험.
- **localhost:3000 풀로컬 전환 시 체크:** ①REST=localhost:3000 ②**소켓이 보는 env도** localhost:3000(미확인 — 확인 필요) ③로컬 백엔드 `setGlobalPrefix('/api/asst/v1')` ④CORS origin `localhost:8173` 허용 ⑤`VITE_ACCESS_TOKEN`(RS256) 같은 키로 검증해야 401 안 남 ⑥redis `dev:`+동일 tenant/cc_cti_id publish.
- **권장:** REST·소켓·redis 전부 **한 서버로 통일**. 반반(REST 로컬+소켓 원격)이 디버깅 최악. (소켓 baseUrl이 어느 env인지 확인은 보류 상태 — 사용자 대기 요청.)

#### 43. /assist-stream 실시간 호출 조건 정리 (2026-06-16)
- **유일 진입점:** `useChatMessageParser.ts:479` (`nlp:complete` 분기 내부) → `handleAssistStream`(useChatAssist.ts:216) → `callAssistStream`(`/assist-stream`).
- **발화 조건(전부 AND):**
  1. 채널 = **`nlp:complete`** (`:323`). partial/stt:final/events/voc는 안 나감.
  2. **agent_id 필터 통과**(`:122`) — payload.agent_id == cc_cti_id (안 맞으면 상단에서 silent drop).
  3. **`isUser`**(`messageData.speaker === "customer"`, :360,:479) — **고객 발화만**. 상담사 발화 제외.
  4. **`isFinalEnding`**(`(turn?.ending ?? "final") === "final"`, :478) — turn이 **final**일 때만. 미완(incomplete)·interjection·partial은 보류했다가 **final로 마무리되는 순간 합쳐진 텍스트로 1회** 호출.
- **호출돼도 결과 없을 수 있음:** 백엔드 응답 `intent.skipped=true`(잡담/일상대화)면 이후 이벤트 전부 무시(`useChatAssist.ts:262~269`) → 화면 변화 없음.
- **결론:** "매 순간 실시간"이 아니라 **고객 턴(turn) 단위, final일 때 띄엄띄엄** 호출되는 게 정상. 의심 시 점검: 백엔드 `turn.ending`이 계속 final로 오는지, nlp:complete payload agent_id 형식(cc_cti_id)인지.

#### 44. 지식저장소 본문 폰트 제각각 → ToastEditor 타이포 정규화 (2026-06-16)
- **증상:** 상담어드바이저 우측 지식저장소, 탭 펼친 본문의 폰트가 제각각(어떤 건 bold·큰 사이즈·불편한 line-height).
- **렌더 체인:** TabTypeKnowledgeIndex(껍데기) → DocumentContentPanel → DocumentDetailView(섹션 반복) → **ContentCollapse → `<ToastEditor :model-value="contentString" />`** → Toast UI Editor가 `.toastui-editor-contents`로 마크다운 렌더.
- **원인:** `contentString`(ContentCollapse.vue:253)은 blocks_map에서 뽑은 **마크다운**(DOCX 추출 → `#`/`##`/`**bold**` 포함). Toast UI 기본 CSS(`toastui-editor.css`, 전역 import)가 heading/strong을 자기 기본 큰 사이즈로 렌더. `ToastEditor.vue`의 `.is-readonly`는 테두리/테이블/리스트/코드만 손봤고 **heading·본문 폰트는 미정규화** → 제목·볼드가 튐.
- **함정(중요):** `ContentCollapse.vue` 673~1008행 `.content-html h1~h6/strong/table...` CSS는 **전부 죽은 코드**. 템플릿에 `.content-html` 엘리먼트 없음(본문은 ToastEditor 경유). 여기 고치면 헛수고.
- **수정(A안, `src/components/contentViewer/ToastEditor.vue` `.is-readonly`):** `:deep(.toastui-editor-contents ...)` 타이포 정규화 추가 — base 13px/lh1.6, h1~h6 14px·600·lh1.45·margin 12px 0 4px(h1만 15px), p 13px/lh1.6, strong/b 600·`font-size:inherit`(안 커지게), li 13px/lh1.6. heading 밑줄 border는 기존 `:deep(*){border:none}`가 이미 제거.
- **적용 범위:** `.is-readonly`는 ToastEditor 템플릿에 항상 부착 → readonly ToastEditor 쓰는 **2곳(지식저장소 ContentCollapse + BookmarkDetailModal) 동시 반영**(의도된 동반 변경). 사이즈는 숫자만 조정 가능.

#### 45. (보류) 상담화면 브라우저 뒤로가기 제한 검토 (2026-06-16)
- **문제:** 상담 중 브라우저 뒤로가기 누르면 상담어드바이저 라우트(consultant/index.vue→agent/index.vue) 자체를 벗어남 → 컴포넌트 unmount + 소켓 리스너 정리 + store 초기화 → **실시간 수신 상담 데이터 전부 날아감(대형사고).**
- **구조 메모:** Dashboard↔상담화면 전환은 라우터 이동 아님 = `agent/index.vue`의 `isFirstMount` ref 토글. "오늘의 상담 준비"→`handleOnReady`에서 `isFirstMount=false`. 정상 이탈경로 = "대시보드" 버튼(`handleBackToDashboard`, isFirstMount=true+NOT_WORKING). 기존 가드 = `onBeforeRouteLeave`(agent/index.vue:253, 현재 NOT_WORKING 처리만).
- **검토안:** ①소프트=`onBeforeRouteLeave` 강화해 상담모드(isFirstMount===false)일 때 confirm→취소 시 `return false`(추천, ~10줄). ②하드=`history.pushState`+`popstate` 재push로 뒤로가기 봉인(~20줄, 리스너 정리 필요). ③하이브리드=평상시 소프트 + 통화중(ON_CALL) 하드. 트리거 범위(상담모드 항상 vs 통화중만)·문구 미확정.
- **상태:** 사용자 보류(이번 턴은 UI까지만 마무리). 추후 방식/트리거 확정되면 구현.

#### 46. 기획자 배포 UI를 시안으로 → Playwright MCP 도입 결정 (2026-06-16)
- **배경:** 기획자가 Figma 대신 **실제 배포된 화면**을 디자인 시안으로 공유. URL `http://13.209.195.192:32010/asst-web-ui/#/agent/dashboard` (경로 `/asst-web-ui/`, 해시 라우팅 → 별도 배포된 시안용 화면으로 추정).
- **할 수 없는 것:** 저 배포 서버를 직접 수정 불가(빌드된 dist 결과물). → 화면을 **참고**해 로컬 소스(`asst-web`)에 구현하는 흐름.
- **화면 보는 방법 검토:** WebFetch는 Vue SPA(JS 렌더+해시라우팅+로그인)라 빈 껍데기만 와서 부적합. → **Playwright MCP(Microsoft 공식)** 채택. 접속·스크린샷·DOM 스냅샷·CSS 확인 가능.
- **설치(사용자 작업):** `claude mcp add playwright npx @playwright/mcp@latest` → Claude Code 재시작 → `/mcp` 에서 connected 확인. (Node/npx 필요, 첫 실행 시 chromium 자동 다운로드, 안 되면 `npx playwright install chromium`.) 접속 시 로그인 필요 여부·사내망 접근 확인 필요.
- **다음 단계:** MCP 연결되면 클로드가 v2 시안 전체 분석 → 현재 소스 대비 수정 규모 검토.

#### 47. 감정(VOC탐지) 박스 UI 리디자인 + 종합위험도 게이지 신규(4행) (2026-06-16)
- **배경:** `voc.png` 시안에서 감정 박스가 정렬이 들쭉날쭉(라벨 폭 제각각·여러 줄 텍스트가 라벨 밑으로 파고듦). 추가로 1.고객감정 2.민원위험 3.이탈징후 + **4.종합위험도(신규, 수치화)** 4행 노출 요청. 수치화는 종합위험도만, 계산식은 `CustomerVocPanel.vue` 로직 계승.
- **수정 `src/view/advisor/components/voc/VocDetailBox.vue` (전면 리라이트):**
  - 1~3행 라벨을 **고정폭 칩(64px) 뱃지**로 통일 → 본문 시작 위치 줄마다 정렬 + hanging-indent(2번째 줄 안 파고듦). 감정 칩 = 감정색 연한 배경(`tint()` 14% rgba)+색점, 위험 2행 = 회색 칩.
  - **4행 종합위험도(신규):** 구분선 아래 `% 수치 + 상태라벨 + 가로 게이지 바`. 단계별 색상.
  - 인라인 헬퍼 `tint(hex)`(칩 배경 rgba 변환).
- **수정 `src/utils/emotionVoc.ts`:**
  - `VocView`에 `totalRisk: VocTotalRiskView | null` 추가(`{score,pct,level,label,color}`). `VocRiskLevel`("safe"|"warn"|"danger") + `RISK_LEVEL_META`(안정#22c55e/주의#f59e0b/위험#ef4444) + `buildTotalRisk(scores[])`(score 평균→3단계).
  - **단계 기준(사용자 선택=3단계):** `<0.5 안정` / `0.5~0.8 주의` / `≥0.8 위험`. (CustomerVocPanel은 0.8 단일이나 게이지 가독 위해 중간단계 추가.)
  - `resolveVocView`: 하드코딩 4개 콜은 score 없어 `totalRisk:null`(미노출), API 경로는 `[emotion,complaintRisk,churnRisk].score` 평균으로 계산.
- **시각화 선택(사용자):** 종합위험도 = **가로 게이지 바** (상태 뱃지/원형 링 후보 중 선택).

#### 48. 상담이력 상세 모달 — VOC를 상세응답 data.voc 에서 수신(고객정보 키워드 아래 노출) (2026-06-16)
- **배경:** 상세 API(`GET /calls/{id}` = `getHistoryDetail`) 응답에 `call`/`keywords`와 **같은 depth로 `voc` 객체**가 추가됨. 형식: `data.voc = { emotion:{type,score,summary}, complaintRisk:{score,summary}, churnRisk:{score,summary} }` (사용자 확정).
- **UI 배선은 이미 존재:** `ChatHistoryModal.vue` `vocView`(computed) → `CustomerPanel :voc` → `CustomerPanel.vue:74~78` **키워드 아래** "감정(VOC탐지)" 섹션 + `VocDetailBox`(47번 4행 UI 그대로). 변경은 **데이터 출처만**.
- **수정 `src/view/advisor/components/ChatHistoryModal.vue`:**
  - 상세응답 직후 `apiVoc.value = (data.voc as VocApiPayload) ?? null;` 추가(loadedCall 세팅 옆).
  - 기존 `apiVoc = summaryData`(요약 응답)는 **`data.voc`가 없을 때만 폴백**(`if (!apiVoc.value?.emotion)`)으로 강등(구버전 호환).
- **검증:** vue-tsc 관련 파일 에러 0. `data`는 any라 `data.voc` 접근 무탈.

#### 49. 고객정보 패널 스크롤 처리 (VOC 추가로 높이 초과 시 잘림 방지) (2026-06-16)
- **증상:** 키워드 아래 VOC 4행이 붙으면서 고객정보 패널 내용이 모달 높이(620px) 초과 → 하단 잘림.
- **수정 `src/view/advisor/components/ChatHistoryModal/CustomerPanel.vue`:** 루트 div에 `.customer-panel` 클래스 추가 + `min-height:0; overflow-y:auto; padding-bottom:20px`. → 모달 높이 초과 시 **왼쪽 패널 내부에서만 스크롤**, VOC 박스 안 잘림. (헤더 "고객정보"도 함께 스크롤되는 형태 — 거슬리면 헤더 고정 분리 가능, 보류.)

#### 50. VOC 노출 "값 없으면 미노출" 가드 강화 (필수 의존성 아님 확인) (2026-06-16)
- **사용자 우려:** VOC 두 곳(상담요약 팝오버 + 상담이력 상세) 추가가 필수인지, 값 없으면 안 뜨는지.
- **확인:** 셋 다 이미 `v-if` 가드 — `CounselingStatus.vue:114`(`v-if="vocView"`), `CustomerPanel.vue:75`(`v-if="voc"`), `VocDetailBox.vue`(`v-if="voc"`). `resolveVocView`는 하드코딩 매칭X + API voc 없으면 `null` 반환 → 미노출. **필수 의존성 없음**(백엔드가 voc 안 줘도 에러 없이 그냥 안 보임).
- **강화 `src/utils/emotionVoc.ts`:** API 경로 노출 조건을 `(e.summary || e.type)` → **`e.summary`** 로 좁힘. → voc 객체는 왔는데 summary(문구) 비면 빈 줄 안 나오게. (민원위험/이탈징후는 `riskView`가 summary 없으면 null, 종합위험도는 score 없으면 null — 각 행 개별 가드.)

#### 51. (분석/보류) 상담이력 상세 클릭 시 "오디오를 불러오는데 실패했습니다" 토스트 (2026-06-16)
- **증상:** 상담이력 상세 모달을 **열기만 해도**(재생 안 눌러도) 빨간 에러 토스트.
- **출처 체인:** `<audio preload="metadata" :src="audioSrc">`의 `error` 이벤트 → `useAudioPlayer.ts:77 handleAudioError` → `audioError=true` → `watch(audioError)`(:19) → `showCustomMessage("오디오를 불러오는데 실패했습니다.")`.
- **원인(메커니즘 확실):** `ChatHistoryModal.vue:494`에서 데이터 로딩 끝에 `audioSrc`에 playback URL 세팅 → `preload="metadata"`라 **사용자 재생 전에 브라우저가 자동 fetch** → 실패 시 error 이벤트. 가드(`isCallHistoryModalActive && isModalVisible && audioSrc`)는 통과되므로 토스트 발생.
- **실패 사유(env 의존, 추정):** 해당 콜 AGENT 녹취 부재 / `ticket·recKey(call_id)·date`/proxy 불일치 / **로컬-개발 환경에서 audio playback proxy 미제공**.
- **수정안(미확정, 사용자 선택 대기):** A안(추천)=error 이벤트 자동 토스트 제거, 재생 직접 눌렀을 때만 토스트+상태로 버튼 비활성/"녹취없음" 표시 / B안=`preload="none"`로 자동 fetch 차단 / C안=A+B.

#### 52. VOC 고객감정 3종 → 5종(+레거시 3종) 프론트 반영 (2026-06-17)
- **배경(백엔드 변경):** `docs/voc-emotion-5type-frontend.md`. VOC 3축 중 **emotion 축만** 세분화. `emotion.type` 값이 신규 5종(`angry`화남/`dissatisfied`불만/`normal`일반/`satisfied`만족/`thanks`감사) + 과거 콜이력 한정 레거시 3종(`negative`/`neutral`/`positive`)로 변경. 민원위험/이탈징후/종합위험도는 변경 없음.
- **백엔드 추가 확인(중요):** 실시간 소켓 `emotion` payload에서 **`sentiment_type` 필드 제거됨 → 이제 `type`만 옴**(`{ type, score, summary }`). 예: `{"type":"negative","score":0.65,"summary":"..."}`. → 프론트가 `type`(8종)을 직접 정규화하도록 통일.
- **색상 확정(사용자):** 화남=red`#ef4444` / 불만=보라`#a855f7` / 일반=중립색`#94a3b8` / 만족=긍정색`#22c55e` / 감사=핑크`#ec4899`. 레거시 부정/중립/긍정은 기존 3색 그대로.
- **수정 `src/utils/emotionVoc.ts`:** 8종 단일 소스 신규 — `EmotionTypeKey`(8종) + `EMOTION_TYPE_META`(라벨/색) + `resolveEmotionType(type)`(미정의/누락 값은 `normal`로 안전 처리, 문서 권장). `resolveVocView`의 하드코딩·API 양 경로가 이걸 써서 `emotion:{key,label,color,summary}` 생성. 죽은 `toSentiment`/`VOC_SENTIMENT_META` 제거. `VocEmotionView.sentiment`(4종) → `key`(8종 EmotionTypeKey)로 교체.
- **수정 `src/api/types/voc.type.ts`:** `VocEmotionType` → 신규5+레거시3 8종으로 교체(구 raw 5종 calm/sad/happy 폐기). `VocEmotion`에서 `sentiment_type` 제거(이제 안 옴), `type/score/summary`만. `VocSentimentType`(4종)은 정의만 잔존(미사용, 호환용).
- **수정 `src/view/advisor/components/voc/CustomerVocPanel.vue`:** 실시간 풀패널 — `SENTIMENT_META`/`sentimentMeta`(sentiment_type 기반) 제거 → `emotionMeta = resolveEmotionType(current.emotion.type)`. 템플릿 점/라벨 색 바인딩도 `emotionMeta`로.
- **수정 `src/view/advisor/components/chat/index.vue`:** 상담내용 헤더 인라인 VOC — `VOC_SENTIMENT_META`/`vocSentimentMeta`(sentiment_type) 제거 → `resolveEmotionType(vocLatest.emotion.type)`. import도 `VocSentimentType` → `resolveEmotionType`.
- **수정 `useChatMessageParser.ts:254`:** 진단 로그 `sentiment=...sentiment_type` → `type=...type` (로그만).
- **검증:** `vue-tsc --noEmit` 관련 파일 에러 0(잔여는 작업 전부터 있던 tsconfig deprecation 경고 2건뿐). `sentiment_type`/`VOC_SENTIMENT_META`/`toSentiment` 실사용 전부 제거 확인.
- **안 건드린 것:** 하드코딩 데모 4콜(`EMOTION_BY_CALL_ID`) 경로 — 기존 우선 노출 그대로(키가 positive/neutral/negative라 8종 메타에 그대로 매핑됨).
