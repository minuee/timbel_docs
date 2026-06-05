# 백엔드 Phase 1 리팩토링 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** socket.gateway.ts(1070줄), summary.service.ts(835줄), redis.service.ts(774줄) 세 파일을 도메인별 서비스로 분리하여 각 파일 400줄 이내로 축소

**Architecture:** 기능 동작 변경 없이 구조만 개선하는 순수 리팩토링. 각 파일에서 특정 도메인 책임을 별도 서비스 클래스로 위임한다. Gateway는 라우팅/연결 관리만 담당하고, 도메인 로직은 전용 서비스로 이동한다.

**Tech Stack:** TypeScript, NestJS 11, Socket.IO, Redis (ioredis), TypeORM

---

## Task 1: redis.service.ts — CoachingRedisService 분리

**목표**: 코칭 도메인 Redis 발행 메서드 2개를 별도 서비스로 분리

**Files:**
- Create: `asst-service/src/advisor/coaching/services/coaching-redis.service.ts`
- Modify: `asst-service/src/common/services/redis.service.ts` (라인 508-617 삭제)
- Modify: `asst-service/src/advisor/coaching/coaching.module.ts` (새 서비스 등록)
- Modify: `asst-service/src/common/common.module.ts` (exports 확인)

**Step 1: 새 파일 생성**

`asst-service/src/advisor/coaching/services/coaching-redis.service.ts` 생성:

```typescript
import { Injectable, Logger } from '@nestjs/common';

import { CoachingRequest } from '@app/advisor/coaching/entities/coaching-request.entity';
import { Coaching } from '@app/advisor/coaching/entities/coaching.entity';
import { REDIS_COACHING_CHANNELS } from '@app/common/constants/coaching.constants';
import {
  CoachingRequestMessage,
  CoachingMessage,
} from '@app/common/types/coaching.types';
import { RedisService } from '@app/common/services/redis.service';

@Injectable()
export class CoachingRedisService {
  private readonly logger = new Logger(CoachingRedisService.name);

  constructor(private readonly redisService: RedisService) {}

  async publishCoachingRequest(
    coachingRequest: CoachingRequest,
  ): Promise<void> {
    // redis.service.ts 508-563 그대로 이동
  }

  async publishCoaching(coaching: Coaching): Promise<void> {
    // redis.service.ts 570-617 그대로 이동
  }
}
```

**Step 2: 메서드 본문 복사**

`redis.service.ts` 508-617줄의 `publishCoachingRequest`, `publishCoaching` 메서드 본문을 위 파일로 이동. `this.redisService.publish(...)` 형태로 호환.

**Step 3: redis.service.ts에서 메서드 제거**

`redis.service.ts`에서:
- 508-617줄 (`publishCoachingRequest`, `publishCoaching`) 삭제
- 상단 import에서 `CoachingRequest`, `Coaching`, `REDIS_COACHING_CHANNELS`, `CoachingRequestMessage`, `CoachingMessage` 삭제 (다른 곳에서 사용 안 하면)

**Step 4: CoachingRedisService 기존 사용처 교체**

`redis.service.ts`의 `publishCoachingRequest`, `publishCoaching` 호출처 찾아 교체:
```bash
grep -r "publishCoachingRequest\|publishCoaching" asst-service/src --include="*.ts"
```
- 찾은 파일에서 `RedisService` → `CoachingRedisService` import 및 주입으로 교체

**Step 5: coaching.module.ts에 등록**

```typescript
// providers에 추가
CoachingRedisService,
// exports에 추가 (다른 모듈에서 사용 시)
CoachingRedisService,
```

**Step 6: typecheck 실행**

```bash
cd asst-service && npx tsc --noEmit
```
Expected: 에러 0개

**Step 7: lint 실행**

```bash
cd asst-service && npm run lint
```

**Step 8: 커밋**

```
refactor: CoachingRedisService 분리

- RedisService에서 publishCoachingRequest, publishCoaching 메서드 추출
- coaching/services/coaching-redis.service.ts 신규 생성
```

---

## Task 2: summary.service.ts — LLM 서비스 분리

**목표**: LLM 호출 로직(약 350줄)을 SummaryLlmService로 분리, SummaryService는 CRUD 및 오케스트레이션만 담당

**Files:**
- Create: `asst-service/src/advisor/summary/services/summary-llm.service.ts`
- Modify: `asst-service/src/advisor/summary/services/summary.service.ts`
- Modify: `asst-service/src/advisor/summary/summary.module.ts`

**Step 1: SummaryLlmService 파일 생성**

`asst-service/src/advisor/summary/services/summary-llm.service.ts` 생성:

```typescript
import { Injectable, Logger, HttpException, HttpStatus } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

import { AdvisorService } from '@app/advisor/advisor.service';
import {
  SummaryResponseDto,
  LlmKeywordContentDto,
  CounselingTypeItemDto,
} from '@app/advisor/summary/dto/summary-response.dto';
import { SummaryRequestDto } from '@app/advisor/summary/dto/summary-request.dto';
import { LlmOrchestratorService } from '@app/common/services/llm-orchestrator.service';
import { UserInfoService } from '@app/common/services/user-info.service';

@Injectable()
export class SummaryLlmService {
  private readonly logger = new Logger(SummaryLlmService.name);

  constructor(
    private readonly advisorService: AdvisorService,
    private readonly configService: ConfigService,
    private readonly llmOrchestratorService: LlmOrchestratorService,
    private readonly userInfoService: UserInfoService,
  ) {}

  // 이동할 메서드:
  // summarizeCall (44-128)
  // callLlmSummarize (136-152)
  // callLlmKeywords (161-179)
  // getCompanyIdFromToken (181-201)
  // classifyCounselingType (210-374)
  // parseCounselingTypeResponse (379-416)
}
```

**Step 2: 메서드 본문 이동**

`summary.service.ts` 44-416줄 메서드 6개를 `summary-llm.service.ts`로 이동.

**Step 3: SummaryService 수정**

`summary.service.ts`:
- constructor에서 `LlmOrchestratorService`, `UserInfoService` 제거
- `SummaryLlmService` 주입 추가
- `summarizeCall`은 `SummaryLlmService`에 위임:

```typescript
async summarizeCall(request: SummaryRequestDto, token: string | undefined) {
  return this.summaryLlmService.summarizeCall(request, token);
}
```

**Step 4: summary.module.ts 업데이트**

```typescript
providers: [SummaryService, SummaryLlmService],
```

**Step 5: typecheck 실행**

```bash
cd asst-service && npx tsc --noEmit
```

**Step 6: lint 실행**

```bash
cd asst-service && npm run lint
```

**Step 7: 커밋**

```
refactor: SummaryLlmService 분리

- SummaryService에서 LLM 호출 로직 추출 (summarizeCall 외 5개 메서드)
- summary/services/summary-llm.service.ts 신규 생성
- SummaryService는 CRUD 및 위임만 담당
```

---

## Task 3: socket.gateway.ts — 도메인 핸들러 서비스 분리

**목표**: Gateway 1070줄 → 400줄 이하로 축소. 코칭/공지/에이전트 상태 로직을 별도 서비스로 위임.

**분리 전략**: NestJS에서 WebSocketGateway는 하나만 두는 것이 권장됨. 따라서 Gateway 분리가 아니라 "도메인 핸들러 서비스"로 로직을 위임하는 패턴 사용.

**Files:**
- Create: `asst-service/src/common/gateways/handlers/coaching-socket-handler.service.ts`
- Create: `asst-service/src/common/gateways/handlers/notice-socket-handler.service.ts`
- Create: `asst-service/src/common/gateways/handlers/agent-status-socket-handler.service.ts`
- Modify: `asst-service/src/common/gateways/socket.gateway.ts`
- Modify: `asst-service/src/common/common.module.ts`

### Task 3a: CoachingSocketHandlerService 생성

**Step 1: handlers 디렉토리 생성 후 파일 작성**

`asst-service/src/common/gateways/handlers/coaching-socket-handler.service.ts`:

```typescript
import { Injectable, Logger } from '@nestjs/common';
import { Server } from 'socket.io';

import {
  REDIS_COACHING_CHANNELS,
  SOCKET_COACHING_EVENTS,
} from '@app/common/constants/coaching.constants';
import {
  CoachingRequestMessage,
  CoachingMessage,
} from '@app/common/types/coaching.types';
import { RedisService } from '@app/common/services/redis.service';

@Injectable()
export class CoachingSocketHandlerService {
  private readonly logger = new Logger(CoachingSocketHandlerService.name);
  private server: Server;

  constructor(private readonly redisService: RedisService) {}

  setServer(server: Server): void {
    this.server = server;
  }

  async subscribeToCoachingChannels(): Promise<void> {
    // socket.gateway.ts 805-863 이동
  }

  handleCoachingRequestMessage(message: CoachingRequestMessage): void {
    // socket.gateway.ts 869-942 이동
  }

  handleCoachingMessage(message: CoachingMessage): void {
    // socket.gateway.ts 948-1019 이동
  }
}
```

**Step 2: 메서드 본문 이동**

`socket.gateway.ts` 805-1019줄 3개 메서드를 위 서비스로 이동.

**Step 3: SocketGateway에서 위임 호출**

`socket.gateway.ts` 수정:
- constructor에 `CoachingSocketHandlerService` 주입
- `afterInit` 내 `this.initializeRedisSubscription()` → 핸들러 서비스의 `setServer(this.server)` 후 구독 실행
- 기존 메서드 자리에 위임 호출만 남김

### Task 3b: NoticeSocketHandlerService 생성

**Step 1: 파일 작성**

`asst-service/src/common/gateways/handlers/notice-socket-handler.service.ts`:

```typescript
import { Injectable, Logger } from '@nestjs/common';
import { Server } from 'socket.io';

import { NoticeSocketMessage } from '@app/common/types/socket.types';

@Injectable()
export class NoticeSocketHandlerService {
  private readonly logger = new Logger(NoticeSocketHandlerService.name);
  private server: Server;

  setServer(server: Server): void {
    this.server = server;
  }

  handleNoticeMessage(message: NoticeSocketMessage): void {
    // socket.gateway.ts 365-380 이동
  }

  broadcastNotice(message: NoticeSocketMessage): void {
    // socket.gateway.ts 489-544 이동
  }
}
```

**Step 2: 메서드 이동 및 Gateway 위임 처리**

`socket.gateway.ts`의 `handleNoticeMessage`(365-380), `broadcastNotice`(489-544) 이동.

### Task 3c: AgentStatusSocketHandlerService 생성

**Step 1: 파일 작성**

`asst-service/src/common/gateways/handlers/agent-status-socket-handler.service.ts`:

```typescript
import { Injectable, Logger } from '@nestjs/common';
import { Server } from 'socket.io';

@Injectable()
export class AgentStatusSocketHandlerService {
  private readonly logger = new Logger(AgentStatusSocketHandlerService.name);
  private server: Server;

  setServer(server: Server): void {
    this.server = server;
  }

  broadcastToAgentStatusRoom(data: unknown): void {
    // socket.gateway.ts 1025-1069 이동
  }
}
```

**Step 2: 메서드 이동 및 Gateway 위임 처리**

`socket.gateway.ts`의 `broadcastToAgentStatusRoom`(1025-1069) 이동.

### Task 3d: common.module.ts 업데이트 및 최종 검증

**Step 1: common.module.ts에 핸들러 서비스 등록**

```typescript
providers: [
  ...기존...,
  CoachingSocketHandlerService,
  NoticeSocketHandlerService,
  AgentStatusSocketHandlerService,
],
exports: [
  ...기존...,
  CoachingSocketHandlerService,
  NoticeSocketHandlerService,
  AgentStatusSocketHandlerService,
],
```

**Step 2: typecheck 실행**

```bash
cd asst-service && npx tsc --noEmit
```
Expected: 에러 0개

**Step 3: lint 실행**

```bash
cd asst-service && npm run lint
```

**Step 4: 커밋**

```
refactor: SocketGateway 도메인 핸들러 서비스 분리

- CoachingSocketHandlerService: Redis 구독 및 코칭 메시지 처리
- NoticeSocketHandlerService: 공지사항 메시지 처리 및 브로드캐스트
- AgentStatusSocketHandlerService: 상담사 상태 브로드캐스트
- SocketGateway는 연결 관리 및 라우팅만 담당
```

---

## 완료 기준

| 파일 | 목표 줄 수 | 분리 산출물 |
|------|-----------|-----------|
| `redis.service.ts` | ~680줄 이하 | `coaching-redis.service.ts` |
| `summary.service.ts` | ~450줄 이하 | `summary-llm.service.ts` |
| `socket.gateway.ts` | ~450줄 이하 | `coaching-socket-handler.service.ts`, `notice-socket-handler.service.ts`, `agent-status-socket-handler.service.ts` |

**최종 검증:**

```bash
cd asst-service && npx tsc --noEmit && npm run lint
```

Expected: 에러 0개, 경고 0개
