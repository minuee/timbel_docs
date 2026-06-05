# retrieval-service — Milvus (`kms_chunks`)

> 벡터 컬렉션 스키마, HNSW 인덱스 설정, 검색 필터, archived/삭제 처리

---

## 1. 컬렉션 스키마

retrieval-service가 소유·관리하는 벡터 스토리지이다. aicm-service는 Milvus에 직접 접근하지 않으며, 시맨틱/하이브리드 검색은 retrieval-service API를 통해 수행한다.

```
Collection: kms_chunks

Fields:
├── chunk_id       VARCHAR (PK)
├── source_id      VARCHAR          ← 문서 단위 필터 (핫패스, STL_SORT)
├── metadata       JSON             ← 호출자 전달 메타데이터 (pass-through)
├── embedding      FLOAT_VECTOR(1024)ㅍㅍ
└── created_at     INT64
```

**`metadata` JSON 필드 구조**

호출자(aicm-service)가 ingest 시 전달하는 메타데이터를 그대로 저장한다. retrieval-service는 이 필드의 내부 구조를 해석하지 않으며, 검색 필터 매핑과 pass-through 반환만 수행한다.

```jsonc
{
  // ── 검색 필터용 (핫패스) ──
  "board_id": "board-123",
  "is_suspended": false,
  "tags": ["태그A", "태그B"],

  // ── 재임베딩/정리용 (콜드패스) ──
  "item_id": "group-abc",
  "block_ids": ["block-1", "block-2", "block-3"]
}
```

| 구분 | 키 | 용도 | 접근 빈도 |
|------|-----|------|----------|
| 검색 필터 | `board_id` | 권한 사전 필터 — 접근 가능 게시판 필터링 | 핫패스 (매 검색) |
| 검색 필터 | `is_suspended` | 검색 일시 정지 필터 | 핫패스 (매 검색) |
| 검색 필터 | `tags` | 태그 필터 | 핫패스 (매 검색) |
| 재임베딩 | `item_id` | retriever가 ingest 시 부여한 item 식별자. 재임베딩 시 교체 대상 청크 조회 | 콜드패스 |
| 역추적 | `block_ids` | 이 청크를 생성한 블록 ID 목록. 고아 청크 정리·reconciliation 용 | 콜드패스 |

> **핫패스 필터 성능**: Milvus 2.4+에서 JSON 필드 내 키에 대한 스칼라 필터(`metadata["board_id"] IN [...]`, `metadata["is_suspended"] == false`)를 지원한다. JSON 필터는 전용 스칼라 필드 대비 느리나, `source_id` STL_SORT 인덱스로 먼저 좁힌 뒤 JSON 필터를 적용하는 2단계 전략으로 성능을 확보한다. 테넌트당 수만~수십만 청크 규모에서 `source_id` 필터 후 잔여 대상은 수십~수백 건이므로 JSON scan 비용이 무시 가능하다.

> **status 필드 불필요**: Milvus에는 발행(published)된 문서의 청크만 인덱싱된다. archived/삭제 시 Milvus에서 데이터를 제거하므로, Milvus에 존재하는 것 = 전부 published 상태이다. `is_suspended`만 필터로 유지한다 — 일시 정지는 임시 조치이므로 Milvus에서 삭제했다가 재임베딩하는 것보다 플래그 하나 바꾸는 것이 효율적이다.

**검색 시 필수 필터**: `metadata["is_suspended"] == false`

**권한 사전 필터**: aicm-service가 검색 요청 시 PermissionService에서 조회한 권한 정보를 retrieval-service 검색 API의 `filters` 파라미터로 전달한다. retrieval-service는 이를 Milvus JSON 필터 표현식으로 변환하여 검색 쿼리 실행 전에 적용한다:

- `metadata["board_id"] IN [접근 가능 게시판 ID]` — `filters.must.source_metadata.board_id`에서 변환
- `source_id NOT IN [제한 문서 ID]` — `filters.must_not.source_ids`에서 변환

retrieval-service는 aicm의 권한 모델을 알지 못하며, 범용 필터 파라미터를 Milvus 필터 표현식으로 매핑할 뿐이다. 상세 API 인터페이스는 [외부 서비스 연동 7.3절](../../06-external-integration.md), 의사결정 배경은 [ADR-003](../../../adr/003-rag-search-pre-filtering.md)을 참조한다.

### 범용 모델 매핑

retrieval-service 내부에서는 AICM 도메인 필드가 범용 필드로 매핑된다:

| AICM 도메인 필드 | Milvus 저장 위치 | 비고 |
|-----------------|-----------------|------|
| `document_id` | `source_id` (VARCHAR) | 핫패스 — STL_SORT 인덱스 |
| `board_id`, `is_suspended`, `tags` | `metadata` (JSON) | 핫패스 — JSON 필터 |
| `item_id` (그룹 ID) | `metadata` (JSON) | 콜드패스 — 재임베딩 대상 식별 |
| `block_ids` (원본 블록 ID 목록) | `metadata` (JSON) | 콜드패스 — 고아 정리·역추적 |

> **retrieval-service는 `metadata`를 해석하지 않는다.** 호출자가 `source_metadata`로 전달한 값을 Milvus `metadata` JSON 필드에 pass-through 저장하고, 검색 시 호출자가 `filters` 파라미터로 지정한 키를 JSON 필터로 변환할 뿐이다. `block_ids`, `item_id` 같은 키의 의미를 retrieval-service가 알 필요는 없다.

**재임베딩 시 대상 청크 조회**:

```python
# source_id STL_SORT → 문서 범위로 축소 후 JSON 필터
expr = 'source_id == "doc-123" and metadata["item_id"] in ["group-A", "group-C"]'
```

**고아 청크 reconciliation**:

```python
# 문서의 전체 청크를 조회하여 RDB Chunk 테이블과 대조
expr = 'source_id == "doc-123"'
# → 각 청크의 metadata["block_ids"]로 역추적 가능
```

---

## 2. 인덱스 설정

```
Index:
├── embedding      → HNSW (metric: COSINE, M: 16, efConstruction: 256)
└── source_id      → STL_SORT (스칼라 필터 가속)
```

| 설정 | 값 | 사유 |
|------|-----|------|
| 인덱스 타입 | HNSW | 검색 정확도 우선. IVF_FLAT 대비 recall 높고, 데이터 규모(테넌트당 수만~수십만 청크)에 적합 |
| 거리 메트릭 | COSINE | 임베딩 모델이 코사인 유사도 기준으로 학습됨 |
| M | 16 | 그래프 연결 수. 기본값. 메모리와 정확도 균형 |
| efConstruction | 256 | 인덱스 빌드 품질. 높을수록 정확하나 빌드 느림. 오프라인 인덱싱이므로 높게 설정 |
| 검색 시 ef | 128 | 검색 시 탐색 범위. 런타임에 조정 가능 |

> **`metadata` JSON 필드에는 별도 인덱스를 설정하지 않는다.** Milvus JSON 필드는 STL_SORT 인덱스를 지원하지 않으며, `source_id` STL_SORT로 먼저 좁힌 뒤 JSON 필터를 적용하는 2단계 전략으로 성능을 확보한다. 검색 핫패스에서 `source_id` 없이 `metadata["board_id"]`만으로 필터링하는 시나리오는 발생하지 않는다 — 권한 필터(`board_id IN [...]`)는 항상 Milvus ANN 검색의 스칼라 사전 필터로 적용되므로, HNSW 탐색 과정에서 후보를 걸러내는 방식으로 동작한다.

---

## 3. archived/삭제 시 처리

| 상황 | Milvus/ES 처리 | 복원 시 비용 |
|------|---|---|
| `is_suspended = true` | `metadata["is_suspended"]` 플래그 변경 | 즉시 (JSON 필드 업데이트) |
| `archived` | 데이터 삭제 | 재인덱싱 필요 (드문 케이스) |
| `deleted` | 데이터 삭제 | 재인덱싱 필요 |

---

**관련 문서**
- [retrieval-service 개요](./README.md) — 검색 모드, 파이프라인
- [ES aicm_chunks](./es.md)
- [aicm/rdb.md](../aicm/rdb.md) — RDB Chunk 엔티티 (RDB vs Milvus 역할 분리)
- [인증/인가 아키텍처](../../03-auth-architecture.md) — DocumentRestriction 권한 필터
