# 청킹 파이프라인 설계 결정 사항 (Q1~Q6)

> 상위 문서: [chunk-pipeline-plan.md](./chunk-pipeline-plan.md)

---

## Q1. Merge 시 목차 제목 포함 여부

목차-단락을 하나의 텍스트로 merge할 때 목차 제목(title)을 텍스트에 포함할지 여부.

### 옵션

#### (A) 목차 제목 포함 (마크다운 헤더 형식)

```
# 1장. 소개
소개 내용이 여기에 들어갑니다...

## 1.1 배경
배경에 대한 설명이 여기에 들어갑니다...
배경 추가 내용...

## 1.2 목적
목적에 대한 설명...
```

| 장점 | 단점 |
|------|------|
| 청크 안에 맥락(어느 섹션인지)이 남아서 RAG 검색 품질 향상 | 목차 제목이 청크 용량을 일부 차지 |
| LLM이 청크를 읽을 때 구조적 이해 가능 | depth가 깊으면 헤더가 반복되어 노이즈 |
| 독립적으로 청크 하나만 봐도 문맥 파악 가능 | |

#### (B) 단락 내용만 이어붙임

```
소개 내용이 여기에 들어갑니다...
배경에 대한 설명이 여기에 들어갑니다...
배경 추가 내용...
목적에 대한 설명...
```

| 장점 | 단점 |
|------|------|
| 구현이 단순 | 청크에서 "이 내용이 어느 섹션인지" 맥락 소실 |
| 청크 전체가 순수 내용 | LLM이 청크만으로 문서 구조 파악 불가 |
| | 유사한 내용이 다른 섹션에 있을 때 구분 불가 |

#### (C) 제목을 메타데이터로 분리

merge 텍스트에는 내용만 넣되, 텍스트 내 위치별로 해당하는 목차 경로 정보를 별도 매핑으로 보관.

```python
merged_text = "소개 내용... 배경 설명... 목적 설명..."
section_map = [
    {"offset": 0, "length": 50, "path": ["1장. 소개"]},
    {"offset": 50, "length": 80, "path": ["1장. 소개", "1.1 배경"]},
    ...
]
```

| 장점 | 단점 |
|------|------|
| 청킹 텍스트는 순수 내용 | 구현 복잡도 높음 |
| 청크 후 역매핑으로 제목 복원 가능 | offset 계산이 정교해야 함 |
| | 유지보수 부담 |

### ✅ 결정: **(A) 목차 제목 포함**

**이유**:

1. RAG 시나리오에서 청크는 결국 LLM에게 전달되는 컨텍스트이다. 제목이 포함되면 LLM이 "이 내용이 문서의 어떤 부분인지" 바로 파악할 수 있다.
2. 임베딩 벡터 생성 시에도 제목이 포함되면 의미적으로 더 정확한 벡터가 만들어진다. 예를 들어 "반품 절차"라는 제목 아래의 내용은, 제목 없이는 일반적인 절차 설명과 구분하기 어렵다.
3. 구현 복잡도가 (B)와 거의 동일하면서 검색 품질 개선 효과가 크다.
4. depth 기반 마크다운 헤더(`#`, `##`, `###`)를 사용하면 구조도 자연스럽게 표현된다.

**구현 예시**:

```python
def merge_outline_to_text(outline, blocks_map, depth=1):
    result = []
    for node in outline:
        title = node.get("title", "")
        if title:
            result.append(f"{'#' * depth} {title}")
        for block_id in node.get("blocks", []):
            block = blocks_map.get(block_id)
            if block:
                result.append(html_to_plain_text(block["content"]))
        for child in node.get("children", []):
            result.append(merge_outline_to_text([child], blocks_map, depth + 1))
    return "\n\n".join(result)
```

---

## Q2. 청크 데이터 저장 전략

청킹된 데이터를 RDB에 저장할 때 신규 테이블 vs 기존 테이블 확장.

### 옵션

#### (A) 신규 테이블 `document_chunks` 생성

```
aicm_documents_contents (1) ──→ (N) aicm_documents_chunks
                              ──→ (N) aicm_documents_index    (기존 유지)
                              ──→ (N) aicm_documents_sections  (기존 유지)
```

| 장점 | 단점 |
|------|------|
| 관심사 분리: 원본(section) vs 검색용(chunk) | 테이블 1개 추가 |
| 기존 코드에 영향 없음 | content_id 기준 조인 시 테이블 추가 |
| 스키마가 chunk 전용으로 최적화 가능 (prev/next, idx) | |
| chunk만 독립적으로 재생성 가능 (원본 무관) | |

#### (B) 기존 `document_sections` 테이블에 `chunk_type` 컬럼 추가

```sql
ALTER TABLE aicm_documents_sections 
ADD COLUMN chunk_type VARCHAR(20) DEFAULT 'original';
-- 'original': 기존 단락, 'chunk': 청킹된 데이터
ADD COLUMN prev_chunk_id VARCHAR(50);
ADD COLUMN next_chunk_id VARCHAR(50);
```

| 장점 | 단점 |
|------|------|
| 테이블 추가 없음 | 기존 sections 조회 쿼리에 `WHERE chunk_type = 'original'` 조건 필요 |
| 기존 인프라(인덱스, 관계) 재활용 | section과 chunk의 라이프사이클이 다름 → 관리 복잡 |
| | 의미가 다른 데이터가 한 테이블에 혼재 |
| | `index_id` FK가 chunk에는 불필요 → nullable 필드 증가 |

### ✅ 결정: **(A) 신규 테이블**

**이유**:

1. **목적이 다르다**: `sections`는 사용자가 편집하는 원본 단락이고, `chunks`는 검색을 위해 시스템이 자동 생성하는 파생 데이터이다. 라이프사이클도 다르다 (청킹 전략이 바뀌면 chunks만 재생성).
2. **기존 코드 안전**: 현재 sections를 조회하는 모든 쿼리(`get_sections_bulk`, `collect_all_sections` 등)에 조건을 추가할 필요가 없다.
3. **스키마 최적화**: chunk 전용 컬럼(`prev_chunk_id`, `next_chunk_id`, `idx`)을 깔끔하게 정의할 수 있다.
4. **재생성 용이**: 청킹 로직이 변경되면 chunks 테이블만 truncate 후 재생성하면 된다. sections는 건드리지 않는다.

**모델 설계**:

```python
class DocumentChunksModel(Base):
    __tablename__ = "aicm_documents_chunks"
    __table_args__ = {'schema': 'aicm'}

    id = Column(String(50), primary_key=True)       # chunk_{uuid}
    workspace_id = Column(String, nullable=False)
    content_id = Column(String(50), FK, nullable=False)
    idx = Column(Integer, nullable=False)            # 순서 (0-based)
    content = Column(Text, nullable=False)           # 청크 평문 텍스트
    prev_chunk_id = Column(String(50), nullable=True)
    next_chunk_id = Column(String(50), nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

---

## Q3. ChunkService 구현 방식

> 상세 설계: [chunk-service-design.md](./chunk-service-design.md)

### 기술 선택 배경

| | OpenAI file_search | LangChain Text Splitters |
|---|---|---|
| **유형** | 관리형 서비스 (SaaS) | 로컬 라이브러리 |
| **청크 접근** | 불가. OpenAI Vector Store 내부에 갇힘 | 자유. 리스트로 반환되어 RDB/ES 등에 활용 |
| **비용** | API 호출당 과금 | 무료 (로컬 실행) |
| **커스터마이징** | `max_chunk_size_tokens`, `chunk_overlap_tokens`만 조정 | separators, chunk_size, overlap 등 자유 |

OpenAI file_search는 청킹 결과를 반환하지 않아 자체 RDB 저장 및 search_engine_service 전달이 불가능하므로 **LangChain Text Splitters**를 사용한다.

### ✅ 결정: **LangChain `RecursiveCharacterTextSplitter`**

`langchain-text-splitters==0.2.2`와 `tiktoken==0.9.0`은 이미 `requirements.txt`에 포함되어 있어 추가 설치 불필요.

**선택 이유**:

1. 단락 → 줄 → 문장 → 단어 순으로 **재귀적 분할**하여 큰 의미 단위부터 보존 시도. 고정 크기 분할의 "문장 중간 잘림" 문제가 발생하지 않음.
2. `separators`에 한국어 종결 패턴(`다. `, `요. `, `까. `)을 추가하여 한국어 문서에 최적화 가능.
3. ABC 인터페이스로 감싸서, 추후 외부 서비스/토큰 기반/Semantic Chunking 등으로 구현체만 교체 가능.

**구현 구조**:

```python
from abc import ABC, abstractmethod
from typing import List
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass
class ChunkResult:
    idx: int        # 순서 (0-based)
    content: str    # 청크 텍스트


class ChunkService(ABC):
    @abstractmethod
    def chunk(self, text: str) -> List[ChunkResult]: ...


class LangChainChunkService(ChunkService):
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=[
                "\n\n",   # 단락 경계 (마크다운 헤더 사이)
                "\n",     # 줄바꿈
                "다. ",   # 한국어 평서문 종결
                "요. ",   # 한국어 존댓말 종결
                "까. ",   # 한국어 의문문 종결
                ". ",     # 영문 문장 종결
                " ",      # 단어
                "",       # 문자 (최후 수단)
            ],
            keep_separator=True,
        )

    def chunk(self, text: str) -> List[ChunkResult]:
        chunks = self.splitter.split_text(text)
        return [ChunkResult(idx=i, content=c) for i, c in enumerate(chunks)]
```

**기본 설정값**:

| 파라미터 | 기본값 | 근거 |
|----------|--------|------|
| `chunk_size` | 500자 | 한국어 500자 ≈ 약 200~250 토큰. RAG top_k=5 시 총 ~1,250 토큰 |
| `chunk_overlap` | 100자 | chunk_size의 20%. 문맥 연속성 유지와 중복 비용의 균형 |

**향후 확장**:

- 토큰 기반: `RecursiveCharacterTextSplitter.from_tiktoken_encoder()` 전환
- 파일 업로드: LangChain Document Loader(`PyPDFLoader` 등)를 앞단에 추가 (ChunkService 변경 불필요)
- 외부 서비스: `ExternalChunkService` 구현체 추가 후 DI로 교체

---

## Q4. 모든 쓰기 작업에 일괄 적용 여부

search_engine_service에 데이터를 전달하는 경로가 여러 곳에 존재한다.

### 현재 search_engine 전달 경로

| 메서드 | 파일 | 호출 시점 |
|--------|------|----------|
| `add_doc` | `services/document_service.py:98` | 문서 최초 생성 |
| `update_doc` | `services/document_service.py:267` | 문서 수정 (JSON) |
| `update_doc_form` | `services/document_service.py:377` | 문서 수정 (Form) |
| `approve_doc` | `services/document_service.py:511` | 문서 승인 |
| `sync_documents` | `services/document_service.py:160` | 수동 동기화 |
| `sync_from_db` | `services/document_service.py:616` | 전체 DB 동기화 |

### 옵션

#### (A) 모든 경로 일괄 적용

| 장점 | 단점 |
|------|------|
| 데이터 일관성 보장 | 변경 범위가 넓어 리스크 높음 |
| 어떤 경로로 저장해도 동일한 검색 결과 | 모든 경로를 동시에 테스트해야 함 |
| | 한 곳의 버그가 전체에 영향 |

#### (B) 점진적 적용 (add_doc → update → approve → sync 순)

| 장점 | 단점 |
|------|------|
| 리스크 분산, 단계별 검증 가능 | 과도기에 혼합 데이터 존재 |
| 문제 발생 시 영향 범위 제한 | 완전 적용까지 시간 소요 |
| 핵심 경로(add_doc)에서 먼저 검증 | |

### ✅ 결정: **(B) 점진적 적용**

**이유**:

1. 6개 경로를 한번에 바꾸면 문제 발생 시 원인 추적이 어렵다.
2. 청킹 로직을 **별도 함수로 추출**해두면, 각 경로에 적용하는 것은 단순 호출 추가이므로 점진 적용이 쉽다.
3. `add_doc`은 가장 기본적인 경로이므로 여기서 먼저 검증한다.

**적용 순서**:

```
Phase 1: add_doc                  ← 신규 문서 생성 시 청킹 적용, 검증
Phase 2: update_doc_form          ← 문서 수정 시 청킹 재적용
Phase 3: approve_doc              ← 승인 시 production 청크 반영
Phase 4: sync_documents, sync_from_db ← 배치/마이그레이션 경로
```

**핵심**: 청킹 파이프라인을 하나의 함수로 추출한다.

```python
def build_chunks_and_search_document(
    document: dict, 
    content_id: str, 
    workspace_id: str,
    chunk_service: ChunkService
) -> tuple[list[ChunkData], dict]:
    """
    document → merge → chunk → RDB 저장 데이터 + search_engine 전달용 dict 반환
    모든 경로에서 이 함수를 호출하면 됨
    """
    ...
```

---

## Q5. prev/next 청크 정보의 전달 위치

search_engine_service에 전달할 때 앞/뒤 청크 식별 정보를 어디에 넣을지.

### 현재 search_engine_service 전달 구조

```json
{
  "document": {
    "id": "doc_xxx",
    "meta": { "doc_type": "manual", ... },     ← 문서 수준 meta
    "contents": { "outline": [...] },
    "blocks_map": [
      { "id": "sect_xxx", "content": "...", "hit_count": 0 }  ← block별 필드
    ]
  }
}
```

search_engine_service 내부의 `es_action_transformer.py`가 이를 ES source로 변환할 때:

```python
source = {
    ...
    "section_id": bid,          # block.id
    "content": content_text,    # block.content → plaintext
    "meta": meta,               # document.meta (문서 수준)
    ...
}
```

### 옵션

#### (A) blocks_map 각 항목에 `meta` 필드 추가

```json
{
  "blocks_map": [
    {
      "id": "chunk_001",
      "content": "청크 내용...",
      "hit_count": 0,
      "meta": {
        "prev_chunk_id": null,
        "next_chunk_id": "chunk_002",
        "chunk_idx": 0
      }
    }
  ]
}
```

| 장점 | 단점 |
|------|------|
| 직관적: 각 청크가 자신의 메타를 가짐 | search_engine_service의 transformer가 block.meta를 ES source에 매핑하도록 수정 필요 |
| 문서 수준 meta와 분리되어 충돌 없음 | |
| 확장 용이 (나중에 chunk_meta에 더 많은 정보 추가 가능) | |

#### (B) 문서 수준 `meta`에 청크 매핑 정보 병합

```json
{
  "meta": {
    "doc_type": "manual",
    "chunk_links": {
      "chunk_001": { "prev": null, "next": "chunk_002" },
      "chunk_002": { "prev": "chunk_001", "next": "chunk_003" }
    }
  }
}
```

| 장점 | 단점 |
|------|------|
| 기존 blocks_map 구조 변경 없음 | 문서 수준 meta가 비대해짐 |
| | ES에서 특정 청크의 prev/next를 찾으려면 meta 전체를 파싱해야 함 |
| | 의미적으로 부적절 (문서 meta ≠ 청크 네비게이션) |

#### (C) `_source` 수준에 별도 필드로 전달

search_engine_service의 ES source에 직접 `prev_chunk_id`, `next_chunk_id` 필드를 추가.

```json
{
  "_source": {
    "section_id": "chunk_001",
    "content": "...",
    "prev_chunk_id": null,
    "next_chunk_id": "chunk_002",
    "chunk_idx": 0
  }
}
```

| 장점 | 단점 |
|------|------|
| ES에서 바로 접근 가능, 가장 간결 | search_engine_service의 transformer 수정 필수 |
| 쿼리/필터 시 직접 사용 가능 | aicm_service → search_engine_service 간 인터페이스 변경 |
| | blocks_map에서 어떻게 전달할지 약속 필요 |

### ✅ 결정: **(B) 문서 수준 `meta`에 청크 매핑 정보 병합**

**결정 이유**:

1. **밀버스 스키마 변경 회피**: (A)나 (C)처럼 새로운 필드를 추가하면 Milvus 벡터 엔진의 스키마를 전면 변경해야 한다. 이는 기존 데이터 재인덱싱, 다운타임 등 큰 리스크를 수반한다.
2. **기존 `meta` 필드 재활용**: 문서 수준 `meta`는 이미 ES/Milvus에 `object` 타입으로 매핑되어 있으므로, 내부에 `chunk_links` 키를 추가하는 것은 스키마 변경 없이 가능하다.
3. **search_engine_service 변경 최소화**: transformer에서 `meta`를 그대로 통과시키고 있으므로, aicm_service 측에서 `meta`에 넣기만 하면 ES/Milvus에 자동 저장된다.

**전달 형태**:

```json
{
  "meta": {
    "doc_type": "manual",
    "chunk_links": {
      "chunk_001": { "prev": null, "next": "chunk_002", "idx": 0 },
      "chunk_002": { "prev": "chunk_001", "next": "chunk_003", "idx": 1 },
      "chunk_003": { "prev": "chunk_002", "next": null, "idx": 2 }
    }
  }
}
```

**RAG 검색 시 활용 흐름**:

```
1. 쿼리 → top_k 청크 검색 (예: chunk_002 히트)
2. chunk_002의 meta.chunk_links에서 prev=chunk_001, next=chunk_003 확인
3. chunk_001, chunk_003 내용을 추가 조회하여 컨텍스트 확장
4. 확장된 컨텍스트를 LLM에 전달
```

**주의사항**:

- 청크 수가 많은 문서의 경우 `chunk_links` 맵이 커질 수 있으나, `meta`는 ES에서 object 타입이므로 실질적 크기 제한은 없다
- 각 청크 ES 문서의 `meta`에 전체 `chunk_links`가 중복 저장되지만, 이는 모든 청크 문서가 같은 문서 수준 `meta`를 공유하는 기존 구조의 연장선이다

---

## Q6. 기존 데이터 마이그레이션

이미 등록된 문서들에 대해 청킹을 소급 적용할지 여부.

### 옵션

#### (A) 즉시 전체 소급 적용

배포 직후 `sync_from_db` 류의 배치를 실행하여 모든 기존 문서를 청킹 → 재인덱싱.

| 장점 | 단점 |
|------|------|
| 모든 데이터가 즉시 새 형태로 통일 | 문서 수가 많으면 시간/리소스 소모 큼 |
| 검색 품질이 전체적으로 개선 | 배치 중 장애 시 복구 복잡 |
| | 기존 section_id 기반으로 동작하는 다른 시스템이 있으면 영향 |

#### (B) 점진적 적용 (신규 우선 + 배치 마이그레이션)

1. 신규/수정 문서는 즉시 청킹 적용
2. 기존 문서는 별도 배치 스크립트로 순차 마이그레이션
3. 마이그레이션 완료 전까지 기존 데이터는 현행 유지

| 장점 | 단점 |
|------|------|
| 리스크 분산 | 과도기에 검색 결과가 혼합 (일부는 section 단위, 일부는 chunk 단위) |
| 문제 발생 시 배치 중단 가능 | 마이그레이션 스크립트 별도 작성 필요 |
| 서비스 영향 최소화 | |

#### (C) 소급 미적용 (신규만)

기존 문서는 건드리지 않고, 앞으로 생성/수정되는 문서에만 적용.

| 장점 | 단점 |
|------|------|
| 가장 안전, 기존 데이터 무영향 | 기존 문서의 검색 품질은 개선 안 됨 |
| 구현 범위 최소 | 동일 시스템 내 두 가지 검색 단위 혼재 |
| | 기존 문서가 수정되면 그때 적용되긴 함 |

### ✅ 결정: **(B) 점진적 적용**

**이유**:

1. 즉시 전체 소급(A)은 리스크가 크다. 청킹 로직이 아직 초기 단계이므로 작은 범위에서 검증하는 게 안전하다.
2. 완전 미적용(C)은 기존 문서의 검색 품질을 개선할 기회를 놓친다.
3. 기존 `sync_from_db` 로직이 이미 "전체 문서 → search_engine 재전송" 기능을 갖추고 있으므로, 이를 확장하면 배치 마이그레이션 스크립트를 별도로 만들 필요가 적다.

**마이그레이션 전략**:

```
Day 1:  배포 → 신규 문서부터 청킹 적용
Day 2~: sync_from_db 배치 실행 (기존 문서 청킹 + 재인덱싱)
        - workspace 단위 또는 document 단위로 분할 실행
        - 실패 시 해당 문서만 재시도
완료:   모든 문서가 청킹 기반 인덱싱으로 전환
```

---

## 요약 매트릭스

| 질문 | 결정 | 핵심 이유 |
|------|------|----------|
| Q1. Merge 시 목차 제목 | **(A) 포함** | RAG 맥락 유지, 임베딩 품질 향상 |
| Q2. 저장 전략 | **(A) 신규 테이블** | 관심사 분리, 기존 코드 안전, 재생성 용이 |
| Q3. ChunkService 구현 | **LangChain `RecursiveCharacterTextSplitter`** | 재귀적 의미 단위 보존, 한국어 separator 지원, 추가 설치 불필요 |
| Q4. 적용 범위 | **(B) 점진적** | 리스크 분산, 단계별 검증 |
| Q5. meta 전달 위치 | **(B) 문서 수준 meta에 병합** | Milvus 스키마 변경 회피, 기존 meta 필드 재활용 |
| Q6. 마이그레이션 | **(B) 점진적** | 안전 + 기존 sync 로직 활용 |
