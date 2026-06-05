# AssistStream 스냅샷 설계

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to produce the implementation plan from this design.

**작성일**: 2026-04-20
**관련 이전 설계**: `2026-04-18-assist-stream-sse-design.md`

---

## 1. 목표

라이브 채팅에서 RAG 응답(관련문서·hint·AI 요약·AI 답변)을 스냅샷으로 DB에 저장해, 상담 이력 조회 시 **라이브에서 본 것과 100% 동일한 내용**을 재현한다.

## 2. 배경 / 문제

현재 라이브와 이력의 렌더링이 세 층위로 어긋난다.

| 층위 | 라이브 | 이력 |
|------|--------|------|
| 호출 API | `/assist-stream` (SSE) | `/search` |
| hint | content에서 `/^Q\.\s*(.+?)(?:\n|$)/`로 추출 (데모 코드) | `metadata.hint` 원본 |
| 문서 | `sources` 이벤트 결과 | `/search` 결과 (다른 문서 셋) |

두 API는 쿼리 리라이트·인덱스 시점에 따라 **서로 다른 문서 셋**을 리턴하므로 병렬 호출로도 완전 일치 불가능. "상담 이력"의 본질은 그 시점의 기록 보존이므로 **라이브 스냅샷 영구 저장**으로 해결한다.

## 3. 접근 방식 (확정)

- 라이브 SSE 종료(`done` 이벤트) 시점에 프론트에서 전체 payload(sources + distilled + answer + hint)를 asst-service로 POST
- asst-service는 테넌트 DB의 **신규 테이블 1개**에 upsert
- 이력 조회 시 asst-service가 snapshot을 조인해 응답에 포함 → 프론트는 저장값만 렌더 (`/search` 재호출 제거)

**대안 기각 사유**
- *RAG에 hint 추가 요청*: RAG 팀 의존, 답변 재생성 비용 문제 해결 못함
- *이력에서 관련문서 표시 제거*: 기능 후퇴
- *callstats_turn JSONB 컬럼 추가*: turn은 배치 적재라 라이브 시점엔 존재 안 함. 또 turn이 STT/NLU 코어 데이터라 책임 혼재
- *병렬 호출*: 두 API 결과 불일치 근본 해결 못함

## 4. 스키마

### 신규 테이블 1개

```sql
CREATE TABLE advisor.callstat_assist_snapshot (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id VARCHAR(128) NOT NULL,        -- raw call id (orchestrator:started 이벤트)
  turn_idx INT NOT NULL,                 -- STT 발급 turn index (발화별 유일)
  customer_query TEXT NULL,              -- masked utterance (보강 매칭용)
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_assist_snapshot UNIQUE (call_id, turn_idx)
);
CREATE INDEX idx_assist_snapshot_call_id
  ON advisor.callstat_assist_snapshot (call_id);
```

### payload 구조

```typescript
interface AssistSnapshotPayload {
  hint: string;              // pill 표시용 제목
  sources: Array<{
    chunk_id: string;
    document_id: string;
    document_title: string;
    section_title: string;
    content: string;
    score: number;
    source_location: string;
    page_info?: string;
    ref_num: number;
  }>;
  distilled: {
    selected_refs: number[];
    summary: string;
    rationale: string;
  };
  answer: string;            // token 스트림 최종 결합
}
```

### 링크 전략

- `turn_id` FK 사용 **안 함** — `callstats_turn`은 콜 종료 후 외부 녹취 시스템 배치 적재되어 라이브 시점엔 존재하지 않음
- `(call_id, message_seq)` 복합 유니크 키로 식별. `message_seq`는 프론트가 콜 단위 전역 카운터로 발급
- `customer_query`는 매칭 보강용 (snapshot ↔ turn 매칭이 순번으로만 되면 불안정. 마스킹된 발화로 일치 여부 추가 확인)

## 5. 저장 흐름 (라이브)

```
[Chat UI]
  사용자 질문 발송
  ├─ messageSeq = ++chatSeqCounter (콜 단위)
  ├─ snapshotBuffer = { hint:'', sources:[], distilled:null, answer:'' }
  │
  ├─ POST /api/asst/v1/assist-stream  (SSE 시작)
  │     body: { query, conversationHistory, callId }
  │
  ├─ sources event    → snapshotBuffer.sources = e.sources
  ├─ intent/hint event → snapshotBuffer.hint = ... (원본 hint 사용)
  ├─ distilled event  → snapshotBuffer.distilled = e
  ├─ token events     → snapshotBuffer.answer += e.text
  │
  └─ done event:
        POST /api/asst/v1/assist-stream/snapshot  (with x-auth-token)
          body: {
            callId,
            messageSeq,
            customerQuery: maskedQuery,
            payload: snapshotBuffer
          }
        retry: 지수 백오프 3회 (500ms → 1s → 2s)
        실패: console.warn + 로깅, UX 영향 없음

[asst-service]
  AssistSnapshotController (AuthMiddleware 통과 → 테넌트 DB)
    @Post('/assist-stream/snapshot')
    AssistSnapshotService.save(dto)
      → repository.upsert(
          { callId, messageSeq, customerQuery, payload },
          { conflictPaths: ['callId', 'messageSeq'] }
        )
```

**주의**: 현재 `app.module.ts`에서 `/assist-stream`이 AuthMiddleware `.exclude()` 되어 있음. 새로 추가하는 `/assist-stream/snapshot`은 **exclude 대상 아님** (테넌트 DB 접근 필수).

## 6. 조회 흐름 (이력)

```
[ChatHistoryModal.vue]
  GET /api/asst/v1/callstat/calls/:callId
    response: {
      call: {...},
      turns: [...],
      snapshots: [
        { messageSeq, customerQuery, payload, createdAt }
      ]
    }

  렌더 로직:
    - 고객 발화 turn 순회
    - 각 turn에 대해 snapshot을 순번으로 매칭 (customerQuery 일치 검증으로 보강)
    - snapshot 없는 turn → 관련문서/AI답변 영역 숨김
    - /search 재호출 및 loadSearchHintsForHistory 함수 완전 제거
```

**asst-service 변경:**
- `CallstatService.getCallStatById()`에서 `callstat_assist_snapshot` 동일 callId로 조회해 응답에 첨부
- 한 쿼리로 처리 (snapshots는 수십 개 이하, 별도 leftJoin 불요)

## 7. 에러 처리

| 케이스 | 동작 |
|--------|------|
| snapshot POST 실패 (네트워크) | 3회 재시도 후 silent fail + 콘솔 경고 |
| snapshot POST 실패 (4xx/5xx) | 재시도 없이 silent fail + 콘솔 경고 |
| 중복 save 요청 | UNIQUE 제약 자동 해결 (upsert) |
| 이력 조회 시 snapshot 없음 | 해당 turn의 관련문서/AI답변 영역 숨김 |
| 매칭 순서 꼬임 | customerQuery 일치 실패하면 해당 turn만 숨김 |

## 8. 변경 파일 리스트

### asst-service
1. `src/advisor/call/entities/callstat-assist-snapshot.entity.ts` (신규)
2. `src/config/database.config.ts` (엔티티 배열에 등록)
3. `migrations/NNN_callstat_assist_snapshot.sql` (신규)
4. `src/advisor/assist-stream/dto/save-snapshot.dto.ts` (신규)
5. `src/advisor/assist-stream/dto/assist-snapshot-payload.dto.ts` (신규)
6. `src/advisor/assist-stream/controllers/assist-snapshot.controller.ts` (신규)
7. `src/advisor/assist-stream/services/assist-snapshot.service.ts` (신규)
8. `src/advisor/assist-stream/assist-stream.module.ts` (Provider 등록)
9. `src/advisor/call/services/callstat.service.ts` (snapshot 조회 추가)
10. `src/advisor/call/dto/get-call-stat-response.dto.ts` (snapshots 필드)
11. `src/app.module.ts` (exclude 경로 검증 — `/assist-stream/snapshot`은 **포함 안 됨**)

### asst-web
12. `src/api/config/path.ts` (`ASSIST_STREAM_SNAPSHOT: /assist-stream/snapshot`)
13. `src/api/apis/assist-stream.api.ts` (`saveAssistSnapshot` 함수 + 재시도 래퍼)
14. `src/view/advisor/components/chat/index.vue`
    - `snapshotBuffer` 누적 로직 추가
    - done 이벤트 후 POST 호출
    - "Q. " 데모 추출(`extractDemoTitle`) 제거 — snapshot hint는 RAG 원본 사용
    - messageSeq 카운터 추가
15. `src/view/advisor/components/ChatHistoryModal.vue`
    - `loadSearchHintsForHistory` 제거
    - `turn ↔ snapshot` 매칭 로직 추가
    - snapshot 없는 turn은 관련문서/AI답변 영역 숨김

### 테스트
16. `asst-service` 유닛: AssistSnapshotService upsert 케이스
17. `asst-web` 유닛: snapshotBuffer 누적 / 매칭 로직

## 9. 테스트 전략

- **asst-service 유닛 (Jest)**: 신규 save / 중복 save / 존재하지 않는 callId 조회
- **asst-web 유닛 (Vitest)**: SSE 이벤트 누적, POST payload 구성, 이력 매칭 알고리즘
- **E2E 수동**: 라이브 대화 1회 → 이력 모달 열기 → pill·문서·요약·답변이 저장된 값과 동일하게 표시되는지 확인. 기존 이력(snapshot 없음) 열어 영역 숨김 확인.

## 10. 리스크 / 향후 과제

| 항목 | 대응 |
|------|------|
| PII echo (answer/distilled에 고객 정보 노출) | 현 단계 마스킹 없음 (라이브 표시 기준과 동일). 별도 이슈로 관리 |
| payload 크기 | 한 턴당 ~10KB, 상담 50턴 극단치에도 수백 KB. JSONB로 충분 |
| 기존 상담(snapshot 없음) | 관련문서/AI답변 영역만 숨김. 다른 데이터(STT/NLU)는 기존대로 정상 노출 |
| turn ↔ snapshot 매칭 실패 | customerQuery 필드로 보강. 실패 시 해당 turn만 숨김, 전체 실패 안 함 |
| messageSeq 충돌 (탭 여러 개 등) | UNIQUE 제약으로 최신 upsert가 이김. 실무상 동일 callId를 두 탭에서 동시 운영할 UX 아님 |

## 11. 배포 순서

1. asst-service: 엔티티 + 마이그레이션 + 저장/조회 API 배포 (프론트 변경 없이도 무해)
2. asst-web: snapshotBuffer + POST + 이력 렌더 변경 배포
3. 배포 후: 신규 상담부터 snapshot 적재, 이력 조회 시 즉시 반영

## 12. 확정된 결정

- [x] 풀 스냅샷 저장 (sources + hint + distilled + answer 전부)
- [x] 새 테이블 1개 (`callstat_assist_snapshot`)
- [x] `(call_id, message_seq)` 복합 유니크 키 (turn_id FK 아님)
- [x] 프론트 주도 저장 (백엔드 SSE 릴레이는 파싱 안 함)
- [x] 저장 실패 silent fail + 3회 지수 백오프
- [x] PII 마스킹은 현 단계 미적용 (라이브와 동일 기준)
- [x] 기존 snapshot 없는 이력은 관련문서/AI답변 영역 숨김, 재호출 안 함
- [x] "Q. " 데모 추출 코드 **유지** (데모 시연용). snapshot.hint는 이 추출 결과를 그대로 저장해 라이브-이력 일치. 데모 종료 후 별도 태스크에서 document_title 폴백으로 전환
