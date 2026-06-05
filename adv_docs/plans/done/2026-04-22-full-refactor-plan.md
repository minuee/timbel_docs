# 전체 리팩토링 구현 계획

> **상태: 미진행 폐기** — asst-web-todo.md 기반으로 BFF 전환 작업이 진행되어 이 계획서는 실행되지 않음.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** TODO-REFACTOR.md에 명시된 백엔드 6개 파일, 프론트엔드 12개 파일을 구조 개선. 기능 동작 변경 없이 파일 크기 및 응집도 문제 해소.

**Architecture:**
- 백엔드: 도메인별 서비스 분리(socket.gateway, redis.service, favorite.service) + 파일 내 private 메서드 추출(summary.service, redis-monitor.controller, todo.service)
- 프론트엔드: 대형 Vue 컴포넌트를 서브컴포넌트 + composable로 분해. 상태는 composable, 렌더링은 서브컴포넌트

**Tech Stack:** TypeScript, NestJS 11, Socket.IO, ioredis, Vue 3, Pinia, Vitest

> **기존 계획서 참고**: `2026-04-21-backend-phase1-refactor-plan.md` — socket.gateway, redis.service Task 뼈대 있음. 단, summary.service는 그 계획서의 "파일 분리" 방향이 틀림 → 이 계획서 Task 2를 따를 것.

---

## 백엔드 Phase 1 (긴급 — 800줄 초과)

### Task 1: redis.service.ts — CoachingRedisService 분리

**파일:**
- Create: `asst-service/src/advisor/coaching/services/coaching-redis.service.ts`
- Modify: `asst-service/src/common/services/redis.service.ts`
- Modify: `asst-service/src/advisor/coaching/coaching.module.ts`

**Step 1: 현재 coaching pub/sub 메서드 위치 파악**
```bash
grep -n "publishCoachingRequest\|publishCoaching" asst-service/src/common/services/redis.service.ts
```

**Step 2: 사용처 목록 확인**
```bash
grep -rn "publishCoachingRequest\|publishCoaching" asst-service/src --include="*.ts"
```

**Step 3: coaching-redis.service.ts 생성**

```typescript
import { Injectable, Logger } from '@nestjs/common';

import { RedisService } from '@app/common/services/redis.service';
// (redis.service.ts에서 사용하던 import들 그대로 가져옴)

@Injectable()
export class CoachingRedisService {
  private readonly logger = new Logger(CoachingRedisService.name);

  constructor(private readonly redisService: RedisService) {}

  async publishCoachingRequest(coachingRequest: CoachingRequest): Promise<void> {
    // redis.service.ts publishCoachingRequest 본문 그대로 이동
    // this.redisService.publish() 형태로 호출
  }

  async publishCoaching(coaching: Coaching): Promise<void> {
    // redis.service.ts publishCoaching 본문 그대로 이동
  }
}
```

**Step 4: redis.service.ts에서 두 메서드 + 관련 import 삭제**

**Step 5: 사용처에서 RedisService → CoachingRedisService로 교체**

**Step 6: coaching.module.ts에 CoachingRedisService 등록**
```typescript
providers: [...기존, CoachingRedisService],
exports: [...기존, CoachingRedisService],
```

**Step 7: typecheck + lint**
```bash
cd asst-service && npx tsc --noEmit && npm run lint
```
Expected: 에러 0개

**Step 8: 커밋**
```
refactor: CoachingRedisService 분리

- RedisService에서 publishCoachingRequest, publishCoaching 추출
- coaching/services/coaching-redis.service.ts 신규 생성
```

---

### Task 2: summary.service.ts — 파일 내 private 메서드 추출 (파일 분리 없음)

> ⚠️ 기존 계획서(2026-04-21)는 파일 분리를 제안했으나 TODO-REFACTOR.md 방침은 "파일 내 정리만". LLM 호출/저장/조회는 항상 함께 보는 코드이므로 분리하지 않음.

**파일:**
- Modify: `asst-service/src/advisor/summary/services/summary.service.ts`

**Step 1: 대형 메서드 파악**
```bash
grep -n "async \|private " asst-service/src/advisor/summary/services/summary.service.ts
```

**Step 2: createOrUpdateSummary 내 반복 저장 루프 추출**

현재 카테고리/키워드 저장이 거의 동일한 패턴으로 두 번 반복됨. 다음 private 메서드로 추출:

```typescript
private async saveEntities<T extends ObjectLiteral>(
  repository: Repository<T>,
  entities: DeepPartial<T>[],
  logTag: string,
): Promise<void> {
  let savedCount = 0;
  for (const entityData of entities) {
    const entity = repository.create(entityData);
    await repository.save(entity);
    savedCount++;
    this.logger.debug(`[${logTag}] 저장 완료: ${savedCount}개`);
  }
}
```

**Step 3: DB 에러 처리 패턴 추출**

4곳에서 반복되는 에러 핸들링:
```typescript
private handleDbError(error: unknown, context: string): never {
  if (error instanceof NotFoundException) throw error;
  this.logger.error(`[${context}] DB 에러:`, error);
  throw new HttpException(`${context} 실패`, HttpStatus.INTERNAL_SERVER_ERROR);
}
```

**Step 4: 로깅 헬퍼 추출**

```typescript
private logSummaryOp(tag: string, callstatsId: string, detail?: string): void {
  this.logger.log(`[요약 저장] ${tag}: callstats_id=${callstatsId}${detail ? ` (${detail})` : ''}`);
}
```

**Step 5: typecheck + lint**
```bash
cd asst-service && npx tsc --noEmit && npm run lint
```

**Step 6: 커밋**
```
refactor: summary.service 파일 내 private 메서드 정리

- 반복 저장 루프 saveEntities 헬퍼로 추출
- DB 에러 처리 패턴 handleDbError로 통일
- 로깅 헬퍼 logSummaryOp 추출
```

---

### Task 3: socket.gateway.ts — 도메인 핸들러 서비스 분리

**파일:**
- Create: `asst-service/src/common/gateways/handlers/coaching-socket.handler.ts`
- Create: `asst-service/src/common/gateways/handlers/notice-socket.handler.ts`
- Create: `asst-service/src/common/gateways/handlers/agent-status-socket.handler.ts`
- Modify: `asst-service/src/common/gateways/socket.gateway.ts`
- Modify: `asst-service/src/common/common.module.ts`

> NestJS에서 @WebSocketGateway 데코레이터는 하나만 사용. Gateway는 라우팅/연결 관리만 담당하고 도메인 로직은 Injectable 서비스로 위임.

**Step 1: 각 메서드 위치 확인**
```bash
grep -n "@SubscribeMessage\|broadcastNotice\|broadcastToAgentStatusRoom\|handleCoaching\|initializeRedisSubscription" \
  asst-service/src/common/gateways/socket.gateway.ts
```

**Step 2: CoachingSocketHandler 생성**

`asst-service/src/common/gateways/handlers/coaching-socket.handler.ts`:
```typescript
import { Injectable, Logger } from '@nestjs/common';
import { Server } from 'socket.io';

import { RedisService } from '@app/common/services/redis.service';
// 기존 socket.gateway.ts에서 coaching 관련 import 이동

@Injectable()
export class CoachingSocketHandler {
  private readonly logger = new Logger(CoachingSocketHandler.name);
  private server: Server;

  constructor(private readonly redisService: RedisService) {}

  setServer(server: Server): void {
    this.server = server;
  }

  async subscribeToChannels(): Promise<void> {
    // socket.gateway.ts의 initializeRedisSubscription 중 coaching 구독 부분 이동
  }

  handleCoachingRequestMessage(rawMessage: string): void {
    // socket.gateway.ts의 handleCoachingRequestMessage 이동
  }

  handleCoachingMessage(rawMessage: string): void {
    // socket.gateway.ts의 handleCoachingMessage 이동
  }
}
```

**Step 3: NoticeSocketHandler 생성**

`asst-service/src/common/gateways/handlers/notice-socket.handler.ts`:
```typescript
import { Injectable, Logger } from '@nestjs/common';
import { Server } from 'socket.io';

@Injectable()
export class NoticeSocketHandler {
  private readonly logger = new Logger(NoticeSocketHandler.name);
  private server: Server;

  setServer(server: Server): void {
    this.server = server;
  }

  broadcastNotice(message: unknown): void {
    // socket.gateway.ts의 broadcastNotice 이동
  }
}
```

**Step 4: AgentStatusSocketHandler 생성**

`asst-service/src/common/gateways/handlers/agent-status-socket.handler.ts`:
```typescript
import { Injectable, Logger } from '@nestjs/common';
import { Server } from 'socket.io';

@Injectable()
export class AgentStatusSocketHandler {
  private readonly logger = new Logger(AgentStatusSocketHandler.name);
  private server: Server;

  setServer(server: Server): void {
    this.server = server;
  }

  broadcastToAgentStatusRoom(data: unknown): void {
    // socket.gateway.ts의 broadcastToAgentStatusRoom 이동
  }
}
```

**Step 5: SocketGateway 수정**

```typescript
// constructor에 핸들러 주입
constructor(
  private readonly moduleRef: ModuleRef,
  private readonly coachingHandler: CoachingSocketHandler,
  private readonly noticeHandler: NoticeSocketHandler,
  private readonly agentStatusHandler: AgentStatusSocketHandler,
) {}

// afterInit에서 server 전달 및 구독 초기화
afterInit(server: Server): void {
  this.server = server;
  this.coachingHandler.setServer(server);
  this.noticeHandler.setServer(server);
  this.agentStatusHandler.setServer(server);
  void this.coachingHandler.subscribeToChannels();
}

// 기존 broadcastNotice는 핸들러에 위임
broadcastNotice(message: unknown): void {
  this.noticeHandler.broadcastNotice(message);
}

// 기존 broadcastToAgentStatusRoom은 핸들러에 위임
broadcastToAgentStatusRoom(data: unknown): void {
  this.agentStatusHandler.broadcastToAgentStatusRoom(data);
}
```

**Step 6: common.module.ts에 핸들러 등록**
```typescript
providers: [...기존, CoachingSocketHandler, NoticeSocketHandler, AgentStatusSocketHandler],
exports: [...기존, CoachingSocketHandler, NoticeSocketHandler, AgentStatusSocketHandler],
```

**Step 7: typecheck + lint**
```bash
cd asst-service && npx tsc --noEmit && npm run lint
```
Expected: 에러 0개

**Step 8: 커밋**
```
refactor: SocketGateway 도메인 핸들러 서비스 분리

- CoachingSocketHandler: Redis 구독 + 코칭 메시지 처리
- NoticeSocketHandler: 공지 브로드캐스트
- AgentStatusSocketHandler: 상담사 상태 브로드캐스트
- SocketGateway는 연결 관리 + 라우팅만 담당
```

---

## 백엔드 Phase 2 (권장 — 400~800줄)

### Task 4: redis-monitor.controller.ts — 파일 내 정리 (파일 분리 없음)

**파일:**
- Modify: `asst-service/src/common/controllers/redis-monitor.controller.ts`

**Step 1: 중복 패턴 파악**
```bash
grep -n "async \|hGetAll\|hSet\|zRange\|zCard" \
  asst-service/src/common/controllers/redis-monitor.controller.ts | head -50
```

**Step 2: 중복 쿼리 로직 private 메서드로 추출**

반복되는 Redis 조회 패턴을 다음 형태로 추출:
```typescript
private async queryRedisHash(key: string): Promise<Record<string, string>> {
  return await this.redisService.hGetAll(key);
}

private formatResponse<T>(data: T, meta?: Record<string, unknown>) {
  return { data, ...meta, timestamp: new Date().toISOString() };
}
```

**Step 3: typecheck + lint**
```bash
cd asst-service && npx tsc --noEmit && npm run lint
```

**Step 4: 커밋**
```
refactor: redis-monitor.controller 파일 내 메서드 추출

- 중복 쿼리 로직 private 메서드로 통합
- 공통 응답 포맷 헬퍼 추가
```

---

### Task 5: favorite.service.ts — BaseFavoriteService 추출

**파일:**
- Create: `asst-service/src/advisor/favorite/services/base-favorite.service.ts`
- Modify: `asst-service/src/advisor/favorite/services/agents-favorite.service.ts`
- Modify: `asst-service/src/advisor/favorite/services/call-favorite.service.ts`
- Modify: `asst-service/src/advisor/favorite/services/coaching-requests-favorite.service.ts`
- Modify: `asst-service/src/advisor/favorite/services/coaching-favorite.service.ts`

**Step 1: 5개 서비스에서 공통 getRepository 패턴 확인**
```bash
grep -n "getRepository" asst-service/src/advisor/favorite/services/*.ts
```

**Step 2: base-favorite.service.ts 생성**

```typescript
import { Injectable } from '@nestjs/common';
import { Repository, ObjectLiteral } from 'typeorm';

import { AdvisorService } from '@app/advisor/advisor.service';

@Injectable()
export abstract class BaseFavoriteService {
  constructor(protected readonly advisorService: AdvisorService) {}

  protected async getRepository<T extends ObjectLiteral>(
    EntityClass: new () => T,
    token: string,
  ): Promise<Repository<T>> {
    return this.advisorService.getRepository(EntityClass, token);
  }
}
```

**Step 3: 각 서비스에서 BaseFavoriteService 상속**

```typescript
// agents-favorite.service.ts
export class AgentsFavoriteService extends BaseFavoriteService {
  // 기존 getRepository 메서드 삭제, 상위 클래스 상속으로 대체
}
```

**Step 4: favorite.module.ts에서 BaseFavoriteService 제거 (추상 클래스이므로 provider 불필요)**

**Step 5: typecheck + lint**
```bash
cd asst-service && npx tsc --noEmit && npm run lint
```

**Step 6: 커밋**
```
refactor: BaseFavoriteService 추상 클래스 추출

- 5개 FavoriteService에서 getRepository 중복 제거
- BaseFavoriteService 공통 기반 클래스 생성
```

---

### Task 6: todo.service.ts — 파일 내 정리 (파일 분리 없음)

**파일:**
- Modify: `asst-service/src/advisor/todo/services/todo.service.ts`

**Step 1: 반복 쿼리 빌더 패턴 파악**
```bash
grep -n "createQueryBuilder\|leftJoinAndSelect\|where\|andWhere" \
  asst-service/src/advisor/todo/services/todo.service.ts | head -40
```

**Step 2: 공통 쿼리 빌더 private 메서드 추출**

```typescript
private buildBaseTodoQuery(
  repository: Repository<Todo>,
  filters: { agentId?: string; companyId?: string },
) {
  return repository
    .createQueryBuilder('todo')
    .leftJoinAndSelect('todo.agent', 'agent')
    .where(filters.companyId ? 'todo.company_id = :companyId' : '1=1', filters);
}
```

**Step 3: typecheck + lint**
```bash
cd asst-service && npx tsc --noEmit && npm run lint
```

**Step 4: 커밋**
```
refactor: todo.service 파일 내 쿼리 빌더 추출

- 반복 쿼리 빌더 buildBaseTodoQuery private 메서드로 통합
- 중복 코드 제거
```

---

## 프론트엔드 Phase 1 (긴급 — 최우선)

### Task 7: icons.ts — JSON 분리

**파일:**
- Create: `asst-web/src/components/mertrialIcon/icons.json`
- Modify: `asst-web/src/components/mertrialIcon/icons.ts`

**Step 1: 현재 import 사용처 확인**
```bash
grep -rn "from.*mertrialIcon/icons\|import.*iconList" asst-web/src --include="*.ts" --include="*.vue"
```

**Step 2: icons.json 생성**

```json
[
  { "name": "ac_unit" },
  { "name": "access_alarm" },
  ...
]
```
(현재 icons.ts의 배열 내용을 그대로 JSON으로 변환)

**Step 3: icons.ts를 import로 교체**

```typescript
import iconData from './icons.json';

export interface IconItem {
  name: string;
}

export const iconList: IconItem[] = iconData;
```

**Step 4: tsconfig에서 resolveJsonModule 확인**
```bash
grep -n "resolveJsonModule" asst-web/tsconfig.json asst-web/tsconfig.*.json 2>/dev/null
```
없으면 추가:
```json
{ "compilerOptions": { "resolveJsonModule": true } }
```

**Step 5: typecheck + lint**
```bash
cd asst-web && npx tsc --noEmit && npm run lint
```

**Step 6: 커밋**
```
refactor: icons.ts 아이콘 데이터 JSON 분리

- 2126줄 정적 배열을 icons.json으로 이동
- icons.ts는 타입 + re-export만 담당
- 번들 사이즈 개선 가능 (dynamic import 전환 여지 확보)
```

---

### Task 8: chat/index.vue — 서브컴포넌트 분리

> 3614줄 중 핵심만 분리. 메시지 목록 / 입력 영역 / 오디오 컨트롤 / 검색을 각각 서브컴포넌트로.

**파일:**
- Create: `asst-web/src/view/advisor/components/chat/ChatMessageList.vue`
- Create: `asst-web/src/view/advisor/components/chat/ChatInputArea.vue`
- Create: `asst-web/src/view/advisor/components/chat/ChatSearchBar.vue`
- Create: `asst-web/src/view/advisor/components/chat/composables/useChatSocket.ts`
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: 현재 template 구조 파악**
```bash
grep -n "<!-- \|<div\|<template\|</div\|</template" \
  asst-web/src/view/advisor/components/chat/index.vue | head -80
```

**Step 2: useChatSocket composable 추출**

소켓 연결/이벤트 구독 관련 함수들을 composable로 분리:

`asst-web/src/view/advisor/components/chat/composables/useChatSocket.ts`:
```typescript
import { onMounted, onUnmounted } from 'vue';
import { useSocket } from '@/plugins/socket';

export function useChatSocket(agentId: string, onMessage: (msg: unknown) => void) {
  const socket = useSocket();

  function subscribeChannels() {
    // index.vue에서 subscribeChannels 함수 이동
  }

  function unsubscribeChannels() {
    // index.vue에서 unsubscribeChannels 함수 이동
  }

  onMounted(subscribeChannels);
  onUnmounted(unsubscribeChannels);

  return { socket };
}
```

**Step 3: ChatMessageList.vue 생성**

메시지 목록 렌더링 + 스크롤 기능:
```vue
<template>
  <!-- 현재 index.vue 메시지 목록 template 섹션 이동 -->
</template>

<script setup lang="ts">
interface Props {
  messages: ChatMessage[];
  isCallEnded: boolean;
  hasForbiddenWord: boolean;
}
const props = defineProps<Props>();
const emit = defineEmits<{
  scrolled: [position: number];
}>();
</script>
```

**Step 4: ChatInputArea.vue 생성**

입력 영역 (텍스트 입력, 전송 버튼):
```vue
<template>
  <!-- 현재 index.vue 입력 영역 template 섹션 이동 -->
</template>

<script setup lang="ts">
const emit = defineEmits<{
  send: [content: string];
  tagSelect: [tag: string];
}>();
</script>
```

**Step 5: ChatSearchBar.vue 생성**

검색 바 + 검색 결과 하이라이트 UI:
```vue
<template>
  <!-- 검색 관련 UI template 이동 -->
</template>

<script setup lang="ts">
interface Props {
  isActive: boolean;
  currentIndex: number;
  totalCount: number;
}
</script>
```

**Step 6: index.vue에서 서브컴포넌트 사용으로 교체**

```vue
<template>
  <div class="chat-container">
    <ChatSearchBar v-if="isSearchActive" ... />
    <ChatMessageList :messages="chatContent" ... />
    <ChatInputArea @send="addChatMessage" ... />
  </div>
</template>

<script setup lang="ts">
import ChatMessageList from './ChatMessageList.vue';
import ChatInputArea from './ChatInputArea.vue';
import ChatSearchBar from './ChatSearchBar.vue';
import { useChatSocket } from './composables/useChatSocket';
</script>
```

**Step 7: typecheck + lint**
```bash
cd asst-web && npx tsc --noEmit && npm run lint
```

**Step 8: dev 서버로 기능 확인**
```bash
cd asst-web && npm run dev
```
확인 항목: 메시지 렌더링, 소켓 수신, 입력 전송, 검색

**Step 9: 커밋**
```
refactor: chat/index.vue 서브컴포넌트 분리

- ChatMessageList: 메시지 목록 렌더링
- ChatInputArea: 텍스트 입력 + 태그 선택
- ChatSearchBar: 검색 UI + 하이라이트 제어
- useChatSocket: 소켓 구독/해제 composable
```

---

## 프론트엔드 Phase 2 (Knowledge 컴포넌트)

### Task 9: TabTypeKnowledgeIndex.vue — composable + 서브컴포넌트 분리

**파일:**
- Create: `asst-web/src/view/advisor/components/knowledge/composables/useKnowledgeTabs.ts`
- Create: `asst-web/src/view/advisor/components/knowledge/composables/useKnowledgeSearch.ts`
- Create: `asst-web/src/view/advisor/components/knowledge/composables/useKnowledgeScroll.ts`
- Modify: `asst-web/src/view/advisor/components/knowledge/TabTypeKnowledgeIndex.vue`

**Step 1: useKnowledgeTabs composable 추출**

탭 상태, 활성 탭, 탭 추가/제거 로직:
```typescript
// composables/useKnowledgeTabs.ts
import { ref, computed } from 'vue';

export function useKnowledgeTabs(chatDocumentList: Ref<...>) {
  const activeTab = ref<string | null>(null);
  const searchSessions = ref<SearchSession[]>([]);

  const allTabs = computed(() => [
    ...chatDocumentList.value.map(d => ({ type: 'chat', ...d })),
    ...searchSessions.value.map(s => ({ type: 'search', ...s })),
  ]);

  function handleTabClick(tabId: string) { ... }
  function handleTabRemove(tabId: string) { ... }

  return { activeTab, allTabs, searchSessions, handleTabClick, handleTabRemove };
}
```

**Step 2: useKnowledgeSearch composable 추출**

검색 실행, 스트리밍, 세션 관리:
```typescript
// composables/useKnowledgeSearch.ts
export function useKnowledgeSearch() {
  const searchAbortControllers = ref<Map<string, AbortController>>(new Map());

  async function handleSearch(keyword: string, sessionId: string) {
    // callDocumentStream 호출 + AbortController 관리
  }

  return { searchAbortControllers, handleSearch };
}
```

**Step 3: useKnowledgeScroll composable 추출**

탭 스크롤 버튼 표시 로직:
```typescript
// composables/useKnowledgeScroll.ts
export function useKnowledgeScroll(tabsRef: Ref<HTMLElement | null>) {
  const showScrollButtons = ref(false);

  function checkScrollNeeded() { ... }
  function scrollTabsLeft() { ... }
  function scrollTabsRight() { ... }

  return { showScrollButtons, checkScrollNeeded, scrollTabsLeft, scrollTabsRight };
}
```

**Step 4: TabTypeKnowledgeIndex.vue에서 composable 사용**

```vue
<script setup lang="ts">
import { useKnowledgeTabs } from './composables/useKnowledgeTabs';
import { useKnowledgeSearch } from './composables/useKnowledgeSearch';
import { useKnowledgeScroll } from './composables/useKnowledgeScroll';

const { activeTab, allTabs, handleTabClick, handleTabRemove } = useKnowledgeTabs(chatDocumentList);
const { handleSearch } = useKnowledgeSearch();
const { showScrollButtons, scrollTabsLeft, scrollTabsRight } = useKnowledgeScroll(tabsRef);
</script>
```

**Step 5: typecheck + lint**
```bash
cd asst-web && npx tsc --noEmit && npm run lint
```

**Step 6: 커밋**
```
refactor: TabTypeKnowledgeIndex composable 분리

- useKnowledgeTabs: 탭 상태 관리
- useKnowledgeSearch: 검색 + 스트리밍 세션
- useKnowledgeScroll: 탭 스크롤 제어
```

---

### Task 10: ChatHistoryModal.vue — 섹션 컴포넌트 분리

**파일:**
- Create: `asst-web/src/view/advisor/components/ChatHistoryModal/CustomerInfoSection.vue`
- Create: `asst-web/src/view/advisor/components/ChatHistoryModal/ConversationSection.vue`
- Create: `asst-web/src/view/advisor/components/ChatHistoryModal/StatisticsSection.vue`
- Modify: `asst-web/src/view/advisor/components/ChatHistoryModal.vue`
  (또는 `ChatHistoryModal/index.vue`로 디렉토리 구조 변경)

**Step 1: 현재 구조 파악**
```bash
grep -n "<!-- \|v-if\|v-show\|<section\|<div class" \
  "asst-web/src/view/advisor/components/ChatHistoryModal.vue" | head -60
```

**Step 2: CustomerInfoSection 분리**

고객 정보 표시 섹션 (이름, 전화번호, 조직 등):
```vue
<template>
  <!-- 고객 정보 UI -->
</template>
<script setup lang="ts">
interface Props { customer: CustomerInfo; }
</script>
```

**Step 3: ConversationSection 분리**

대화 내역 목록 + 스크롤:
```vue
<template>
  <!-- 대화 내역 UI -->
</template>
<script setup lang="ts">
interface Props { messages: HistoryMessage[]; }
</script>
```

**Step 4: StatisticsSection 분리**

통계 데이터 차트/테이블:
```vue
<template>
  <!-- 통계 UI -->
</template>
<script setup lang="ts">
interface Props { stats: CallStatistics; }
</script>
```

**Step 5: 메인 모달에서 조합**

```vue
<template>
  <CustomerInfoSection :customer="customerData" />
  <ConversationSection :messages="conversationHistory" />
  <StatisticsSection :stats="callStats" />
</template>
```

**Step 6: typecheck + lint + dev 서버 확인**
```bash
cd asst-web && npx tsc --noEmit && npm run lint
```

**Step 7: 커밋**
```
refactor: ChatHistoryModal 섹션 컴포넌트 분리

- CustomerInfoSection: 고객 정보
- ConversationSection: 대화 내역
- StatisticsSection: 통계
```

---

### Task 11: knowledge/index.vue — 상태 Pinia 이관 + composable 분리

**파일:**
- Modify: `asst-web/src/stores/modules/knowledge.ts` (없으면 생성)
- Create: `asst-web/src/view/advisor/components/knowledge/composables/useKnowledgeState.ts`
- Modify: `asst-web/src/view/advisor/components/knowledge/index.vue`

**Step 1: 현재 상태 파악**
```bash
grep -n "const \|ref(\|reactive(\|computed(" \
  asst-web/src/view/advisor/components/knowledge/index.vue | head -60
```

**Step 2: Pinia store로 이관할 전역 상태 식별**

여러 컴포넌트에서 공유되는 상태 (검색 결과, 선택된 문서 등)를 store로 이관.

**Step 3: useKnowledgeState composable 생성**

컴포넌트 로컬 상태 + API 호출 로직:
```typescript
export function useKnowledgeState() {
  const searchQuery = ref('');
  const activeTab = ref('faq');

  async function loadContent(tab: string) { ... }

  return { searchQuery, activeTab, loadContent };
}
```

**Step 4: typecheck + lint**
```bash
cd asst-web && npx tsc --noEmit && npm run lint
```

**Step 5: 커밋**
```
refactor: knowledge/index.vue 상태 분리

- 전역 공유 상태 Pinia store 이관
- useKnowledgeState composable 추출
```

---

## 프론트엔드 Phase 3 (드로어 컴포넌트)

### Task 12: Bookmark.vue — 서브컴포넌트 분리

**파일:**
- Create: `asst-web/src/components/layout/Drawer/components/Bookmark/BookmarkList.vue`
- Create: `asst-web/src/components/layout/Drawer/components/Bookmark/BookmarkGroupManager.vue`
- Create: `asst-web/src/components/layout/Drawer/components/Bookmark/BookmarkEditForm.vue`
- Modify: `asst-web/src/components/layout/Drawer/components/Bookmark/Bookmark.vue`

**Step 1: 구조 파악**
```bash
grep -n "<!-- \|v-if\|<BookmarkList\|<div class" \
  "asst-web/src/components/layout/Drawer/components/Bookmark/Bookmark.vue" | head -60
```

**Step 2: BookmarkList 분리** — 북마크 항목 목록 + 드래그앤드롭

**Step 3: BookmarkGroupManager 분리** — 그룹 추가/수정/삭제

**Step 4: BookmarkEditForm 분리** — 북마크 편집 폼

**Step 5: typecheck + lint + dev 확인**

**Step 6: 커밋**
```
refactor: Bookmark.vue 서브컴포넌트 분리

- BookmarkList: 목록 + 드래그앤드롭
- BookmarkGroupManager: 그룹 관리
- BookmarkEditForm: 편집 폼
```

---

### Task 13: AdminCoaching.vue — 목록/상세 분리

**파일:**
- Create: `asst-web/src/components/layout/Drawer/components/AdminCoaching/AdminCoachingList.vue`
- Create: `asst-web/src/components/layout/Drawer/components/AdminCoaching/AdminCoachingDetail.vue`
- Modify: `asst-web/src/components/layout/Drawer/components/AdminCoaching/AdminCoaching.vue`

**Step 1: 구조 파악**
```bash
grep -n "<!-- \|v-if\|<div class" \
  "asst-web/src/components/layout/Drawer/components/AdminCoaching/AdminCoaching.vue" | head -60
```

**Step 2: AdminCoachingList 분리** — 코칭 목록 (독립적으로 수정됨)

**Step 3: AdminCoachingDetail 분리** — 코칭 상세 뷰

**Step 4: typecheck + lint**

**Step 5: 커밋**
```
refactor: AdminCoaching.vue 목록/상세 분리

- AdminCoachingList: 코칭 목록
- AdminCoachingDetail: 코칭 상세
```

---

### Task 14: Dashboard.vue + ConsultantDrawer/index.vue — composable 분리

**파일 (Dashboard):**
- Create: `asst-web/src/view/advisor/agent/composables/useDashboardWidgets.ts`
- Modify: `asst-web/src/view/advisor/agent/Dashboard.vue`

**파일 (ConsultantDrawer):**
- Create: `asst-web/src/view/advisor/components/ConsultantDrawer/composables/useConsultantFilter.ts`
- Modify: `asst-web/src/view/advisor/components/ConsultantDrawer/index.vue`

**Step 1: Dashboard — 위젯(공지/요약/통계) 데이터 로딩 로직 composable 추출**
```typescript
// composables/useDashboardWidgets.ts
export function useDashboardWidgets() {
  const notices = ref([]);
  const summary = ref(null);
  const stats = ref(null);

  async function loadAll() { ... }

  return { notices, summary, stats, loadAll };
}
```

**Step 2: ConsultantDrawer — 검색 필터/목록/선택 상태 composable 추출**
```typescript
// composables/useConsultantFilter.ts
export function useConsultantFilter() {
  const searchQuery = ref('');
  const selectedConsultants = ref<string[]>([]);

  function toggleSelect(id: string) { ... }
  function clearFilter() { ... }

  return { searchQuery, selectedConsultants, toggleSelect, clearFilter };
}
```

**Step 3: typecheck + lint**

**Step 4: 커밋**
```
refactor: Dashboard, ConsultantDrawer composable 추출

- useDashboardWidgets: 위젯 데이터 로딩
- useConsultantFilter: 필터/선택 상태
```

---

## 프론트엔드 Phase 4 (권장)

### Task 15: CallHistoryView/index.vue, agent/index.vue, SpeechBubble.vue

**Task 15a: CallHistoryView — 필터 UI + 데이터 테이블 분리**

**파일:**
- Create: `asst-web/src/view/advisor/components/CallHistoryView/CallHistoryFilter.vue`
- Create: `asst-web/src/view/advisor/components/CallHistoryView/CallHistoryTable.vue`
- Modify: `asst-web/src/view/advisor/components/CallHistoryView/index.vue`

**Step 1: 필터 UI와 테이블이 각각 독립적으로 수정되는지 확인 후 분리**

**Step 2: typecheck + lint**

**Step 3: 커밋**
```
refactor: CallHistoryView 필터/테이블 분리
```

---

**Task 15b: agent/index.vue — composable로 상태 분리**

**파일:**
- Create: `asst-web/src/view/advisor/agent/composables/useAgentTab.ts`
- Modify: `asst-web/src/view/advisor/agent/index.vue`

**Step 1: 탭별 상태(대시보드/상담) 로직을 composable로 추출**

**Step 2: typecheck + lint**

**Step 3: 커밋**
```
refactor: agent/index.vue 탭 상태 composable 추출
```

---

**Task 15c: SpeechBubble.vue — useTextRenderer composable 추출**

> 컴포넌트 분리 없음 — composable 추출만

**파일:**
- Create: `asst-web/src/view/advisor/components/composables/useTextRenderer.ts`
- Modify: `asst-web/src/view/advisor/components/SpeechBubble.vue`

**Step 1: 텍스트 처리 로직 확인**
```bash
grep -n "highlight\|markdown\|renderText\|parseText" \
  asst-web/src/view/advisor/components/SpeechBubble.vue | head -20
```

**Step 2: useTextRenderer composable 추출**
```typescript
// composables/useTextRenderer.ts
export function useTextRenderer() {
  function highlightKeywords(text: string, keywords: string[]): string { ... }
  function renderMarkdown(text: string): string { ... }

  return { highlightKeywords, renderMarkdown };
}
```

**Step 3: typecheck + lint**

**Step 4: 커밋**
```
refactor: SpeechBubble useTextRenderer composable 추출

- 텍스트 하이라이트/마크다운 처리 분리
```

---

## 완료 기준

| Phase | 파일 | 목표 줄 수 | 분리 산출물 |
|-------|------|-----------|-----------|
| 백엔드 P1 | `redis.service.ts` | ~680줄 | `coaching-redis.service.ts` |
| 백엔드 P1 | `summary.service.ts` | ~700줄 | 파일 내 정리만 |
| 백엔드 P1 | `socket.gateway.ts` | ~450줄 | `handlers/` 3개 |
| 백엔드 P2 | `redis-monitor.controller.ts` | ~450줄 | 파일 내 정리만 |
| 백엔드 P2 | `favorite.service.ts` 5개 | 중복 제거 | `base-favorite.service.ts` |
| 백엔드 P2 | `todo.service.ts` | ~380줄 | 파일 내 정리만 |
| 프론트 P1 | `icons.ts` | ~20줄 | `icons.json` |
| 프론트 P1 | `chat/index.vue` | ~1200줄 | 서브컴포넌트 4개 + composable |
| 프론트 P2 | `TabTypeKnowledgeIndex.vue` | ~500줄 | composable 3개 |
| 프론트 P2 | `ChatHistoryModal.vue` | ~400줄 | 섹션 컴포넌트 3개 |
| 프론트 P2 | `knowledge/index.vue` | ~500줄 | composable + store |
| 프론트 P3 | `Bookmark.vue` | ~400줄 | 서브컴포넌트 3개 |
| 프론트 P3 | `AdminCoaching.vue` | ~400줄 | 목록/상세 분리 |
| 프론트 P3 | `Dashboard.vue` | ~500줄 | composable |
| 프론트 P3 | `ConsultantDrawer/index.vue` | ~450줄 | composable |
| 프론트 P4 | `CallHistoryView/index.vue` | ~450줄 | 필터/테이블 분리 |
| 프론트 P4 | `agent/index.vue` | ~500줄 | composable |
| 프론트 P4 | `SpeechBubble.vue` | ~600줄 | composable 추출 |

**최종 검증:**
```bash
# 백엔드
cd asst-service && npx tsc --noEmit && npm run lint

# 프론트엔드
cd asst-web && npx tsc --noEmit && npm run lint
```
Expected: 에러 0개, 경고 0개
