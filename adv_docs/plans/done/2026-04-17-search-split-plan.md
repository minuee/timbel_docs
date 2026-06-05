# 문서 검색 keyword/hybrid 분리 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 단일 hybrid 검색을 keyword/hybrid 병렬 요청으로 분리하여, keyword 결과(문서)를 먼저 표시하고 hybrid 결과(요약)를 비동기 로딩한다.

**Architecture:** 프론트엔드에서 동일 엔드포인트에 `mode: 'keyword'`와 `mode: 'hybrid'`를 각각 fire-and-forget으로 호출. 백엔드는 DTO로 mode를 받아 검색엔진 파라미터를 분기. 지식정보 패널은 keyword 결과를 즉시 렌더링하고, hybrid 응답 도착 시 search_summary를 머지.

**Tech Stack:** NestJS 11, TypeScript, class-validator, Vue 3, Composition API

**Design Doc:** `docs/plans/2026-04-17-search-split-design.md`

---

## Task 1: 백엔드 — DTO에 mode 필드 추가

**Files:**
- Modify: `asst-service/src/advisor/search/dto/search-request.dto.ts`

**Step 1: mode 필드 추가**

`asst-service/src/advisor/search/dto/search-request.dto.ts` — `SearchRequestDto` 클래스에 `mode` 필드 추가:

```typescript
import { IsIn } from 'class-validator';  // 기존 import 라인에 추가

// callId 필드 아래에 추가:
@ApiPropertyOptional({ description: '검색 모드', enum: ['hybrid', 'keyword'], default: 'hybrid' })
@IsOptional()
@IsIn(['hybrid', 'keyword'])
mode?: 'hybrid' | 'keyword';
```

**Step 2: 빌드 확인**

```bash
cd asst-service && npm run build
```
Expected: 성공

**Step 3: 커밋**

```bash
git add asst-service/src/advisor/search/dto/search-request.dto.ts
git commit -m "feat: 검색 DTO에 mode 필드 추가 (hybrid/keyword)"
```

---

## Task 2: 백엔드 — SearchService mode 분기 처리

**Files:**
- Modify: `asst-service/src/advisor/search/services/search.service.ts`
- Modify: `asst-service/src/advisor/search/constants/search.constants.ts`

**Step 1: 상수 파일에 keyword 모드 기본값 추가**

`asst-service/src/advisor/search/constants/search.constants.ts` — `SEARCH_DEFAULTS` 아래에 추가:

```typescript
export const KEYWORD_OVERRIDES = {
  MODE: 'keyword',
  ENABLE_RERANK: false,
  USE_HYDE: false,
  USE_FALLBACK: false,
  ENABLE_LLM_REWRITE: false,
} as const;
```

**Step 2: SearchService에서 mode에 따라 payload 분기**

`asst-service/src/advisor/search/services/search.service.ts` — `search` 메서드의 payload 구성 부분 수정.

기존 (lines 32-48):
```typescript
const payload = {
  query: dto.query,
  repository_id: this.repositoryId,
  document_type_ids: this.documentTypeIds,
  mode: SEARCH_DEFAULTS.MODE,
  top_k: SEARCH_DEFAULTS.TOP_K,
  enable_rerank: SEARCH_DEFAULTS.ENABLE_RERANK,
  use_hyde: SEARCH_DEFAULTS.USE_HYDE,
  use_fallback: SEARCH_DEFAULTS.USE_FALLBACK,
  enable_llm_rewrite: SEARCH_DEFAULTS.ENABLE_LLM_REWRITE,
  with_answer: SEARCH_DEFAULTS.WITH_ANSWER,
  distill: SEARCH_DEFAULTS.DISTILL,
  conversation_history: ...
};
```

변경:
```typescript
import { KEYWORD_OVERRIDES, SEARCH_DEFAULTS } from '@app/advisor/search/constants/search.constants';

// search 메서드 내부:
const isKeyword = dto.mode === 'keyword';

const payload = {
  query: dto.query,
  repository_id: this.repositoryId,
  document_type_ids: this.documentTypeIds,
  mode: isKeyword ? KEYWORD_OVERRIDES.MODE : SEARCH_DEFAULTS.MODE,
  top_k: SEARCH_DEFAULTS.TOP_K,
  enable_rerank: isKeyword ? KEYWORD_OVERRIDES.ENABLE_RERANK : SEARCH_DEFAULTS.ENABLE_RERANK,
  use_hyde: isKeyword ? KEYWORD_OVERRIDES.USE_HYDE : SEARCH_DEFAULTS.USE_HYDE,
  use_fallback: isKeyword ? KEYWORD_OVERRIDES.USE_FALLBACK : SEARCH_DEFAULTS.USE_FALLBACK,
  enable_llm_rewrite: isKeyword ? KEYWORD_OVERRIDES.ENABLE_LLM_REWRITE : SEARCH_DEFAULTS.ENABLE_LLM_REWRITE,
  with_answer: SEARCH_DEFAULTS.WITH_ANSWER,
  distill: SEARCH_DEFAULTS.DISTILL,
  conversation_history: (dto.conversationHistory ?? []).map((item) => ({
    role: item.speaker === 'customer' ? 'user' : 'assistant',
    content: item.content,
  })),
};
```

로그에도 mode 추가:
```typescript
this.logger.debug(`검색 요청: query="${dto.query}", mode=${dto.mode || 'hybrid'}, callId=${dto.callId || 'N/A'}`);
```

**Step 3: 빌드 + 린트**

```bash
cd asst-service && npm run build && npm run lint
```
Expected: 성공

**Step 4: 커밋**

```bash
git add asst-service/src/advisor/search/constants/search.constants.ts \
       asst-service/src/advisor/search/services/search.service.ts
git commit -m "feat: SearchService에서 mode별 검색엔진 파라미터 분기"
```

---

## Task 3: 프론트엔드 — 타입에 mode 추가

**Files:**
- Modify: `asst-web/src/api/types/ce.type.ts:89-93`

**Step 1: DocumentSearchReq에 mode 추가**

```typescript
export interface DocumentSearchReq {
  query: string;
  conversationHistory?: DocumentSearchConversationItem[];
  callId?: string;
  mode?: 'hybrid' | 'keyword';  // 추가
}
```

**Step 2: 커밋**

```bash
git add asst-web/src/api/types/ce.type.ts
git commit -m "feat: DocumentSearchReq 타입에 mode 필드 추가"
```

---

## Task 4: 프론트엔드 — handleDocumentSearch를 keyword/hybrid로 분리

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: summaryLoading 상태 추가**

`<script setup>` 내 기존 reactive 변수 선언 영역에 추가:
```typescript
const summaryLoading = ref<Record<string, boolean>>({});
```

**Step 2: 기존 handleDocumentSearch를 handleKeywordSearch로 리네임 + mode 전달**

기존 `handleDocumentSearch` (lines 1993-2152)를 `handleKeywordSearch`로 변경하고, API 호출 시 `mode: 'keyword'` 추가:

```typescript
const handleKeywordSearch = async (query: string, messageId: string) => {
  // 대화 이력 추출 로직은 기존과 동일 (lines 1994-2025)
  // ...

  try {
    const payload = {
      query,
      conversationHistory,
      mode: 'keyword' as const,  // keyword 모드 지정
    };

    const response = await DocumentSearchAPI.instance.searchDocuments(payload);
    // 기존 결과 처리 로직 동일 (hint 그루핑, keywordDetailData 저장 등)
    // 단, search_summary 관련 데이터는 빈 문자열로 유지 (hybrid에서 채워짐)
    // ...
  } catch (error) {
    console.error("[CHAT] keyword 검색 오류:", error);
  }
};
```

**Step 3: handleHybridSearch 함수 추가**

`handleKeywordSearch` 바로 아래에 추가:

```typescript
const handleHybridSearch = async (query: string, messageId: string) => {
  summaryLoading.value[messageId] = true;

  // 대화 이력 추출 (handleKeywordSearch와 동일 로직)
  const conversationHistory: { speaker: "customer" | "agent"; content: string }[] = [];
  const currentMessages = chatContent.value;

  let lastAgent: { speaker: "agent"; content: string } | null = null;
  let lastCustomer: { speaker: "customer"; content: string } | null = null;

  for (let i = currentMessages.length - 1; i >= 0; i--) {
    const msg = currentMessages[i];
    if (String(msg.id) === messageId) continue;
    if (!lastAgent && msg.sender === "consultant") {
      lastAgent = { speaker: "agent", content: msg.content };
    }
    if (!lastCustomer && msg.sender === "user") {
      lastCustomer = { speaker: "customer", content: msg.content };
    }
    if (lastAgent && lastCustomer) break;
  }

  if (lastCustomer) conversationHistory.push(lastCustomer);
  if (lastAgent) conversationHistory.push(lastAgent);
  conversationHistory.sort((a, b) => {
    const aIdx = currentMessages.findIndex(
      m => m.content === a.content && (a.speaker === "customer" ? m.sender === "user" : m.sender === "consultant")
    );
    const bIdx = currentMessages.findIndex(
      m => m.content === b.content && (b.speaker === "customer" ? m.sender === "user" : m.sender === "consultant")
    );
    return aIdx - bIdx;
  });

  try {
    const payload = {
      query,
      conversationHistory,
      mode: 'hybrid' as const,
    };

    const response = await DocumentSearchAPI.instance.searchDocuments(payload);

    if (response?.status >= 200 && response?.status < 300 && response.data?.results?.length > 0) {
      const results = response.data.results;

      // 기존 keywordDetailData에 search_summary를 머지
      const existingData = keywordDetailData.value[messageId];
      if (existingData?.[0]?.content) {
        for (const existingItem of existingData[0].content) {
          // document_id가 일치하는 hybrid 결과에서 search_summary를 가져옴
          const matchingResult = results.find(
            (r: any) => r.document_id === existingItem.data?.document_id
          );
          if (matchingResult?.metadata?.search_summary) {
            existingItem.data.search_summary = matchingResult.metadata.search_summary;
          }
        }

        // document_id 매칭이 안 된 경우, 첫 번째 결과의 search_summary를 첫 번째 아이템에 적용
        if (existingData[0].content.length > 0 && !existingData[0].content[0].data?.search_summary) {
          const firstSummary = results.find((r: any) => r.metadata?.search_summary);
          if (firstSummary) {
            existingData[0].content[0].data.search_summary = firstSummary.metadata.search_summary;
          }
        }
      }
    }
  } catch (error) {
    console.error("[CHAT] hybrid 검색 오류:", error);
  } finally {
    summaryLoading.value[messageId] = false;
  }
};
```

**Step 4: 호출부 수정**

기존 (line 1542-1544):
```typescript
// 새 문서 검색 (고객 발화 시 검색엔진 호출)
if (isUser) {
  handleDocumentSearch(messageData.origin_text, String(newMsg.id));
}
```

변경:
```typescript
// 문서 검색 — keyword(빠름) + hybrid(요약) 병렬 호출
if (isUser) {
  handleKeywordSearch(messageData.origin_text, String(newMsg.id));
  handleHybridSearch(messageData.origin_text, String(newMsg.id));
}
```

**Step 5: summaryLoading을 expose 또는 emit으로 지식정보 패널에 전달**

`chat/index.vue`의 `defineExpose` 또는 부모 컴포넌트를 통해 `summaryLoading`을 `TabTypeKnowledgeIndex`에 전달해야 한다. 현재 데이터 전달 경로를 확인하여 가장 적합한 방법을 선택:
- `keywordDetailData`가 이미 reactive로 공유되고 있다면, `summaryLoading`도 같은 방식으로 전달
- 또는 `keywordDetailData`의 각 아이템에 `_summaryLoading: boolean` 플래그를 직접 포함

간단한 방법: `keywordDetailData[messageId]`의 첫 번째 그룹에 `summaryLoading` 플래그를 포함:
```typescript
// handleKeywordSearch에서 keywordDetailData 저장 시:
keywordDetailData.value[messageId] = [
  {
    type: "지식정보",
    content: allItems,
    summaryLoading: true,  // hybrid 로딩 중 표시
  }
];

// handleHybridSearch 완료 시:
if (existingData?.[0]) {
  existingData[0].summaryLoading = false;
}
```

**Step 6: 린트**

```bash
cd asst-web && npm run lint
```

**Step 7: 커밋**

```bash
git add asst-web/src/view/advisor/components/chat/index.vue
git commit -m "feat: 문서 검색을 keyword/hybrid 병렬 호출로 분리"
```

---

## Task 5: 프론트엔드 — 지식정보 패널에 로딩 스피너 추가

**Files:**
- Modify: `asst-web/src/view/advisor/components/knowledge/TabTypeKnowledgeIndex.vue`

**Step 1: 검색 요약 영역에 로딩 스피너 조건 추가**

기존 (line 148-158):
```html
<!-- 검색 요약 -->
<div
  v-if="allSelectedItems[activeTabInfo.chatIndex].data?.search_summary"
  class="search-summary-section flex gap8 p12 border-radius8"
  style="background-color: var(--color-bg-info, #f0f7ff);"
>
  <ECPIcon icon="auto_awesome" filled color="primary" size="small" style="flex-shrink: 0; margin-top: 2px;" />
  <ECPTypography variant="body3" color="g80" :style="{ whiteSpace: 'pre-line', lineHeight: '160%' }">
    {{ allSelectedItems[activeTabInfo.chatIndex].data.search_summary }}
  </ECPTypography>
</div>
```

변경 — `v-if`에 로딩 상태도 포함:
```html
<!-- 검색 요약 (로딩 중 또는 결과 표시) -->
<div
  v-if="activeTabInfo.summaryLoading || allSelectedItems[activeTabInfo.chatIndex]?.data?.search_summary"
  class="search-summary-section flex gap8 p12 border-radius8"
  style="background-color: var(--color-bg-info, #f0f7ff);"
>
  <!-- 로딩 스피너 -->
  <template v-if="activeTabInfo.summaryLoading">
    <ECPIcon icon="auto_awesome" filled color="primary" size="small" style="flex-shrink: 0; margin-top: 2px;" />
    <div class="flx-align-center gap8">
      <div class="summary-spinner"></div>
      <ECPTypography variant="body3" color="g60">
        요약 정보를 불러오는 중...
      </ECPTypography>
    </div>
  </template>
  <!-- 요약 결과 -->
  <template v-else>
    <ECPIcon icon="auto_awesome" filled color="primary" size="small" style="flex-shrink: 0; margin-top: 2px;" />
    <ECPTypography variant="body3" color="g80" :style="{ whiteSpace: 'pre-line', lineHeight: '160%' }">
      {{ allSelectedItems[activeTabInfo.chatIndex].data.search_summary }}
    </ECPTypography>
  </template>
</div>
```

**Step 2: `activeTabInfo` computed에서 summaryLoading 접근**

`activeTabInfo`가 현재 탭의 `keywordDetailData`를 참조하는 computed라면, 해당 데이터의 `summaryLoading` 플래그를 읽어오도록 확인. Task 4에서 `keywordDetailData[messageId][0].summaryLoading`에 값을 넣었으므로, 이 값을 `activeTabInfo`에서 접근할 수 있어야 한다.

**Step 3: 스피너 CSS 추가**

`<style>` 섹션에 추가:
```css
.summary-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-border-default, #e0e0e0);
  border-top-color: var(--color-primary, #1976d2);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
```

**Step 4: 린트**

```bash
cd asst-web && npm run lint
```

**Step 5: 커밋**

```bash
git add asst-web/src/view/advisor/components/knowledge/TabTypeKnowledgeIndex.vue
git commit -m "feat: 지식정보 패널에 요약 로딩 스피너 추가"
```

---

## Task 6: 검증

**Step 1: 백엔드 빌드**

```bash
cd asst-service && npm run build
```
Expected: 성공

**Step 2: 프론트엔드 빌드**

```bash
cd asst-web && npm run build:dev
```
Expected: 성공

**Step 3: 통합 확인 (수동)**

1. 개발 서버 실행 (`npm run start:dev` + `npm run dev`)
2. 통화 시작 → 고객 발화 수신
3. 확인사항:
   - 네트워크 탭에서 `/search` 요청 2건 발생 (keyword, hybrid)
   - keyword 응답이 먼저 도착하면 문서 목록이 즉시 표시됨
   - 요약 영역에 스피너가 표시됨
   - hybrid 응답 도착 후 스피너가 search_summary 텍스트로 교체됨

**Step 4: 최종 커밋 (필요 시)**

빌드/린트 오류 수정 후 추가 커밋.
