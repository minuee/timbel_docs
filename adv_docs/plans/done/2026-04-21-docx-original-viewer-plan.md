# DOCX 원본 문서 뷰어 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 검색 결과 DocumentDetailView에서 `open_in_new` 아이콘 클릭 시, 원본 DOCX 파일을 mammoth.js로 렌더링한 모달을 열고 현재 펼쳐진 블록 텍스트를 하이라이트+스크롤한다.

**Architecture:** `DocOriginalViewerModal.vue`(신규)가 모달 렌더링·캐시·포커스를 담당. 모듈 레벨 `Map<docId, html>`(최대 10개 FIFO)으로 세션 기반 캐시. `DocumentDetailView.vue`는 아이콘 클릭 시 `document_id`와 현재 펼쳐진 블록 content를 emit.

**Tech Stack:** Vue 3, TypeScript, mammoth (^1.8.0), Element Plus ElDialog, Axios responseType:arraybuffer

---

### Task 1: mammoth 패키지 설치

**Files:**
- Modify: `asst-web/package.json`

**Step 1: 패키지 설치**

```bash
cd asst-web
npm install mammoth
```

**Step 2: 타입 선언 확인**

mammoth 1.8.x는 번들에 타입 포함. 별도 `@types/mammoth` 불필요.

```bash
npx tsc --noEmit 2>&1 | head -20
```

Expected: mammoth 관련 에러 없음

**Step 3: 커밋**

```bash
git add asst-web/package.json asst-web/package-lock.json
git commit -m "build: mammoth 패키지 추가 (DOCX → HTML 변환)"
```

---

### Task 2: knowledge.api.ts에 원본 문서 fetch 메서드 추가

**Files:**
- Modify: `asst-web/src/api/apis/knowledge.api.ts`

**Step 1: 메서드 추가**

`knowledge.api.ts` 파일 끝 `}` 닫기 전에 아래 메서드를 추가한다.

```typescript
  /** 원본 문서 파일 (DOCX/PDF) 가져오기 - ArrayBuffer 반환 */
  getDocumentOriginal = async (documentId: string): Promise<ArrayBuffer> => {
    const response = await this.client.get(`/v1/documents/${documentId}/original`, {
      responseType: "arraybuffer"
    });
    return response.data as ArrayBuffer;
  };
```

**Step 2: 타입체크**

```bash
cd asst-web
npx tsc --noEmit
```

Expected: 에러 없음

**Step 3: 커밋**

```bash
git add asst-web/src/api/apis/knowledge.api.ts
git commit -m "feat: knowledge API에 원본 문서 다운로드 메서드 추가"
```

---

### Task 3: DocOriginalViewerModal.vue 신규 생성

**Files:**
- Create: `asst-web/src/view/advisor/components/knowledge/DocOriginalViewerModal.vue`

**Step 1: 파일 생성**

```vue
<template>
  <ElDialog
    :model-value="modelValue"
    width="860px"
    :show-close="false"
    modal-class="adv-modal-container"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="flx-align-center gap8">
        <ECPTypography variant="subtitle4" color="g80">원본 문서</ECPTypography>
      </div>
      <ECPButton variant="text" class="adv-icon-button" @click="emit('update:modelValue', false)">
        <template #append>
          <ECPIcon icon="close" class="icon-button-content" color="var(--disabled-color-info)" size="medium" />
        </template>
      </ECPButton>
    </template>

    <div class="original-viewer-body adv-page-scroll size-border-box p20">
      <!-- 로딩 상태 -->
      <div v-if="isLoading" class="loading-wrap flx-center">
        <ECPTypography variant="body2" color="g60">문서를 불러오는 중...</ECPTypography>
      </div>

      <!-- 에러 상태 -->
      <div v-else-if="errorMsg" class="error-wrap flx-center">
        <ECPTypography variant="body2" color="error">{{ errorMsg }}</ECPTypography>
      </div>

      <!-- 렌더링된 HTML -->
      <div v-else ref="docBodyRef" class="doc-html-body" v-html="renderedHtml" />
    </div>
  </ElDialog>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { ElDialog } from "element-plus";
import { KnowledgeAPI } from "@/api/apis/knowledge.api";

// 모듈 레벨 캐시 - 세션 기반 (페이지 새로고침 시 초기화), 최대 10개 FIFO
const _cache = new Map<string, string>();
const MAX_CACHE = 10;

function setCached(docId: string, html: string) {
  if (_cache.size >= MAX_CACHE) {
    _cache.delete(_cache.keys().next().value!);
  }
  _cache.set(docId, html);
}

interface Props {
  modelValue: boolean;
  documentId: string;
  activeContent: string; // 포커스할 블록 텍스트 (캐시 안 함)
}

const props = defineProps<Props>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();

const isLoading = ref(false);
const errorMsg = ref("");
const renderedHtml = ref("");
const docBodyRef = ref<HTMLElement | null>(null);

// mammoth는 비동기 import (코드 스플리팅, 첫 호출 시에만 로드)
async function convertDocx(buffer: ArrayBuffer): Promise<string> {
  const mammoth = await import("mammoth");
  const result = await mammoth.convertToHtml({ arrayBuffer: buffer });
  return result.value;
}

async function loadDocument() {
  if (!props.documentId) return;

  // 캐시 HIT
  if (_cache.has(props.documentId)) {
    renderedHtml.value = _cache.get(props.documentId)!;
    await nextTick();
    focusActiveContent();
    return;
  }

  // 캐시 MISS → API 요청
  isLoading.value = true;
  errorMsg.value = "";
  renderedHtml.value = "";

  try {
    const buffer = await KnowledgeAPI.instance.getDocumentOriginal(props.documentId);
    const html = await convertDocx(buffer);
    setCached(props.documentId, html);
    renderedHtml.value = html;
    await nextTick();
    focusActiveContent();
  } catch (e) {
    errorMsg.value = "문서를 불러오지 못했습니다.";
  } finally {
    isLoading.value = false;
  }
}

function focusActiveContent() {
  if (!docBodyRef.value || !props.activeContent) return;

  const searchText = props.activeContent.slice(0, 60).trim();
  if (!searchText) return;

  // 기존 하이라이트 제거
  docBodyRef.value.querySelectorAll("mark.kms-focus").forEach(el => {
    el.replaceWith(document.createTextNode(el.textContent || ""));
  });

  // 텍스트 노드 순회하여 일치 구간 찾기
  const walker = document.createTreeWalker(docBodyRef.value, NodeFilter.SHOW_TEXT);
  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const idx = node.textContent?.indexOf(searchText) ?? -1;
    if (idx === -1) continue;

    const range = document.createRange();
    range.setStart(node, idx);
    range.setEnd(node, idx + searchText.length);

    const mark = document.createElement("mark");
    mark.className = "kms-focus";
    range.surroundContents(mark);
    mark.scrollIntoView({ behavior: "smooth", block: "center" });
    break; // 첫 번째 일치만
  }
}

// 모달이 열릴 때마다 (documentId 또는 activeContent 변경 포함)
watch(
  () => [props.modelValue, props.documentId] as const,
  ([open]) => {
    if (open) loadDocument();
  },
  { immediate: false }
);

// activeContent만 바뀌면 (같은 문서, 다른 섹션) → 다시 포커스만
watch(
  () => props.activeContent,
  async () => {
    if (props.modelValue && renderedHtml.value) {
      await nextTick();
      focusActiveContent();
    }
  }
);
</script>

<style scoped lang="scss">
.original-viewer-body {
  height: 600px;
}

.loading-wrap,
.error-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.doc-html-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-g80);

  :deep(h1),
  :deep(h2),
  :deep(h3) {
    font-weight: 600;
    margin: 16px 0 8px;
    color: var(--color-black);
  }

  :deep(p) {
    margin: 6px 0;
  }

  :deep(table) {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
  }

  :deep(td),
  :deep(th) {
    border: 1px solid var(--color-g30);
    padding: 6px 10px;
    font-size: 13px;
  }

  :deep(mark.kms-focus) {
    background-color: #fff176;
    border-radius: 2px;
    padding: 0 2px;
  }
}
</style>
```

**Step 2: 타입체크**

```bash
cd asst-web
npx tsc --noEmit
```

Expected: 에러 없음

**Step 3: 커밋**

```bash
git add asst-web/src/view/advisor/components/knowledge/DocOriginalViewerModal.vue
git commit -m "feat: DOCX 원본 뷰어 모달 컴포넌트 추가 (mammoth, FIFO 캐시)"
```

---

### Task 4: DocumentDetailView.vue — activeContent 추적 + emit 업데이트

**Files:**
- Modify: `asst-web/src/view/advisor/components/knowledge/DocumentDetailView.vue`

**현재 상태:**
- `handleOpenModal` → `emit("openModal", props.document)`
- emit 타입: `openModal: [document: Document]`
- `handleContentToggle(contentIndex, isCollapsed, isUp)` 가 isUp=true(펼침) 를 받음

**Step 1: `document_id` 필드를 Document 인터페이스에 추가, `activeContent` ref 추가, emit 타입 변경**

`DocumentDetailView.vue` 파일의 `interface Document` 블록을 아래로 교체한다:

```typescript
interface Document {
  id: number;
  document_id?: string; // UUID (검색 결과에서 전달)
  title: string;
  name?: string;
  type: string;
  keywords?: string[];
  blocks_map?: Array<{
    id: string;
    content: string;
    hit_count: number;
    score?: number;
  }>;
  contents?: {
    outline: Array<{
      id: string;
      title: string;
      blocks: string[];
      children: Array<{
        id: string;
        title: string;
        blocks: string[];
        children: any[];
      }>;
    }>;
  };
}
```

**Step 2: emit 타입 + activeContent ref 추가**

`const emit = defineEmits<{` 블록을 아래로 교체:

```typescript
const activeContent = ref("");

const emit = defineEmits<{
  goBack: [];
  openModal: [document: Document];
  openOriginalViewer: [documentId: string, activeContent: string];
}>();
```

**Step 3: `handleContentToggle` 수정 — 펼쳐진 섹션의 content를 activeContent에 저장**

기존 `handleContentToggle` 함수를 아래로 교체:

```typescript
const handleContentToggle = (contentIndex: number, isCollapsed: boolean, isUp: boolean) => {
  const contentItem = contentItems.value[contentIndex];
  if (contentItem) {
    contentItem.isCollapsed = isCollapsed;
    contentItem.isUp = isUp;
  }

  // 섹션이 열릴 때(isUp=true) blocks_map에서 해당 블록 content 추출
  if (isUp && contentItem) {
    const blockIds: string[] = (contentItem as any).blocks || [];
    const firstBlockId = blockIds[0];
    const block = props.document?.blocks_map?.find(b => b.id === firstBlockId);
    if (block?.content) {
      activeContent.value = block.content;
    }
  }
};
```

**Step 4: `handleOpenModal` 수정**

기존 `handleOpenModal` 함수를 아래로 교체:

```typescript
const handleOpenModal = () => {
  if (!props.document) return;

  const docId = (props.document as any).document_id || String(props.document.id);
  emit("openOriginalViewer", docId, activeContent.value);
};
```

**Step 5: 타입체크**

```bash
cd asst-web
npx tsc --noEmit
```

Expected: 에러 없음

**Step 6: 커밋**

```bash
git add asst-web/src/view/advisor/components/knowledge/DocumentDetailView.vue
git commit -m "feat: DocumentDetailView에 activeContent 추적 및 openOriginalViewer emit 추가"
```

---

### Task 5: knowledge/index.vue — DocOriginalViewerModal 연결

**Files:**
- Modify: `asst-web/src/view/advisor/components/knowledge/index.vue`

**Step 1: import 추가**

`index.vue` 상단 import 블록(다른 컴포넌트 import 근처)에 추가:

```typescript
import DocOriginalViewerModal from "@/view/advisor/components/knowledge/DocOriginalViewerModal.vue";
```

**Step 2: 상태 변수 추가**

`isDocumentModalOpen` 등 다른 상태 변수 근처에 추가:

```typescript
const isOriginalViewerOpen = ref(false);
const originalViewerDocId = ref("");
const originalViewerContent = ref("");
```

**Step 3: 핸들러 추가**

`openDocumentModal` 함수 아래에 추가:

```typescript
const openOriginalViewer = (documentId: string, activeContent: string) => {
  originalViewerDocId.value = documentId;
  originalViewerContent.value = activeContent;
  isOriginalViewerOpen.value = true;
};
```

**Step 4: DocumentDetailView 사용 부분에 이벤트 바인딩 추가**

index.vue 템플릿에서 `<DocumentDetailView` 태그를 찾아 `@open-original-viewer` 이벤트를 추가:

```vue
<DocumentDetailView
  v-else
  :document="selectedDocumentForDetail"
  @go-back="goBackToSearchResults"
  @open-modal="openDocumentModal"
  @open-original-viewer="openOriginalViewer"
/>
```

(DocumentDetailView가 여러 곳에 있다면 모두 동일하게 적용)

**Step 5: 템플릿 하단에 모달 컴포넌트 추가**

다른 `ElDialog`/`DocModal` 근처(템플릿 맨 아래 `</template>` 직전)에 추가:

```vue
<DocOriginalViewerModal
  v-model="isOriginalViewerOpen"
  :document-id="originalViewerDocId"
  :active-content="originalViewerContent"
/>
```

**Step 6: 타입체크 + 린트**

```bash
cd asst-web
npx tsc --noEmit
npm run lint
```

Expected: 에러 0

**Step 7: 커밋**

```bash
git add asst-web/src/view/advisor/components/knowledge/index.vue
git commit -m "feat: 검색 결과 원본 DOCX 뷰어 연결 (open_in_new → DocOriginalViewerModal)"
```

---

## 검증 방법

1. 검색 실행 → 결과 카드 클릭 → DocumentDetailView 열림
2. 섹션 하나를 펼침 (ContentCollapse toggle)
3. `open_in_new` 아이콘 클릭
4. 로딩 스피너 표시 후 DOCX 렌더링 확인
5. 펼쳐진 블록 텍스트가 노란 `<mark>` 로 하이라이트되고 스크롤됨 확인
6. 모달 닫고 다시 같은 문서 아이콘 클릭 → 로딩 없이 즉시 표시 (캐시 HIT)
7. 다른 섹션 펼치고 아이콘 클릭 → 다른 위치로 포커스 이동 확인
8. 다른 문서 카드로 이동 후 아이콘 클릭 → 새로 요청 확인
