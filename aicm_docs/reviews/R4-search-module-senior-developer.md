# R4 리뷰 — Search 모듈 상세 설계 (시니어 백엔드 개발자)

| 항목 | 값 |
|------|---|
| 리뷰 라운드 | R4 (최종 재리뷰) |
| 대상 문서 | `docs/03-module-design/search/` 전체 (README.md, api.md, data.md, events.md, schedule.md, rules.md) |
| 페르소나 | 시니어 백엔드 개발자 — 최민재 |
| 루브릭 | 모듈 스펙 (§4) + 시니어 개발자 전문 루브릭 |
| 점수 이력 | R1: 69 → R2: 79 → R3: 84 → **R4: 88** |
| 리뷰 일자 | 2026-04-03 |

---

## 1. R3 → R4 수정 사항 검증

| # | 수정 내역 | 검증 결과 | 근거 |
|---|----------|:---------:|------|
| 1 | RagSearchDto에 `categoryIds` 추가 | ~~✅ 반영 완료~~ 후속 폐기: Category 엔티티 폐지로 `categoryIds` 자체가 불필요해짐 | ~~api.md `RagSearchDto.filters.categoryIds?: string[]`~~ — Category 폐지로 해당 필드 제거됨 |
| 2 | es.md에 `is_excluded` 필드 매핑 + 필드 설명 표 추가 | ✅ 반영 완료 | es.md §1.2.2 mappings에 `"is_excluded": { "type": "boolean" }` 추가, 필드 설명 표에 `is_excluded` 행 + BR-SCH-029 참조 기재 |
| 3 | `document.content-updated` 소비 이벤트 재시도 정책 추가 | ✅ 반영 완료 | events.md §3.2 — "최대 3회, 지수 백오프 (초기 5s, 최대 120s). 소진 후 DLQ `es-indexing:dlq`" |
| 4 | README 소비 이벤트 목록에 `parsing.completed` 추가 | ✅ 반영 완료 | README.md 인프라 사용 요약 EventBus 소비 항목에 `parsing.completed` 포함 |
| 5 | events.md 요약 표의 나머지 "ES" 참조를 "SearchRepository"로 통일 | ✅ 반영 완료 | events.md §1.2 소비 이벤트 요약 및 §3 상세 전체에서 "SearchRepository를 통해"로 일관 기술 |

**R3 지적 사항 5건 모두 정상 반영 확인.**

---

## 2. 공용 루브릭 채점 (RD-MS, 시니어 개발자 가중치)

### RD-MS-01 — API 설계 품질 (30%) : **87점**

**근거**:

- **강점**: 27개 엔드포인트가 RESTful 관례에 부합하고 네이밍 일관성이 우수하다 (사용자 API `/search/*`, 관리자 API `/admin/search/*` 분리). DTO가 TypeScript interface로 명세되어 프론트엔드·백엔드 간 계약이 명확하다. 에러 코드 카탈로그(rules.md §3)가 9개 도메인 에러를 정의하며, 각 API에 관련 BR 참조를 달았다. 페이지네이션 패턴(`meta.page/limit/totalItems/totalPages`)이 일관적이다.
- **비고**: 이전에 지적된 `categoryIds` 누락은 Category 엔티티 폐지로 인해 자동 해소되었다. 게시판 트리(Board.parent_id)가 분류 체계를 대체한다.

### RD-MS-02 — 구현 변환 용이성 (10%) : **86점**

**근거**:

- **강점**: SearchRepository 인터페이스가 TypeScript 코드로 완전히 정의되어 있고, 구현체 매핑 표(README.md §SearchRepository 인터페이스)에서 각 메서드가 ElasticsearchSearchAdapter에서 어떤 ES API로 변환되는지 1:1 매핑되어 있다. 보조 타입(`SearchFilters`, `FieldWeights`, `IndexableBlock` 등)도 상세하다. DDL(data.md §3)이 CHECK 제약조건, 부분 인덱스를 포함하여 완전하다. 타임아웃 정책 표가 오퍼레이션별로 명시되어 있다.
- **약점**: 경미. events.md의 일부 소비 이벤트(§3.3~3.5)에서 SearchRepository의 어떤 메서드를 호출하는지 설명은 있으나, §3.1 `document.published`만큼 상세한 단계별 플로우가 아닌 이벤트가 있다.

### RD-MS-03 — 이벤트/비동기 설계 건전성 (25%) : **86점**

**근거**:

- **강점**: 발행 3건 + 소비 9건 이벤트 매트릭스가 요약 표와 상세 절로 이원화되어 있다. 각 발행 이벤트에 TypeScript 페이로드 인터페이스가 정의되어 있고, 멱등성 보장(§7)이 이벤트/큐별 멱등성 키와 전략으로 명시되어 있다. DLQ(§6) 2개 큐에 대한 모니터링/수동 처리 계획이 있다. `document.content-updated` 재시도 정책이 R4에서 추가되었고, `parsing.completed` 이벤트도 추가 완료되었다.
- **약점**: `document.deleted`(§3.3), `document.suspended`/`unsuspended`(§3.4), `document.archived`(§3.5) — 4개 소비 이벤트에 재시도 정책이 명시적으로 기재되지 않았다. 모두 Important 티어이며 동일한 `es-indexing` BullMQ 큐를 사용하므로 큐 레벨 기본 재시도가 적용될 것으로 추정되지만, `document.published`와 `document.content-updated`에는 명시적으로 기재된 것과 비교하면 불균일하다.

### RD-MS-04 — 모듈 책임 범위 적절성 (15%) : **90점**

**근거**:

- README.md의 모듈 책임 표가 10개 영역으로 명확히 정의되어 있다. "현재 범위 제외 기능" 표(Playground, 멀티턴 RAG, 개인화 랭킹)로 Phase 2 분리가 명시적이다. 파싱 파이프라인의 ParsingModule 분리 참조가 일관적이다. 개인 검색 선호 설정의 MVP 대체 전략("SearchFilterPreset으로 유사 기능 대체 가능, 전용 엔티티는 향후 검토")도 실용적인 판단이다.

### RD-MS-05 — 모듈 간 계약 명확성 (10%) : **88점**

**근거**:

- SearchRepository 인터페이스가 검색 엔진과의 계약을 명확히 분리한다. 모듈 아키텍처 §3.3 규칙 4의 예외 사항(SearchModule의 Repository/Adapter 패턴)을 README에서 명시적으로 참조한다. 의존 관계 다이어그램(Mermaid)과 의존 표가 방향·유형·용도를 명시한다. RetrievalServiceClient의 서킷브레이커/타임아웃/폴백이 events.md §4.1에 정의되어 있다.

### RD-MS-06 — 운영 고려사항 (10%) : **90점**

**근거**:

- 주요 메트릭 7항목(`search.keyword_count` ~ `circuit.retrieval.state_change`)이 수집 방식과 함께 정의되어 있다. 모니터링 알림 임계값이 5개 조건에 대해 심각도·채널과 함께 명시되어 있다. 외부 설정값 카탈로그 4항목이 기본값·용도·참조와 함께 기술되어 있다. 피처 게이트 기반 Graceful Degradation(README §피처 게이트, events.md §5)이 3중 방어(피처 게이트 + 서킷브레이커 + 타임아웃)로 체계적이다.

### 공용 점수 산출

| 차원 | 가중치 | 점수 | 기여 |
|------|:------:|:----:|-----:|
| RD-MS-01 API 설계 품질 | 30% | 87 | 26.1 |
| RD-MS-02 구현 변환 용이성 | 10% | 86 | 8.6 |
| RD-MS-03 이벤트/비동기 설계 건전성 | 25% | 86 | 21.5 |
| RD-MS-04 모듈 책임 범위 적절성 | 15% | 90 | 13.5 |
| RD-MS-05 모듈 간 계약 명확성 | 10% | 88 | 8.8 |
| RD-MS-06 운영 고려사항 | 10% | 90 | 9.0 |
| **공용 점수** | **100%** | | **88 (87.5 반올림)** |

---

## 3. 전문 루브릭 채점 (EX-MS-SR, 시니어 개발자)

### EX-MS-SR-01 — 런타임 안정성 설계 (50%) : **86점**

**평가 관점**: 재시도, 서킷브레이커, 타임아웃, DLQ가 실무 수준으로 정의되어 있는가

**근거**:

- **재시도**: `document.published`, `document.content-updated`, `parsing.completed`에 "최대 3회, 지수 백오프" 재시도 정책이 명시되어 있다. 발행 이벤트 `search.config.updated`에도 "최대 3회, 지수 백오프 (초기 1s, 최대 30s)"가 정의되어 있다.
- **서킷브레이커**: RetrievalServiceClient에 Redis 키 기반 서킷브레이커 (`{tenant_id}:circuit:retrieval-service`)가 정의되어 있고, 서킷 Open 시 CRITICAL 알림이 연결되어 있다.
- **타임아웃**: SearchRepository 오퍼레이션별 타임아웃 표(3s/1s/30s/10s/60s)가 실패 시 동작과 함께 정의되어 있다.
- **DLQ**: `es-indexing:dlq`, `search-events:dlq` 2개 DLQ가 모니터링 방법과 함께 정의되어 있다.
- **분산 락**: Reconciliation/아카이빙에 Redis 분산 락(TTL 포함)이 명시되어 있다.
- **약점**: `document.deleted`/`suspended`/`unsuspended`/`archived` 4개 소비 이벤트에 재시도 정책이 명시적으로 기재되지 않았다. 실무에서 구현 시 "이 이벤트의 재시도 정책이 뭔지"를 문서만으로 즉시 판단하기 어렵다.

### EX-MS-SR-02 — 참조 무결성 (50%) : **88점**

**평가 관점**: 정의만 있고 참조 없는 항목, 또는 참조만 있고 정의 없는 항목이 없는가

**근거**:

- **BR → API 매핑**: rules.md에 정의된 20개 BR이 api.md의 각 엔드포인트에서 "비즈니스 규칙 참조"로 역참조된다. 유령 BR이 없다.
- **SearchRepository ↔ events.md**: SearchRepository 인터페이스의 7개 메서드가 events.md의 소비 이벤트 상세에서 구체적으로 호출된다 (`indexDocumentBlocks`, `removeDocument`, `updateDocumentFields`, `setExcluded`, `getIndexedDocumentIds`, `syncAnalyzerSettings`).
- **엔티티 ↔ DTO**: data.md의 7개 엔티티(SearchConfig~SearchFilterPreset) 필드와 api.md의 DTO 필드가 네이밍 변환(snake_case → camelCase)을 제외하면 정합한다.
- **es.md 정합**: es.md `aicm_blocks` 매핑의 `is_excluded` 필드가 R4에서 추가되어 SearchRepository의 `setExcluded()` 메서드 및 BR-SCH-029와 정합한다.
- **비고**: 이전에 지적된 `categoryIds` 누락은 Category 엔티티 폐지로 자동 해소되었다.

### 전문 점수 산출

| 차원 | 가중치 | 점수 | 기여 |
|------|:------:|:----:|-----:|
| EX-MS-SR-01 런타임 안정성 설계 | 50% | 86 | 43.0 |
| EX-MS-SR-02 참조 무결성 | 50% | 88 | 44.0 |
| **전문 점수** | **100%** | | **87** |

---

## 4. 종합 점수

| 계층 | 점수 | 비율 | 기여 |
|------|:----:|:----:|-----:|
| 공용 루브릭 | 88 | 60% | 52.8 |
| 전문 루브릭 | 87 | 40% | 34.8 |
| **종합** | | | **88 (87.6 반올림)** |

**점수 이력**: R1(69) → R2(79) → R3(84) → **R4(88)** (+4)

---

## 5. 잔여 이슈

### P2 — 중요 (구현 가능하나 품질 저하 / 팀 간 혼란 초래)

#### ~~P2-1. PresetFilters에 categoryIds 누락~~ (자동 해소)

Category 엔티티가 폐지되고 게시판 트리(Board.parent_id)로 대체되어, `categoryIds` 필드 자체가 불필요해졌다. 이 이슈는 자동 해소되었다.

#### P2-2. document.deleted / suspended / unsuspended / archived 재시도 정책 미기재 [RD-MS-03, EX-MS-SR-01]

| 항목 | 내용 |
|------|------|
| **위치** | events.md §3.3, §3.4, §3.5 |
| **현상** | 4개 소비 이벤트에 재시도 정책이 명시적으로 기재되지 않았다. 모두 Important 티어이며 `es-indexing` BullMQ 큐를 사용하므로 `document.published`(§3.1)과 동일한 재시도가 적용될 것으로 추정되지만, §3.1과 §3.2에는 "최대 3회, 지수 백오프, DLQ"가 명시된 반면 §3.3~3.5에는 없다. |
| **영향** | 주니어 개발자가 구현 시 재시도 정책을 누락하거나, 이벤트별 차등 정책이 필요한지 판단하기 어려움 |
| **조치 제안** | §3.3~3.5에 재시도 정책 행 추가 (동일하면 "§3.1과 동일" 참조도 충분), 또는 §3 도입부에 "`es-indexing` 큐 공통 재시도 정책: 최대 3회, 지수 백오프, DLQ `es-indexing:dlq`" 기재 후 개별 이벤트에서 참조 |

### P3 — 개선 권고 (현재 상태로 동작하나 개선하면 더 나아짐)

#### P3-1. SearchRepository 인터페이스에 is_excluded 자동 필터링 명시 부재 [RD-MS-01]

| 항목 | 내용 |
|------|------|
| **위치** | README.md SearchRepository 인터페이스 / SearchFilters |
| **현상** | `SearchFilters`에 `excludeSuspended: boolean`이 명시적으로 존재하지만, `is_excluded` 문서에 대한 유사한 필터 플래그가 없다. `setExcluded()` 메서드와 BR-SCH-029에서 "검색 결과에서 즉시 제외"라고 기술되어 있어 구현체가 내부적으로 처리할 것이 내포되어 있으나, 인터페이스 수준에서 명시적이지 않다. |
| **조치 제안** | `SearchFilters`에 `excludeExcluded: boolean // is_excluded: false 필터 (항상 true)` 추가, 또는 SearchRepository JSDoc에 "모든 검색 메서드는 `is_excluded: true` 문서를 자동 필터링한다"는 주석 추가 |

#### P3-2. es.md §1.3 쿼리 패턴에 is_excluded 필터 미포함 [RD-MS-06]

| 항목 | 내용 |
|------|------|
| **위치** | es.md §1.3 문서 검색 쿼리 패턴 예시 |
| **현상** | 예시 쿼리의 `bool.filter`에 `{ "term": { "is_suspended": false } }`만 있고 `{ "term": { "is_excluded": false } }`가 없다. 예시 목적이지만 보안 관련 필수 필터이므로 포함을 권장한다. |
| **조치 제안** | 쿼리 패턴의 filter 배열에 `{ "term": { "is_excluded": false } }` 추가 |

---

## 6. 총평

R3에서 지적된 5건이 모두 정확히 반영되었다. 특히 `SearchRepository`를 통한 검색 엔진 추상화가 README, api.md, events.md, schedule.md 전반에 걸쳐 일관성 있게 적용되어 있어 모듈 아키텍처 §3.3 규칙 4의 예외 설계가 문서 레벨에서 잘 관철되고 있다.

**90점 도달을 위한 핵심 조치**:
1. ~~P2-1: `PresetFilters`에 `categoryIds` 추가~~ — Category 폐지로 자동 해소
2. P2-2: 소비 이벤트 재시도 정책 균일화 (events.md)

P2-2만 반영하면 90점 이상(우수) 달성이 가능하다.
