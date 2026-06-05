# aicm-service — Elasticsearch

> aicm-service가 소유하는 ES 인덱스: `aicm_blocks` (문서 검색)

---

## 1. `aicm_blocks` — 문서 검색 인덱스

### 1.1 인덱스 개요

| 항목 | 값 |
|------|-----|
| 인덱스명 | `aicm_blocks` |
| 용도 | 문서 검색 (BM25 단독 사용) |
| 인덱싱 단위 | **블록 그룹 단위** (그룹 1건 = ES doc 1건). 인접 짧은 블록을 그룹으로 병합하되, 그룹 식별자는 ES에 저장하지 않음 (ADR-012 참조) |
| 스코어링 | BM25 |
| 인덱싱 주체 | aicm-service |
| 인덱싱 트리거 | 승인 완료(published) 이벤트 — BlockSnapshot에서 인덱싱 |

> **왜 블록 그룹 단위인가**: 블록 과세분화(over-fragmentation)를 방지하고 BM25 품질을 안정화하기 위해 인접 짧은 블록을 그룹으로 병합하여 인덱싱한다. 검색 결과는 `document_id`로 collapse하여 문서 단위로 그루핑한다. 그룹은 RDB에 영속되지 않는 런타임 계산 결과이므로(ADR-012 §3.1), ES에는 그룹 식별자(`group_id`)나 그룹 타입(`group_type`)을 저장하지 않는다. 대신 `block_ids` 필드에 해당 그룹을 구성하는 블록 ID 목록을 저장하여, 검색 히트 → 블록 역추적에 사용한다. 재발행 시에는 해당 문서의 ES doc을 전량 삭제 후 재생성한다.

> **ES 인덱스 운영**: aicm-service는 `aicm_blocks`(문서 검색)를 소유한다. 접근 로그는 RDB `access_event_log` 테이블에 저장한다 ([rdb.md](./rdb.md) 참조). retrieval-service는 `aicm_chunks`(RAG 하이브리드 합산)를 소유한다. `aicm_chunks`에 대해서는 [retriever/es.md](../retriever/es.md)를 참조한다.

> **검색 엔진 추상화**: aicm-service는 SearchRepository 인터페이스를 통해 `aicm_blocks` 인덱스에 접근한다. 기본 구현체인 ElasticsearchSearchAdapter가 아래의 매핑·쿼리 패턴을 캡슐화하며, 고객 요구에 따라 다른 검색 솔루션(다이퀘스트 등) 어댑터로 교체할 수 있다. 이 문서의 ES 매핑·쿼리는 ElasticsearchSearchAdapter의 구현 참조로 기능한다.

---

### 1.2 인덱스 매핑

#### 1.2.1 공통 분석기 설정 (Settings)

```json
{
  "settings": {
    "analysis": {
      "analyzer": {
        "nori_analyzer": {
          "type": "custom",
          "tokenizer": "nori_tokenizer",
          "filter": ["nori_readingform", "lowercase"]
        }
      },
      "tokenizer": {
        "nori_tokenizer": {
          "type": "nori_tokenizer",
          "decompound_mode": "mixed",
          "user_dictionary_rules": []
        }
      }
    }
  }
}
```

#### 1.2.2 Mappings

```json
{
  "mappings": {
    "properties": {
      "document_id":   { "type": "keyword" },
      "board_id":      { "type": "keyword" },
      "block_ids":     { "type": "keyword" },
      "is_suspended":  { "type": "boolean" },
      "is_excluded":   { "type": "boolean" },
      "tags":          { "type": "keyword" },
      "sequence":      { "type": "integer" },
      "content_text": {
        "type": "text",
        "analyzer": "nori_analyzer"
      },
      "content_caption": {
        "type": "text",
        "analyzer": "nori_analyzer"
      },
      "created_at":    { "type": "date" }
    }
  }
}
```

**필드 설명:**

| 필드 | 소스 | 설명 |
|------|------|------|
| `document_id` | Document.id | collapse 그루핑 키 |
| `board_id` | Document → Board.id | 게시판 필터 (비정규화) |
| `block_ids` | 머지 알고리즘 산출 (블록 ID 목록) | 검색 히트 → 블록 역추적용. 이 ES doc을 구성하는 블록 ID 배열 |
| `content_text` | 그룹 내 블록들의 content_text 병합 | nori 형태소 분석 → BM25 키워드 매칭 |
| `content_caption` | 그룹 내 블록들의 caption 병합 | nori 형태소 분석 → caption 키워드 매칭 |
| `tags` | Document → DocumentTag → Tag | 문서 태그 필터 (keyword 배열, 비정규화) |
| `is_suspended` | Document.is_suspended | 일시 정지 필터 (비정규화) |
| `is_excluded` | 관리자 긴급 제외 플래그 | 긴급 검색 제외/복원 필터 ([BR-SCH-029](../../../03-module-design/search/rules.md), SearchRepository.setExcluded) |
| `sequence` | 그룹 내 첫 블록의 sequence | inner_hits 정렬 기준 |
| `created_at` | Document.created_at | 기간 필터 |

> **그룹 식별 필드가 없는 이유**: 인덱싱 단위는 그룹(인접 블록 병합)이지만, `group_id`나 `group_type` 같은 그룹 정체성(identity) 필드는 저장하지 않는다. 그룹은 RDB에 영속되지 않는 런타임 계산 결과이며(ADR-012 §3.1), 재발행 시 해당 문서의 ES doc을 전량 삭제 후 재생성하므로 기존 그룹을 식별할 필요가 없다. 검색 히트 → 블록 역추적은 `block_ids` 필드로 수행한다.

> **비정규화 필드**: `board_id`, `tags`, `is_suspended`는 Document에서 가져와 ES 문서에 비정규화한다. ES는 JOIN이 불가능하므로 필터링에 필요한 필드를 인덱싱 시점에 미리 펼쳐 저장한다. 문서 메타데이터가 변경되면(태그 수정, 일시 정지 등) 해당 문서의 ES 문서들도 함께 업데이트한다.

---

### 1.3 문서 검색 쿼리 패턴

그룹 단위로 인덱싱하면 같은 문서의 여러 ES doc이 히트되므로, `collapse`로 문서 단위 그루핑 + `inner_hits`로 각 문서의 히트 목록을 함께 가져온다.

```json
{
  "query": {
    "bool": {
      "must": {
        "multi_match": {
          "query": "계좌 개설",
          "fields": ["content_text", "content_caption"]
        }
      },
      "filter": [
        { "term": { "is_suspended": false } },
        { "term": { "is_excluded": false } },
        { "terms": { "tags": ["계좌 개설"] } }
      ]
    }
  },
  "collapse": {
    "field": "document_id",
    "inner_hits": {
      "name": "matched_groups",
      "size": 5,
      "sort": [{ "_score": "desc" }],
      "_source": ["block_ids", "sequence"]
    }
  },
  "size": 10,
  "from": 0
}
```

이 쿼리 하나로:
- `multi_match`로 **content_text(텍스트/표 셀)와 content_caption(이미지·표 캡션)** 동시 검색
- `filter`로 `is_suspended`, 문서 태그(`tags`) 등 범위 축소 (태그 필터는 사용자가 선택한 경우에만)
- `size`/`from`으로 **문서 단위 페이지네이션** (page 1에 문서 10개)
- 각 문서에서 **가장 스코어 높은 그룹이 대표**로 정렬
- `inner_hits`로 각 문서에서 히트된 **그룹 최대 5개** 반환 — `block_ids`로 히트 블록을 역추적하여 하이라이트

---

### 1.4 인덱싱 시점

- 테넌트별 인프라 격리 (DB-per-tenant와 동일 원칙) — 인덱스명에 테넌트 식별자 불필요
- 한국어 형태소 분석기 `nori` 적용, 사용자 사전(동의어/불용어) 지원

| 이벤트 | 인덱싱 동작 |
|--------|-----------|
| 문서 발행 (published) | BlockSnapshot 기반으로 머지 알고리즘을 실행하여 그룹을 구성한 뒤 bulk 인덱싱 (ADR-012 참조) |
| 재발행 (v2+ published) | 해당 문서의 기존 ES doc **전량 삭제** → 머지 알고리즘 재실행 → 새 그룹 전량 인덱싱 |
| 메타데이터 변경 (태그 수정, 일시 정지) | 해당 문서의 ES 문서들의 비정규화 필드 업데이트 (`update_by_query`) |
| archived / 삭제 | 해당 문서의 ES 문서 전량 삭제 (`delete_by_query`) |

> **재발행이 증분 업데이트가 아닌 전량 재인덱싱인 이유**: 그룹은 RDB에 영속되지 않는 런타임 계산 결과이므로(ADR-012 §3.1), 기존 ES doc의 식별자를 알 수 없다. 전량 삭제 후 재생성이 가장 단순하고 신뢰성 높은 전략이다. ES 텍스트 인덱싱은 임베딩과 달리 수십 ms 수준이므로 비용이 무시할 수 있다.

---

**관련 문서**
- [전체 개요](../README.md)
- [RDB 엔티티](./rdb.md) — Block/BlockSnapshot 엔티티 정의, AccessEventLog(접근 로그) 테이블
- [Redis Key 패턴](./redis.md) — Access Log 관련 Redis 키 패턴
- [횡단 관심사](../../07-cross-cutting-concerns.md) — Access Log 전략 (8.1.1)
- [retriever/es.md](../retriever/es.md) — ES `aicm_chunks` 인덱스 (RAG 하이브리드 합산용)
