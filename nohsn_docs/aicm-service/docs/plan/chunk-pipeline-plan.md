# 문서 등록 파이프라인 변경 계획: 청킹 기반 검색 인덱싱

## 1. 배경 및 목표

### 1.1 현재 문제

기존 시스템은 사용자가 입력한 **목차-단락(outline-section)** 구조를 그대로 검색 단위로 사용한다.
즉, 하나의 block(=section)이 곧 하나의 검색 단위이다.

이 방식의 한계:

- 목차-단락 구조는 **사람이 정한 논리적 구분**이지, RAG 검색에 최적화된 크기가 아님
- 단락이 너무 길거나, 너무 짧거나, depth가 깊으면 청크 품질이 일정하지 않음
- 외부 청크 서비스가 이 구조화된 문서를 강제로 청킹하기 어려움

### 1.2 변경 목표

- 원본 목차-단락 구조는 **그대로 보존** (사용자 편집/열람용)
- 목차-단락을 **하나의 연속된 텍스트로 merge** 후 별도 청킹
- 청킹된 결과를 검색 엔진에 전달하여 **일관된 크기의 검색 단위** 확보
- 앞/뒤 청크 식별 정보를 meta에 포함하여 **RAG 컨텍스트 확장** 지원

---

## 2. AS-IS 분석

### 2.1 현재 데이터 흐름

```
사용자 입력 (outline + blocks_map)
    │
    ▼
┌─────────────────────────────────┐
│ DocumentService.add_doc()       │
│   → DB_DocumentService          │
│     .create_document()          │
│       → DocumentContentsRepo    │
│         .create_document_contents() │
│           → DocumentIndexService│
│             ._create_index_recursive() ──→ RDB: aicm_documents_index (트리)
│           → DocumentSectionsService    │
│             .create_sections_bulk() ──→ RDB: aicm_documents_sections
│                                     │
│   → SearchEngineClient          │
│     .insert_document(document)  │──→ search_engine_service (외부)
└─────────────────────────────────┘
```

### 2.2 현재 search_engine_service 전달 형태

`SearchEngineClient.insert_document()`에 전달되는 `document` dict:

```json
{
  "id": "doc_xxx",
  "name": "문서명",
  "version_name": "1.0.0",
  "contents": { "outline": [...] },
  "blocks_map": [
    { "id": "sect_xxx", "content": "<p>HTML 단락 내용</p>", "hit_count": 0 }
  ],
  ...
}
```

search_engine_service 측에서 `es_action_transformer.py`와 유사한 로직으로 outline을 DFS 순회하며 각 block을 하나의 ES 문서로 색인:

```json
{
  "_id": "sect_xxx",
  "_source": {
    "section_id": "sect_xxx",
    "title": "1장 > 1.1절",
    "content": "단락 평문 텍스트",
    ...
  }
}
```

### 2.3 현재 RDB 모델

| 테이블 | 역할 |
|--------|------|
| `aicm_documents` | 문서 메타 (current_contents_id) |
| `aicm_documents_contents` | 버전별 콘텐츠 (contents = root index ID 배열) |
| `aicm_documents_index` | 목차 트리 (parent_id, root_id, name, sections) |
| `aicm_documents_sections` | 단락 (content_id, index_id, idx, content) |

### 2.4 `contents` 입력 구조

```json
{
  "outline": [
    {
      "id": "idx_1",
      "title": "1장. 소개",
      "blocks": ["block_a"],
      "children": [
        {
          "id": "idx_1_1",
          "title": "1.1 배경",
          "blocks": ["block_b", "block_c"],
          "children": []
        }
      ]
    }
  ],
  "blocks_map": [
    { "id": "block_a", "content": "<p>소개 내용...</p>" },
    { "id": "block_b", "content": "<p>배경 1...</p>" },
    { "id": "block_c", "content": "<p>배경 2...</p>" }
  ]
}
```

---

## 3. TO-BE 설계

### 3.1 변경된 데이터 흐름

```
사용자 입력 (outline + blocks_map)
    │
    ▼
┌─────────────────────────────────────────┐
│ ① RDB 저장 (기존과 동일)                 │
│   → documents_index (트리 구조)          │
│   → documents_sections (원본 단락)       │
├─────────────────────────────────────────┤
│ ② Merge: outline + blocks_map           │
│   → 하나의 연속 텍스트로 변환              │
│   → depth 구분 없이 flat하게 합침          │
├─────────────────────────────────────────┤
│ ③ ChunkService (내부)                    │
│   → merged 텍스트를 청크 리스트로 분할      │
│   → 각 청크에 순서(idx) 부여               │
├─────────────────────────────────────────┤
│ ④ RDB 저장 (신규)                        │
│   → documents_chunks 테이블에 저장        │
├─────────────────────────────────────────┤
│ ⑤ Search Engine 전달                     │
│   → 청크 리스트를 기존 인터페이스 형태로     │
│     변환하여 insert_document 호출          │
│   → 각 청크 meta에 prev/next 청크 ID 포함  │
└─────────────────────────────────────────┘
```

### 3.2 신규 RDB 모델: `DocumentChunksModel`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | String(50) PK | `chunk_{uuid}` |
| `workspace_id` | String | 워크스페이스 ID |
| `content_id` | String(50) FK | documents_contents.id |
| `idx` | Integer | 청크 순서 (0-based) |
| `content` | Text | 청크 텍스트 (평문) |
| `prev_chunk_id` | String(50) | 이전 청크 ID (첫 번째면 NULL) |
| `next_chunk_id` | String(50) | 다음 청크 ID (마지막이면 NULL) |
| `created_at` | DateTime | 생성일시 |
| `updated_at` | DateTime | 수정일시 |

> **설계 의도**: 기존 `documents_sections`는 원본 단락 저장 용도로 유지하고, 청킹 결과는 별도 테이블에 저장하여 관심사를 분리한다.

### 3.3 Merge 로직 (`ContentMerger`)

outline 트리를 DFS 순회하면서 blocks_map의 content(HTML)를 순서대로 합침:

```
[title_depth_marker] 목차 제목
[plain_text] 단락 내용
[title_depth_marker] 하위 목차 제목
[plain_text] 하위 단락 내용
...
```

- HTML → 평문 변환은 기존 `html_to_plain_text()` 활용
- 목차 제목을 포함해야 검색 시 맥락 유지 가능 (**⚠️ 확인 필요**)

### 3.4 ChunkService (스텁 → 추후 본격 구현)

```python
class ChunkService:
    def chunk(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """텍스트를 chunk_size 단위로 분할, overlap만큼 겹침"""
        ...
```

- 초기에는 **고정 크기 + overlap 방식**의 간단한 구현
- 추후 NLP 기반, 의미 단위 청킹 등으로 교체 가능

### 3.5 Search Engine 전달 형태 변환

기존 인터페이스를 유지하기 위해 chunks를 기존 `document` dict 형태로 변환:

```json
{
  "id": "doc_xxx",
  "name": "문서명",
  "version_name": "1.0.0",
  "contents": {
    "outline": [
      {
        "id": "chunk_001",
        "title": "",
        "blocks": ["chunk_001"],
        "children": []
      },
      {
        "id": "chunk_002",
        "title": "",
        "blocks": ["chunk_002"],
        "children": []
      }
    ]
  },
  "blocks_map": [
    {
      "id": "chunk_001",
      "content": "청크 1 텍스트",
      "hit_count": 0,
      "meta": {
        "prev_chunk_id": null,
        "next_chunk_id": "chunk_002",
        "chunk_idx": 0
      }
    },
    {
      "id": "chunk_002",
      "content": "청크 2 텍스트",
      "hit_count": 0,
      "meta": {
        "prev_chunk_id": "chunk_001",
        "next_chunk_id": "chunk_003",
        "chunk_idx": 1
      }
    }
  ]
}
```

> **핵심**: search_engine_service는 기존처럼 outline을 DFS 순회하며 blocks_map에서 content를 꺼내 색인한다. 차이점은 각 block이 이제 "청크"이며, meta 필드에 앞/뒤 청크 정보가 포함된다는 것.

---

## 4. 구현 단계

### Step 1: DocumentChunksModel 생성

- `db/models/document/document_chunks.py` 신규 모델 생성
- `DocumentsContentModel`에 chunks 관계 추가
- DB 마이그레이션

### Step 2: ContentMerger 유틸리티 구현

- `utils/content_merger.py` 신규
- outline DFS 순회 → blocks_map content(HTML) 수집 → 평문 변환 → 연결
- 단위 테스트

### Step 3: ChunkService 스텁 구현

- `services/chunk_service.py` 신규
- 고정 크기 + overlap 방식의 기본 청킹
- 인터페이스를 확정하여 추후 교체 용이하게 설계

### Step 4: 청크 RDB 저장 로직

- `db/repositories/document/document_chunks_repository.py` 신규
- `db/services/document/document_chunks_service.py` 신규
- content_id별 청크 CRUD

### Step 5: Search Engine 전달 형태 변환

- `services/chunk_to_search_transformer.py` 신규
- chunks → 기존 document dict 형태로 변환
- prev/next chunk ID를 meta에 포함

### Step 6: DocumentService 파이프라인 수정

- `services/document_service.py`의 `add_doc`, `update_doc_form` 등 수정
- 기존 RDB 저장 후 → merge → chunk → chunk 저장 → 변환 → search_engine 전달
- `approve_doc`, `sync_documents` 등에도 동일 적용

### Step 7: 테스트 및 검증

- 단위 테스트: merger, chunk_service, transformer
- 통합 테스트: 전체 파이프라인 (등록 → 청킹 → 검색엔진 전달)
- 기존 기능 회귀 테스트

---

## 5. 영향 범위

### 5.1 수정 대상 파일

| 파일 | 변경 내용 |
|------|----------|
| `services/document_service.py` | add_doc, update_doc_form, approve_doc, sync_documents에 청킹 파이프라인 추가 |
| `db/models/document/documents_contents.py` | chunks 관계 추가 |
| `worker/es_index_task.py` | Celery 태스크에서도 청킹 파이프라인 적용 (필요시) |

### 5.2 신규 파일

| 파일 | 역할 |
|------|------|
| `db/models/document/document_chunks.py` | 청크 ORM 모델 |
| `db/repositories/document/document_chunks_repository.py` | 청크 저장소 |
| `db/services/document/document_chunks_service.py` | 청크 DB 서비스 |
| `utils/content_merger.py` | outline+blocks → 연속 텍스트 merge |
| `services/chunk_service.py` | 텍스트 → 청크 분할 |
| `services/chunk_to_search_transformer.py` | 청크 → search_engine 전달 형태 변환 |

### 5.3 영향 없는 영역

- 문서 조회/열람 (원본 outline-section 구조 그대로)
- 카테고리, 첨부파일, 댓글 등
- search_engine_service 자체 (인터페이스 유지)

---

## 6. 미결 사항 (⚠️ 확인 필요)

아래 사항들은 구현 전 확인이 필요합니다.

### Q1. Merge 시 목차 제목 포함 여부

목차-단락을 하나의 텍스트로 merge할 때 **목차 제목(title)**을 텍스트에 포함할지?

- **(A)** 포함: `"# 1장. 소개\n소개 내용...\n## 1.1 배경\n배경 내용..."` → 검색 시 맥락 유지에 유리
- **(B)** 미포함: 단락 텍스트만 이어붙임 → 단순하지만 청크에서 맥락 손실 가능

### Q2. 청크 데이터 저장 전략

- **(A)** 신규 테이블 `document_chunks` 생성 (본 계획의 기본안)
- **(B)** 기존 `document_sections` 테이블에 `chunk_type` 컬럼을 추가하여 원본/청크 구분

### Q3. ChunkService 초기 구현 수준

- **(A)** 고정 크기(예: 500자) + overlap(예: 100자) 방식의 간단한 스텁
- **(B)** 문장 단위 분할 (마침표/줄바꿈 기준으로 자연스러운 경계)
- **(C)** 아직 구현하지 않고 인터페이스만 정의 (chunkService 외부 연동 대기)

### Q4. update/approve 등 모든 쓰기 작업에 일괄 적용?

`add_doc` 외에도 `update_doc_form`, `approve_doc`, `sync_documents` 등에서 검색 엔진에 데이터를 전달하는 모든 경로에 동일하게 적용해야 하는지?

### Q5. search_engine_service의 meta 필드 상세

현재 search_engine_service에 전달할 때 `meta` 필드가 이미 존재하는데 (`document.meta`), 청크의 prev/next 정보를 어떻게 구분할지?

- **(A)** blocks_map 각 항목에 `meta` 필드 추가 (본 계획의 기본안)
- **(B)** source-level의 `meta` 필드에 병합
- **(C)** 별도 필드명 사용 (예: `chunk_meta`)

### Q6. 기존 데이터 마이그레이션

이미 등록된 문서들에 대해 청킹을 소급 적용해야 하는지?
(기존 `sync_from_db`나 `sync_documents` 로직 활용 가능)

---

## 7. 타임라인 (예상)

| 단계 | 예상 소요 |
|------|----------|
| Step 1: 모델 생성 | 0.5일 |
| Step 2: ContentMerger | 0.5일 |
| Step 3: ChunkService 스텁 | 0.5일 |
| Step 4: 청크 저장 로직 | 0.5일 |
| Step 5: 검색엔진 변환기 | 1일 |
| Step 6: 파이프라인 통합 | 1일 |
| Step 7: 테스트 | 1일 |
| **합계** | **~5일** |
