> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `discussion` |
> | 검수 | `unreviewed` |
> | 대상 | RAG 담당자, retrieval-service 개발팀 |
> | 최종 수정 | 2026-04-10 |

# 블록 그룹핑 책임 이전 + 청킹 보조 메타데이터 검토

> 현재 aicm-service가 담당하는 블록 그룹핑(인접 블록 병합)을 retrieval-service로 이전하는 방안과, 이를 위한 구조 힌트 설계, RAG 청킹 품질 향상을 위한 추가 메타데이터를 검토한다.

---

## 1. 현재 설계

### 블록 그룹핑 → 청킹 흐름

```
aicm-service (EmbeddingProcessor)              retrieval-service
  │                                               │
  │  [1] 블록 로드 (DB)                            │
  │  [2] merge 알고리즘 실행 (ADR-012)              │
  │      - heading → 그룹 경계                      │
  │      - 짧은 text → 인접끼리 병합                 │
  │      - table/image/code → 단독 그룹             │
  │      - token 초과 → 그룹 분리                    │
  │  [3] 50블록 단위 배치 분할                       │
  │                                               │
  │── POST /ingest/embed (블록 배열) ──────────────▶│
  │                                               │── 청킹 (토큰 분할)
  │                                               │── 임베딩 생성
  │                                               │── Milvus + ES 저장
  │◀── { chunks: [{ chunk_id, block_ids }] } ────│
```

### 책임 분리 현황

| 책임 | 현재 소유자 | 필요 지식 |
|------|:----------:|----------|
| 블록 그룹핑 (인접 블록을 하나의 단위로 병합) | **aicm** | block_type, heading_level, token 계산, 에디터 구조 |
| 청킹 (그룹을 토큰 단위로 분할) | **retrieval** | max_tokens, overlap, 토크나이저 |
| 임베딩 생성 | **retrieval** | 임베딩 모델 |
| 블록 저장/관리 | **aicm** | DB 스키마, 에디터 |

### 현재 설계의 제약

1. **그룹핑과 청킹이 분리**되어 통합 최적화 불가 — "3개 블록을 합치면 280토큰인데, 그룹 1개 + 청크 2개로 할지, 그룹 2개 + 청크 2개로 할지" 같은 판단을 한 곳에서 할 수 없음
2. **50블록 배치 분할**이 기계적 — 그룹 경계와 무관하게 잘릴 수 있음
3. aicm에 **IR 도메인 로직**(그룹핑)이 존재 — retrieval 전략 변경 시 aicm도 수정 필요

---

## 2. 제안: 그룹핑 책임을 retrieval로 이전

### 핵심 아이디어

aicm은 블록의 **구조 정보(structure hints)**만 전달하고, retrieval이 그룹핑 + 청킹을 통합 수행.

```
aicm-service                                    retrieval-service
  │                                               │
  │  [1] 블록 로드 (DB)                            │
  │  [2] 구조 힌트 포함하여 전달                     │
  │      (그룹핑 로직 없음)                          │
  │                                               │
  │── POST /ingest/embed ─────────────────────────▶│
  │   (블록 + 구조 힌트)                             │── [NEW] 그룹핑
  │                                               │── 청킹
  │                                               │── 임베딩
  │◀── { chunks: [{ chunk_id, block_ids }] } ────│
```

### 변경 후 책임 분리

| 책임 | 변경 후 소유자 | 비고 |
|------|:------------:|------|
| 블록 그룹핑 | **retrieval** | 구조 힌트 기반으로 판단 |
| 청킹 | **retrieval** | 그룹핑과 통합 최적화 가능 |
| 구조 힌트 제공 | **aicm** | block_type → structural_role 매핑 (저장 시점) |
| 임베딩 생성 | **retrieval** | 변경 없음 |

---

## 3. 구조 힌트 설계 — 에디터 비종속

### 문제

retrieval이 그룹핑을 하려면 "heading이 뭔지", "table이 뭔지" 같은 에디터 도메인 지식이 필요한데, 이러면 retrieval이 aicm 에디터(Tiptap)에 종속된다.

### 해법: structural_role

retrieval은 block_type의 의미를 알 필요 없이, **구조적 역할** 3가지만 알면 그룹핑이 가능하다.

| structural_role | 의미 | 그룹핑 동작 | 현재 block_type 매핑 |
|-----------------|------|-----------|---------------------|
| `boundary` | 그룹 경계. 이 블록 전후로 그룹을 끊는다 | 새 그룹 시작 | heading |
| `mergeable` | 인접한 다른 mergeable과 병합 가능 | 합산 token 초과 전까지 병합 | text, list |
| `standalone` | 단독 그룹. 다른 블록과 병합 불가 | 항상 독립 그룹 | table, image, code, file |

**에디터 종속 없음**: retrieval은 `structural_role` 값만 보고 그룹핑을 결정한다. aicm이 에디터를 교체하거나 block_type을 추가해도, aicm 쪽에서 매핑만 업데이트하면 retrieval은 변경 불필요.

### 기존 Block 테이블과의 관계

현재 Block 테이블에 이미 있는 컬럼들로 structural_role을 유도할 수 있다:

```sql
SELECT
  id AS block_id,
  content_text,
  sequence,
  heading_level,                              -- 기존 컬럼
  embeddable,                                 -- 기존 컬럼
  CASE
    WHEN heading_level IS NOT NULL THEN 'boundary'
    WHEN block_type IN ('text', 'list')  THEN 'mergeable'
    ELSE 'standalone'
  END AS structural_role                      -- 기존 컬럼에서 유도 가능
FROM block
WHERE document_id = :docId AND embeddable = true
ORDER BY sequence;
```

**별도 컬럼 저장 vs 쿼리 시 계산**:

| 방식 | 장점 | 단점 |
|------|------|------|
| 컬럼 저장 (`structural_role` VARCHAR) | 조회 빠름, 인덱스 가능 | block_type 변경 시 동기화 필요 |
| 쿼리 시 CASE 계산 | 동기화 불필요, 항상 최신 | 매 쿼리마다 계산 (비용 미미) |

> **권장**: 쿼리 시 계산. block_type → structural_role 매핑은 단순 CASE문이고, 추가 컬럼의 동기화 리스크를 없앨 수 있다. 매핑 규칙이 변경되면 쿼리만 수정.

---

## 4. IngestBlock 인터페이스 변경안

### 현재

```typescript
interface IngestBlock {
  block_id: string;
  block_type: 'text' | 'image' | 'table' | 'code';
  content: string;
  block_metadata?: Record<string, any>;
}
```

### 변경안

```typescript
interface IngestBlock {
  block_id: string;
  content: string;
  sequence: number;

  // ── 구조 힌트 (에디터 비종속) ──
  structural_role: 'boundary' | 'mergeable' | 'standalone';
  hierarchy_level?: number;       // boundary일 때만. 1~6
  token_count: number;            // 사전 계산된 토큰 수

  // ── 청킹 보조 메타데이터 (§5 참조) ──
  section_path?: string[];        // 상위 heading 경로 (contextual prefix용)
  source_page?: number;           // 원본 페이지 번호 (citation용)
  language?: string;              // 블록 언어 (토크나이저 선택용)
  content_class?: string;         // 의미 분류 (§5.3 참조)
}
```

**주요 변경점**:
- `block_type` 제거 → `structural_role`로 대체 (retrieval이 에디터 타입을 알 필요 없음)
- `sequence` 추가 (인접 판별, 순서 보장)
- `token_count` 추가 (그룹핑 시 합산 계산용)
- `section_path` 추가 (contextual chunking prefix용)
- 청킹 보조 메타데이터 옵션 추가

---

## 5. 청킹 보조 메타데이터 — 추가 검토 항목

### 5.1 `token_count` (INT) — 필수

그룹핑/청킹의 기본 연산 재료. mergeable 블록들의 token_count를 합산하여 max_tokens 초과 여부를 판단.

| 항목 | 내용 |
|------|------|
| 계산 시점 | content_text 변경 시 (블록 저장/수정) |
| 계산 주체 | aicm-service BlockService |
| 토크나이저 | 임베딩 모델과 동일한 토크나이저 사용 권장. 불일치 시 오차 발생 |
| DB 저장 | Block 테이블에 컬럼 추가 (`token_count INT`) |

> **논의 필요**: 토크나이저를 aicm이 직접 실행할지(tiktoken 등 라이브러리), retrieval에 토큰 계산 API를 요청할지. aicm이 Python 토크나이저를 갖고 있지 않으므로, 근사 계산(문자 수 기반)으로 충분한지 검토.

### 5.2 `section_path` (TEXT[]) — 강력 권장

블록이 속한 섹션 계층 경로. Anthropic contextual retrieval 패턴의 핵심 재료.

```
문서: "계좌 개설 매뉴얼"
  heading(1): "필요 서류"
    heading(2): "개인 고객"
      text: "신분증 사본 1부를 지참하세요"

→ section_path = ["계좌 개설 매뉴얼", "필요 서류", "개인 고객"]
```

**retrieval이 contextual prefix로 사용**:
```
[계좌 개설 매뉴얼 > 필요 서류 > 개인 고객] 신분증 사본 1부를 지참하세요
```

| 항목 | 내용 |
|------|------|
| 계산 시점 | embed 요청 시 (sequence 순 순회하며 heading 스택 유지) |
| 계산 주체 | aicm 또는 retrieval (블록 목록을 sequence 순으로 받으면 누구든 계산 가능) |
| DB 저장 | **비권장** — heading 수정 시 하위 모든 블록의 경로 갱신 필요. embed 시점 계산이 안전 |

> **논의 필요**: section_path 계산을 aicm이 할지 retrieval이 할지. retrieval이 하면 aicm 의존 제거. aicm이 하면 retrieval이 더 generic하게 유지.

### 5.3 `content_class` (VARCHAR) — 선택

블록의 의미적 분류. 청킹 전략을 분류별로 다르게 적용할 수 있다.

| content_class | 설명 | 청킹 영향 |
|---------------|------|----------|
| `definition` | 용어/개념 정의 | 단독 청크 유지 (쪼개면 정의 불완전) |
| `procedure` | 절차/단계 | 단계 전체를 하나로 묶어야 의미 보존 |
| `warning` | 주의/경고/중요 | 단독 + 높은 가중치 |
| `reference` | 법조문/규정 인용 | 원문 보존, 쪼개기 불가 |
| `narrative` | 일반 서술 | 자유롭게 청킹 가능 |
| `qa` | Q&A 쌍 | Q+A를 반드시 한 청크에 |
| `data` | 수치/통계 데이터 | 표/그래프와 함께 묶어야 의미 있음 |

| 항목 | 내용 |
|------|------|
| 판별 주체 | (1) 파서가 LLM으로 판별, (2) 규칙 기반(heading 텍스트 키워드), (3) 사용자 수동 태깅 |
| 정확도 | 자동 판별은 best-effort. null 허용, null이면 기본 전략 적용 |
| DB 저장 | Block 테이블 컬럼 또는 metadata JSONB 내 필드 |

> **논의 필요**: content_class 자동 판별의 ROI. 규칙 기반(heading에 "절차", "주의사항", "FAQ" 포함 여부)만으로도 주요 케이스는 커버 가능. LLM 판별은 파싱 비용 증가.

### 5.4 `source_page` (INT) — 권장

원본 문서의 페이지 번호. RAG 답변의 citation/attribution에 사용.

| 항목 | 내용 |
|------|------|
| 현재 상태 | `metadata.sourcePageNumber`에 파서 생성 블록만 존재 |
| 제안 | Block 테이블 컬럼으로 승격 (`source_page INT, nullable`) |
| 용도 | RAG 답변에 "매뉴얼 p.23 참조" 표시, 페이지 범위 필터링 |

### 5.5 `language` (VARCHAR(5)) — 상황부

다국어 문서에서 블록 단위로 언어가 다를 수 있음.

| 항목 | 내용 |
|------|------|
| 영향 | 토크나이저 선택, 임베딩 모델 선택, 청크 크기 조절 |
| 판별 | 문자 유니코드 범위 기반 자동 감지 (fasttext, langdetect 등) |
| 단일 언어 환경 | 문서 레벨 기본값(예: 'ko')으로 충분. 블록 단위 불필요 |

> **논의 필요**: 대상 고객사가 다국어 문서를 다루는지. 한국어 단일 환경이면 우선순위 낮음.

---

## 6. 추가 메타데이터 우선순위 요약

| 우선순위 | 항목 | Block 테이블 변경 | 비고 |
|:--------:|------|:-----------------:|------|
| **필수** | `token_count` | +1 컬럼 (INT) | 그룹핑/청킹의 기본 재료 |
| **강력 권장** | `section_path` | 없음 (런타임 계산) | contextual chunking 핵심 |
| **권장** | `source_page` | +1 컬럼 (INT) — metadata에서 승격 | citation/attribution |
| **선택** | `content_class` | +1 컬럼 (VARCHAR) 또는 metadata 내 | 자동 판별 정확도 이슈 |
| **상황부** | `language` | +1 컬럼 (VARCHAR) 또는 문서 레벨 | 다국어 환경에서만 필요 |

**Block 테이블 최소 변경**: `token_count` 1개 컬럼 추가. 나머지는 기존 컬럼에서 유도 가능하거나 런타임 계산.

---

## 7. 배치 분할 전략 변경

### 현재: 기계적 50블록 분할

```
블록 200개 → 배치 4개 (50 + 50 + 50 + 50)
문제: 배치 경계에서 그룹이 잘릴 수 있음
```

### 변경안: boundary 기반 분할

structural_role을 활용하여, boundary(heading) 단위로 배치를 끊는다.

```
블록 200개, boundary 위치: [0, 45, 90, 150]
→ 배치 1: 블록 0~44   (섹션 1 완전체)
→ 배치 2: 블록 45~89  (섹션 2 완전체)
→ 배치 3: 블록 90~149 (섹션 3 완전체)
→ 배치 4: 블록 150~199 (섹션 4 완전체)
```

**장점**: retrieval이 배치 내에서 자유롭게 그룹핑해도 그룹이 배치 경계에서 잘리지 않음.

**제약**: 하나의 섹션이 50블록을 초과하면 해당 섹션 내에서 추가 분할 필요 (하위 heading 기준 또는 token 기준).

---

## 8. 열린 질문 (논의 필요)

### Q1. retrieval-service의 generic 원칙을 유지할 것인가?

현재 retrieval-service는 aicm 에디터 구조를 모르는 generic 서비스. structural_role 방식이면 generic은 유지되지만, **그룹핑 로직 자체**는 retrieval에 새로 구현해야 함. retrieval 팀의 수용 가능 범위는?

### Q2. token_count 계산의 토크나이저 일치

aicm(NestJS/TypeScript)에서 토큰 수를 계산하려면 임베딩 모델과 동일한 토크나이저가 필요. 선택지:
- (a) retrieval에 `/tokenize` API 추가 → 정확하지만 네트워크 호출
- (b) aicm에서 근사 계산 (문자 수 × 계수) → 부정확하지만 의존 없음
- (c) aicm에 tiktoken WASM 패키지 도입 → 정확하지만 의존 추가

### Q3. section_path 계산 주체

| 주체 | 장점 | 단점 |
|------|------|------|
| aicm | retrieval이 더 generic하게 유지 | aicm에 IR 관련 로직 잔존 |
| retrieval | aicm 의존 완전 제거 | retrieval이 블록 순서를 이해해야 함 |

→ retrieval이 계산하는 것이 자연스러움. boundary 블록(heading)의 content가 곧 section label이고, hierarchy_level로 깊이를 알 수 있으므로, retrieval이 sequence 순으로 순회하며 스택 기반으로 계산 가능.

### Q4. re-embed 시 그룹 재계산 범위

블록 하나 수정 시 인접 블록과의 그룹 경계가 바뀔 수 있음. 현재 `POST /ingest/re-embed`의 `modified_block_ids` 방식으로 충분한지, 전체 블록을 다시 보내야 하는지.

### Q5. content_class 자동 판별 도입 시점

v1에서 도입할지, 그룹핑 이전 완료 후 v2에서 도입할지. 규칙 기반(heading 키워드)만으로 시작하고 LLM 판별은 나중에 추가하는 점진적 접근이 현실적.

---

## 9. 제안 로드맵

| 단계 | 내용 | 변경 범위 |
|:----:|------|----------|
| **1단계** | Block에 `token_count` 컬럼 추가 + 저장 시 계산 | aicm DB 마이그레이션, BlockService |
| **1단계** | `source_page` 컬럼 승격 (metadata → 컬럼) | aicm DB 마이그레이션 |
| **2단계** | IngestBlock에 structural_role, hierarchy_level, token_count 추가 | retrieval API 스펙 변경 |
| **2단계** | retrieval에 그룹핑 로직 구현 (structural_role 기반) | retrieval-service |
| **2단계** | aicm의 merge 알고리즘 제거, 배치 분할을 boundary 기반으로 변경 | aicm EmbeddingProcessor |
| **3단계** | section_path 계산 (retrieval 내부) + contextual prefix 적용 | retrieval-service |
| **3단계** | content_class 규칙 기반 판별 도입 | aicm 파서/BlockService |

---

## 관련 문서

- [retrieval-service 연동](./retrieval-service-integration.md) — 현재 임베딩 파이프라인 연동 상세
- [retrieval-service API 스펙](./retrieval-service-api-spec.md) — 현재 IngestBlock/ChunkResult 인터페이스
- [블록 그룹 청킹 ADR](../adr/012-block-group-chunking.md) — Block↔Chunk M:N 관계 의사결정
- [청킹 전략](../01-requirements/flows/search-rag/02-chunking.md) — 청킹 파이프라인 전략
- [Document/Block 엔티티](../03-module-design/document/data.md) — Block 테이블 현재 스키마
- [서비스 간 통신 복원력 전략](../02-architecture/09-resilience-strategy.md) — retrieval-service 호출 에러 처리
