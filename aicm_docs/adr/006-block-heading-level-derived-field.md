# ADR-006: Block에 heading_level 파생 필드 도입

- **상태**: 승인됨
- **날짜**: 2026-03-24
- **의사결정자**: 개발팀
- **관련 문서**: [document-module.md](../03-module-design/document/data.md), [03-search.md](../01-requirements/flows/search-rag/03-search.md)

---

## 1. 컨텍스트

### 1.1 heading 정보가 content_raw 내부에만 존재

현재 Block 스키마에서 에디터 노드의 세부 타입(paragraph, heading, bulletList 등)은 `content_raw` JSONB 안에만 저장되어 있다. `block_type` 컬럼은 `text`, `image`, `table`, `file` 4가지 상위 분류만 제공하며, heading 블록도 `block_type = 'text'`로 분류된다.

```json
// block_type = 'text'인 heading 블록의 content_raw
{ "type": "heading", "attrs": { "level": 2 }, "content": [{ "type": "text", "text": "계좌 개설 절차" }] }

// block_type = 'text'인 paragraph 블록의 content_raw
{ "type": "paragraph", "content": [{ "type": "text", "text": "영업점 방문 시..." }] }
```

### 1.2 섹션 구조 탐색의 비효율

검색 스니펫(03-search.md 7.6절)에서 히트 블록이 속한 섹션의 헤딩 텍스트를 `section_title`로 부착해야 한다. 현재 스키마로는 이를 위해:

1. 히트 블록의 `document_id` + `sequence` 기준으로 이전 블록들을 조회
2. 각 블록의 `content_raw` JSONB를 파싱하여 `type === 'heading'`인 블록을 탐색
3. heading의 `attrs.level`을 추출하여 가장 가까운 상위 헤딩을 특정

이 과정이 **매 검색 히트마다** 발생하며, JSONB 파싱이 SQL 레벨에서 반복된다.

### 1.3 향후 확장 시에도 동일한 문제

- 섹션 단위 컨텍스트 확장: "같은 섹션 내 블록만 확장"하려면 섹션 경계(heading 위치 + level) 탐색 필요
- 계층적 breadcrumb 구성: LLM 컨텍스트에 `문서 > H1 > H2 > H3` 경로를 부여하려면 heading 계층 탐색 필요
- 문서 목차 조회: Block 테이블에서 heading 블록만 빠르게 조회해야 함

모든 경우에서 `content_raw` JSONB 파싱이 병목이 된다.

---

## 2. 결정

### 2.1 heading_level 파생 필드 추가

Block과 BlockSnapshot 양쪽에 `heading_level SMALLINT (nullable)` 컬럼을 추가한다.

| 값 | 의미 |
|---|---|
| `1`~`6` | heading 블록의 레벨 (H1~H6) |
| `NULL` | heading이 아닌 블록 (paragraph, list, image, table 등) |

### 2.2 파생 필드 추출 규칙

블록 저장 시 백엔드가 `content_raw`에서 자동 추출한다. 기존 `content_text`, `content_hash` 추출과 동일한 패턴이다.

```
content_raw (원본)
    ├──→ content_text   ← 순수 텍스트 추출        (기존)
    ├──→ content_hash   ← SHA-256 해시 계산       (기존)
    └──→ heading_level  ← content_raw.type === 'heading'이면
                           content_raw.attrs.level, 아니면 NULL (신규)
```

프론트엔드는 기존과 동일하게 `content_raw`만 전송하면 되며, 추가 작업이 없다.

### 2.3 인덱스 전략

heading 블록은 문서 전체 블록 중 소수이므로, 부분 인덱스(partial index)로 효율적으로 탐색한다.

```sql
-- Block: 섹션 헤딩 탐색용
CREATE INDEX idx_block_heading
  ON block (document_id, sequence)
  WHERE heading_level IS NOT NULL;

-- BlockSnapshot: 발행본 기준 섹션 헤딩 탐색용
CREATE INDEX idx_snapshot_heading
  ON block_snapshot (version_id, sequence)
  WHERE heading_level IS NOT NULL;
```

### 2.4 node_type 컬럼은 추가하지 않는다

Tiptap의 노드 타입(`paragraph`, `bulletList`, `orderedList`, `codeBlock` 등)을 별도 컬럼으로 미러링하지 않는다. 이유:

- **에디터 종속성 확산 방지**: Tiptap 고유 네이밍(`bulletList`, `codeBlock`)이 DB 스키마에 침투하면, 에디터 교체 시 스키마·쿼리·인덱싱 파이프라인 전체를 수정해야 한다.
- **백엔드 쿼리 수요 없음**: "불릿 리스트만 조회", "코드 블록만 필터"하는 백엔드 유스케이스가 없다. 이들은 표현(presentation) 차이이지 문서 구조를 정의하지 않는다.
- **heading만 특별**: heading은 유일하게 문서의 논리적 구조(섹션 계층)를 정의하는 노드이다. "heading level"은 에디터 불문 보편적 개념이므로 에디터 교체 시에도 추출 로직만 변경하면 된다.

---

## 3. 근거

### 3.1 대안 비교

| 대안 | 설명 | 채택 | 사유 |
|------|------|:---:|------|
| (A) `node_type` + `heading_level` 조합 | Tiptap 노드 타입 전체를 컬럼으로 미러링 | 기각 | 에디터 고유 네이밍이 스키마에 침투. 쿼리 수요 없는 타입까지 관리 부담 |
| **(B) `heading_level`만 추가** | heading이면 1~6, 아니면 NULL | **채택** | 에디터 중립적. 실제 쿼리 수요(섹션 탐색)에 정확히 대응. 최소 변경 |
| (C) 현행 유지 (`content_raw` 파싱) | JSONB에서 런타임 추출 | 기각 | 매 검색 히트마다 JSON 파싱 비용. SQL 인덱스 활용 불가 |

### 3.2 기존 파생 필드 패턴과의 일관성

Block 스키마는 이미 `content_raw`에서 파생한 컬럼들을 보유하고 있다.

| 파생 필드 | 원본 | 목적 |
|-----------|------|------|
| `content_text` | `content_raw` | 검색/임베딩용 순수 텍스트 |
| `content_hash` | `content_text` | 변경 감지, 재임베딩 판단 |
| **`heading_level`** (신규) | `content_raw` | 섹션 구조 쿼리 + 블록 그룹 경계 결정 (ADR-012) |

`heading_level`은 이 패턴의 자연스러운 확장이다.

### 3.3 YAGNI 원칙 적용

향후 다른 노드 타입(list, code, quote 등)에 대한 쿼리 수요가 발생하면, 같은 패턴으로 컬럼을 추가할 수 있다. 현 시점에서 수요가 확인된 heading_level만 도입하고, 나머지는 필요 시 추가한다.

---

## 4. 영향

### 4.1 문서 갱신

| 문서 | 변경 내용 |
|------|----------|
| [document-module.md](../03-module-design/document/data.md) | Block, BlockSnapshot 필드 테이블에 `heading_level` 추가, DDL에 컬럼 및 인덱스 추가, 설계 결정 섹션 추가, content_raw 예시에 heading 추가 |

### 4.2 코드 영향

| 영역 | 영향 |
|------|------|
| Block 엔티티 | `heading_level` 컬럼 추가 |
| BlockSnapshot 엔티티 | `heading_level` 컬럼 추가 |
| 블록 저장 로직 | `content_raw.type === 'heading'`일 때 `content_raw.attrs.level` 추출 → `heading_level`에 저장 |
| 블록 스냅샷 생성 | Block → BlockSnapshot 복사 시 `heading_level` 포함 |
| 섹션 헤딩 탐색 | `content_raw` JSONB 파싱 → `WHERE heading_level IS NOT NULL` SQL 쿼리로 단순화 |
| 블록 그룹 머지 알고리즘 | `heading_level IS NOT NULL`인 블록은 그룹 경계로 작용 (ADR-012) |
| 프론트엔드 | 변경 없음 — `content_raw`만 전송하는 기존 흐름 유지 |

### 4.3 변경하지 않는 영역

| 영역 | 사유 |
|------|------|
| [03-search.md](../01-requirements/flows/search-rag/03-search.md) | `section_title` 부착 규칙은 이미 정의됨. 이번 변경은 그 구현을 가능하게 하는 데이터 레이어 변경 |
| ES `aicm_blocks` 인덱스 | heading_level은 ES에 인덱싱할 필요 없음 — RDB 레벨 쿼리로 충분 |
| 임베딩/청킹 파이프라인 | heading_level은 임베딩 입력에 영향 없음 — 기존 `content_text`/`caption` 기반 유지 |
