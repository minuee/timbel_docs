# ADR-009: 검색 설정 싱글톤 통합 — search_config + parsing_config 2테이블 구조

- **상태**: 승인됨
- **날짜**: 2026-03-25
- **의사결정자**: 개발팀
- **대체**: [ADR-008](./008-search-config-three-entity-split.md)을 대체한다
- **관련 문서**: [search-config-module](../03-module-design/search-config/data.md), [rdb](../02-architecture/data/aicm/rdb.md), [FD-SCH](../01-requirements/features/FD-SCH-검색.md), [04-search-tuning](../01-requirements/flows/search-rag/04-search-tuning.md)

---

## 1. 컨텍스트

### 1.1 ADR-008이 만든 구조

ADR-008에서 단일 SearchConfig를 KeywordSearchConfig / RagSearchConfig / ParsingConfig 3개 전용 엔티티로 분리했다. 분리 근거는 ① 변경 주기가 다름, ② 소비자가 다름, ③ 동기화 패턴이 다름이었다.

```
KeywordSearchConfig (싱글톤)
  ├── FieldWeight (1:1)
  ├── Synonym (1:N)
  ├── StopWord (1:N)
  └── BoostRule (1:N)

RagSearchConfig (싱글톤)
  └── BoardRagConfig (1:N)

ParsingConfig (싱글톤)
  ├── BoardParsingOverride (1:N)
  └── TemplateChunkingRule (1:N)
```

### 1.2 과도 정규화 문제

| 문제 | 설명 |
|------|------|
| **싱글톤 3개 = 테이블 3개** | 3개 모두 시스템당 1행만 존재하는 설정 폼. "행 단위 조작" 개념 자체가 없다 |
| **FieldWeight 1:1 분리** | KeywordSearchConfig와 항상 1:1인데 별도 테이블. FieldWeight에 컬럼 추가도 결국 ALTER TABLE이므로 분리 이점 없음. 불필요한 JOIN만 발생 |
| **KeywordSearchConfig + RagSearchConfig 분리** | 둘 다 "검색" 설정이고, 관리자 화면에서도 같은 맥락에서 조회/수정. 튜닝 기간에 몇 번 만지고 끝나는 설정 폼을 굳이 2테이블로 나눌 실익 없음 |

### 1.3 파싱/청킹은 검색이 아니다

KeywordSearchConfig와 RagSearchConfig는 둘 다 **"검색할 때"** 소비되지만, ParsingConfig는 **"문서를 임베딩할 때"** 소비된다. 본질적으로 다른 파이프라인이다.

| 영역 | 소비 시점 | 소비자 | 동기화 방식 |
|------|----------|--------|-----------|
| 키워드 검색 | 검색 요청 시 | aicm-service → ES | ES 직접 적용 |
| RAG 검색 | 검색 요청 시 | aicm-service → retrieval-service | `PUT /config` push |
| **파싱/청킹** | **문서 발행(임베딩) 시** | **임베딩 파이프라인 → retrieval-service** | **`POST /ingest/embed` 요청 시 동봉** |

`search_config`라는 이름 안에 파싱 설정이 있으면 의미론적으로 어색하다. 테이블명만 보고 파싱 설정이 여기 있다고 예상하기 어렵다.

---

## 2. 결정

### 2.1 KeywordSearchConfig + FieldWeight + RagSearchConfig → search_config

키워드 검색과 RAG 검색 설정을 **search_config** 1개 싱글톤 테이블로 합친다. 컬럼 프리픽스(`kw_`, `rag_`)로 관심사를 구분한다.

| 프리픽스 | 영역 | 기존 테이블 | 동기화 대상 |
|---------|------|-----------|-----------|
| `kw_` | 키워드 검색 | KeywordSearchConfig + FieldWeight | ES 직접 적용 |
| `rag_` | RAG 검색 | RagSearchConfig | retrieval-service `PUT /config` |

### 2.2 ParsingConfig → parsing_config 독립 유지

파싱/청킹 설정은 **parsing_config** 싱글톤 테이블로 독립 유지한다. 프리픽스 없이 원래 컬럼명을 사용한다.

| 필드 | 동기화 대상 |
|------|-----------|
| `default_chunking_strategy`, `chunk_size`, `chunk_overlap_percent` | `POST /ingest/embed` 요청 시 동봉 |

### 2.3 하위 엔티티 FK

| 하위 엔티티 | FK | 부모 |
|------------|-----|------|
| Synonym, StopWord, BoostRule | `search_config_id` | search_config |
| BoardRagConfig | `search_config_id` | search_config |
| BoardParsingOverride | `parsing_config_id` | parsing_config |
| TemplateChunkingRule | `parsing_config_id` | parsing_config |

### 2.4 FieldWeight 컬럼 병합

FieldWeight 5개 컬럼(`title_weight`, `body_weight`, `caption_weight`, `tag_weight`, `comment_weight`)을 search_config에 `kw_` 프리픽스로 직접 병합한다. 1:1 테이블과 JOIN이 사라진다.

### 2.5 동기화 패턴은 유지

| 영역 | 동기화 방식 | 변경 없음 |
|------|-----------|----------|
| 키워드 검색 (`kw_*`) | aicm-service → ES 직접 적용 | O |
| RAG 검색 (`rag_*`) | aicm-service → retrieval-service `PUT /config` | O |
| 파싱/청킹 | `POST /ingest/embed` 요청 시 동봉 | O |

---

## 3. 근거

### 3.1 검색 설정은 합치고, 파싱은 분리하는 이유

| 관점 | KeywordSearch + RAG | Parsing |
|------|-------------------|---------|
| 소비 시점 | 검색 요청 시 (동일) | 문서 발행 시 (다름) |
| 관리자 화면 | "검색 설정" 같은 탭에서 관리 | "파싱/임베딩 설정" 별도 탭 |
| 개념 | 검색 | 인제스트 전처리 |
| 테이블명 | `search_config` — 자연스러움 | `search_config` — **어색** |

### 3.2 싱글톤 2개는 과도하지 않은가?

싱글톤이 1개든 2개든 물리적 비용 차이는 거의 없다. 그러나 **테이블명이 도메인 개념과 일치하는지**는 코드 가독성과 유지보수에 직접 영향을 준다. search_config에서 파싱 설정을 찾아야 하는 것보다, parsing_config에서 찾는 게 자연스럽다.

### 3.3 FieldWeight 1:1 분리의 이점이 없음

ADR-008에서 "향후 필드 추가 시 KeywordSearchConfig 스키마를 변경하지 않기 위해" 분리했으나, FieldWeight에 컬럼을 추가하는 것도 ALTER TABLE이므로 실질적 이점이 없다.

---

## 4. 검토한 대안

| 대안 | 채택 여부 | 사유 |
|------|----------|------|
| ADR-008 현행 유지 (3테이블) | 기각 | 싱글톤에 테이블 분리는 과도. FieldWeight 1:1이 불필요한 복잡도 추가 |
| search_config 1테이블에 전부 통합 | 기각 | 파싱/청킹은 검색이 아닌 인제스트 전처리. `search_config`라는 이름에 parse_*가 있으면 의미론적으로 어색 |
| SystemConfig key-value에 통합 | 기각 | 구조화된 컬럼의 타입 안전성·DEFAULT·CHECK 제약 상실 |
| **search_config + parsing_config 2테이블** | **채택** | 검색 설정 통합으로 과도 정규화 해소 + 파싱은 독립 도메인이므로 분리 유지 |

---

## 5. 영향

### 5.1 제거되는 테이블

| 테이블 | 사유 |
|--------|------|
| `keyword_search_config` | search_config `kw_*` 컬럼으로 병합 |
| `field_weight` | search_config `kw_*_weight` 컬럼으로 병합 |
| `rag_search_config` | search_config `rag_*` 컬럼으로 병합 |

### 5.2 변경되는 FK

| 테이블 | 기존 FK | 변경 후 FK |
|--------|---------|-----------|
| synonym | `keyword_search_config_id` | `search_config_id` |
| stop_word | `keyword_search_config_id` | `search_config_id` |
| boost_rule | `keyword_search_config_id` | `search_config_id` |
| board_rag_config | `rag_search_config_id` | `search_config_id` |
| board_parsing_override | `parsing_config_id` | `parsing_config_id` (변경 없음) |
| template_chunking_rule | `parsing_config_id` | `parsing_config_id` (변경 없음) |

### 5.3 문서 갱신

| 문서 | 변경 내용 |
|------|----------|
| search-config-module.md | search_config + parsing_config 2테이블 구조로 개편 |
| rdb.md | ERD 갱신, 모듈별 엔티티 목록 변경 |
| ADR-008 | 상태를 Superseded by ADR-009로 변경 (완료) |
| 기능정의서/흐름도 | KeywordSearchConfig + RagSearchConfig → SearchConfig 용어 치환, ParsingConfig 유지 |

### 5.4 코드 영향

| 영역 | 변경 내용 |
|------|----------|
| SearchModule 엔티티 | KeywordSearchConfig, FieldWeight, RagSearchConfig → SearchConfig. ParsingConfig 유지 |
| SearchConfigService | 검색 설정 UPSERT 1곳 + 파싱 설정 UPSERT 1곳 |
| DB 마이그레이션 | 3테이블 → 2테이블 마이그레이션. 검색 하위 엔티티 FK 변경 |

---

## 6. 최종 구조 요약

```
SearchConfig (싱글톤 — 시스템당 1행)
  ├── kw_*    : 키워드 검색 설정 (nori 사전, 필드 가중치)
  └── rag_*   : RAG 검색 설정 (하이브리드 가중치, 리랭킹, 유사도)

SearchConfig 하위 엔티티 (1:N, search_config_id FK):
  ├── Synonym               — 동의어 그룹
  ├── StopWord              — 불용어
  ├── BoostRule             — 부스팅 규칙
  └── BoardRagConfig        — 게시판별 RAG 오버라이드

ParsingConfig (싱글톤 — 시스템당 1행)
  └── 청킹 전략, 사이즈, 오버랩

ParsingConfig 하위 엔티티 (1:N, parsing_config_id FK):
  ├── BoardParsingOverride  — 게시판별 청킹 오버라이드
  └── TemplateChunkingRule  — 템플릿별 청킹 전략
```
