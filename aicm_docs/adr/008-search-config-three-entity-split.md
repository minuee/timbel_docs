# ADR-002: 검색 설정 3엔티티 분리 (KeywordSearchConfig / RagSearchConfig / ParsingConfig)

- **상태**: ~~승인됨~~ → **Superseded by [ADR-009](./009-search-config-singleton-merge.md)**
- **날짜**: 2026-03-25
- **의사결정자**: 개발팀
- **관련 문서**: [FD-SCH](../01-requirements/features/FD-SCH-검색.md), [FD-SYS](../01-requirements/features/FD-SYS-시스템설정.md), [04-search-tuning](../01-requirements/flows/search-rag/04-search-tuning.md), [search-config-module](../03-module-design/search-config/data.md)

---

## 1. 컨텍스트

### 1.1 기존 구조: 단일 SearchConfig에 모든 검색 설정이 혼재

기존 설계에서 `SearchConfig`는 테넌트당 1건의 단일 엔티티로, 키워드 검색(ES/nori)·RAG 검색(retrieval-service)·파싱/청킹 파라미터가 모두 섞여 있었다.

| 기존 SearchConfig 필드 | 실제 성격 |
|----------------------|----------|
| `nori_user_dict` | 키워드 검색 — ES nori 형태소 분석기 전용 |
| FieldWeight (`title_weight`, `body_weight`, `caption_weight`) | 키워드 검색 — ES `multi_match` 가중치 |
| Synonym, StopWord, BoostRule | 키워드 검색 — ES 분석기/스코어링 |
| `hybrid_bm25_weight`, `hybrid_vector_weight`, `rrf_k` | RAG 검색 — retrieval-service 하이브리드 파라미터 |
| `rerank_enabled`, `rerank_model`, `rerank_top_n` | RAG 검색 — retrieval-service 리랭킹 |
| `rag_top_k`, `rag_window_context_size` | RAG 검색 — retrieval-service 검색 파라미터 |
| RagConfig (`chunk_max_tokens`, `chunk_overlap_tokens`) | 파싱/청킹 — 임베딩 파이프라인 |

### 1.2 SystemConfig과의 이중 정의

FD-SYS의 SystemConfig Key-Value에도 동일한 값이 `pm:search.title_weight`, `pm:parsing.chunk_size` 등으로 중복 정의되어 있었다. 진실의 원천이 모호했다.

### 1.3 문서 간 모델 불일치

`search-config-module.md`(데이터 아키텍처)에서는 SearchConfig를 key-value 테이블로 정의하고, `04-search-tuning.md`(흐름도)에서는 구조화된 컬럼 엔티티로 정의하여 동일 이름의 엔티티가 서로 다른 스키마를 가지고 있었다.

---

## 2. 결정

### 2.1 SearchConfig → KeywordSearchConfig + RagSearchConfig 분리

**KeywordSearchConfig** — ES/nori 직접 연동, aicm-service 내부에서 소비:

| 필드/하위 엔티티 | 설명 |
|---------------|------|
| `nori_user_dict` | nori 사용자 사전 |
| FieldWeight (1:1) | 제목/본문/캡션 필드 가중치 |
| Synonym (1:N) | 동의어 그룹 |
| StopWord (1:N) | 불용어 |
| BoostRule (1:N) | 부스팅 규칙 |

**RagSearchConfig** — retrieval-service에 push 동기화:

| 필드/하위 엔티티 | 설명 |
|---------------|------|
| `default_search_mode` | 기본 검색 모드 (keyword/semantic/hybrid) |
| `hybrid_bm25_weight`, `hybrid_vector_weight`, `rrf_k` | 하이브리드 검색 가중치 |
| `rerank_enabled`, `rerank_model`, `rerank_top_n` | 리랭킹 설정 |
| `rag_top_k`, `rag_window_context_size` | RAG 검색 파라미터 |
| `similarity_threshold` | 유사도 임계값 |
| BoardRagConfig (1:N) | 게시판별 RAG 오버라이드 (rag_enabled, top_k, similarity_threshold, prompt_template_id, model_id) |

### 2.2 ParsingConfig 신설

기존 RagConfig에 혼재된 청킹 파라미터와 SystemConfig의 parsing 키를 통합한 전용 엔티티:

| 필드/하위 엔티티 | 설명 |
|---------------|------|
| `default_chunking_strategy` | 기본 청킹 전략 (`fixed_token` / `semantic` / `sliding_window`) |
| `chunk_size` | 청크 토큰 수 (기본 512) |
| `chunk_overlap_percent` | 오버랩 비율 (기본 10%) |
| BoardParsingOverride (1:N) | 게시판별 청킹 파라미터 오버라이드 |
| TemplateChunkingRule (1:N) | 템플릿별 청킹 전략 매핑 (FAQ→Q&A 쌍, SOP→스텝 단위 등) |

### 2.3 동기화 패턴

| 엔티티 | 동기화 방식 | 근거 |
|--------|-----------|------|
| KeywordSearchConfig | aicm-service → ES 직접 적용 | ES nori 설정은 인덱스 close/open 배치 배포 |
| RagSearchConfig | aicm-service → retrieval-service `PUT /config` (Push) | 검색 API가 실시간 다수 호출되므로 사전 캐싱 필요 |
| ParsingConfig | aicm-service → `POST /ingest/embed` 요청 시 `chunking_config` 파라미터 동봉 | 임베딩은 published 시점에만 발생하여 빈도 낮음, retrieval-service stateless 유지 |

### 2.4 SystemConfig에서 검색/파싱 카테고리 제거

SystemConfig은 범용 운영 설정(파일 업로드, 알림, 집계, 감사, 내보내기, 임베딩 워커, 커뮤니티)만 관리한다. `pm:search.*`, `pm:parsing.*` 키는 더 이상 SystemConfig에 정의하지 않는다.

---

## 3. 근거

### 3.1 변경 주기가 다름

| 엔티티 | 변경 주기 | 변경 시 비용 |
|--------|----------|------------|
| KeywordSearchConfig | 비빈번 | ES 인덱스 close/open, 전체 재인덱싱 (nori 사전 변경 시) |
| RagSearchConfig | 중빈번 | retrieval-service 캐시 갱신 (즉시 반영) |
| ParsingConfig | 저빈번 | 영향 문서 재청킹/재임베딩 필요 (비용 큼) |

### 3.2 소비자가 다름

| 엔티티 | 소비자 | 통신 경로 |
|--------|--------|----------|
| KeywordSearchConfig | aicm-service → ES 직접 | ES REST API |
| RagSearchConfig | aicm-service → retrieval-service | HTTP `PUT /config` |
| ParsingConfig | 임베딩 파이프라인 (BullMQ 워커) → retrieval-service | HTTP `POST /ingest/embed` 파라미터 |

### 3.3 ParsingConfig을 요청 시 동봉하는 이유

- 게시판/템플릿별 오버라이드가 있어, 문서마다 적용할 청킹 설정이 다를 수 있음 — 전부 사전 push하면 복잡
- 임베딩은 문서 `published` 시점에만 발생하여 호출 빈도가 낮음 — 매번 설정 동봉의 네트워크 비용 무시 가능
- retrieval-service가 파싱 설정 상태를 보관하지 않아 stateless에 가까워짐 — parser-service 패턴과 일관

### 3.4 SystemConfig에서 제거하는 이유

- 구조화 엔티티(컬럼 기반)가 key-value보다 타입 안전성·유효성 검증에 유리
- 전용 엔티티는 retrieval-service push, ES 배치 배포 등 고유한 동기화 로직을 가지므로 범용 SystemConfig CRUD로 관리하기 부적절
- 이중 정의로 인한 진실의 원천 모호성 해소

---

## 4. 검토한 대안

| 대안 | 채택 여부 | 사유 |
|------|----------|------|
| 기존 단일 SearchConfig 유지 | 기각 | 관심사 혼재, SystemConfig과 이중 정의, 문서 간 모델 불일치 |
| SearchConfig + ParsingConfig (2분할) | 기각 | 키워드/RAG도 변경 주기·소비자·동기화 대상이 다름 |
| **3분할 (KeywordSearchConfig / RagSearchConfig / ParsingConfig)** | **채택** | 변경 주기, 소비자, 동기화 대상이 각각 다름 |
| 모든 설정을 SystemConfig Key-Value로 통합 | 기각 | 구조화 엔티티의 타입 안전성·검증 상실, retrieval-service 동기화 복잡 |

---

## 5. 영향

### 5.1 문서 갱신

| 범위 | 대상 문서 수 | 주요 파일 |
|------|-----------|----------|
| 기능정의서 | 4개 | FD-SYS, FD-SCH, FD-ADM, overview |
| 아키텍처 | 6개 | search-config-module, system-config-module, rdb, 00-overview, module-architecture, external-integration |
| 흐름도 | 5개 | 04-search-tuning, 03-search, 02-chunking, 01-parsing, README |
| 권한 | 2개 | permissions, resource-classification |
| ADR | 1개 | ADR-001 (관리 자원 예시 갱신) |

### 5.2 코드 영향

| 영역 | 변경 내용 |
|------|----------|
| SearchModule 엔티티 | `SearchConfig` → `KeywordSearchConfig` + `RagSearchConfig` 분리, `ParsingConfig` 신규 |
| EmbeddingProcessor | `POST /ingest/embed` 요청에 `chunking_config` 파라미터 추가 |
| retrieval-service | `IngestEmbedRequest`에 `chunking_config` 필드 확장 |
| DB 마이그레이션 | `search_config` → `keyword_search_config` + `rag_search_config` 분리, `parsing_config` 신규 |

### 5.3 AdminPermission 변경

`manage_search` AdminPermission이 3개 전용 엔티티를 모두 관리한다. 권한 키를 더 세분화(`manage_keyword_search`, `manage_rag_search`, `manage_parsing`)할지는 향후 검토 사항으로 남긴다.

---

## 6. 최종 구조 요약

```
검색/파싱 설정 엔티티:
  ├── KeywordSearchConfig     → aicm-service가 ES에 직접 적용
  │     ├── FieldWeight (1:1)
  │     ├── Synonym (1:N)
  │     ├── StopWord (1:N)
  │     └── BoostRule (1:N)
  │
  ├── RagSearchConfig         → retrieval-service에 PUT /config push
  │     └── BoardRagConfig (1:N, 게시판별 오버라이드)
  │
  └── ParsingConfig           → POST /ingest/embed 요청 시 동봉
        ├── BoardParsingOverride (1:N, 게시판별 오버라이드)
        └── TemplateChunkingRule (1:N, 템플릿별 전략)

SystemConfig (범용 운영 설정만):
  ├── system (업로드 제한)
  ├── document (태그 수, 자동 저장, 드래프트)
  ├── approval (긴급 발행 사유, 리마인더)
  ├── aggregation (인기 가중치, 트렌딩)
  ├── audit (보관 기간, access log)
  ├── export (워터마크)
  ├── embedding (워커, 재시도, 보관)
  └── community (신고 자동 비공개)
```
