> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `draft` |
> | 검수 | `unreviewed` |
> | 대상 | parser-service 개발팀 |
> | 최종 수정 | 2026-04-07 |

# parser-service API 스펙

> parser-service가 구현해야 하는 API 계약, 프로토콜, 제약 사항을 정의한다.
> aicm-service 내부 구현(큐, DB, SSE 등)은 이 문서의 범위 밖이다.

---

## 1. 서비스 역할

parser-service는 외부 문서(PDF, DOCX, PPTX, XLSX, TXT 등)를 파싱하여 **Block 구조의 NDJSON 스트림**으로 반환하는 Python(FastAPI) 서비스이다.

```
f(파일, 옵션, 커서?) → NDJSON 블록 스트림
```

### PDF 선변환 (Normalize-to-PDF)

parser-service는 입력 포맷에 관계없이 **모든 문서를 먼저 PDF로 변환**한 뒤 파싱한다. 이를 통해 파싱 로직과 커서 체계를 단일화한다.

| 단계 | 설명 |
|------|------|
| 1. 포맷 감지 | `file_type`(MIME)으로 원본 포맷 판별 |
| 2. PDF 변환 | 비PDF 포맷(DOCX, PPTX, XLSX, HWP 등)을 PDF로 변환. 원본이 PDF이면 이 단계를 건너뜀 |
| 3. PDF 파싱 | 변환된 PDF를 페이지 단위로 파싱하여 NDJSON 블록 스트림 생성 |

**결과**: 모든 포맷의 커서가 `{"page": N}` 형태로 통일되며, 커서 기반 재개(resume)가 전 포맷에서 동일하게 동작한다.

### 핵심 제약

| 항목 | 규칙 |
|------|------|
| **Stateless** | 세션, 진행 상태, 캐시를 보유하지 않는다. 호출 간 의존 없음 |
| **파일 접근** | MinIO에서 직접 읽는다 (presigned URL 아님, 내부 경로) |
| **이미지 업로드** | 추출 이미지를 MinIO에 직접 업로드하고 경로만 응답에 포함 |
| **PDF 선변환** | 비PDF 문서를 PDF로 변환한 뒤 파싱. 커서 체계 단일화 |
| **커서 발행** | 블록마다 페이지 기반 커서(`{"page": N}`)를 함께 반환 |
| **스트리밍** | 전체 완료를 기다리지 않고, 블록 생산 즉시 NDJSON 라인으로 전송 |

### MinIO 접근

parser-service는 다음 두 가지 용도로 MinIO에 직접 접근한다:

1. **원본 파일 읽기** — 요청의 `file_url` 경로에서 파일 다운로드
2. **추출 이미지 업로드** — 파싱 중 추출한 이미지를 `image_upload_prefix` 하위에 업로드

MinIO 접속 정보(endpoint, access key, secret key, bucket)는 환경변수로 주입한다.

---

## 2. API 엔드포인트

### `POST /parse`

문서를 파싱하여 NDJSON 스트림으로 블록을 반환한다.

#### 요청

```
POST /parse
Content-Type: application/json
Accept: application/x-ndjson
```

```typescript
interface ParseRequest {
  document_id: string;           // 문서 ID (이미지 업로드 경로 생성에 사용)
  file_url: string;              // MinIO 내부 경로 (예: "originals/{docId}/file.pdf")
  file_name: string;             // 원본 파일명 (확장자 포함)
  file_type: string;             // MIME type
  image_upload_prefix: string;   // 추출 이미지 업로드 경로 (예: "documents/{docId}/images")
  resume_cursor?: Record<string, unknown>;  // 재개용 불투명 커서 (생략 시 처음부터)
  options?: {
    extract_images?: boolean;    // 이미지 추출 여부 (기본: true)
    ocr_enabled?: boolean;       // OCR 활성화 (기본: false)
    language?: string;           // OCR 언어 (기본: 'ko')
  };
}
```

#### 응답 — NDJSON 스트리밍

```
Content-Type: application/x-ndjson
Transfer-Encoding: chunked
```

블록을 생산하는 즉시 한 줄씩 전송한다. 전체 파싱 완료를 기다리지 않는다.

```
{"type":"metadata","page_count":500}
{"type":"block","order":0,"block_type":"heading","content":{...},"cursor":{"page":1},"metadata":{"page_number":1,"heading_level":1}}
{"type":"block","order":1,"block_type":"text","content":{...},"cursor":{"page":1},"metadata":{"page_number":1}}
{"type":"block","order":2,"block_type":"image","content":{"src":"documents/doc-123/images/2-001.png","alt":"..."},"cursor":{"page":2},"metadata":{"page_number":2}}
{"type":"heartbeat","status":"processing","detail":"page 3, table extraction"}
...
{"type":"done","parsing_duration_ms":45000,"warnings":[]}
```

---

## 3. NDJSON 라인 타입

### 전체 타입

```typescript
type ParseStreamLine =
  | ParseMetadataLine
  | ParseBlockLine
  | ParseHeartbeatLine
  | ParseDoneLine
  | ParseErrorLine;
```

### 3.1 `metadata` — 스트림 시작

**반드시 첫 번째 라인으로 전송**한다.

```typescript
interface ParseMetadataLine {
  type: 'metadata';
  page_count: number;            // 총 페이지 수 (PDF 선변환으로 항상 존재)
}
```

### 3.2 `block` — 파싱된 블록

```typescript
interface ParseBlockLine {
  type: 'block';
  block_type: string;            // 'text' | 'heading' | 'table' | 'image' | 'list'
  content: string | object;      // 블록 내용 (중간 포맷 — §4 참조)
  order: number;                 // 블록 순서 (0부터 시작, 단조 증가)
  cursor: Record<string, unknown>;  // 불투명 커서 (§5 참조)
  metadata?: {
    page_number?: number;        // 원본 페이지 번호
    heading_level?: number;      // 제목 레벨 (1~6, heading일 때만)
    original_type?: string;      // 파서 내부 세분화 타입 (향후 확장용)
  };
}
```

**`block_type` v1 지원 목록**:

| block_type | 설명 | content 형식 |
|------------|------|-------------|
| `text` | 일반 텍스트 단락 | `string` — 인라인 마크다운 (§4.3) |
| `heading` | 제목 | `string` — 인라인 마크다운 + `metadata.heading_level` 필수 (§4.3) |
| `table` | 표 | `TableContent` JSON (§4.4) |
| `image` | 이미지 | `ImageContent` JSON (§4.6) |
| `list` | 목록 | `ListContent` JSON (§4.5) |

> 호출자는 알 수 없는 `block_type`을 `text`로 fallback 처리한다. 새 타입 추가 시 기존 호출자에 영향 없음.

### 3.3 `heartbeat` — 생존 신호

블록 생산이 지연될 때 **30초 간격**으로 전송한다.

```typescript
interface ParseHeartbeatLine {
  type: 'heartbeat';
  status: 'processing';
  detail?: string;               // 진행 상황 (예: "page 45, table extraction")
}
```

> 호출자는 `block` 또는 `heartbeat` 수신 시 타임아웃 타이머를 리셋한다. 블록 생산이 오래 걸리는 구간(복잡한 표, OCR, LLM 대기 등)에서 반드시 heartbeat를 보내야 한다.

### 3.4 `done` — 파싱 완료

스트림의 마지막 라인이다.

```typescript
interface ParseDoneLine {
  type: 'done';
  parsing_duration_ms: number;   // 파싱 소요 시간 (ms)
  warnings?: string[];           // 품질 경고 메시지 (일부 페이지 OCR 실패 등)
}
```

### 3.5 `error` — 파싱 중 오류

복구 불가능한 오류 발생 시 전송하고 스트림을 종료한다.

```typescript
interface ParseErrorLine {
  type: 'error';
  code: string;                  // 에러 코드
  message: string;               // 에러 상세 메시지
}
```

**스트림 내 에러 코드**:

| 코드 | 설명 |
|------|------|
| `PARSE_FAILED` | 파싱 처리 실패 (손상된 파일, 암호화 등) |
| `OCR_FAILED` | OCR 처리 실패 (이미지 손상 등) |
| `IMAGE_UPLOAD_FAILED` | MinIO 이미지 업로드 실패 |

### 라인 전송 순서

```
metadata (1개, 반드시 첫 번째)
  → block / heartbeat (반복)
    → done 또는 error (1개, 반드시 마지막)
```

---

## 4. Content 중간 포맷

`ParseBlockLine.content`의 형식을 정의한다. **에디터-무관(editor-agnostic)** 중간 포맷이며, Tiptap 등 특정 에디터 스키마를 직접 생성하지 않는다.

> 전체 설계 배경: [Content 중간 포맷 설계](../6-2-parser-content-intermediate-format.md)

**핵심 규칙**: `block_type`이 content 형식을 결정한다.

- **블록 구조**(표, 리스트)는 **JSON**으로 표현
- **인라인 서식**(볼드, 링크 등)은 **마크다운 문자열**로 표현
- 특정 에디터 포맷은 모른다. 중간 포맷만 반환하면 된다.

### 4.1 content 타입 요약

```typescript
type IntermediateContent =
  | string            // text, heading
  | TableContent      // table
  | ListContent       // list
  | ImageContent;     // image
```

| block_type | content 타입 | 설명 |
|-----------|-------------|------|
| `text` | `string` | 인라인 마크다운 |
| `heading` | `string` | 인라인 마크다운. 레벨은 `metadata.heading_level`에 전달 (`#` 마커 없음) |
| `table` | `TableContent` | JSON 구조 + 셀 값은 마크다운 문자열 |
| `list` | `ListContent` | JSON 구조 + 아이템 텍스트는 마크다운 문자열 |
| `image` | `ImageContent` | JSON 구조 (마크다운 없음) |

### 4.2 인라인 마크다운 — 허용 목록

content 문자열 안에서 **인라인 서식만** 사용한다. 블록 레벨 마크다운(`#`, `-`, `>`, `|` 등)은 사용하지 않는다.

| 구문 | 의미 |
|------|------|
| `**text**` | 볼드 |
| `*text*` | 이탤릭 |
| `~~text~~` | 취소선 |
| `` `text` `` | 인라인 코드 |
| `[text](url)` | 링크 |
| `==text==` | 하이라이트 |
| `<u>text</u>` | 밑줄 |
| `<sup>text</sup>` | 위첨자 |
| `<sub>text</sub>` | 아래첨자 |

**이스케이핑**: 원본 텍스트에 마크다운 구문 문자(`*`, `~`, `` ` ``, `[`, `=`)가 서식이 아닌 의미로 쓰이면 `\`로 이스케이프한다.

```
원본:  할인율은 5*10% 입니다.
중간:  할인율은 5\*10% 입니다.
```

### 4.3 text / heading

content는 인라인 마크다운 `string`이다.

```jsonc
// text
{"type":"block","block_type":"text","content":"영업점 방문 시 **본인 확인 서류**를 지참하세요.","order":1,"cursor":{"page":1},"metadata":{"page_number":1}}

// heading — # 마커 없이 텍스트만, 레벨은 metadata
{"type":"block","block_type":"heading","content":"계좌 개설 **절차**","order":0,"cursor":{"page":1},"metadata":{"page_number":1,"heading_level":2}}
```

### 4.4 table

```typescript
interface TableContent {
  has_header: boolean;              // 첫 행이 헤더인지
  rows: TableCell[][];              // 2D 배열 (행 × 열)
  caption?: string;                 // 표 캡션 (예: "표 1. 금리 조건표")
}

type TableCell = string | RichTableCell;

interface RichTableCell {
  content: CellContent;
  colspan?: number;                 // 기본 1
  rowspan?: number;                 // 기본 1
}

type CellContent =
  | string                          // 인라인 마크다운 (대부분)
  | TableContent                    // 중첩 표
  | ListContent;                    // 셀 안의 목록
```

**규칙**:
- 원본 문서에 표 캡션("표 1. …", "[Table 3-1] …" 등)이 있으면 `caption`에 담는다. 없으면 생략
- 셀 값이 단순 문자열이면 `string`으로 직접 넣는다 (object 래핑 불필요)
- 병합 셀이나 중첩 구조가 필요할 때만 `RichTableCell` 사용
- 빈 셀은 `""`. `null`이나 누락 금지
- 모든 행의 열 수는 동일 (부족하면 `""` 패딩)
- 병합된 영역의 나머지 슬롯은 생략
- **중첩 depth**: 2 depth까지 허용 (표→표, 표→리스트). 3 depth 이상은 평탄화

**예시 1 — 단순 표 + 캡션**

```
  [표 1] 고객 유형별 필요 서류

┌────────┬────────────────────┬──────────┐
│ 구분   │ 필요 서류           │ 비고     │
├────────┼────────────────────┼──────────┤
│ 개인   │ 신분증, 인감증명서   │ 사본 불가 │
├────────┼────────────────────┼──────────┤
│ 법인   │ 사업자등록증, 법인인감│          │
└────────┴────────────────────┴──────────┘
```

```jsonc
{
  "type": "block",
  "block_type": "table",
  "content": {
    "has_header": true,
    "caption": "[표 1] 고객 유형별 필요 서류",
    "rows": [
      ["**구분**",  "**필요 서류**",       "**비고**"],
      ["개인",      "신분증, 인감증명서",   "사본 불가"],
      ["법인",      "사업자등록증, 법인인감", ""]
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

### 4.5 list

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

**규칙**: 중첩은 3 depth까지. 초과 시 평탄화.

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

### 4.6 image

```typescript
interface ImageContent {
  src: string;                      // MinIO 경로 (업로드 완료한 경로)
  alt?: string;                     // 대체 텍스트 (OCR 또는 LLM 생성)
  width?: number;                   // 원본 너비 (px)
  height?: number;                  // 원본 높이 (px)
}
```

```jsonc
{
  "type": "block",
  "block_type": "image",
  "content": {
    "src": "documents/doc-123/images/4-001.png",
    "alt": "계좌 개설 신청서 양식",
    "width": 800,
    "height": 600
  },
  "order": 4,
  "cursor": { "page": 2 },
  "metadata": { "page_number": 2 }
}
```

---

## 5. 불투명 커서 (Opaque Cursor)

### 개념

parser-service는 블록마다 **커서(cursor)**를 발행한다. 호출자는 커서를 해석하지 않고 그대로 저장했다가, 재개 요청 시 `resume_cursor`로 돌려보낸다.

### 커서 형식 — 페이지 단위 통일

PDF 선변환(§1)에 의해 모든 문서가 PDF로 파싱되므로, 커서는 원본 포맷에 관계없이 **페이지 단위**로 통일된다.

```jsonc
// 모든 포맷 공통
{ "page": 30 }
```

| 원본 형식 | 변환 후 | 커서 예시 |
|-----------|---------|-----------|
| PDF | (변환 없음) | `{"page": 30}` |
| DOCX | PDF 변환 | `{"page": 30}` |
| PPTX | PDF 변환 | `{"page": 15}` |
| XLSX | PDF 변환 | `{"page": 8}` |
| TXT / Markdown | PDF 변환 | `{"page": 5}` |

### 커서 재개 (`resume_cursor`)

호출자가 `resume_cursor`를 전달하면, 해당 페이지부터 파싱을 재개한다.

- 커서 위치 **이전** 블록은 이미 저장되어 있으므로 다시 보내지 않는다
- 커서 위치의 블록부터 새로 파싱하여 스트리밍한다
- `order`는 이전 세션의 마지막 order 이후부터 이어가지 **않는다** — 커서 위치부터 0으로 재시작하며, 호출자가 기존 블록과 병합한다

> **커서 재개 구현**: PDF 선변환으로 모든 포맷이 페이지 단위로 파싱되므로, 커서 발행과 재개 모두 **전 포맷에서 동일하게 동작**한다. 포맷별 재개 난이도 차이가 없어 1차부터 전체 구현이 가능하다.
>
> LLM 파싱은 컨텍스트 의존적이므로, 중간 재개 시 이전 맥락 없이 품질이 저하될 수 있다. resume 시 직전 N개 블록 텍스트를 LLM 프롬프트에 컨텍스트로 주입하는 방안을 검토한다.

---

## 6. 이미지 처리

### 업로드 경로 규칙

추출한 이미지를 다음 경로로 MinIO에 업로드한다:

```
{image_upload_prefix}/{order}-{seq}.{ext}
```

| 토큰 | 설명 | 예시 |
|------|------|------|
| `image_upload_prefix` | 요청에서 전달받은 프리픽스 | `documents/doc-123/images` |
| `order` | 해당 이미지가 속한 블록의 order | `5` |
| `seq` | 블록 내 이미지 순번 (001부터) | `001` |
| `ext` | 이미지 확장자 | `png` |

**예**: `documents/doc-123/images/5-001.png` (order 5 블록의 첫 번째 이미지)

### `image` 블록의 content

`block_type: "image"`인 블록의 `content`에는 `ImageContent` 구조(§4.6)를 사용한다.

```json
{"type":"block","order":5,"block_type":"image","content":{"src":"documents/doc-123/images/5-001.png","alt":"신청서 양식","width":800,"height":600},"cursor":{"page":3},"metadata":{"page_number":3}}
```

> 이미지를 응답 본문(바이너리)에 포함하지 않으므로, 이미지 수에 관계없이 NDJSON 스트림 크기가 안정적이다.

---

## 7. HTTP 에러 응답

스트리밍 시작 전, 요청 자체를 거부할 때의 에러이다.

| HTTP 상태 | 에러 코드 | 설명 |
|-----------|----------|------|
| 400 | `UNSUPPORTED_FORMAT` | 지원하지 않는 파일 포맷 |
| 400 | `FILE_TOO_LARGE` | 파일 크기 초과 |
| 404 | `FILE_NOT_FOUND` | MinIO에서 파일을 찾을 수 없음 |
| 500 | `INTERNAL_ERROR` | 서비스 내부 오류 |
| 503 | `SERVICE_UNAVAILABLE` | 서비스 과부하 또는 리소스 부족 |

**에러 응답 본문**:

```json
{
  "code": "UNSUPPORTED_FORMAT",
  "message": "File type 'application/x-hwpx' is not supported"
}
```

> 스트리밍이 이미 시작된 후의 에러는 NDJSON `error` 라인(§3.5)으로 전송한다.

---

## 8. 타임아웃 제약

호출자가 적용하는 타임아웃이다. parser-service는 이 시간 안에 응답해야 한다.

| 구간 | 제한 시간 | 의미 |
|------|----------|------|
| 첫 라인 대기 | **60초** | 연결 후 `metadata` 라인까지. 파일 다운로드 + 초기화 포함 |
| 라인 간 대기 | **90초** | 연속 NDJSON 라인(`block` 또는 `heartbeat`) 사이 최대 간격 |
| 전체 스트리밍 | **30분** | 단일 파싱 요청의 최대 총 시간 |

**핵심**: 블록 생산이 90초 이상 걸리는 구간에서는 반드시 **heartbeat**를 30초 간격으로 보내야 한다. 90초 내에 `block`이나 `heartbeat`가 도착하지 않으면 호출자는 서비스가 hang된 것으로 판단하고 연결을 끊는다.

---

## 9. 환경변수

| 변수 | 설명 | 예시 |
|------|------|------|
| `MINIO_ENDPOINT` | MinIO 엔드포인트 | `minio:9000` |
| `MINIO_ACCESS_KEY` | MinIO 접근 키 | |
| `MINIO_SECRET_KEY` | MinIO 시크릿 키 | |
| `MINIO_BUCKET` | 기본 버킷 이름 | `aicm` |
| `MINIO_USE_SSL` | SSL 사용 여부 | `false` |

---

## 10. 연동 시퀀스

호출자(aicm-service Worker) 관점에서의 전체 흐름이다. parser-service가 담당하는 구간을 강조한다.

```
호출자(Worker)                   parser-service                    MinIO
     │                                │                              │
     │── POST /parse ────────────────▶│                              │
     │   { file_url, options, ... }   │── 파일 다운로드 ────────────▶│
     │                                │◀── 파일 바이너리 ────────────│
     │                                │                              │
     │◀── metadata ──────────────────│  (파싱 시작)                  │
     │                                │                              │
     │◀── block (order=0) ───────────│                              │
     │◀── block (order=1) ───────────│                              │
     │                                │── 이미지 업로드 ────────────▶│
     │◀── block (order=2, image) ────│                              │
     │                                │                              │
     │◀── heartbeat ─────────────────│  (복잡한 표 처리 중)         │
     │                                │                              │
     │◀── block (order=3) ───────────│                              │
     │   ...                          │                              │
     │◀── done ──────────────────────│  (파싱 완료)                  │
```

### 재개 시퀀스 (resume_cursor)

```
호출자(Worker)                   parser-service                    MinIO
     │                                │                              │
     │── POST /parse ────────────────▶│                              │
     │   { file_url,                  │                              │
     │     resume_cursor: {"page":30} │── 파일 다운로드 ────────────▶│
     │   }                            │◀── 파일 바이너리 ────────────│
     │                                │                              │
     │◀── metadata ──────────────────│  (page 30부터 파싱)           │
     │◀── block (order=0) ───────────│  ← order는 0부터 재시작       │
     │◀── block (order=1) ───────────│                              │
     │   ...                          │                              │
     │◀── done ──────────────────────│                              │
```

---

## 11. 체크리스트

구현 시 확인해야 할 항목이다.

### 필수 (v1)

- [ ] `POST /parse` 엔드포인트 구현
- [ ] NDJSON 스트리밍 응답 (chunked transfer)
- [ ] `metadata` → `block`* → `done`/`error` 순서 보장
- [ ] 블록마다 `cursor` 필드 포함 (전 포맷)
- [ ] `order`는 0부터 단조 증가
- [ ] heartbeat 30초 간격 전송 (블록 생산 지연 시)
- [ ] 추출 이미지 MinIO 직접 업로드 + 경로 반환
- [ ] 이미지 업로드 경로 규칙: `{prefix}/{order}-{seq}.{ext}`
- [ ] HTTP 레벨 에러 코드 반환 (400, 500, 503)
- [ ] 스트림 내 에러 시 `error` 라인 전송 후 스트림 종료
- [ ] Content 중간 포맷 준수 (§4)
  - [ ] `text`, `heading`의 content는 `string` (인라인 마크다운)
  - [ ] `table`의 content는 `{ has_header, rows }` 구조. 원본에 캡션 있으면 `caption` 포함
  - [ ] `list`의 content는 `{ list_type, items }` 구조
  - [ ] `image`의 content는 `{ src }` 구조 (`src` 필수)
  - [ ] 인라인 마크다운에 블록 레벨 구문 미포함
  - [ ] 서식 아닌 마크다운 구문 문자는 `\` 이스케이프
  - [ ] 테이블 모든 행 동일 열 수 (부족 시 `""` 패딩)
  - [ ] 중첩 표/리스트 2 depth 이하, 리스트 중첩 3 depth 이하
- [ ] 첫 라인 60초 이내 전송

### 선택 (v1 이후)

- [ ] `resume_cursor` 기반 재개 — 전 포맷 동일 (PDF 선변환으로 페이지 단위 통일)

---

## 관련 문서

- [Content 중간 포맷 설계](../6-2-parser-content-intermediate-format.md) — `content` 필드의 상세 포맷 정의
- [parser-service 연동 (전체)](../6-1-parser-service-integration.md) — aicm-service 내부 구현 포함 전체 연동 문서
