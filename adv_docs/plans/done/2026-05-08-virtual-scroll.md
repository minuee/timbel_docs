# 채팅 가상 스크롤(DynamicScroller) 구현 계획

> **완료일: 2026-05-08**
> **결과:** 7개 Task 모두 구현 완료. `DynamicScroller` 적용, `filteredChatContent` computed 전환, 스크롤 API 전면 교체 완료. 타입 체크 오류(우리 변경분) 0개.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `chat/index.vue`의 `v-for` 렌더링을 `vue-virtual-scroller`의 `DynamicScroller`로 교체하여 긴 상담에서 발생하는 텍스트 지연, 점진적 성능 저하, 스크롤 버벅임을 해결한다.

**Architecture:** 전체 메시지 데이터는 JS 배열에 그대로 유지하되 DOM에는 현재 화면에 보이는 ~15개 컴포넌트만 마운트한다. `filteredChatContent`를 `ref`에서 `computed`로 전환해 STT 스트리밍 업데이트 시 불필요한 전체 재계산을 제거한다. 기존 `querySelector` 기반 스크롤 로직은 `dynamicScrollerRef`와 `scrollToItem()` API로 전면 교체한다.

**Tech Stack:** Vue 3, vue-virtual-scroller 2.x (DynamicScroller / DynamicScrollerItem), TypeScript

---

## 변경 대상 파일

- **수정:** `asst-web/src/main.ts` — 플러그인 등록
- **수정:** `asst-web/src/view/advisor/components/chat/index.vue` — 템플릿·스크립트 전반
- **수정:** `asst-web/src/view/advisor/components/chat/composables/useChatSearch.ts` — itemIndex 추가
- **수정:** `asst-web/src/view/advisor/components/chat/composables/useChatKeywordInteraction.ts` — scrollToKeywordDetail 재설계

---

## Task 1: vue-virtual-scroller 설치 및 전역 등록

**Files:**
- Modify: `asst-web/package.json` (npm install)
- Modify: `asst-web/src/main.ts:161` (app.use 추가)

**Step 1: 패키지 설치**

```bash
cd asst-web && npm install vue-virtual-scroller
```

Expected: `package.json`의 dependencies에 `vue-virtual-scroller` 추가됨

**Step 2: main.ts에 플러그인 등록**

`asst-web/src/main.ts`의 `app.use(ElementPlus, ...)` 바로 아래에 추가:

```typescript
import VueVirtualScroller from "vue-virtual-scroller";
import "vue-virtual-scroller/dist/vue-virtual-scroller.css";

// ... (기존 import들 아래에)
app.use(VueVirtualScroller);
```

**Step 3: 타입 선언 확인**

`vue-virtual-scroller`는 자체 타입 선언이 포함되어 있음. 별도 `@types` 패키지 불필요.

**Step 4: 커밋**

```
build: vue-virtual-scroller 패키지 설치 및 전역 등록
```

---

## Task 2: `filteredChatContent` → `computed` 전환

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**배경:** 현재 `filteredChatContent`는 `ref`이며, `addChatMessage` / `updateChatMessage` / 여러 `watch` 에서 `updateFilteredContent()`를 명시적으로 호출한다. STT partial 업데이트마다 전체 배열이 교체되어 Vue가 N개 컴포넌트를 전부 diff한다.

**Step 1: `filteredChatContent` ref → computed로 교체**

`index.vue` 스크립트에서 아래 코드를 찾아 교체:

```typescript
// 삭제할 코드 (750번째 줄 근처)
const filteredChatContent = ref<any[]>([]);
```

```typescript
// 추가할 코드
const filteredChatContent = computed<any[]>(() => {
  const roleFilter =
    chatContentConversationSetting.value !== "all"
      ? chatContentConversationSetting.value
      : chatContentSpeakerSetting.value;
  if (roleFilter === "all") return chatContent.value;
  return chatContent.value.filter((item: any) => item.sender === roleFilter);
});
```

**Step 2: `updateFilteredContent` 함수 및 관련 호출 제거**

아래 항목들을 `index.vue`에서 삭제:

1. `updateFilteredContent` 함수 전체 (1413~1432번째 줄)
2. `watch(chatContentSpeakerSetting, () => { updateFilteredContent(); });` (1435~1437번째 줄)
3. `watch(chatContent, () => { updateFilteredContent(); });` (1455~1457번째 줄)
4. `addChatMessage` 함수 내 `updateFilteredContent();` 호출 (1283번째 줄)
5. `updateChatMessage` 함수 내 `updateFilteredContent();` 호출 (1295번째 줄)
6. `onMounted` 내 `updateFilteredContent();` 호출 (1173번째 줄)
7. `preservedChatContent` watch 내 `updateFilteredContent();` 호출 (1448번째 줄)

**Step 3: `resetSearchPositionsIfInactive` watch 추가**

기존 `updateFilteredContent`에서 호출하던 로직을 별도 watch로 유지:

```typescript
// chatContentSpeakerSetting watch 삭제한 자리 근처에 추가
watch(filteredChatContent, () => {
  resetSearchPositionsIfInactive();
});
```

**Step 4: 타입체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit
```

Expected: 에러 없음 (ComputedRef는 Ref의 서브타입이므로 useChatSearch 파라미터와 호환)

**Step 5: 커밋**

```
refactor: filteredChatContent를 computed로 전환하여 STT 업데이트 시 불필요한 재계산 제거
```

---

## Task 3: v-for → DynamicScroller 템플릿 교체

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue` (template + script)

**Step 1: script에 ref 추가**

`index.vue` script 상단부 ref 선언 근처 (735번째 줄 근처)에 추가:

```typescript
// DynamicScroller ref — 스크롤 제어에 사용
const dynamicScrollerRef = ref<any>(null);
```

**Step 2: 템플릿에서 기존 v-for 블록 교체**

교체 전 (260~445번째 줄):
```vue
<div class="adv-chat-content-container" :class="{ 'flex-1': isAdmin }" v-else>
  <template v-for="item in filteredChatContent" :key="item.id">
    <div :data-message-id="item.id">
      <SpeechBubble ... />
    </div>
    <!-- 키워드 클릭 시 표시될 컴포넌트 -->
    <div
      v-if="selectedKeywordForBubble[item.id]"
      class="mb10 py20 px10 border-radius8 border-default bg-white-50"
      :data-message-id="item.id"
    >
      <!-- ... 키워드 상세 내용 ... -->
    </div>
  </template>
  <div v-if="isCallEnded" class="pb20">
    <!-- ... 통화 종료 메시지 ... -->
  </div>
</div>
```

교체 후:
```vue
<DynamicScroller
  v-else
  ref="dynamicScrollerRef"
  class="adv-chat-content-container"
  :class="{ 'flex-1': isAdmin }"
  :items="filteredChatContent"
  key-field="id"
  :min-item-size="80"
  :buffer="600"
  @scroll.passive="onScrollerScroll"
>
  <template #default="{ item, active }">
    <DynamicScrollerItem
      :item="item"
      :active="active"
      :size-dependencies="[
        item.content,
        item.isStreaming,
        selectedKeywordForBubble[item.id],
        keywordDetailLoading[item.id],
      ]"
    >
      <div :data-message-id="item.id">
        <SpeechBubble
          :content="item.content"
          :sender="item.sender"
          :time="item.time"
          :customerInfoStatus="item.customerInfoStatus"
          :chatContentConversationSearchText="appliedSearchText"
          :isSearchActive="isSearchActive"
          :currentSearchIndex="currentSearchIndex"
          :messageId="item.id"
          :searchResultPositions="searchResultPositions"
          :highlightKeywords="item.highlightKeywords"
          :selectedKeyword="selectedKeywordTextForBubble[item.id]"
          :upDownState="upDownStateForBubble[item.id] || {}"
          :isClippingActive="isClippingActive"
          :isClipped="isClippedMessages[item.id] || false"
          :isViewer="isViewer"
          :intentId="item.intentId"
          :customerUtterance="item.customerUtterance"
          :hasSearchQuery="item.hasSearchQuery"
          :isStreaming="item.isStreaming || false"
          :isSearchQueryLoading="searchQueryLoading[item.id] || false"
          @keyword-click="
            (keyword, isSelected, intentId, customerUtterance) =>
              handleKeywordClick(item.id, keyword, isSelected, intentId, customerUtterance)
          "
          @keyword-up="(keyword, isSelected) => handleKeywordUp(item.id, keyword, isSelected)"
          @keyword-down="(keyword, isSelected) => handleKeywordDown(item.id, keyword, isSelected)"
          @clipping-add="content => handleClippingAdd(item.id, content)"
          @search-query-click="() => handleSearchQueryClick(item.id, item.nlpData)"
        />
      </div>
      <!-- 키워드 클릭 시 표시될 컴포넌트 — DynamicScrollerItem 안에 배치해야 높이 재측정됨 -->
      <!-- data-message-id → data-detail-id로 변경 (중복 제거) -->
      <div
        v-if="selectedKeywordForBubble[item.id]"
        class="mb10 py20 px10 border-radius8 border-default bg-white-50"
        :data-detail-id="item.id"
      >
        <!-- 기존 키워드 상세 내용 그대로 유지 -->
        <!-- Loading 상태 -->
        <div v-if="keywordDetailLoading[item.id]" class="flex justify-center items-center py20">
          <!-- ... 기존 로딩 UI 그대로 ... -->
        </div>
        <div v-else class="flex flex-col gap20">
          <!-- ... 기존 키워드 상세 UI 그대로 ... -->
        </div>
      </div>
    </DynamicScrollerItem>
  </template>

  <!-- 통화 종료 메시지는 #after 슬롯으로 이동 -->
  <template #after>
    <div v-if="isCallEnded" class="pb20">
      <ElDivider>
        <ECPTypography variant="body3" tag="span" color="g60">상담이 종료되었습니다.</ECPTypography>
      </ElDivider>
      <div v-if="!isAdmin" class="flex justify-center mb16">
        <ECPButton :disabled="isViewer" variant="filled" color="info" @click="handleTodoAddModal">
          할일 등록
        </ECPButton>
      </div>
    </div>
  </template>
</DynamicScroller>
```

> **주의:** 키워드 상세 div의 속성을 `:data-message-id` → `:data-detail-id`로 변경한다. 같은 `data-message-id`를 가진 요소가 2개 존재하는 기존 버그 수정.

**Step 3: 타입체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit
```

**Step 4: 커밋**

```
feat: v-for → DynamicScroller 교체, 키워드 상세를 DynamicScrollerItem 내부로 이동
```

---

## Task 4: 스크롤 제어 코드 교체

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: `setupScrollListener` 함수 제거**

`setupScrollListener` 함수 전체(1236~1256번째 줄)를 삭제하고, `onMounted` 내 `setupScrollListener();` 호출(1175번째 줄)도 삭제.

**Step 2: `onScrollerScroll` 함수 추가**

`scrollToBottom` 함수 근처에 추가:

```typescript
// DynamicScroller의 @scroll 이벤트 핸들러 — setupScrollListener 대체
const onScrollerScroll = (event: Event) => {
  const el = event.target as HTMLElement;
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
  if (!isCalling.value) {
    showScrollToBottomButton.value = false;
    return;
  }
  showScrollToBottomButton.value = distance > SCROLL_TO_BOTTOM_THRESHOLD;
};
```

**Step 3: `scrollToBottom` 함수 수정**

기존 `scrollToBottom`(1361~1385번째 줄)을 교체:

```typescript
// scrollToBottom — DynamicScroller ref 기반으로 교체
const scrollToBottom = () => {
  return new Promise<void>(resolve => {
    if (scrollBottomTimer) {
      clearTimeout(scrollBottomTimer);
    }

    scrollBottomTimer = setTimeout(() => {
      scrollBottomTimer = null;
      nextTick(() => {
        const el = dynamicScrollerRef.value?.$el as HTMLElement | null;
        if (el) {
          el.scrollTop = el.scrollHeight;
        }
        resolve();
      });
    }, 80);
  });
};
```

**Step 4: recommend tag watch 수정**

1460~1470번째 줄의 watch를 교체:

```typescript
// 지식정보 패널이 열리거나 키워드가 선택되면 DOM 업데이트 후 채팅을 맨 아래로 스크롤
watch(
  [isRecommendTagActive, selectedRecommendTag],
  ([active]) => {
    if (!active) return;
    nextTick(() => {
      const el = dynamicScrollerRef.value?.$el as HTMLElement | null;
      if (el) el.scrollTop = el.scrollHeight;
    });
  },
  { flush: "post" }
);
```

**Step 5: 타입체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit
```

**Step 6: 커밋**

```
refactor: 스크롤 제어를 querySelector에서 DynamicScroller ref 기반으로 교체
```

---

## Task 5: `scrollToItemById` 헬퍼 추가 및 `scrollToMessage` 교체

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: `scrollToItemById` 헬퍼 함수 추가**

`scrollToBottom` 함수 바로 아래에 추가:

```typescript
// 메시지 ID로 DynamicScroller 스크롤 — querySelector 대체 공통 헬퍼
const scrollToItemById = (bubbleId: number) => {
  const index = filteredChatContent.value.findIndex((item: any) => item.id === bubbleId);
  if (index !== -1 && dynamicScrollerRef.value) {
    dynamicScrollerRef.value.scrollToItem(index);
  }
};
```

**Step 2: `scrollToMessage` 함수 교체**

기존 `scrollToMessage`(1488~1525번째 줄)를 교체:

```typescript
// 클리핑 메시지 클릭 시 해당 위치로 스크롤
const scrollToMessage = (bubbleId: number) => {
  return new Promise<void>(resolve => {
    scrollToItemById(bubbleId);
    resolve();
  });
};
```

**Step 3: 타입체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit
```

**Step 4: 커밋**

```
refactor: scrollToMessage를 DynamicScroller scrollToItem API로 교체
```

---

## Task 6: `useChatSearch` — `itemIndex` 추가 및 스크롤 콜백 주입

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatSearch.ts`
- Modify: `asst-web/src/view/advisor/components/chat/index.vue` (composable 초기화 부분)

**배경:** 현재 `searchResultPositions`에는 `messageId`와 `positionInMessage`만 저장된다. 가상 스크롤에서는 배열 인덱스(`itemIndex`)가 있어야 `scrollToItem()`을 호출할 수 있다. 또한 `scrollToCurrentSearchResult`가 `document.querySelector` + `scrollIntoView`를 사용하므로, 스크롤 콜백을 외부에서 주입받도록 변경한다.

**Step 1: `useChatSearch.ts` 인터페이스에 `scrollToItemByIndex` 추가**

```typescript
export interface UseChatSearchParams {
  filteredChatContent: Ref<ChatMessage[]>;
  isSearchActive: Ref<boolean>;
  chatContentConversationSearchText: Ref<string>;
  chatContentConversationSetting: Ref<string>;
  onSearch: (conversationSetting: string, searchText: string) => void;
  scrollToItemByIndex: (index: number) => void;  // ← 추가
}
```

**Step 2: `searchResultPositions` 타입에 `itemIndex` 추가**

```typescript
// 변경 전
const searchResultPositions = ref<Array<{ messageId: number; positionInMessage: number }>>([]);

// 변경 후
const searchResultPositions = ref<Array<{
  messageId: number;
  positionInMessage: number;
  itemIndex: number;
}>>([]);
```

**Step 3: `calculateSearchPositions`에서 `itemIndex` 함께 저장**

`filteredChatContent.value.forEach(item => {` 를 아래로 교체:

```typescript
filteredChatContent.value.forEach((item, arrayIndex) => {
  // ... (기존 매칭 로직 동일) ...
  positions.push({
    messageId: Number(item.id),
    positionInMessage: searchIndex,
    itemIndex: arrayIndex,  // ← 추가
  });
  // ...
});
```

**Step 4: `scrollToCurrentSearchResult` 교체**

```typescript
// 현재 검색 결과로 스크롤 — querySelector + scrollIntoView 제거
const scrollToCurrentSearchResult = () => {
  if (searchResultPositions.value.length === 0) return;
  const currentResult = searchResultPositions.value[currentSearchIndex.value];
  scrollToItemByIndex(currentResult.itemIndex);
};
```

**Step 5: `index.vue`의 `useChatSearch` 초기화에 콜백 추가**

`useChatSearch({` 블록(964번째 줄)에 추가:

```typescript
} = useChatSearch({
  filteredChatContent,
  isSearchActive,
  chatContentConversationSearchText,
  chatContentConversationSetting,
  onSearch: (setting: string, searchText: string) => handleSpeechBubbleText(setting, searchText),
  scrollToItemByIndex: (index: number) => {   // ← 추가
    dynamicScrollerRef.value?.scrollToItem(index);
  },
});
```

**Step 6: 타입체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit
```

**Step 7: 커밋**

```
refactor: useChatSearch 검색 결과 스크롤을 DynamicScroller scrollToItem API로 교체
```

---

## Task 7: `useChatKeywordInteraction` — `scrollToKeywordDetail` 재설계

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatKeywordInteraction.ts`
- Modify: `asst-web/src/view/advisor/components/chat/index.vue` (composable 초기화 부분)

**배경:** `scrollToKeywordDetail`이 `querySelector` + `nextTick + setTimeout(100ms)` 패턴을 사용한다. 가상 스크롤에서는 대상 DOM이 없을 수 있으므로, 먼저 `scrollToItemById`로 이동해서 DOM을 생성한 뒤, `data-detail-id`로 정확한 위치를 찾는다.

**Step 1: 인터페이스에 두 콜백 추가**

```typescript
export interface UseChatKeywordInteractionParams {
  summaryByKey: Ref<Record<string, string>>;
  isAdmin: ComputedRef<boolean>;
  isClippingActive: Ref<boolean>;
  isDocumentModalOpen: Ref<boolean>;
  selectedDocument: Ref<{ title: string; type: string; item?: unknown } | null>;
  emit: (event: string, ...args: unknown[]) => void;
  scrollToItemById: (bubbleId: number) => void;       // ← 추가
  getScrollContainer: () => HTMLElement | null;        // ← 추가
}
```

**Step 2: `scrollToKeywordDetail` 함수 교체**

기존 함수(40~107번째 줄) 전체를 교체:

```typescript
const scrollToKeywordDetail = async (bubbleId: number): Promise<void> => {
  // 1. 가상 스크롤이 해당 아이템을 DOM에 생성하도록 먼저 이동
  scrollToItemById(bubbleId);

  // 2. DOM 렌더링 완료 대기
  await nextTick();

  // 3. 이제 DOM에 있으므로 키워드 상세 div 탐색
  const scrollContainer = getScrollContainer();
  if (!scrollContainer) return;

  const detailEl = scrollContainer.querySelector(`[data-detail-id="${bubbleId}"]`);
  if (!detailEl) return; // 키워드 상세가 펼쳐지지 않은 경우

  const containerRect = scrollContainer.getBoundingClientRect();
  const elementRect = detailEl.getBoundingClientRect();
  const isVisible =
    elementRect.top >= containerRect.top && elementRect.bottom <= containerRect.bottom;

  if (!isVisible) {
    const scrollTop = scrollContainer.scrollTop + (elementRect.top - containerRect.top) - 20;
    scrollContainer.scrollTo({ top: scrollTop, behavior: "smooth" });
  }
};
```

**Step 3: `index.vue`의 `useChatKeywordInteraction` 초기화에 콜백 추가**

`useChatKeywordInteraction({` 블록(909번째 줄)에 추가:

```typescript
} = useChatKeywordInteraction({
  summaryByKey,
  isAdmin: computed(() => props.isAdmin),
  isClippingActive,
  isDocumentModalOpen,
  selectedDocument,
  emit: emit as (event: string, ...args: unknown[]) => void,
  scrollToItemById: (bubbleId: number) => {              // ← 추가
    const index = filteredChatContent.value.findIndex((item: any) => item.id === bubbleId);
    if (index !== -1 && dynamicScrollerRef.value) {
      dynamicScrollerRef.value.scrollToItem(index);
    }
  },
  getScrollContainer: () =>                              // ← 추가
    (dynamicScrollerRef.value?.$el as HTMLElement | null) ?? null,
});
```

**Step 4: 타입체크 실행**

```bash
cd asst-web && npx vue-tsc --noEmit
```

**Step 5: 커밋**

```
refactor: useChatKeywordInteraction scrollToKeywordDetail을 DynamicScroller ref 기반으로 재설계
```

---

## 검증 방법

- 상담 중 STT partial 텍스트가 실시간으로 나타나는지 확인
- 100개 이상 메시지 쌓인 뒤 스크롤 버벅임 없는지 확인
- 키워드 클릭 → 상세 펼침 → 해당 위치로 스크롤되는지 확인
- 발화 내용 검색 → 이전/다음 결과 이동이 정상 동작하는지 확인
- 클리핑 메시지 클릭 → 해당 위치로 이동하는지 확인
- 관리자(isAdmin) 화면에서도 동일하게 동작하는지 확인
- 통화 종료 메시지("상담이 종료되었습니다.")가 마지막에 표시되는지 확인

## 리스크 및 고려사항

- `DynamicScroller`는 루트 요소에 `height`가 정의되어야 동작함. 기존 `.adv-chat-content-container`의 `flex-1 + overflow-y: auto` 스타일이 그대로 적용되므로 별도 height 지정 불필요
- `vue-virtual-scroller`의 CSS(`vue-virtual-scroller/dist/vue-virtual-scroller.css`)를 반드시 import해야 레이아웃이 올바르게 렌더링됨
- `filteredChatContent`가 `computed`로 바뀌면 `ComputedRef<any[]>`가 되는데, `useChatSearch`의 `Ref<ChatMessage[]>` 파라미터와 타입이 맞지 않을 수 있음. 타입 에러 발생 시 `useChatSearch` 인터페이스의 타입을 `Ref<ChatMessage[]> | ComputedRef<ChatMessage[]>`로 수정
