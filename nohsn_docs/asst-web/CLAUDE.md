# asst-web 작업 기록

## 대화 지시사항 (항상 준수)
- **언어:** 사용자와 항상 한국어로 대화한다. 친근한 반말 OK(사용자가 편하게 여김).
- **확정 후 작업:** 코드 수정 전 사용자에게 이해한 내용을 정리해 **확정받고** 진행한다. 추측으로 무조건 수정하지 않는다.
- **대화 기록:** 모든 대화는 `CLAUDE-history.md` 에 순차 기록한다. 매 턴 즉시 저장이 아니라 **적당한 시기(대화 2~3턴 진행될 때마다)** 에 이전 마지막 항목에 **이어서** 저장한다(번호 연속, 날짜 헤더 유지). `CLAUDE.md` 에는 사용자가 별도로 지정할 때만 저장한다.

## LLM 기반 기능 처리 구조 (통화요약 / 키워드 추출 / 자동 Todo / 감정)

### 핵심 요약
- 프론트엔드에 **LLM(OpenAI/Anthropic 등) 직접 호출은 없음**.
- 프론트는 `callstats_id`만 백엔드 게이트웨이로 전달하고, 실제 LLM 추론은 백엔드 `asst-service`가 수행해 결과만 내려줌 → 프론트 입장에서는 **순수 백엔드 프록시 호출**.

### 공통 인프라
| 항목 | 값 |
|---|---|
| HTTP 클라이언트 | `super("advisor")` → `getClient("advisor")` (axios) |
| Base URL | `LANGSA_GATEWAY_URL` (dev: `https://ecpad.etaas.co.kr`, prd: `https://ecp.etaas.co.kr`) |
| 게이트웨이 prefix | `path.ADVISOR.API_PREFIX` = `/aicc/asst-service` (`src/api/config/path.ts:26`) |
| 인증 | Bearer 토큰 + `X-Auth-token` 헤더 (쿠키 → env 폴백) |

### 진입점
- **`src/components/layout/HeaderActionBar/CounselingStatus.vue`** 의 `handleSummary()`.
- 사용자가 **"상담요약" 버튼 1회 클릭** 시 아래 API가 순차 연쇄 호출됨.

### "상담요약" 클릭 시 호출되는 API (최대 3개)

1. **상담 요약 생성 (메인)**
   - `POST /aicc/asst-service/summary`
   - 소스: `src/api/apis/summary.api.ts:22` `createSummary()`
   - 요청: `{ callstats_id, keyword_count: 5 }`
   - 응답: `{ summary(마크다운), keywords[], counselingTypes[], emotion? }`
   - ⭐ **감정(VOC탐지) 값은 이 응답의 `emotion` 객체로 내려옴 (아래 구조 참고)**

2. **요약 자동 저장** (①성공 직후 자동)
   - `POST /aicc/asst-service/summary/data`
   - 소스: `src/api/apis/summary.api.ts:28` `saveSummaryData()`
   - 요청: `{ callstats_id, summary, keywords, external_categories_id }`

3. **할일 자동 생성** (①성공 직후 자동)
   - `POST /aicc/asst-service/todos/auto-create`
   - 소스: `src/api/apis/todo.api.ts:63` `autoCreateTodo()`
   - 요청: `{ callstats_id, maxLength: 100, includeSimple: true, user_key }`
   - 성공 시 `todoListStore.refreshTodoList(이번달 시작~끝)`로 목록 갱신

### 키워드 추출 참고
- 별도 API 아님 → ①의 `createSummary` 응답 `keywords[]`에 함께 포함됨.
- `KeywordDetectAPI`(`src/api/apis/keyword-detect.api.ts`)는 **정적 키워드 탐지 규칙 관리용**으로 요약 키워드와 무관 (혼동 주의).

### 저장 버튼(`handleApply`)
- `POST /aicc/asst-service/summary/data` (재저장)
- dev/prd 한정 `POST {ADVISOR.API_PREFIX}/proxy/qa/calls/end` (QA 집계)

---

## 감정(VOC탐지) 기능 (최종)

### 개요
- **3분류**(긍정/중립/부정). 색상 점(●) + 라벨 + 콜별 문구 한 줄 노출 (sample.png 기준).
- 라벨은 부가설명 괄호 없이 **`긍정` / `중립` / `부정`** 만 노출. 출력 형태: `● 부정: <콜별 문구>`
- ⚠️ **백엔드 연동 아님 — "상담 아이디별 하드코딩"으로 노출** (추후 LLM 응답 연동 시 교체 예정).
- 정의·매핑·노출 로직은 **공용 모듈 `src/utils/emotionVoc.ts`** 단일 소스. 콜 등록은 이 파일의 `EMOTION_BY_CALL_ID` 한 곳에서만.

### 적용 위치
| 화면 | 파일 | 노출 여부 | 분류 기준 |
|---|---|---|---|
| 상담중 상담요약 팝오버 (상담내용 아래) | `components/layout/HeaderActionBar/CounselingStatus.vue` | ✅ 노출 | `callId` / `callStatsId` |
| 상담이력 상세 — 고객정보 패널 (키워드 아래) | `ChatHistoryModal.vue` → `ChatHistoryModal/CustomerPanel.vue` | ✅ 노출 | `props.callStatsId` / 로드된 `call_id` / `id` |
| 상담이력 상세 — 상담내용 패널 (상담내용 아래) | `ChatHistoryModal.vue` → `ChatHistoryModal/SummaryPanel.vue` | ⛔ **주석 처리** (`:emotion` 주석) | — |
- `CustomerPanel`/`SummaryPanel` 은 `emotion?: EmotionDef \| null` prop 만 받아 표시(dumb). 부모(`ChatHistoryModal`)가 `resolveEmotionByCallIds(...)` 로 계산해 전달.
- 상담내용 패널을 다시 켜려면 `ChatHistoryModal.vue` 의 `<SummaryPanel ... /><!-- :emotion="emotionDef" -->` 주석만 풀면 됨. (SummaryPanel 에는 내부 스크롤 처리가 되어 있어 상담내용이 길어도 감정 박스가 안 잘림)

### 데이터 구조 (`emotionVoc.ts`)
- `EMOTION_META`: 분류별 라벨/색상 — `positive`(긍정/`#22c55e`), `neutral`(중립/`#cbd5e1`), `negative`(부정/`#ef4444`).
- `EMOTION_BY_CALL_ID`: 콜아이디 → `{ type, description }`. **콜마다 문구가 다름.**
- `resolveEmotionByCallId(id)` / `resolveEmotionByCallIds(...ids)`: 등록된 콜이면 `EmotionDef{ key,label,color,description }` 반환, 아니면 `null`(미노출). 여러 식별자 후보 중 하나만 맞으면 노출.

### 현재 등록된 콜 (4개)
| 콜 ID | 분류 | 문구 |
|---|---|---|
| `call_767b6b1e_9d85_9711_9631_3110f18fc8f6` | 부정 | 어려운 안내에 불만 제기 ('왜 그렇게 어려운 말을 써요'), 상담사 사과 발생 |
| `call_da59d87f_a0f2_a77d_c615_14dfecd64fad` | 중립 | 평이한 이직 연말정산 문의, 안내 수긍 후 종료 |
| `call_73a1075c_70de_d8be_b97e_9e878ee1eb3d` | 중립 | 혼인 공제 정보 요청 및 수긍, 만족/불만 표현 없음 |
| `call_52c5f7aa_0ad9_e4bb_f307_9b1c088b40e8` | 중립 | 재설명 요청(답답함)은 있으나 욕설/언성 없음 |

### 콜 식별자 주의 (중요)
- 상담이력 모달의 URL `/callstat/calls/{X}` 의 `{X}` 가 곧 `props.callStatsId` (예: `call_5f6effe6_...`). 이 값이 `EMOTION_BY_CALL_ID` 키와 정확히 일치해야 노출됨.
- `props.callStatsId`(row id) 외에 로드된 `data.call.call_id` / `data.call.id` 도 함께 대조 (혼용 대비).

### 하마터면 헷갈리는 함정 2가지 (해결 완료)
1. **레이아웃 잘림**: 상담내용 패널은 높이 제한이 없어 요약이 길면 그 아래 감정 박스가 모달(620px) 밖으로 밀려 안 보였음 → `SummaryPanel` 의 `.chat-content-wrapper` 에 `flex:1; min-height:0; overflow-y:auto`, 패널에 `overflow:hidden` 적용해 상담내용만 스크롤·감정 박스 고정.
2. **색상 점 안 보임**: `flx-align-start` 는 **존재하지 않는 클래스**(common.scss엔 `.flx-center`/`.flx-align-center` 만 있음) → 박스가 flex 가 아니라 `<span>` 점이 인라인이 되어 width/height 무시됨 → `flex` 클래스로 교체 + `.emotion-dot` 에 `display:inline-block` 안전장치 추가.

### API 응답 emotion 보관 (화면 미사용 / 추후 활용)
- `CounselingStatus.vue` 의 `handleSummary` 에서 `POST /aicc/asst-service/summary` 응답의 `emotion` 을 `apiEmotion` ref 에 **원본 그대로 보관** (없어도 `null`, 에러 없음).
- 화면 노출은 위 하드코딩 분류만 사용. 추후 연동 시 `apiEmotion` 값으로 교체.
