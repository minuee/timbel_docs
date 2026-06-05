# 모듈 스펙 리뷰 — Search (MS-SCH)

| 항목 | 값 |
|------|---|
| 리뷰 대상 | `docs/03-module-design/search/` (README, api, data, events, schedule, rules) |
| 페르소나 | 시니어 백엔드 개발자 — 최민재 |
| 루브릭 | 모듈 스펙 루브릭 (§4) + 시니어 개발자 전문 루브릭 |
| 리뷰 포커스 | SearchRepository/ElasticsearchSearchAdapter 추상화 반영 일관성 |
| 리뷰 일시 | 2026-04-03 |

---

## 1. 종합 점수

| 계층 | 점수 | 비율 |
|------|:----:|:----:|
| 공용 루브릭 | **71** | 60% |
| 전문 루브릭 | **67** | 40% |
| **종합** | **69** | — |

**판정: 양호 (60~79)**
— 대부분 견고하나, SearchRepository 추상화 완결성과 일부 참조 정합성에서 소수 개선 권고가 존재한다.

---

## 2. 공용 루브릭 채점

### RD-MS-01 — API 설계 품질 (가중치 30%)

**점수: 70**

**잘 된 점:**
- api.md에 30개 이상의 엔드포인트가 TypeScript 인터페이스로 상세 정의되어 있다. `KeywordSearchDto`, `RagSearchDto`, `SearchConfigDto` 등 DTO 구조가 명확하다.
- 페이지네이션 패턴이 `meta: { page, limit, totalItems, totalPages }`로 일관적이다.
- 에러 코드가 `rules.md §3`과 1:1 매핑되고, 각 API 엔드포인트에 관련 BR이 명시되어 있다.
- HTTP 상태 코드가 의미에 맞게 사용된다: `201`(생성), `202`(비동기 내보내기), `409`(OCC 충돌), `422`(비즈니스 제약 위반).

**개선 필요:**

1. **api.md `POST /search` 설명에 ES 직접 언급** — "ES `aicm_blocks` 인덱스에 대한 풀텍스트 검색"이라고 기술되어 있다. SearchRepository 추상화를 반영하여 "SearchRepository를 통한 `aicm_blocks` 풀텍스트 검색"으로 수정해야 한다. rules.md와 README.md는 일관되게 SearchRepository를 경유하는 표현을 사용하고 있어 api.md만 불일치한다.

2. **`mode: 'all'` API 엔드포인트 부재** — README.md `SearchQueryDto`에 `mode?: 'keyword' | 'ai' | 'all'`이 정의되고, 피처 게이트 테이블에서 `mode=all`의 폴백 동작까지 상세히 기술되어 있다. 그러나 api.md에는 이 모드를 수용하는 엔드포인트가 없다. `POST /search`(키워드 전용)와 `POST /search/rag`(RAG 전용)만 있어, 키워드+RAG 병합 결과를 반환하는 경로가 외부 API로 노출되지 않는다. 이 모드가 내부 전용이라면 README에서 명시해야 하고, 클라이언트에 노출한다면 api.md에 정의해야 한다.

3. ~~**카테고리 필터 누락**~~ — ~~해소됨: Category 엔티티가 폐지되고 게시판 트리(Board.parent_id)로 대체되어 `categoryIds` 필터는 더 이상 필요하지 않다.~~

4. **FD와 필드명 불일치** — FD-SCH §7.1은 페이지 크기를 `size`로, 모듈 스펙 api.md는 `limit`로 정의한다. 기능 차이는 아니나 FD를 기준으로 구현하는 팀원에게 혼란을 줄 수 있다. 어느 쪽이 최종인지 data dictionary 또는 용어 정의에서 통일하는 것을 권장한다.

---

### RD-MS-02 — 구현 변환 용이성 (가중치 10%)

**점수: 62**

**잘 된 점:**
- data.md에 DDL이 제약 조건·인덱스까지 완비되어 있어 DB 레이어 구현은 즉시 착수 가능하다.
- 각 비즈니스 규칙(BR)의 트리거/조건/동작이 구체적이고, API ↔ BR 매핑이 명확하다.

**개선 필요:**

1. **SearchRepository 인터페이스 미정의** — README, data.md, rules.md, events.md, schedule.md 전체에서 "SearchRepository"를 참조하지만, 실제 메서드 시그니처가 어디에도 없다. 주니어 개발자가 이 문서만으로 Adapter를 구현하려면 최소한 아래 수준의 인터페이스가 필요하다:

```typescript
// 예시 — 실제 정의가 필요한 시그니처
interface SearchRepository {
  search(query: SearchQuery): Promise<SearchResult>;
  indexDocument(doc: IndexableDocument): Promise<void>;
  deleteDocument(documentId: string): Promise<void>;
  updateDocumentMeta(documentId: string, meta: Partial<IndexMeta>): Promise<void>;
  listIndexedDocumentIds(): Promise<string[]>;
  // ...
}
```

아키텍처 문서(02-module-architecture.md §3.3 규칙4)에서 "SearchRepository 인터페이스를 정의하고"라고 명시했으므로, 모듈 스펙 수준에서 이 인터페이스를 정의해야 한다. api.md에 별도 섹션으로 추가하거나 `interfaces.md`를 신설하는 것을 권장한다.

2. **ElasticsearchSearchAdapter 구현 가이드** — es.md가 매핑·쿼리 패턴을 잘 문서화하고 있으나, SearchRepository의 각 메서드가 es.md의 어떤 쿼리 패턴에 매핑되는지 연결 문서가 없다. BR-SCH-001은 "SearchRepository를 통해 키워드 검색... ElasticsearchSearchAdapter에서는 ES multi_match 쿼리로 구현"이라고 기술하고 있어 힌트는 있지만, 체계적 매핑이 아닌 산발적 언급이다.

---

### RD-MS-03 — 이벤트/비동기 설계 건전성 (가중치 25%)

**점수: 73**

**잘 된 점:**
- events.md의 2계층 구조(매트릭스 요약 → 상세)가 체계적이다.
- 모든 BullMQ 이벤트에 TypeScript 페이로드 인터페이스가 정의되어 있다.
- 멱등성 전략이 이벤트별로 구체적이다: `documentId+version`, `eventId` UUID+Redis TTL 등 (events.md §7).
- DLQ가 `es-indexing:dlq`, `search-events:dlq` 2개 큐에 대해 정의되어 있다 (events.md §6).
- RetrievalServiceClient에 서킷브레이커(`{tenant_id}:circuit:retrieval-service`)와 타임아웃(검색 10s/설정 5s)이 정의되어 있다 (events.md §4.1).
- schedule.md의 Reconciliation 배치가 분산 락·실패 처리·동시 실행 제어까지 상세하다.

**개선 필요:**

1. **벡터 DB 보정 배치 부재** — schedule.md §2.1의 Reconciliation은 RDB ↔ ES 불일치만 보정한다. 그러나 RAG 검색은 벡터 DB(Milvus)에 의존하며, 임베딩 실패·부분 실패 시 RDB ↔ Milvus 불일치도 발생할 수 있다. events.md §3.6 `shared-content.updated`에서도 "임베딩 재처리는 Best-effort (실패 시 다음 Reconciliation 배치에서 보정)"이라고 기술하지만, 해당 Reconciliation 배치가 ES만 커버한다. Milvus 보정은 retrieval-service 책임일 수 있으나, 그렇다면 그 책임 경계를 명시해야 한다.

2. **인덱싱 경로의 추상화 부재** — events.md §3.1~3.8의 처리 절차가 "ES `aicm_blocks` 인덱스에 문서 블록 인덱싱"으로 직접 ES를 참조한다. SearchRepository 추상화가 검색(read) 경로에만 적용되고 인덱싱(write) 경로에는 적용되지 않은 상태이다. 02-module-architecture.md §3.3 규칙4가 "검색 엔진 접근"을 포괄적으로 추상화하라고 명시하므로, 인덱싱 경로도 `SearchIndexWriter` 또는 `SearchRepository.index*()` 메서드로 추상화해야 검색 솔루션 교체 시 Adapter만 교체하겠다는 목표가 달성된다.

3. **`document.content-updated` 등 개별 이벤트 재시도 파라미터 누락** — `document.published` (§3.1)는 "최대 3회, 지수 백오프 (초기 5s, 최대 120s)"로 구체적이나, `document.content-updated`(§3.2), `document.deleted`(§3.3), `document.suspended/unsuspended`(§3.4) 등은 재시도 정책이 명시되지 않았다. 모두 같은 `es-indexing` 큐를 사용하므로 큐 레벨 재시도를 의미하는 것 같지만, 명시적으로 "es-indexing 큐 공통 재시도: 최대 3회, 5s~120s"라고 한 곳에 선언하고 참조하는 것이 안전하다.

4. **`parsing.completed` 재시도 구체 파라미터 미기재** — events.md §3.8에 "최대 3회, 지수 백오프"만 있고 초기 지연·최대 지연이 빠져 있다. 다른 이벤트와 형식을 맞춰야 한다.

---

### RD-MS-04 — 모듈 책임 범위 적절성 (가중치 15%)

**점수: 78**

**잘 된 점:**
- 파싱 책임을 ParsingModule로 분리하고 "파싱 설정 CRUD는 ParsingModule이 소유한다. SearchModule 관리자 API에서 프록시한다"(README)로 경계를 명확히 했다.
- "현재 범위 제외 기능" 테이블(Playground, 멀티턴 RAG, 개인화 랭킹)에서 Phase 2 기능을 명시적으로 제외하고 FD 참조까지 연결했다.
- SearchLog를 감사 로그(LogEventModule)와 명확히 분리한 설계 결정이 기술되어 있다 (data.md §2.6).

**개선 필요:**

1. **검색 인덱싱 워커의 모듈 소속 모호** — events.md에서 정의하는 `es-indexing` 큐 워커는 SearchModule의 일부인지, 별도 인프라 워커인지 명시되지 않았다. document.published 이벤트를 소비하여 ES에 인덱싱하는 워커가 SearchModule 서비스인지 확인이 필요하다. README의 "인프라 사용 요약"에서 EventBus를 "●발행/소비"로 표기하고 있어 SearchModule이 소비하는 것은 알 수 있으나, 워커 클래스의 위치(services/ vs workers/)가 모호하다.

---

### RD-MS-05 — 모듈 간 계약 명확성 (가중치 10%)

**점수: 68**

**잘 된 점:**
- 의존 관계 다이어그램이 mermaid로 명확하며, `읽기` / `RAG 검색 위임` / `설정 push` 3가지 의존 유형이 구분된다.
- 의존 방향이 02-module-architecture.md §3.3.1의 매트릭스와 일치한다.

**개선 필요:**

1. **retrieval-service 설정 push 계약 미정의** — events.md §4.1에서 "설정 push"와 "RAG 검색 위임"을 언급하지만, `PUT /config`(설정 push)의 요청/응답 페이로드가 정의되지 않았다. `search.config.updated` 이벤트의 페이로드는 있지만 이것은 이벤트 페이로드이고, retrieval-service HTTP API 계약은 다르다. 최소한 요청 필드 목록과 예상 응답 코드를 기술해야 한다.

2. **DocumentModule 조회 범위 불명확** — README의 의존 테이블에 "검색 결과 메타데이터 보강 (제목, 작성자, 태그, 게시판명 등)"이라고 기술되어 있으나, ES `aicm_blocks` 인덱스에 이미 `document_id`, `board_id`, `tags`가 비정규화되어 있다 (es.md §1.2). DocumentModule에서 추가로 조회해야 하는 필드(작성자명, 게시판명, embeddingStatus 등)를 명시적으로 나열하면 구현 시 불필요한 조회를 줄일 수 있다.

---

### RD-MS-06 — 운영 고려사항 (가중치 10%)

**점수: 72**

**잘 된 점:**
- 주요 메트릭 7개(README §주요 메트릭)와 알림 임계값 5개(README §모니터링 알림 임계값)가 구체적이다.
- 외부 설정값 카탈로그(4개 키)가 `lm:`/`sc:` 접두사와 기본값, 용도, 참조까지 정리되어 있다.
- 피처 게이트 기반 Graceful Degradation이 모드별 동작 테이블로 명확하다.

**개선 필요:**

1. **배포 시 ES 인덱스 마이그레이션 전략 미기술** — 동의어/불용어 설정 변경 시 "ES 인덱스 close → 설정 적용 → reopen"이 필요하다고 기술하지만(BR-SCH-024, FD-SCH §6.5), SearchModule 배포 자체에서 인덱스 매핑 변경이 필요한 경우의 전략(reindex API, alias swap 등)이 없다.

2. **헬스체크 항목** — README에 SearchModule 전용 헬스 포인트(ES 연결, retrieval-service 연결)가 없다. 02-module-architecture.md의 HealthModule이 전체를 커버한다고 하지만, SearchModule 관점에서 의존 서비스 상태를 별도로 모니터링할 필요가 있다.

---

## 3. 전문 루브릭 채점

### EX-MS-SR-01 — 런타임 안정성 설계 (가중치 50%)

**점수: 70**

**잘 된 점:**
- retrieval-service에 대해 **서킷브레이커 + 타임아웃 + 폴백** 3중 방어가 완비되어 있다 (events.md §4.1).
- BullMQ `es-indexing` 큐의 재시도(3회, 지수 백오프 5s→120s)와 DLQ가 정의되어 있다.
- 멱등성 키가 모든 이벤트 핸들러에 정의되어 있다 (events.md §7).
- 분산 락이 배치 작업에 TTL과 함께 정의되어 있다 (schedule.md §2.1, §2.2).
- Reconciliation 배치가 개별 문서 실패 시 건너뛰고 계속하는 내결함성 전략이 있다.

**개선 필요:**

1. **ElasticsearchSearchAdapter 타임아웃/서킷브레이커 미정의** — retrieval-service에는 서킷브레이커(`{tenant_id}:circuit:retrieval-service`)와 타임아웃(10s/5s)이 명시되어 있으나, ES 키워드 검색에 대한 동일 수준의 안정성 설계가 없다. README에서 "키워드 검색(SearchRepository)은 어떤 환경에서도 동작한다"고 선언하지만, ES 자체의 장애(노드 다운, GC pause, slow query)에 대한 방어가 없다. 최소한 ES 검색 타임아웃과 ES 연결 장애 시 동작(503 반환 등)을 정의해야 한다.

2. **DLQ 자동 처리 부재** — events.md §6에서 DLQ 처리 방식이 "관리자 재처리 또는 Reconciliation 배치에서 자동 보정"이라고 되어 있다. Reconciliation이 30분마다 실행되므로 어느 정도 커버되지만, DLQ에 쌓인 메시지를 자동으로 재처리하는 메커니즘(예: DLQ consumer, 일정 주기 재시도)은 없다. 운영 중 DLQ에 수천 건이 쌓이면 관리자가 수동으로 처리해야 하는 상황이 발생할 수 있다.

---

### EX-MS-SR-02 — 참조 무결성 (가중치 50%)

**점수: 63**

**잘 된 점:**
- BR-SCH-001~044 → api.md 에러 코드·권한 매핑이 빠짐없다.
- 엔티티(data.md) ↔ DDL ↔ README 핵심 엔티티 테이블이 일관적이다.
- 발행/소비 이벤트가 README(인프라 사용 요약), events.md(매트릭스), FD-SCH(§9)에서 일관적이다.

**개선 필요:**

1. **SearchRepository — 20회 이상 참조, 0회 정의** — 모듈 스펙 전체에서 가장 큰 참조 무결성 문제이다. "정의만 있고 참조 없는 항목"은 없지만, 반대로 "참조만 있고 정의 없는 항목"이 SearchRepository이다. README, data.md, rules.md, events.md, schedule.md에서 일관되게 참조하지만 인터페이스 시그니처가 어디에도 없다. 이는 RD-MS-02에서도 지적한 핵심 문제이다.

2. **README `SearchQueryDto` ↔ api.md 단절** — README.md의 피처 게이트 섹션에 정의된 `SearchQueryDto` (mode: 'keyword' | 'ai' | 'all')가 api.md의 어떤 DTO와도 매핑되지 않는다. 내부 서비스 DTO라면 README에 명시해야 하고, 외부 API DTO라면 api.md에 반영해야 한다.

3. **에러 코드 매핑 누락** — rules.md §3에 `SCH_EXCLUDE_TARGET_NOT_FOUND` (404)가 정의되어 있고 BR-SCH-029에 연결되어 있으나, api.md의 `POST /admin/search/exclude` 에러 테이블에 이 코드가 없다.

4. **FD ↔ 모듈 스펙 기본값 불일치 미문서화** — FD-SCH §6.5의 SearchConfig 기본값과 data.md의 기본값이 다른 항목이 있다:

| 필드 | FD 기본값 | 모듈 스펙 기본값 | 비고 |
|------|----------|----------------|------|
| title weight | 3.0 | 2.0 (`kw_title_weight`) | FD는 JSONB `field_weights`, 모듈 스펙은 개별 컬럼 |
| tags weight | 2.0 | 1.5 (`kw_tag_weight`) | |
| caption weight | (없음) | 1.5 (`kw_caption_weight`) | FD에 캡션 가중치 미정의 |
| top_k | 10 | 20 (`rag_top_k`) | |
| hybrid BM25 | 0.50 | 0.40 (`rag_hybrid_bm25_weight`) | |
| hybrid vector | 0.50 | 0.60 (`rag_hybrid_vector_weight`) | |

JSONB → 개별 컬럼 전환은 ADR-009에서 설명되지만, 기본값 변경 사유는 문서화되어 있지 않다. data.md의 "설계 결정" 섹션에 기본값 조정 근거를 추가해야 한다.

---

## 4. 지적사항 요약

### P1 — 치명

| # | 차원 | 지적사항 | 영향 범위 | 대안 |
|---|------|---------|----------|------|
| 1 | RD-MS-02, EX-MS-SR-02 | **SearchRepository 인터페이스 미정의** — 모듈 전반에서 20회 이상 참조되지만 메서드 시그니처가 없다 | 구현 착수 시 개발자가 SearchRepository의 메서드를 추측해야 하며, 다이퀘스트 등 대체 어댑터 구현 시 계약이 모호하여 API 불일치 위험 | api.md에 `## SearchRepository 인터페이스` 섹션을 추가하고, 최소한 `search()`, `index()`, `delete()`, `updateMeta()`, `listDocumentIds()` 등 핵심 메서드 시그니처를 TypeScript 인터페이스로 정의한다. es.md의 쿼리 패턴과 각 메서드의 매핑도 명시한다 |
| 2 | RD-MS-03, EX-MS-SR-01 | **인덱싱(write) 경로의 추상화 부재** — events.md의 모든 인덱싱 핸들러가 "ES `aicm_blocks` 인덱스에" 직접 기술되어 있어, 검색 솔루션 교체 시 이벤트 핸들러 전체를 수정해야 한다. 02-module-architecture.md §3.3 규칙4가 "검색 엔진 접근"을 포괄적으로 추상화하라고 명시한 것과 불일치 | 검색 엔진 교체(B2B 납품 시나리오) 시 read 경로만 Adapter 교체로는 불충분. write 경로(인덱싱)도 수정 필요 → Adapter 교체만으로 동작한다는 아키텍처 약속 위반 | SearchRepository 인터페이스에 인덱싱 메서드(`indexDocument`, `deleteDocument`, `updateDocumentMeta`)를 포함하거나, 별도 `SearchIndexWriter` 인터페이스를 정의한다. events.md의 처리 절차를 "SearchRepository를 통해 인덱싱"으로 통일한다 |

### P2 — 중요

| # | 차원 | 지적사항 | 조치 제안 |
|---|------|---------|----------|
| 3 | EX-MS-SR-01 | **ES 키워드 검색 타임아웃/장애 대응 미정의** — retrieval-service는 서킷브레이커+타임아웃이 있으나 ES는 없다. ES 장애 시 키워드 검색의 동작이 정의되지 않음 | events.md §4에 `ElasticsearchSearchAdapter` 전용 타임아웃(예: 검색 3s, 인덱싱 5s)과 장애 시 503 반환 동작을 추가한다. 서킷브레이커 도입 여부도 검토 |
| 4 | RD-MS-01 | **api.md `POST /search`에 ES 직접 언급** — 설명문이 "ES `aicm_blocks`"로 시작하여 SearchRepository 추상화와 불일치 | "SearchRepository를 통한 `aicm_blocks` 풀텍스트 검색"으로 수정 |
| 5 | RD-MS-01 | ~~**카테고리 필터(`categoryIds`) 누락**~~ — 해소됨: Category 폐지로 불필요 | 조치 불필요 |
| 6 | RD-MS-03 | **벡터 DB(Milvus) Reconciliation 부재** — ES 보정은 있으나 Milvus 보정이 없다 | retrieval-service 책임이면 그 경계를 events.md에 명시. SearchModule 책임이면 schedule.md에 Milvus Reconciliation 배치 추가 |
| 7 | RD-MS-01, EX-MS-SR-02 | **`mode: 'all'` API 미정의** — README에서 상세히 기술된 mode=all 동작에 대응하는 API가 없다 | (a) `POST /search`에 `mode` 필드를 추가하여 통합 검색 엔드포인트로 확장하거나, (b) mode=all이 프론트엔드의 클라이언트 사이드 병합이라면 README에 "클라이언트 오케스트레이션" 명시 |
| 8 | EX-MS-SR-02 | **`SCH_EXCLUDE_TARGET_NOT_FOUND` 에러 코드 api.md 미연결** — rules.md §3에 정의되었으나 `POST /admin/search/exclude` 에러 테이블에 누락 | api.md의 해당 엔드포인트 에러 코드 테이블에 추가 |
| 9 | EX-MS-SR-02 | **FD ↔ 모듈 스펙 기본값 차이 미문서화** — title weight 3.0→2.0, top_k 10→20 등 6건의 기본값 변경 사유가 없다 | data.md "설계 결정"에 기본값 조정 근거 (예: "nori 한국어 분석기 특성상 제목 가중치 2.0이 적정" 등)를 추가 |

### P3 — 개선 권고

| # | 차원 | 지적사항 | 조치 제안 |
|---|------|---------|----------|
| 10 | RD-MS-03 | **es-indexing 큐 공통 재시도 정책 미선언** — document.published만 구체 값이 있고, content-updated/deleted/suspended 등은 암묵적 | events.md에 "es-indexing 큐 공통: 최대 3회, 지수 백오프, 초기 5s, 최대 120s, DLQ es-indexing:dlq" 한 줄 선언 후 각 이벤트에서 참조 |
| 11 | RD-MS-03 | **`parsing.completed` 재시도 구체 파라미터** — "최대 3회, 지수 백오프"만 기술 | 초기 지연, 최대 지연 값 추가 |
| 12 | RD-MS-06 | **배포 시 ES 인덱스 매핑 변경 전략** — 인덱스 스키마 변경이 필요한 배포의 처리 방법이 없다 | alias swap + reindex 전략 또는 "매핑 변경 시 운영 절차" 섹션을 README에 추가 |
| 13 | RD-MS-05 | **retrieval-service 설정 push HTTP 계약 미정의** — 이벤트 페이로드는 있으나 HTTP `PUT /config` 계약이 없다 | events.md §4.1에 HTTP 요청/응답 스키마 추가 또는 retrieval-service 문서 참조 링크 |
| 14 | RD-MS-04 | **es-indexing 워커의 모듈 소속 명시** — SearchModule 서비스인지 별도 워커인지 모호 | README의 모듈 책임 또는 디렉토리 구조에서 워커 위치를 명시 |

---

## 5. SearchRepository 추상화 반영 일관성 (리뷰 포커스 종합)

SearchRepository 인터페이스 + ElasticsearchSearchAdapter 추상화 도입은 전반적으로 **읽기(검색) 경로에서는 잘 반영**되었으나, **쓰기(인덱싱) 경로와 인터페이스 정의에서 불완전**하다.

| 문서 | 읽기 경로 | 쓰기 경로 | 평가 |
|------|:---------:|:---------:|------|
| README.md | SearchRepository 일관 사용 | — (쓰기 경로 없음) | **양호** |
| data.md | "SearchRepository(ElasticsearchSearchAdapter)를 통해 적용" | — | **양호** |
| rules.md | 모든 검색 BR에서 "SearchRepository를 통해" + "ElasticsearchSearchAdapter에서는" 패턴 | BR-SCH-029 인덱스 마킹: "SearchRepository를 통해" | **양호** |
| events.md | §5 피처 게이트: "SearchRepository 기반" | §3.1~3.8 인덱싱: **"ES aicm_blocks 인덱스에" 직접 참조** | **불일치** |
| schedule.md | §2.1 Reconciliation 읽기: "SearchRepository를 통해" | — | **양호** |
| api.md | `POST /search` 설명: **"ES aicm_blocks 인덱스"** | — | **불일치** |

**핵심 권고**: events.md의 인덱싱 경로와 api.md의 검색 설명을 SearchRepository 표현으로 통일하고, SearchRepository 인터페이스에 인덱싱 메서드를 포함하여 read/write 양 경로의 추상화를 완결해야 한다.

---

## 6. 점수 상세

### 공용 루브릭 상세

| ID | 차원 | 가중치 | 점수 | 가중 점수 |
|----|------|:------:|:----:|:---------:|
| RD-MS-01 | API 설계 품질 | 30% | 70 | 21.0 |
| RD-MS-02 | 구현 변환 용이성 | 10% | 62 | 6.2 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 25% | 73 | 18.3 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 15% | 78 | 11.7 |
| RD-MS-05 | 모듈 간 계약 명확성 | 10% | 68 | 6.8 |
| RD-MS-06 | 운영 고려사항 | 10% | 72 | 7.2 |
| | | **합계** | | **71** |

### 전문 루브릭 상세

| ID | 차원 | 가중치 | 점수 | 가중 점수 |
|----|------|:------:|:----:|:---------:|
| EX-MS-SR-01 | 런타임 안정성 설계 | 50% | 70 | 35.0 |
| EX-MS-SR-02 | 참조 무결성 | 50% | 63 | 31.5 |
| | | **합계** | | **67** |

### 종합 산출

```
종합 = 71 × 0.60 + 67 × 0.40 = 42.6 + 26.8 = 69.4 → 69
```
