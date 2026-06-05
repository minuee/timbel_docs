> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `draft` |
> | 검수 | `unreviewed` |
> | 출처 | `docs/02-architecture/06-external-integration/6-1-parser-service-integration.md` L206–211 TODO |
> | 최종 수정 | 2026-04-07 |

# Parser Content 중간 포맷 (Intermediate Format) 설계

> parser-service가 반환하는 블록 `content`의 에디터-무관(editor-agnostic) 중간 포맷을 정의한다.
> aicm-service의 **BlockTransformer**가 이 포맷을 Tiptap JSON(`Block.content_raw`)으로 변환한다.

---

## 1. 배경 및 문제

### 현재 상황

parser-service의 `ParseBlockLine.content` 형식이 미확정 상태이다. 두 가지 극단적 선택지가 존재한다:

| 선택지 | 문제 |
|--------|------|
| parser-service가 **Tiptap JSON을 직접 생성** | 파서가 프론트엔드 에디터 스키마에 종속된다. Tiptap 버전 업그레이드·스키마 변경 시 Python 파서를 함께 수정해야 한다. 에디터 교체(예: Lexical) 시 파서 전면 재작업 |
| parser-service가 **순수 마크다운 문자열만 반환** | 블록 구조(테이블 행/열, 리스트 중첩, 이미지 메타)를 표현하기 어렵다. 마크다운 → Tiptap 변환 시 블록 레벨 파싱의 모호성이 크다 |

### 목표

두 극단 사이에서, **블록 구조는 JSON으로, 인라인 서식은 제한된 마크다운으로** 표현하는 하이브리드 중간 포맷을 정의한다.

```
parser-service                    aicm-service                    DB
  (Python)                         (TypeScript)

┌──────────┐   NDJSON 스트림   ┌──────────────────┐          ┌────────┐
│ 문서 파싱 │ ──────────────▶ │ BlockTransformer  │ ───────▶ │ Block  │
│          │   중간 포맷       │ 중간→Tiptap JSON  │          │        │
└──────────┘                  │ 중간→content_text  │          │content_│
                              │ text→content_hash  │          │  raw   │
                              └──────────────────┘          └────────┘
```

---

## 2. 설계 원칙

### 2.1 에디터 무관성 (Editor-Agnostic)

중간 포맷은 Tiptap, Lexical, Slate 등 특정 에디터의 스키마를 모르며, "**bold**", "표(행×열)", "순서 리스트" 같은 보편적 문서 개념만 사용한다. 에디터 종속 변환은 전적으로 aicm-service의 BlockTransformer가 담당한다.

### 2.2 파서 생산 편의성

parser-service는 LLM + OCR 조합을 사용한다. LLM 출력은 마크다운이 자연스러우므로, 인라인 서식에 마크다운을 그대로 사용하여 파서의 후가공을 최소화한다. 블록 구조만 JSON 봉투에 담으면 된다.

### 2.3 결정론적 변환 (Deterministic Conversion)

중간 포맷 → Tiptap JSON 변환은 **1:1 결정론적 매핑**이어야 한다. 같은 입력에 항상 같은 Tiptap JSON이 생성되어야 `content_hash` 기반 변경 감지가 유효하다.

### 2.4 점진적 확장성

v1에서는 5개 블록 타입(`text`, `heading`, `table`, `image`, `list`)만 지원한다. 새 블록 타입 추가 시 중간 포맷에 새 `ContentSchema`를 정의하고 BlockTransformer에 변환기를 추가하면 된다. 기존 타입의 스키마는 변경되지 않는다.

---

## 3. 중간 포맷 전체 구조

### 3.1 ParseBlockLine 수정

기존 `content: string | object`를 타입별로 구체화한다:

```typescript
interface ParseBlockLine {
  type: 'block';
  block_type: BlockType;
  content: IntermediateContent;     // ← 타입별 구체 스키마
  order: number;
  cursor: Record<string, unknown>;
  metadata?: BlockMetadata;
}

type BlockType = 'text' | 'heading' | 'table' | 'image' | 'list';

interface BlockMetadata {
  page_number?: number;
  heading_level?: number;           // heading 블록에만 존재
  original_type?: string;           // 파서 내부 세분화 타입
}
```

### 3.2 IntermediateContent 유니온 타입

```typescript
type IntermediateContent =
  | string            // text, heading → 제한된 마크다운 문자열
  | TableContent      // table → 구조화 JSON + 마크다운 셀
  | ListContent       // list → 구조화 JSON + 마크다운 아이템
  | ImageContent;     // image → 구조화 JSON (마크다운 없음)
```

**핵심 규칙**: `block_type`이 콘텐츠 형식을 결정한다.

| block_type | content 타입 | 설명 |
|-----------|-------------|------|
| `text` | `string` | 제한된 마크다운 (인라인 서식 포함) |
| `heading` | `string` | 제한된 마크다운 (인라인 서식 포함). 레벨은 `metadata.heading_level`에 별도 전달 |
| `table` | `TableContent` | JSON 구조 (행/열) + 셀 값은 마크다운 문자열 |
| `list` | `ListContent` | JSON 구조 (중첩) + 아이템 텍스트는 마크다운 문자열 |
| `image` | `ImageContent` | JSON 구조 (src, alt, 크기). 마크다운 없음 |

---

## 4. 인라인 서식 — 제한된 마크다운 서브셋 (Restricted Inline Markdown)

중간 포맷의 마크다운은 **인라인 서식 전용**이다. 블록 레벨 마크다운(`#`, `-`, `>`, `|`, `---` 등)은 사용하지 않는다 — 블록 구조는 JSON 봉투(`block_type`, `TableContent`, `ListContent`)가 이미 담당한다.

### 4.1 허용되는 인라인 마크다운

| 마크다운 구문 | 의미 | Tiptap 매핑 | 비고 |
|-------------|------|------------|------|
| `**text**` | 볼드 | `{ type: "bold" }` | `__text__`도 허용하나 파서는 `**`를 권장 |
| `*text*` | 이탤릭 | `{ type: "italic" }` | `_text_`도 허용하나 파서는 `*`를 권장 |
| `~~text~~` | 취소선 | `{ type: "strike" }` | GFM 확장 |
| `` `text` `` | 인라인 코드 | `{ type: "code" }` | |
| `[text](url)` | 링크 | `{ type: "link", attrs: { href: url } }` | |
| `==text==` | 하이라이트 | `{ type: "highlight" }` | markdown-it mark 플러그인 호환 |
| `<u>text</u>` | 밑줄 | `{ type: "underline" }` | 마크다운에 밑줄 구문이 없으므로 HTML 태그 사용 |
| `<sup>text</sup>` | 위첨자 | `{ type: "superscript" }` | |
| `<sub>text</sub>` | 아래첨자 | `{ type: "subscript" }` | |

### 4.2 허용되지 않는 마크다운 (블록 레벨)

중간 포맷 문자열 안에 다음이 포함되면 **BlockTransformer가 에러를 발생**시키지 않고, plain text로 취급한다.

| 금지 구문 | 이유 |
|----------|------|
| `# heading` | 블록 레벨 → `block_type: "heading"` + `metadata.heading_level`로 표현 |
| `- item`, `1. item` | 블록 레벨 → `block_type: "list"` + `ListContent`로 표현 |
| `> blockquote` | 블록 레벨 → v1 미지원 (text로 fallback) |
| `\| table \|` | 블록 레벨 → `block_type: "table"` + `TableContent`로 표현 |
| `![alt](url)` | 블록 레벨 → `block_type: "image"` + `ImageContent`로 표현 |
| `---` | 블록 레벨 → v1 미지원 |
| ` ``` ` (코드 블록) | 블록 레벨 → v1 미지원 (text로 fallback) |

### 4.3 이스케이핑

원본 텍스트에 마크다운 구문 문자(`*`, `~`, `` ` ``, `[`, `=`)가 포함되면, 파서는 `\` 프리픽스로 이스케이프한다.

```
원본:  가격은 **100만원**이며, 할인율은 5*10% 입니다.
중간:  가격은 **100만원**이며, 할인율은 5\*10% 입니다.
                                       ^^ 이스케이프
```

### 4.4 중첩 마크 (Overlapping Marks)

볼드+이탤릭 등 중첩은 마크다운 표준 방식을 따른다:

```
***볼드 이탤릭***
**볼드 안에 *이탤릭* 포함**
```

---

## 5. 블록 타입별 Content 스키마

### 5.1 text (단락)

| 항목 | 값 |
|------|-----|
| content 타입 | `string` |
| 형식 | 제한된 인라인 마크다운 |

```jsonc
// NDJSON 라인 예시
{
  "type": "block",
  "block_type": "text",
  "content": "영업점 방문 시 **본인 확인 서류**를 지참하여야 합니다. 자세한 내용은 [고객센터](https://cs.example.com)에서 확인하세요.",
  "order": 3,
  "cursor": { "page": 2 },
  "metadata": { "page_number": 2 }
}
```

**변환 결과** (Tiptap JSON → `Block.content_raw`):

```json
{
  "type": "paragraph",
  "content": [
    { "type": "text", "text": "영업점 방문 시 " },
    { "type": "text", "text": "본인 확인 서류", "marks": [{ "type": "bold" }] },
    { "type": "text", "text": "를 지참하여야 합니다. 자세한 내용은 " },
    {
      "type": "text",
      "text": "고객센터",
      "marks": [{ "type": "link", "attrs": { "href": "https://cs.example.com" } }]
    },
    { "type": "text", "text": "에서 확인하세요." }
  ]
}
```

**추출 결과** (`Block.content_text`):

```
영업점 방문 시 본인 확인 서류를 지참하여야 합니다. 자세한 내용은 고객센터에서 확인하세요.
```

---

### 5.2 heading (제목)

| 항목 | 값 |
|------|-----|
| content 타입 | `string` |
| 형식 | 제한된 인라인 마크다운 (제목 텍스트만, `#` 마커 없음) |
| 레벨 전달 | `metadata.heading_level` (1~6) |

```jsonc
{
  "type": "block",
  "block_type": "heading",
  "content": "계좌 개설 **절차**",
  "order": 0,
  "cursor": { "page": 1 },
  "metadata": { "page_number": 1, "heading_level": 2 }
}
```

> **heading_level을 content가 아닌 metadata에 두는 이유**:
> - `content`를 순수 텍스트(+인라인 서식)로 유지하여 text 블록과 동일한 파싱 경로를 재사용
> - `Block.heading_level` 파생 필드([ADR-006](../../adr/006-block-heading-level-derived-field.md))와 1:1 대응
> - `# 제목` 형식으로 넣으면 depth와 텍스트를 다시 분리해야 하는 불필요한 파싱 발생

---

### 5.3 table (표)

| 항목 | 값 |
|------|-----|
| content 타입 | `TableContent` (JSON object) |
| 셀 콘텐츠 형식 | `CellContent` — 인라인 마크다운 문자열, 중첩 표, 또는 중첩 리스트 |

```typescript
interface TableContent {
  has_header: boolean;              // 첫 행이 헤더인지
  rows: TableCell[][];              // 2D 배열 (행 × 열)
  caption?: string;                 // 표 캡션 (예: "표 1. 금리 조건표")
}

type TableCell = string | RichTableCell;

// ── 셀 내부에 들어갈 수 있는 콘텐츠 ──
type CellContent =
  | string                          // 인라인 마크다운 (가장 흔한 케이스)
  | TableContent                    // 중첩 표 (표 안의 표)
  | ListContent;                    // 셀 안의 목록

interface RichTableCell {
  content: CellContent;             // 셀 콘텐츠 (재귀 구조 지원)
  colspan?: number;                 // 기본 1
  rowspan?: number;                 // 기본 1
}
```

**설계 포인트 — `CellContent` 재귀 구조**:

1. **`string` 단축 표기**: 대부분의 표는 단순 셀이므로 `string`으로 충분하다 (셀마다 object 래핑 불필요)
2. **`RichTableCell`**: 병합 셀이거나 셀 내부에 중첩 구조가 필요할 때 사용한다
3. **`CellContent` 유니온**: 셀 안에 다시 표(`TableContent`)나 목록(`ListContent`)을 넣을 수 있다
4. BlockTransformer는 `typeof cell === 'string'`으로 단순 셀을 분기하고, `RichTableCell.content`의 타입으로 재귀 변환한다

> **왜 `RichTableCell.text`가 아니라 `content`인가**:
> 금융·정부 문서에서 표 안에 하위 표를 넣는 패턴(금리 조건표 내 세부 구간표, 수수료 표 내 채널별 상세표 등)이 빈번하다. `text: string`으로는 이런 구조를 표현할 수 없으므로, `content: CellContent`로 확장하여 중첩 표·중첩 리스트를 재귀적으로 표현한다. 마크다운은 표 안의 표를 원천적으로 표현할 수 없기 때문에, 이 설계가 JSON 중간 포맷의 핵심 차별점이다.

**예시 1 — 단순 표 + 캡션**

```
  [표 1] 고객 유형별 필요 서류

┌────────┬──────────────────────┬──────────────────────┐
│ 구분   │ 필요 서류             │ 비고                  │
├────────┼──────────────────────┼──────────────────────┤
│ 개인   │ 신분증, 인감증명서     │ 사본 불가             │
├────────┼──────────────────────┼──────────────────────┤
│ 법인   │ 사업자등록증, 법인인감  │ 세부안내 (링크)       │
└────────┴──────────────────────┴──────────────────────┘
```

```jsonc
{
  "type": "block",
  "block_type": "table",
  "content": {
    "has_header": true,
    "caption": "[표 1] 고객 유형별 필요 서류",
    "rows": [
      ["**구분**",    "**필요 서류**",           "**비고**"],
      ["개인",        "신분증, 인감증명서",       "사본 불가"],
      ["법인",        "사업자등록증, 법인인감",    "[세부안내](https://...)"]
    ]
  },
  "order": 5,
  "cursor": { "page": 3 },
  "metadata": { "page_number": 3 }
}
```

**예시 2 — 병합 셀 (colspan)**

```
┌─────────────────────────┬──────────┐
│ 계좌 종류 (2칸 병합)     │ 한도     │
├────────────┬────────────┼──────────┤
│ 보통예금   │ 입출금 자유  │ 제한 없음 │
├────────────┼────────────┼──────────┤
│ 정기예금   │ 만기 해지    │ 1억 원   │
└────────────┴────────────┴──────────┘
```

```jsonc
{
  "type": "block",
  "block_type": "table",
  "content": {
    "has_header": true,
    "rows": [
      [{ "content": "**계좌 종류**", "colspan": 2 }, "**한도**"],
      ["보통예금", "입출금 자유",                      "제한 없음"],
      ["정기예금", "만기 해지",                        "1억 원"]
    ]
  },
  "order": 8,
  "cursor": { "page": 4 },
  "metadata": { "page_number": 4 }
}
```

**예시 3 — 중첩 표 (표 안의 표, 2 depth)**

```
┌──────────┬──────────────────┐
│ 구분     │ 금리 조건         │
├──────────┼──────────────────┤
│          │ ┌──────┬───────┐ │
│ 보통예금 │ │ 일반 │ 우대  │ │
│          │ ├──────┼───────┤ │
│          │ │ 1.0% │ 1.5%  │ │
│          │ └──────┴───────┘ │
├──────────┼──────────────────┤
│ 정기예금 │ 연 2.0%          │
└──────────┴──────────────────┘
```

```jsonc
{
  "type": "block",
  "block_type": "table",
  "content": {
    "has_header": true,
    "rows": [
      ["**구분**", "**금리 조건**"],
      [
        "보통예금",
        {
          "content": {
            "has_header": true,
            "rows": [
              ["일반", "우대"],
              ["1.0%", "1.5%"]
            ]
          }
        }
      ],
      ["정기예금", "연 2.0%"]
    ]
  },
  "order": 9,
  "cursor": { "page": 5 },
  "metadata": { "page_number": 5 }
}
```

**예시 4 — 셀 안에 리스트**

```
┌────────┬───────────────────┐
│ 구분   │ 필요 서류          │
├────────┼───────────────────┤
│        │ • 신분증           │
│ 개인   │ • 인감증명서       │
│        │ • 주민등록초본     │
└────────┴───────────────────┘
```

```jsonc
{
  "type": "block",
  "block_type": "table",
  "content": {
    "has_header": true,
    "rows": [
      ["**구분**", "**필요 서류**"],
      [
        "개인",
        {
          "content": {
            "list_type": "unordered",
            "items": [
              { "text": "신분증" },
              { "text": "인감증명서" },
              { "text": "주민등록초본" }
            ]
          }
        }
      ]
    ]
  },
  "order": 10,
  "cursor": { "page": 5 },
  "metadata": { "page_number": 5 }
}
```

> **caption**: 원본 문서에서 표 위/아래에 "표 1. …", "[Table 3-1] …" 등의 캡션이 있으면 `caption` 필드에 담는다. 캡션이 없으면 필드를 생략한다. caption은 `Block.caption`으로 매핑되며, 임베딩 입력에 포함되어 검색 품질에 영향을 준다.

> **빈 셀**: 빈 문자열 `""`로 표현한다. `null`이나 누락은 허용하지 않는다.

> **병합 셀 뒤 빈 슬롯**: colspan/rowspan으로 병합된 영역의 나머지 슬롯은 **생략한다** (HTML `<td>` 생략과 동일). BlockTransformer가 Tiptap의 `tableCell`/`tableHeader` 노드로 변환할 때 병합 정보를 attrs에 반영한다.

> **중첩 depth 제한**: 중첩 표/리스트는 **2 depth**까지 허용한다 (표 → 표, 표 → 리스트). 3 depth 이상(표 → 표 → 표)은 파서가 평탄화하고 `metadata.original_type`에 원본 구조를 기록한다. Tiptap의 `table` 노드가 내부에 `table`을 허용하지 않으므로, BlockTransformer는 2 depth 중첩 표를 셀 내부의 별도 Tiptap 노드 그룹으로 변환한다.

---

### 5.4 list (목록)

| 항목 | 값 |
|------|-----|
| content 타입 | `ListContent` (JSON object) |
| 아이템 텍스트 형식 | 제한된 인라인 마크다운 |

```typescript
interface ListContent {
  list_type: 'ordered' | 'unordered';
  start?: number;                   // ordered에서 시작 번호 (기본 1)
  items: ListItem[];
}

interface ListItem {
  text: string;                     // 인라인 마크다운
  children?: ListContent;           // 중첩 리스트 (재귀)
}
```

```
1. 신분증 지참
   • 주민등록증
   • 운전면허증
   • 여권 (유효기간 내)
2. 창구 방문
3. 신청서 작성 및 전자서명
```

```jsonc
{
  "type": "block",
  "block_type": "list",
  "content": {
    "list_type": "ordered",
    "items": [
      {
        "text": "**신분증** 지참",
        "children": {
          "list_type": "unordered",
          "items": [
            { "text": "주민등록증" },
            { "text": "운전면허증" },
            { "text": "여권 (*유효기간 내*)" }
          ]
        }
      },
      { "text": "창구 방문" },
      { "text": "신청서 작성 및 [전자서명](https://sign.example.com)" }
    ]
  },
  "order": 6,
  "cursor": { "page": 3 },
  "metadata": { "page_number": 3 }
}
```

> **중첩 depth**: 파서는 원본 문서의 리스트 구조를 충실히 반영하되, 3 depth를 초과하는 중첩은 3 depth로 평탄화한다 (Tiptap 에디터 UX 한계). 평탄화 시 `metadata.original_type`에 원본 depth를 기록한다.

---

### 5.5 image (이미지)

| 항목 | 값 |
|------|-----|
| content 타입 | `ImageContent` (JSON object) |
| 마크다운 | 사용하지 않음 |

```typescript
interface ImageContent {
  src: string;                      // MinIO 경로 (parser-service가 업로드 완료한 경로)
  alt?: string;                     // 대체 텍스트 (OCR 추출 또는 LLM 생성)
  width?: number;                   // 원본 너비 (px)
  height?: number;                  // 원본 높이 (px)
}
```

```
┌─────────────────────────────┐
│                             │
│   [계좌 개설 신청서 양식]    │
│       (800 × 600 px)        │
│                             │
└─────────────────────────────┘
  alt: "계좌 개설 신청서 양식"
```

```jsonc
{
  "type": "block",
  "block_type": "image",
  "content": {
    "src": "documents/doc-123/images/2-001.png",
    "alt": "계좌 개설 신청서 양식",
    "width": 800,
    "height": 600
  },
  "order": 4,
  "cursor": { "page": 2 },
  "metadata": { "page_number": 2 }
}
```

> **alt → Block.caption 연결**: `ImageContent.alt`는 BlockTransformer에서 `Block.caption`으로 매핑된다. caption은 임베딩 입력으로 사용되므로, 파서가 OCR/LLM으로 생성한 이미지 설명이 검색 품질에 직접 영향을 미친다.

---

## 6. 전체 TypeScript 타입 정의

```typescript
// ─── 중간 포맷 (parser-service → aicm-service) ───

type IntermediateContent = string | TableContent | ListContent | ImageContent;

// ── 셀 내부 콘텐츠 (재귀 구조) ──
type CellContent =
  | string                          // 인라인 마크다운 (가장 흔한 케이스)
  | TableContent                    // 중첩 표 (표 안의 표)
  | ListContent;                    // 셀 안의 목록

// ── table ──
interface TableContent {
  has_header: boolean;
  rows: TableCell[][];
  caption?: string;                 // 표 캡션 (예: "표 1. 금리 조건표")
}
type TableCell = string | RichTableCell;
interface RichTableCell {
  content: CellContent;             // 재귀 구조 — 문자열, 중첩 표, 중첩 리스트
  colspan?: number;
  rowspan?: number;
}

// ── list ──
interface ListContent {
  list_type: 'ordered' | 'unordered';
  start?: number;
  items: ListItem[];
}
interface ListItem {
  text: string;
  children?: ListContent;
}

// ── image ──
interface ImageContent {
  src: string;
  alt?: string;
  width?: number;
  height?: number;
}

// ── ParseBlockLine (기존 인터페이스 수정) ──
interface ParseBlockLine {
  type: 'block';
  block_type: 'text' | 'heading' | 'table' | 'image' | 'list';
  content: IntermediateContent;
  order: number;
  cursor: Record<string, unknown>;
  metadata?: {
    page_number?: number;
    heading_level?: number;
    original_type?: string;
  };
}
```

---

## 7. BlockTransformer — 변환 계층

### 7.1 위치와 책임

```
parsing 큐 Worker (ParsingProcessor)
  │
  │  NDJSON block 라인 수신
  ▼
BlockTransformer.transform(parsedBlock: ParseBlockLine): TransformedBlock
  │
  │  (1) 중간 포맷 → Tiptap JSON  (content_raw)
  │  (2) 중간 포맷 → 순수 텍스트   (content_text)
  │  (3) content_text → SHA-256    (content_hash)
  │  (4) block_type 매핑           (DB block_type)
  │  (5) heading_level 추출        (heading만)
  │  (6) caption 추출              (image.alt, table은 향후)
  ▼
Block INSERT/UPSERT
```

BlockTransformer는 **aicm-service 내부**에 위치하며, parser-service와는 무관하다. parser-service가 교체되어도 BlockTransformer의 입력 스키마(이 문서)만 준수하면 된다.

### 7.2 변환 규칙

| block_type | content → content_raw | content → content_text | content → caption |
|-----------|----------------------|----------------------|------------------|
| `text` | 마크다운 파싱 → `{ type: "paragraph", content: [텍스트 노드…] }` | 마크다운 스트리핑 (마크 제거, 순수 텍스트) | `null` |
| `heading` | 마크다운 파싱 → `{ type: "heading", attrs: { level }, content: [텍스트 노드…] }` | 마크다운 스트리핑 | `null` |
| `table` | `TableContent` → `{ type: "table", content: [tableRow → tableCell…] }`. 셀의 `CellContent`에 따라 재귀 변환: `string` → 인라인 마크다운 파싱, `TableContent` → 중첩 table 노드, `ListContent` → 중첩 list 노드 | 셀 텍스트 연결 (탭/줄바꿈 구분). 중첩 표/리스트는 평탄화하여 텍스트 추출 | `TableContent.caption` (있으면 그대로 사용, 없으면 `null`) |
| `list` | `ListContent` → `{ type: "bulletList"|"orderedList", content: [listItem…] }`. 재귀 중첩 처리 | 아이템 텍스트 평탄화 (줄바꿈 구분) | `null` |
| `image` | `ImageContent` → `{ type: "image", attrs: { src, alt, width, height } }` | `null` | `ImageContent.alt` |

### 7.3 마크다운 파싱 라이브러리

BlockTransformer의 인라인 마크다운 파싱에는 **markdown-it** (또는 **remark/unified**)를 사용한다.

```
인라인 마크다운 문자열
  │
  │  markdown-it (inline rule만 사용)
  ▼
마크다운 AST (inline tokens)
  │
  │  custom renderer
  ▼
Tiptap text nodes + marks
```

**인라인 전용 파싱**: `md.parseInline(src)` API를 사용하여 블록 레벨 파싱을 완전히 건너뛴다. 이로써 문자열 안에 `#`이나 `-`가 있어도 블록으로 해석하지 않고 plain text로 유지한다.

### 7.4 미지원 block_type Fallback

parser-service가 v1 지원 타입 외의 `block_type`(예: `code_block`, `blockquote`)을 전송하면:

1. BlockTransformer는 해당 `content`를 **string으로 취급**한다 (object면 `JSON.stringify`)
2. `block_type = 'text'`로 매핑한다
3. `metadata.original_type`에 원래 block_type을 보존한다
4. 향후 해당 타입 지원 추가 시, `original_type` 기반으로 재변환 가능 (재파싱 불필요)

```typescript
// BlockTransformer.transform() 내부
if (!SUPPORTED_BLOCK_TYPES.has(block.block_type)) {
  return this.transformAsText({
    ...block,
    block_type: 'text',
    content: typeof block.content === 'string'
      ? block.content
      : JSON.stringify(block.content),
    metadata: {
      ...block.metadata,
      original_type: block.block_type,
    },
  });
}
```

### 7.5 에러 처리

| 시나리오 | BlockTransformer 동작 |
|---------|---------------------|
| 마크다운 파싱 실패 (잘못된 구문) | content를 plain text로 취급 (마크 없이 전체를 단일 텍스트 노드로) |
| `TableContent.rows`가 비어있음 | 빈 테이블 노드 생성 + 경고 로그 |
| `ImageContent.src` 누락 | Block 생성 스킵 + 에러 로그 + `done.warnings`에 포함 |
| `ListContent.items`가 비어있음 | 빈 리스트 노드 생성 + 경고 로그 |
| 열 수 불일치 (행마다 셀 수가 다름) | 부족한 셀은 `""`로 채움 + 경고 로그 |
| 중첩 depth 초과 (표→표→표 3 depth 이상) | 가장 안쪽 구조를 plain text로 평탄화 + 경고 로그 |
| `RichTableCell.content`가 예상 외 타입 | `JSON.stringify`하여 string으로 fallback + 경고 로그 |

---

## 8. 전체 NDJSON 스트림 예시

실제 PDF(5페이지, 제목+텍스트+표+이미지+목록)의 파싱 결과:

**원본 문서 레이아웃**:

```
─── p.1 ────────────────────────────────────
  계좌 개설 안내                    ← heading (h1)

  본 문서는 개인 고객의 계좌 개설    ← text
  절차를 안내합니다. ...

─── p.2 ────────────────────────────────────
  필요 서류                         ← heading (h2)

  ┌────────┬──────────────────┬──────────┐
  │ 구분   │ 서류              │ 비고     │  ← table
  ├────────┼──────────────────┼──────────┤
  │ 개인   │ 신분증, 인감증명서 │ 사본 불가 │
  ├────────┼──────────────────┼──────────┤
  │ 법인   │ 사업자등록증, ...  │          │
  └────────┴──────────────────┴──────────┘

─── p.3 ────────────────────────────────────
  ┌─────────────────────────────┐
  │                             │
  │   [신청서 양식 예시]         │   ← image
  │       (800 × 1100 px)       │
  │                             │
  └─────────────────────────────┘

─── p.4 ────────────────────────────────────
  개설 절차                         ← heading (h2)

  1. 신분증 지참                    ← list (ordered)
     • 주민등록증                      (중첩 unordered)
     • 운전면허증
  2. 창구 방문 후 번호표 수령
  3. 신청서 작성 및 서명
  4. 계좌 개설 완료 (즉시 사용 가능)

─── p.5 ────────────────────────────────────
  문의 사항은 고객센터               ← text
  1599-1234로 연락하시기 바랍니다.
```

**NDJSON 스트림 출력**:

```
{"type":"metadata","page_count":5}
{"type":"block","block_type":"heading","content":"계좌 개설 안내","order":0,"cursor":{"page":1},"metadata":{"page_number":1,"heading_level":1}}
{"type":"block","block_type":"text","content":"본 문서는 **개인 고객**의 계좌 개설 절차를 안내합니다. 관련 규정은 [금융위원회 고시](https://fsc.go.kr)를 참조하십시오.","order":1,"cursor":{"page":1},"metadata":{"page_number":1}}
{"type":"block","block_type":"heading","content":"필요 서류","order":2,"cursor":{"page":2},"metadata":{"page_number":2,"heading_level":2}}
{"type":"block","block_type":"table","content":{"has_header":true,"rows":[["**구분**","**서류**","**비고**"],["개인","신분증, 인감증명서","사본 불가"],["법인","사업자등록증, 법인인감",""]]},"order":3,"cursor":{"page":2},"metadata":{"page_number":2}}
{"type":"heartbeat","status":"processing","detail":"page 3, image extraction"}
{"type":"block","block_type":"image","content":{"src":"documents/doc-001/images/4-001.png","alt":"신청서 양식 예시","width":800,"height":1100},"order":4,"cursor":{"page":3},"metadata":{"page_number":3}}
{"type":"block","block_type":"heading","content":"개설 절차","order":5,"cursor":{"page":4},"metadata":{"page_number":4,"heading_level":2}}
{"type":"block","block_type":"list","content":{"list_type":"ordered","items":[{"text":"**신분증** 지참","children":{"list_type":"unordered","items":[{"text":"주민등록증"},{"text":"운전면허증"}]}},{"text":"창구 방문 후 번호표 수령"},{"text":"신청서 작성 및 서명"},{"text":"계좌 개설 완료 (*즉시 사용 가능*)"}]},"order":6,"cursor":{"page":4},"metadata":{"page_number":4}}
{"type":"block","block_type":"text","content":"문의 사항은 고객센터 ~~1588-0000~~ `1599-1234`로 연락하시기 바랍니다.","order":7,"cursor":{"page":5},"metadata":{"page_number":5}}
{"type":"done","parsing_duration_ms":12500,"warnings":[]}
```

---

## 9. 대안 비교 (Alternatives Considered)

### 9.1 Tiptap JSON 직접 생성 (기각)

```jsonc
// parser-service가 이걸 만들어야 함
{
  "type": "paragraph",
  "content": [
    { "type": "text", "text": "볼드 ", "marks": [{ "type": "bold" }] },
    { "type": "text", "text": "일반" }
  ]
}
```

| 기준 | 평가 |
|------|------|
| 에디터 무관성 | **X** — Tiptap 스키마 직접 의존 |
| 파서 생산 편의성 | **X** — Python에서 ProseMirror 노드 트리를 정확히 구성해야 함 |
| 에디터 교체 시 | **X** — parser-service 전면 수정 |
| 변환 비용 | **O** — aicm-service에서 변환 불필요 |

**기각 이유**: 관심사 분리 위반. 파서가 프론트엔드 에디터 스키마에 종속되면, Tiptap 스키마 변경(마크 추가, 노드 구조 변경)마다 Python 파서를 함께 수정해야 한다.

### 9.2 순수 마크다운 (기각)

```markdown
## 계좌 개설 안내

본 문서는 **개인 고객**의 계좌 개설 절차를 안내합니다.

| 구분 | 서류 | 비고 |
|------|------|------|
| 개인 | 신분증 | 사본 불가 |
```

| 기준 | 평가 |
|------|------|
| 에디터 무관성 | **O** — 마크다운은 보편적 |
| 파서 생산 편의성 | **O** — LLM 출력 그대로 |
| 블록 구조 표현 | **X** — 마크다운 테이블은 colspan/rowspan 미지원, **중첩 표(표 안의 표) 원천 불가**, 셀 안 리스트 미지원, 이미지 메타 부족 |
| 결정론적 변환 | **X** — 마크다운 → 블록 분리가 모호 (빈 줄 기준? heading 기준?) |
| 블록 커서 매핑 | **X** — 순수 문자열에 블록별 커서를 부착할 수 없음 |

**기각 이유**: 블록 단위 NDJSON 스트리밍과 커서 기반 재개 메커니즘은 "블록 하나 = NDJSON 한 줄"을 전제한다. 순수 마크다운은 블록 경계가 불명확하여 이 전제를 충족하지 못한다.

### 9.3 텍스트 런 배열 — Text Runs with Marks (보류)

```jsonc
{
  "content": [
    { "text": "볼드 ", "marks": ["bold"] },
    { "text": "일반" },
    { "text": "링크", "marks": [{ "type": "link", "href": "https://..." }] }
  ]
}
```

| 기준 | 평가 |
|------|------|
| 에디터 무관성 | **O** — 보편적 텍스트 런 모델 |
| 파서 생산 편의성 | **△** — LLM 마크다운 출력을 런으로 분해해야 함 (추가 파싱 필요) |
| 변환 결정론성 | **O** — 1:1 매핑 |
| 이스케이핑 문제 | **O** — 없음 (plain text + 마크 메타 분리) |

**보류 이유**: 기술적으로 우수하나, parser-service가 LLM 출력을 런 배열로 변환하는 비용이 크다. LLM은 마크다운을 출력하므로 파서 내부에서 `마크다운 → 런 배열` 변환을 해야 하는데, 이 변환을 TypeScript 쪽(BlockTransformer)에서 하든 Python 쪽(parser-service)에서 하든 한 번은 필요하다. **변환 책임을 aicm-service에 집중**시키는 것이 유지보수에 유리하다.

> **향후 전환 가능성**: 인라인 마크다운의 이스케이핑 문제가 실무에서 빈번하게 발생하면, 텍스트 런 배열로 전환을 검토한다. 이 경우 parser-service만 변경하면 되며, BlockTransformer는 런 배열을 직접 Tiptap 마크로 매핑하는 더 단순한 로직으로 교체된다.

---

## 10. 블록 타입 확장 로드맵

| 단계 | block_type | content 형식 | 비고 |
|------|-----------|-------------|------|
| v1 (현재) | `text`, `heading`, `table`, `image`, `list` | 이 문서의 스키마 | 1차 구현 범위 |
| v1.1 | `code_block` | `{ language: string, code: string }` | 기술 문서 파싱 시 |
| v1.2 | `blockquote` | `string` (인라인 마크다운) | 인용 블록 |
| v2 | `callout`, `divider` | 각 타입별 정의 | 에디터 고급 기능 연동 |

미지원 타입은 §7.4의 fallback으로 `text`로 매핑되므로, 파서가 새 타입을 먼저 구현해도 aicm-service가 에러 없이 처리된다.

---

## 11. 검증 체크리스트

### parser-service 측 (Python)

- [ ] `text`, `heading` 블록의 `content`는 반드시 `string` 타입
- [ ] `table` 블록의 `content`는 반드시 `{ has_header, rows }` 구조. 원본에 캡션이 있으면 `caption` 포함
- [ ] `list` 블록의 `content`는 반드시 `{ list_type, items }` 구조
- [ ] `image` 블록의 `content`는 반드시 `{ src }` 구조 (`src` 필수)
- [ ] 인라인 마크다운에 블록 레벨 구문(`#`, `-`, `|`, `>`) 미포함
- [ ] 마크다운 구문 문자가 서식이 아닌 원본 텍스트이면 `\`로 이스케이프
- [ ] 테이블의 모든 행은 동일한 열 수 (부족하면 `""` 패딩)
- [ ] `RichTableCell.content`가 `string | TableContent | ListContent` 중 하나
- [ ] 중첩 표/리스트는 2 depth 이하 (표→표→표 금지, 초과 시 평탄화)
- [ ] 리스트 중첩은 3 depth 이하

### aicm-service 측 (TypeScript — BlockTransformer)

- [ ] `md.parseInline()` 전용 사용 (블록 레벨 파싱 차단)
- [ ] 미지원 `block_type` → `text` fallback + `original_type` 보존
- [ ] 마크다운 파싱 실패 시 plain text fallback (에러 전파 금지)
- [ ] `ImageContent.alt` → `Block.caption` 매핑
- [ ] `TableContent.caption` → `Block.caption` 매핑
- [ ] `metadata.heading_level` → `Block.heading_level` 매핑
- [ ] `content_text` 추출 시 마크다운 마크 완전 제거
- [ ] `content_hash` = `SHA-256(content_text)` (text, table) / `SHA-256(content_raw.attrs.src)` (image)
- [ ] `RichTableCell.content`가 `TableContent`일 때 재귀적으로 Tiptap table 노드 생성
- [ ] `RichTableCell.content`가 `ListContent`일 때 재귀적으로 Tiptap list 노드 생성
- [ ] 중첩 depth 초과 시 plain text fallback + 경고 로그
- [ ] 빈 테이블/리스트 허용 (경고 로그만)

---

## 12. 관련 문서

- [parser-service 연동](./6-1-parser-service-integration.md) — NDJSON 프로토콜, 큐 설계, ERD 변경
- [Document/Block 엔티티](../../03-module-design/document/data.md) — Block.content_raw (Tiptap JSON), content_text, content_hash
- [ADR-006 heading_level 파생 필드](../../adr/006-block-heading-level-derived-field.md) — heading_level 추출 패턴
- [검색·RAG 파이프라인](../../01-requirements/flows/search-rag/README.md) — content_text/caption의 검색 사용처
- [청킹 전략](../../01-requirements/flows/search-rag/02-chunking.md) — content_text 기반 청킹 입력
