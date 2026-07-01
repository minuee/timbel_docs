# 카테고리 관리 API 프론트엔드 가이드

카테고리 순서 변경, 엑셀 양식 다운로드, 엑셀 내보내기, 엑셀 벌크 업로드 관련 API 가이드입니다.

---

## 1. 엑셀 양식 다운로드 (양식받기)

### `GET /category/download_template`

| 항목 | 값 |
|------|-----|
| Method | `GET` |
| Query Param | 없음 |
| Response | `.xlsx` 파일 다운로드 |

별도 파라미터 없이 호출하면 1depth ~ 10depth 헤더와 예시 데이터가 포함된 엑셀 양식 파일을 다운로드합니다.

#### 엑셀 양식 구조

| 1depth | 2depth | 3depth | ... | 10depth |
|--------|--------|--------|-----|---------|
| 인사 | | | | |
| 인사 | 채용 | | | |
| 인사 | 채용 | 신입채용 | | |
| 인사 | 채용 | 경력채용 | | |
| 인사 | 교육 | | | |
| IT | | | | |
| IT | 보안 | | | |
| IT | 보안 | 접근권한 | | |

#### 코드 예시 (TypeScript)

```typescript
async function downloadCategoryTemplate() {
  const res = await fetch("/category/download_template");
  if (!res.ok) throw new Error("양식 다운로드 실패");

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "category_template.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}
```

---

## 2. 기존 분류체계 엑셀 내보내기 (내려받기)

### `GET /category/download_categories`

| 항목 | 값 |
|------|-----|
| Method | `GET` |
| Query Param | `workspace_id` (필수) |
| Response | `.xlsx` 파일 다운로드 |

현재 등록된 모든 카테고리를 양식과 동일한 포맷의 엑셀 파일로 내보냅니다.

#### 코드 예시 (TypeScript)

```typescript
async function downloadCategories(workspaceId: string) {
  const res = await fetch(
    `/category/download_categories?workspace_id=${workspaceId}`,
  );
  if (!res.ok) throw new Error("분류체계 내보내기 실패");

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "categories_export.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}
```

---

## 3. 분류체계 엑셀 벌크 업로드

### `POST /category/upload_bulk`

| 항목 | 값 |
|------|-----|
| Method | `POST` |
| Query Param | `workspace_id` (필수) |
| Content-Type | `multipart/form-data` |
| Form Field | `file` (`.xlsx` 파일) |

양식에 맞춰 작성된 엑셀 파일을 업로드하여 카테고리를 벌크 등록합니다.

#### 처리 규칙

- 각 행의 왼쪽부터 빈 셀이 나올 때까지의 값을 depth 경로로 인식
- 중간 경로가 누락된 경우 자동으로 보충 (예: `인사 > 채용 > 신입채용`만 있어도 `인사`, `인사 > 채용`이 자동 생성)
- 이미 존재하는 카테고리는 스킵 (중복 안전)
- 파일 형식은 `.xlsx` 또는 `.xls`만 허용

#### Response (200 OK)

```json
{
  "total_count": 8,
  "created_count": 5,
  "skipped_count": 2,
  "failed_count": 1,
  "failures": [
    {
      "row": 7,
      "path": "IT > 보안 > 접근권한",
      "reason": "부모 카테고리를 찾을 수 없습니다."
    }
  ]
}
```

| 필드 | 설명 |
|------|------|
| `total_count` | 총 처리 건수 |
| `created_count` | 신규 생성된 카테고리 수 |
| `skipped_count` | 이미 존재하여 스킵된 수 |
| `failed_count` | 실패 건수 |
| `failures` | 실패 상세 (행 번호, 경로, 사유) |

#### Error Responses

| 상태 코드 | 상황 |
|-----------|------|
| 400 | 엑셀 파일이 아닌 경우 (`.xlsx`/`.xls` 외) |
| 400 | 엑셀 파싱 실패 |
| 400 | 등록할 데이터가 없는 경우 |
| 500 | 벌크 등록 중 서버 오류 |

#### 코드 예시 (TypeScript)

```typescript
interface BulkCreateResult {
  total_count: number;
  created_count: number;
  skipped_count: number;
  failed_count: number;
  failures: { row: number; path: string; reason: string }[];
}

async function uploadBulkCategories(
  workspaceId: string,
  file: File,
): Promise<BulkCreateResult> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(
    `/category/upload_bulk?workspace_id=${workspaceId}`,
    {
      method: "POST",
      body: formData,
    },
  );

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message ?? "벌크 업로드 실패");
  }
  return res.json();
}
```

#### 업로드 후 결과 표시 가이드

```typescript
function showBulkResult(result: BulkCreateResult) {
  const msg = `총 ${result.total_count}건 처리: 생성 ${result.created_count}건, 스킵 ${result.skipped_count}건, 실패 ${result.failed_count}건`;

  if (result.failures.length > 0) {
    const details = result.failures
      .map((f) => `  - ${f.row}행 [${f.path}]: ${f.reason}`)
      .join("\n");
    console.warn(`${msg}\n실패 상세:\n${details}`);
  }
}
```

---

## 4. 카테고리 순서 변경

### 개요

같은 depth(같은 부모)에 속한 카테고리들의 표시 순서를 변경하는 API입니다.
최상위 카테고리뿐만 아니라 모든 depth의 형제 카테고리 순서를 변경할 수 있습니다.

### API 스펙

#### `PATCH /category/update_category_order`

| 항목 | 값 |
|------|-----|
| Method | `PATCH` |
| Query Param | `workspace_id` (필수) |
| Content-Type | `application/json` |

#### Request Body

```json
{
  "parent_id": "string | null",
  "category_ids": ["string", "string", "string"]
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `parent_id` | `string \| null` | 선택 | 부모 카테고리 ID (암호화된 값). `null`이면 최상위 카테고리 대상 |
| `category_ids` | `string[]` | 필수 | 카테고리 ID 리스트 (암호화된 값). **배열 순서대로** ord가 0, 1, 2... 재부여됨 |

#### Response (200 OK)

업데이트된 카테고리 목록이 입력한 순서대로 반환됩니다.

```json
[
  {
    "id": "encrypted_id_1",
    "workspace_id": "ws1",
    "name": "총무",
    "description": "...",
    "doc_type": null,
    "icon": null,
    "ord": 0,
    "parent_id": "encrypted_parent_id",
    "root_id": "encrypted_root_id",
    "created_at": "2025-01-01T00:00:00+09:00",
    "updated_at": "2025-01-01T00:00:00+09:00"
  },
  {
    "id": "encrypted_id_2",
    "workspace_id": "ws1",
    "name": "인사",
    "ord": 1,
    "..."
  }
]
```

#### Error Response (400)

```json
{
  "detail": {
    "error": "bad_request",
    "message": "카테고리 순서 업데이트 실패: ..."
  }
}
```

#### 사용 예시

**최상위 카테고리 순서 변경**

최상위(root) 카테고리끼리 순서를 바꿀 때는 `parent_id`를 `null`로 보냅니다.

```
PATCH /category/update_category_order?workspace_id=ws1
```

```json
{
  "parent_id": null,
  "category_ids": ["총무_enc_id", "개발_enc_id", "인사_enc_id"]
}
```

결과: 총무(ord=0), 개발(ord=1), 인사(ord=2)

**하위 카테고리 순서 변경**

특정 부모 아래의 자식 카테고리 순서를 바꿀 때는 `parent_id`에 부모 카테고리 ID를 넣습니다.

```
PATCH /category/update_category_order?workspace_id=ws1
```

```json
{
  "parent_id": "인사팀_enc_id",
  "category_ids": ["채용_enc_id", "교육_enc_id", "평가_enc_id"]
}
```

결과: 채용(ord=0), 교육(ord=1), 평가(ord=2)

#### 프론트엔드 구현 가이드

**드래그 앤 드롭 / 위아래 이동 버튼**

1. 사용자가 같은 depth의 카테고리 목록에서 순서를 변경한다 (드래그 앤 드롭 또는 위/아래 버튼)
2. 변경된 순서대로 해당 카테고리들의 ID 배열을 만든다
3. 해당 카테고리들의 `parent_id`와 함께 API를 호출한다
4. 응답으로 받은 데이터로 UI를 갱신한다

**참고 사항**

- `category_ids`에는 해당 parent 아래의 **모든 형제 카테고리 ID**를 포함해야 합니다. 일부만 보내면 보낸 카테고리만 ord가 갱신되고, 누락된 카테고리의 ord는 변경되지 않습니다.
- 카테고리 조회 API(`GET /category/get_category`)의 응답은 이미 `ord` 순서로 정렬되어 반환됩니다.
- 기존 `PATCH /category/update_top_category_order` API는 하위 호환을 위해 유지되지만, 새 API가 최상위 카테고리도 지원하므로 신규 개발 시에는 `update_category_order`를 사용하세요.

#### 코드 예시 (TypeScript)

```typescript
interface SiblingOrderUpdate {
  parent_id: string | null;
  category_ids: string[];
}

async function updateCategoryOrder(
  workspaceId: string,
  parentId: string | null,
  orderedCategoryIds: string[],
): Promise<Category[]> {
  const body: SiblingOrderUpdate = {
    parent_id: parentId,
    category_ids: orderedCategoryIds,
  };

  const res = await fetch(
    `/category/update_category_order?workspace_id=${workspaceId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );

  if (!res.ok) throw new Error("순서 변경 실패");
  return res.json();
}
```

**위/아래 이동 버튼 핸들러**

```typescript
function moveCategoryUp(categories: Category[], index: number): string[] {
  if (index <= 0) return categories.map((c) => c.id);
  const ids = categories.map((c) => c.id);
  [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
  return ids;
}

function moveCategoryDown(categories: Category[], index: number): string[] {
  if (index >= categories.length - 1) return categories.map((c) => c.id);
  const ids = categories.map((c) => c.id);
  [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
  return ids;
}

// 사용 예시
async function handleMoveUp(categories: Category[], index: number) {
  const parentId = categories[0]?.parent_id ?? null;
  const newOrder = moveCategoryUp(categories, index);
  await updateCategoryOrder(workspaceId, parentId, newOrder);
}
```
