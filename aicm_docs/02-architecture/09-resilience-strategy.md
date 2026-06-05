> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `draft` |
> | 검수 | `unreviewed` |
> | 최종 수정 | 2026-04-08 |

# 서비스 간 통신 복원력 전략

> aicm-service가 외부 서비스(parser-service, retrieval-service, LLM Orchestrator)와 통신할 때 적용하는 장애 격리·복구 패턴을 정의한다. 각 서비스별 구현 상세는 원천 문서를 참조하고, 이 문서는 **패턴 카탈로그 + 서비스별 설정 총괄표** 역할을 한다.

---

## 1. 적용 범위

aicm-service는 모듈러 모놀리스로서, 외부 3개 서비스와 HTTP 기반으로 통신한다.

```
aicm-service (NestJS)
  ├─ parser-service (FastAPI)      — NDJSON 스트리밍, 비동기(BullMQ)
  ├─ retrieval-service (Python)    — REST, 동기 + 비동기(BullMQ)
  └─ LLM Orchestrator              — REST + SSE 스트리밍, 동기
```

| 통신 유형 | 적용 패턴 | 이유 |
|----------|----------|------|
| **동기 HTTP** | 타임아웃 + 서킷 브레이커 + Fallback | API 핸들러에서 호출하므로 이벤트 루프 블로킹 방지 필수 |
| **비동기 BullMQ** | 타임아웃 + 재시도 + DLQ | Worker에서 호출하므로 CB 불필요. BullMQ 자체 재시도/DLQ로 관리 |
| **스트리밍 (NDJSON/SSE)** | 2단계 타임아웃 + heartbeat + 점진적 저장 | 단일 타임아웃으로는 장시간 스트리밍을 관리할 수 없음 |

> **모놀리스 내부 호출에는 적용하지 않는다.** 모듈 간 호출은 인프로세스이므로 네트워크 장애가 발생하지 않는다. EventBus(Best-effort 티어) 이벤트의 유실은 Reconciliation 배치(§6)로 보정한다.

---

## 2. 패턴 카탈로그

### 2.1 타임아웃 (Timeout)

외부 서비스 호출에 반드시 타임아웃을 설정한다. 타임아웃 없는 외부 호출은 코드 리뷰에서 차단한다.

**종류**:

| 종류 | 설명 | 적용 대상 |
|------|------|----------|
| **단일 타임아웃** | HTTP 요청 전체에 대한 제한 시간 | 동기 REST 호출 |
| **2단계 타임아웃** | (1) 첫 응답 대기 + (2) 후속 데이터 간격 | 스트리밍 (NDJSON, SSE) |
| **Job 타임아웃** | BullMQ Job 전체 실행 제한 시간 | 비동기 큐 워커. 스트리밍 타임아웃의 최종 안전망 |

**2단계 타임아웃 상세**:

스트리밍 프로토콜은 단일 HTTP 타임아웃으로 관리할 수 없다. 연결 후 데이터가 간헐적으로 도착하므로, "첫 데이터까지의 대기"와 "데이터 간 간격"을 분리한다.

```
연결 ──[첫 응답 타임아웃]──▶ 첫 데이터 수신
                              │
                              ├──[라인 간 타임아웃]──▶ 데이터 N
                              ├──[라인 간 타임아웃]──▶ 데이터 N+1
                              └──[라인 간 타임아웃]──▶ 종료 신호
                              
──────────── [Job 타임아웃 (최종 안전망)] ──────────────▶
```

### 2.2 재시도 (Retry)

**지수 백오프 (Exponential Backoff)**:

재시도 간격을 지수적으로 증가시켜 장애 중인 서비스에 과부하를 방지한다.

```
delay = min(baseDelay × 2^(attempt-1), maxDelay)
```

| 파라미터 | 기본값 | 설명 |
|---------|-------|------|
| `baseDelay` | 5,000ms | 첫 번째 재시도 대기 시간 |
| `maxDelay` | 120,000ms | 최대 대기 시간 상한 |
| `attempts` | 3 | 최대 재시도 횟수 (초회 포함하지 않음) |

BullMQ 기본 설정:

```typescript
const defaultJobOptions: JobsOptions = {
  attempts: 3,
  backoff: {
    type: 'exponential',
    delay: 5000, // 5s → 10s → 20s
  },
  removeOnComplete: true,
  removeOnFail: false, // 실패 Job 보존 (DLQ 이동)
};
```

**Jitter (지터)**:

다수 Job이 동시에 실패하면 동일 간격으로 재시도하여 **thundering herd**가 발생한다. 재시도 간격에 랜덤 지터를 추가하여 요청을 분산시킨다.

```typescript
delay = min(baseDelay × 2^(attempt-1) + random(0, baseDelay), maxDelay)
```

Jitter는 다음 상황에서 특히 중요하다:
- 서비스 완전 다운(ECONNREFUSED) 후 복구 시 — 대기 중이던 모든 Job이 동시 재시도
- 배포(rolling update) 중 일시적 연결 실패 — 복수 워커가 동시에 재시도

**재시도 불가 에러 분류**:

모든 에러를 동일하게 재시도하면 확정적 에러(`FILE_TOO_LARGE` 등)가 큐 슬롯을 무의미하게 점유한다. 에러를 **retryable**과 **non-retryable**로 분류하여, non-retryable은 재시도 없이 즉시 DLQ로 이동한다.

| 분류 | HTTP 상태 | 예시 | 처리 |
|------|----------|------|------|
| **Non-retryable** | 400, 404, 422 | `UNSUPPORTED_FORMAT`, `FILE_TOO_LARGE`, `FILE_NOT_FOUND`, `INVALID_REQUEST`, `EMPTY_BLOCKS` | `job.discard()` → 즉시 DLQ |
| **Retryable** | 409, 429, 500, 503 | `CONCURRENT_OPERATION`, `RATE_LIMITED`, `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE` | 지수 백오프 재시도 |
| **특수** | 400 (`INVALID_CURSOR`) | 커서 형식 변경 | 커서 제거 후 처음부터 재시도 |

### 2.3 서킷 브레이커 (Circuit Breaker)

외부 서비스 장애가 지속될 때, 계속 요청을 보내면 이벤트 루프가 블로킹되고 응답 지연이 전파된다. 서킷 브레이커는 실패가 임계값을 넘으면 요청을 즉시 차단(fail-fast)하여 장애 전파를 방지한다.

**상태 전이**:

```
     연속 실패 ≥ 임계값
Closed ──────────────────▶ Open
  ▲                          │
  │ 시험 성공                 │ 복구 대기 시간 경과
  │                          ▼
  └──────────────────── Half-Open
           시험 실패 ──▶ Open (복귀)
```

| 상태 | 동작 |
|------|------|
| **Closed** (정상) | 요청을 정상 전달. 연속 실패 횟수를 카운트 |
| **Open** (차단) | 요청을 즉시 실패 처리(fail-fast). Fallback 반환. 복구 대기 시간 후 Half-Open으로 전환 |
| **Half-Open** (시험) | 제한된 수의 요청만 통과시켜 복구 여부를 확인. 성공 시 Closed, 실패 시 Open 복귀 |

**적용 기준**:

| 호출 유형 | CB 적용 | 이유 |
|----------|:-------:|------|
| 동기 HTTP (API 핸들러에서 호출) | **Yes** | 이벤트 루프 보호 |
| 비동기 BullMQ (Worker에서 호출) | **No** | BullMQ 자체 재시도/DLQ로 관리. Worker는 별도 스레드풀 |
| 헬스체크 (`GET /health`) | **No** | CB Half-Open 프로브 용도. CB 대상이 아님 |

**CB 상태 저장**:

```
Redis Key: {tenant_id}:circuit:{service_name}
예시:      tenant-001:circuit:retrieval-service
```

### 2.4 Fallback (Graceful Degradation)

서킷 브레이커 Open 또는 외부 서비스 에러 시, 서비스 전체가 중단되지 않도록 대체 경로를 제공한다.

**Fallback 유형**:

| 유형 | 설명 | 예시 |
|------|------|------|
| **기능 축소** | 핵심 기능은 유지하되 부가 기능을 비활성화 | 시맨틱 검색 불가 → 키워드 검색만 제공 |
| **대체 데이터소스** | 외부 API 대신 내부 DB에서 직접 조회 | 외부 조직 API 장애 → AICM DB Team 계층 직접 조회 |
| **지연 처리** | 즉시 처리 대신 후속 배치에서 보정 | 임베딩 삭제 실패 → 삭제 마킹 + Reconciliation 배치에서 보정 |
| **사용자 재시도 위임** | 자동 복구 불가 시 사용자에게 재시도 버튼 노출 | LLM 스트리밍 실패 → 프론트엔드 재시도 버튼 |

### 2.5 DLQ (Dead Letter Queue)

재시도 소진 후 최종 실패한 Job을 별도 큐에 보관하여, 운영자가 확인·재처리할 수 있도록 한다.

**처리 흐름**:

```
Job 실행 → 실패 → 재시도 횟수 < 3?
  ├─ Yes → 지수 백오프 대기 → 재실행
  └─ No  → DLQ 큐로 이동 → 관리자 알림 → Bull Board에서 확인
            ├─ 수동 재시도 → 원본 큐에 Job 재등록
            └─ 영구 삭제
```

> DLQ 관리 API(`/admin/dlq/*`)는 정책으로 정한 `AdminPermission`이 필요하며, 모든 조작은 감사 로그에 기록된다. 상세: [비동기 처리 아키텍처 §6.6](./05-async-event-architecture.md)

### 2.6 Heartbeat (생존 신호)

스트리밍 프로토콜에서 블록/토큰 생산이 지연되는 구간(복잡한 표 OCR, LLM 추론 대기 등)에서 타임아웃을 방지하기 위해, 실제 데이터 없이 "살아있음" 신호를 전송한다.

```
블록 생산 ──▶ [30초 초과] ──▶ heartbeat 전송 ──▶ 타임아웃 타이머 리셋
                                                  (DB 저장/SSE 푸시 없음)
```

### 2.7 점진적 저장 + 커서 기반 재개

비용이 높은 장시간 스트리밍 작업(LLM+OCR 파싱 등)에서, 장애 시 이미 처리된 결과를 보존하고 중단 지점부터 재개한다.

| 구성 요소 | 역할 |
|----------|------|
| **점진적 저장** | 데이터(블록) 수신 즉시 DB에 저장. 전체 완료를 기다리지 않음 |
| **불투명 커서** | 서비스가 블록마다 발행. aicm-service는 해석 없이 저장/전달만 함 |
| **경계 블록 삭제** | 재개 전 마지막 커서 위치의 불완전한 블록을 삭제 |
| **커서 재개** | 재시도 시 `resume_cursor`로 중단 지점부터 재처리 |

```
장애 시점:  DB에 블록 0~42 저장됨, lastCursor = {"page": 30}
  → 경계 블록 삭제 (page 30 소속)
  → resume_cursor: {"page": 30}으로 재시도
  → page 30부터 재파싱 → 블록 43~120 이어 저장
```

> 이 패턴은 all-or-nothing 대비 장애 복구 비용을 크게 절감한다. 95% 완료 후 장애 시 5%만 재처리. 상세: [parser-service 연동](../temp/parser-service-integration.md)

---

## 3. 서비스별 설정 총괄표

### 3.1 타임아웃

#### 동기 호출

| 서비스 | 엔드포인트 | 타임아웃 | 비고 |
|--------|-----------|:--------:|------|
| retrieval-service | `POST /search` | 30s | 검색 응답 SLA |
| retrieval-service | `DELETE /sources/{sourceId}` | 15s | 벡터 삭제 포함 |
| retrieval-service | `DELETE /sources` (배치) | 60s | 최대 100건 |
| retrieval-service | `PATCH /sources/{sourceId}/metadata` | 10s | 경량 요청 |
| retrieval-service | `GET /sources/{sourceId}/chunks` | 15s | 대형 문서 고려 |
| retrieval-service | `PUT /config` | 10s | 설정 push |
| retrieval-service | `GET /health` | 3s | CB 프로브 |
| LLM Orchestrator | `POST /llm/complete` | 30s | 비스트리밍 |
| LLM Orchestrator | `GET /usage/summary` | 10s | 통계 조회 |

#### 스트리밍 호출 — 2단계 타임아웃

| 서비스 | 프로토콜 | 첫 응답 | 데이터 간격 | Job 타임아웃 | SystemConfig 키 |
|--------|---------|:-------:|:----------:|:-----------:|----------------|
| parser-service | NDJSON | 60s | 90s | 30분 | `pm:system.parser_first_line_timeout_ms`, `pm:system.parser_inter_line_timeout_ms` |
| LLM Orchestrator (SaaS) | SSE | 30s | — | — | `lm:ai.sse_first_token_timeout_ms` |
| LLM Orchestrator (온프레미스 sLLM) | SSE | 120s | — | — | `lm:ai.sse_first_token_timeout_ms` |

| 서비스 | 전체 스트리밍 제한 | SystemConfig 키 |
|--------|:-----------------:|----------------|
| parser-service | 30분 (BullMQ Job) | — |
| LLM Orchestrator (SaaS) | 120s | `lm:ai.sse_total_timeout_ms` |
| LLM Orchestrator (온프레미스 sLLM) | 300s | `lm:ai.sse_total_timeout_ms` |

> LLM Orchestrator SSE는 Job 타임아웃이 아닌 HTTP 클라이언트 레벨에서 전체 시간을 제한한다. 온프레미스 sLLM은 모델 로딩·컨텍스트 준비에 시간이 걸리므로 첫 토큰 타임아웃을 120s로 확장한다.

#### 비동기 호출 — BullMQ Job 타임아웃

| 큐 | 다운스트림 서비스 | Job 타임아웃 | 동시 처리 | 비고 |
|----|-----------------|:-----------:|:--------:|------|
| `upload` | MinIO | 2분 | 20 | I/O 바운드 |
| `parsing` | parser-service | 30분 | 2 | LLM+OCR, 가장 무거움 |
| `embedding` | retrieval-service | 5분 | 5 | GPU 바운드 |
| `ai-summary` | LLM Orchestrator | 2분 | 2 | LLM rate limit 종속 |
| `es-indexing` | Elasticsearch | 1분 | 3 | ES bulk 부하 |
| `export` | MinIO | 5분 | 3 | 렌더링+업로드 |

### 3.2 서킷 브레이커

| 서비스 | 실패 임계값 | 복구 대기 시간 | Half-Open 허용 수 | Fallback |
|--------|:----------:|:------------:|:-----------------:|---------|
| retrieval-service (동기) | 연속 5회 | 15s | 2 | 엔드포인트별 상이 (§4.2) |
| LLM Orchestrator | 연속 3회 | 30s | 1 | 503 반환 + 사용자 재시도 |
| Auth OrgProvider (외부 조직 API) | 최근 10회 중 5회 실패 또는 연속 3회 타임아웃(>500ms) | 30s | 1 | AICM DB Team 계층 직접 조회 |

> parser-service에는 서킷 브레이커를 적용하지 않는다. BullMQ Worker에서 비동기로 호출하므로 이벤트 루프에 영향이 없고, BullMQ 자체 재시도/DLQ로 관리한다.

### 3.3 재시도 정책

| 큐 | 재시도 횟수 | 백오프 | 기본 간격 | 최대 간격 | Jitter | DLQ |
|----|:----------:|--------|:--------:|:--------:|:------:|-----|
| `upload` | 3 | 지수 | 5s | 60s | — | `upload-dlq` |
| `parsing` | 3 | 지수 + 커스텀 | 10s (ECONNREFUSED: 30s) | 120s | Yes | `parsing-dlq` |
| `embedding` | 3 | 지수 | 5s | 60s | — | `embedding-dlq` |
| `ai-summary` | 3 | 지수 | 5s | 20s | — | `ai-summary-dlq` |
| `notification` | 3 | 지수 | 5s | 20s | — | `notification-dlq` |
| `es-indexing` | 3 | 지수 | 5s | 20s | — | `es-indexing-dlq` |
| 기타 (`board.events`, `acl.events`, `search-events`, `export`, `scheduled-publish`) | 3 | 지수 | 5s | 20s | — | 각 `{queue}-dlq` |

> `parsing` 큐는 ECONNREFUSED(서비스 다운) 시 첫 재시도 간격을 30s로 늘리고 jitter를 적용한다. 서비스 복구 직후 thundering herd를 방지하기 위함이다.

---

## 4. 서비스별 Fallback 전략

### 4.1 parser-service

비동기(BullMQ) 전용. 서킷 브레이커 미적용.

| 시나리오 | Fallback |
|---------|---------|
| 파싱 실패 (재시도 소진) | `parsing_status = 'failed'`, DLQ 이동. 사용자에게 실패 표시 |
| 이미지 업로드 부분 실패 | 해당 이미지 블록 `src` 빈 문자열 + warning. 파싱 계속 |
| `INVALID_CURSOR` | 기존 블록 전체 삭제, 커서 없이 처음부터 재파싱 |
| 사용자 명시적 취소 | 스트림 abort, 파서 생성 블록 전체 삭제 |

> 상세: [parser-service 연동](../temp/parser-service-integration.md)

### 4.2 retrieval-service

동기 호출에 서킷 브레이커 적용. 비동기(BullMQ)는 재시도/DLQ로 관리.

| 엔드포인트 | CB | Fallback |
|-----------|:--:|---------|
| `POST /search` | Yes | 시맨틱/하이브리드 불가 → **키워드 검색(ES `aicm_blocks` 직접 쿼리)**으로 graceful degradation. 사용자에게 "일부 검색 기능이 제한됩니다" 안내 |
| `PUT /config` | Yes | 설정 push 실패 → 로컬 캐시 유지 + 재시도 Job 등록 |
| `DELETE /sources/{sourceId}` | Yes | 삭제 마킹 → Reconciliation 배치에서 보정 |
| `DELETE /sources` (배치) | Yes | 부분 실패 허용 — `failed_sources`에 실패 건 포함. 실패 건은 단건 재시도 |
| `PATCH /sources/{sourceId}/metadata` | Yes | 3회 재시도 → `EMB_E002` 에스컬레이션. `is_suspended` 갱신 실패는 CRITICAL 로그 |
| `GET /sources/{sourceId}/chunks` | Yes | 해당 문서 스킵, 다음 Reconciliation 주기에 재시도 |
| `GET /health` | No | CB 상태 판단에만 사용. 사용자 영향 없음 |
| `POST /ingest/embed` (비동기) | No | BullMQ 재시도 3회 → DLQ |
| `POST /ingest/re-embed` (비동기) | No | BullMQ 재시도 3회 → DLQ |

> 상세: [retrieval-service 연동](../temp/retrieval-service-integration.md)

### 4.3 LLM Orchestrator

| 엔드포인트 | CB | Fallback |
|-----------|:--:|---------|
| `POST /llm/complete` (동기) | Yes | `EXTERNAL_SERVICE_UNAVAILABLE` (503) 반환. AI 기능 일시 불가 안내 |
| `POST /llm/complete/stream` (SSE) | Yes | SSE 에러 이벤트 전달 → 연결 종료 → 프론트엔드 재시도 버튼 노출 |
| `GET /usage/summary` | Yes | 503 반환. 통계 조회 불가 안내 |

> LLM 요청은 멱등하지 않으므로(동일 프롬프트에 다른 결과) 자동 재연결을 구현하지 않는다. 사용자에게 재시도를 위임한다. 상세: [외부 서비스 연동 §7](./06-external-integration.md)

### 4.4 Auth OrgProvider (외부 조직 API)

| 시나리오 | Fallback |
|---------|---------|
| 외부 API 장애 (CB Open) | `LocalOrgProvider` 로직 — AICM DB Team 계층에서 직접 조회. 정확도 낮지만 가용성 우선 |
| Redis 캐시 장애 | 외부 API 직접 호출. stale 캐시 사용 불가 (보안 — 최신 권한 데이터 필수) |

> 상세: [auth 캐시 설계](../03-module-design/auth/cache.md)

---

## 5. 에러 변환

### 5.1 동기 호출 공통 에러 변환

외부 서비스의 다양한 에러를 aicm-service 표준 에러 코드로 변환한다.

| 외부 서비스 응답 | aicm-service 변환 | HTTP | 비고 |
|----------------|-------------------|:----:|------|
| 연결 실패 (ECONNREFUSED) | `EXTERNAL_SERVICE_UNAVAILABLE` | 503 | CB Open 시 즉시 반환 |
| 타임아웃 (ETIMEDOUT) | `EXTERNAL_SERVICE_UNAVAILABLE` | 503 | |
| HTTP 4xx (클라이언트 에러) | `INTERNAL_SERVER_ERROR` | 500 | aicm-service 요청 구성 오류. WARN 로그 |
| HTTP 5xx (서버 에러) | `EXTERNAL_SERVICE_UNAVAILABLE` | 503 | |

> 모든 동기 호출에 `X-Trace-Id` 헤더를 전파하고, 서비스명·엔드포인트·HTTP 메서드·응답 시간·상태 코드·에러 메시지를 구조화 JSON으로 기록한다.

### 5.2 retrieval-service 에러 코드 매핑

| HTTP | 에러 코드 | 재시도 가능 | aicm-service 처리 |
|:----:|----------|:----------:|------------------|
| 400 | `INVALID_REQUEST` | No | 즉시 실패 |
| 400 | `BATCH_LIMIT_EXCEEDED` | No | 분할 후 재호출 |
| 404 | `SOURCE_NOT_FOUND` | No | 정상 처리 (이미 삭제됨) |
| 409 | `CONCURRENT_OPERATION` | Yes | 지수 백오프 재시도 |
| 422 | `EMPTY_BLOCKS` | No | 즉시 실패 (사전 필터링 누락) |
| 429 | `RATE_LIMITED` | Yes | 지수 백오프 재시도 |
| 500 | `INTERNAL_ERROR` | Yes | 재시도 대상 |
| 503 | `SERVICE_UNAVAILABLE` | Yes | CB 반영 |

### 5.3 parser-service 에러 코드 매핑

**HTTP 레벨 (스트리밍 시작 전)**:

| HTTP | 에러 코드 | 재시도 가능 | 처리 |
|:----:|----------|:----------:|------|
| 400 | `UNSUPPORTED_FORMAT` | No | 즉시 DLQ |
| 400 | `FILE_TOO_LARGE` | No | 즉시 DLQ |
| 400 | `INVALID_CURSOR` | 특수 | 커서 제거 + 처음부터 재파싱 |
| 404 | `FILE_NOT_FOUND` | No | 즉시 DLQ |
| 500 | `INTERNAL_ERROR` | Yes | 재시도 |
| 503 | `SERVICE_UNAVAILABLE` | Yes | 재시도 |

**스트림 내 (파싱 중)**:

| 에러 코드 | 재시도 가능 | 처리 |
|----------|:----------:|------|
| `PARSE_FAILED` (암호화, 심각한 손상) | No | 즉시 DLQ |
| `OCR_FAILED` | Yes | 경계 블록 삭제 + resume_cursor 재시도 |
| `IMAGE_UPLOAD_FAILED` | Yes | 경계 블록 삭제 + resume_cursor 재시도 |

---

## 6. Reconciliation (보정 배치)

서킷 브레이커 Open, 네트워크 일시 장애 등으로 누적된 불일치를 주기적으로 감지·보정한다.

| 배치 | 주기 | 대상 | 동작 |
|------|:----:|------|------|
| `reconciliation` | 10분 | 파싱/임베딩 실패 문서 | DB에서 `parsing_status = 'failed'` 또는 `embedding_status = 'failed'` 문서를 감지하여 해당 큐에 Job 재등록 |

> Reconciliation은 DLQ와 별개이다. DLQ는 재시도 소진 후 수동 개입이 필요한 Job을 보관하고, Reconciliation은 일시적 장애로 놓친 작업을 자동 감지하여 재시도한다.

---

## 7. 모니터링과 알림

### 7.1 핵심 메트릭

| 메트릭 | 수집 방식 | 알림 임계값 |
|--------|----------|-----------|
| 외부 서비스 응답 시간 | OpenTelemetry HTTP client 계측 | > 5초 (retrieval/parser) |
| 5xx 에러 비율 | HTTP 응답 코드 집계 | > 1% (5분 윈도우) |
| BullMQ 큐 대기 Job 수 | 큐별 주기적 폴링 | > 100건 (큐별) |
| DLQ 적체 건수 | DLQ 큐 폴링 | > 10건 |
| 서킷 브레이커 상태 변경 | Redis 키 변경 감지 | **Open 전환 시 CRITICAL** |

### 7.2 알림 채널

| 심각도 | 조건 | 채널 |
|--------|------|------|
| **CRITICAL** | CB Open 전환 (`circuit.*.state_change == Open`) | Slack + PagerDuty |
| **CRITICAL** | `is_suspended` 메타데이터 갱신 실패 | Slack + PagerDuty |
| WARNING | DLQ 적체 > 10건 | Slack |
| WARNING | 외부 서비스 p99 > 5초 | Slack |
| INFO | CB Half-Open → Closed (복구) | Slack |

### 7.3 CB 상태 모니터링 메트릭

| 메트릭 | 설명 |
|--------|------|
| `circuit.retrieval.state_change` | retrieval-service CB 상태 전이 |
| `auth.cache.org_provider.circuit_state` | Auth OrgProvider CB 상태 (closed/open/half-open) |
| `auth.cache.org_provider.fallback_count` | Auth OrgProvider fallback 호출 횟수 |

---

## 8. 패턴 결정 가이드

새로운 외부 서비스 호출을 추가할 때, 아래 결정 트리를 따른다.

```
외부 서비스 호출 추가
  │
  ├─ API 핸들러에서 동기 호출?
  │    ├─ Yes → 타임아웃 + 서킷 브레이커 + Fallback 필수
  │    │         └─ Fallback 유형 결정:
  │    │              ├─ 대체 데이터소스 있음? → 기능 축소 (graceful degradation)
  │    │              ├─ 후속 배치로 보정 가능? → 지연 처리
  │    │              └─ 둘 다 불가? → 사용자 재시도 위임 (503 + 안내 메시지)
  │    └─ No (Worker에서 비동기 호출)
  │         └─ BullMQ 재시도 + DLQ 필수
  │              ├─ 스트리밍? → 2단계 타임아웃 + heartbeat
  │              │              └─ 비용 높음? → 점진적 저장 + 커서 재개
  │              └─ 단발 요청? → 단일 타임아웃
  │
  └─ 에러 분류 필수
       ├─ 400/404/422 → non-retryable (즉시 DLQ)
       └─ 409/429/500/503 → retryable (지수 백오프)
```

**체크리스트** — 외부 호출 추가 시 확인 항목:

- [ ] 타임아웃 설정 (단일 or 2단계)
- [ ] 에러 분류 (retryable / non-retryable)
- [ ] 동기 호출이면 서킷 브레이커 적용
- [ ] Fallback 전략 정의
- [ ] 비동기 호출이면 재시도 정책 + DLQ 매핑
- [ ] 에러 변환 (`EXTERNAL_SERVICE_UNAVAILABLE` 등)
- [ ] `X-Trace-Id` 헤더 전파
- [ ] 구조화 로깅 (서비스명, 엔드포인트, 응답 시간, 상태 코드)
- [ ] 모니터링 메트릭 + 알림 임계값 정의

---

## 9. SystemConfig 키 일람

런타임에 조정 가능한 복원력 관련 설정 키이다. 값은 Admin UI에서 테넌트별로 오버라이드할 수 있다.

| 키 | 범주 | 기본값 | 설명 |
|----|------|-------|------|
| `pm:system.parser_first_line_timeout_ms` | 타임아웃 | 60,000 | parser-service 첫 라인 대기 |
| `pm:system.parser_inter_line_timeout_ms` | 타임아웃 | 90,000 | parser-service 라인 간 대기 |
| `pm:system.parsing_concurrency` | 동시성 | 2 | parsing 큐 동시 처리 수 |
| `lm:ai.sse_first_token_timeout_ms` | 타임아웃 | SaaS: 30,000 / sLLM: 120,000 | LLM SSE 첫 토큰 대기 |
| `lm:ai.sse_total_timeout_ms` | 타임아웃 | SaaS: 120,000 / sLLM: 300,000 | LLM SSE 전체 스트리밍 제한 |
| `pm:embedding.ingest_batch_size` | 배치 | 50 | 임베딩 배치당 블록 수 |

> 서킷 브레이커 임계값(실패 횟수, 복구 대기 시간)과 BullMQ 재시도 정책(횟수, 백오프 간격)은 현재 코드에 하드코딩되어 있다. 운영 중 튜닝이 필요하면 SystemConfig 키로 승격을 검토한다.

---

## 관련 문서

| 문서 | 역할 |
|------|------|
| [외부 서비스 연동](./06-external-integration.md) | 서비스별 API 스펙, 타임아웃/CB/Fallback 원천 정의 |
| [비동기 처리 아키텍처](./05-async-event-architecture.md) | BullMQ 큐 설계, 재시도/DLQ 정책 |
| [횡단 관심사](./07-cross-cutting-concerns.md) | 전역 에러 코드, BusinessException 패턴, 모니터링 메트릭 |
| [비동기 처리 아키텍처](./05-async-event-architecture.md) | BullMQ 큐 목록, DLQ 매핑, 관리자 API |
| [parser-service 연동](../temp/parser-service-integration.md) | 점진적 저장, 커서 재개, 스트리밍 에러 처리 상세 |
| [retrieval-service 연동](../temp/retrieval-service-integration.md) | 엔드포인트별 CB/Fallback, 에러 코드 매핑 상세 |
| [auth 캐시 설계](../03-module-design/auth/cache.md) | OrgProvider CB, Redis 캐시 장애 대응 |
| [search 모듈 설계](../03-module-design/search/README.md) | CB 상태 Redis 키, 모니터링 이벤트 |
