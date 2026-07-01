# 템플릿 API 프론트엔드 가이드

템플릿 CRUD 및 템플릿 기반 문서 생성 흐름에 대한 가이드입니다.

---

## 핵심: 템플릿 → 문서 생성 흐름

템플릿의 `template` 필드와 문서 생성의 `contents` 필드는 **동일한 구조**(`outline` → `title` / `blocks` / `children`)를 사용합니다.
별도 변환 없이 템플릿 조회 응답을 에디터 초기값으로 사용하고, 편집 결과를 그대로 문서 저장 API에 전달하면 됩니다.

```
1. GET /template/get_template_outline  →  outline 구조 응답
2. 응답을 에디터 초기값으로 설정
3. 사용자가 편집
4. POST /docs/add_doc_with_files  →  contents에 편집된 outline 전달
```

### 노드 구조 (TemplateNode)

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `id` | `string \| null` | 선택 | 인덱스 ID (없으면 문서 생성 시 자동 생성) |
| `title` | `string` | 필수 | 섹션 제목 |
| `blocks` | `string[]` | 선택 | 섹션 블록 ID 리스트 (기본값: `[]`) |
| `children` | `TemplateNode[]` | 선택 | 하위 섹션 (기본값: `[]`, 재귀) |

### TypeScript 타입 정의

```typescript
interface TemplateNode {
  id?: string | null;
  title: string;
  blocks: string[];
  children: TemplateNode[];
}

interface TemplateOutline {
  outline: TemplateNode[];
}
```

---

## 1. 템플릿 생성

### `POST /template/add_template`

| 항목 | 값 |
|------|-----|
| Method | `POST` |
| Content-Type | `application/json` |
| Response | 생성된 템플릿 객체 |

#### Request Body

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `workspace_id` | `string` | 필수 | 워크스페이스 ID |
| `name` | `string` | 필수 | 템플릿 이름 |
| `template` | `TemplateOutline` | 필수 | 템플릿 구조 (`{"outline": [...]}`) |
| `tags` | `string[]` | 필수 | 문서 유형 태그 |

#### 요청 예시

```json
{
  "workspace_id": "ws_001",
  "name": "기술 문서 템플릿",
  "template": {
    "outline": [
      {
        "title": "1. 개요",
        "blocks": [],
        "children": [
          { "title": "1.1 목적", "blocks": [], "children": [] },
          { "title": "1.2 범위", "blocks": [], "children": [] }
        ]
      },
      {
        "title": "2. 상세 설계",
        "blocks": [],
        "children": [
          {
            "title": "2.1 아키텍처",
            "blocks": [],
            "children": [
              { "title": "2.1.1 시스템 구성도", "blocks": [], "children": [] }
            ]
          }
        ]
      }
    ]
  },
  "tags": ["기술문서", "설계"]
}
```

#### 코드 예시

```typescript
async function createTemplate(
  workspaceId: string,
  name: string,
  outline: TemplateNode[],
  tags: string[]
) {
  const res = await fetch("/template/add_template", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      workspace_id: workspaceId,
      name,
      template: { outline },
      tags,
    }),
  });

  if (res.status === 409) throw new Error("동일한 이름의 템플릿이 이미 존재합니다");
  if (!res.ok) throw new Error("템플릿 생성 실패");

  return res.json();
}
```

---

## 2. 템플릿 목록 조회

### `GET /template/get_templates`

| 항목 | 값 |
|------|-----|
| Method | `GET` |
| Query Params | `workspace_id` (필수), `tag` (선택) |
| Response | 태그 목록 + 필터된 템플릿 목록 |

#### Query Parameters

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `workspace_id` | `string` | 필수 | 워크스페이스 ID |
| `tag` | `string` | 선택 | 특정 태그로 필터링 |

#### 응답 예시

```json
{
  "tags": ["기술문서", "설계", "회의록"],
  "tags_count": { "기술문서": 3, "설계": 2, "회의록": 1 },
  "total_count": 5,
  "filtered_count": 3,
  "templates": [
    {
      "id": "암호화된_템플릿_ID",
      "workspace_id": "ws_001",
      "name": "기술 문서 템플릿",
      "template": { "outline": [...] },
      "tags": ["기술문서", "설계"],
      "created_at": "2026-03-10T10:00:00+09:00",
      "updated_at": "2026-03-10T10:00:00+09:00"
    }
  ]
}
```

#### 코드 예시

```typescript
async function getTemplates(workspaceId: string, tag?: string) {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (tag) params.set("tag", tag);

  const res = await fetch(`/template/get_templates?${params}`);
  if (!res.ok) throw new Error("템플릿 목록 조회 실패");

  return res.json();
}
```

---

## 3. 템플릿 구조 조회 (문서 생성 시 사용)

### `GET /template/get_template_outline`

| 항목 | 값 |
|------|-----|
| Method | `GET` |
| Query Params | `workspace_id` (필수), `template_id` (필수) |
| Response | `template` 필드의 값 (outline 구조) |

이 API의 응답을 **문서 에디터의 초기 contents로 그대로 사용**합니다.

#### 응답 예시

```json
{
  "outline": [
    {
      "title": "1. 개요",
      "blocks": [],
      "children": [
        { "title": "1.1 목적", "blocks": [], "children": [] },
        { "title": "1.2 범위", "blocks": [], "children": [] }
      ]
    },
    {
      "title": "2. 상세 설계",
      "blocks": [],
      "children": []
    }
  ]
}
```

#### 코드 예시: 템플릿 기반 문서 생성 흐름

```typescript
async function getTemplateOutline(workspaceId: string, templateId: string) {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    template_id: templateId,
  });

  const res = await fetch(`/template/get_template_outline?${params}`);
  if (!res.ok) throw new Error("템플릿 조회 실패");

  return res.json(); // { outline: [...] }
}

/**
 * 템플릿 기반 문서 생성 전체 흐름
 *
 * 1. 템플릿 outline 조회
 * 2. 에디터에 초기값으로 설정 (사용자 편집)
 * 3. 편집 완료 후 문서 저장 API 호출
 */
async function createDocFromTemplate(
  workspaceId: string,
  templateId: string,
  docName: string,
  categoryId: string,
  creatorId: string
) {
  // 1. 템플릿 구조 조회
  const templateOutline = await getTemplateOutline(workspaceId, templateId);

  // 2. 에디터에 초기값으로 설정 (여기서는 편집 없이 바로 저장하는 예시)
  const editedContents = templateOutline; // 실제로는 사용자 편집 후의 값

  // 3. 문서 저장 - contents에 outline 구조 그대로 전달
  const formData = new FormData();
  formData.append("workspace_id", workspaceId);
  formData.append("name", docName);
  formData.append("contents", JSON.stringify(editedContents));
  formData.append("category_id", categoryId);
  formData.append("creator_id", creatorId);
  formData.append("keywords", JSON.stringify([]));
  formData.append("meta", JSON.stringify({}));
  formData.append("is_temporary", "true");

  const res = await fetch("/docs/add_doc_with_files", {
    method: "POST",
    headers: { "X-auth-token": "토큰값" },
    body: formData,
  });

  if (!res.ok) throw new Error("문서 생성 실패");
  return res.json();
}
```

---

## 4. 템플릿 수정

### `PATCH /template/update_template`

| 항목 | 값 |
|------|-----|
| Method | `PATCH` |
| Query Params | `workspace_id` (필수), `template_id` (필수) |
| Content-Type | `application/json` |
| Response | 수정된 템플릿 객체 |

모든 필드는 선택적이며, 전달된 필드만 업데이트됩니다.

#### Request Body

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `name` | `string` | 선택 | 템플릿 이름 |
| `template` | `TemplateOutline` | 선택 | 템플릿 구조 |
| `tags` | `string[]` | 선택 | 문서 유형 태그 |

#### 코드 예시

```typescript
async function updateTemplate(
  workspaceId: string,
  templateId: string,
  updates: {
    name?: string;
    template?: { outline: TemplateNode[] };
    tags?: string[];
  }
) {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    template_id: templateId,
  });

  const res = await fetch(`/template/update_template?${params}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });

  if (!res.ok) throw new Error("템플릿 수정 실패");
  return res.json();
}
```

---

## 5. 템플릿 삭제

### `DELETE /template/delete_template`

| 항목 | 값 |
|------|-----|
| Method | `DELETE` |
| Query Params | `workspace_id` (필수), `template_id` (필수) |
| Response | 삭제 결과 메시지 |

#### 코드 예시

```typescript
async function deleteTemplate(workspaceId: string, templateId: string) {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    template_id: templateId,
  });

  const res = await fetch(`/template/delete_template?${params}`, {
    method: "DELETE",
  });

  if (!res.ok) throw new Error("템플릿 삭제 실패");
  return res.json();
}
```

---

## 에러 응답

| 상태 코드 | 상황 |
|-----------|------|
| `400` | 잘못된 요청 (필수 필드 누락, 유효성 검증 실패 등) |
| `409` | 동일한 이름의 템플릿이 이미 존재 |
| `422` | `template` 구조가 `TemplateNode` 형식에 맞지 않음 (예: `title` 누락, `children`이 배열이 아님 등) |

### 422 에러 예시 (구조 검증 실패)

`template` 필드에 `title` 없이 전송하면:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "template", "outline", 0, "title"],
      "msg": "Field required"
    }
  ]
}
```
