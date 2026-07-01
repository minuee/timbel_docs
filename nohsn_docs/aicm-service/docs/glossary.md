# AICM Service 용어 사전

> 문서 구조 관련 용어가 레이어마다 다르게 불리기 때문에 혼동이 생길 수 있다.
> 이 문서는 **동일 개념이 레이어별로 어떤 이름으로 사용되는지** 한눈에 정리한다.

---

## 용어 매핑 요약

| 개념 | 프론트엔드 / API JSON | DB 테이블 | DB 모델 클래스 | ID 접두사 |
|------|----------------------|-----------|---------------|----------|
| 문서 | document | `aicm_documents` | `DocumentsModel` | `document_` |
| 문서 버전(내용) | contents | `aicm_documents_contents` | `DocumentsContentModel` | `contents_` |
| 목차(제목 노드) | outline 노드 | `aicm_documents_index` | `DocumentIndexModel` | `idx_` |
| 단락(본문 내용) | block | `aicm_documents_sections` | `DocumentSectionsModel` | `sect_` |

---

## 상세 용어 설명

### Document (문서)

- **DB 테이블**: `aicm_documents`
- **설명**: 문서의 최상위 엔티티. 메타데이터만 보관하며 실제 내용은 갖지 않는다.
- **핵심 필드**:
  - `current_contents_id` — 최신 편집 버전을 가리키는 포인터
  - `effective_contents_id` — 승인된 유효 버전을 가리키는 포인터
  - `doc_type` — 문서 유형

### Content / Contents (문서 버전)

**주의**: "content"라는 단어가 두 가지 맥락에서 사용된다.

#### ① `aicm_documents_contents` (DB 테이블)

- **설명**: 문서의 **버전별 스냅샷**. 문서를 수정할 때마다 새 레코드가 생성된다.
- **핵심 필드**:
  - `contents` (ARRAY) — 최상위 index(목차) ID 목록 (outline의 루트 노드들)
  - `summary` — 요약
  - `version_name` — 버전명 (예: "1.0.0")
  - `category_id` — 분류

#### ② Section의 `content` (필드)

- **설명**: `aicm_documents_sections` 테이블의 `content` 컬럼. 단락 하나의 **실제 HTML 본문**을 담는다.
- 예: `"<p>이 문서는 <strong>중요한</strong> 내용을 담고 있습니다.</p>"`

---

### Outline vs Index (목차)

**같은 것의 다른 이름이다.** 레이어에 따라 부르는 이름이 다를 뿐이다.

#### Outline (API / 프론트엔드)

클라이언트가 주고받는 **JSON 트리 구조**를 말한다.

```json
{
  "outline": [
    {
      "id": "idx_1",
      "title": "1장. 소개",
      "blocks": ["sect_id_1", "sect_id_2"],
      "children": [
        {
          "title": "1.1 배경",
          "blocks": ["sect_id_3"],
          "children": []
        }
      ]
    }
  ]
}
```

| 필드 | 설명 |
|------|------|
| `title` | 목차 제목 |
| `blocks` | 이 목차에 속한 단락(section) ID 목록 |
| `children` | 하위 목차 (재귀) |

#### Index (DB)

- **DB 테이블**: `aicm_documents_index`
- **설명**: outline의 각 노드가 DB에 저장된 한 행(row)이다.

| outline 필드 | → | index 컬럼 |
|-------------|---|-----------|
| `title` | → | `name` |
| `blocks` | → | `sections` (단락 ID 배열) |
| `children` | → | `parent_id` / `root_id` (트리 관계) |

#### 변환 흐름

```
[프론트엔드]              [서비스]                    [DB]
outline JSON  ──→  _create_index_recursive()  ──→  aicm_documents_index
  title                                              name
  blocks                                             sections
  children                                           parent_id, root_id
```

---

### Block vs Section (단락)

**같은 것의 다른 이름이다.**

#### Block (API / 프론트엔드)

- outline 노드의 `blocks` 배열에 들어있는 **단락 ID** 또는 해당 단락 객체를 말한다.
- `blocks_map`에서 ID로 조회하면 실제 HTML 내용을 얻을 수 있다.

```json
{
  "blocks_map": [
    { "id": "sect_abc123", "content": "<p>단락 내용</p>", "hit_count": 0 }
  ]
}
```

#### Section (DB)

- **DB 테이블**: `aicm_documents_sections`
- **설명**: 단락 하나의 HTML 본문을 저장하는 DB 행이다.
- **핵심 필드**:
  - `content` — HTML 본문
  - `index_id` — 소속 목차 (nullable, DB상으로는 목차 없이 존재 가능)
  - `content_id` — 소속 문서 버전
  - `idx` — 목차 내 순서
  - `hit_count` — 검색 적중 횟수

#### 정리

| 맥락 | 이름 | 예시 |
|------|------|------|
| outline JSON 안에서 | `blocks` | `"blocks": ["sect_id_1", "sect_id_2"]` |
| API 응답에서 | `blocks_map` | `[{ "id": "sect_id_1", "content": "..." }]` |
| DB에서 | `section` | `aicm_documents_sections` 테이블의 한 행 |

---

### blocks_map (블록 맵)

- **사용 위치**: API 응답 JSON
- **설명**: 문서에 속한 모든 단락(section)의 내용을 **ID → 내용 매핑** 형태로 제공하는 배열이다.
- outline의 `blocks` 배열에는 ID만 있고, 실제 HTML 내용은 `blocks_map`에서 꺼낸다.

```json
{
  "contents": { "outline": [ ... ] },
  "blocks_map": [
    { "id": "sect_abc", "content": "<p>내용1</p>", "hit_count": 3 },
    { "id": "sect_def", "content": "<p>내용2</p>", "hit_count": 0 }
  ]
}
```

---

### Chunk (청크) — 계획 중

- **DB 테이블**: `aicm_documents_chunks` (계획)
- **설명**: 검색 최적화를 위해 문서 전체를 일정 크기로 재분할한 단위.
- section(단락)은 사용자가 정한 논리적 구분이지만, chunk는 **RAG 검색에 최적화된 크기**로 기계적으로 분할한 것이다.
- 원본 목차-단락 구조는 보존하면서, 별도로 청킹하여 검색 엔진에 전달한다.

| 구분 | Section (단락) | Chunk (청크) |
|------|---------------|-------------|
| 누가 나누는가 | 사용자 | 시스템 (자동) |
| 크기 | 가변 (사용자 입력에 따라) | 일정 (토큰/문자 수 기준) |
| 용도 | 편집/열람 | 검색/RAG |
| 저장 위치 | `aicm_documents_sections` | `aicm_documents_chunks` (계획) |

---

### 기타 용어

| 용어 | 설명 |
|------|------|
| `workspace_id` | 테넌트 구분 단위. 모든 데이터는 workspace에 속한다 |
| `doc_type` | 문서 유형 (예: manual, faq 등). `document_types` 테이블에 정의 |
| `category` | 문서 분류. 계층형 트리 구조 (`parent_id`로 자기참조) |
| `template` | 문서 생성 시 초기 outline 구조를 제공하는 틀. outline과 동일한 JSON 구조 |
| `version_name` | 문서 버전명. content가 새로 생성될 때마다 부여 |
| `current_contents_id` | 문서의 최신 편집 버전 포인터 |
| `effective_contents_id` | 문서의 승인된 유효 버전 포인터 |
| `hit_count` | 검색 적중 횟수 (section 단위 / 문서 단위 모두 존재) |
| `is_temporary` | 임시 저장 여부 |
| `approval` | 문서 승인 레코드 |
| `encrypt_str` / `decrypt_str` | DB ID를 암호화/복호화하는 유틸. API 응답의 ID는 항상 암호화된 상태 |

---

## 전체 데이터 흐름

```
[프론트엔드 에디터]
    │
    │  POST /docs/add_doc_with_files
    │  body: { name, contents: { outline: [...] }, blocks_map이 아닌 outline.blocks에 HTML 직접 포함 }
    │
    ▼
[API Layer]
    │
    ▼
[DB Service]
    ├── aicm_documents          ← Document 생성
    ├── aicm_documents_contents ← Content(버전) 생성, contents = [루트 index ID들]
    ├── aicm_documents_index    ← outline 각 노드 → index 행 생성 (트리)
    └── aicm_documents_sections ← outline.blocks 각 항목 → section 행 생성
    │
    ▼
[검색 엔진 연동]
    ├── outline DFS 순회
    ├── blocks_map에서 section 내용 조회
    ├── HTML → 평문 변환
    └── Elasticsearch 색인
```

---

## 자주 헷갈리는 것들

| 헷갈리는 점 | 정리 |
|------------|------|
| outline과 index의 차이? | 같은 것. outline = API JSON, index = DB 테이블 |
| block과 section의 차이? | 같은 것. block = API JSON, section = DB 테이블 |
| content가 너무 많다? | ① `documents_contents` = 문서 버전, ② `sections.content` = 단락 본문, ③ `contents` 컬럼 = 루트 index ID 배열 |
| blocks와 blocks_map? | `blocks` = outline 노드 안의 section ID 배열, `blocks_map` = API 응답에서 section 내용을 담은 배열 |
| section과 chunk? | section = 사용자가 나눈 단락, chunk = 시스템이 검색용으로 재분할한 단위 (계획 중) |
