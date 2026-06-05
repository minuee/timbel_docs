# 고객 발화 자동 검색 SSE(assist-stream) 전환 설계

## 목표

고객 발화 실시간 자동 검색 흐름을 기존 `POST /api/v1/search` 이중 호출(keyword + hybrid 병렬)에서 신규 SSE 엔드포인트 `POST /api/v1/rag/assist-stream` 단일 호출로 통합한다. 근거 문서 → 요약 → LLM 답변을 순차적으로 스트리밍 수신하여 UI에 실시간 반영한다.

## 배경

- 현재 `asst-web/src/view/advisor/components/chat/index.vue` L1545-1546이 고객 발화마다 `handleKeywordSearch` + `handleHybridSearch`를 **병렬로** 호출한다. keyword 결과는 UI에 prominent하게 표시되지 않고 소모되는 형태.
- RAG 서비스가 신규 SSE 엔드포인트 `/api/v1/rag/assist-stream`을 제공. 문서상 체감 응답 근거 ~330ms, 답변 완료 ~2.9s (기존 대비 88% 개선).
- 엔드포인트가 `mode=hybrid`, `rerank=on`, `intent_gate=on`, `distill=on`, `with_answer=on` 등을 서버측 고정 파라미터로 강제 → 클라이언트의 keyword/hybrid 분기가 불필요해짐.

## 범위

**전환 대상 (1곳)**
- `chat/index.vue`의 고객 발화 트리거 자동 검색 흐름

**유지 (3곳, `/api/v1/search` 계속 사용)**
- `ChatHistoryModal.vue` L618 (히스토리 모달 오픈)
- `ChatHistoryModal.vue` L1052 (히스토리 turn 클릭)
- `TabTypeKnowledgeIndex.vue` L876 (상담원 수동 검색)

## 아키텍처 (NestJS SSE 프록시)

```
Browser (asst-web)              NestJS (asst-service)              RAG Service
─────────────────               ─────────────────────              ────────────
AssistStreamAPI                 AssistStreamController
  fetch POST      ──────POST─▶  /api/asst/v1/assist-stream
                                AssistStreamService
                                  fetch stream      ──────POST──▶  /api/v1/rag/assist-stream
                                                                     (SSE)
                                                    ◀─────SSE────  intent
                                res.write ◀──────────────────────  sources
ReadableStream    ◀─────SSE───  res.write ◀──────────────────────  distilled
  파싱                          res.write ◀──────────────────────  token × N
이벤트별 UI 갱신                res.write ◀──────────────────────  done
```

- **인증**: 프론트엔드 → NestJS는 기존 Bearer (`x-auth-token`) 유지. NestJS → RAG는 `X-Tenant-Id` 자동 주입.
- **프록시 방식**: axios는 SSE 스트리밍 릴레이에 부적합하므로 Node.js `fetch` + `ReadableStream` 사용.
- **취소**: 클라이언트 `req.on('close')` 시 `AbortController.abort()`로 업스트림 취소.

## 백엔드 설계 (asst-service)

### 신규 파일

```
src/advisor/assist-stream/
├── controllers/assist-stream.controller.ts
├── services/assist-stream.service.ts
└── dto/assist-stream-request.dto.ts
```

### 엔드포인트

**`POST /api/asst/v1/assist-stream`**

요청 바디 (`AssistStreamRequestDto`):
```typescript
{
  query: string;              // 1~1000자
  conversationHistory?: Array<{
    speaker: 'customer' | 'agent';
    content: string;          // min 1자
  }>;
  repositoryId?: string;      // 없으면 SEARCH_REPOSITORY_ID env fallback
  callId?: string;            // 로깅용
}
```

응답 헤더:
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

응답 본문: SSE 이벤트 (`intent`, `sources`, `distilled`, `token` × N, `done` | `error`)

### AssistStreamService 동작

1. **입력 변환**:
   - `conversationHistory` → `conversation_history`: `customer` → `user`, `agent` → `assistant`
   - 서버측 마지막 4 메시지(2턴) truncate (문서 §1)
   - `repositoryId` 없으면 `SEARCH_REPOSITORY_ID` env 사용
2. **업스트림 호출**:
   - URL: `${SEARCH_HOST}/api/v1/rag/assist-stream`
   - 헤더: `Content-Type: application/json`, `Accept: text/event-stream`, `X-Tenant-Id: <tenant>`
   - Node `fetch` + `ReadableStream` (axios 사용 금지)
   - `AbortController` 연결
3. **응답 릴레이**:
   - 업스트림 status ≥ 400 & SSE 헤더 미전송 상태 → 일반 JSON 에러 응답으로 변환 (422/429/503 등 pass-through)
   - SSE 시작 후 업스트림 에러 → `event: error` 프레임 생성 후 스트림 종료
   - 정상 프레임은 `event:`/`data:` 라인 단위로 그대로 `res.write()`
4. **취소**:
   - `req.on('close', () => abortController.abort())` 등록
5. **타임아웃**:
   - 총 요청 40s hard timeout (문서 §5)
   - 업스트림 연결 실패 → 503

### 보존
- `SearchController`/`SearchService`/`POST /search`: 변경 없음. keyword/hybrid mode 파라미터도 그대로 (다른 호출처 영향 없음).

## 프론트엔드 설계 (asst-web)

### 신규 파일

```
src/api/
├── apis/assist-stream.api.ts        # fetch + ReadableStream SSE 파서
└── types/assist-stream.type.ts      # 이벤트 타입
```

### 타입 정의

```typescript
// assist-stream.type.ts
export interface AssistStreamReq {
  query: string;
  conversationHistory?: Array<{ speaker: 'customer' | 'agent'; content: string }>;
  repositoryId?: string;
  callId?: string;
}

export interface IntentEvent {
  search: boolean;
  reason: string;
  latency_ms: number;
  skipped: boolean;
}

export interface SourceItem {
  ref_num: number;
  document_id: string;
  chunk_id: string;
  document_title: string;
  section_title: string;
  content: string;
  score: number;
  token_count: number;
  page_info?: string;
  source_location?: { page_number?: number; bbox?: number[] };
}

export interface SourcesEvent {
  sources: SourceItem[];
  confidence: number;
  search_latency_ms: number;
  total_candidates: number;
}

export interface DistilledEvent {
  selected_refs: number[];
  summary: string;
  rationale: string;
  latency_ms: number;
}

export interface TokenEvent { text: string; }

export interface DoneEvent {
  model_used: string | null;
  confidence: number;
  token_usage: { context_tokens: number; prompt_tokens: number; completion_tokens: number; total_tokens: number };
  latency_ms: number;
  stages: { intent: number; search: number; distill?: number; generate?: number };
}

export interface ErrorEvent {
  stage: 'search' | 'generate' | 'unknown';
  code: string;      // timeout, ttft_timeout, total_timeout, service_unavailable, llm_error, search_error, internal_error
  message: string;
}

export type AssistStreamHandlers = {
  intent?: (e: IntentEvent) => void;
  sources?: (e: SourcesEvent) => void;
  distilled?: (e: DistilledEvent) => void;
  token?: (e: TokenEvent) => void;
  done?: (e: DoneEvent) => void;
  error?: (e: ErrorEvent) => void;
};
```

### API 래퍼

```typescript
// assist-stream.api.ts (요지)
export class AssistStreamAPI {
  async call(
    req: AssistStreamReq,
    handlers: AssistStreamHandlers,
    signal?: AbortSignal,
  ): Promise<void> {
    const res = await fetch('/api/asst/v1/assist-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify(req),
      signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // ReadableStream → 라인 버퍼링 → event/data 프레임 파싱 → handlers 호출
    // done/error 수신 시 종료
  }
}
```

### chat/index.vue 수정

**제거**
- `handleKeywordSearch()` 함수 (L1995-2158)
- `handleHybridSearch()` 함수 (L2160-2230+)
- L1545-1546의 이중 호출

**추가**
- `handleAssistStream(query, messageId)` 단일 함수:
  ```
  대화 이력 추출 (마지막 고객 1 + 상담원 1)
  ↓
  AbortController 생성, 메시지 ID별로 저장
  ↓
  AssistStreamAPI.call(req, handlers, controller.signal)
  ↓
  handlers:
    intent   → intent.search=false면 UI 스킵 플래그
    sources  → 메시지 keyword 데이터 구조 채움 (기존 hybrid 결과 자리)
    distilled → 메시지 ai_summary 슬롯 채움
    token    → aiSearchResultText 누적 (messageId별 버퍼)
    done     → 로딩 상태 해제
    error    → 에러 UI
  ```
- 호출 지점 (L1545-1546 대체):
  ```
  if (isUser) {
    handleAssistStream(messageData.origin_text, messageId);
  }
  ```
- 메시지 언마운트/채팅 초기화 시 AbortController.abort() 호출

## SSE 이벤트 ↔ UI 매핑

| SSE 이벤트 | UI 슬롯 | 위치 |
|---|---|---|
| `sources.sources[]` | 참고문서 카드 리스트 | [knowledge/index.vue:238-246](asst-web/src/view/advisor/components/knowledge/index.vue#L238) |
| `distilled.summary` | AI 요약 영역 | [TabTypeKnowledgeIndex.vue:101-105](asst-web/src/view/advisor/components/knowledge/TabTypeKnowledgeIndex.vue#L101) |
| `token[].text` 누적 | AI 답변 영역 (`aiSearchResultText`) | [knowledge/index.vue:231-234](asst-web/src/view/advisor/components/knowledge/index.vue#L231) |
| `sources.sources[].ref_num` | 문서 카드 번호 | 기존 인덱스 자리 |
| `sources.sources[].page_info` | 카드 페이지 표시 | 기존 metadata 자리 |

## 엣지 케이스 처리

| 상황 | 동작 |
|---|---|
| `intent.search=false` (일상 대화) | sources=[] 렌더, 답변 영역에 안내 토큰 1건만 표시, 요약 영역 숨김 |
| `sources.sources=[]` (검색 0건) | "참고 자료를 찾지 못했습니다" 단일 토큰, 요약 영역 숨김 |
| `distilled` 이벤트 생략 (증류 실패) | AI 요약 영역 숨김, 답변만 진행 |
| `error` 이벤트 | stage/code/message 로깅, 에러 안내 UI, 로딩 해제 |
| 422 (요청 스키마 위반) | 일반 에러 토스트 |
| 429 (테넌트 동시 8건 초과) | "잠시 후 다시 시도" 안내 |
| 클라이언트 unmount/네비게이션 | AbortController로 스트림 취소 → 서버측 업스트림 취소 |

## 환경변수

변경 없음.
- `SEARCH_HOST`: 그대로 사용 (RAG 서비스 호스트)
- `SEARCH_REPOSITORY_ID`: 그대로 사용 (기본 repository_id fallback)

## 테스트 전략

**백엔드**
- `AssistStreamService` 단위 테스트: fetch mock으로 SSE 이벤트 릴레이 검증
- 취소 처리: 클라이언트 close 시 AbortController abort 호출 검증
- 에러 변환: 업스트림 422/429/503 → 적절한 응답 변환

**프론트엔드**
- `AssistStreamAPI` 단위 테스트: ReadableStream mock으로 프레임 파싱 및 handler 디스패치 검증
- 경계: 청크가 프레임 중간에 끊기는 경우 버퍼링 정상 동작
- 이벤트 순서: intent → sources → distilled → token × N → done

**통합**
- 로컬에서 실제 RAG 서비스 연결 후 발화 1회 → 세 영역(참고문서/요약/답변) 모두 실시간 업데이트 확인

## 리스크 & 고려사항

- **NestJS Express 5 SSE**: path-to-regexp v8 환경에서 SSE 응답 쓰기 검증 필요. `@Res({ passthrough: false })` + raw `res.write` 사용.
- **프록시/로드밸런서**: 운영 환경 nginx의 `proxy_buffering off`, `proxy_read_timeout 60s` 설정 필요 (문서 §5). 운영 배포 전 인프라팀 확인.
- **동시 요청 한도**: 테넌트당 워커당 8건. 4 워커 환경에서 실질 32건. 상담원 수 많으면 추가 조정 필요.
- **keyword mode 제거 아님**: `SearchService`의 keyword 분기 코드는 남겨둠. 다른 호출처가 계속 사용 가능.

## 검증 방법

1. 로컬 환경에서 `npm run start:dev` + `npm run dev`
2. 테스트 통화 연결 후 고객 발화 시뮬레이션
3. 네트워크 탭에서 `/api/asst/v1/assist-stream` 응답이 `text/event-stream`, 이벤트 순차 수신 확인
4. UI 세 영역(참고문서/AI 요약/AI 답변)이 순차적으로 채워지는지 확인
5. 두 번째 발화 시 첫 발화 스트림이 abort되는지 확인
6. `console.log`로 done.stages latency 확인 (근거 ≤500ms, 답변 완료 ≤3s 목표)
