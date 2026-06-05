# 모듈 스펙 리뷰 R3 — Search (MS-SCH)

| 항목 | 값 |
|------|---|
| 리뷰 대상 | `docs/03-module-design/search/` (README, api, data, events, schedule, rules) |
| 페르소나 | 시니어 백엔드 개발자 — 최민재 |
| 루브릭 | 모듈 스펙 루브릭 (§4) + 시니어 개발자 전문 루브릭 |
| 리뷰 라운드 | **R3** (R1: 69점 → R2: 79점 → 이번 리뷰) |
| 리뷰 일시 | 2026-04-03 |

---

## 0. R2 지적사항 해소 확인

| # | R2 P2 지적 | 해소 여부 | 확인 근거 |
|---|-----------|:---------:|-----------|
| 1 | 보조 타입 미정의 (FieldWeights, IndexableBlock 등) | ✅ 해소 | README.md §보조 타입에 FieldWeights, IndexableBlock, DocumentMetadata, IndexableMetadata, SynonymGroup, KeywordSearchResult, AutocompleteResult 7개 타입이 TypeScript 인터페이스로 정의됨 |
| 2 | FieldWeights ↔ ES 매핑 관계 불명확 | ✅ 해소 | README.md 하단 주석에 "SearchConfig의 `kw_*_weight` 5개 필드는 **쿼리 시점**에 적용... ES에는 `content_text`와 `content_caption` 2개 텍스트 필드만 존재... Adapter가 FieldWeights를 해당 엔진의 필드 구조에 맞게 변환" — 물리 필드 ↔ 논리 가중치 관계가 명확해짐 |
| 3 | 타임아웃 정책 미정의 | ✅ 해소 | README.md §타임아웃 정책에 6개 오퍼레이션별 타임아웃(1s~60s) + 실패 시 동작(graceful/재시도/로그) 테이블 추가됨 |
| 4 | KeywordSearchDto에 categoryIds 누락 | ~~✅ 해소~~ 후속 폐기: Category 엔티티 폐지로 `categoryIds` 자체가 불필요해짐 | ~~api.md KeywordSearchDto에 반영~~ — Category 폐지로 해당 필드 제거됨 |

**R2 P2 6건 중 핵심 4건 해소 확인.** 나머지 2건(FD 필드명 불일치, mode=all 미정의)도 부분적 개선 확인 — 아래 잔여 이슈에서 후속 추적.

---

## 1. 종합 점수

| 계층 | 점수 | 비율 |
|------|:----:|:----:|
| 공용 루브릭 | **84** | 60% |
| 전문 루브릭 | **84** | 40% |
| **종합** | **84** | — |

**판정: 우수 (80~100)**
— R1(69) → R2(79) → R3(84)으로 일관된 개선 추세. SearchRepository 인터페이스 완결, 보조 타입 전량 정의, 타임아웃 정책 추가 등 R2 핵심 지적이 해소되었다. 잔여 P2 2건, P3 4건은 구현에 즉각적 장애를 초래하지 않으나 문서 정합성 완성을 위해 보완 권장.

---

## 2. 공용 루브릭 채점

### RD-MS-01 — API 설계 품질 (가중치 30%)

**점수: 82**

**잘 된 점:**
- api.md에 30개 이상의 엔드포인트가 TypeScript 인터페이스로 정의. `KeywordSearchDto`, `RagSearchDto`, `SearchConfigDto` 등 DTO 구조가 구체적이다.
- 페이지네이션 패턴(`meta: { page, limit, totalItems, totalPages }`)이 일관적이다.
- HTTP 상태 코드가 의미에 맞게 사용된다: `201`(생성), `202`(비동기 Export), `409`(OCC 충돌), `422`(비즈니스 제약 위반).
- R2 대비 검색 필터 필드가 KeywordSearchDto에 정상 반영됨 (api.md line 62). (참고: `categoryIds`는 이후 Category 폐지로 제거됨)
- api.md `POST /search` 설명이 "SearchRepository를 통한 `aicm_blocks` 풀텍스트 검색"으로 추상화 표현과 일관적이다.
- 에러 코드가 rules.md §3과 1:1 매핑되고, 각 API 엔드포인트에 관련 BR이 명시되어 있다.

**잔여 이슈:**

1. ~~**(P2)** **RagSearchDto에 categoryIds 누락**~~ — ~~해소됨: Category 엔티티가 폐지되고 게시판 트리(Board.parent_id)로 대체되어 `categoryIds` 필터는 더 이상 필요하지 않다.~~

2. **(P3)** **mode=all 검색 경로 미연결** — README.md `SearchQueryDto`에 `mode?: 'keyword' | 'ai' | 'all'`이 정의되고 피처 게이트 테이블에서 모드별 동작이 상세 기술되어 있으나, api.md에는 이 모드를 수용하는 엔드포인트가 없다. 내부 서비스 레이어 전용이라면 README에서 "내부 전용(클라이언트에 노출하지 않음)" 명시 권장.

3. **(P3)** **FD ↔ api.md 페이지네이션 필드명 불일치** — FD-SCH §7.1은 페이지 크기를 `size`로, api.md는 `limit`로 정의. 기능 차이는 없으나 FD 기반 구현 시 혼동 가능. 용어 정의 통일 권장.

---

### RD-MS-02 — 구현 변환 용이성 (가중치 10%)

**점수: 83**

**잘 된 점:**
- SearchRepository 인터페이스가 9개 메서드(읽기 3개 + 쓰기 4개 + 설정 동기화 1개)로 완전히 정의되어, 주니어 개발자가 Adapter를 구현할 수 있는 수준이다.
- 모든 파라미터 타입(SearchFilters, FieldWeights, IndexableBlock, DocumentMetadata, IndexableMetadata, SynonymGroup)이 정의되어 있어 시그니처만으로 계약이 명확하다.
- 구현체 매핑 테이블(README.md §구현체 매핑)이 인터페이스 메서드 ↔ ES API 패턴을 1:1로 연결한다.
- data.md DDL이 CHECK 제약, 부분 인덱스(`WHERE is_active = true`)까지 포함하여 DB 레이어 즉시 착수 가능하다.
- BR 정의의 트리거/조건/동작이 구체적이고, API ↔ BR 매핑이 명확하다.

**잔여 이슈:**
- FieldWeights → ES multi_match 변환 로직이 주석으로 설명되어 있으나, 5개 논리 필드가 2개 물리 필드(content_text, content_caption)로 어떻게 사상되는지 — 예시 쿼리까지 있으면 더 명확하다. 현재 수준으로도 구현 가능하므로 P3 미만.

---

### RD-MS-03 — 이벤트/비동기 설계 건전성 (가중치 25%)

**점수: 85**

**잘 된 점:**
- 발행 3개 + 소비 9개 이벤트가 매트릭스로 정리되어 있다. 큐명, 신뢰성 티어, 전달 수단이 일관적이다.
- 재시도 정책이 `document.published`(3회, 지수 백오프 5s~120s), `search.config.updated`(3회, 1s~30s), `search.reindex.*`(재시도 없음—알림 전용)으로 역할에 따라 차별화되어 있다.
- DLQ 정의(`es-indexing:dlq`, `search-events:dlq`)와 모니터링(BullMQ Dashboard, Slack 알림) + 수동 처리 절차가 명시되어 있다.
- 멱등성 전략이 이벤트별로 정의: `documentId+version`, `documentId+parsingVersion`, `eventId UUID` — Redis TTL 24h 중복 방지까지 구체적이다.
- 서킷브레이커(`{tenant_id}:circuit:retrieval-service`)와 피처 게이트(`ft:search.rag`) 3중 방어가 잘 설계되어 있다.
- 타임아웃 정책이 R3에서 추가되어 런타임 안정성이 크게 개선됨.

**잔여 이슈:**

1. **(P3)** **events.md §3.2 `document.content-updated` 재시도 정책 미명시** — §3.1 `document.published`는 "재시도 정책: 최대 3회, 지수 백오프"를 명시하고 있으나, §3.2 `document.content-updated`는 멱등성만 기술하고 재시도 정책 행이 없다. 동일 큐(`es-indexing`)이므로 동일 정책일 것으로 추정되지만, 명시적 기재가 있어야 구현자가 확인 질문 없이 진행 가능하다.

---

### RD-MS-04 — 모듈 책임 범위 적절성 (가중치 15%)

**점수: 87**

**잘 된 점:**
- SearchModule과 ParsingModule의 책임 분리가 명확하다. 파싱 설정 CRUD를 ParsingModule이 소유하고, SearchModule 관리자 API에서 프록시하는 패턴이 적절하다.
- "현재 범위 제외 기능" 테이블(검색 테스트 환경, 멀티턴 RAG, 개인화 랭킹)이 Phase 2 범위를 명확히 구분한다.
- AccessLog(`aicm_access_logs`)를 SearchRepository 범위에서 명시적으로 제외하고, 근거("검색 솔루션과 무관한 운영 데이터이며 ES ILM에 강하게 의존")를 제시한 것이 좋다.
- 개인 검색 선호 설정을 "MVP에서는 SearchFilterPreset으로 유사 기능 대체 가능, 전용 엔티티는 향후 검토"로 단계적 접근한 것이 실용적이다.

---

### RD-MS-05 — 모듈 간 계약 명확성 (가중치 10%)

**점수: 78**

**잘 된 점:**
- 의존 관계 다이어그램이 방향·유형·용도까지 명확히 정의되어 있다.
- RetrievalServiceClient의 계약(타임아웃, 서킷브레이커, 폴백)이 events.md §4.1에 구체적이다.
- SearchRepository 인터페이스 자체가 모듈과 인프라 간 명확한 계약이다.

**잔여 이슈:**

1. **(P3)** **읽기 의존 모듈의 구체적 서비스 메서드 미정의** — DocumentModule("검색 결과 메타데이터 보강"), BoardModule("게시판 설정 조회"), PermissionModule("접근 가능 게시판 ID 목록 조회")에 대한 읽기 의존이 용도만 기술되어 있다. 구체적으로 어떤 서비스 메서드(예: `DocumentService.findByIds()`, `PermissionService.getViewableBoardIds()`)를 호출하는지 정의되면 모듈 간 인터페이스 합의가 더 용이해진다.

---

### RD-MS-06 — 운영 고려사항 (가중치 10%)

**점수: 88**

**잘 된 점:**
- 주요 메트릭 7개(`search.keyword_count`, `search.rag_latency_ms`, `search.zero_result_rate`, `circuit.retrieval.state_change` 등)가 수집 방식까지 정의되어 있다.
- 모니터링 알림 임계값 5개(키워드 지연 1000ms, RAG 지연 5000ms, 무결과율 30%, 서킷브레이커 Open, 아카이빙 실패)가 심각도·채널까지 분류되어 있다.
- 외부 설정값 카탈로그(`lm:search.preset_max_count`, `sc:search.es_recon_cron` 등)가 기본값·용도·참조와 함께 정리되어 있어 운영팀이 설정을 조정할 때 참조할 수 있다.
- SearchLog 아카이빙(5년 보관, 배치 1000건 단위, INSERT+DELETE 트랜잭션, 건수 검증)이 금융권 감사 대비로 견고하다.

---

### 공용 루브릭 점수 산출

| ID | 차원 | 점수 | 가중치 | 가중 점수 |
|----|------|:----:|:------:|:---------:|
| RD-MS-01 | API 설계 품질 | 82 | 30% | 24.6 |
| RD-MS-02 | 구현 변환 용이성 | 83 | 10% | 8.3 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 85 | 25% | 21.3 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 87 | 15% | 13.1 |
| RD-MS-05 | 모듈 간 계약 명확성 | 78 | 10% | 7.8 |
| RD-MS-06 | 운영 고려사항 | 88 | 10% | 8.8 |
| | **공용 합계** | | **100%** | **84** |

---

## 3. 전문 루브릭 채점

### EX-MS-SR-01 — 런타임 안정성 설계 (가중치 50%)

**점수: 86**

**평가 관점**: 재시도, 서킷브레이커, 타임아웃, DLQ가 실무 수준으로 정의되어 있는가

**잘 된 점:**
- **타임아웃**: R3에서 6개 오퍼레이션별 타임아웃(searchByKeyword 3s, autocomplete 1s, indexDocumentBlocks 30s, removeDocument 10s, updateDocumentFields 10s, syncAnalyzerSettings 60s)이 정의됨. 실패 시 동작이 역할에 따라 차별화(검색: 에러 반환/graceful, 인덱싱: BullMQ 재시도, 설정: 다음 변경 시 재시도).
- **서킷브레이커**: RetrievalServiceClient에 대해 Redis 키 기반(`{tenant_id}:circuit:retrieval-service`) 서킷브레이커 정의. 검색 실패 시 키워드 폴백(mode=all) 또는 503(mode=ai).
- **재시도**: 이벤트별 재시도 정책이 차별화(인덱싱: 3회/5s~120s, 설정: 3회/1s~30s, 알림: 재시도 없음). DLQ 소진 후 경로가 명확.
- **DLQ**: `es-indexing:dlq`, `search-events:dlq` 정의. BullMQ Dashboard + Slack 알림으로 모니터링. Reconciliation 배치가 DLQ 이벤트를 자동 보정하는 안전망 역할.
- **분산 락**: schedule.md의 2개 배치 작업에 Redis 분산 락(TTL 포함) + 획득 실패 시 스킵 정책이 정의.
- **3중 방어**: 피처 게이트 + 서킷브레이커 + 타임아웃이 retrieval-service 의존에 계층적으로 적용.

**미세 개선점:**
- events.md §3.2 `document.content-updated`의 재시도 정책이 명시적으로 기재되면 더 완결적 (P3으로 별도 태깅).

---

### EX-MS-SR-02 — 참조 무결성 (가중치 50%)

**점수: 82**

**평가 관점**: 정의만 있고 참조 없는 항목, 또는 참조만 있고 정의 없는 항목이 없는가

**잘 된 점:**
- SearchRepository 인터페이스가 정의(README.md) → events.md, schedule.md, rules.md에서 일관되게 "SearchRepository를 통해"로 참조. 어댑터 매핑 테이블이 인터페이스 ↔ ES 구현을 1:1 연결.
- 보조 타입 7개(FieldWeights, IndexableBlock 등)가 정의(README.md §보조 타입) → SearchRepository 메서드 파라미터에서 참조. 정의만 있고 참조 없는 유령 타입 없음.
- BR-SCH-001~044가 정의(rules.md) → api.md 각 엔드포인트 "비즈니스 규칙 참조"에서 참조. 유령 규칙 없음.
- 에러 코드 9개가 정의(rules.md §3) → api.md 에러 코드 테이블에서 참조. 미참조 에러 코드 없음.
- 이벤트 페이로드(SearchConfigUpdatedPayload 등)가 정의(events.md §2) → 멱등성 전략(events.md §7)에서 키 필드 참조.

**잔여 이슈:**

1. **(P2)** **es.md `aicm_blocks` 매핑에 `is_excluded` 필드 미정의** — SearchRepository.`setExcluded()` 메서드가 `is_excluded` 필드를 `_update_by_query`로 갱신하고(README.md §구현체 매핑), IndexableMetadata에 `isExcluded: boolean`이 정의되어 있다. 그러나 아키텍처 참조 문서 es.md §1.2.2 매핑에는 `is_excluded` 필드가 없다. ES 검색 쿼리의 bool filter에서 `is_excluded: false` 조건을 적용하려면 매핑에 해당 필드가 존재해야 한다. 또한 FD-SCH §1에서는 `is_search_excluded`라는 이름을 사용하여 네이밍도 불일치한다.

   **영향**: ElasticsearchSearchAdapter 구현 시 `setExcluded()` 메서드가 존재하지 않는 필드를 갱신하게 되며, `searchByKeyword()`의 필터에서도 해당 필드를 참조할 수 없다.

   **조치 제안**: es.md `aicm_blocks` 매핑에 `is_excluded: { "type": "boolean" }` 추가. 필드명을 `is_excluded`(모듈 스펙 기준)로 통일하거나, FD의 `is_search_excluded`를 채택하고 모듈 스펙을 수정.

2. **(P3)** **README §인프라 사용 요약 소비 이벤트 목록에 `parsing.completed` 누락** — events.md §1.2에 `parsing.completed` (ParsingModule → BullMQ `parsing-events`)가 정의되어 있으나, README.md §인프라 사용 요약의 EventBus 소비 이벤트 목록(8개)에 포함되지 않았다. 총 9개여야 함.

   **조치 제안**: README EventBus 소비 목록에 `parsing.completed` 추가.

---

### 전문 루브릭 점수 산출

| ID | 차원 | 점수 | 가중치 | 가중 점수 |
|----|------|:----:|:------:|:---------:|
| EX-MS-SR-01 | 런타임 안정성 설계 | 86 | 50% | 43.0 |
| EX-MS-SR-02 | 참조 무결성 | 82 | 50% | 41.0 |
| | **전문 합계** | | **100%** | **84** |

---

## 4. 종합 점수 산출

| 계층 | 점수 | 비율 | 기여 |
|------|:----:|:----:|:----:|
| 공용 루브릭 | 84 | 60% | 50.4 |
| 전문 루브릭 | 84 | 40% | 33.6 |
| **종합** | | | **84** |

---

## 5. 잔여 이슈 요약

### P2 — 중요 (2건)

| # | 차원 ID | 이슈 | 조치 제안 |
|---|---------|------|----------|
| 1 | RD-MS-01, EX-MS-SR-02 | ~~**RagSearchDto에 categoryIds 미반영**~~ — 해소됨: Category 폐지로 `categoryIds` 불필요 | 조치 불필요 |
| 2 | EX-MS-SR-02 | **es.md `aicm_blocks` 매핑에 `is_excluded` 필드 미정의** — SearchRepository.`setExcluded()`와 IndexableMetadata.`isExcluded`가 참조하는 필드가 ES 매핑에 없음. FD-SCH는 `is_search_excluded`로 명명하여 네이밍도 불일치 | ① es.md 매핑에 `is_excluded: boolean` 추가 ② 필드명을 `is_excluded`로 통일 (또는 FD 기준 `is_search_excluded` 채택 후 모듈 스펙 전체 수정) ③ SearchRepository.`searchByKeyword()` 내부에서 `is_excluded: false` 필터를 `is_suspended`와 동일 패턴으로 암묵 적용 |

### P3 — 개선 권고 (4건)

| # | 차원 ID | 이슈 | 조치 제안 |
|---|---------|------|----------|
| 3 | RD-MS-01, EX-MS-SR-02 | **mode=all 검색 경로 미연결** — README.md `SearchQueryDto`에 `mode?: 'keyword' \| 'ai' \| 'all'`이 정의되고 피처 게이트 동작 테이블이 존재하나, api.md에 대응 엔드포인트 없음 | 방안 A: api.md에 `POST /search`의 body에 `mode` 필드를 추가하여 통합 검색 엔드포인트로 확장. 방안 B: mode가 내부 서비스 레이어 전용이라면 README에 "내부 전용, 클라이언트에 노출하지 않음" 주석 추가 |
| 4 | RD-MS-03 | **events.md §3.2 `document.content-updated` 재시도 정책 미명시** — §3.1은 "재시도 정책: 최대 3회, 지수 백오프"를 명시하나 §3.2는 멱등성만 기술 | events.md §3.2에 "**재시도 정책**: 최대 3회, 지수 백오프 (초기 5s, 최대 120s). 소진 후 DLQ `es-indexing:dlq`" 1행 추가 |
| 5 | EX-MS-SR-02 | **README §인프라 사용 요약 소비 이벤트 목록에 `parsing.completed` 누락** — events.md §1.2에 9번째 소비 이벤트로 정의되어 있으나 README 목록(8개)에서 빠짐 | README EventBus 소비 목록에 `parsing.completed` 추가 |
| 6 | RD-MS-01 | **FD ↔ api.md 페이지네이션 필드명 불일치** — FD-SCH §7.1은 `size`, api.md는 `limit`. 기능 차이 없으나 FD 기반 구현 시 혼동 가능 | 프로젝트 전체 용어 정의에서 통일 (api.md의 `limit`이 NestJS 관례에 부합하므로 FD를 `limit`으로 수정 추천) |

---

## 6. 점수 추이

| 라운드 | 종합 점수 | 판정 | P1 | P2 | P3 |
|--------|:---------:|------|:--:|:--:|:--:|
| R1 | 69 | 양호 | 2 | — | — |
| R2 | 79 | 양호 | 0 | 6 | — |
| **R3** | **84** | **우수** | **0** | **2** | **4** |

---

## 7. 다음 단계 권장

P2 2건 + P3 4건은 모두 문서 수정으로 해소 가능하며, 아키텍처 변경이나 설계 재검토가 필요한 항목은 없다. 우선순위에 따라:

1. **즉시 수정 가능** (P3 #4, #5): events.md 재시도 정책 1행 추가, README 소비 이벤트 목록 보완. (P2 #1은 Category 폐지로 자동 해소)
2. **아키텍처 팀 협의 필요** (P2 #2): es.md 매핑 수정 + 필드명 통일 — SearchModule 단독으로 결정 불가, 데이터 아키텍처 담당자와 협의
3. **설계 결정 필요** (P3 #3): mode=all의 API 노출 여부 — 프론트엔드 팀과 협의하여 통합 엔드포인트 필요 여부 결정
4. **프로젝트 수준** (P3 #6): 용어 통일은 프로젝트 전체 영향이므로 별도 정리 시점에 일괄 처리

**90점 도달 조건**: P2 2건 해소 + P3 중 #4, #5 해소 시 90점 근접 가능.
