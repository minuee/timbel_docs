# assist-stream SSE 전환 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 고객 발화 실시간 자동 검색을 기존 `/api/v1/search` 이중 호출(keyword+hybrid)에서 신규 SSE 엔드포인트 `/api/v1/rag/assist-stream` 단일 호출로 전환하고, 참고문서/요약/답변을 스트리밍으로 UI에 반영한다.

**Architecture:** NestJS가 SSE 프록시 역할을 하여 프론트엔드는 기존 Bearer 인증을 유지하고, asst-service가 `X-Tenant-Id`를 주입해 RAG 서비스의 assist-stream 엔드포인트로 릴레이한다. `sources` → 참고문서 카드, `distilled.summary` → AI 요약, `token` 누적 → AI 답변 영역에 각각 바인딩.

**Tech Stack:** NestJS 11 (Express 5), Node fetch + ReadableStream, Vue 3, Vitest, Jest. 기존 `/search` 엔드포인트와 keyword 분기는 보존.

**Design doc:** [2026-04-18-assist-stream-sse-design.md](2026-04-18-assist-stream-sse-design.md)

---

## 백엔드 (asst-service)

### Task 1: AssistStreamRequestDto 생성

**Files:**
- Create: `asst-service/src/advisor/assist-stream/dto/assist-stream-request.dto.ts`
- Create: `asst-service/src/advisor/assist-stream/dto/assist-stream-request.dto.spec.ts`

**Step 1: Write the failing test**

```typescript
// assist-stream-request.dto.spec.ts
import { validate } from 'class-validator';
import { plainToInstance } from 'class-transformer';
import { AssistStreamRequestDto } from './assist-stream-request.dto';

describe('AssistStreamRequestDto', () => {
  it('query가 비어있으면 실패', async () => {
    const dto = plainToInstance(AssistStreamRequestDto, { query: '' });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('query가 1000자 초과이면 실패', async () => {
    const dto = plainToInstance(AssistStreamRequestDto, { query: 'a'.repeat(1001) });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('정상 요청은 통과', async () => {
    const dto = plainToInstance(AssistStreamRequestDto, {
      query: '수수료 얼마야?',
      conversationHistory: [{ speaker: 'customer', content: '안녕' }],
      repositoryId: '00000000-0000-0000-0000-000000000001',
      callId: 'call-123',
    });
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('speaker가 잘못된 값이면 실패', async () => {
    const dto = plainToInstance(AssistStreamRequestDto, {
      query: 'q',
      conversationHistory: [{ speaker: 'bot', content: 'x' }],
    });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest assist-stream-request.dto.spec.ts`
Expected: FAIL (Cannot find module './assist-stream-request.dto')

**Step 3: Write minimal implementation**

```typescript
// assist-stream-request.dto.ts
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import {
  IsArray,
  IsIn,
  IsOptional,
  IsString,
  IsUUID,
  Length,
  MinLength,
  ValidateNested,
} from 'class-validator';

export class AssistStreamConversationItemDto {
  @ApiProperty({ enum: ['customer', 'agent'] })
  @IsString()
  @IsIn(['customer', 'agent'])
  speaker: 'customer' | 'agent';

  @ApiProperty()
  @IsString()
  @MinLength(1)
  content: string;
}

export class AssistStreamRequestDto {
  @ApiProperty({ description: '현재 고객 발화', minLength: 1, maxLength: 1000 })
  @IsString()
  @Length(1, 1000)
  query: string;

  @ApiPropertyOptional({ type: [AssistStreamConversationItemDto] })
  @IsOptional()
  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => AssistStreamConversationItemDto)
  conversationHistory?: AssistStreamConversationItemDto[];

  @ApiPropertyOptional({ description: '검색 저장소 ID (UUID)' })
  @IsOptional()
  @IsUUID()
  repositoryId?: string;

  @ApiPropertyOptional({ description: '통화 ID (로깅용)' })
  @IsOptional()
  @IsString()
  callId?: string;
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest assist-stream-request.dto.spec.ts`
Expected: PASS, 4 tests

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/dto/
git commit -m "feat: assist-stream 요청 DTO 추가

- query/conversationHistory/repositoryId/callId 필드 정의
- class-validator로 스키마 검증"
```

---

### Task 2: conversation history 변환 유틸

**Files:**
- Create: `asst-service/src/advisor/assist-stream/services/conversation-history.util.ts`
- Create: `asst-service/src/advisor/assist-stream/services/conversation-history.util.spec.ts`

**Step 1: Write the failing test**

```typescript
// conversation-history.util.spec.ts
import { toRagHistory } from './conversation-history.util';

describe('toRagHistory', () => {
  it('customer → user, agent → assistant로 변환', () => {
    const result = toRagHistory([
      { speaker: 'customer', content: '안녕' },
      { speaker: 'agent', content: '네' },
    ]);
    expect(result).toEqual([
      { role: 'user', content: '안녕' },
      { role: 'assistant', content: '네' },
    ]);
  });

  it('마지막 4개(2턴)만 남기고 앞쪽은 truncate', () => {
    const input = Array.from({ length: 10 }, (_, i) => ({
      speaker: i % 2 === 0 ? ('customer' as const) : ('agent' as const),
      content: `msg${i}`,
    }));
    const result = toRagHistory(input);
    expect(result).toHaveLength(4);
    expect(result[0].content).toBe('msg6');
    expect(result[3].content).toBe('msg9');
  });

  it('undefined/빈 배열이면 빈 배열 반환', () => {
    expect(toRagHistory(undefined)).toEqual([]);
    expect(toRagHistory([])).toEqual([]);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest conversation-history.util.spec.ts`
Expected: FAIL (Cannot find module)

**Step 3: Write minimal implementation**

```typescript
// conversation-history.util.ts
import { AssistStreamConversationItemDto } from '@app/advisor/assist-stream/dto/assist-stream-request.dto';

export interface RagHistoryItem {
  role: 'user' | 'assistant';
  content: string;
}

const MAX_HISTORY_MESSAGES = 4;

export function toRagHistory(
  history: AssistStreamConversationItemDto[] | undefined,
): RagHistoryItem[] {
  if (!history || history.length === 0) return [];
  const recent = history.slice(-MAX_HISTORY_MESSAGES);
  return recent.map((item) => ({
    role: item.speaker === 'customer' ? 'user' : 'assistant',
    content: item.content,
  }));
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest conversation-history.util.spec.ts`
Expected: PASS, 3 tests

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/services/conversation-history.util.ts asst-service/src/advisor/assist-stream/services/conversation-history.util.spec.ts
git commit -m "feat: assist-stream 대화 이력 변환 유틸 추가

- customer/agent → user/assistant 매핑
- 마지막 4 메시지(2턴) truncate"
```

---

### Task 3: AssistStreamService 스켈레톤 + 테넌트 해석

**Files:**
- Create: `asst-service/src/advisor/assist-stream/services/assist-stream.service.ts`
- Create: `asst-service/src/advisor/assist-stream/services/assist-stream.service.spec.ts`

**Step 1: Write the failing test**

```typescript
// assist-stream.service.spec.ts
import { Test } from '@nestjs/testing';
import { ConfigService } from '@nestjs/config';
import { AssistStreamService } from './assist-stream.service';
import { TenantConfigService } from '@app/common/services/tenant-config.service';

describe('AssistStreamService', () => {
  let service: AssistStreamService;
  let tenantConfigService: jest.Mocked<TenantConfigService>;

  beforeEach(async () => {
    tenantConfigService = {
      getTenantConfig: jest.fn(),
    } as unknown as jest.Mocked<TenantConfigService>;

    const moduleRef = await Test.createTestingModule({
      providers: [
        AssistStreamService,
        {
          provide: ConfigService,
          useValue: {
            get: (key: string) => {
              if (key === 'SEARCH_HOST') return 'http://rag.test';
              if (key === 'SEARCH_REPOSITORY_ID') return 'default-repo-id';
              return undefined;
            },
          },
        },
        { provide: TenantConfigService, useValue: tenantConfigService },
      ],
    }).compile();

    service = moduleRef.get(AssistStreamService);
  });

  describe('resolveTenantId', () => {
    it('Bearer 토큰에서 tenant_id 추출', async () => {
      tenantConfigService.getTenantConfig.mockResolvedValue({
        tenant_id: 'tenant-abc',
      } as any);

      const tenantId = await service['resolveTenantId']('token123');
      expect(tenantId).toBe('tenant-abc');
      expect(tenantConfigService.getTenantConfig).toHaveBeenCalledWith('token123');
    });
  });

  describe('buildUpstreamPayload', () => {
    it('dto → RAG 요청 바디 매핑', () => {
      const payload = service['buildUpstreamPayload']({
        query: '수수료 얼마야',
        conversationHistory: [
          { speaker: 'customer', content: '안녕' },
          { speaker: 'agent', content: '네' },
        ],
        repositoryId: 'repo-1',
      });
      expect(payload).toEqual({
        query: '수수료 얼마야',
        repository_id: 'repo-1',
        conversation_history: [
          { role: 'user', content: '안녕' },
          { role: 'assistant', content: '네' },
        ],
      });
    });

    it('repositoryId 없으면 env fallback', () => {
      const payload = service['buildUpstreamPayload']({
        query: 'q',
      });
      expect(payload.repository_id).toBe('default-repo-id');
    });
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest assist-stream.service.spec.ts`
Expected: FAIL (Cannot find module)

**Step 3: Write minimal implementation**

```typescript
// assist-stream.service.ts
import { HttpException, HttpStatus, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

import { TenantConfigService } from '@app/common/services/tenant-config.service';
import { AssistStreamRequestDto } from '@app/advisor/assist-stream/dto/assist-stream-request.dto';
import { toRagHistory } from '@app/advisor/assist-stream/services/conversation-history.util';

interface UpstreamPayload {
  query: string;
  repository_id: string;
  conversation_history: Array<{ role: 'user' | 'assistant'; content: string }>;
}

@Injectable()
export class AssistStreamService {
  private readonly logger = new Logger(AssistStreamService.name);
  private readonly searchHost: string;
  private readonly defaultRepositoryId: string;

  constructor(
    private readonly configService: ConfigService,
    private readonly tenantConfigService: TenantConfigService,
  ) {
    this.searchHost = (
      this.configService.get<string>('SEARCH_HOST') || ''
    ).replace(/\/+$/, '');
    this.defaultRepositoryId =
      this.configService.get<string>('SEARCH_REPOSITORY_ID') || '';
  }

  private async resolveTenantId(token: string): Promise<string> {
    const tenantConfig = await this.tenantConfigService.getTenantConfig(token);
    if (!tenantConfig?.tenant_id) {
      throw new HttpException(
        '테넌트 정보를 조회할 수 없습니다.',
        HttpStatus.UNAUTHORIZED,
      );
    }
    return tenantConfig.tenant_id;
  }

  private buildUpstreamPayload(dto: AssistStreamRequestDto): UpstreamPayload {
    return {
      query: dto.query,
      repository_id: dto.repositoryId || this.defaultRepositoryId,
      conversation_history: toRagHistory(dto.conversationHistory),
    };
  }
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest assist-stream.service.spec.ts`
Expected: PASS, 3 tests

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/services/assist-stream.service.ts asst-service/src/advisor/assist-stream/services/assist-stream.service.spec.ts
git commit -m "feat: AssistStreamService 기초 뼈대 추가

- Bearer 토큰 → tenant_id 해석
- dto → RAG 요청 바디 매핑"
```

---

### Task 4: AssistStreamService SSE 릴레이 구현

**Files:**
- Modify: `asst-service/src/advisor/assist-stream/services/assist-stream.service.ts`
- Modify: `asst-service/src/advisor/assist-stream/services/assist-stream.service.spec.ts`

**Step 1: Write the failing test**

```typescript
// 기존 spec에 추가
import { Response } from 'express';
import { Readable } from 'stream';

function mockSseUpstream(frames: string[], status = 200) {
  const stream = new ReadableStream({
    start(controller) {
      for (const f of frames) controller.enqueue(new TextEncoder().encode(f));
      controller.close();
    },
  });
  return {
    ok: status < 400,
    status,
    headers: new Headers({ 'Content-Type': 'text/event-stream' }),
    body: stream,
    text: async () => frames.join(''),
  } as unknown as Response;
}

describe('relay', () => {
  let mockRes: Partial<Response> & { written: string[]; ended: boolean; statusCode?: number };
  let abortSignal: AbortSignal;

  beforeEach(() => {
    const written: string[] = [];
    mockRes = {
      written,
      ended: false,
      setHeader: jest.fn(),
      status: jest.fn().mockReturnThis(),
      write: jest.fn((chunk: string) => {
        written.push(chunk);
        return true;
      }),
      end: jest.fn(function () {
        (this as any).ended = true;
      }),
      flushHeaders: jest.fn(),
    };
    abortSignal = new AbortController().signal;
  });

  it('업스트림 SSE 프레임을 그대로 릴레이', async () => {
    tenantConfigService.getTenantConfig.mockResolvedValue({ tenant_id: 't1' } as any);
    const fetchSpy = jest.spyOn(global, 'fetch').mockResolvedValue(
      mockSseUpstream([
        'event: sources\ndata: {"sources":[]}\n\n',
        'event: done\ndata: {"latency_ms":100}\n\n',
      ]) as any,
    );

    await service.stream(
      { query: 'q' } as any,
      'token',
      mockRes as Response,
      abortSignal,
    );

    expect(mockRes.setHeader).toHaveBeenCalledWith('Content-Type', 'text/event-stream');
    expect(mockRes.setHeader).toHaveBeenCalledWith('X-Accel-Buffering', 'no');
    expect(mockRes.written.join('')).toContain('event: sources');
    expect(mockRes.written.join('')).toContain('event: done');
    expect(mockRes.ended).toBe(true);

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('http://rag.test/api/v1/rag/assist-stream');
    expect((init as any).headers['X-Tenant-Id']).toBe('t1');
    fetchSpy.mockRestore();
  });

  it('업스트림 4xx (SSE 시작 전) → HttpException', async () => {
    tenantConfigService.getTenantConfig.mockResolvedValue({ tenant_id: 't1' } as any);
    const errorBody = { detail: 'Too many concurrent' };
    const fetchSpy = jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 429,
      text: async () => JSON.stringify(errorBody),
      headers: new Headers(),
    } as any);

    await expect(
      service.stream({ query: 'q' } as any, 'token', mockRes as Response, abortSignal),
    ).rejects.toMatchObject({ status: 429 });
    fetchSpy.mockRestore();
  });

  it('abort 시그널 → 업스트림 fetch에 전파', async () => {
    tenantConfigService.getTenantConfig.mockResolvedValue({ tenant_id: 't1' } as any);
    const controller = new AbortController();
    const fetchSpy = jest.spyOn(global, 'fetch').mockImplementation(((_u: any, init: any) => {
      return new Promise((_, reject) => {
        init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      });
    }) as any);

    const promise = service.stream(
      { query: 'q' } as any,
      'token',
      mockRes as Response,
      controller.signal,
    );
    controller.abort();
    await expect(promise).resolves.toBeUndefined();
    fetchSpy.mockRestore();
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest assist-stream.service.spec.ts`
Expected: FAIL (service.stream is not a function)

**Step 3: Write minimal implementation**

```typescript
// assist-stream.service.ts에 추가
import type { Response } from 'express';

// class 내부에 추가:

async stream(
  dto: AssistStreamRequestDto,
  token: string,
  res: Response,
  clientAbort: AbortSignal,
): Promise<void> {
  if (!this.searchHost) {
    throw new HttpException(
      'SEARCH_HOST가 설정되지 않았습니다.',
      HttpStatus.SERVICE_UNAVAILABLE,
    );
  }

  const tenantId = await this.resolveTenantId(token);
  const payload = this.buildUpstreamPayload(dto);
  const url = `${this.searchHost}/api/v1/rag/assist-stream`;

  const abortController = new AbortController();
  const onClientAbort = () => abortController.abort();
  clientAbort.addEventListener('abort', onClientAbort);

  let upstream: globalThis.Response;
  try {
    upstream = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'X-Tenant-Id': tenantId,
      },
      body: JSON.stringify(payload),
      signal: abortController.signal,
    });
  } catch (err) {
    clientAbort.removeEventListener('abort', onClientAbort);
    if ((err as Error).name === 'AbortError') return;
    this.logger.error(`RAG 서비스 연결 실패: ${(err as Error).message}`);
    throw new HttpException(
      '검색 서비스에 연결할 수 없습니다.',
      HttpStatus.SERVICE_UNAVAILABLE,
    );
  }

  if (!upstream.ok) {
    clientAbort.removeEventListener('abort', onClientAbort);
    const body = await upstream.text();
    this.logger.warn(`RAG 업스트림 에러: ${upstream.status} ${body}`);
    throw new HttpException(body || upstream.statusText, upstream.status);
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders?.();

  const reader = upstream.body!.getReader();
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      res.write(decoder.decode(value, { stream: true }));
    }
  } catch (err) {
    if ((err as Error).name !== 'AbortError') {
      this.logger.error(`SSE 릴레이 중단: ${(err as Error).message}`);
      res.write(
        `event: error\ndata: ${JSON.stringify({
          stage: 'unknown',
          code: 'internal_error',
          message: (err as Error).message,
        })}\n\n`,
      );
    }
  } finally {
    clientAbort.removeEventListener('abort', onClientAbort);
    res.end();
  }
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest assist-stream.service.spec.ts`
Expected: PASS, 6 tests total

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/services/assist-stream.service.ts asst-service/src/advisor/assist-stream/services/assist-stream.service.spec.ts
git commit -m "feat: assist-stream SSE 릴레이 구현

- fetch + ReadableStream으로 업스트림 프레임 pass-through
- X-Tenant-Id 자동 주입, 클라이언트 abort 전파
- 업스트림 4xx/5xx는 HttpException으로 변환"
```

---

### Task 5: AssistStreamController

**Files:**
- Create: `asst-service/src/advisor/assist-stream/controllers/assist-stream.controller.ts`
- Create: `asst-service/src/advisor/assist-stream/controllers/assist-stream.controller.spec.ts`

**Step 1: Write the failing test**

```typescript
// assist-stream.controller.spec.ts
import { Test } from '@nestjs/testing';
import { AssistStreamController } from './assist-stream.controller';
import { AssistStreamService } from '@app/advisor/assist-stream/services/assist-stream.service';

describe('AssistStreamController', () => {
  let controller: AssistStreamController;
  let service: jest.Mocked<AssistStreamService>;

  beforeEach(async () => {
    service = { stream: jest.fn() } as any;
    const moduleRef = await Test.createTestingModule({
      controllers: [AssistStreamController],
      providers: [{ provide: AssistStreamService, useValue: service }],
    }).compile();
    controller = moduleRef.get(AssistStreamController);
  });

  it('service.stream에 dto, token, res, signal 전달', async () => {
    const dto = { query: 'q' } as any;
    const mockReq = {
      token: 'tkn',
      on: jest.fn(),
    };
    const mockRes = {} as any;
    service.stream.mockResolvedValue(undefined);

    await controller.assistStream(dto, mockReq as any, mockRes);

    expect(service.stream).toHaveBeenCalledWith(
      dto,
      'tkn',
      mockRes,
      expect.any(AbortSignal),
    );
    expect(mockReq.on).toHaveBeenCalledWith('close', expect.any(Function));
  });

  it('req close 이벤트 → AbortController.abort() 호출', async () => {
    const dto = { query: 'q' } as any;
    let closeHandler: () => void = () => {};
    const mockReq = {
      token: 'tkn',
      on: jest.fn((evt: string, cb: () => void) => {
        if (evt === 'close') closeHandler = cb;
      }),
    };
    const mockRes = {} as any;
    let capturedSignal: AbortSignal | undefined;
    service.stream.mockImplementation(async (_d, _t, _r, sig) => {
      capturedSignal = sig;
    });

    await controller.assistStream(dto, mockReq as any, mockRes);
    closeHandler();
    expect(capturedSignal?.aborted).toBe(true);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest assist-stream.controller.spec.ts`
Expected: FAIL (Cannot find module)

**Step 3: Write minimal implementation**

```typescript
// assist-stream.controller.ts
import {
  Body,
  Controller,
  HttpCode,
  HttpStatus,
  Post,
  Req,
  Res,
} from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { Request, Response } from 'express';

import { AssistStreamRequestDto } from '@app/advisor/assist-stream/dto/assist-stream-request.dto';
import { AssistStreamService } from '@app/advisor/assist-stream/services/assist-stream.service';

@ApiTags('AI 상담 보조')
@ApiBearerAuth('bearer')
@Controller('assist-stream')
export class AssistStreamController {
  constructor(private readonly assistStreamService: AssistStreamService) {}

  @Post()
  @HttpCode(HttpStatus.OK)
  @ApiOperation({
    summary: '고객 발화 기반 상담 보조 SSE 스트림',
    description:
      '근거 문서(Top5), 요약, LLM 답변을 SSE로 순차 스트리밍. text/event-stream 응답.',
  })
  async assistStream(
    @Body() dto: AssistStreamRequestDto,
    @Req() req: Request & { token: string },
    @Res() res: Response,
  ): Promise<void> {
    const abortController = new AbortController();
    req.on('close', () => abortController.abort());
    await this.assistStreamService.stream(dto, req.token, res, abortController.signal);
  }
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest assist-stream.controller.spec.ts`
Expected: PASS, 2 tests

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/controllers/
git commit -m "feat: AssistStreamController 추가

- POST /assist-stream 엔드포인트
- req close → AbortController 연결"
```

---

### Task 6: advisor.module에 등록

**Files:**
- Modify: `asst-service/src/advisor/advisor.module.ts`

**Step 1: 현재 모듈 확인**

Run: `grep -n "SearchController\|SearchService" asst-service/src/advisor/advisor.module.ts`
Expected: import 라인과 controllers/providers 배열 위치 확인

**Step 2: import, controllers, providers 추가**

```typescript
// advisor.module.ts 상단 import 섹션에 추가
import { AssistStreamController } from '@app/advisor/assist-stream/controllers/assist-stream.controller';
import { AssistStreamService } from '@app/advisor/assist-stream/services/assist-stream.service';

// controllers 배열에 추가
AssistStreamController,

// providers 배열에 추가
AssistStreamService,
```

**Step 3: 빌드 검증**

Run: `cd asst-service && npm run build`
Expected: 에러 없이 완료

**Step 4: 로컬 기동 검증**

Run: `cd asst-service && npm run start:dev`
Expected: 로그에 `[RouterExplorer] Mapped {/assist-stream, POST}` 출력. Ctrl+C.

**Step 5: Commit**

```bash
git add asst-service/src/advisor/advisor.module.ts
git commit -m "feat: advisor 모듈에 AssistStream 등록

- AssistStreamController, AssistStreamService 추가"
```

---

### Task 7: 수동 통합 테스트 (curl)

**Files:** 없음 (검증만)

**Step 1: 서버 기동 확인**

Run: `cd asst-service && npm run start:dev`
백그라운드로 실행되거나 별도 터미널.

**Step 2: 일반 발화로 curl**

Run:
```bash
curl -N -X POST http://localhost:${PORT}/api/asst/v1/assist-stream \
  -H "Content-Type: application/json" \
  -H "x-auth-token: <로컬 테스트 토큰>" \
  -d '{
    "query": "수수료가 얼마야?",
    "conversationHistory": [
      {"speaker":"customer","content":"안녕"},
      {"speaker":"agent","content":"네 말씀하세요"}
    ]
  }'
```

Expected:
- `event: intent` → `event: sources` → `event: distilled` → `event: token × N` → `event: done` 순서로 출력
- 스트림이 즉시 중단되지 않고 토큰이 타이핑처럼 도착

**Step 3: 일상 대화 시나리오**

Run: 위 curl에서 query를 `"날씨 좋네요"` 로 변경
Expected:
- `event: intent` (search=false) → `event: sources` (sources=[]) → `event: token` (안내 1건) → `event: done`

**Step 4: abort 시나리오**

Run: curl 중간에 Ctrl+C
Expected: 서버 로그에 "SSE 릴레이 중단" 또는 abort 관련 로그 (장시간 LLM이 백그라운드에서 계속 도는 현상 없음)

**Step 5: 422 스키마 위반**

Run: `query` 없이 요청
Expected: HTTP 422, SSE 시작 전이므로 일반 JSON 에러

---

## 프론트엔드 (asst-web)

### Task 8: SSE 타입 정의

**Files:**
- Create: `asst-web/src/api/types/assist-stream.type.ts`

**Step 1: 타입 파일 생성**

```typescript
// asst-web/src/api/types/assist-stream.type.ts
export interface AssistStreamConversationItem {
  speaker: 'customer' | 'agent';
  content: string;
}

export interface AssistStreamReq {
  query: string;
  conversationHistory?: AssistStreamConversationItem[];
  repositoryId?: string;
  callId?: string;
}

export interface IntentEvent {
  search: boolean;
  reason: string;
  latency_ms: number;
  skipped: boolean;
}

export interface SourceItem {
  ref_num: number;
  document_id: string;
  chunk_id: string;
  document_title: string;
  section_title: string;
  content: string;
  score: number;
  token_count: number;
  page_info?: string;
  source_location?: { page_number?: number; bbox?: number[] };
}

export interface SourcesEvent {
  sources: SourceItem[];
  confidence: number;
  search_latency_ms: number;
  total_candidates: number;
}

export interface DistilledEvent {
  selected_refs: number[];
  summary: string;
  rationale: string;
  latency_ms: number;
}

export interface TokenEvent {
  text: string;
}

export interface DoneEvent {
  model_used: string | null;
  confidence: number;
  token_usage: {
    context_tokens: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  latency_ms: number;
  stages: {
    intent?: number;
    search?: number;
    distill?: number;
    generate?: number;
  };
}

export interface AssistStreamErrorEvent {
  stage: 'search' | 'generate' | 'unknown';
  code: string;
  message: string;
}

export interface AssistStreamHandlers {
  intent?: (e: IntentEvent) => void;
  sources?: (e: SourcesEvent) => void;
  distilled?: (e: DistilledEvent) => void;
  token?: (e: TokenEvent) => void;
  done?: (e: DoneEvent) => void;
  error?: (e: AssistStreamErrorEvent) => void;
}
```

**Step 2: 타입 컴파일 확인**

Run: `cd asst-web && npx vue-tsc --noEmit`
Expected: 추가 에러 없음

**Step 3: Commit**

```bash
git add asst-web/src/api/types/assist-stream.type.ts
git commit -m "feat: assist-stream SSE 이벤트 타입 추가

- intent/sources/distilled/token/done/error 타입 정의
- handlers 인터페이스"
```

---

### Task 9: SSE 프레임 파서 유틸

**Files:**
- Create: `asst-web/src/api/apis/sse-parser.ts`
- Create: `asst-web/src/api/apis/__tests__/sse-parser.spec.ts`

**Step 1: Write the failing test**

```typescript
// sse-parser.spec.ts
import { describe, it, expect, vi } from 'vitest';
import { parseSseStream } from '../sse-parser';

function toStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

describe('parseSseStream', () => {
  it('완전한 프레임 처리', async () => {
    const stream = toStream([
      'event: sources\ndata: {"x":1}\n\n',
      'event: done\ndata: {"y":2}\n\n',
    ]);
    const onEvent = vi.fn();
    await parseSseStream(stream, onEvent);
    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onEvent).toHaveBeenCalledWith('sources', { x: 1 });
    expect(onEvent).toHaveBeenCalledWith('done', { y: 2 });
  });

  it('청크가 프레임 중간에 끊겨도 버퍼링', async () => {
    const stream = toStream([
      'event: sou',
      'rces\ndata: {"x"',
      ':1}\n\n',
    ]);
    const onEvent = vi.fn();
    await parseSseStream(stream, onEvent);
    expect(onEvent).toHaveBeenCalledWith('sources', { x: 1 });
  });

  it('done 수신 시 조기 종료', async () => {
    const stream = toStream([
      'event: token\ndata: {"text":"a"}\n\n',
      'event: done\ndata: {}\n\n',
      'event: should_be_ignored\ndata: {}\n\n',
    ]);
    const onEvent = vi.fn();
    await parseSseStream(stream, onEvent);
    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onEvent).not.toHaveBeenCalledWith('should_be_ignored', expect.anything());
  });

  it('error 수신 시 조기 종료', async () => {
    const stream = toStream([
      'event: error\ndata: {"code":"x"}\n\n',
      'event: done\ndata: {}\n\n',
    ]);
    const onEvent = vi.fn();
    await parseSseStream(stream, onEvent);
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith('error', { code: 'x' });
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-web && npx vitest run sse-parser.spec`
Expected: FAIL (Cannot find module)

**Step 3: Write minimal implementation**

```typescript
// sse-parser.ts
export type SseEventHandler = (event: string, data: unknown) => void;

export async function parseSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: SseEventHandler,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';

      for (const frame of frames) {
        if (!frame.trim()) continue;
        const lines = frame.split('\n');
        const eventLine = lines.find((l) => l.startsWith('event:'));
        const dataLine = lines.find((l) => l.startsWith('data:'));
        if (!eventLine || !dataLine) continue;
        const event = eventLine.slice(6).trim();
        let data: unknown;
        try {
          data = JSON.parse(dataLine.slice(5).trim());
        } catch {
          continue;
        }
        onEvent(event, data);
        if (event === 'done' || event === 'error') return;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-web && npx vitest run sse-parser.spec`
Expected: PASS, 4 tests

**Step 5: Commit**

```bash
git add asst-web/src/api/apis/sse-parser.ts asst-web/src/api/apis/__tests__/sse-parser.spec.ts
git commit -m "feat: SSE 프레임 파서 유틸 추가

- ReadableStream → event/data 프레임 파싱
- 청크 경계 버퍼링, done/error 조기 종료"
```

---

### Task 10: AssistStreamAPI 래퍼

**Files:**
- Create: `asst-web/src/api/apis/assist-stream.api.ts`
- Modify: `asst-web/src/api/config/path.ts` (엔드포인트 경로 추가)

**Step 1: path.ts에 경로 추가**

`ADVISOR.API` 객체에 `ASSIST_STREAM: '/assist-stream'` 추가.

**Step 2: API 래퍼 구현**

```typescript
// asst-web/src/api/apis/assist-stream.api.ts
import { parseSseStream } from '@/api/apis/sse-parser';
import {
  AssistStreamHandlers,
  AssistStreamReq,
} from '@/api/types/assist-stream.type';
import { path } from '@/api/config/path';

const ENDPOINT = path.ADVISOR.API_PREFIX + path.ADVISOR.API.ASSIST_STREAM;

function getAuthHeader(): string | undefined {
  // 기존 APIInstance가 x-auth-token을 어떻게 얻는지와 동일한 방식 사용.
  // 저장소(예: localStorage) 또는 auth store에서 가져온다.
  // 실제 구현 시 기존 APIInstance/interceptor 재사용.
  return undefined;
}

export async function callAssistStream(
  req: AssistStreamReq,
  handlers: AssistStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const authToken = getAuthHeader();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  if (authToken) headers['x-auth-token'] = authToken;

  const res = await fetch(ENDPOINT, {
    method: 'POST',
    headers,
    body: JSON.stringify(req),
    signal,
  });

  if (!res.ok) {
    const body = await res.text();
    handlers.error?.({
      stage: 'unknown',
      code: `http_${res.status}`,
      message: body || res.statusText,
    });
    return;
  }

  if (!res.body) {
    handlers.error?.({
      stage: 'unknown',
      code: 'no_body',
      message: 'Response body is null',
    });
    return;
  }

  await parseSseStream(res.body, (event, data) => {
    const h = handlers as Record<string, ((d: unknown) => void) | undefined>;
    h[event]?.(data);
  });
}
```

**Step 3: 실제 토큰 조회 방식 맞추기**

기존 `DocumentSearchAPI` 또는 `APIInstance`가 토큰을 어떻게 조회하는지 확인 후 동일 방식 적용:

Run: `grep -n "x-auth-token\|authToken\|localStorage" asst-web/src/api/apis/document-search.api.ts asst-web/src/api/client/*.ts 2>&1 | head -20`

해당 패턴을 `getAuthHeader`에 복제하거나, 기존 `APIInstance.client` 인스턴스를 활용하는 방법 검토. axios 인스턴스를 쓰고 있다면 `axios.defaults.headers` 또는 interceptor에서 토큰을 가져오는 방식 재사용.

**Step 4: 타입 컴파일 확인**

Run: `cd asst-web && npx vue-tsc --noEmit`
Expected: 에러 없음

**Step 5: Commit**

```bash
git add asst-web/src/api/apis/assist-stream.api.ts asst-web/src/api/config/path.ts
git commit -m "feat: AssistStreamAPI 래퍼 추가

- fetch + ReadableStream + SSE 파서 통합
- /api/asst/v1/assist-stream 호출, 이벤트별 handler 디스패치"
```

---

### Task 11: chat/index.vue의 이중 호출 제거 및 단일 SSE 호출로 교체

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: 기존 코드 확인**

Run: `grep -n "handleKeywordSearch\|handleHybridSearch" asst-web/src/view/advisor/components/chat/index.vue`

L1545-1546 호출부, L1995-2158 `handleKeywordSearch`, L2160-2230+ `handleHybridSearch` 위치 확인.

**Step 2: 두 함수에서 공통 로직 파악**

두 함수가 공유하는 부분:
- 대화 이력 추출 (고객 1 + 상담사 1)
- messageId별 상태 관리 (search summary 로딩, 결과 매핑)
- 결과 → chat 버블 keyword 리스트 머지

**Step 3: `handleAssistStream(query, messageId)` 신규 함수 작성**

```typescript
// chat/index.vue <script> 내부
import { callAssistStream } from '@/api/apis/assist-stream.api';
import type {
  SourcesEvent,
  DistilledEvent,
  TokenEvent,
  IntentEvent,
  DoneEvent,
  AssistStreamErrorEvent,
} from '@/api/types/assist-stream.type';

const assistStreamControllers = new Map<string, AbortController>();

async function handleAssistStream(query: string, messageId: string) {
  // 이전 스트림이 있으면 취소
  const prev = assistStreamControllers.get(messageId);
  prev?.abort();
  const controller = new AbortController();
  assistStreamControllers.set(messageId, controller);

  const history = extractRecentConversation(); // 기존 handleKeywordSearch의 동일 로직 추출

  // 로딩/버퍼 초기화
  resetMessageAssistState(messageId);

  await callAssistStream(
    { query, conversationHistory: history, callId: currentCallId.value },
    {
      intent: (e: IntentEvent) => {
        if (!e.search) markMessageAsSmalltalk(messageId);
      },
      sources: (e: SourcesEvent) => {
        applySourcesToMessage(messageId, e.sources);
      },
      distilled: (e: DistilledEvent) => {
        applySummaryToMessage(messageId, e.summary, e.selected_refs);
      },
      token: (e: TokenEvent) => {
        appendAssistTokenToMessage(messageId, e.text);
      },
      done: (e: DoneEvent) => {
        finalizeMessageAssistState(messageId);
        console.debug('[assist-stream] stages', e.stages);
      },
      error: (e: AssistStreamErrorEvent) => {
        markMessageAssistError(messageId, e);
      },
    },
    controller.signal,
  );
}
```

**Step 4: L1545-1546 호출부 교체**

```typescript
// 기존
handleKeywordSearch(messageData.origin_text, messageId);
handleHybridSearch(messageData.origin_text, messageId);

// 변경
handleAssistStream(messageData.origin_text, messageId);
```

**Step 5: `handleKeywordSearch`, `handleHybridSearch` 함수 및 관련 상태 제거**

- 함수 본문 삭제
- 두 함수에서만 쓰이던 import, ref, 헬퍼 정리
- `DocumentSearchAPI` import는 다른 곳에서 쓰지 않으면 제거 (chat/index.vue 스코프 한정)

**Step 6: 기존 헬퍼 함수 매핑/신설**

`applySourcesToMessage`, `applySummaryToMessage`, `appendAssistTokenToMessage` 등은 기존 `handleHybridSearch`의 결과 머지 로직을 토대로 재조립한다. 기존 UI 슬롯(`ai_summary`, `aiSearchResultText`, `search_summary`)이 동일한 데이터 구조를 기대하도록 매핑.

- `applySourcesToMessage`: 기존 hybrid 결과 → `metadata.search_summary`를 채우던 자리에 `sources[]` 매핑. 문서 카드용 배열로 저장.
- `applySummaryToMessage`: `ai_summary` 필드에 `summary` 저장, `selected_refs`도 보관.
- `appendAssistTokenToMessage`: knowledge 패널의 `aiSearchResultText`와 연동되는 per-message 버퍼에 `+=`.
- `resetMessageAssistState`, `finalizeMessageAssistState`, `markMessageAsSmalltalk`, `markMessageAssistError`: 로딩/에러 상태 관리.

**Step 7: 컴포넌트 언마운트 시 모든 스트림 취소**

```typescript
onBeforeUnmount(() => {
  for (const [, ctrl] of assistStreamControllers) ctrl.abort();
  assistStreamControllers.clear();
});
```

**Step 8: 타입 컴파일 & 린트**

Run: `cd asst-web && npm run lint && npx vue-tsc --noEmit`
Expected: 에러 없음 (미사용 import/변수 경고 0)

**Step 9: 단위 테스트 스위트 실행**

Run: `cd asst-web && npm run test:unit`
Expected: 기존 테스트 PASS. (chat/index.vue 전용 테스트가 없으므로 추가 실패 없어야 함)

**Step 10: Commit**

```bash
git add asst-web/src/view/advisor/components/chat/index.vue
git commit -m "refactor: 고객 발화 자동 검색을 SSE assist-stream 단일 호출로 통합

- handleKeywordSearch/handleHybridSearch 병렬 호출 제거
- handleAssistStream 단일 함수로 intent/sources/distilled/token/done 처리
- AbortController로 메시지별 스트림 취소 관리
- sources → 참고문서, distilled.summary → AI 요약, token → AI 답변 영역 바인딩"
```

---

### Task 12: 브라우저 수동 검증

**Files:** 없음 (QA)

**Step 1: 개발 서버 기동**

Run: 별도 터미널 2개
- `cd asst-service && npm run start:dev`
- `cd asst-web && npm run dev`

**Step 2: 상담원 계정으로 로그인 → 통화 연결**

브라우저 DevTools > Network 탭 열고 `Fetch/XHR` 필터, `text/event-stream` 찾기.

**Step 3: 고객 발화 1회 시뮬레이션**

체크리스트:
- [ ] `POST /api/asst/v1/assist-stream` 요청이 1회만 발생 (keyword/hybrid 두 번 아님)
- [ ] 응답 헤더 `content-type: text/event-stream`
- [ ] 응답 본문 탭에서 `event: intent` → `event: sources` → `event: distilled` → `event: token × N` → `event: done` 순서 확인
- [ ] 지식 패널 **참고문서** 카드가 ~500ms 내 표시
- [ ] **AI 요약** 영역이 요약 문구로 채워짐 (~1.5s)
- [ ] **AI 답변** 영역이 타이핑처럼 토큰 누적 (~3s 완료)
- [ ] DevTools Console에 `[assist-stream] stages` 로그 확인

**Step 4: 일상 대화 시뮬레이션**

고객 발화가 "오늘 날씨 좋네요" 같은 비상담 발화일 때:
- [ ] 참고문서/요약 영역 숨김 또는 비어있음
- [ ] AI 답변 영역에 안내 문구 1회만 표시

**Step 5: 연속 발화 시 이전 스트림 abort**

고객 발화 2회 연속 (짧은 간격):
- [ ] 첫 발화 요청이 `canceled` 상태로 바뀜 (Network 탭)
- [ ] 두 번째 발화 결과가 UI에 덮어씀

**Step 6: 페이지 이탈**

통화 중 페이지 새로고침 또는 다른 화면 이동:
- [ ] 진행 중 SSE 요청이 `canceled`

**Step 7: 에러 시나리오 (선택)**

`SEARCH_HOST`를 잘못된 값으로 바꿔 재기동 → 발화:
- [ ] UI에 에러 안내, 패널이 로딩 상태로 멈추지 않고 복구

**Step 8: 기존 `/search` 흐름 회귀 테스트**

- [ ] ChatHistoryModal 열기 → 문서 검색 결과 정상 표시
- [ ] 지식 탭 수동 검색 → 정상 표시

---

### Task 13: 최종 타입체크 + 린트 + 빌드

**Step 1: asst-service**

Run: `cd asst-service && npm run lint && npm run build && npm test`
Expected: 모두 통과

**Step 2: asst-web**

Run: `cd asst-web && npm run lint && npm run test:unit && npm run build:dev`
Expected: 모두 통과

**Step 3: 모노레포 전체 git status 확인**

Run: `git status`
Expected: 커밋되지 않은 파일 없음 (이전 Task 커밋에 모두 포함)

**Step 4: 커밋 로그 확인**

Run: `git log --oneline | head -15`
Expected: Task 1~11의 커밋이 한국어 conventional commits 형식으로 순서대로 기록

---

## 롤아웃 체크리스트

- [ ] Design doc 승인 (완료)
- [ ] Task 1~13 구현 및 커밋
- [ ] 로컬 E2E 수동 검증 (Task 7, Task 12)
- [ ] 코드 리뷰 (superpowers:requesting-code-review)
- [ ] nginx/프록시 `proxy_buffering off`, `proxy_read_timeout 60s` 설정 운영팀 요청 (design doc 리스크 참고)
- [ ] 스테이징 배포 후 실제 상담 시나리오 1건 녹화

---

## 참고

- [설계 문서](2026-04-18-assist-stream-sse-design.md)
- [RAG assist-stream API 가이드](../../rag-assist-stream.md) — 외부 팀 전달 문서
- CLAUDE.md — 커밋 메시지 규칙, 절대 경로 import, path-to-regexp v8 유의
