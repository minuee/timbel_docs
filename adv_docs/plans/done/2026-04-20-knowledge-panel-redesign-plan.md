# Knowledge Panel 2-패널 재설계 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Knowledge 패널을 좌(문서 content) / 우(문서 리스트) 2-패널로 재구성하고, Chat 모드에서 `sources`는 리스트로 보여주되 `distilled.selected_refs`로 하이라이트만 적용 (자동 클릭 제거).

**Architecture:** Knowledge 패널 내부 상태를 `documentList` / `highlightedRefs` / `selectedDoc` 3개로 통합. Chat / AISearch / manualSearch 세 모드가 동일 레이아웃 컴포넌트를 공유. Chat 경로의 `sources` / `distilled` SSE 이벤트는 새 emit을 통해 agent → knowledge로 전달. `isAutoSearch` 기반 자동 클릭 및 `distilled` 필터링-재선택 로직은 제거.

**Tech Stack:** Vue 3 (`<script setup>`), TypeScript, Vitest (node env, source-text / pure-TS 레벨), Element Plus, ECP 컴포넌트.

**Design doc:** [2026-04-20-knowledge-panel-redesign-design.md](./2026-04-20-knowledge-panel-redesign-design.md)

**Testing 전제:** `asst-web`은 Vitest `node` 환경으로 Vue 컴포넌트 마운트 테스트 인프라가 없다. 순수 TS 헬퍼는 Vitest로 단위 테스트하고, 컴포넌트 변경은 source-text assertion(기존 `AdminCoachingCard.test.ts` 패턴) + typecheck + lint + 수동 브라우저 확인으로 검증한다.

**Commit style:** 한국어 Conventional Commits. 각 Task 완료 시 한 커밋.

---

## Task 1: 하이라이트 / 리스트 구성 순수 함수 추출

**Files:**
- Create: `asst-web/src/view/advisor/components/knowledge/helpers/documentList.ts`
- Test: `asst-web/src/view/advisor/components/knowledge/helpers/documentList.spec.ts`

**Why:** 하이라이트 판정 (`ref_num ∈ selected_refs`)과 리스트 순서 (하이라이트된 것이 위로 오도록) 같은 로직을 컴포넌트 밖 순수 함수로 꺼내두면 Vitest `node` 환경에서도 테스트 가능.

**Step 1: Write the failing test**

```ts
// documentList.spec.ts
import { describe, expect, test } from "vitest";
import { isHighlighted, sortByHighlight } from "./documentList";

describe("isHighlighted", () => {
  test("returns true when ref_num is in selected_refs set", () => {
    expect(isHighlighted({ ref_num: 2 } as any, new Set([1, 2]))).toBe(true);
  });

  test("returns false when ref_num missing", () => {
    expect(isHighlighted({} as any, new Set([1, 2]))).toBe(false);
  });

  test("returns false when selected_refs is empty", () => {
    expect(isHighlighted({ ref_num: 1 } as any, new Set<number>())).toBe(false);
  });
});

describe("sortByHighlight", () => {
  test("highlighted docs come first, preserves relative order within groups", () => {
    const docs = [
      { ref_num: 1, name: "A" },
      { ref_num: 2, name: "B" },
      { ref_num: 3, name: "C" },
      { ref_num: 4, name: "D" }
    ] as any[];
    const result = sortByHighlight(docs, new Set([2, 4]));
    expect(result.map(d => d.name)).toEqual(["B", "D", "A", "C"]);
  });

  test("returns original order when highlight set is empty", () => {
    const docs = [{ ref_num: 1 }, { ref_num: 2 }] as any[];
    expect(sortByHighlight(docs, new Set<number>())).toEqual(docs);
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd asst-web && npm run test:unit -- documentList.spec.ts
```
Expected: FAIL (module not found).

**Step 3: Implement**

```ts
// documentList.ts
export interface DocLike {
  ref_num?: number;
  [key: string]: any;
}

export function isHighlighted(doc: DocLike, highlighted: Set<number>): boolean {
  if (doc.ref_num == null) return false;
  return highlighted.has(doc.ref_num);
}

export function sortByHighlight<T extends DocLike>(docs: T[], highlighted: Set<number>): T[] {
  if (highlighted.size === 0) return docs;
  const hi: T[] = [];
  const lo: T[] = [];
  for (const d of docs) {
    if (isHighlighted(d, highlighted)) hi.push(d);
    else lo.push(d);
  }
  return [...hi, ...lo];
}
```

**Step 4: Run tests to verify they pass**

```bash
cd asst-web && npm run test:unit -- documentList.spec.ts
```
Expected: PASS.

**Step 5: Commit**

```bash
git add asst-web/src/view/advisor/components/knowledge/helpers/
git commit -m "refactor: 문서 리스트 하이라이트 판정 로직을 순수 함수로 추출

- isHighlighted: ref_num 기반 하이라이트 판정
- sortByHighlight: 하이라이트 문서가 먼저 오도록 정렬
- Vitest 단위 테스트 추가"
```

---

## Task 2: DocumentList 컴포넌트 (오른쪽 리스트 패널)

**Files:**
- Create: `asst-web/src/view/advisor/components/knowledge/DocumentList.vue`

**Why:** 세 모드(Chat/AI/manual)가 공통으로 쓸 우측 리스트. `DocumentCard`를 세로 나열하고 하이라이트/선택 상태를 시각화.

**Props:**
```ts
interface Props {
  documents: any[];              // 표시할 문서 배열
  highlightedRefs?: Set<number>; // ref_num 기반 하이라이트 (Chat 전용)
  selectedDocId?: string | number | null; // 현재 선택된 문서 (배경 강조용)
}
defineEmits<{ select: [doc: any]; openModal: [doc: any] }>();
```

**Step 1: 컴포넌트 작성**

- 템플릿: `v-for="doc in displayDocs"`, 각 항목을 `<div class="doc-list-item" :class="{ highlighted: isHi, dimmed: !isHi && hasHighlights, selected: isSelected }">` 로 감싸고 내부는 기존 `DocumentCard` 사용.
- 하이라이트 뱃지: `<ECPTag v-if="isHi" color="primary" size="small">참고</ECPTag>` + 좌측 ★ 아이콘.
- 클릭 시 `emit('select', doc)`.
- 정렬은 `sortByHighlight(props.documents, props.highlightedRefs ?? new Set())` 기반 computed.

**Step 2: Source-text test**

`asst-web/src/view/advisor/components/knowledge/DocumentList.test.ts`:
```ts
import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

describe("DocumentList.vue", () => {
  const source = readFileSync(new URL("./DocumentList.vue", import.meta.url), "utf-8");

  test("uses DocumentCard for each item", () => {
    expect(source).toContain("DocumentCard");
  });

  test("emits select event on item click", () => {
    expect(source).toMatch(/emit\(['"]select['"]/);
  });

  test("applies highlighted class based on isHighlighted helper", () => {
    expect(source).toContain("isHighlighted");
  });
});
```

**Step 3: Typecheck + lint**
```bash
cd asst-web && npm run lint && npx vue-tsc --noEmit
```
Expected: PASS (0 errors on new file).

**Step 4: Commit**
```bash
git commit -m "feat: DocumentList 컴포넌트 추가

- 문서 리스트를 세로 나열, 하이라이트/선택 상태 시각화
- 정렬: 하이라이트 문서가 상단으로
- select / openModal 이벤트 emit"
```

---

## Task 3: DocumentContentPanel 컴포넌트 (왼쪽 content 패널)

**Files:**
- Create: `asst-web/src/view/advisor/components/knowledge/DocumentContentPanel.vue`

**Why:** 좌측 content 영역. 선택된 문서가 없을 때의 빈 상태, 있을 때의 요약+본문 렌더를 한 곳에서 담당.

**Props:**
```ts
interface Props {
  document: any | null;     // selectedDoc
  summary?: string;         // LLM 요약 (Chat/AI 모드)
  emptyMessage?: string;    // 빈 상태 안내문
}
defineEmits<{ openModal: [doc: any] }>();
```

**Step 1: 컴포넌트 작성**

- `v-if="!document"`: `emptyMessage` 렌더 (기본값 "오른쪽 리스트에서 문서를 선택하세요.").
- `v-else`: `summary` 있으면 상단에 `<div class="llm-summary search-results-ai-result">` 박스 (기존 `search-results-ai-result` 스타일 재사용), 그 아래 `<DocumentDetailView :document="document" @open-modal="..." />`.
- `@go-back` 이벤트는 이 컴포넌트가 처리하지 않음 (상위에서 selectedDoc=null로 만들면 빈 상태 복귀). 내부에서는 `<DocumentDetailView>`의 go-back 이벤트를 받아서 상위에 emit `select: null` 대신, 부모가 처리하도록 `deselect` 이벤트 추가.

```ts
defineEmits<{ openModal: [doc: any]; deselect: [] }>();
```

**Step 2: Source-text test**
```ts
// DocumentContentPanel.test.ts — 빈 상태 안내문 / 요약 박스 / DocumentDetailView 사용 확인
```

**Step 3: Typecheck + lint**

**Step 4: Commit**
```bash
git commit -m "feat: DocumentContentPanel 컴포넌트 추가

- 빈 상태 안내문
- LLM 요약 박스 + DocumentDetailView 조합 렌더
- deselect / openModal 이벤트 emit"
```

---

## Task 4: Knowledge 패널 2-패널 레이아웃으로 교체 (Chat 모드 우선)

**Files:**
- Modify: `asst-web/src/view/advisor/components/knowledge/index.vue`

**Step 1: 신규 state 추가**

`<script setup>` 상단에 추가:
```ts
import DocumentList from "./DocumentList.vue";
import DocumentContentPanel from "./DocumentContentPanel.vue";

const documentList = ref<any[]>([]);
const highlightedRefs = ref<Set<number>>(new Set());
const selectedDoc = ref<any | null>(null);
const listMode = ref<"chat" | "ai" | "manual" | null>(null);
```

**Step 2: Props 추가**
```ts
const props = defineProps<{
  selectedDetailItems: Record<number, SelectedItem[]>;
  isDetailItemSelected: (bubbleId: number, keyword: string, type: string, itemId: number) => boolean;
  optionsRef: string | null;
  isViewer?: boolean;
  botId?: string;
  chatDocumentList?: any[];       // 신규
  chatSelectedRefs?: number[];    // 신규
}>();
```

**Step 3: watch로 props → state 연결**
```ts
watch(() => props.chatDocumentList, (v) => {
  if (props.optionsRef === "chat" && v) {
    documentList.value = v;
    listMode.value = "chat";
    // sources 재수신 시 선택 유지 안 함
    selectedDoc.value = null;
  }
}, { immediate: true });

watch(() => props.chatSelectedRefs, (v) => {
  highlightedRefs.value = new Set(v ?? []);
}, { immediate: true });

watch(() => props.optionsRef, (v) => {
  if (v === "AISearch") listMode.value = "ai";
  else if (v === "manualSearch") listMode.value = "manual";
  else if (v === "chat") listMode.value = "chat";
  else listMode.value = null;
  // 모드 전환 시 선택 초기화
  selectedDoc.value = null;
});
```

**Step 4: 템플릿 교체 (Chat 모드 블록)**

기존 `<div v-if="hasChatSelection" ...>` 블록 ([79-172](../../asst-web/src/view/advisor/components/knowledge/index.vue#L79-L172))을:

```html
<div v-if="listMode === 'chat'" class="knowledge-2panel flex gap16 flex-1 min-h-0">
  <DocumentContentPanel
    class="flex-1 min-w-0"
    :document="selectedDoc"
    :summary="aiSearchResultText"
    @open-modal="openDocumentModal"
    @deselect="selectedDoc = null"
  />
  <div class="knowledge-list-panel w-320 flex-shrink-0 flex flex-col gap8 min-h-0">
    <div class="content-center border-bottom-default pb8 size-border-box min-h-40">
      <ECPTypography variant="subtitle3" tag="span" color="info">참고문서</ECPTypography>
    </div>
    <DocumentList
      class="flex-1 overflow-y-auto"
      :documents="documentList"
      :highlighted-refs="highlightedRefs"
      :selected-doc-id="selectedDoc?.id ?? null"
      @select="onDocSelect"
      @open-modal="openDocumentModal"
    />
  </div>
</div>
```

**Step 5: `onDocSelect` 핸들러 추가**

기존 `handleDetailItemClick`을 재활용해 단일 doc content 가공. 핵심:
```ts
const onDocSelect = (doc: any) => {
  selectedDoc.value = doc;
  // DocumentDetailView는 document prop을 그대로 받으므로 추가 가공 없이 전달 가능
};
```

**Step 6: AISearch/manualSearch 블록은 일단 그대로 유지** (Task 8/9에서 변환). Chat 모드가 동작하는지 빌드 확인:
```bash
cd asst-web && npm run lint && npx vue-tsc --noEmit
```

**Step 7: Commit**
```bash
git commit -m "refactor: Knowledge 패널 Chat 모드를 2-패널 레이아웃으로 교체

- 왼쪽 DocumentContentPanel (빈 상태 포함)
- 오른쪽 DocumentList (하이라이트 지원)
- chatDocumentList / chatSelectedRefs prop 추가
- 기존 selection-card 다중 카드 블록 제거 (Chat 모드 한정)"
```

---

## Task 5: Chat 경로 sources / distilled → Knowledge 전달 배선

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`
- Modify: `asst-web/src/view/advisor/agent/index.vue`

**Step 1: chat/index.vue emit 추가**

```ts
// defineEmits에 추가
updateChatDocumentList: [payload: { messageId: string; list: any[] }];
updateChatSelectedRefs: [payload: { messageId: string; refs: number[] }];
```

`sources` 핸들러([L2104-L2158](../../asst-web/src/view/advisor/components/chat/index.vue#L2104-L2158)) 끝부분에:
```ts
emit("updateChatDocumentList", {
  messageId,
  list: allItems.map(it => it.data) // Document 형태로 flatten
});
```

`distilled` 핸들러([L2191-L2298](../../asst-web/src/view/advisor/components/chat/index.vue#L2191-L2298))의 early-return 이후, selected_refs 있을 때:
```ts
emit("updateChatSelectedRefs", {
  messageId,
  refs: e.selected_refs ?? []
});
```

**Step 2: agent/index.vue 연결**

```vue
<ChatComponent
  ...
  @updateChatDocumentList="handleChatDocumentListUpdate"
  @updateChatSelectedRefs="handleChatSelectedRefsUpdate"
/>
<KnowledgeComponent
  ref="knowledgeRef"
  ...
  :chat-document-list="chatDocumentList"
  :chat-selected-refs="chatSelectedRefs"
/>
```

```ts
const chatDocumentList = ref<any[]>([]);
const chatSelectedRefs = ref<number[]>([]);

const handleChatDocumentListUpdate = (payload: { messageId: string; list: any[] }) => {
  chatDocumentList.value = payload.list;
  chatSelectedRefs.value = []; // sources 재수신 → 하이라이트 리셋
};
const handleChatSelectedRefsUpdate = (payload: { messageId: string; refs: number[] }) => {
  chatSelectedRefs.value = payload.refs;
};
```

**Step 3: 수동 확인 시나리오**

`npm run dev`로 서버 기동 → 브라우저에서 고객 발화 입력 → 콘솔에서:
- `sources` 수신 시 Knowledge 패널 오른쪽에 리스트 5건 표시 (하이라이트 없음, 왼쪽은 빈 상태)
- `distilled` 수신 시 selected_refs 해당 항목에 ★ 뱃지 + 테두리, 나머지는 dim
- 리스트에서 항목 클릭 시 왼쪽 content 영역에 해당 문서가 표시됨
- 다른 항목 클릭 시 왼쪽이 교체됨

**Step 4: Commit**
```bash
git commit -m "feat: Chat sources/distilled를 Knowledge 패널 리스트로 전달

- chat/index.vue: updateChatDocumentList / updateChatSelectedRefs emit
- agent/index.vue: Knowledge 컴포넌트에 prop으로 forward
- sources 도착 → 리스트 표시, distilled 도착 → 하이라이트 적용"
```

---

## Task 6: isAutoSearch 자동 클릭 로직 제거

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue:2159-2189` (sources 핸들러 내 auto-click)

**Why:** 사용자가 왼쪽 content 패널을 "빈 상태 → 수동 선택"으로 선택했으므로 auto-click 완전 제거.

**Step 1: 해당 블록 삭제**

[L2159-L2189](../../asst-web/src/view/advisor/components/chat/index.vue#L2159-L2189)의 `if (isAutoSearch.value && firstHintKey && allItems.length > 0) { ... }` 블록 전체 제거.

**Step 2: 해당 블록에서 사용되던 `currentSelectedDocument` 참조가 다른 곳에 여전히 필요한지 Grep으로 확인**
```bash
```

Grep으로 `currentSelectedDocument` 사용처 찾고, 더 이상 필요 없으면 선언부까지 제거.

**Step 3: Typecheck + lint**
```bash
cd asst-web && npm run lint && npx vue-tsc --noEmit
```

**Step 4: 수동 확인**
- 고객 발화 → sources 수신 → Knowledge 왼쪽 패널이 빈 상태 유지 (자동으로 열리지 않음)
- distilled 수신 → 여전히 빈 상태, 오른쪽에 하이라이트만 적용

**Step 5: Commit**
```bash
git commit -m "refactor: sources 수신 시 첫 문서 자동 클릭 제거

- isAutoSearch 기반 auto-click 블록 삭제
- 사용자가 리스트에서 수동으로 선택하는 흐름으로 전환
- 관련 없는 문서가 먼저 뜨는 UX 문제 해소"
```

---

## Task 7: distilled 필터-재선택 로직 제거

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue:2228-2298`

**Why:** distilled는 이제 하이라이트 힌트로만 쓰이고, 버블 아래 칩 필터링은 유지하되 "필터링 후 재선택" 로직 (auto-click 흔적)은 제거.

**Step 1: [L2257-L2298](../../asst-web/src/view/advisor/components/chat/index.vue#L2257-L2298) `isAutoSearch...stillSelected...` 블록 제거**

선택 재조정 로직은 auto-click과 한 쌍이므로 함께 제거. 단, 칩 리스트 자체의 필터링([L2228-L2255](../../asst-web/src/view/advisor/components/chat/index.vue#L2228-L2255))은 **유지** (버블 UI는 기존 동작 보존).

**Step 2: Typecheck + lint + 수동 확인**
- 버블 아래 칩은 여전히 distilled에 의해 걸러진 항목만 표시되는지 확인
- Knowledge 리스트는 여전히 5건 전체 표시 + 하이라이트

**Step 3: Commit**
```bash
git commit -m "refactor: distilled 수신 후 자동 재선택 로직 제거

- Knowledge 패널 왼쪽이 수동 선택 모델로 바뀌어 재선택 불필요
- 버블 아래 칩 필터링은 유지"
```

---

## Task 8: AISearch 모드를 2-패널 레이아웃으로 전환

**Files:**
- Modify: `asst-web/src/view/advisor/components/knowledge/index.vue:227-257`

**Step 1: 기존 AISearch 블록을 새 레이아웃으로 교체**

```html
<div v-else-if="listMode === 'ai'" class="knowledge-2panel flex gap16 flex-1 min-h-0">
  <DocumentContentPanel
    class="flex-1 min-w-0"
    :document="selectedDoc"
    :summary="aiSearchResultText"
    @open-modal="openDocumentModal"
    @deselect="selectedDoc = null"
  />
  <div class="knowledge-list-panel w-320 flex-shrink-0 flex flex-col gap8 min-h-0">
    <div class="content-center border-bottom-default pb8 size-border-box min-h-40">
      <ECPTypography variant="subtitle3" tag="span" color="info">참고문서</ECPTypography>
    </div>
    <DocumentList
      class="flex-1 overflow-y-auto"
      :documents="searchResults"
      :selected-doc-id="selectedDoc?.id ?? null"
      @select="onDocSelect"
      @open-modal="openDocumentModal"
    />
  </div>
</div>
```

AISearch는 하이라이트 없음 (`highlighted-refs` 미전달 → DocumentList 내부에서 모두 정상 표시).

**Step 2: `handleSearch`에서 AISearch 완료 시 `selectedDoc = null` + `documentList`는 props가 아닌 `searchResults` computed로 직접 바인딩 가능.** (위 템플릿처럼 `:documents="searchResults"` 직접 전달이 더 간단.)

**Step 3: Typecheck + lint + 수동 확인**
- 상단 검색바에서 AI 검색 수행
- 왼쪽 = 빈 상태 (LLM 답변이 있으면 이것도 아직 안 보임; 선택 후에만 상단 요약으로 노출)
  - **주의:** 기존 UX는 검색 직후 AI 답변이 크게 노출되었음. 새 모델에서는 왼쪽 빈 상태에도 요약을 보여줄지 결정 필요.

**Step 3a: 빈 상태에서도 요약 노출하도록 DocumentContentPanel 개선**

`DocumentContentPanel.vue`에서 `v-if="!document"` 분기에도 `summary` 있으면 안내문 위에 요약 박스 렌더:
```html
<div v-if="!document" class="empty-state flex flex-col gap16">
  <div v-if="summary" class="llm-summary search-results-ai-result ...">
    <ECPTypography>AI 답변</ECPTypography>
    <ECPTypography>{{ summary }}</ECPTypography>
  </div>
  <div class="empty-message content-center">
    <ECPTypography color="g60">{{ emptyMessage ?? "오른쪽 리스트에서 문서를 선택하세요." }}</ECPTypography>
  </div>
</div>
```

**Step 4: Commit**
```bash
git commit -m "refactor: AISearch 모드를 2-패널 레이아웃으로 전환

- DocumentContentPanel 빈 상태에서도 LLM 요약 노출
- 참고문서 리스트는 오른쪽 DocumentList로 통일"
```

---

## Task 9: manualSearch 모드를 2-패널 레이아웃으로 전환

**Files:**
- Modify: `asst-web/src/view/advisor/components/knowledge/index.vue:182-224`

**Step 1: 기존 manualSearch 블록을 새 레이아웃으로 교체**

```html
<div v-else-if="listMode === 'manual'" class="knowledge-2panel flex gap16 flex-1 min-h-0">
  <DocumentContentPanel
    class="flex-1 min-w-0"
    :document="selectedDoc"
    @open-modal="openDocumentModal"
    @deselect="selectedDoc = null"
  />
  <div class="knowledge-list-panel w-320 flex-shrink-0 flex flex-col gap8 min-h-0">
    <ECPTabs v-model="activeTab" type="card" class="adv-tabs" @tab-click="handleTabClick">
      <ECPTabPane :label="`전체(${searchResults.length})`" name="all" />
      <ECPTabPane v-for="tab in dynamicTabs" :key="tab.name" :label="`${tab.name}(${tab.count})`" :name="tab.name" />
    </ECPTabs>
    <DocumentList
      class="flex-1 overflow-y-auto"
      :documents="getCurrentTabDocuments()"
      :selected-doc-id="selectedDoc?.id ?? null"
      @select="onDocSelect"
      @open-modal="openDocumentModal"
    />
  </div>
</div>
```

탭은 리스트 상단 필터로만 기능. 본문은 `DocumentList`가 일관되게 렌더.

**Step 2: `getCurrentTabDocuments`는 기존 ([L1002-L1011](../../asst-web/src/view/advisor/components/knowledge/index.vue#L1002-L1011)) 그대로 재활용. 탭을 computed로 바꿔 반응성 확보:**

```ts
const currentTabDocuments = computed(() => {
  if (activeTab.value === "all") return searchResults.value;
  return dynamicTabs.value.find(t => t.name === activeTab.value)?.documents ?? [];
});
```

템플릿에서 `:documents="currentTabDocuments"` 사용.

**Step 3: Typecheck + lint + 수동 확인**
- 수동 검색 → 오른쪽 리스트 표시, 탭 전환 동작
- 항목 클릭 → 왼쪽 content 교체

**Step 4: Commit**
```bash
git commit -m "refactor: manualSearch 모드를 2-패널 레이아웃으로 전환

- 탭은 리스트 상단 필터로 이동
- 본문은 DocumentList로 일관되게 렌더"
```

---

## Task 10: selection-card / 다중 선택 로직 정리

**Files:**
- Modify: `asst-web/src/view/advisor/components/knowledge/index.vue`
- Modify: `asst-web/src/view/advisor/agent/index.vue`

**Step 1: knowledge/index.vue 정리**

제거 대상:
- `allSelectedItems`, `expandedCardIndex`, `gridTemplateColumns` computed/ref
- `getContentItemsForCard`, `getBlockMapsForCard`, `handleCardToggle` 함수
- `.selection-card`, `.selection-card-collapsed` 등 관련 SCSS 블록
- `hasChatSelection` computed (더 이상 템플릿 분기에 쓰이지 않음)

`handleDetailItemClick`은 단일 doc 선택 용도로 축소 — `contentItemsMap` / `currentBlockMaps`는 selectedDoc 단일 기준으로 단순화. 아직 외부(`agent/index.vue`)가 호출 중이므로 시그니처는 유지하되 내부를 `selectedDoc.value = selectedItem?.data ?? { title, content: ... }` 형태로 단순화.

**Step 2: agent/index.vue 정리**

- `handleDetailItemClick` ([L594-L697](../../asst-web/src/view/advisor/agent/index.vue#L594-L697))의 중복 체크 / focusExistingTab 분기 제거 → 단순 `emit` 또는 직접 호출로 축소.
- `selectedDetailItems` 다중 배열 → 단일 선택(`selectedDetailItem: SelectedItem | null`)으로 전환하거나, 버블 UI의 "선택 상태 표시" 용도로만 유지하되 3개 누적 불가하게 변경.
- `handleAddKnowledgeDocuments` ([L714-L750](../../asst-web/src/view/advisor/agent/index.vue#L714-L750))는 다중 탭 누적 전제이므로 **단일 선택으로 재작성 또는 완전 제거** (호출처 Grep 후 결정).

```bash
```
Grep으로 `handleAddKnowledgeDocuments` 호출처 조사 후 영향 범위 판단.

**Step 3: Typecheck + lint**
```bash
cd asst-web && npm run lint && npx vue-tsc --noEmit
```

**Step 4: 전체 수동 회귀 확인**

- Chat 경로: 고객 발화 → 리스트 표시 → 하이라이트 → 클릭 시 왼쪽 교체 → 다른 발화 → 리스트 갱신
- AISearch: 검색 → 요약 + 리스트 → 클릭
- manualSearch: 검색 → 탭 전환 → 클릭
- DocumentDetailModal (돋보기 아이콘) 정상 동작
- Document 삭제/수정 시 리스트 재렌더
- 여러 발화 연속 → 메모리 누수나 좀비 선택 없는지

**Step 5: 전체 테스트 스위트 + 빌드**
```bash
cd asst-web && npm run test:unit && npm run build:dev
```
Expected: 기존 테스트 모두 PASS, 빌드 성공.

**Step 6: Commit**
```bash
git commit -m "refactor: 다중 문서 선택 카드 UI 및 관련 로직 제거

- knowledge/index.vue: selection-card 그리드/확장 로직 제거
- agent/index.vue: selectedDetailItems 단일 선택으로 축소
- handleDetailItemClick 내부 단순화 (selectedDoc 단일 업데이트)
- handleAddKnowledgeDocuments 단일 선택 기반으로 재작성
- 관련 SCSS 정리"
```

---

## 롤백 전략

각 Task가 독립 커밋이므로 문제 발생 시 `git revert <sha>` 단위 롤백 가능. 특히 Task 6 (auto-click 제거)를 먼저 되돌리면 UX가 기존 동작으로 즉시 회귀.

## 후속 작업 (범위 밖)

- `TabTypeKnowledgeIndex.vue`에도 동일 패턴 적용 여부 — 쓰이는 라우트 확인 후 결정
- 최근 열람 문서 실제 스토리지 연동 (현재 빈 배열)
- 하이라이트 뱃지 디자인 토큰화 (ECPTag vs 커스텀 스타일)
