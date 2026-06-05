# R5 리뷰 — Search 모듈 상세 설계 (시니어 백엔드 개발자)

| 항목 | 값 |
|------|---|
| 리뷰 라운드 | R5 (최종 확인 리뷰) |
| 대상 문서 | `docs/03-module-design/search/` 전체 (README.md, api.md, data.md, events.md, schedule.md, rules.md) |
| 페르소나 | 시니어 백엔드 개발자 — 최민재 |
| 루브릭 | 모듈 스펙 (§4) + 시니어 개발자 전문 루브릭 |
| 점수 이력 | R1: 69 → R2: 79 → R3: 84 → R4: 88 → **R5: 90** |
| 리뷰 일자 | 2026-04-03 |

---

## 1. R4 → R5 수정 사항 검증

| # | 수정 내역 | 검증 결과 | 근거 |
|---|----------|:---------:|------|
| 1 | data.md SearchFilterPreset filters에 `category_ids` 추가 | ~~✅ 반영 완료~~ 후속 폐기: Category 엔티티 폐지로 `category_ids` 자체가 불필요해짐 | ~~data.md §2.7 filters JSONB 설명과 FD-SCH §6.7 정합~~ — Category 폐지로 해당 필드 제거됨 |
| 2 | events.md `document.deleted` 재시도 정책 추가 | ✅ 반영 완료 | events.md §3.3 — "**재시도 정책**: 최대 3회, 지수 백오프 (초기 5s, 최대 120s). 소진 후 DLQ `es-indexing:dlq`" 명시. 멱등성 `documentId` 기반 no-op도 기재 |
| 3 | events.md `document.suspended`/`unsuspended` 재시도 정책 추가 | ✅ 반영 완료 | events.md §3.4 — "**재시도 정책**: 최대 3회, 지수 백오프 (초기 5s, 최대 120s). 소진 후 DLQ `es-indexing:dlq`" 명시. 멱등성 "현재 상태와 동일하면 skip"도 기재 |
| 4 | events.md `document.archived` 멱등성 + 재시도 정책 추가 | ✅ 반영 완료 | events.md §3.5 — "**멱등성**: `documentId` 기반 — 이미 삭제된 경우 no-op", "**재시도 정책**: `document.deleted`와 동일" 명시. `document.deleted` 참조로 중복 없이 일관적 |

**R4 지적 사항 반영 요약**: R4 P2-2(재시도 정책 미기재)는 **완전 해소**되었다. R4 P2-1(PresetFilters categoryIds 누락)은 Category 엔티티 폐지로 인해 `categoryIds` 필드 자체가 불필요해져 **자동 해소**되었다.

---

## 2. 공용 루브릭 채점 (RD-MS, 시니어 개발자 가중치)

### RD-MS-01 — API 설계 품질 (30%) : **88점** (R4: 87 → +1)

**근거**:

- **강점**: 27개 엔드포인트의 RESTful 관례 준수, 사용자/관리자 경로 분리(`/search/*`, `/admin/search/*`), TypeScript DTO 명세, 에러 코드 카탈로그(rules.md §3, 9개 도메인 에러), 페이지네이션 패턴(`meta.page/limit/totalItems/totalPages`) 일관성이 모두 유지된다.
- **개선**: Category 엔티티 폐지로 `categoryIds` 관련 정합 이슈가 자동 해소되었다. 게시판 트리(Board.parent_id)가 분류 체계를 대체하므로 `boardIds` 필터만으로 충분하다.

### RD-MS-02 — 구현 변환 용이성 (10%) : **88점** (R4: 86 → +2)

**근거**:

- **강점**: SearchRepository 인터페이스 + 구현체 매핑 표 + 보조 타입 정의가 완전하다. DDL(data.md §3)이 CHECK 제약조건, 부분 인덱스를 포함한다. 타임아웃 정책 표가 오퍼레이션별로 명시되어 있다.
- **개선**: events.md §3.3~3.5에 재시도 정책이 모두 명시되면서, 주니어 개발자가 **모든 소비 이벤트**의 재시도 정책을 문서만으로 즉시 파악할 수 있게 되었다. 특히 §3.5 `document.archived`의 "`document.deleted`와 동일" 참조 방식은 중복을 피하면서 명확성을 유지하는 좋은 패턴이다.

### RD-MS-03 — 이벤트/비동기 설계 건전성 (25%) : **91점** (R4: 86 → +5)

**근거**:

- **강점**: 발행 3건 + 소비 9건 이벤트 매트릭스가 요약 + 상세 이원 구조로 정리되어 있다. **모든 Important 티어 소비 이벤트**(document.published, content-updated, deleted, suspended, unsuspended, archived, parsing.completed)에 재시도 정책(최대 3회, 지수 백오프, DLQ)이 명시되어 있다. 멱등성 보장(§7)이 이벤트/큐별 멱등성 키와 전략으로 체계적이다. DLQ(§6) 2개 큐의 모니터링/처리 계획이 수립되어 있다.
- **R4 대비 개선**: events.md §3.3 `document.deleted`에 "최대 3회, 지수 백오프 (초기 5s, 최대 120s). DLQ `es-indexing:dlq`"가 추가되었다. §3.4 `document.suspended`/`unsuspended`에도 동일한 재시도 정책이 추가되었다. §3.5 `document.archived`에 멱등성(`documentId` 기반 no-op) + 재시도 정책(`document.deleted`와 동일 참조)이 추가되었다. 이로써 `es-indexing` 큐의 **7개 소비 이벤트 전체**에 재시도·멱등성·DLQ가 균일하게 기재되었다.
- Best-effort 티어(shared-content.updated, block.visibility-changed)는 의도적으로 재시도 미정의이며 "다음 Reconciliation 배치에서 보정"이라는 보정 전략이 명시되어 있어 설계 의도가 명확하다.

### RD-MS-04 — 모듈 책임 범위 적절성 (15%) : **90점** (R4 동일)

**근거**:

- README.md 모듈 책임 표 10개 영역이 명확하다. "현재 범위 제외 기능" 표(Playground, 멀티턴 RAG, 개인화 랭킹)로 Phase 2 분리가 명시적이다. 파싱 파이프라인의 ParsingModule 분리 참조가 일관적이다. 개인 검색 선호 설정의 MVP 대체 전략도 실용적이다.

### RD-MS-05 — 모듈 간 계약 명확성 (10%) : **88점** (R4 동일)

**근거**:

- SearchRepository 인터페이스가 검색 엔진과의 계약을 명확히 분리한다. 모듈 아키텍처 §3.3 규칙 4 예외(Repository/Adapter 패턴)를 README에서 명시적으로 참조한다. 의존 관계 다이어그램(Mermaid) + 의존 표가 방향·유형·용도를 명시한다. RetrievalServiceClient의 서킷브레이커/타임아웃/폴백이 events.md §4.1에 정의되어 있다.

### RD-MS-06 — 운영 고려사항 (10%) : **90점** (R4 동일)

**근거**:

- 주요 메트릭 7항목이 수집 방식과 함께 정의되어 있다. 모니터링 알림 임계값 5개가 심각도·채널과 함께 명시되어 있다. 외부 설정값 카탈로그 4항목이 기본값·용도·참조와 함께 기술되어 있다. 피처 게이트 기반 Graceful Degradation(3중 방어)이 체계적이다.

### 공용 점수 산출

| 차원 | 가중치 | 점수 | 기여 |
|------|:------:|:----:|-----:|
| RD-MS-01 API 설계 품질 | 30% | 88 | 26.4 |
| RD-MS-02 구현 변환 용이성 | 10% | 88 | 8.8 |
| RD-MS-03 이벤트/비동기 설계 건전성 | 25% | 91 | 22.75 |
| RD-MS-04 모듈 책임 범위 적절성 | 15% | 90 | 13.5 |
| RD-MS-05 모듈 간 계약 명확성 | 10% | 88 | 8.8 |
| RD-MS-06 운영 고려사항 | 10% | 90 | 9.0 |
| **공용 점수** | **100%** | | **89 (89.25 반올림)** |

---

## 3. 전문 루브릭 채점 (EX-MS-SR, 시니어 개발자)

### EX-MS-SR-01 — 런타임 안정성 설계 (50%) : **91점** (R4: 86 → +5)

**평가 관점**: 재시도, 서킷브레이커, 타임아웃, DLQ가 실무 수준으로 정의되어 있는가

**근거**:

- **재시도**: R5에서 `es-indexing` 큐의 **모든 소비 이벤트**(published, content-updated, deleted, suspended, unsuspended, archived, parsing.completed)에 재시도 정책이 명시되었다. "최대 3회, 지수 백오프 (초기 5s, 최대 120s), 소진 후 DLQ `es-indexing:dlq`"가 균일하게 적용되어 있고, `document.archived`는 "`document.deleted`와 동일" 참조 방식으로 중복 없이 기재되었다. 발행 이벤트 `search.config.updated`의 재시도(3회, 초기 1s, 최대 30s)와 알림 전용 이벤트(reindex.completed/failed)의 의도적 재시도 미적용도 명확하다.
- **서킷브레이커**: RetrievalServiceClient에 Redis 키 기반 서킷브레이커(`{tenant_id}:circuit:retrieval-service`)가 정의되어 있고, 서킷 Open 시 CRITICAL 알림이 연결되어 있다.
- **타임아웃**: SearchRepository 오퍼레이션별 타임아웃 표(3s/1s/30s/10s/60s)가 실패 시 동작과 함께 정의되어 있다.
- **DLQ**: `es-indexing:dlq`, `search-events:dlq` 2개 DLQ가 모니터링·수동 처리 방법과 함께 정의되어 있다.
- **분산 락**: Reconciliation/아카이빙에 Redis 분산 락(키 패턴 + TTL)이 명시되어 있다.
- **멱등성**: 모든 소비 이벤트에 멱등성 전략이 기재되어 있다(`documentId+version` 기반, 현재 상태 비교, `documentId` 기반 no-op 등). §7 멱등성 보장 요약 표로 한눈에 확인 가능하다.

R4 대비 가장 큰 개선점: 재시도 정책의 균일한 기재로 "이 이벤트의 재시도 정책이 뭔지"를 문서만으로 즉시 판단할 수 있게 되었다. 실무 구현 시 모든 이벤트 핸들러에 대해 별도 확인 없이 문서만으로 구현 가능한 수준이다.

### EX-MS-SR-02 — 참조 무결성 (50%) : **89점** (R4: 88 → +1)

**평가 관점**: 정의만 있고 참조 없는 항목, 또는 참조만 있고 정의 없는 항목이 없는가

**근거**:

- **BR → API 매핑**: rules.md에 정의된 20개 BR이 api.md의 각 엔드포인트에서 "비즈니스 규칙 참조"로 역참조된다. 유령 BR 없음.
- **SearchRepository ↔ events.md**: SearchRepository 인터페이스의 7개 메서드(`searchByKeyword`, `autocomplete`, `getIndexedDocumentIds`, `indexDocumentBlocks`, `removeDocument`, `updateDocumentFields`, `setExcluded`, `syncAnalyzerSettings`)가 events.md/schedule.md에서 구체적으로 참조된다.
- **엔티티 ↔ DTO**: data.md의 7개 엔티티 필드와 api.md DTO 필드가 네이밍 변환(snake_case → camelCase)을 제외하면 정합한다.
- **es.md 정합**: `aicm_blocks` 매핑의 `is_excluded` 필드가 SearchRepository `setExcluded()` + BR-SCH-029와 정합한다.
- **data.md ↔ FD-SCH**: Category 엔티티 폐지로 `category_ids` 관련 정합 이슈가 자동 해소되었다.

### 전문 점수 산출

| 차원 | 가중치 | 점수 | 기여 |
|------|:------:|:----:|-----:|
| EX-MS-SR-01 런타임 안정성 설계 | 50% | 91 | 45.5 |
| EX-MS-SR-02 참조 무결성 | 50% | 89 | 44.5 |
| **전문 점수** | **100%** | | **90** |

---

## 4. 종합 점수

| 계층 | 점수 | 비율 | 기여 |
|------|:----:|:----:|-----:|
| 공용 루브릭 | 89 | 60% | 53.4 |
| 전문 루브릭 | 90 | 40% | 36.0 |
| **종합** | | | **89 (89.4 반올림)** |

**점수 이력**: R1(69) → R2(79) → R3(84) → R4(88) → **R5(89)** (+1)

---

## 5. 잔여 이슈

### P2 — 중요 (구현 가능하나 품질 저하 / 팀 간 혼란 초래)

#### ~~P2-1. api.md PresetFilters에 categoryIds 누락~~ (자동 해소)

Category 엔티티가 폐지되고 게시판 트리(Board.parent_id)로 대체되어, `categoryIds` 필드 자체가 불필요해졌다. 이 이슈는 자동 해소되었다.

### P3 — 개선 권고 (현재 상태로 동작하나 개선하면 더 나아짐)

#### P3-1. SearchFilters에 is_excluded 자동 필터링 명시 부재 (R4 잔존) [RD-MS-01]

| 항목 | 내용 |
|------|------|
| **위치** | README.md SearchRepository 인터페이스 / SearchFilters |
| **현상** | `SearchFilters`에 `excludeSuspended: boolean`은 명시적이지만, `is_excluded` 문서에 대한 유사한 필터 플래그가 없다. `setExcluded()` 메서드와 BR-SCH-029에서 의미가 내포되어 있으나 인터페이스 수준에서 불명시적이다. |
| **조치 제안** | `SearchFilters`에 `excludeExcluded: boolean` 추가, 또는 SearchRepository 인터페이스 JSDoc에 "모든 검색 메서드는 `is_excluded: true` 문서를 자동 필터링한다" 명시 |

#### P3-2. es.md §1.3 쿼리 패턴에 is_excluded 필터 미포함 (R4 잔존) [RD-MS-06]

| 항목 | 내용 |
|------|------|
| **위치** | es.md §1.3 문서 검색 쿼리 패턴 JSON 예시 |
| **현상** | 쿼리 패턴의 `bool.filter`에 `{ "term": { "is_suspended": false } }`만 있고 `{ "term": { "is_excluded": false } }`가 빠져 있다. 예시 목적이지만 보안 관련 필수 필터이므로 포함을 권장한다. |
| **조치 제안** | filter 배열에 `{ "term": { "is_excluded": false } }` 추가 |

---

## 6. 총평

### R4 → R5 개선 평가

R4 P2 2건 중 P2-2(재시도 정책 미기재)가 **완전 해소**되었다. events.md §3.3~3.5에 재시도 정책이 명시적으로 추가되면서, `es-indexing` 큐의 모든 Important 티어 소비 이벤트(7건)에 재시도·멱등성·DLQ가 균일하게 기재되었다. 특히 `document.archived`의 "`document.deleted`와 동일" 참조 패턴은 중복을 피하면서 추적 가능성을 유지하는 모범적인 기술 방식이다.

P2-1(PresetFilters categoryIds)은 Category 엔티티 폐지로 인해 `categoryIds` 필드 자체가 불필요해져 **자동 해소**되었다.

### 문서 전체 평가

Search 모듈 상세 설계 문서는 5라운드의 반복 리뷰를 통해 **우수(80~100)** 수준에 안정적으로 진입했다.

**특히 높이 평가하는 부분:**
1. **SearchRepository 추상화의 일관적 관철**: README, api.md, events.md, schedule.md 전반에서 검색 엔진 접근이 인터페이스를 통해 기술되어 있고, 모듈 아키텍처 §3.3 규칙 4의 예외 설계가 문서 레벨에서 완벽히 반영되어 있다.
2. **이벤트/비동기 설계의 완결성**: 모든 Important 소비 이벤트에 재시도·멱등성·DLQ가 균일하게 정의되어 있고, Best-effort 이벤트는 Reconciliation 배치로 보정하는 설계가 명확하다.
3. **운영 관점의 체계성**: 메트릭·알림·피처 게이트·서킷브레이커·분산 락이 체계적으로 정의되어 있어, 운영 환경에서의 장애 대응이 문서만으로 판단 가능하다.

**90점 이상 달성을 위한 마지막 조치:**
- P2-1은 Category 폐지로 자동 해소되었다. 잔여 P3 이슈만 남아 있어 90점 도달이 가능하다.

### 점수 추이 분석

```
R1(69) ──+10──> R2(79) ──+5──> R3(84) ──+4──> R4(88) ──+1──> R5(89)
 미흡          양호            양호→우수       우수           우수
```

R1에서 R5까지 20점 상승했으며, 점수 증가폭이 라운드마다 수렴하고 있어 문서 품질이 안정기에 진입한 것으로 판단된다. 잔여 P2 1건과 P3 2건은 모두 경미한 수준이며, P2-1만 해소하면 구현 착수에 충분한 품질이다.
