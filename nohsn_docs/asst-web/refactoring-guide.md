# 프로젝트 리팩토링 가이드

> 작성일: 2026-01-02
> 프로젝트: asst-web
> 목적: 코드 유지보수성 및 확장성 개선

---

## 📑 목차

1. [진행 상황](#1-진행-상황) ⭐ NEW
2. [현재 상태 분석](#2-현재-상태-분석)
3. [주요 문제점](#3-주요-문제점)
4. [리팩토링 전략](#4-리팩토링-전략)
5. [Phase 1: 긴급 개선 (1-2주)](#5-phase-1-긴급-개선-1-2주)
6. [Phase 2: 중기 개선 (3-4주)](#6-phase-2-중기-개선-3-4주)
7. [Phase 3: 장기 개선](#7-phase-3-장기-개선)
8. [마이그레이션 체크리스트](#8-마이그레이션-체크리스트)

---

## 1. 진행 상황

> 최종 업데이트: 2026-01-02

### 전체 진행률

```
Phase 1: ████████░░░░░░░░░░░░ 40% (진행 중)
Phase 2: ░░░░░░░░░░░░░░░░░░░░  0% (대기)
Phase 3: ░░░░░░░░░░░░░░░░░░░░  0% (대기)
```

### Phase 1 상세 진행 상황

| 단계 | 작업 | 상태 | 커밋 | 비고 |
|------|------|------|------|------|
| Step 1-3 | Composables 생성 | ✅ 완료 | 6104269, c7e71f4 | 810줄 분리 |
| Step 3 | ChatFilterPopover.vue 생성 | ✅ 완료 | 6104269 | 260줄 UI 분리 |
| Step 4 | chat/index.vue 임포트 | ✅ 완료 | d1018b4 | 기본 세팅 |
| Step 4 | chat/index.vue 상태 교체 | ⏳ 대기 | - | 다음 작업 |
| Step 4 | chat/index.vue 메서드 교체 | ⏳ 대기 | - | 다음 작업 |
| Step 4 | chat/index.vue 템플릿 수정 | ⏳ 대기 | - | 다음 작업 |
| Step 5 | 추가 컴포넌트 분리 | ⏳ 대기 | - | 미착수 |
| Step 6 | API 중앙화 | ⏳ 대기 | - | 미착수 |
| Step 7 | 타입 정의 중앙화 | ⏳ 대기 | - | 미착수 |

### 완료된 파일

#### ✅ Composables (3개, 810줄)

1. **useChatFilter.ts** (350줄) - 커밋: 6104269
   ```typescript
   // 기능: 필터링 및 검색
   - 발화자 필터 (전체/고객/상담사)
   - 발화 내용 검색
   - 검색 결과 네비게이션
   - 팝오버 드래그
   ```

2. **useChatKeyword.ts** (310줄) - 커밋: c7e71f4
   ```typescript
   // 기능: 키워드 관리
   - 키워드 클릭 처리
   - CE API 문서 검색
   - Up/Down 평가
   - 데이터 캐싱
   ```

3. **useChatClipping.ts** (150줄) - 커밋: c7e71f4
   ```typescript
   // 기능: 메시지 클리핑
   - 클리핑 추가/제거
   - 클리핑 목록 관리
   - 메시지 스크롤
   ```

#### ✅ UI 컴포넌트 (1개, 260줄)

1. **ChatFilterPopover.vue** (260줄) - 커밋: 6104269
   ```vue
   <!-- 기능: 필터 UI -->
   - 발화자 설정 탭
   - 발화 내용 검색 탭
   - 검색 결과 표시
   ```

### 성과 요약

- **총 분리된 코드**: 1,070줄
- **생성된 Composable**: 3개
- **생성된 컴포넌트**: 1개
- **커밋 횟수**: 3회
- **브랜치**: feature/refactoring-chat

### 다음 작업

상세 내용은 [next-steps-phase1.md](./next-steps-phase1.md) 참조

**즉시 진행할 작업**:
1. chat/index.vue에서 기존 상태 변수 제거 (30-40줄)
2. chat/index.vue에서 기존 메서드 제거 (900-1000줄)
3. 템플릿에서 필터 UI를 ChatFilterPopover로 교체 (180줄 → 20줄)
4. 전체 기능 테스트 및 검증

**예상 효과**:
- chat/index.vue: 3,031줄 → 1,900줄 (37% 감소)

---

## 2. 현재 상태 분석

### 2.1 프로젝트 규모

```
📊 파일 통계
- Vue 파일: 129개
  - src/view/: 74개 (페이지/기능별 컴포넌트)
  - src/components/: 55개 (재사용 가능한 UI 컴포넌트)
- TypeScript 파일: 142개
- Pinia Store 모듈: 35개
```

### 2.2 디렉토리 구조

```
src/
├── api/                    # API 통신 계층
│   ├── modules/
│   │   ├── request.ts     # 레거시 Axios (단일 인스턴스)
│   │   └── [기타 API 모듈]
│   └── apiPlugin.ts       # 모던 API (서비스별 인스턴스)
│
├── stores/                 # Pinia State Management (35개 모듈)
│   └── modules/
│       ├── chatData.ts
│       ├── advisorbot.ts
│       ├── bookmark.ts
│       └── [기타 32개]
│
├── composables/            # Vue Composition API
│   └── useAdvisorbot.ts
│
├── hooks/                  # 유틸 Hooks (10개)
│   ├── useTime.ts
│   ├── useDateFormat.ts
│   └── [기타]
│
├── components/             # 재사용 컴포넌트 (55개)
│   └── layout/
│       ├── Drawer/
│       ├── HeaderActionBar/
│       └── ContentLayout/
│
└── view/                   # 페이지 컴포넌트 (74개)
    └── advisor/
        ├── agent/
        └── components/
            └── chat/
                └── index.vue  # ⚠️ 3,031줄 (문제 파일)
```

### 2.3 초대형 컴포넌트 목록

| 파일 | 줄 수 | 주요 문제 |
|------|------|----------|
| `chat/index.vue` | **3,031** | Props 21개, State 60개+, 메서드 30개+ |
| `TabTypeKnowledgeIndex.vue` | 1,397 | 복잡한 필터링 로직 |
| `ChatHistoryModal.vue` | 1,310 | 데이터 정렬/필터 혼재 |
| `knowledge/index.vue` | 1,126 | 검색 + CRUD 로직 |
| `Bookmark.vue` | 1,110 | 그룹/카드 관리 로직 |
| `AdminCoaching.vue` | 1,014 | 복잡한 상태 관리 |
| `Memo.vue` | 991 | CRUD + UI 로직 혼재 |
| `ContentCollapse.vue` | 950 | 트리 구조 관리 |

---

## 3. 주요 문제점

### 3.1 초대형 컴포넌트 (God Component)

**chat/index.vue (3,031줄) 분석:**

```typescript
❌ Props: 21개 (과도함)
❌ State 변수: 60개 이상
❌ 메서드: 30개 이상
❌ Store 의존성: 5개 동시 사용
❌ 직접 API 호출 포함 (라인 993)
❌ Composable 의존성 복합
```

**구조:**
```vue
<!-- Template: 646줄 -->
<template>
  <div>
    <!-- 검색 팝오버 (200줄) -->
    <!-- 채팅 메시지 (400줄) -->
    <!-- 클리핑 컨테이너 (150줄) -->
    <!-- 추천 태그 (200줄) -->
    <!-- 할일 모달 (150줄) -->
  </div>
</template>

<!-- Script: 2,385줄 -->
<script setup>
// 60개 이상의 State 변수
// 30개 이상의 메서드
// 5개의 Store 의존성
// 직접 API 호출
</script>
```

### 2.2 API 호출 패턴 혼재

**문제:**
```typescript
// ❌ Pattern A: Component에서 직접 호출
// chat/index.vue (라인 993)
const subscribeChannels = async (socketChannels: string[]) => {
  const advisorApi = getClient("advisor");
  const response = await advisorApi.post(
    `/api/asst/v1/redis-monitor/subscribe/${encodedChannelName}`
  );
  // ...
};

// ✅ Pattern B: Store Actions에서 호출 (권장)
// stores/modules/advisorbot.ts
const initialize = async (options?: ApiOptions) => {
  AdvisorbotClient.init(options);
};

// ⚠️ Pattern C: 2가지 API 클라이언트 혼재
// request.ts (레거시) vs apiPlugin.ts (모던)
```

### 2.3 로직 분리 부족

```
❌ UI 로직 + 비즈니스 로직 + API 호출이 한 파일에 혼재
❌ 단일 책임 원칙(SRP) 위반
❌ 테스트 불가능한 구조
```

### 2.4 코드 중복

**반복되는 패턴:**

```typescript
// 1) 데이터 필터링 + 정렬 (CallHistory, Bookmark, Memo 등)
const filteredData = computed(() => {
  return items.filter(item => {
    // 필터 조건
  }).sort((a, b) => {
    // 정렬 로직
  });
});

// 2) Modal 상태 관리 (모든 컴포넌트)
const showModal = ref(false);
const openModal = () => { showModal.value = true; };
const closeModal = () => { showModal.value = false; };

// 3) 로딩 상태 (모든 비동기 작업)
const loading = ref(false);
const handleAsync = async () => {
  loading.value = true;
  try { /* ... */ }
  finally { loading.value = false; }
};

// 4) 배열 업데이트 (여러 CRUD 컴포넌트)
const updateItem = (id: string, newData: any) => {
  const index = items.value.findIndex(i => i.id === id);
  if (index !== -1) {
    items.value[index] = { ...items.value[index], ...newData };
  }
};
```

---

## 4. 리팩토링 전략

### 4.1 목표

```
✅ 단일 파일 최대 줄 수: 500줄 이하
✅ Component Props: 10개 이하
✅ API 호출: Store/Composable에서만
✅ 코드 중복: 80% 감소
✅ 테스트 커버리지: 60% 이상
```

### 4.2 단계별 접근

| Phase | 기간 | 우선순위 | 주요 작업 |
|-------|------|---------|----------|
| **Phase 1** | 1-2주 | 🔴 긴급 | chat/index.vue 분할, API 호출 중앙화 |
| **Phase 2** | 3-4주 | 🟡 중간 | 공통 Composables 추출, Store 정리 |
| **Phase 3** | 지속적 | 🟢 낮음 | 레거시 제거, 테스트 추가 |

### 4.3 설계 원칙

```
1. 단일 책임 원칙 (SRP)
   - 한 파일은 한 가지 역할만

2. 관심사의 분리 (Separation of Concerns)
   - UI 로직 vs 비즈니스 로직 vs 데이터 계층

3. DRY (Don't Repeat Yourself)
   - 공통 로직은 Composable로

4. 계층화 (Layered Architecture)
   Component → Composable → Store → API
```

---

## 5. Phase 1: 긴급 개선 (1-2주)

### 5.1 chat/index.vue 분할

#### 현재 구조 (3,031줄)

```
chat/index.vue
├── Template (646줄)
│   ├── 검색 팝오버 (200줄)
│   ├── 채팅 메시지 (400줄)
│   ├── 클리핑 컨테이너 (150줄)
│   ├── 추천 태그 (200줄)
│   └── 할일 모달 (150줄)
└── Script (2,385줄)
    ├── Props (21개)
    ├── State (60개+)
    ├── Methods (30개+)
    └── API 호출
```

#### 개선 후 구조

```
src/view/advisor/components/chat/
├── ChatView.vue (500줄)              # 메인 컨테이너
├── ChatMessageList.vue (400줄)       # 메시지 렌더링
├── ChatFilterPopover.vue (300줄)     # 검색/필터 UI
├── ChatClippingPanel.vue (250줄)     # 클리핑 기능
├── ChatRecommendTags.vue (250줄)     # 추천 태그
├── ChatTodoModal.vue (200줄)         # 할일 모달
└── composables/
    ├── useChatFilter.ts (150줄)      # 필터링 로직
    ├── useChatKeyword.ts (200줄)     # 키워드 처리
    └── useChatClipping.ts (150줄)    # 클리핑 로직
```

### 5.2 ChatView.vue (메인 컨테이너)

```vue
<template>
  <div class="chat-view">
    <!-- 필터 팝오버 -->
    <ChatFilterPopover
      v-model:visible="filterVisible"
      @filter-change="handleFilterChange"
    />

    <!-- 메시지 리스트 -->
    <ChatMessageList
      :messages="filteredMessages"
      :selected-keyword="selectedKeyword"
      @keyword-click="handleKeywordClick"
    />

    <!-- 클리핑 패널 -->
    <ChatClippingPanel
      v-if="showClipping"
      :clipped-messages="clippedMessages"
      @remove="handleRemoveClip"
    />

    <!-- 추천 태그 -->
    <ChatRecommendTags
      v-if="showRecommend"
      :keywords="recommendKeywords"
      @tag-click="handleTagClick"
    />

    <!-- 할일 모달 -->
    <ChatTodoModal
      v-model="showTodoModal"
      @save="handleTodoSave"
    />
  </div>
</template>

<script setup lang="ts">
import { useChatFilter } from './composables/useChatFilter';
import { useChatKeyword } from './composables/useChatKeyword';
import { useChatClipping } from './composables/useChatClipping';

// ✅ Props 축소: 21개 → 8개
interface Props {
  id?: string;
  currentConsultant?: any;
  isAdmin?: boolean;
  isViewer?: boolean;
  tenantId?: string;
  cardPosition?: "left" | "right";
  showConsultantView?: boolean;
  toggleConsultantView?: () => void;
}

const props = withDefaults(defineProps<Props>(), {
  isAdmin: false,
  isViewer: false,
  showConsultantView: false,
  cardPosition: "left"
});

// ✅ Composables로 로직 분리
const {
  filteredMessages,
  filterVisible,
  handleFilterChange
} = useChatFilter();

const {
  selectedKeyword,
  recommendKeywords,
  handleKeywordClick,
  handleTagClick
} = useChatKeyword();

const {
  clippedMessages,
  showClipping,
  handleRemoveClip
} = useChatClipping();
</script>
```

### 5.3 useChatFilter.ts (필터링 로직)

```typescript
// src/view/advisor/components/chat/composables/useChatFilter.ts
import { ref, computed } from 'vue';
import { useChatDataStore } from '@/stores/modules/chatData';

export function useChatFilter() {
  const chatDataStore = useChatDataStore();

  // State
  const filterVisible = ref(false);
  const searchKeyword = ref('');
  const speakerFilter = ref<'all' | 'agent' | 'customer'>('all');
  const dateFilter = ref({ start: '', end: '' });

  // Computed
  const filteredMessages = computed(() => {
    let messages = chatDataStore.activeChatContent;

    // 발화자 필터
    if (speakerFilter.value !== 'all') {
      messages = messages.filter(msg =>
        msg.sender === speakerFilter.value
      );
    }

    // 키워드 검색
    if (searchKeyword.value) {
      messages = messages.filter(msg =>
        msg.content.includes(searchKeyword.value)
      );
    }

    // 날짜 필터
    if (dateFilter.value.start && dateFilter.value.end) {
      messages = messages.filter(msg => {
        const msgDate = new Date(msg.time);
        return msgDate >= new Date(dateFilter.value.start) &&
               msgDate <= new Date(dateFilter.value.end);
      });
    }

    return messages;
  });

  // Methods
  const handleFilterChange = (filters: any) => {
    searchKeyword.value = filters.keyword || '';
    speakerFilter.value = filters.speaker || 'all';
    dateFilter.value = filters.dateRange || { start: '', end: '' };
  };

  const resetFilter = () => {
    searchKeyword.value = '';
    speakerFilter.value = 'all';
    dateFilter.value = { start: '', end: '' };
  };

  return {
    filterVisible,
    filteredMessages,
    handleFilterChange,
    resetFilter
  };
}
```

### 5.4 useChatKeyword.ts (키워드 처리)

```typescript
// src/view/advisor/components/chat/composables/useChatKeyword.ts
import { ref, computed } from 'vue';
import { getClient } from '@/api/apiPlugin';
import { showCustomMessage } from '@/utils/messageUtils';

export function useChatKeyword() {
  // State
  const selectedKeywordForBubble = ref<Record<number, string | null>>({});
  const keywordDetailData = ref<Record<string, any[]>>({});
  const keywordDetailLoading = ref<Record<number, boolean>>({});

  // Computed
  const recommendKeywords = computed(() => {
    return Object.values(keywordDetailData.value).flat();
  });

  // Methods
  const handleKeywordClick = async (
    bubbleId: number,
    keyword: string,
    isSelected: boolean,
    intentId: string,
    customerUtterance: string
  ) => {
    if (!isSelected) {
      selectedKeywordForBubble.value[bubbleId] = null;
      return;
    }

    // 캐시 체크
    if (keywordDetailData.value[keyword]) {
      selectedKeywordForBubble.value[bubbleId] = keyword;
      return;
    }

    try {
      keywordDetailLoading.value[bubbleId] = true;
      selectedKeywordForBubble.value[bubbleId] = keyword;

      // API 호출
      const ceApi = getClient("ce");
      const response = await ceApi.post(
        `/api/ce/v1/advisor/search-documents`,
        { intentId, customerUtterance }
      );

      if (response?.status === 200) {
        keywordDetailData.value[keyword] = response.data.data.documents.map(
          (doc: any) => ({
            id: doc.id,
            title: doc.name,
            keyword: extractKeywords(doc),
            data: doc
          })
        );
      }
    } catch (error) {
      console.error(`키워드 '${keyword}' API 호출 실패:`, error);
      showCustomMessage({
        message: `키워드 조회에 실패했습니다.`,
        type: "error",
        duration: 2000,
        category: "키워드"
      });
    } finally {
      keywordDetailLoading.value[bubbleId] = false;
    }
  };

  const extractKeywords = (doc: any): string[] => {
    // 키워드 추출 로직
    return [];
  };

  return {
    selectedKeyword: selectedKeywordForBubble,
    recommendKeywords,
    keywordDetailData,
    keywordDetailLoading,
    handleKeywordClick
  };
}
```

### 5.5 API 호출 중앙화

#### 문제: Component에서 직접 API 호출

```typescript
// ❌ chat/index.vue (라인 993)
const subscribeChannels = async (socketChannels: string[]) => {
  const advisorApi = getClient("advisor");
  const response = await advisorApi.post(
    `/api/asst/v1/redis-monitor/subscribe/${encodedChannelName}`
  );
  const { room } = response.data.socketConnection;
  joinRoom(room);
};
```

#### 해결: Store → Composable → Component 구조

**1) Store에 API 메서드 추가**

```typescript
// src/stores/modules/chatData.ts
import { defineStore } from 'pinia';
import { getClient } from '@/api/apiPlugin';

export const useChatDataStore = defineStore('chatData', () => {
  // State
  const subscribedChannels = ref<string[]>([]);
  const socketRooms = ref<Map<string, string>>(new Map());

  // ✅ API Action
  const subscribeChannel = async (channelName: string) => {
    try {
      const advisorApi = getClient("advisor");
      const encodedChannelName = encodeURIComponent(channelName);

      const response = await advisorApi.post(
        `/api/asst/v1/redis-monitor/subscribe/${encodedChannelName}`
      );

      const { room } = response.data.socketConnection;

      // State 업데이트
      subscribedChannels.value.push(channelName);
      socketRooms.value.set(channelName, room);

      return room;
    } catch (error) {
      console.error('채널 구독 실패:', error);
      throw error;
    }
  };

  const unsubscribeChannel = async (channelName: string) => {
    try {
      const advisorApi = getClient("advisor");
      const encodedChannelName = encodeURIComponent(channelName);

      await advisorApi.post(
        `/api/asst/v1/redis-monitor/unsubscribe/${encodedChannelName}`
      );

      // State 업데이트
      subscribedChannels.value = subscribedChannels.value.filter(
        ch => ch !== channelName
      );
      socketRooms.value.delete(channelName);
    } catch (error) {
      console.error('채널 구독 해제 실패:', error);
      throw error;
    }
  };

  return {
    subscribedChannels,
    socketRooms,
    subscribeChannel,
    unsubscribeChannel
  };
});
```

**2) Composable에서 Store 래핑**

```typescript
// src/composables/useChatChannel.ts
import { useChatDataStore } from '@/stores/modules/chatData';
import { useSocketIO } from '@/composables/useSocketIO';

export function useChatChannel() {
  const chatDataStore = useChatDataStore();
  const { joinRoom, leaveRoom } = useSocketIO();

  const subscribeChannels = async (socketChannels: string[]) => {
    for (const channel of socketChannels) {
      try {
        const room = await chatDataStore.subscribeChannel(channel);
        joinRoom(room);
      } catch (error) {
        console.error(`채널 ${channel} 구독 실패:`, error);
      }
    }
  };

  const unsubscribeChannels = async (socketChannels: string[]) => {
    for (const channel of socketChannels) {
      try {
        await chatDataStore.unsubscribeChannel(channel);
        const room = chatDataStore.socketRooms.get(channel);
        if (room) leaveRoom(room);
      } catch (error) {
        console.error(`채널 ${channel} 구독 해제 실패:`, error);
      }
    }
  };

  return {
    subscribeChannels,
    unsubscribeChannels
  };
}
```

**3) Component에서 사용**

```vue
<script setup lang="ts">
// ✅ Component는 Composable만 사용
import { useChatChannel } from '@/composables/useChatChannel';

const { subscribeChannels } = useChatChannel();

onMounted(async () => {
  await subscribeChannels(['channel1', 'channel2']);
});
</script>
```

### 5.6 마이그레이션 일정

```
Week 1-2: chat/index.vue 분할

Day 1-3:
  ✅ useChatFilter.ts 추출 및 테스트
  ✅ ChatFilterPopover.vue 분리

Day 4-6:
  ✅ useChatKeyword.ts 추출 및 테스트
  ✅ ChatMessageList.vue 분리

Day 7-10:
  ✅ useChatClipping.ts 추출
  ✅ ChatClippingPanel.vue 분리
  ✅ ChatRecommendTags.vue 분리
  ✅ ChatTodoModal.vue 분리

Day 11-14:
  ✅ ChatView.vue 완성 (메인 컨테이너)
  ✅ 기존 chat/index.vue 교체
  ✅ 회귀 테스트
```

---

## 6. Phase 2: 중기 개선 (3-4주)

### 6.1 공통 Composable: useTableFilter

#### 문제: 필터링/정렬 로직 중복

```typescript
// CallHistory.vue, Bookmark.vue, Memo.vue 등에서 반복
const filteredData = computed(() => {
  return items.filter(item => {
    if (activeTab.value === 'interest') return item.isImportant;
    return true;
  }).sort((a, b) => {
    return sortOption.value === 'new' ? b.date - a.date : a.date - b.date;
  });
});
```

#### 해결: useTableFilter Composable

```typescript
// src/composables/useTableFilter.ts
import { ref, computed, Ref } from 'vue';

export interface FilterConfig<T> {
  searchFields?: (keyof T)[];
  sortOptions?: Record<string, (a: T, b: T) => number>;
  tabFilters?: Record<string, (item: T) => boolean>;
}

export function useTableFilter<T>(
  data: Ref<T[]>,
  config: FilterConfig<T>
) {
  // State
  const searchKeyword = ref('');
  const activeTab = ref('all');
  const sortOption = ref('default');
  const dateRange = ref({ start: '', end: '' });

  // Computed - 필터링된 데이터
  const filteredData = computed(() => {
    let result = [...data.value];

    // 탭 필터
    if (activeTab.value !== 'all' && config.tabFilters?.[activeTab.value]) {
      result = result.filter(config.tabFilters[activeTab.value]);
    }

    // 검색어 필터
    if (searchKeyword.value && config.searchFields) {
      result = result.filter(item =>
        config.searchFields!.some(field =>
          String(item[field])
            .toLowerCase()
            .includes(searchKeyword.value.toLowerCase())
        )
      );
    }

    // 정렬
    if (sortOption.value !== 'default' && config.sortOptions?.[sortOption.value]) {
      result.sort(config.sortOptions[sortOption.value]);
    }

    return result;
  });

  // 탭별 카운트
  const tabCounts = computed(() => {
    if (!config.tabFilters) return {};

    const counts: Record<string, number> = {
      all: data.value.length
    };

    Object.keys(config.tabFilters).forEach(tabKey => {
      counts[tabKey] = data.value.filter(
        config.tabFilters![tabKey]
      ).length;
    });

    return counts;
  });

  // Methods
  const setSearchKeyword = (keyword: string) => {
    searchKeyword.value = keyword;
  };

  const setActiveTab = (tab: string) => {
    activeTab.value = tab;
  };

  const setSortOption = (option: string) => {
    sortOption.value = option;
  };

  const resetFilters = () => {
    searchKeyword.value = '';
    activeTab.value = 'all';
    sortOption.value = 'default';
    dateRange.value = { start: '', end: '' };
  };

  return {
    // State
    searchKeyword,
    activeTab,
    sortOption,
    dateRange,
    // Computed
    filteredData,
    tabCounts,
    // Methods
    setSearchKeyword,
    setActiveTab,
    setSortOption,
    resetFilters
  };
}
```

#### 사용 예시: CallHistory.vue

```vue
<script setup lang="ts">
import { useTableFilter } from '@/composables/useTableFilter';
import { useCallHistoryStore } from '@/stores/modules/callHistory';

const callHistoryStore = useCallHistoryStore();

// ✅ 필터 설정
const {
  filteredData,
  tabCounts,
  activeTab,
  sortOption,
  setActiveTab,
  setSortOption
} = useTableFilter(
  computed(() => callHistoryStore.allCalls),
  {
    searchFields: ['customerName', 'phoneNumber'],
    tabFilters: {
      interest: (call) => call.isImportant,
      recent: (call) => isRecent(call.date, 7)
    },
    sortOptions: {
      new: (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime(),
      old: (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
      duration: (a, b) => parseDuration(b.duration) - parseDuration(a.duration)
    }
  }
);
</script>

<template>
  <div class="call-history">
    <!-- 탭 -->
    <el-tabs :model-value="activeTab" @update:model-value="setActiveTab">
      <el-tab-pane label="전체" name="all">
        <template #label>
          전체 ({{ tabCounts.all }})
        </template>
      </el-tab-pane>
      <el-tab-pane label="관심" name="interest">
        <template #label>
          관심 ({{ tabCounts.interest }})
        </template>
      </el-tab-pane>
    </el-tabs>

    <!-- 정렬 -->
    <el-select :model-value="sortOption" @update:model-value="setSortOption">
      <el-option label="최신순" value="new" />
      <el-option label="과거순" value="old" />
      <el-option label="통화시간순" value="duration" />
    </el-select>

    <!-- 데이터 -->
    <CallHistoryCard
      v-for="call in filteredData"
      :key="call.id"
      :call="call"
    />
  </div>
</template>
```

### 6.2 공통 Composable: useModalState

#### 문제: Modal 상태 관리 중복

```typescript
// 모든 컴포넌트에서 반복
const showModal = ref(false);
const openModal = () => { showModal.value = true; };
const closeModal = () => { showModal.value = false; };
```

#### 해결: useModalState Composable

```typescript
// src/composables/useModalState.ts
import { ref } from 'vue';

export interface UseModalOptions {
  onOpen?: () => void;
  onClose?: () => void;
  onConfirm?: () => void | Promise<void>;
  closeOnConfirm?: boolean;
}

export function useModalState(options: UseModalOptions = {}) {
  const isVisible = ref(false);
  const isLoading = ref(false);

  const open = () => {
    isVisible.value = true;
    options.onOpen?.();
  };

  const close = () => {
    isVisible.value = false;
    options.onClose?.();
  };

  const confirm = async () => {
    if (!options.onConfirm) {
      close();
      return;
    }

    try {
      isLoading.value = true;
      await options.onConfirm();

      if (options.closeOnConfirm !== false) {
        close();
      }
    } catch (error) {
      console.error('Modal confirm 실패:', error);
      throw error;
    } finally {
      isLoading.value = false;
    }
  };

  return {
    isVisible,
    isLoading,
    open,
    close,
    confirm
  };
}
```

#### 사용 예시

```vue
<script setup lang="ts">
import { useModalState } from '@/composables/useModalState';
import { useTodoListStore } from '@/stores/modules/todoList';

const todoStore = useTodoListStore();

// ✅ Modal 상태 관리
const {
  isVisible: showTodoModal,
  isLoading: isTodoSaving,
  open: openTodoModal,
  close: closeTodoModal,
  confirm: saveTodo
} = useModalState({
  onConfirm: async () => {
    await todoStore.createTodo(todoForm.value);
  },
  closeOnConfirm: true
});
</script>

<template>
  <ECPButton @click="openTodoModal">할일 추가</ECPButton>

  <ElDialog :visible="showTodoModal" @close="closeTodoModal">
    <template #header>할일 추가</template>

    <!-- 폼 필드들 -->

    <template #footer>
      <ECPButton @click="closeTodoModal">취소</ECPButton>
      <ECPButton
        type="primary"
        :loading="isTodoSaving"
        @click="saveTodo"
      >
        저장
      </ECPButton>
    </template>
  </ElDialog>
</template>
```

### 6.3 공통 Composable: useAsyncOperation

#### 문제: 비동기 처리 패턴 중복

```typescript
// 모든 비동기 작업에서 반복
const loading = ref(false);
const handleAsync = async () => {
  loading.value = true;
  try {
    await someAsyncOperation();
    showSuccessMessage();
  } catch (error) {
    showErrorMessage();
  } finally {
    loading.value = false;
  }
};
```

#### 해결: useAsyncOperation Composable

```typescript
// src/composables/useAsyncOperation.ts
import { ref } from 'vue';
import { showCustomMessage } from '@/utils/messageUtils';

export interface UseAsyncOptions {
  loadingMessage?: string;
  successMessage?: string;
  errorMessage?: string;
  showLoading?: boolean;
  showSuccess?: boolean;
  showError?: boolean;
  onSuccess?: (result: any) => void;
  onError?: (error: any) => void;
}

export function useAsyncOperation<T = any>(
  asyncFn: (...args: any[]) => Promise<T>,
  options: UseAsyncOptions = {}
) {
  const isLoading = ref(false);
  const error = ref<Error | null>(null);
  const data = ref<T | null>(null);

  const execute = async (...args: any[]): Promise<T | null> => {
    isLoading.value = true;
    error.value = null;

    try {
      // 로딩 메시지
      if (options.showLoading && options.loadingMessage) {
        showCustomMessage({
          message: options.loadingMessage,
          type: 'info',
          duration: 0,
          category: 'Loading'
        });
      }

      // 비동기 작업 실행
      const result = await asyncFn(...args);
      data.value = result;

      // 성공 콜백
      options.onSuccess?.(result);

      // 성공 메시지
      if (options.showSuccess !== false && options.successMessage) {
        showCustomMessage({
          message: options.successMessage,
          type: 'success',
          duration: 3000,
          category: 'Success'
        });
      }

      return result;
    } catch (err: any) {
      error.value = err;

      // 에러 콜백
      options.onError?.(err);

      // 에러 메시지
      if (options.showError !== false) {
        showCustomMessage({
          message: options.errorMessage || err.message || '작업 실패',
          type: 'error',
          duration: 3000,
          category: 'Error'
        });
      }

      return null;
    } finally {
      isLoading.value = false;
    }
  };

  const reset = () => {
    isLoading.value = false;
    error.value = null;
    data.value = null;
  };

  return {
    isLoading,
    error,
    data,
    execute,
    reset
  };
}
```

#### 사용 예시

```vue
<script setup lang="ts">
import { useAsyncOperation } from '@/composables/useAsyncOperation';
import { useBookmarkStore } from '@/stores/modules/bookmark';

const bookmarkStore = useBookmarkStore();

// ✅ 북마크 생성
const {
  isLoading: isCreating,
  execute: createBookmark
} = useAsyncOperation(
  (data: BookmarkData) => bookmarkStore.createBookmark(data),
  {
    successMessage: '북마크가 추가되었습니다.',
    errorMessage: '북마크 추가에 실패했습니다.',
    onSuccess: () => {
      formData.value = {};
      closeModal();
    }
  }
);

// ✅ 북마크 삭제
const {
  isLoading: isDeleting,
  execute: deleteBookmark
} = useAsyncOperation(
  (id: string) => bookmarkStore.deleteBookmark(id),
  {
    successMessage: '북마크가 삭제되었습니다.',
    errorMessage: '북마크 삭제에 실패했습니다.'
  }
);
</script>

<template>
  <ECPButton
    :loading="isCreating"
    @click="createBookmark(formData)"
  >
    추가
  </ECPButton>

  <ECPButton
    :loading="isDeleting"
    @click="deleteBookmark(bookmark.id)"
  >
    삭제
  </ECPButton>
</template>
```

### 6.4 Store 정리

#### Store Actions에서 API 호출 통일

**원칙:**
```
✅ 모든 API 호출은 Store Actions에서
✅ Component는 Store Actions만 호출
✅ Composable은 Store를 래핑
```

**예시: BookmarkStore 개선**

```typescript
// src/stores/modules/bookmark.ts
import { defineStore } from 'pinia';
import { getClient } from '@/api/apiPlugin';

export const useBookmarkStore = defineStore('bookmark', () => {
  // State
  const groups = ref<BookmarkGroup[]>([]);
  const list = ref<BookmarkItem[]>([]);
  const isLoading = ref(false);
  const error = ref<Error | null>(null);

  // ===== API Actions =====

  const fetchGroups = async () => {
    try {
      isLoading.value = true;
      const advisorApi = getClient('advisor');

      const response = await advisorApi.get('/api/asst/v1/bookmark-groups');
      groups.value = response.data;

      return response.data;
    } catch (err: any) {
      error.value = err;
      throw err;
    } finally {
      isLoading.value = false;
    }
  };

  const createGroup = async (title: string) => {
    try {
      isLoading.value = true;
      const advisorApi = getClient('advisor');

      const response = await advisorApi.post('/api/asst/v1/bookmark-groups', {
        title
      });

      // 로컬 State 업데이트
      groups.value.push(response.data);

      return response.data;
    } catch (err: any) {
      error.value = err;
      throw err;
    } finally {
      isLoading.value = false;
    }
  };

  const updateGroup = async (groupId: string, title: string) => {
    try {
      isLoading.value = true;
      const advisorApi = getClient('advisor');

      const response = await advisorApi.put(
        `/api/asst/v1/bookmark-groups/${groupId}`,
        { title }
      );

      // 로컬 State 업데이트
      const index = groups.value.findIndex(g => g.id === groupId);
      if (index !== -1) {
        groups.value[index] = response.data;
      }

      return response.data;
    } catch (err: any) {
      error.value = err;
      throw err;
    } finally {
      isLoading.value = false;
    }
  };

  const deleteGroup = async (groupId: string) => {
    try {
      isLoading.value = true;
      const advisorApi = getClient('advisor');

      await advisorApi.delete(`/api/asst/v1/bookmark-groups/${groupId}`);

      // 로컬 State 업데이트
      groups.value = groups.value.filter(g => g.id !== groupId);

      // 해당 그룹의 북마크들도 삭제
      list.value = list.value.filter(
        b => b.bookmark_groups_id !== groupId
      );
    } catch (err: any) {
      error.value = err;
      throw err;
    } finally {
      isLoading.value = false;
    }
  };

  // Bookmarks CRUD (동일 패턴)

  return {
    // State
    groups,
    list,
    isLoading,
    error,
    // Actions
    fetchGroups,
    createGroup,
    updateGroup,
    deleteGroup
  };
});
```

### 6.5 마이그레이션 일정

```
Week 3-4: 공통 Composables + Store 정리

Day 1-5:
  ✅ chatData Store에 API Actions 추가
  ✅ Component의 직접 API 호출 → Store로 이동
  ✅ useTableFilter 작성 및 적용

Day 6-10:
  ✅ useModalState 작성 및 적용
  ✅ useAsyncOperation 작성 및 적용
  ✅ 주요 Component에 적용 (CallHistory, Bookmark, Memo)

Day 11-14:
  ✅ 통합 테스트
  ✅ 문서화
```

---

## 7. Phase 3: 장기 개선

### 7.1 레거시 API 클라이언트 통일

**현재:**
```
⚠️ request.ts (레거시) + apiPlugin.ts (모던) 혼재
```

**목표:**
```
✅ apiPlugin.ts로 통일
✅ 단계적 마이그레이션
```

### 7.2 TypeScript 타입 강화

**현재:**
```typescript
// ❌ any 남용
const data: any = response.data;
const items: any[] = [];
```

**개선:**
```typescript
// ✅ 명확한 타입
interface BookmarkItem {
  id: string;
  title: string;
  url: string;
  bookmark_groups_id: string;
  created_at: string;
}

const items: BookmarkItem[] = [];
```

### 7.3 테스트 커버리지

**목표:**
```
✅ Unit Test: Composables, Store Actions
✅ Component Test: Vue Testing Library
✅ E2E Test: Playwright
✅ 커버리지: 60% 이상
```

---

## 8. 마이그레이션 체크리스트

### Phase 1 완료 기준

```
□ chat/index.vue 분할 완료
  □ ChatView.vue (500줄 이하)
  □ ChatMessageList.vue
  □ ChatFilterPopover.vue
  □ ChatClippingPanel.vue
  □ ChatRecommendTags.vue
  □ ChatTodoModal.vue
  □ useChatFilter.ts
  □ useChatKeyword.ts
  □ useChatClipping.ts

□ API 호출 중앙화
  □ chatData Store에 API Actions 추가
  □ Component에서 직접 API 호출 제거
  □ useChatChannel Composable 작성

□ 회귀 테스트 통과
```

### Phase 2 완료 기준

```
□ 공통 Composables 작성
  □ useTableFilter
  □ useModalState
  □ useAsyncOperation

□ Composables 적용
  □ CallHistory.vue
  □ Bookmark.vue
  □ Memo.vue
  □ Notice.vue
  □ AdminCoaching.vue

□ Store 정리
  □ bookmark Store API Actions 완성
  □ memo Store API Actions 완성
  □ notice Store API Actions 완성

□ 코드 중복 80% 감소
```

### Phase 3 완료 기준

```
□ 레거시 제거
  □ request.ts → apiPlugin.ts 마이그레이션

□ 타입 강화
  □ any 사용 최소화
  □ 인터페이스 정의

□ 테스트 추가
  □ Unit Test 작성
  □ Component Test 작성
  □ E2E Test 작성
  □ 커버리지 60% 달성
```

### 최종 목표

```
✅ 단일 파일 최대 줄 수: 500줄 이하
✅ Component Props: 10개 이하
✅ API 호출: Store/Composable에서만
✅ 코드 중복: 80% 감소
✅ 테스트 커버리지: 60% 이상
✅ 유지보수성: 크게 개선
```

---

## 8. 추가 리소스

### 참고 문서

- Vue 3 Composition API: https://vuejs.org/guide/extras/composition-api-faq.html
- Pinia: https://pinia.vuejs.org/
- Vue Testing Library: https://testing-library.com/docs/vue-testing-library/intro

### 관련 파일

- `src/api/apiPlugin.ts` - API 클라이언트
- `src/stores/modules/chatData.ts` - Chat 데이터 Store
- `src/composables/useAdvisorbot.ts` - Composable 예시
- `src/view/advisor/components/chat/index.vue` - 리팩토링 대상

---

**문서 버전:** 1.0
**최종 수정:** 2026-01-02
**담당자:** Development Team
