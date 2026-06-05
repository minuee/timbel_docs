# STT Partial 스트리밍 실시간 발화 표시 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `nlp:partial` Redis 채널을 구독해 발화 중 실시간 텍스트 스트리밍을 버블로 표시하고, `nlp:complete` 도착 시 NLP 데이터와 함께 확정한다. 상담사·고객이 동시에 발화하더라도 각자의 버블이 독립적으로 표시된다.

**Architecture:** `nlp:partial` 메시지는 발화자(speaker)별로 하나씩 "스트리밍 버블"을 `chatContent`에 유지하며 `origin_text`가 올 때마다 업데이트한다. `nlp:complete` 도착 시 동일 `turn_idx`의 스트리밍 버블을 찾아 NLP 데이터로 확정(`isStreaming: false`)한다. 스트리밍 버블이 없으면 기존 방식대로 신규 버블을 생성한다(하위 호환).

**Tech Stack:** TypeScript, Vue 3, Vitest, Vue Composition API (ref, computed). 변경 대상은 프론트엔드(`asst-web`)만이며 백엔드 수정 없음.

**Redis 채널 스펙 (문서 기준):**
- `{env}:{tenant_id}:{agent_id}:call:nlp:partial` — 스트리밍 중 발화. `masked_text: ""`, `nlp: null`, `origin_text`: 누적 텍스트
- `{env}:{tenant_id}:{agent_id}:call:nlp:complete` — 발화 확정. `masked_text` 마스킹 완료, `nlp` 객체 포함
- 두 채널 모두 동일 `turn_idx` 공유 (같은 발화 단위)

---

## Task 1: redisKey.ts — "partial" 채널 키 추가

**Files:**
- Modify: `asst-web/src/utils/redisKey.ts`

**Step 1: "partial" case 추가**

`case "db":` 앞에 삽입:

```typescript
case "partial":
  return `${environment}:${tenantId}:${agentId}:call:nlp:partial`;
```

최종 파일:
```typescript
export const getRedisKey = (tenantId: string, agentId: string, serviceName: any) => {
  const environment = "dev";

  switch (serviceName) {
    case "nlp":
      return `${environment}:${tenantId}:${agentId}:call:nlp:complete`;
    case "partial":
      return `${environment}:${tenantId}:${agentId}:call:nlp:partial`;
    case "events":
      return `${environment}:${tenantId}:${agentId}:call:events`;
    case "db":
      return `${environment}:${tenantId}:${agentId}:call:orchestrator:persisted`;
    default:
      return `Unknown`;
  }
};
```

**Step 2: 타입체크**

```bash
cd asst-web && npx tsc --noEmit
```

Expected: 오류 없음

**Step 3: Commit**

```bash
git add asst-web/src/utils/redisKey.ts
git commit -m "feat: nlp:partial Redis 채널 키 추가"
```

---

## Task 2: index.vue — updateChatMessage 함수 추가

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: addChatMessage 이후(1286줄)에 updateChatMessage 추가**

`addChatMessage` 함수(line 1257~1286) 바로 뒤에 삽입:

```typescript
const updateChatMessage = (id: number, updates: Record<string, unknown>) => {
  const idx = chatContent.value.findIndex((m: unknown) => (m as Record<string, unknown>).id === id);
  if (idx !== -1) {
    chatContent.value[idx] = { ...(chatContent.value[idx] as Record<string, unknown>), ...updates };
    updateFilteredContent();
  }
};
```

**Step 2: 타입체크**

```bash
cd asst-web && npx tsc --noEmit
```

Expected: 오류 없음

---

## Task 3: SpeechBubble.vue — isStreaming prop + 커서 UI

**Files:**
- Modify: `asst-web/src/view/advisor/components/SpeechBubble.vue`

**Step 1: defineProps에 isStreaming 추가**

`isSearchQueryLoading?: boolean;` (line 243) 뒤에 추가:

```typescript
isStreaming?: boolean;
```

**Step 2: 스트리밍 커서 엘리먼트 추가**

`</span>` (line 73, span :style 닫는 태그) 안, `<!-- 클리핑 추가 버튼 -->` 앞에 커서 span 삽입:

```html
        <!-- 스트리밍 중 깜빡이는 커서 -->
        <span v-if="props.isStreaming" class="streaming-cursor" aria-hidden="true" />
```

즉 line 73~75 사이:
```html
        </span>

        <!-- 스트리밍 중 깜빡이는 커서 -->
        <span v-if="props.isStreaming" class="streaming-cursor" aria-hidden="true" />

        <!-- 클리핑 추가 버튼 (chat-bubble-message 기준) -->
        <ECPButton
```

**Step 3: CSS 애니메이션 추가**

`<style>` 섹션 안에 추가:

```css
.streaming-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  background-color: currentColor;
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: cursor-blink 1s step-end infinite;
}

@keyframes cursor-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}
```

**Step 4: index.vue의 SpeechBubble 사용부에 isStreaming prop 전달**

`index.vue` line 263~291의 `<SpeechBubble ...>` 안에 추가:

```html
:isStreaming="item.isStreaming || false"
```

위치: `:hasSearchQuery="item.hasSearchQuery"` 줄 뒤

**Step 5: 타입체크**

```bash
cd asst-web && npx tsc --noEmit
```

**Step 6: Commit**

```bash
git add asst-web/src/view/advisor/components/SpeechBubble.vue
git add asst-web/src/view/advisor/components/chat/index.vue
git commit -m "feat: SpeechBubble isStreaming prop 및 커서 UI 추가"
```

---

## Task 4: useChatMessageParser.ts — 인터페이스에 updateChatMessage 추가

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts`

**Step 1: UseChatMessageParserParams 인터페이스 수정**

`addChatMessage` 줄(line 30) 뒤에 추가:

```typescript
updateChatMessage: (id: number, updates: Record<string, unknown>) => void;
```

**Step 2: 구조분해 할당에 updateChatMessage 추가**

`params` 구조분해(line 37~57) 안에 추가:

```typescript
updateChatMessage,
```

(`addChatMessage,` 줄 뒤)

**Step 3: index.vue useChatMessageParser 호출부에 전달**

`index.vue` line 1395(`addChatMessage: ...`) 뒤에 추가:

```typescript
updateChatMessage: (id: number, updates: Record<string, unknown>) => updateChatMessage(id, updates),
```

**Step 4: 타입체크**

```bash
cd asst-web && npx tsc --noEmit
```

Expected: 오류 없음

---

## Task 5: useChatMessageParser.ts — streamingBySpeaker 상태 + nlp:partial 핸들러

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts`

**Step 1: streamingBySpeaker 상태 추가**

`parseMessageData` 함수(line 64) 바로 위에 삽입:

```typescript
type StreamingState = { id: number; turnIdx: number } | null;
const streamingBySpeaker: Record<"user" | "consultant", StreamingState> = {
  user: null,
  consultant: null,
};
```

**Step 2: nlp:partial 채널 핸들러 추가**

`} else if (raw.message.channel.includes("stt:final")) {` 블록(line 183~184) 뒤에, `} else if (raw.message.channel.includes("nlp:complete")) {` 앞에 삽입:

```typescript
} else if (raw.message.channel.includes("nlp:partial")) {
  const isUser = messageData.speaker === "customer";
  const sender = isUser ? "user" : "consultant";
  const turnIdx = messageData.turn_idx as number;
  const existing = streamingBySpeaker[sender];

  if (existing && existing.turnIdx === turnIdx) {
    // 동일 turn_idx → 기존 버블 텍스트 업데이트
    updateChatMessage(existing.id, { content: messageData.origin_text });
  } else {
    // 새로운 발화 시작 (또는 turn_idx 변경)
    if (existing) {
      // 이전 스트리밍 버블 강제 확정
      updateChatMessage(existing.id, { isStreaming: false });
    }
    const newMsg = addChatMessage({
      content: messageData.origin_text,
      sender,
      time: new Date(raw.timestamp.trim()).toLocaleTimeString("ko-KR", {
        hour12: true,
        hour: "2-digit",
        minute: "2-digit",
      }),
      isStreaming: true,
      turnIdx,
      highlightKeywords: [],
      intentId: "",
      customerUtterance: "",
      nlpData: null,
      hasSearchQuery: false,
    });
    streamingBySpeaker[sender] = { id: newMsg.id, turnIdx };
  }

  if (!showScrollToBottomButton.value) {
    scrollToBottom();
  }
```

**Step 3: 타입체크**

```bash
cd asst-web && npx tsc --noEmit
```

Expected: 오류 없음

---

## Task 6: useChatMessageParser.ts — nlp:complete 핸들러 수정 (streaming 버블 확정 처리)

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts`

**현재 코드 (line 226~229):**
```typescript
const turnIdx = messageData.turn_idx as number | undefined;
if (turnIdx !== undefined && chatContent.value.some((msg: unknown) => (msg as Record<string, unknown>).turnIdx === turnIdx)) {
  return;
}
```

**Step 1: 위 블록을 아래로 교체 (nlp:complete 핸들러 내부)**

`const intentId = nlp?.intent?.[0]?.intent;` (line 221) 뒤부터 `const newMsg = addChatMessage({` (line 231) 이전까지를 다음으로 교체:

```typescript
const isUser = messageData.speaker === "customer";
const hasValidIntent = intents.length > 0;
const hasNlpKeywords = Array.isArray(nlp?.keywords) && (nlp?.keywords?.length ?? 0) > 0;
const intentId = nlp?.intent?.[0]?.intent;
const turnIdx = messageData.turn_idx as number | undefined;
const sender = isUser ? "user" : "consultant";
const streamingState = streamingBySpeaker[sender];

// Case 1: 동일 turn_idx 스트리밍 버블이 있으면 확정
if (streamingState && turnIdx !== undefined && streamingState.turnIdx === turnIdx) {
  updateChatMessage(streamingState.id, {
    content: messageData.origin_text,
    isStreaming: false,
    intentId: intentId || "",
    customerUtterance: messageData.origin_text || "",
    nlpData: nlp || null,
    hasSearchQuery: isUser && !hasValidIntent && hasNlpKeywords,
  });
  streamingBySpeaker[sender] = null;

  if (isUser) {
    const msgTurnIdx = typeof messageData.turn_idx === "number" ? messageData.turn_idx : null;
    const customerQuery = (messageData.masked_text ?? messageData.origin_text ?? "") as string;
    handleAssistStream(messageData.origin_text as string, String(streamingState.id), msgTurnIdx, customerQuery);
  }

  const startTime = msToMMSS(callStartTimestamp.value, messageData.start_ms as number);
  const endTime = msToMMSS(callStartTimestamp.value, messageData.end_ms as number);
  callAnalyticsData.value = {
    totalCallTime: callStartTime.value,
    currentPlayTime: callStartTime.value,
    segments: [
      ...callAnalyticsData.value.segments,
      {
        id: messageData.turn_idx as number,
        sender: messageData.speaker === "customer" ? "user" : "consultant",
        startTime,
        endTime,
      },
    ],
  };

  if (!showScrollToBottomButton.value) {
    scrollToBottom();
  }
  return;
}

// Case 2: 스트리밍 버블 없음 — 기존 방식 (하위 호환)
if (turnIdx !== undefined && chatContent.value.some((msg: unknown) => (msg as Record<string, unknown>).turnIdx === turnIdx)) {
  return;
}
```

**주의:** 기존 코드 `const isUser = ...`, `const hasValidIntent = ...`, `const hasNlpKeywords = ...` (line 222~224)는 위 블록으로 대체되므로 중복 제거. 이후 `const newMsg = addChatMessage({...})` (line 231~)는 그대로 유지.

**Step 2: 타입체크**

```bash
cd asst-web && npx tsc --noEmit
```

Expected: 오류 없음

---

## Task 7: useChatMessageParser.ts — call:events에서 스트리밍 버블 클리어

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts`

**Step 1: call:events "start" 시 스트리밍 상태 초기화**

`clearChatContent();` (line 102) 바로 앞에 삽입:

```typescript
// 새 통화 시작 시 이전 스트리밍 상태 초기화
streamingBySpeaker.user = null;
streamingBySpeaker.consultant = null;
```

**Step 2: call:events "end" 시 진행 중인 스트리밍 버블 확정**

`isCalling.value = false;` (line 164) 뒤에 삽입:

```typescript
// 통화 종료 시 스트리밍 중인 버블이 있으면 확정 처리
(["user", "consultant"] as const).forEach(speaker => {
  if (streamingBySpeaker[speaker]) {
    updateChatMessage(streamingBySpeaker[speaker]!.id, { isStreaming: false });
    streamingBySpeaker[speaker] = null;
  }
});
```

**Step 3: 타입체크**

```bash
cd asst-web && npx tsc --noEmit
```

Expected: 오류 없음

**Step 4: Commit**

```bash
git add asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.ts
git commit -m "feat: nlp:partial 스트리밍 발화 실시간 표시 구현"
```

---

## Task 8: index.vue — partial 채널 구독 추가

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: socketChannels 배열에 "partial" 채널 추가**

line 1126~1132의 `socketChannels` 배열을 수정:

```typescript
const socketChannels = isAdmin.value
  ? [
      getRedisKey(tenantId, agentId, "nlp"),
      getRedisKey(tenantId, agentId, "partial"),
      getRedisKey(tenantId, agentId, "db")
    ]
  : [
      getRedisKey(tenantId, agentId, "events"),
      getRedisKey(tenantId, agentId, "nlp"),
      getRedisKey(tenantId, agentId, "partial"),
      getRedisKey(tenantId, agentId, "db")
    ];
```

**Step 2: 타입체크 + 린트**

```bash
cd asst-web && npx tsc --noEmit && npm run lint
```

Expected: 오류 없음

**Step 3: Vitest 실행**

```bash
cd asst-web && npm run test:unit
```

Expected: 기존 테스트 모두 통과

**Step 4: Commit**

```bash
git add asst-web/src/view/advisor/components/chat/index.vue
git commit -m "feat: nlp:partial 채널 구독 추가"
```

---

## Task 9: 테스트 작성 — useChatMessageParser partial 스트리밍 동작 검증

**Files:**
- Create: `asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.spec.ts`

**Step 1: 테스트 파일 생성**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ref } from "vue";

// store mock
vi.mock("@/stores/modules/agentStatus", () => ({
  useAgentStatusStore: () => ({ updateStatus: vi.fn() }),
  AgentStatus: { ON_CALL: "ON_CALL", AFTER_CALL: "AFTER_CALL" },
}));
vi.mock("@/stores/modules/userList", () => ({
  useUserListStore: () => ({ agents: [], setAgents: vi.fn() }),
}));
vi.mock("@/stores/modules/callSummaryInfo", () => ({
  useCallSummaryInfoStore: () => ({
    isCalling: false,
    callId: "",
    setCallId: vi.fn(),
    setCallStatsId: vi.fn(),
    setIsInit: vi.fn(),
    setIsCalling: vi.fn(),
    setCallTime: vi.fn(),
  }),
}));
vi.mock("@/stores/modules/customer", () => ({
  useCustomerStore: () => ({ setCustomer: vi.fn() }),
}));
vi.mock("@/stores/modules/userProfile", () => ({
  useUserProfileStore: () => ({ agent: { cc_cti_id: "agent-1" } }),
}));
vi.mock("@/utils/common", () => ({
  formatPhoneNumber: (v: string) => v,
  msToMMSS: () => "00:00",
}));

import { useChatMessageParser } from "./useChatMessageParser";

function makeParams(overrides: Record<string, unknown> = {}) {
  const chatContent = ref<unknown[]>([]);
  const addChatMessage = vi.fn((data: Record<string, unknown>) => {
    const msg = { ...data, id: chatContent.value.length + 1 };
    chatContent.value.push(msg);
    return msg;
  });
  const updateChatMessage = vi.fn((id: number, updates: Record<string, unknown>) => {
    const idx = chatContent.value.findIndex((m: unknown) => (m as Record<string, unknown>).id === id);
    if (idx !== -1) {
      chatContent.value[idx] = { ...(chatContent.value[idx] as Record<string, unknown>), ...updates };
    }
  });

  return {
    chatContent,
    addChatMessage,
    updateChatMessage,
    isAdmin: ref(false),
    isViewer: ref(false),
    agentId: ref("agent-1"),
    isCalling: ref(false),
    isCallEnded: ref(false),
    currentCallId: ref(""),
    callStartTimestamp: ref(Date.now()),
    callStartTime: ref("00:00"),
    callTimer: ref(null),
    intentList: ref([]),
    callAnalyticsData: ref({ totalCallTime: "00:00", currentPlayTime: "00:00", segments: [] }),
    showScrollToBottomButton: ref(false),
    chatAdminPanelRef: ref(null),
    clearChatContent: vi.fn(),
    scrollToBottom: vi.fn(),
    handleAssistStream: vi.fn(),
    emit: vi.fn(),
    ...overrides,
  };
}

function makePartialMessage(overrides: Record<string, unknown> = {}) {
  return {
    message: {
      channel: "dev:4609686:agent-1:call:nlp:partial",
      message: JSON.stringify({
        tenant_id: "4609686",
        agent_id: "agent-1",
        call_id: "call-1",
        turn_idx: 10,
        speaker: "customer",
        start_ms: 1000,
        end_ms: 2000,
        origin_text: "안녕하세요",
        masked_text: "",
        nlp: null,
        timestamp: new Date().toISOString(),
        ...overrides,
      }),
    },
    timestamp: new Date().toISOString(),
  };
}

function makeCompleteMessage(overrides: Record<string, unknown> = {}) {
  return {
    message: {
      channel: "dev:4609686:agent-1:call:nlp:complete",
      message: JSON.stringify({
        tenant_id: "4609686",
        agent_id: "agent-1",
        call_id: "call-1",
        turn_idx: 10,
        speaker: "customer",
        start_ms: 1000,
        end_ms: 2000,
        origin_text: "안녕하세요 반갑습니다",
        masked_text: "안녕하세요 반갑습니다",
        nlp: { intent: [{ intent: "GREET", score: 0.99 }], keywords: ["안녕"], search_query: "" },
        timestamp: new Date().toISOString(),
        ...overrides,
      }),
    },
    timestamp: new Date().toISOString(),
  };
}

describe("useChatMessageParser - nlp:partial 스트리밍", () => {
  it("nlp:partial 첫 수신 시 isStreaming:true 버블을 생성한다", async () => {
    const params = makeParams();
    const { parseMessageData } = useChatMessageParser(params);

    await parseMessageData(makePartialMessage());

    expect(params.addChatMessage).toHaveBeenCalledOnce();
    expect(params.addChatMessage).toHaveBeenCalledWith(
      expect.objectContaining({ isStreaming: true, turnIdx: 10, sender: "user" })
    );
  });

  it("동일 turn_idx의 nlp:partial 재수신 시 버블을 새로 생성하지 않고 텍스트만 업데이트한다", async () => {
    const params = makeParams();
    const { parseMessageData } = useChatMessageParser(params);

    await parseMessageData(makePartialMessage({ origin_text: "안녕" }));
    await parseMessageData(makePartialMessage({ origin_text: "안녕하세요" }));

    expect(params.addChatMessage).toHaveBeenCalledOnce(); // 버블 생성은 1회
    expect(params.updateChatMessage).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({ content: "안녕하세요" })
    );
  });

  it("nlp:complete 수신 시 스트리밍 버블을 확정(isStreaming:false)하고 NLP 데이터를 채운다", async () => {
    const params = makeParams();
    const { parseMessageData } = useChatMessageParser(params);

    await parseMessageData(makePartialMessage());
    const streamingId = (params.chatContent.value[0] as Record<string, unknown>).id as number;

    await parseMessageData(makeCompleteMessage());

    expect(params.updateChatMessage).toHaveBeenCalledWith(
      streamingId,
      expect.objectContaining({ isStreaming: false, content: "안녕하세요 반갑습니다" })
    );
    expect(params.addChatMessage).toHaveBeenCalledOnce(); // 신규 버블 추가 없음
  });

  it("nlp:partial 없이 nlp:complete만 오면 기존 방식대로 신규 버블을 생성한다 (하위 호환)", async () => {
    const params = makeParams();
    const { parseMessageData } = useChatMessageParser(params);

    await parseMessageData(makeCompleteMessage());

    expect(params.addChatMessage).toHaveBeenCalledOnce();
    expect(params.addChatMessage).toHaveBeenCalledWith(
      expect.objectContaining({ isStreaming: undefined })
    );
  });

  it("상담사와 고객이 동시 발화 시 각자의 스트리밍 버블이 독립적으로 유지된다", async () => {
    const params = makeParams();
    const { parseMessageData } = useChatMessageParser(params);

    await parseMessageData(makePartialMessage({ speaker: "customer", turn_idx: 10, origin_text: "고객 발화" }));
    await parseMessageData(makePartialMessage({ speaker: "agent", turn_idx: 11, origin_text: "상담사 발화" }));

    expect(params.addChatMessage).toHaveBeenCalledTimes(2);
    expect(params.chatContent.value).toHaveLength(2);
    expect((params.chatContent.value[0] as Record<string, unknown>).sender).toBe("user");
    expect((params.chatContent.value[1] as Record<string, unknown>).sender).toBe("consultant");
  });
});
```

**Step 2: 테스트 실행 (실패 확인)**

```bash
cd asst-web && npx vitest run src/view/advisor/components/chat/composables/useChatMessageParser.spec.ts
```

Expected: Task 5~7 구현 후 전부 통과

**Step 3: 전체 테스트 실행**

```bash
cd asst-web && npm run test:unit
```

Expected: 기존 테스트 포함 모두 통과

**Step 4: Commit**

```bash
git add asst-web/src/view/advisor/components/chat/composables/useChatMessageParser.spec.ts
git commit -m "test: useChatMessageParser nlp:partial 스트리밍 동작 테스트 추가"
```

---

## 검증 방법

1. 로컬 개발 서버 실행 후 실제 통화 진행
2. 브라우저 콘솔에서 `redis-message` 이벤트로 `nlp:partial` 수신 확인
3. 발화 중 버블에 깜빡이는 커서 표시 확인
4. `nlp:complete` 도착 후 커서 사라지고 키워드 버튼 표시 확인
5. 상담사·고객 동시 발화 시 두 버블이 독립적으로 업데이트되는지 확인

## 리스크 & 고려사항

- `nlp:partial` → `nlp:complete` 순서가 항상 보장되어야 함. 네트워크 지연으로 `complete`가 먼저 오면 스트리밍 버블 없이 신규 버블 생성 (하위 호환 경로)
- 동일 `turn_idx`의 `nlp:complete` 중복 수신: 스트리밍 버블 확정 후 `streamingBySpeaker[sender] = null`이므로 두 번째 `complete`는 하위 호환 경로의 dedup(line: turnIdx 중복 체크)에서 차단됨
- `stt:final` 핸들러(line 183~184)는 현재 빈 상태이므로 이번 작업에서 건드리지 않음
