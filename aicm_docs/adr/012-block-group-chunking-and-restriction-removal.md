# ADR-012: 블록 그룹 기반 청킹/인덱싱 전환 및 BlockRestriction 제거

- **상태**: 제안됨
- **날짜**: 2026-04-01
- **의사결정자**: 개발팀
- **관련 문서**: [02-chunking.md](../01-requirements/flows/search-rag/02-chunking.md), [03-search.md](../01-requirements/flows/search-rag/03-search.md), [aicm/es.md](../02-architecture/data/aicm/es.md), [aicm/rdb.md](../02-architecture/data/aicm/rdb.md), [FD-ACL-권한체계.md](../01-requirements/features/FD-ACL-권한체계.md), [ADR-003](./003-rag-search-pre-filtering.md), [ADR-006](./006-block-heading-level-derived-field.md)

---

## 1. 컨텍스트

### 1.1 현재 설계: Block = 청킹/인덱싱의 최소 단위

현재 청킹과 ES 인덱싱 모두 **블록 1건 = 최소 처리 단위**로 설계되어 있다.

| 영역 | 현재 설계 |
|------|----------|
| ES `aicm_blocks` | Block 1건 = ES doc 1건 |
| 벡터 임베딩 | Block:Chunk = 1:N (청크는 반드시 하나의 블록에 속함) |
| RAG 재임베딩 | 변경된 블록의 청크만 교체 |
| 검색 히트 하이라이트 | block_id로 정확한 블록 위치 특정 |

이 설계의 근거는 **BlockRestriction**(블록 단위 접근 제한)이다. `block_id`가 권한 경계와 일치해야 하므로, 인덱싱/청킹 단위도 블록으로 고정되었다.

### 1.2 문제: 블록 과세분화(over-fragmentation)

Tiptap 블록 에디터에서 작성자의 습관에 따라 블록 크기가 극단적으로 달라질 수 있다.

**목록 항목을 paragraph로 나열하는 경우:**

```
[P] "1. 아스피린 과민증 환자"        → 블록 1건, ~20토큰
[P] "2. 소화성 궤양 환자"            → 블록 1건, ~15토큰
[P] "3. 출혈성 뇌졸중 병력"          → 블록 1건, ~10토큰
[P] "4. 심한 신장 기능 저하"          → 블록 1건, ~20토큰
[P] "5. 임신 후기(30주 이상)"        → 블록 1건, ~20토큰
```

→ 블록 5건, ES doc 5건, 벡터 5개 — 각각 의미가 빈약한 짧은 단위.

**orderedList로 작성했다면:**

동일한 내용이 orderedList 블록 1건에 담겨 ES doc 1건, 벡터 1~2개로 처리된다.

### 1.3 과세분화가 초래하는 구체적 문제

| 문제 | 설명 | 심각도 |
|------|------|--------|
| **ES 인덱스 비대화** | 블록 수에 비례하여 ES doc 증가. 동일 내용을 목록 vs paragraph로 쓰면 ES doc 수 5배 차이 | 중간 |
| **BM25 길이 정규화 왜곡** | 짧은 블록이 많아지면 `avgdl` 감소 → 짧은 블록의 BM25 점수 과대 평가 → 의미 없는 짧은 블록이 상위 노출 | 높음 |
| **RAG 벡터 품질 저하** | 본문 10~20토큰짜리 블록은 Contextual Chunking(접두 포함)으로도 의미 신호가 빈약. 검색 노이즈 증가 | 높음 |
| **임베딩 자원 낭비** | 접두가 블록마다 반복되어 임베딩 입력 총량 증가. sLLM 환경에서 처리 시간 비례 증가 | 중간 |
| **Window Context 의존** | 짧은 블록이 히트되면 LLM 컨텍스트 구성을 위해 window 크기를 크게 잡아야 함 → 토큰 소비 증가 | 중간 |

### 1.4 BlockRestriction의 실제 필요성 재평가

BlockRestriction은 현재 설계에서 블록 단위 인덱싱/청킹의 핵심 근거이나, 재평가 결과:

- **BR-ACL-029**: 시스템 설정으로 on/off 가능하게 이미 설계됨 → 없어도 시스템이 동작해야 하는 구조
- **경쟁 제품 부재**: Confluence, Notion, SharePoint 어디에도 블록 단위 접근 제한은 없음
- **DocumentRestriction 대체 가능**: 문서 단위 접근 제한이 대부분의 보안 요건을 충족
- **아키텍처 복잡도**: BlockRestriction이 검색 파이프라인(ES 필터, RAG 사전 필터, 내보내기 처리, 감사 로그)에 전방위적 복잡도를 추가

---

## 2. 결정

### 2.1 BlockRestriction 제거

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) BlockRestriction 유지 | 세밀한 블록 단위 접근 제어 | 블록=인덱싱 단위 제약 유지, 과세분화 해결 불가, 아키텍처 복잡도 |
| **(b) BlockRestriction 제거 ✅** | 인덱싱/청킹 단위를 블록에서 해방, 아키텍처 단순화 | 블록 단위 접근 제한 불가 |

**결정: (b) BlockRestriction 제거**

- 근거: 이미 optional 설계(BR-ACL-029). DocumentRestriction이 실무 요건의 대부분을 충족. 블록 단위 권한은 경쟁 제품에도 없는 기능이며, 이를 위해 청킹/인덱싱 아키텍처 전체가 블록에 종속되는 비용이 과도하다.

### 2.2 블록 그룹 기반 청킹/인덱싱 도입

| 선택지 | 장점 | 단점 |
|--------|------|------|
| (a) 블록 단위 유지 + 병합 청킹만 추가 | 변경 범위 최소 | ES 비대화 미해결, M:1 매핑 복잡 |
| (b) 전체 텍스트 통으로 retriever에 전달 | 가장 단순 | 재임베딩 시 청크 경계 밀림(drift) → 오타 수정에 전체 재임베딩 위험 |
| **(c) 인접 짧은 블록을 그룹으로 병합하여 전달 ✅** | 과세분화 해결 + 경계 안정성 + ES 효율화 | 머지 알고리즘 추가 구현 필요 |

**결정: (c) 블록 그룹 기반 청킹/인덱싱**

- 근거: 블록 경계를 "고정 앵커"로 유지하여 청크 경계 밀림을 방지하면서, 짧은 블록을 병합하여 검색/RAG 품질을 안정화한다. retriever API 계약(`item_id + content → chunks`)은 변경 없이 aicm 내부에서 그룹 구성만 추가한다.

---

## 3. 상세 설계

### 3.1 블록 머지 알고리즘

발행 시 블록 목록을 순회하며 그룹을 생성한다. 그룹은 별도 엔티티가 아니라 **발행 핸들러 내 로컬 변수로 계산**된다.

```
블록 시퀀스 순회:
  ├── 헤딩 블록       → 버퍼 flush, 새 그룹 시작 (고정 앵커)
  ├── 텍스트 (짧음)   → 버퍼에 누적
  ├── 텍스트 (길음)   → 버퍼 flush, 단독 그룹
  ├── 테이블/이미지    → 버퍼 flush, 단독 아이템 (caption 기반, 기존 로직)
  ├── 코드            → 버퍼 flush, 단독 아이템
  └── 누적 합계 ≥ max_tokens → 버퍼 flush, 새 그룹 시작

  * embeddable=false 블록은 그룹에서 제외
  * 헤딩 블록은 그룹의 경계이자 Contextual Chunking의 섹션 컨텍스트
```

**왜 헤딩이 그룹 경계인가**: 헤딩은 작성자가 의도적으로 놓은 의미적 경계이다. 테이블·이미지·코드 블록도 그룹 경계로 작용하여, 이질적인 콘텐츠 타입이 하나의 그룹에 섞이지 않는다.

**왜 블록 경계가 앵커로 필요한가**: 전체 텍스트를 통으로 전달하면 오타 수정 시 청크 경계가 밀려(drift) 변경되지 않은 청크까지 해시가 달라져 전체 재임베딩이 발생한다. 블록 경계를 앵커로 유지하면 한 블록 내의 수정이 해당 그룹 내로 격리되어 다른 그룹의 청크에는 영향을 주지 않는다.

### 3.2 Chunk 엔티티 변경

```
현재:   Chunk.block_id       UUID FK NOT NULL  — 1블록에서 생성됨
변경:   Chunk.block_ids UUID[]           — N블록 병합에서 생성됨
```

aicm이 retriever에 그룹을 `item_id`로 전달하고, 반환된 청크에 `block_ids`를 직접 매핑한다. retriever는 블록이나 그룹의 존재를 모른다.

### 3.3 ES 인덱싱 단위 변경

```
현재:   Block 1건 = ES doc 1건 (aicm_blocks)
변경:   그룹 1건 = ES doc 1건 (aicm_blocks)
```

| 필드 변경 | 현재 | 변경 |
|-----------|------|------|
| `block_id` (keyword) | 단일 블록 ID | `group_id` (그룹 식별자) |
| `block_text` (text) | 단일 블록 텍스트 | `group_text` (병합된 텍스트) |
| `block_type` (keyword) | 단일 블록 타입 | `group_type` (text/table/image/code) |
| `sequence` (integer) | 블록 순번 | 그룹 내 첫 블록의 순번 |
| 나머지 (`document_id`, `board_id`, `tags`, `is_suspended`) | 변경 없음 | 변경 없음 |

collapse(document_id 그루핑) 및 inner_hits 패턴은 동일하게 유지한다.

### 3.4 재발행 시 재임베딩 흐름

```
1. BlockSnapshot 비교 → 변경된 블록 특정 (현재와 동일)
2. 전체 블록에 대해 머지 알고리즘 재실행 → 새 그룹 목록 생성
3. 각 그룹의 content_hash 계산 (그룹 텍스트의 SHA-256)
4. 기존 청크의 block_ids로 기존 그룹 식별 → 기존 content_hash 비교
5. content_hash가 달라진 그룹만 retriever에 재전달
6. 해당 그룹의 기존 청크 삭제 → 새 청크 저장
7. ES의 해당 그룹 doc 업데이트
```

**경계 안정성**: 블록 내부 수정(오타 등)은 해당 블록이 속한 그룹의 content_hash만 변경한다. 다른 그룹의 경계와 content_hash는 영향받지 않는다. 블록 추가/삭제로 그룹 구성이 바뀌는 경우에만 복수 그룹이 재처리된다.

### 3.5 retriever API 변경 사항

**변경 없음.** retriever의 API 계약은 동일하다:

```
요청: { items: [{ item_id, source_id, content, metadata }] }
응답: { results: [{ item_id, chunks: [{ chunk_id, content_text, vector }] }] }
```

aicm이 `content`에 병합된 텍스트를 넣을 뿐이다. retriever는 item의 출처를 알지 못한다. `group_id`/`group_type`은 Milvus/retriever ES에 저장하지 않는다 — 블록 그룹 역추적은 반환된 `chunk_id`로 RDB Chunk 테이블(`block_ids`)을 조회하여 수행한다.

### 3.6 검색 히트 하이라이트 변경

| 현재 | 변경 |
|------|------|
| ES 히트 → `block_id` → 에디터에서 해당 블록으로 스크롤 | ES 히트 → `group_text` 내 매칭 키워드 → 문서 내 텍스트 검색으로 위치 특정 |

정밀도가 블록 단위에서 텍스트 매칭 단위로 약간 낮아지나, ES의 `highlight` 기능이 매칭 부분을 반환하므로 실용적으로 충분하다.

---

## 4. 제거 대상

### 4.1 BlockRestriction 관련

| 항목 | 위치 |
|------|------|
| BlockRestriction 엔티티 | rdb.md, data.md |
| RestrictionEntry.restriction_type = 'block' | FD-ACL §5, rdb.md |
| 블록 단위 접근 제한 UC | UC-ADM-13 (블록 부분) |
| 블록 접근 제한 감사 로그 이벤트 | FD-AUD (restriction.enabled/disabled의 block 타입) |
| 블록 접근 제한 내보내기 처리 | FD-EXP §2.4 (BR-EXP-041의 블록 부분) |
| 블록 접근 제한 검색 필터 | 03-search.md, ADR-003 |
| acl.restriction.updated 이벤트의 block 분기 | FD-ACL §10 이벤트, auth/events.md |

### 4.2 Block:Chunk = 1:N 불변 원칙 관련

| 항목 | 위치 |
|------|------|
| "모든 Chunk는 정확히 하나의 Block에 속한다" 원칙 | 02-chunking.md §2.1 |
| Chunk.block_id FK | rdb.md, document/data.md |
| 블록 단위 ES 인덱싱 설명 | aicm/es.md §1 |
| 블록 단위 Milvus 메타 | retriever/milvus.md |

---

## 5. 영향 받는 문서

| 문서 | 변경 유형 | 내용 |
|------|----------|------|
| FD-ACL-권한체계.md | 수정 | §5에서 BlockRestriction 제거, DocumentRestriction만 유지 |
| 02-chunking.md | 대규모 수정 | §2 블록 타입별 전략에 그룹 머지 알고리즘 추가, Block:Chunk 원칙 → M:N으로 변경 |
| aicm/es.md | 수정 | `aicm_blocks` 인덱싱 단위를 블록→그룹으로 변경 |
| aicm/rdb.md | 수정 | Chunk 엔티티에서 block_id FK → block_ids, BlockRestriction 테이블 제거 |
| retriever/milvus.md | 수정 | `group_id`/`group_type` 미저장 — 그룹 역추적은 `chunk_id` → RDB Chunk(`block_ids`) 조회로 수행 |
| retriever/es.md | 수정 | `aicm_chunks`에서도 `group_id`/`group_type` 미저장 — Milvus와 동일 원칙 |
| 03-search.md | 수정 | 키워드 검색 쿼리 패턴 변경, 히트 하이라이트 방식 변경 |
| ADR-003 | 수정 | BlockRestriction 필터 제거 반영 |
| ADR-006 | 수정 | heading_level의 그룹 경계 앵커 역할 추가 |
| document/data.md | 수정 | Chunk 엔티티 필드 변경, Block 엔티티에서 restricted 관련 필드 정리 |
| document/rules.md | 수정 | BlockRestriction 관련 비즈니스 규칙 제거 |
| auth/events.md | 수정 | BlockRestriction 이벤트 제거 |
| FD-EXP-내보내기.md | 수정 | §2.4 블록 접근 제한 처리 제거 |
| FD-AUD-감사로그.md | 수정 | restriction 이벤트에서 block 타입 제거 |
| UC-ADM-13 | 수정 | 블록 단위 접근 제한 부분 제거 |

---

## 6. 선택지 비교 요약 (논의 과정에서 검토된 대안)

| 접근 | 과세분화 | 경계 안정성 | ES 비대화 | 아키텍처 복잡도 | 결과 |
|------|:---:|:---:|:---:|:---:|------|
| 현행 (블록 단위) | ✗ | ✓ | ✗ | 높음 (BlockRestriction) | 현행 문제 미해결 |
| 글자 수 강제 분할 | ✓ | ✗ | ✓ | 높음 (에디터 커스텀) | 편집 UX 파괴 |
| 전체 텍스트 통으로 전달 | ✓ | ✗ (경계 밀림) | ✓ | 낮음 | 재임베딩 비용 폭증 |
| 섹션(헤딩) 단위 고정 | ✓ | ✓ | ✓ | 중간 | 헤딩 없는 문서에서 실패 |
| **그룹 병합 (채택)** | **✓** | **✓** | **✓** | **중간** | **전 케이스 대응** |

---

## 7. 리스크 및 완화

| 리스크 | 심각도 | 완화 방안 |
|--------|--------|----------|
| 머지 알고리즘의 그룹 구성이 의미 경계를 벗어남 | 낮음 | 헤딩·비텍스트 블록이 자연스러운 경계 역할. 같은 타입(텍스트)만 병합 |
| block_ids JSON 배열 쿼리 성능 | 낮음 | document_id 인덱스로 먼저 필터 후 소수 청크 대상 탐색 |
| 기존 문서 대량 수정 필요 | 중간 | 설계 단계이므로 구현 전 변경. ADR 기반으로 순차 반영 |
| 히트 하이라이트 정밀도 저하 | 낮음 | ES highlight 기능 + 텍스트 매칭으로 실용적 수준 유지 |
