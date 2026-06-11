# Phase 1 리팩토링 다음 단계 가이드

## 현재 진행 상황 (2026-01-02)

### ✅ 완료된 작업

1. **Composables 생성** (커밋: 6104269, c7e71f4)
   - `useChatFilter.ts` (350줄) - 필터 및 검색 로직
   - `useChatKeyword.ts` (310줄) - 키워드 처리 로직
   - `useChatClipping.ts` (150줄) - 클리핑 기능 로직
   - **총 810줄의 로직 분리 완료**

2. **UI 컴포넌트 생성** (커밋: 6104269)
   - `ChatFilterPopover.vue` (260줄) - 필터 팝오버 UI

3. **chat/index.vue 임포트 추가** (커밋: d1018b4)
   ```typescript
   import ChatFilterPopover from "@/view/advisor/components/chat/ChatFilterPopover.vue";
   import { useChatFilter } from "@/view/advisor/components/chat/composables/useChatFilter";
   import { useChatKeyword } from "@/view/advisor/components/chat/composables/useChatKeyword";
   import { useChatClipping } from "@/view/advisor/components/chat/composables/useChatClipping";
   ```

### ⏳ 진행 중인 작업

**chat/index.vue 통합** - 상태 변수와 메서드를 Composable로 교체

---

## 다음 작업: chat/index.vue 통합 (Step 4 완료)

### 작업 개요

`chat/index.vue` 파일에서 기존 상태 변수와 메서드를 제거하고, Composable에서 반환된 것들로 교체합니다.

### 1단계: Composable 초기화 코드 추가

**위치**: `chat/index.vue` setup 함수 내부 (props 선언 직후)

**추가할 코드**:

```typescript
// ===== Composables 초기화 =====

// 1. 필터 Composable
const {
  // State
  isPopoverOpen,
  activeChatPopoverTab,
  chatContentSpeakerSetting,
  chatContentConversationSetting,
  chatContentConversationSearchText,
  isSearchActive,
  currentSearchIndex,
  searchResultPositions,
  appliedSearchText,
  popoverToggleButtonRef,

  // Computed
  filteredChatContent,
  isFilterActive,

  // Methods
  handlePopoverToggle,
  handleClosePopover,
  handlePopoverHide,
  handleSearchEnterNavigate,
  goToPreviousSearchResult,
  goToNextSearchResult,
  startSearchPopoverDrag,
  resetFilters
} = useChatFilter();

// 2. 키워드 Composable
const {
  // State
  selectedKeywordForBubble,
  keywordDetailLoading,
  keywordDetailData,
  upDownStateForBubble,
  detailUpDownState,

  // Computed
  recommendKeywords,

  // Methods
  getKeywordDetailData,
  handleKeywordClick,
  handleKeywordUp,
  handleKeywordDown,
  getDetailUpState,
  getDetailDownState,
  handleDetailUp,
  handleDetailDown,
  handleKeywordDelete,
  resetKeywordState
} = useChatKeyword();

// 3. 클리핑 Composable (chatContent 참조 필요)
const {
  // State
  isClippingActive,
  isClippedMessages,

  // Computed
  clippedMessagesList,
  scrollButtonBottom,

  // Methods
  handleClippingAdd,
  removeClippedMessage,
  toggleClipping,
  deactivateClipping,
  activateClipping,
  scrollToMessage,
  clearAllClippings,
  resetClippingState
} = useChatClipping(chatContent);
```

### 2단계: 제거할 기존 상태 변수 (chat/index.vue 약 755-850줄)

아래 변수들을 **완전히 삭제**합니다:

```typescript
// ❌ 삭제할 필터 관련 변수들
const isPopoverOpen = ref(false);
const activeChatPopoverTab = ref("speaker");
const chatContentSpeakerSetting = ref<string>("all");
const chatContentConversationSetting = ref<string>("all");
const chatContentConversationSearchText = ref<string>("");
const isSearchActive = ref<boolean>(false);
const currentSearchIndex = ref<number>(0);
const searchResultPositions = ref<Array<{ messageId: number; positionInMessage: number }>>([]);
const appliedSearchText = ref<string>("");
const popoverToggleButtonRef = ref<HTMLElement | null>(null);

// ❌ 삭제할 팝오버 드래그 관련 변수
const popoverDrag = ref({
  dragging: false,
  startX: 0,
  startY: 0,
  left: 0,
  top: 0,
  wasDragged: false
});
const isClosingPopoverExplicitly = ref(false);

// ❌ 삭제할 키워드 관련 변수들
const selectedKeywordForBubble = ref<Record<number, string | null>>({});
const keywordDetailLoading = ref<Record<number, boolean>>({});
const keywordDetailData = ref<Record<string, KeywordDetailGroup[]>>({});
const upDownStateForBubble = ref<Record<number, Record<string, "up" | "down" | null>>>({});
const detailUpDownState = ref<Record<number, Record<string, "up" | "down" | null>>>({});

// ❌ 삭제할 클리핑 관련 변수들
const isClippingActive = ref(true);
const isClippedMessages = ref<Record<number, boolean>>({});
```

**예상 줄 수**: 약 30-40줄 삭제

### 3단계: 제거할 기존 Computed (chat/index.vue 약 900-1000줄)

아래 computed들을 **완전히 삭제**합니다:

```typescript
// ❌ 삭제할 computed들
const filteredChatContent = computed(() => { /* ... */ });
const isFilterActive = computed(() => { /* ... */ });
const clippedMessagesList = computed(() => { /* ... */ });
const scrollButtonBottom = computed(() => { /* ... */ });
const recommendKeywords = computed(() => { /* ... */ });
```

**예상 줄 수**: 약 50-70줄 삭제

### 4단계: 제거할 기존 메서드들 (chat/index.vue 약 1200-2500줄)

아래 메서드들을 **완전히 삭제**합니다:

#### 필터 관련 메서드 (약 300줄)
```typescript
// ❌ 삭제할 메서드들
const handlePopoverToggle = () => { /* ... */ };
const handleClosePopover = () => { /* ... */ };
const handlePopoverHide = () => { /* ... */ };
const handleSearchEnterNavigate = () => { /* ... */ };
const goToPreviousSearchResult = () => { /* ... */ };
const goToNextSearchResult = () => { /* ... */ };
const scrollToSearchResult = (index: number) => { /* ... */ };
const startSearchPopoverDrag = (event: MouseEvent) => { /* ... */ };
const onSearchPopoverDragMove = (event: MouseEvent) => { /* ... */ };
const endSearchPopoverDrag = () => { /* ... */ };
const getPopoverElement = (): HTMLElement | null => { /* ... */ };
```

#### 키워드 관련 메서드 (약 400줄)
```typescript
// ❌ 삭제할 메서드들
const getKeywordDetailData = (keyword: string | null) => { /* ... */ };
const handleKeywordClick = async (...) => { /* ... */ };
const handleKeywordUp = (...) => { /* ... */ };
const handleKeywordDown = (...) => { /* ... */ };
const getDetailUpState = (...) => { /* ... */ };
const getDetailDownState = (...) => { /* ... */ };
const handleDetailUp = (...) => { /* ... */ };
const handleDetailDown = (...) => { /* ... */ };
const handleKeywordDelete = (keyword: string) => { /* ... */ };
const extractKeywordsFromBlocksMap = (doc: any) => { /* ... */ };
```

#### 클리핑 관련 메서드 (약 200줄)
```typescript
// ❌ 삭제할 메서드들
const handleClippingAdd = (bubbleId: number, content: string | undefined) => { /* ... */ };
const removeClippedMessage = (messageId: number) => { /* ... */ };
const toggleClipping = () => { /* ... */ };
const deactivateClipping = () => { /* ... */ };
const activateClipping = () => { /* ... */ };
const scrollToMessage = async (messageId: number) => { /* ... */ };
const clearAllClippings = () => { /* ... */ };
```

**예상 총 삭제 줄 수**: 약 900-1000줄

### 5단계: 템플릿 수정

**위치**: `chat/index.vue` template 부분 (약 11-193줄)

#### 변경 1: 필터 팝오버를 ChatFilterPopover 컴포넌트로 교체

**기존 코드 (삭제할 부분)**:
```vue
<ElPopover
  :visible="isPopoverOpen"
  @update:visible="isPopoverOpen = $event"
  placement="bottom"
  trigger="manual"
  <!-- 약 180줄의 팝오버 UI 코드 -->
>
  <!-- 발화자 설정 탭 -->
  <!-- 발화 내용 탭 -->
  <!-- 검색 결과 -->
</ElPopover>
```

**새 코드 (교체할 부분)**:
```vue
<ChatFilterPopover
  :is-viewer="isViewer"
  :is-popover-open="isPopoverOpen"
  @update:is-popover-open="isPopoverOpen = $event"
  :active-chat-popover-tab="activeChatPopoverTab"
  @update:active-chat-popover-tab="activeChatPopoverTab = $event"
  :chat-content-speaker-setting="chatContentSpeakerSetting"
  @update:chat-content-speaker-setting="chatContentSpeakerSetting = $event"
  :chat-content-conversation-setting="chatContentConversationSetting"
  @update:chat-content-conversation-setting="chatContentConversationSetting = $event"
  :chat-content-conversation-search-text="chatContentConversationSearchText"
  @update:chat-content-conversation-search-text="chatContentConversationSearchText = $event"
  :is-search-active="isSearchActive"
  :current-search-index="currentSearchIndex"
  :search-result-positions="searchResultPositions"
  :is-filter-active="isFilterActive"
  :popover-toggle-button-ref="popoverToggleButtonRef"
  @handle-popover-toggle="handlePopoverToggle"
  @handle-close-popover="handleClosePopover"
  @handle-popover-hide="handlePopoverHide"
  @handle-search-enter-navigate="handleSearchEnterNavigate"
  @go-to-previous-search-result="goToPreviousSearchResult"
  @go-to-next-search-result="goToNextSearchResult"
  @start-search-popover-drag="startSearchPopoverDrag"
/>
```

**예상 삭제 줄 수**: 약 180줄 삭제, 20줄 추가

### 6단계: Watch 함수 정리

**위치**: `chat/index.vue` (약 2600-2700줄)

아래 watch들을 **삭제**합니다 (Composable 내부에서 처리됨):

```typescript
// ❌ 삭제할 watch들
watch(chatContentSpeakerSetting, () => {
  // 필터 적용 로직
});

watch(chatContentConversationSetting, () => {
  // 필터 적용 로직
});
```

---

## 작업 후 예상 결과

### 파일 크기 변화
- **chat/index.vue**: 3,031줄 → **약 1,900줄** (약 1,130줄 감소)
- 감소 비율: **37% 감소**

### 코드 구조 개선
- ✅ 필터 로직 → `useChatFilter.ts`
- ✅ 키워드 로직 → `useChatKeyword.ts`
- ✅ 클리핑 로직 → `useChatClipping.ts`
- ✅ 필터 UI → `ChatFilterPopover.vue`
- ✅ 관심사 분리 (UI ↔ Logic)
- ✅ 재사용 가능한 Composable 생성

---

## 검증 체크리스트

작업 완료 후 아래 기능들이 정상 작동하는지 확인:

### 필터 기능
- [ ] 발화자 필터 (전체/고객/상담사) 동작 확인
- [ ] 발화 내용 필터 (전체/고객/상담사) 동작 확인
- [ ] 검색어 입력 및 엔터 키 검색 동작 확인
- [ ] 검색 결과 개수 표시 확인
- [ ] 이전/다음 검색 결과 네비게이션 동작 확인
- [ ] 필터 팝오버 드래그 기능 확인
- [ ] 필터 적용 시 아이콘 색상 변경 확인

### 키워드 기능
- [ ] 키워드 클릭 시 문서 검색 API 호출 확인
- [ ] 키워드 상세 데이터 표시 확인
- [ ] 키워드 Up/Down 평가 기능 확인
- [ ] 문서별 Up/Down 평가 기능 확인
- [ ] 키워드 캐싱 동작 확인 (동일 키워드 재클릭 시 API 재호출 없음)
- [ ] 키워드 삭제 기능 확인

### 클리핑 기능
- [ ] 메시지 클리핑 추가/제거 토글 확인
- [ ] 클리핑된 메시지 목록 표시 확인
- [ ] 클리핑 기능 활성화/비활성화 토글 확인
- [ ] 클리핑된 메시지로 스크롤 기능 확인
- [ ] 스크롤 버튼 위치 동적 조정 확인
- [ ] 모든 클리핑 제거 기능 확인

### UI/UX
- [ ] 페이지 로딩 시 오류 없음
- [ ] 콘솔에 에러 메시지 없음
- [ ] 모든 버튼과 인터랙션 정상 작동
- [ ] 팝오버 열기/닫기 애니메이션 정상
- [ ] 반응형 레이아웃 정상 작동

---

## 다음 단계 (Phase 1 나머지)

chat/index.vue 통합이 완료되면, Phase 1의 나머지 작업을 진행합니다:

### Step 5: 추가 컴포넌트 분리

1. **ChatMessageList.vue** - 메시지 목록 렌더링
   - 현재 template의 메시지 목록 부분 (약 200줄)
   - props: messages, isViewer, handlers

2. **ChatClippingPanel.vue** - 클리핑 패널 UI
   - 클리핑된 메시지 표시 패널 (약 100줄)
   - props: clippedMessages, handlers

3. **ChatRecommendTags.vue** - 추천 태그 컴포넌트
   - 추천 키워드 태그 표시 (약 80줄)
   - props: keywords, handlers

4. **ChatTodoModal.vue** - Todo 모달
   - Todo 관리 모달 (약 150줄)
   - props: todos, handlers

5. **ChatView.vue** - 최상위 컨테이너
   - 모든 서브 컴포넌트 조합
   - chat/index.vue의 역할을 대체

### Step 6: API 호출 중앙화

1. **src/api/modules/chat/** 디렉토리 생성
2. API 함수들을 별도 파일로 분리:
   - `getChatHistory.ts`
   - `sendMessage.ts`
   - `searchDocuments.ts`

### Step 7: 타입 정의 중앙화

1. **src/types/chat/** 디렉토리 생성
2. 타입 정의 파일 생성:
   - `ChatMessage.ts`
   - `ChatKeyword.ts`
   - `ChatClipping.ts`

---

## 작업 시 주의사항

1. **점진적 수정**
   - 한 번에 모든 것을 수정하지 말고, 섹션별로 수정 후 테스트
   - 각 섹션 수정 후 커밋하여 롤백 가능하도록 유지

2. **테스트**
   - 각 수정 후 개발 서버에서 실제 동작 확인
   - 브라우저 콘솔에서 에러 메시지 확인

3. **타입 체크**
   - TypeScript 에러가 발생하면 즉시 수정
   - `npm run type-check` 명령으로 전체 타입 확인

4. **커밋 전략**
   - 각 단계별로 커밋 (1단계 완료 → 커밋, 2단계 완료 → 커밋)
   - 커밋 메시지에 단계 번호 명시

---

## 예상 작업 시간

- **1-2단계** (Composable 초기화 + 상태 변수 제거): 30분
- **3-4단계** (Computed + 메서드 제거): 1시간
- **5단계** (템플릿 수정): 1시간
- **6단계** (Watch 정리): 15분
- **검증 및 테스트**: 1시간

**총 예상 시간**: 약 3.5-4시간

---

## 문제 발생 시 대응

### 타입 에러 발생 시
- Composable의 반환 타입과 사용처의 타입이 일치하는지 확인
- 필요시 Composable에서 명시적 타입 지정

### 기능 동작 안 함
- 브라우저 개발자 도구의 Vue DevTools로 상태 확인
- 콘솔 로그로 Composable이 올바르게 초기화되었는지 확인

### 빌드 에러
- `npm run build`로 빌드 에러 확인
- import 경로가 올바른지 확인
- 순환 참조가 없는지 확인

---

## 브랜치 전략

현재 브랜치: `feature/refactoring-chat`

작업 완료 후:
1. 모든 체크리스트 항목 확인
2. `develop_20251208` 브랜치로 PR 생성
3. 코드 리뷰 후 머지

---

## 요약

**현재 상태**: Phase 1의 약 40% 완료 (Composable 생성 완료)

**다음 작업**: chat/index.vue 통합 (상태/메서드 교체, 템플릿 수정)

**예상 결과**: chat/index.vue를 3,031줄 → 1,900줄로 줄이고, 관심사 분리 달성

**목표**: 유지보수하기 쉽고, 테스트 가능하며, 재사용 가능한 코드 구조
