# retrieval-service — Elasticsearch (`aicm_chunks`)

> RAG 하이브리드 합산용 청크 단위 BM25 인덱스 — 매핑, 인덱싱 시점

---

## 1. 인덱스 개요

| 항목 | 값 |
|------|-----|
| 인덱스명 | `aicm_chunks` |
| 용도 | RAG 하이브리드 합산용 (BM25 점수 + Milvus 벡터 점수를 같은 chunk_id 기준으로 RRF 합산) |
| 인덱싱 단위 | **청크 단위** (Chunk 1건 = ES doc 1건) |
| 스코어링 | BM25 |
| 인덱싱 주체 | retrieval-service |
| 인덱싱 트리거 | 청킹/임베딩 완료 시 (Milvus 저장과 동시에 ES에도 저장) |

> **왜 청크 단위인가**: Milvus 벡터 검색은 청크 단위로 결과를 반환한다. ES BM25 점수 + Milvus 벡터 점수를 **같은 chunk_id 기준으로 합산**(RRF 등)하려면 인덱싱 단위가 동일해야 한다.

> **`aicm_blocks`와의 차이**: `aicm_blocks`(aicm-service 소유)는 블록 단위로 인덱싱되어 사용자 대면 문서 검색에서 단독으로 결과를 반환한다. `aicm_chunks`는 Milvus와의 하이브리드 합산 전용이다. 자세한 내용은 [aicm/es.md](../aicm/es.md)를 참조한다.

---

## 2. 인덱스 매핑

공통 분석기 설정(`nori_analyzer`)은 [aicm/es.md](../aicm/es.md)와 동일하다.

```json
{
  "mappings": {
    "properties": {
      "chunk_id":      { "type": "keyword" },
      "document_id":   { "type": "keyword" },
      "board_id":      { "type": "keyword" },
      "is_suspended":  { "type": "boolean" },
      "tags":          { "type": "keyword" },
      "chunk_text": {
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
| `chunk_text` | Chunk.content_text | nori BM25 스코어링 → Milvus 벡터 점수와 RRF 합산 |
| `chunk_id` | keyword | Milvus chunk_id와 동일 → RRF 매칭 키 |

> **비정규화 필드**: `board_id`, `tags`, `is_suspended`는 Document/Block에서 가져와 ES 문서에 비정규화한다. ES는 JOIN이 불가능하므로 필터링에 필요한 필드를 인덱싱 시점에 미리 펼쳐 저장한다. 문서 메타데이터가 변경되면(태그 수정, 일시 정지 등) 해당 문서의 ES 문서들도 함께 업데이트한다.

> **`group_id`/`group_type` 미저장**: Milvus `kms_chunks`와 동일하게, 그룹 정보는 ES 청크 인덱스에 저장하지 않는다. 블록 그룹 역추적은 `chunk_id`로 RDB Chunk 테이블을 조회하여 수행한다.

---

## 2-1. 하이브리드 검색 시 사전 필터 적용

하이브리드 검색에서 BM25 검색 실행 시, aicm-service가 retrieval-service 검색 API로 전달한 `filters` 파라미터를 ES bool 쿼리 필터로 적용한다. Milvus 스칼라 필터와 동일한 패턴이다.

| 필터 파라미터 | ES 적용 |
|---|---|
| `filters.must.source_metadata.board_id` | `bool.filter.terms: { board_id: [...] }` |
| `filters.must_not.source_ids` | `bool.must_not.terms: { document_id: [...] }` |
| (기본) `is_suspended` | `bool.filter.term: { is_suspended: false }` |

이를 통해 하이브리드 RRF 합산 시 BM25 측과 벡터 측 모두 동일한 권한 필터가 적용되어, 접근 불가한 청크가 양쪽 검색 결과에서 원천 배제된다.

---

## 3. 인덱싱 시점

| 이벤트 | 인덱싱 동작 |
|--------|-----------|
| 청킹/임베딩 완료 | Milvus 저장과 동시에 ES에도 청크 저장 |
| 재임베딩 (블록 변경) | 변경된 블록이 포함된 그룹의 청크를 교체 |
| 메타데이터 변경 | 해당 문서의 ES 문서들의 비정규화 필드 업데이트 |
| archived / 삭제 | 해당 문서의 ES 문서 삭제 |

---

**관련 문서**
- [retrieval-service 개요](./README.md) — 검색 모드, 파이프라인
- [Milvus kms_chunks](./milvus.md)
- [aicm/es.md](../aicm/es.md) — ES `aicm_blocks` (문서 검색용)
