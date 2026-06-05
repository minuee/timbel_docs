# AssistStream 스냅샷 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 라이브 채팅 RAG 응답(관련문서·hint·AI 요약·AI 답변)을 테넌트 DB에 저장해, 상담 이력 조회 시 라이브 표시와 동일한 내용을 재현한다.

**Architecture:** 신규 테이블 `advisor.callstat_assist_snapshot` 한 개 추가. 프론트가 SSE `done` 이벤트 후 `(call_id, turn_idx)` 키로 asst-service에 POST → upsert. 이력 조회 시 기존 `getCallStatById` 응답에 snapshot을 함께 내려 프론트가 `/search` 재호출 없이 저장값만 렌더.

**Tech Stack:** NestJS 11, TypeORM 0.3.x (PostgreSQL JSONB), Jest, Vue 3, Vitest. 기존 `/assist-stream` SSE 흐름은 그대로 유지.

**Design doc:** [2026-04-20-assist-snapshot-design.md](2026-04-20-assist-snapshot-design.md)

---

## 백엔드 (asst-service)

### Task 1: AssistSnapshotPayloadDto 생성

**Files:**
- Create: `asst-service/src/advisor/assist-stream/dto/assist-snapshot-payload.dto.ts`
- Create: `asst-service/src/advisor/assist-stream/dto/assist-snapshot-payload.dto.spec.ts`

**Step 1: Write the failing test**

```typescript
// assist-snapshot-payload.dto.spec.ts
import { validate } from 'class-validator';
import { plainToInstance } from 'class-transformer';
import { AssistSnapshotPayloadDto } from './assist-snapshot-payload.dto';

describe('AssistSnapshotPayloadDto', () => {
  const validPayload = {
    hint: '비대면 계좌개설 방법',
    sources: [
      {
        chunk_id: 'c1',
        document_id: 'd1',
        document_title: '문서1',
        section_title: '섹션1',
        content: '내용',
        score: 0.87,
        source_location: 'loc1',
        ref_num: 1,
      },
    ],
    distilled: { selected_refs: [1], summary: '요약', rationale: '근거' },
    answer: 'AI 답변 텍스트',
  };

  it('정상 payload 통과', async () => {
    const dto = plainToInstance(AssistSnapshotPayloadDto, validPayload);
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('hint 누락 시 실패', async () => {
    const dto = plainToInstance(AssistSnapshotPayloadDto, { ...validPayload, hint: undefined });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('sources 빈 배열 허용', async () => {
    const dto = plainToInstance(AssistSnapshotPayloadDto, { ...validPayload, sources: [] });
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('answer가 string이 아니면 실패', async () => {
    const dto = plainToInstance(AssistSnapshotPayloadDto, { ...validPayload, answer: 123 });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest assist-snapshot-payload.dto.spec.ts`
Expected: FAIL (Cannot find module './assist-snapshot-payload.dto')

**Step 3: Write minimal implementation**

```typescript
// assist-snapshot-payload.dto.ts
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import {
  IsArray,
  IsInt,
  IsNumber,
  IsOptional,
  IsString,
  ValidateNested,
} from 'class-validator';

export class AssistSnapshotSourceDto {
  @ApiProperty() @IsString() chunk_id: string;
  @ApiProperty() @IsString() document_id: string;
  @ApiProperty() @IsString() document_title: string;
  @ApiProperty() @IsString() section_title: string;
  @ApiProperty() @IsString() content: string;
  @ApiProperty() @IsNumber() score: number;
  @ApiProperty() @IsString() source_location: string;
  @ApiPropertyOptional() @IsOptional() @IsString() page_info?: string;
  @ApiProperty() @IsInt() ref_num: number;
}

export class AssistSnapshotDistilledDto {
  @ApiProperty({ type: [Number] }) @IsArray() @IsInt({ each: true }) selected_refs: number[];
  @ApiProperty() @IsString() summary: string;
  @ApiProperty() @IsString() rationale: string;
}

export class AssistSnapshotPayloadDto {
  @ApiProperty() @IsString() hint: string;

  @ApiProperty({ type: [AssistSnapshotSourceDto] })
  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => AssistSnapshotSourceDto)
  sources: AssistSnapshotSourceDto[];

  @ApiProperty({ type: AssistSnapshotDistilledDto })
  @ValidateNested()
  @Type(() => AssistSnapshotDistilledDto)
  distilled: AssistSnapshotDistilledDto;

  @ApiProperty() @IsString() answer: string;
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest assist-snapshot-payload.dto.spec.ts`
Expected: PASS (4/4)

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/dto/assist-snapshot-payload.dto.ts \
        asst-service/src/advisor/assist-stream/dto/assist-snapshot-payload.dto.spec.ts
git commit -m "feat: AssistSnapshot payload DTO 추가

- sources, distilled, hint, answer 필드 구조 정의
- class-validator 기반 validation"
```

---

### Task 2: SaveAssistSnapshotRequestDto 생성

**Files:**
- Create: `asst-service/src/advisor/assist-stream/dto/save-assist-snapshot.dto.ts`
- Create: `asst-service/src/advisor/assist-stream/dto/save-assist-snapshot.dto.spec.ts`

**Step 1: Write the failing test**

```typescript
// save-assist-snapshot.dto.spec.ts
import { validate } from 'class-validator';
import { plainToInstance } from 'class-transformer';
import { SaveAssistSnapshotRequestDto } from './save-assist-snapshot.dto';

describe('SaveAssistSnapshotRequestDto', () => {
  const validPayload = {
    hint: 'h',
    sources: [],
    distilled: { selected_refs: [], summary: '', rationale: '' },
    answer: '',
  };

  it('정상 요청 통과', async () => {
    const dto = plainToInstance(SaveAssistSnapshotRequestDto, {
      callId: '693375345978',
      turnIdx: 1,
      customerQuery: '질문',
      payload: validPayload,
    });
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });

  it('callId 누락 시 실패', async () => {
    const dto = plainToInstance(SaveAssistSnapshotRequestDto, {
      turnIdx: 1,
      payload: validPayload,
    });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('turnIdx가 음수이면 실패', async () => {
    const dto = plainToInstance(SaveAssistSnapshotRequestDto, {
      callId: 'c1',
      turnIdx: -1,
      payload: validPayload,
    });
    const errors = await validate(dto);
    expect(errors.length).toBeGreaterThan(0);
  });

  it('customerQuery는 optional', async () => {
    const dto = plainToInstance(SaveAssistSnapshotRequestDto, {
      callId: 'c1',
      turnIdx: 1,
      payload: validPayload,
    });
    const errors = await validate(dto);
    expect(errors).toHaveLength(0);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest save-assist-snapshot.dto.spec.ts`
Expected: FAIL

**Step 3: Write minimal implementation**

```typescript
// save-assist-snapshot.dto.ts
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsInt, IsOptional, IsString, Min, ValidateNested } from 'class-validator';

import { AssistSnapshotPayloadDto } from '@app/advisor/assist-stream/dto/assist-snapshot-payload.dto';

export class SaveAssistSnapshotRequestDto {
  @ApiProperty({ description: '통화 ID' })
  @IsString()
  callId: string;

  @ApiProperty({ description: '턴 인덱스 (STT 발급)' })
  @IsInt()
  @Min(0)
  turnIdx: number;

  @ApiPropertyOptional({ description: '마스킹된 고객 발화' })
  @IsOptional()
  @IsString()
  customerQuery?: string;

  @ApiProperty({ type: AssistSnapshotPayloadDto })
  @ValidateNested()
  @Type(() => AssistSnapshotPayloadDto)
  payload: AssistSnapshotPayloadDto;
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest save-assist-snapshot.dto.spec.ts`
Expected: PASS (4/4)

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/dto/save-assist-snapshot.dto.ts \
        asst-service/src/advisor/assist-stream/dto/save-assist-snapshot.dto.spec.ts
git commit -m "feat: AssistSnapshot 저장 요청 DTO 추가

- callId, turnIdx, customerQuery, payload 필드 검증"
```

---

### Task 3: CallstatAssistSnapshot 엔티티 생성

**Files:**
- Create: `asst-service/src/advisor/call/entities/callstat-assist-snapshot.entity.ts`

**Step 1: Write the entity**

```typescript
// callstat-assist-snapshot.entity.ts
import { ApiProperty } from '@nestjs/swagger';

import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  PrimaryGeneratedColumn,
  Unique,
} from 'typeorm';

import type { AssistSnapshotPayloadDto } from '@app/advisor/assist-stream/dto/assist-snapshot-payload.dto';

@Entity('callstat_assist_snapshot', { schema: 'advisor' })
@Unique('uq_assist_snapshot', ['call_id', 'turn_idx'])
@Index('idx_assist_snapshot_call_id', ['call_id'])
export class CallstatAssistSnapshot {
  @ApiProperty({ description: '스냅샷 ID' })
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @ApiProperty({ description: '통화 ID (raw call id)' })
  @Column({ type: 'varchar', length: 128 })
  call_id: string;

  @ApiProperty({ description: '턴 인덱스 (STT 발급)' })
  @Column({ type: 'int4' })
  turn_idx: number;

  @ApiProperty({ description: '마스킹된 고객 발화 (매칭 보강용)' })
  @Column({ type: 'text', nullable: true })
  customer_query: string | null;

  @ApiProperty({ description: '스냅샷 payload (sources, hint, distilled, answer)' })
  @Column({ type: 'jsonb' })
  payload: AssistSnapshotPayloadDto;

  @ApiProperty({ description: '생성일' })
  @CreateDateColumn({ type: 'timestamptz', default: () => 'now()' })
  created_at: Date;
}
```

**Step 2: Commit**

```bash
git add asst-service/src/advisor/call/entities/callstat-assist-snapshot.entity.ts
git commit -m "feat: CallstatAssistSnapshot 엔티티 추가

- advisor.callstat_assist_snapshot 테이블 매핑
- (call_id, turn_idx) 복합 유니크 키"
```

---

### Task 4: 마이그레이션 SQL 작성 + database.config 등록

**Files:**
- Create: `asst-service/migrations/create_callstat_assist_snapshot_table.sql`
- Modify: `asst-service/src/config/database.config.ts`

**Step 1: Create migration SQL**

```sql
-- asst-service/migrations/create_callstat_assist_snapshot_table.sql
-- AssistStream 라이브 응답 스냅샷 테이블

CREATE TABLE IF NOT EXISTS advisor.callstat_assist_snapshot (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id VARCHAR(128) NOT NULL,
    turn_idx INT NOT NULL,
    customer_query TEXT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_assist_snapshot UNIQUE (call_id, turn_idx)
);

CREATE INDEX IF NOT EXISTS idx_assist_snapshot_call_id
    ON advisor.callstat_assist_snapshot (call_id);

COMMENT ON TABLE advisor.callstat_assist_snapshot IS '라이브 AssistStream 응답 스냅샷 (상담 이력 재현용)';
COMMENT ON COLUMN advisor.callstat_assist_snapshot.call_id IS '통화 ID (orchestrator:started 이벤트 원본)';
COMMENT ON COLUMN advisor.callstat_assist_snapshot.turn_idx IS 'STT 발급 턴 인덱스';
COMMENT ON COLUMN advisor.callstat_assist_snapshot.customer_query IS '마스킹된 고객 발화 (매칭 보강)';
COMMENT ON COLUMN advisor.callstat_assist_snapshot.payload IS 'sources + hint + distilled + answer 전체 스냅샷 JSONB';
```

**Step 2: Register entity in database.config.ts**

파일 맨 위 `entities` 배열 관련 import 섹션에 추가:

```typescript
// asst-service/src/config/database.config.ts
import { CallstatAssistSnapshot } from '@app/advisor/call/entities/callstat-assist-snapshot.entity';
```

`entities` 배열에 `CallstatAssistSnapshot` 항목 추가.

**Step 3: Run asst-service locally to verify synchronize creates the table**

Run: `cd asst-service && npm run start:dev`
Expected: 로그에 `CREATE TABLE "advisor"."callstat_assist_snapshot"` 확인

로그 확인 후 Ctrl+C로 종료.

**Step 4: Commit**

```bash
git add asst-service/migrations/create_callstat_assist_snapshot_table.sql \
        asst-service/src/config/database.config.ts
git commit -m "feat: callstat_assist_snapshot 테이블 마이그레이션 추가

- advisor 스키마에 신규 테이블 생성
- database.config.ts entities 배열 등록"
```

---

### Task 5: AssistSnapshotService 구현 (upsert)

**Files:**
- Create: `asst-service/src/advisor/assist-stream/services/assist-snapshot.service.ts`
- Create: `asst-service/src/advisor/assist-stream/services/assist-snapshot.service.spec.ts`

**Step 1: Write the failing test**

```typescript
// assist-snapshot.service.spec.ts
import { Test, TestingModule } from '@nestjs/testing';
import { Repository } from 'typeorm';
import { getRepositoryToken } from '@nestjs/typeorm';

import { CallstatAssistSnapshot } from '@app/advisor/call/entities/callstat-assist-snapshot.entity';
import { AssistSnapshotService } from './assist-snapshot.service';
import type { SaveAssistSnapshotRequestDto } from '@app/advisor/assist-stream/dto/save-assist-snapshot.dto';

describe('AssistSnapshotService', () => {
  let service: AssistSnapshotService;
  let repo: jest.Mocked<Repository<CallstatAssistSnapshot>>;

  const baseDto: SaveAssistSnapshotRequestDto = {
    callId: '693375345978',
    turnIdx: 1,
    customerQuery: '질문',
    payload: {
      hint: 'h',
      sources: [],
      distilled: { selected_refs: [], summary: '', rationale: '' },
      answer: '',
    },
  };

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        AssistSnapshotService,
        {
          provide: getRepositoryToken(CallstatAssistSnapshot),
          useValue: { upsert: jest.fn(), find: jest.fn() },
        },
      ],
    }).compile();

    service = module.get(AssistSnapshotService);
    repo = module.get(getRepositoryToken(CallstatAssistSnapshot));
  });

  it('save는 (call_id, turn_idx) 키로 upsert를 호출한다', async () => {
    repo.upsert.mockResolvedValue({ identifiers: [], generatedMaps: [], raw: [] });
    await service.save(baseDto);
    expect(repo.upsert).toHaveBeenCalledWith(
      expect.objectContaining({
        call_id: '693375345978',
        turn_idx: 1,
        customer_query: '질문',
        payload: baseDto.payload,
      }),
      ['call_id', 'turn_idx'],
    );
  });

  it('findByCallId는 call_id 기준으로 조회한다', async () => {
    repo.find.mockResolvedValue([]);
    await service.findByCallId('c1');
    expect(repo.find).toHaveBeenCalledWith({
      where: { call_id: 'c1' },
      order: { turn_idx: 'ASC' },
    });
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest assist-snapshot.service.spec.ts`
Expected: FAIL (Cannot find module './assist-snapshot.service')

**Step 3: Write minimal implementation**

```typescript
// assist-snapshot.service.ts
import { Injectable, Logger } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';

import { CallstatAssistSnapshot } from '@app/advisor/call/entities/callstat-assist-snapshot.entity';
import { SaveAssistSnapshotRequestDto } from '@app/advisor/assist-stream/dto/save-assist-snapshot.dto';

@Injectable()
export class AssistSnapshotService {
  private readonly logger = new Logger(AssistSnapshotService.name);

  constructor(
    @InjectRepository(CallstatAssistSnapshot)
    private readonly repo: Repository<CallstatAssistSnapshot>,
  ) {}

  async save(dto: SaveAssistSnapshotRequestDto): Promise<void> {
    await this.repo.upsert(
      {
        call_id: dto.callId,
        turn_idx: dto.turnIdx,
        customer_query: dto.customerQuery ?? null,
        payload: dto.payload,
      },
      ['call_id', 'turn_idx'],
    );
  }

  async findByCallId(callId: string): Promise<CallstatAssistSnapshot[]> {
    return this.repo.find({
      where: { call_id: callId },
      order: { turn_idx: 'ASC' },
    });
  }
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest assist-snapshot.service.spec.ts`
Expected: PASS (2/2)

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/services/assist-snapshot.service.ts \
        asst-service/src/advisor/assist-stream/services/assist-snapshot.service.spec.ts
git commit -m "feat: AssistSnapshotService 구현

- save: (call_id, turn_idx) upsert
- findByCallId: call_id 기준 turn_idx 오름차순 조회"
```

---

### Task 6: AssistSnapshotController 구현

**Files:**
- Create: `asst-service/src/advisor/assist-stream/controllers/assist-snapshot.controller.ts`
- Create: `asst-service/src/advisor/assist-stream/controllers/assist-snapshot.controller.spec.ts`

**Step 1: Write the failing test**

```typescript
// assist-snapshot.controller.spec.ts
import { Test, TestingModule } from '@nestjs/testing';

import { AssistSnapshotController } from './assist-snapshot.controller';
import { AssistSnapshotService } from '@app/advisor/assist-stream/services/assist-snapshot.service';
import type { SaveAssistSnapshotRequestDto } from '@app/advisor/assist-stream/dto/save-assist-snapshot.dto';

describe('AssistSnapshotController', () => {
  let controller: AssistSnapshotController;
  let service: jest.Mocked<AssistSnapshotService>;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      controllers: [AssistSnapshotController],
      providers: [
        { provide: AssistSnapshotService, useValue: { save: jest.fn() } },
      ],
    }).compile();

    controller = module.get(AssistSnapshotController);
    service = module.get(AssistSnapshotService);
  });

  it('POST /assist-stream/snapshot은 서비스 save를 호출하고 204 메시지를 반환한다', async () => {
    const dto: SaveAssistSnapshotRequestDto = {
      callId: 'c1',
      turnIdx: 1,
      payload: {
        hint: 'h',
        sources: [],
        distilled: { selected_refs: [], summary: '', rationale: '' },
        answer: '',
      },
    };
    service.save.mockResolvedValue(undefined);
    const result = await controller.save(dto);
    expect(service.save).toHaveBeenCalledWith(dto);
    expect(result).toEqual({ success: true });
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest assist-snapshot.controller.spec.ts`
Expected: FAIL

**Step 3: Write minimal implementation**

```typescript
// assist-snapshot.controller.ts
import { Body, Controller, HttpCode, Post } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';

import { AssistSnapshotService } from '@app/advisor/assist-stream/services/assist-snapshot.service';
import { SaveAssistSnapshotRequestDto } from '@app/advisor/assist-stream/dto/save-assist-snapshot.dto';

@ApiTags('assist-stream')
@Controller('assist-stream/snapshot')
export class AssistSnapshotController {
  constructor(private readonly service: AssistSnapshotService) {}

  @Post()
  @HttpCode(200)
  @ApiOperation({ summary: 'AssistStream 라이브 응답 스냅샷 저장 (upsert)' })
  async save(@Body() dto: SaveAssistSnapshotRequestDto): Promise<{ success: true }> {
    await this.service.save(dto);
    return { success: true };
  }
}
```

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest assist-snapshot.controller.spec.ts`
Expected: PASS (1/1)

**Step 5: Commit**

```bash
git add asst-service/src/advisor/assist-stream/controllers/assist-snapshot.controller.ts \
        asst-service/src/advisor/assist-stream/controllers/assist-snapshot.controller.spec.ts
git commit -m "feat: AssistSnapshotController 추가

- POST /assist-stream/snapshot 엔드포인트
- AuthMiddleware 통과 (테넌트 DB)"
```

---

### Task 7: AssistStreamModule에 신규 Provider 등록

**Files:**
- Modify: `asst-service/src/advisor/assist-stream/assist-stream.module.ts`

**Step 1: Module 수정**

```typescript
// assist-stream.module.ts (예상 구조 — 실제 파일에 맞춰 수정)
import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';

import { CallstatAssistSnapshot } from '@app/advisor/call/entities/callstat-assist-snapshot.entity';
import { AssistStreamController } from '@app/advisor/assist-stream/controllers/assist-stream.controller';
import { AssistSnapshotController } from '@app/advisor/assist-stream/controllers/assist-snapshot.controller';
import { AssistStreamService } from '@app/advisor/assist-stream/services/assist-stream.service';
import { AssistSnapshotService } from '@app/advisor/assist-stream/services/assist-snapshot.service';

@Module({
  imports: [TypeOrmModule.forFeature([CallstatAssistSnapshot])],
  controllers: [AssistStreamController, AssistSnapshotController],
  providers: [AssistStreamService, AssistSnapshotService],
  exports: [AssistSnapshotService],
})
export class AssistStreamModule {}
```

**Step 2: Verify build**

Run: `cd asst-service && npm run build`
Expected: 타입 에러 없음

**Step 3: Verify server starts**

Run: `cd asst-service && npm run start:dev`
Expected: 로그에 `Mapped {/api/asst/v1/assist-stream/snapshot, POST}` 확인. Ctrl+C 종료.

**Step 4: Commit**

```bash
git add asst-service/src/advisor/assist-stream/assist-stream.module.ts
git commit -m "feat: AssistStreamModule에 Snapshot Controller/Service 등록

- TypeOrmModule.forFeature 에 엔티티 등록
- AssistSnapshotService export (CallModule에서 사용)"
```

---

### Task 8: AuthMiddleware exclude 경로 검증

**Files:**
- Modify (확인만): `asst-service/src/app.module.ts`

**Step 1: Check exclude patterns**

`app.module.ts`에서 `MiddlewareConsumer.apply(AuthMiddleware).exclude(...)` 블록 확인.
현재 `'assist-stream'`만 exclude 되어 있어야 함. `/assist-stream/snapshot`은 **exclude 대상 아님** — 테넌트 DB 접근 필수.

**Step 2: 확인 기준**

- path-to-regexp v8 패턴상 `.exclude('assist-stream')`이 정확히 `/assist-stream` 한 경로만 제외하는지 확인
- 만약 prefix match라면 `{*path}` wildcard가 포함되지 않았는지 명시 검증

**Step 3: 테스트 실행**

Run: `cd asst-service && npm run start:dev`

curl 테스트:
```bash
# 토큰 없이 snapshot POST → 401 기대
curl -sS -o /dev/null -w "%{http_code}\n" -X POST \
  "http://localhost:5001/api/asst/v1/assist-stream/snapshot" \
  -H "Content-Type: application/json" \
  -d '{"callId":"x","turnIdx":0,"payload":{"hint":"","sources":[],"distilled":{"selected_refs":[],"summary":"","rationale":""},"answer":""}}'
```
Expected: `401`

토큰 없는 /assist-stream은:
```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X POST \
  "http://localhost:5001/api/asst/v1/assist-stream" \
  -H "Content-Type: application/json" \
  -d '{"query":"q"}'
```
Expected: 400 or 503 (auth 우회 확인 — 401이 아니어야 함)

**Step 4: 필요시 코드 수정 + 커밋**

exclude가 prefix match가 아닌 exact match인 경우 수정 불필요. prefix match이면:
```typescript
.exclude(
  { path: 'assist-stream', method: RequestMethod.POST },
  { path: 'health/check', method: RequestMethod.GET },
)
```
형태로 method/path 쌍 명시.

**Step 5: Commit (수정한 경우에만)**

```bash
git add asst-service/src/app.module.ts
git commit -m "fix: AuthMiddleware exclude를 exact path match로 고정

- /assist-stream/snapshot이 잘못 제외되지 않도록 POST /assist-stream만 지정"
```

---

### Task 9: CallstatService에 snapshot 조회 추가

**Files:**
- Modify: `asst-service/src/advisor/call/services/callstat.service.ts`
- Modify: `asst-service/src/advisor/call/services/callstat.service.spec.ts` (기존 존재 가정, 없으면 create)
- Modify: `asst-service/src/advisor/call/call.module.ts` (AssistStreamModule import 추가)

**Step 1: Write the failing test**

`callstat.service.spec.ts`에 추가:

```typescript
it('getCallStatById는 응답에 snapshots 배열을 포함한다', async () => {
  // 기존 mock setup에 이어서
  const mockSnapshots = [
    { id: 's1', call_id: 'callX', turn_idx: 1, customer_query: 'q1', payload: { hint: 'h1', sources: [], distilled: { selected_refs: [], summary: '', rationale: '' }, answer: '' }, created_at: new Date() },
  ];
  assistSnapshotService.findByCallId.mockResolvedValue(mockSnapshots);

  // call에 call_id가 있어야 함 (callstats_call.call_id 필드)
  mockCallRepo.findOne.mockResolvedValue({ id: 'callstatsX', call_id: 'callX', /* ... */ });

  const result = await service.getCallStatById('callstatsX');

  expect(assistSnapshotService.findByCallId).toHaveBeenCalledWith('callX');
  expect(result.snapshots).toEqual(mockSnapshots);
});
```

**Step 2: Run test to verify it fails**

Run: `cd asst-service && npx jest callstat.service.spec.ts`
Expected: FAIL

**Step 3: Implement**

`callstat.service.ts` 수정:
- 생성자에 `AssistSnapshotService` 주입
- `getCallStatById` 메서드 내 기존 조회 후, `this.assistSnapshotService.findByCallId(call.call_id)` 결과를 응답 객체의 `snapshots` 필드에 추가

```typescript
// callstat.service.ts (수정 예시 — 기존 시그니처 유지하며 필드 추가)
import { AssistSnapshotService } from '@app/advisor/assist-stream/services/assist-snapshot.service';

constructor(
  // ... 기존 주입
  private readonly assistSnapshotService: AssistSnapshotService,
) {}

async getCallStatById(callstatsId: string) {
  const call = await this.callRepo.findOne({ where: { id: callstatsId } });
  // ... 기존 turns, entities, keywords 조회
  const snapshots = call?.call_id
    ? await this.assistSnapshotService.findByCallId(call.call_id)
    : [];
  return { call, turns, entities, keywords, snapshots };
}
```

`call.module.ts` 수정: `imports: [..., AssistStreamModule]`

**Step 4: Run test to verify it passes**

Run: `cd asst-service && npx jest callstat.service.spec.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add asst-service/src/advisor/call/services/callstat.service.ts \
        asst-service/src/advisor/call/services/callstat.service.spec.ts \
        asst-service/src/advisor/call/call.module.ts
git commit -m "feat: 이력 조회 응답에 snapshots 포함

- CallstatService.getCallStatById에서 call_id로 snapshot 조회
- 응답 DTO에 snapshots 배열 추가"
```

---

### Task 10: 이력 조회 응답 DTO에 snapshots 필드 추가

**Files:**
- Modify: `asst-service/src/advisor/call/dto/*call-stat*.dto.ts` (응답 DTO 파일 — 실제 파일명 확인 필요)

**Step 1: DTO에 snapshots 필드 추가**

```typescript
import { ApiProperty } from '@nestjs/swagger';
import { CallstatAssistSnapshot } from '@app/advisor/call/entities/callstat-assist-snapshot.entity';

// 응답 DTO 클래스에 추가:
@ApiProperty({
  type: [CallstatAssistSnapshot],
  description: '라이브 AssistStream 스냅샷 (이력 재현용)',
})
snapshots: CallstatAssistSnapshot[];
```

**Step 2: Swagger 문서 확인**

Run: `cd asst-service && npm run start:dev`
브라우저: `http://localhost:5001/api/asst/v1/doc`
Expected: `GET /callstat/calls/{id}` 응답 스키마에 `snapshots` 포함 확인

**Step 3: Commit**

```bash
git add asst-service/src/advisor/call/dto/
git commit -m "docs: 이력 조회 응답 DTO에 snapshots 필드 추가

- Swagger 스키마 반영"
```

---

## 프론트엔드 (asst-web)

### Task 11: API path 상수 + API 함수 추가

**Files:**
- Modify: `asst-web/src/api/config/path.ts`
- Create: `asst-web/src/api/apis/assist-snapshot.api.ts`

**Step 1: Path 상수 추가**

`path.ts`의 ADVISOR 섹션에 추가:

```typescript
ASSIST_STREAM_SNAPSHOT: '/assist-stream/snapshot',
```

**Step 2: API 함수 구현 (재시도 포함)**

```typescript
// asst-web/src/api/apis/assist-snapshot.api.ts
import { request } from '@/api/modules/request';
import { PATH } from '@/api/config/path';

export interface AssistSnapshotPayload {
  hint: string;
  sources: Array<{
    chunk_id: string;
    document_id: string;
    document_title: string;
    section_title: string;
    content: string;
    score: number;
    source_location: string;
    page_info?: string;
    ref_num: number;
  }>;
  distilled: {
    selected_refs: number[];
    summary: string;
    rationale: string;
  };
  answer: string;
}

export interface SaveAssistSnapshotBody {
  callId: string;
  turnIdx: number;
  customerQuery?: string;
  payload: AssistSnapshotPayload;
}

const RETRY_DELAYS_MS = [500, 1000, 2000];

export async function saveAssistSnapshot(body: SaveAssistSnapshotBody): Promise<void> {
  let lastError: unknown;
  for (let attempt = 0; attempt < RETRY_DELAYS_MS.length; attempt++) {
    try {
      await request.post(`${PATH.ADVISOR}${PATH.ASSIST_STREAM_SNAPSHOT}`, body);
      return;
    } catch (err) {
      lastError = err;
      await new Promise((r) => setTimeout(r, RETRY_DELAYS_MS[attempt]));
    }
  }
  console.warn('[AssistSnapshot] save failed after retries', lastError);
}
```

**Step 3: Vitest 단위 테스트**

```typescript
// asst-web/src/api/apis/__tests__/assist-snapshot.api.spec.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { saveAssistSnapshot } from '@/api/apis/assist-snapshot.api';
import { request } from '@/api/modules/request';

vi.mock('@/api/modules/request', () => ({
  request: { post: vi.fn() },
}));

describe('saveAssistSnapshot', () => {
  beforeEach(() => vi.clearAllMocks());

  it('성공 시 즉시 종료', async () => {
    (request.post as any).mockResolvedValue({ data: { success: true } });
    await saveAssistSnapshot({
      callId: 'c1', turnIdx: 1,
      payload: { hint: '', sources: [], distilled: { selected_refs: [], summary: '', rationale: '' }, answer: '' },
    });
    expect(request.post).toHaveBeenCalledTimes(1);
  });

  it('실패 시 최대 3회 재시도 후 silent 종료', async () => {
    (request.post as any).mockRejectedValue(new Error('network'));
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    await saveAssistSnapshot({
      callId: 'c1', turnIdx: 1,
      payload: { hint: '', sources: [], distilled: { selected_refs: [], summary: '', rationale: '' }, answer: '' },
    });
    expect(request.post).toHaveBeenCalledTimes(3);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
}, 30_000);
```

**Step 4: Run tests**

Run: `cd asst-web && npm run test:unit -- assist-snapshot.api`
Expected: PASS (2/2)

**Step 5: Commit**

```bash
git add asst-web/src/api/config/path.ts \
        asst-web/src/api/apis/assist-snapshot.api.ts \
        asst-web/src/api/apis/__tests__/assist-snapshot.api.spec.ts
git commit -m "feat: AssistSnapshot 저장 API 함수 추가

- 지수 백오프 3회 재시도 (500ms, 1s, 2s)
- 최종 실패 시 silent fail + console.warn"
```

---

### Task 12: 채팅 컴포넌트에 snapshotBuffer + POST 연결

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: 변경 범위 요약**

- 현재 turn_idx 추적: STT 이벤트(`stt:final` / `nlp:complete`) 수신 시 `currentTurnIdx` + `currentMaskedQuery`에 저장
- `snapshotBuffer` ref 추가: SSE 이벤트별로 누적
- `sources`, `distilled`, `token`, `done` 핸들러에 누적 로직 추가
- `done` 이벤트 말미에서 `saveAssistSnapshot` 호출
- `extractDemoTitle` 로직은 **데모 시연 위해 유지**. `snapshot.hint`에는 `extractDemoTitle` 결과를 그대로 저장해 라이브와 이력이 동일한 "Q. ..." 표시를 갖도록 함. 데모 종료 후 별도 태스크로 제거 예정 (document_title 폴백으로 전환)

**Step 2: 구현 — snapshotBuffer 선언**

`<script setup>` 상단 (기존 ref 모음 근처):

```typescript
import { saveAssistSnapshot, type AssistSnapshotPayload } from '@/api/apis/assist-snapshot.api';

const currentTurnIdx = ref<number | null>(null);
const currentMaskedQuery = ref<string>('');
const snapshotBuffer = ref<AssistSnapshotPayload>({
  hint: '',
  sources: [],
  distilled: { selected_refs: [], summary: '', rationale: '' },
  answer: '',
});
```

**Step 3: STT 이벤트 수신 시 turn_idx 갱신**

WebSocket `redis-message` 핸들러의 `stt:final` 또는 customer utterance 처리부에:

```typescript
if (messageData.speaker === 'customer' && typeof messageData.turn_idx === 'number') {
  currentTurnIdx.value = messageData.turn_idx;
  currentMaskedQuery.value = messageData.masked_text ?? messageData.origin_text ?? '';
  // buffer 초기화
  snapshotBuffer.value = {
    hint: '',
    sources: [],
    distilled: { selected_refs: [], summary: '', rationale: '' },
    answer: '',
  };
}
```

**Step 4: SSE 이벤트별 누적 — sources 핸들러 수정**

기존 `sources:` 핸들러의 `extractDemoTitle` 로직은 **유지**하되, 계산된 hint를 snapshot buffer에도 저장:

```typescript
sources: (e: SourcesEvent) => {
  if (skipped) return;

  // 데모용 Q. 추출은 유지 (데모 종료 후 별 태스크로 제거 예정)
  const extractDemoTitle = (content: string | undefined, fallback: string) => {
    const m = content?.match(/^Q\.\s*(.+?)(?:\n|$)/);
    return m ? `Q. ${m[1].trim()}` : fallback;
  };

  // buffer 누적 — sources 원본 그대로 저장
  snapshotBuffer.value.sources = e.sources.map((s) => ({
    chunk_id: s.chunk_id,
    document_id: s.document_id,
    document_title: s.document_title ?? '',
    section_title: s.section_title ?? '',
    content: s.content ?? '',
    score: s.score ?? 0,
    source_location: s.source_location ?? '',
    page_info: s.page_info,
    ref_num: s.ref_num ?? 0,
  }));

  // 첫 번째 source 기준 hint 계산 (라이브 pill에 표시되는 것과 동일 값 → snapshot에도 동일 저장)
  const firstSource = e.sources[0];
  const computedHint = firstSource
    ? extractDemoTitle(firstSource.content, firstSource.document_title || firstSource.section_title || '문서')
    : '문서';
  snapshotBuffer.value.hint = computedHint;

  // 기존 keywordDetailData 바인딩 로직은 그대로 두되, title 계산에도 같은 computedHint 경로 사용
},
```

> 핵심: 라이브 pill에 표시되는 값과 `snapshot.hint`에 저장되는 값이 **반드시 동일 경로로 계산**되어야 함. 이력에서 복원 시 그대로 맞음.

**Step 5: distilled / token / done 핸들러에 누적 추가**

```typescript
distilled: (e) => {
  snapshotBuffer.value.distilled = {
    selected_refs: e.selected_refs ?? [],
    summary: e.summary ?? '',
    rationale: e.rationale ?? '',
  };
  // ... 기존 UI 반영
},
token: (e) => {
  snapshotBuffer.value.answer += e.text ?? '';
  // ... 기존 UI 반영
},
done: async () => {
  // ... 기존 cleanup

  // 스냅샷 저장 (fire-and-forget)
  if (currentCallId.value && currentTurnIdx.value != null) {
    void saveAssistSnapshot({
      callId: currentCallId.value,
      turnIdx: currentTurnIdx.value,
      customerQuery: currentMaskedQuery.value,
      payload: snapshotBuffer.value,
    });
  }
},
```

**Step 6: `extractDemoTitle` 유지 확인**

`extractDemoTitle`은 데모 시연을 위해 당분간 유지. Step 4에서 이 함수 결과를 `snapshot.hint`에 저장하도록 연결했으면 충분. 데모 종료 후 별도 태스크에서 제거 + `document_title` 폴백으로 전환.

**Step 7: Run unit tests (없다면 스킵 가능)**

Run: `cd asst-web && npm run test:unit -- chat`
Expected: 기존 테스트 PASS (또는 없음)

**Step 8: Commit**

```bash
git add asst-web/src/view/advisor/components/chat/index.vue
git commit -m "feat: 라이브 응답 스냅샷 저장 연결

- SSE 이벤트별 snapshotBuffer 누적
- done 이벤트 시 saveAssistSnapshot 호출 (fire-and-forget)
- STT turn_idx + masked_text를 스냅샷 키로 사용
- snapshot.hint는 pill에 표시되는 값과 동일하게 extractDemoTitle 결과 저장 (데모용 유지)"
```

---

### Task 13: 이력 모달 — snapshot 기반 렌더로 교체

**Files:**
- Modify: `asst-web/src/view/advisor/components/ChatHistoryModal.vue`

**Step 1: 변경 범위 요약**

- `loadSearchHintsForHistory` 함수 + 호출부 **전부 제거**
- `getCallStatById` 응답의 `snapshots` 배열 사용
- turn의 turn_idx와 snapshot.turn_idx 매칭 (`customer_query`로 보강 검증)
- snapshot 없는 turn → pill/지식정보 영역 **렌더 생략**

**Step 2: 구현**

기존 `loadSearchHintsForHistory` 함수 삭제.
응답 파싱 후 아래 로직 추가:

```typescript
// API 응답 처리 직후
const snapshots = response.data.snapshots ?? [];
const snapshotByTurnIdx = new Map<number, (typeof snapshots)[number]>();
for (const s of snapshots) snapshotByTurnIdx.set(s.turn_idx, s);

for (const msg of chatContent.value) {
  if (msg.sender !== 'user') continue;

  // turn_idx 기반 매칭 (msg에 turn_idx가 없다면 파싱 시점에 세팅되도록 보정)
  const snapshot = snapshotByTurnIdx.get(Number(msg.turnIdx));
  if (!snapshot) continue;

  // customer_query 보강 검증 (불일치 시 skip)
  if (snapshot.customer_query && snapshot.customer_query !== msg.content) {
    // 마스킹 차이로 완전 일치 안 할 수 있으니 경고만
    console.warn('[ChatHistoryModal] snapshot/turn mismatch', snapshot.turn_idx);
  }

  // pill + 지식정보 렌더 구성 (라이브와 동일 포맷)
  const allItems = snapshot.payload.sources.map((s, idx) => ({
    id: idx + 1,
    title: snapshot.payload.hint,
    keyword: [],
    isLike: false,
    isMain: idx === 0,
    data: {
      id: s.chunk_id,
      document_id: s.document_id,
      document_name: s.document_title,
      section_title: s.section_title,
      content: s.content,
      score: s.score,
      block_type: '',
      source_location: s.source_location,
      search_summary: snapshot.payload.distilled.summary,
      hint: snapshot.payload.hint,
      ref_num: s.ref_num,
      page_info: s.page_info,
    },
  }));

  const messageId = String(msg.id);
  const hintKey = snapshot.payload.hint.slice(0, 20);
  const hintKeyFull = `${messageId}_${hintKey}`;
  keywordDetailData.value[hintKeyFull] = [
    { type: '지식정보', content: allItems },
  ];
  msg.highlightKeywords = [hintKey];
}
```

**Step 3: 테스트 — 수동 E2E 체크리스트**

로컬 dev 환경에서:

1. 새 상담 1회 진행 (질문 2~3개 던짐) → snapshot 저장 확인 (DB `advisor.callstat_assist_snapshot` 조회)
2. 콜 종료 후 상담 이력 모달 열기 → 라이브와 **동일한 pill 텍스트 · 동일한 지식정보 리스트 · 동일한 AI 요약 · 동일한 AI 답변** 표시되는지 확인
3. 기존(snapshot 없는) 과거 상담 이력 열기 → pill/지식정보 영역이 깔끔히 숨겨지는지 확인 (에러 없음)

**Step 4: Commit**

```bash
git add asst-web/src/view/advisor/components/ChatHistoryModal.vue
git commit -m "feat: 이력 모달을 snapshot 기반 렌더로 교체

- loadSearchHintsForHistory 함수 및 /search 재호출 제거
- getCallStatById 응답의 snapshots 배열을 turn_idx로 매칭
- snapshot 없는 turn은 pill/지식정보 영역 숨김"
```

---

### Task 14: 통합 수동 검증

**Files:**
- 변경 없음 (검증 단계)

**Step 1: 전체 스택 기동**

```bash
# asst-service
cd asst-service && npm run start:dev

# asst-web (별도 터미널)
cd asst-web && npm run dev
```

**Step 2: 체크리스트 수행**

- [ ] 신규 상담 진행 → `done` 이벤트마다 `POST /assist-stream/snapshot` 200 응답 확인 (Network 탭)
- [ ] DB에서 `SELECT call_id, turn_idx, customer_query, jsonb_typeof(payload) FROM advisor.callstat_assist_snapshot ORDER BY created_at DESC LIMIT 10;` 실행해 저장값 확인
- [ ] 같은 `(call_id, turn_idx)` 중복 저장 시 upsert 동작 (로그 에러 없음)
- [ ] 네트워크 차단(Devtools Offline) 상태에서 SSE 완료 → `[AssistSnapshot] save failed after retries` 경고 + UX 영향 없음
- [ ] 상담 이력 모달 열기 → 라이브와 동일한 pill·지식정보·요약·답변 확인
- [ ] 기존 상담(snapshot 없음) 이력 모달 → pill/지식정보 영역 숨김, 나머지는 정상
- [ ] 이력에서 `/search` 재호출 **발생하지 않음** 확인 (Network 탭)
- [ ] `customer_query` 불일치 시 `console.warn` 발생, 해당 turn만 영역 숨김 (전체 파손 없음)

**Step 3: Commit (변경 없음, 체크리스트만)**

없음. 검증 완료 후 PR로 넘김.

---

## 완료 기준

- Task 1~10 백엔드 작업 모두 빌드/테스트 통과
- Task 11~13 프론트 작업 모두 빌드/테스트 통과
- Task 14 수동 검증 체크리스트 전 항목 통과
- 라이브 세션과 이력 세션의 관련문서/hint/요약/답변이 **100% 동일**하게 표시됨
- 기존 상담(snapshot 없는) 이력 조회 시 에러 없음
