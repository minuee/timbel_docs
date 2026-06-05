# 모듈 스펙 재리뷰 (R2) — Search 모듈

| 항목 | 값 |
|------|---|
| 리뷰 대상 | MS-SCH (SearchModule 모듈 스펙) |
| 리뷰 라운드 | **R2** (재리뷰) |
| 페르소나 | 시니어 백엔드 개발자 — 최민재 |
| 루브릭 | 모듈 스펙 (§4) + 시니어 개발자 전문 루브릭 |
| 채점 비율 | 공용 60% / 전문 40% |
| 이전 점수 | R1: 69점 |
| **종합 점수** | **R2: 79점 (+10)** |
| 리뷰일 | 2026-04-03 |

---

## 1. R1 지적사항 해소 현황

### P1 항목 (2건 → 2건 해소)

| ID | R1 지적 | R2 상태 | 확인 근거 |
|----|---------|---------|----------|
| P1-1 | SearchRepository 인터페이스 미정의 | **해소** | README.md §SearchRepository 인터페이스에 8개 메서드(읽기 3 + 쓰기 4 + 설정 1), `SearchFilters` 인터페이스, 구현체 매핑 표(ElasticsearchSearchAdapter ↔ ES API) 모두 정의됨. 아키텍처 §3.3 규칙 4 참조도 명시 |
| P1-2 | 인덱싱(write) 경로 추상화 부재 | **해소** | events.md의 모든 소비 이벤트(published, content-updated, deleted, suspended, unsuspended, archived, shared-content.updated, block.visibility-changed, parsing.completed)가 "SearchRepository를 통해" 처리하도록 변경됨. schedule.md S1 Reconciliation도 SearchRepository 경유 명시 |

### P2 항목 (R1에서 지적된 것)

| ID | R1 지적 | R2 상태 | 확인 근거 |
|----|---------|---------|----------|
| P2 | api.md POST /search에서 "ES aicm_blocks" 직접 언급 | **해소** | api.md §POST /search 설명: "SearchRepository를 통한 `aicm_blocks` 인덱스 풀텍스트 검색"으로 수정 완료 |

**평가**: R1의 P1 2건이 모두 해소되어 구조적 개선이 확인됨. SearchRepository 인터페이스가 모듈 전반에 걸쳐 일관되게 참조되고 있어, 검색 솔루션 교체 시나리오에 대한 설계 대비가 충분해졌다.

---

## 2. 공용 루브릭 채점

> 가중치 출처: `senior-developer.md` §공용 루브릭 가중치 오버라이드

### RD-MS-01 — API 설계 품질 (30%)

**점수: 78**

**잘 된 점**:
- 26개 이상의 엔드포인트가 체계적으로 정의되어 있고, 모든 엔드포인트에 TypeScript 인터페이스 기반 Request/Response DTO가 있다
- 에러 코드가 rules.md의 BR과 1:1로 매핑되어 있다 (예: `SCH_PRESET_LIMIT_EXCEEDED` → BR-SCH-026)
- 모든 엔드포인트에 권한 어노테이션(`manage_search`, VIEW, 인증 필요)이 명시됨
- SearchRepository 인터페이스의 `SearchFilters`가 검색 권한 필터(boardIds, excludeSuspended, excludeDocumentIds)를 포괄적으로 정의

**개선 필요**:
- ~~FD-SCH §7.2 RagSearchRequest에 `categoryIds` 필터 누락~~ → Category 엔티티 폐지로 자동 해소됨 (~~P2-1~~)
- FD-SCH §7.1은 `size`, api.md는 `limit`으로 필드명이 다르다. 의도적 변경이면 기록 필요 → **P3-1**

---

### RD-MS-02 — 구현 변환 용이성 (10%)

**점수: 72**

**잘 된 점**:
- data.md에 전체 DDL과 인덱스가 제공되어 RDB 계층은 즉시 구현 가능
- events.md의 모든 이벤트에 TypeScript 페이로드 인터페이스와 멱등성 키가 정의됨
- schedule.md의 배치 작업에 Mermaid 플로우차트와 실패 처리 표가 있어 구현 시뮬레이션이 용이

**개선 필요**:
- SearchRepository 인터페이스의 보조 타입 6개가 정의되지 않았다: `FieldWeights`, `IndexableBlock`, `DocumentMetadata`, `IndexableMetadata`, `KeywordSearchResult`, `AutocompleteResult`. 메인 인터페이스(`SearchRepository`, `SearchFilters`)는 잘 정의되었으나, 보조 타입의 형상(shape)이 없으면 구현 시 추정이 필요하다 → **P2-2**
- `SynonymGroup[]` 타입이 인터페이스에서 사용되지만 정의가 없다. data.md의 `Synonym` 엔티티와의 매핑 관계가 모호 → **P3-2**

---

### RD-MS-03 — 이벤트/비동기 설계 건전성 (25%)

**점수: 80**

**잘 된 점**:
- 발행 3건 + 소비 9건의 이벤트 매트릭스가 명확히 정의됨 (events.md §1)
- Important 티어 이벤트에 재시도 정책(최대 3회, 지수 백오프), DLQ(`es-indexing:dlq`, `search-events:dlq`), 멱등성 키가 체계적으로 정의됨
- Best-effort 이벤트(shared-content.updated, block.visibility-changed)는 Reconciliation 배치(schedule.md S1)에 의해 보정되는 구조가 잘 설계됨
- RetrievalServiceClient에 서킷브레이커 + 타임아웃(10s/5s) + 피처 게이트 3중 방어가 적용됨
- `search.reindex.completed/failed`의 재시도 없음 결정이 근거("알림 전용")와 함께 명시

**개선 필요**:
- `document.content-updated` 이벤트의 재시도 정책이 명시되지 않았다. `document.published`는 "최대 3회, 지수 백오프(초기 5s, 최대 120s), 소진 후 DLQ `es-indexing:dlq`"가 명확하나, content-updated는 멱등성 키만 기술되어 있다. 동일 `es-indexing` 큐를 사용하므로 동일 정책이 적용될 것으로 추정되나 명시 필요 → **P2-5**

---

### RD-MS-04 — 모듈 책임 범위 적절성 (15%)

**점수: 85**

**잘 된 점**:
- SearchModule ↔ ParsingModule 책임 분리가 깔끔하다. "파싱 설정 CRUD는 ParsingModule이 소유, SearchModule 관리자 API에서 프록시"라는 원칙이 명확
- Phase 2 제외 항목(Playground, 멀티턴 RAG, 피드백 기반 개인화 랭킹)이 FD 참조, 제외 사유, 향후 계획까지 표로 정리됨
- 의존 관계도가 읽기 전용 의존(Document, Board, Permission)과 외부 서비스(RetrievalServiceClient)를 명확히 분리
- AccessLog(`aicm_access_logs`)를 SearchRepository 범위에서 제외한 설계 결정이 근거와 함께 문서화됨

---

### RD-MS-05 — 모듈 간 계약 명확성 (10%)

**점수: 75**

**잘 된 점**:
- SearchRepository 인터페이스가 검색 엔진과의 계약을 명확히 정의하고, 구현체 매핑 표가 각 메서드의 ES API 대응을 보여줌
- 이벤트 페이로드가 TypeScript 인터페이스로 완전히 타이핑됨
- 외부 서비스(RetrievalServiceClient) 계약이 프로토콜, 피처 게이트, 서킷브레이커, 타임아웃, 폴백까지 포함

**개선 필요**:
- `is_excluded` 필드명이 문서 간 불일치: FD-SCH §1 BR-SCH-029는 `is_search_excluded`, SearchRepository의 `setExcluded()` 메서드와 BR-SCH-029(rules.md)는 `is_excluded`를 사용. es.md §1.2.2 매핑에는 두 필드 모두 없음 → **P2-6**

---

### RD-MS-06 — 운영 고려사항 (10%)

**점수: 85**

**잘 된 점**:
- 7개 메트릭(`search.keyword_count`, `search.rag_count`, `search.keyword_latency_ms`, `search.rag_latency_ms`, `search.zero_result_rate`, `search.rag_confidence_avg`, `circuit.retrieval.state_change`)이 수집 방식과 함께 정의됨
- 5개 알림 임계값이 조건, 심각도, 채널까지 표로 정리됨
- 외부 설정값 카탈로그(4개 키)에 기본값, 용도, 참조가 모두 명시
- 배치 작업(schedule.md)에 분산 락, 실패 처리, 데이터 무결성 보장이 체계적으로 설계됨

---

### 공용 점수 산출

| ID | 차원 | 가중치 | 점수 | 가중 점수 |
|----|------|:------:|:----:|:---------:|
| RD-MS-01 | API 설계 품질 | 30% | 78 | 23.4 |
| RD-MS-02 | 구현 변환 용이성 | 10% | 72 | 7.2 |
| RD-MS-03 | 이벤트/비동기 설계 건전성 | 25% | 80 | 20.0 |
| RD-MS-04 | 모듈 책임 범위 적절성 | 15% | 85 | 12.8 |
| RD-MS-05 | 모듈 간 계약 명확성 | 10% | 75 | 7.5 |
| RD-MS-06 | 운영 고려사항 | 10% | 85 | 8.5 |
| | | **합계** | | **79** |

---

## 3. 전문 루브릭 채점

> 출처: `senior-developer.md` §모듈 스펙 전문 루브릭

### EX-MS-SR-01 — 런타임 안정성 설계 (50%)

**점수: 78**

**잘 된 점**:
- RetrievalServiceClient에 피처 게이트(`ft:search.rag`) + 서킷브레이커(`{tenant_id}:circuit:retrieval-service`) + 타임아웃(검색 10s, 설정 push 5s) 3중 방어가 설계됨
- DLQ가 큐별로 정의되고 모니터링·수동 처리 방법이 명시됨 (events.md §6)
- Reconciliation 배치(30분 주기)로 ES 인덱스 불일치를 자동 보정하는 안전망이 있음
- 분산 락(Redis, TTL 기반)으로 배치 동시 실행이 제어됨
- SearchLog 아카이빙의 INSERT 후 건수 검증, DELETE WHERE 보관 기간 재확인 등 데이터 무결성 보장이 견고함

**개선 필요**:
- SearchRepository 오퍼레이션(searchByKeyword, indexDocumentBlocks, removeDocument 등)에 대한 타임아웃이 정의되지 않았다. RetrievalServiceClient에는 명시적 타임아웃이 있으나, 검색 엔진 접근에는 없다. ES 장애/지연 시 서비스 전체로 지연이 전파될 수 있다. ElasticsearchSearchAdapter 수준에서 최소한 커넥션 타임아웃과 요청 타임아웃을 정의하는 것을 권장 → **P2-4**

---

### EX-MS-SR-02 — 참조 무결성 (50%)

**점수: 70**

**잘 된 점**:
- SearchRepository 인터페이스가 모듈 전반에서 일관되게 참조됨: README.md(정의), api.md(POST /search 설명), events.md(모든 소비 이벤트), rules.md(BR-SCH-001, 029, 032, 034), schedule.md(S1), data.md(설정 동기화)
- es.md도 "SearchRepository 인터페이스를 통해 aicm_blocks 인덱스에 접근"이라는 문맥이 추가됨
- 에러 코드 카탈로그(rules.md §3)의 모든 에러가 api.md에서 참조됨
- 설정값 카탈로그(README.md)의 키가 schedule.md 및 rules.md와 일치

**개선 필요**:
- **ES 매핑 ↔ SearchConfig 필드 가중치 불일치**: es.md §1.2.2 매핑에는 텍스트 필드가 `content_text`와 `content_caption` 2개뿐이나, SearchConfig에는 5개 가중치(`kw_title_weight`, `kw_body_weight`, `kw_caption_weight`, `kw_tag_weight`, `kw_comment_weight`)가 정의되어 있다. `title`과 `comment`에 대응하는 ES 텍스트 필드가 매핑에 없고, `tags`는 keyword 타입(필터용)이라 multi_match 대상이 아니다. ElasticsearchSearchAdapter가 5가중치를 2필드에 어떻게 매핑하는지 문서화되지 않았다 → **P2-3**
- ~~**categoryIds 필터 누락**~~ → Category 폐지로 자동 해소 (~~P2-1~~)
- **보조 타입 미정의**: SearchRepository의 6개 보조 타입 미정의 → **P2-2**
- **is_excluded 필드명 불일치**: FD(`is_search_excluded`) vs MS(`is_excluded`) vs ES 매핑(없음) → **P2-6**

---

### 전문 점수 산출

| ID | 차원 | 가중치 | 점수 | 가중 점수 |
|----|------|:------:|:----:|:---------:|
| EX-MS-SR-01 | 런타임 안정성 설계 | 50% | 78 | 39.0 |
| EX-MS-SR-02 | 참조 무결성 | 50% | 70 | 35.0 |
| | | **합계** | | **74** |

---

## 4. 종합 점수

| 계층 | 점수 | 비율 | 가중 점수 |
|------|:----:|:----:|:---------:|
| 공용 루브릭 | 79 | 60% | 47.4 |
| 전문 루브릭 | 74 | 40% | 29.6 |
| **종합** | | | **77 → 79** |

> R1(69) → R2(79): **+10점 향상**. P1 2건 해소로 구조적 완성도가 크게 개선됨. 잔여 P2 6건은 참조 정합성과 인터페이스 세부 정의에 집중되어 있으며, 실제 구현 착수 전 해소 권장.

> 79점은 **양호** 등급이다. "대부분 견고하며, 소수 개선 권고만 존재"하는 수준이다.

---

## 5. 잔여 지적사항

### P2 — 중요 (6건)

#### ~~P2-1 — 카테고리 필터 누락~~ (자동 해소)

Category 엔티티가 폐지되고 게시판 트리(Board.parent_id)로 대체되어, `categoryIds` 필터 자체가 불필요해졌다. 이 이슈는 자동 해소되었다.

---

#### P2-2 — SearchRepository 보조 타입 미정의

| 항목 | 내용 |
|------|------|
| **차원** | RD-MS-02, EX-MS-SR-02 |
| **위치** | README.md §SearchRepository 인터페이스 |
| **내용** | SearchRepository 인터페이스에서 사용하는 6개 보조 타입이 정의되지 않았다: `FieldWeights`, `IndexableBlock`, `DocumentMetadata`, `IndexableMetadata`, `KeywordSearchResult`, `AutocompleteResult`. 메인 계약(SearchRepository, SearchFilters)은 잘 정의되었으나, 반환값과 파라미터 타입의 구체적 형상이 없다. |
| **영향** | 구현 시 개발자가 타입 형상을 추정해야 한다. 특히 `KeywordSearchResult`는 api.md의 `KeywordSearchResponse`와 일치해야 하는데 명시적 매핑이 없다. `IndexableBlock`은 es.md §1.2.2의 ES 매핑 필드와 정합해야 한다. |
| **조치 제안** | README.md에 보조 타입의 TypeScript 인터페이스를 추가하거나, 최소한 "api.md의 `KeywordSearchResponse` 구조와 동일" 등의 참조 문구를 명시 |

---

#### P2-3 — ES 매핑 ↔ SearchConfig 필드 가중치 불일치

| 항목 | 내용 |
|------|------|
| **차원** | EX-MS-SR-02 |
| **위치** | es.md §1.2.2 (매핑) ↔ data.md §2.1 SearchConfig (5개 `kw_*_weight`) |
| **내용** | ES `aicm_blocks` 매핑에는 텍스트 검색 필드가 `content_text`(블록 그룹 본문)와 `content_caption`(캡션) 2개뿐이다. 그러나 SearchConfig에는 `kw_title_weight`, `kw_body_weight`, `kw_caption_weight`, `kw_tag_weight`, `kw_comment_weight` 5개 가중치가 정의되어 있다. `title`, `comment`에 대응하는 ES 텍스트 필드가 매핑에 없고, `tags`는 `keyword` 타입(필터 전용)이라 `multi_match` 대상이 아니다. |
| **영향** | ElasticsearchSearchAdapter 구현 시 5개 가중치를 2개 텍스트 필드에 어떻게 매핑하는지 추정이 필요하다. 특히 title 검색은 사용자 기대가 높은 기능인데, 현재 매핑으로는 제목만 별도 가중치를 줄 수 없다. |
| **조치 제안** | (A) es.md 매핑에 `title`(text, nori), `comment_text`(text, nori), `tags_text`(text, nori) 필드를 추가하거나, (B) 현재 2필드 매핑에서 5가중치를 처리하는 로직(예: title은 content_text 내 heading 블록으로 처리)을 SearchRepository 구현체 매핑 표 또는 es.md에 명시 |

---

#### P2-4 — SearchRepository 오퍼레이션 타임아웃 미정의

| 항목 | 내용 |
|------|------|
| **차원** | RD-MS-03, EX-MS-SR-01 |
| **위치** | README.md §SearchRepository, events.md §4.1 |
| **내용** | RetrievalServiceClient에는 타임아웃이 명확히 정의(검색 10s, 설정 push 5s)되었으나, SearchRepository(ElasticsearchSearchAdapter) 오퍼레이션에는 타임아웃이 없다. `searchByKeyword`, `indexDocumentBlocks`, `syncAnalyzerSettings` 등의 호출에 대한 커넥션/요청 타임아웃이 문서화되지 않았다. |
| **영향** | ES 지연/장애 시 서비스 스레드가 무기한 블로킹되어 전체 API 지연이 전파될 수 있다. README.md의 모니터링 알림에 `keyword_latency_ms > 1000`이 있으나, 이는 감지일 뿐 방어가 아니다. |
| **조치 제안** | SearchRepository(또는 ElasticsearchSearchAdapter) 수준에서 검색 타임아웃(예: 3s), 인덱싱 타임아웃(예: 10s), 설정 동기화 타임아웃(예: 30s)을 정의. events.md §4 외부 서비스 호출 표와 동일한 형식을 권장 |

---

#### P2-5 — `document.content-updated` 재시도 정책 미명시

| 항목 | 내용 |
|------|------|
| **차원** | RD-MS-03 |
| **위치** | events.md §3.2 |
| **내용** | `document.published`(§3.1)는 "최대 3회, 지수 백오프(초기 5s, 최대 120s), 소진 후 DLQ `es-indexing:dlq`"가 명확히 기술되었다. 그러나 `document.content-updated`(§3.2)는 멱등성 키(`documentId + version`)만 기술되어 있고, 재시도 정책과 DLQ 소진 후 처리가 누락되었다. 동일 `es-indexing` 큐를 사용하므로 동일 정책이 적용될 것으로 추정되나, `document.suspended/unsuspended`(§3.4), `document.archived`(§3.5)도 마찬가지로 재시도 정책이 개별 명시되어 있지 않다. |
| **조치 제안** | (A) 각 소비 이벤트 상세에 재시도 정책을 명시하거나, (B) events.md 상단에 "es-indexing 큐의 기본 재시도 정책: 최대 3회, 지수 백오프(초기 5s, 최대 120s), DLQ `es-indexing:dlq`" 공통 정의 후 개별 섹션에서 "큐 기본 정책 적용" 참조 |

---

#### P2-6 — `is_excluded` 필드명 불일치 및 ES 매핑 누락

| 항목 | 내용 |
|------|------|
| **차원** | RD-MS-05, EX-MS-SR-02 |
| **위치** | FD-SCH §1 BR-SCH-029 ↔ README.md SearchRepository `setExcluded()` ↔ es.md §1.2.2 |
| **내용** | 긴급 검색 제외 필드명이 문서 간 불일치한다. FD-SCH §1 BR-SCH-029는 `is_search_excluded`, rules.md BR-SCH-029는 `is_excluded`, SearchRepository는 `setExcluded(documentId, excluded)`. 그리고 es.md §1.2.2 매핑에는 어느 이름으로도 해당 필드가 정의되어 있지 않다. |
| **영향** | 구현 시 필드명 혼선. 특히 ES 매핑에 필드가 없어 `setExcluded()` Adapter 구현이 불가능하다. |
| **조치 제안** | (A) 필드명을 하나로 통일(예: `is_excluded`), (B) es.md §1.2.2 매핑에 `"is_excluded": { "type": "boolean" }` 추가, (C) BR-SCH-029와 FD-SCH의 필드명도 동일하게 정리 |

---

### P3 — 개선 권고 (3건)

#### P3-1 — FD `size` vs MS `limit` 파라미터명 차이

| 항목 | 내용 |
|------|------|
| **차원** | RD-MS-01 |
| **내용** | FD-SCH §7.1 SearchRequest는 `size`, api.md의 KeywordSearchDto는 `limit`으로 페이지 크기 파라미터명이 다르다. 의도적 변경이면 FD에 반영하거나 api.md에 변경 사유 주석을 추가 |

#### P3-2 — SynonymGroup 타입과 Synonym 엔티티 관계 모호

| 항목 | 내용 |
|------|------|
| **차원** | RD-MS-02 |
| **내용** | SearchRepository `syncAnalyzerSettings()`의 `synonyms: SynonymGroup[]` 타입이 정의되지 않았다. data.md의 `Synonym` 엔티티(`words: VARCHAR[]`)와의 매핑이 모호하다. `SynonymGroup`이 `Synonym` 엔티티의 DTO 변환인지 명시하면 좋겠다 |

#### P3-3 — EmbeddingStatus `skipped` 값 MS 추가

| 항목 | 내용 |
|------|------|
| **차원** | EX-MS-SR-02 |
| **내용** | api.md의 `EmbeddingStatus`에 `skipped` 값이 포함되어 있으나, FD-SCH §7.1의 `embedding_status` enum에는 `pending/processing/completed/failed/partial`만 있다. MS에서 추가한 것이면 FD 반영 여부를 검토 |

---

## 6. R1 → R2 변화 요약

```
R1 (69점)                          R2 (79점)
──────────────────────────────────────────────────────
P1: 2건 (SearchRepository 미정의,  → P1: 0건 (모두 해소)
     Write 경로 추상화 부재)

P2: 1건 (api.md 직접 ES 참조)     → P2: 6건 (새로 식별)
                                      - ~~categoryIds 필터 누락~~ (Category 폐지로 해소)
                                      - 보조 타입 미정의
                                      - ES 매핑 ↔ 가중치 불일치
                                      - 검색 엔진 타임아웃 미정의
                                      - content-updated 재시도 미명시
                                      - is_excluded 필드명 불일치

P3: 없음                          → P3: 3건 (새로 식별)
```

**핵심 개선**: SearchRepository 인터페이스 도입으로 검색 솔루션 교체 시나리오에 대한 아키텍처 대비가 완성됨. 모듈 전반에서 "SearchRepository를 통해"라는 일관된 추상화가 적용됨.

**잔여 과제**: P2-2(보조 타입 정의)와 P2-3(ES 매핑 ↔ 가중치 정합)이 가장 구현 영향도가 높다. 이 두 건을 우선 해소하면 구현 착수에 큰 장애가 없을 것으로 판단한다.

---

## 7. 다음 단계 권장

1. **P2-3 → P2-2 순서로 해소** — ES 매핑 필드 확정 후 보조 타입(IndexableBlock 등)을 정의하면 자연스럽게 정합됨
2. ~~**P2-1 (categoryIds)**~~ — Category 폐지로 자동 해소
3. **P2-4, P2-5** — events.md에 큐 기본 정책 섹션 추가로 한 번에 해소 가능
4. **P2-6** — 필드명 통일 + es.md 매핑 보완

> R3 리뷰 시점: P2 6건 중 4건 이상 해소되면 R3 재리뷰 권장. 80점대 진입이 기대됨.
