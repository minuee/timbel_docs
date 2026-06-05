# 문서 검색 기능 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 고객 발화 수신 시 검색 엔진에 dense 검색을 요청하고 지식정보 패널에 결과를 표시한다.

**Architecture:** 프론트에서 무의미 발화를 필터링한 후 asst-service에 검색 요청 → asst-service가 검색엔진을 호출하고 결과를 가공하여 반환 → 프론트가 기존 keywordDetailData 구조에 저장하여 지식정보 패널에 표시.

**Tech Stack:** NestJS 11, TypeScript, axios, Vue 3, class-validator

**Design Doc:** `docs/plans/2026-04-16-document-search-design.md`

---

## Task 1: 백엔드 — 상수 및 DTO 정의

**Files:**
- Create: `asst-service/src/advisor/search/constants/search.constants.ts`
- Create: `asst-service/src/advisor/search/dto/search-request.dto.ts`

**Step 1: 상수 파일 생성**

`asst-service/src/advisor/search/constants/search.constants.ts`:
```typescript
export const TRIVIAL_UTTERANCES = [
  '네', '예', '응', '음', '으음', '아니오', '아니요', '아뇨',
  '감사합니다', '고맙습니다', '알겠습니다', '그렇습니다', '맞습니다',
  '여보세요', '네네',
];

export const TRIVIAL_MIN_LENGTH = 2;

export const SEARCH_DEFAULTS = {
  REPOSITORY_ID: '00000000-0000-0000-0000-000000000001',
  DOCUMENT_TYPE_IDS: ['3fa85f64-5717-4562-b3fc-2c963f66afa6'],
  MODE: 'hybrid',
  TOP_K: 5,
  ENABLE_RERANK: true,
  USE_HYDE: true,
  USE_FALLBACK: true,
  ENABLE_LLM_REWRITE: true,
  WITH_ANSWER: true,
  DISTILL: true,
} as const;
```

**Step 2: 요청 DTO 생성**

`asst-service/src/advisor/search/dto/search-request.dto.ts`:
```typescript
import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsString, IsNotEmpty, IsOptional, IsArray, ValidateNested } from 'class-validator';
import { Type } from 'class-transformer';

export class ConversationHistoryItemDto {
  @ApiProperty({ description: '발화자', enum: ['customer', 'agent'] })
  @IsString()
  speaker: 'customer' | 'agent';

  @ApiProperty({ description: '발화 내용' })
  @IsString()
  content: string;
}

export class SearchRequestDto {
  @ApiProperty({ description: '검색 쿼리 (현재 고객 발화)' })
  @IsString()
  @IsNotEmpty()
  query: string;

  @ApiPropertyOptional({ description: '직전 대화 이력 (고객+상담사 각 1턴)', type: [ConversationHistoryItemDto] })
  @IsOptional()
  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => ConversationHistoryItemDto)
  conversationHistory?: ConversationHistoryItemDto[];

  @ApiPropertyOptional({ description: '통화 ID (로깅용)' })
  @IsOptional()
  @IsString()
  callId?: string;
}
```

**Step 3: 커밋**

```bash
git add asst-service/src/advisor/search/
git commit -m "feat: 문서 검색 상수 및 요청 DTO 정의"
```

---

## Task 2: 백엔드 — SearchService 구현

**Files:**
- Create: `asst-service/src/advisor/search/services/search.service.ts`

**Step 1: SearchService 생성**

`asst-service/src/advisor/search/services/search.service.ts`:
```typescript
import { HttpException, HttpStatus, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import axios, { AxiosResponse } from 'axios';

import { SEARCH_DEFAULTS, TRIVIAL_MIN_LENGTH, TRIVIAL_UTTERANCES } from '@app/advisor/search/constants/search.constants';
import { SearchRequestDto } from '@app/advisor/search/dto/search-request.dto';

@Injectable()
export class SearchService {
  private readonly logger = new Logger(SearchService.name);
  private readonly searchHost: string;

  constructor(private readonly configService: ConfigService) {
    this.searchHost = this.configService.get<string>('SEARCH_HOST') || '';
    if (!this.searchHost) {
      this.logger.warn('SEARCH_HOST가 설정되지 않았습니다.');
    }
  }

  isTrivialUtterance(query: string): boolean {
    const trimmed = query.replace(/\s/g, '');
    if (trimmed.length <= TRIVIAL_MIN_LENGTH) return true;
    return TRIVIAL_UTTERANCES.includes(trimmed);
  }

  async search(dto: SearchRequestDto, token: string | undefined): Promise<any> {
    if (this.isTrivialUtterance(dto.query)) {
      this.logger.debug(`무의미 발화 필터링: "${dto.query}"`);
      return { results: [], total_candidates: 0 };
    }

    if (!this.searchHost) {
      throw new HttpException('SEARCH_HOST가 설정되지 않았습니다.', HttpStatus.SERVICE_UNAVAILABLE);
    }

    const url = `${this.searchHost}/api/v1/search`;

    const payload = {
      query: dto.query,
      repository_id: SEARCH_DEFAULTS.REPOSITORY_ID,
      document_type_ids: SEARCH_DEFAULTS.DOCUMENT_TYPE_IDS,
      mode: SEARCH_DEFAULTS.MODE,
      top_k: SEARCH_DEFAULTS.TOP_K,
      enable_rerank: SEARCH_DEFAULTS.ENABLE_RERANK,
      use_hyde: SEARCH_DEFAULTS.USE_HYDE,
      use_fallback: SEARCH_DEFAULTS.USE_FALLBACK,
      enable_llm_rewrite: SEARCH_DEFAULTS.ENABLE_LLM_REWRITE,
      with_answer: SEARCH_DEFAULTS.WITH_ANSWER,
      distill: SEARCH_DEFAULTS.DISTILL,
      conversation_history: dto.conversationHistory ?? [],
    };

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (token) {
      headers['Authorization'] = token.startsWith('Bearer ') ? token : `Bearer ${token}`;
    }

    this.logger.debug(`검색 요청: query="${dto.query}", callId=${dto.callId || 'N/A'}`);

    try {
      const response: AxiosResponse = await axios.post(url, payload, {
        headers,
        timeout: 30000,
      });

      // 검색엔진 응답: { success, data: { query, results, total_candidates, latency_ms }, error }
      const responseData = response.data;
      if (!responseData?.success) {
        this.logger.warn(`검색엔진 실패 응답: ${responseData?.error}`);
        return { results: [], total_candidates: 0 };
      }
      return responseData.data ?? { results: [], total_candidates: 0 };
    } catch (error) {
      if (axios.isAxiosError(error)) {
        if (error.response) {
          this.logger.error(`검색엔진 응답 오류: ${error.response.status}`, error.response.data);
          throw new HttpException(
            `검색 서비스 오류: ${error.response.status}`,
            HttpStatus.BAD_GATEWAY,
          );
        }
        if (error.request) {
          this.logger.error('검색엔진에 연결할 수 없습니다.');
          throw new HttpException(
            '검색 서비스에 연결할 수 없습니다.',
            HttpStatus.SERVICE_UNAVAILABLE,
          );
        }
      }
      throw error;
    }
  }
}
```

**Step 2: 커밋**

```bash
git add asst-service/src/advisor/search/services/search.service.ts
git commit -m "feat: 검색 서비스 구현 (무의미 발화 필터링 + 검색엔진 호출)"
```

---

## Task 3: 백엔드 — SearchController + 모듈 등록

**Files:**
- Create: `asst-service/src/advisor/search/controllers/search.controller.ts`
- Modify: `asst-service/src/advisor/advisor.module.ts`
- Modify: `asst-service/src/config/validation.config.ts`

**Step 1: SearchController 생성**

`asst-service/src/advisor/search/controllers/search.controller.ts`:
```typescript
import { Body, Controller, Post, Req, UseInterceptors } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';

import { DbCleanupInterceptor } from '@app/common/interceptors/db-cleanup.interceptor';
import { SearchRequestDto } from '@app/advisor/search/dto/search-request.dto';
import { SearchService } from '@app/advisor/search/services/search.service';

@ApiTags('검색')
@ApiBearerAuth('bearer')
@Controller('search')
@UseInterceptors(DbCleanupInterceptor)
export class SearchController {
  constructor(private readonly searchService: SearchService) {}

  @Post()
  @ApiOperation({ summary: '문서 검색', description: '고객 발화 기반 문서 검색' })
  async search(
    @Body() dto: SearchRequestDto,
    @Req() req: Request & { token?: string },
  ) {
    return this.searchService.search(dto, req.token);
  }
}
```

**Step 2: advisor.module.ts에 등록**

import 추가:
```typescript
// Search
import { SearchController } from '@app/advisor/search/controllers/search.controller';
import { SearchService } from '@app/advisor/search/services/search.service';
```

`controllers` 배열에 `SearchController` 추가, `providers` 배열에 `SearchService` 추가.

**Step 3: validation.config.ts에 SEARCH_HOST 추가**

```typescript
SEARCH_HOST: Joi.string().uri().optional(),
```

`SOCKET_SECURE` 라인 바로 위에 추가.

**Step 4: 타입체크 + 린트**

```bash
cd asst-service && npm run build && npm run lint
```

**Step 5: 커밋**

```bash
git add asst-service/src/advisor/search/controllers/search.controller.ts \
       asst-service/src/advisor/advisor.module.ts \
       asst-service/src/config/validation.config.ts
git commit -m "feat: 검색 컨트롤러 및 모듈 등록"
```

---

## Task 4: 프론트엔드 — API 경로, 타입, API 클래스 추가

**Files:**
- Modify: `asst-web/src/api/config/path.ts`
- Modify: `asst-web/src/api/types/ce.type.ts` (검색 타입 추가)
- Create: `asst-web/src/api/apis/document-search.api.ts`

**Step 1: path.ts에 SEARCH 경로 추가**

`asst-web/src/api/config/path.ts` — ADVISOR.API 객체에 추가:
```typescript
SEARCH: `/search`
```

**Step 2: 검색 타입 정의**

`asst-web/src/api/types/ce.type.ts` 하단에 추가:
```typescript
// Document Search (검색엔진)
export interface DocumentSearchConversationItem {
  speaker: 'customer' | 'agent';
  content: string;
}

export interface DocumentSearchReq {
  query: string;
  conversationHistory?: DocumentSearchConversationItem[];
  callId?: string;
}

export interface DocumentSearchResultItem {
  chunk_id: string;
  document_id: string;
  document_title: string;
  section_title: string | null;
  content: string;
  score: number;
  block_type: string;
  block_index: number;
  repository_id: string;
  validity: string | null;
  nature: string | null;
  classification_confidence: number | null;
  token_count: number | null;
  fallback_level: number | null;
  source_location?: {
    file_path?: string | null;
    page_number?: number | null;
    heading_path?: string[];
  };
  metadata?: {
    hint?: string;
    search_summary?: string;
    highlight?: {
      content?: string[];
    };
    repository_name?: string;
    [key: string]: any;
  };
}

export interface DocumentSearchResponse {
  success: boolean;
  data: {
    query: string;
    results: DocumentSearchResultItem[];
    total_candidates: number;
    latency_ms: number;
    decomposed: any;
  };
  error: any;
}
```

**Step 3: API 클래스 생성**

`asst-web/src/api/apis/document-search.api.ts`:
```typescript
import APIInstance from "@/api/apis";
import { path } from "@/api/config/path";
import type { DocumentSearchReq } from "@/api/types/ce.type";

const SEARCH = path.ADVISOR.API_PREFIX + path.ADVISOR.API.SEARCH;

export class DocumentSearchAPI extends APIInstance {
  private static _instance: DocumentSearchAPI | null = null;

  constructor() {
    super("advisor");
  }

  static get instance(): DocumentSearchAPI {
    if (!DocumentSearchAPI._instance) {
      DocumentSearchAPI._instance = new DocumentSearchAPI();
    }
    return DocumentSearchAPI._instance;
  }

  searchDocuments = async (req: DocumentSearchReq) => {
    const response = await this.client.post(SEARCH, req);
    return response;
  };
}
```

**Step 4: 커밋**

```bash
git add asst-web/src/api/config/path.ts \
       asst-web/src/api/types/ce.type.ts \
       asst-web/src/api/apis/document-search.api.ts
git commit -m "feat: 문서 검색 API 경로, 타입, 클래스 추가"
```

---

## Task 5: 프론트엔드 — chat/index.vue 검색 연동

**Files:**
- Modify: `asst-web/src/view/advisor/components/chat/index.vue`

**Step 1: 무의미 발화 필터 상수 추가**

파일 상단 `<script setup>` 내에 추가:
```typescript
import { DocumentSearchAPI } from "@/api/apis/document-search.api";

const TRIVIAL_UTTERANCES = new Set([
  '네', '예', '응', '음', '으음', '아니오', '아니요', '아뇨',
  '감사합니다', '고맙습니다', '알겠습니다', '그렇습니다', '맞습니다',
  '여보세요', '네네',
]);

const isTrivialUtterance = (text: string): boolean => {
  const trimmed = text.replace(/\s/g, '');
  return trimmed.length <= 2 || TRIVIAL_UTTERANCES.has(trimmed);
};
```

**Step 2: handleDocumentSearch 함수 추가**

`handleAutoSelectKeywordV2` 함수 바로 위에 추가:
```typescript
const handleDocumentSearch = async (query: string, messageId: string) => {
  if (isTrivialUtterance(query)) return;

  // 직전 대화 이력 추출 (현재 메시지 제외, 가장 최근 고객 1턴 + 상담사 1턴)
  const conversationHistory: { speaker: 'customer' | 'agent'; content: string }[] = [];
  const currentMessages = chatContent.value;

  let lastAgent: { speaker: 'agent'; content: string } | null = null;
  let lastCustomer: { speaker: 'customer'; content: string } | null = null;

  // 현재 메시지 제외하고 뒤에서부터 탐색
  for (let i = currentMessages.length - 1; i >= 0; i--) {
    const msg = currentMessages[i];
    if (String(msg.id) === messageId) continue;
    if (!lastAgent && msg.sender === 'consultant') {
      lastAgent = { speaker: 'agent', content: msg.content };
    }
    if (!lastCustomer && msg.sender === 'user') {
      lastCustomer = { speaker: 'customer', content: msg.content };
    }
    if (lastAgent && lastCustomer) break;
  }

  if (lastCustomer) conversationHistory.push(lastCustomer);
  if (lastAgent) conversationHistory.push(lastAgent);
  // 시간순 정렬 (위에서 뒤에서부터 찾았으므로 역순일 수 있음)
  conversationHistory.sort((a, b) => {
    const aIdx = currentMessages.findIndex(m =>
      m.content === a.content && (a.speaker === 'customer' ? m.sender === 'user' : m.sender === 'consultant')
    );
    const bIdx = currentMessages.findIndex(m =>
      m.content === b.content && (b.speaker === 'customer' ? m.sender === 'user' : m.sender === 'consultant')
    );
    return aIdx - bIdx;
  });

  try {
    const payload: { query: string; conversationHistory: typeof conversationHistory; callId?: string } = {
      query,
      conversationHistory,
    };

    const callId = callSummaryInfoStore.callId;
    if (callId) payload.callId = callId;

    const response = await DocumentSearchAPI.instance.searchDocuments(payload);

    // 응답 구조: { success, data: { results: [...] }, error }
    // asst-service가 data 내부를 그대로 반환하므로 → response.data.results
    if (response?.status === 200 && response.data?.results?.length > 0) {
      const results = response.data.results;
      const topResult = results[0];  // 1위: 메인 표시 (document_title + content)
      const relatedResults = results.slice(1);  // 나머지: 관련 자료

      // 메인 결과 (1위)
      const mainItem = {
        id: 1,
        title: topResult.document_title || '문서',
        keyword: [],
        isLike: false,
        isMain: true,
        data: {
          document_id: topResult.document_id,
          document_name: topResult.document_title,
          section_title: topResult.section_title,
          content: topResult.content,
          score: topResult.score,
          block_type: topResult.block_type,
          source_location: topResult.source_location,
          search_summary: topResult.metadata?.search_summary || '',
          hint: topResult.metadata?.hint || '',
        },
      };

      // 관련 자료 (2위~)
      const relatedItems = relatedResults.map((item: any, index: number) => ({
        id: index + 2,
        title: item.document_title || item.section_title || '문서',
        keyword: [],
        isLike: false,
        isMain: false,
        data: {
          document_id: item.document_id,
          document_name: item.document_title,
          section_title: item.section_title,
          content: item.content,
          score: item.score,
          block_type: item.block_type,
          source_location: item.source_location,
          search_summary: item.metadata?.search_summary || '',
          hint: item.metadata?.hint || '',
        },
      }));

      keywordDetailData.value[messageId] = [
        {
          type: "지식정보",
          content: [mainItem, ...relatedItems],
        },
      ];

      updateKeywordOrder(messageId, query.slice(0, 20));

      if (isAutoSearch.value) {
        const latestUserMessage = chatContent.value.filter(msg => msg.sender === "user").pop();
        const latestMessageId = latestUserMessage?.id || (chatContent.value.length > 0 ? chatContent.value[chatContent.value.length - 1].id : 1);
        const detailData = keywordDetailData.value[messageId];
        if (detailData.length > 0 && detailData[0].content.length > 0) {
          const firstGroup = detailData[0];
          const firstItem = firstGroup.content[0];

          currentSelectedDocument.value = {
            keyword: messageId,
            type: firstGroup.type,
            itemId: firstItem.id,
            title: firstItem.title,
          };

          nextTick(() => {
            emit(
              "detailItemClick",
              latestMessageId,
              messageId,
              firstGroup.type,
              firstItem.id,
              "chat",
              firstItem.title,
              detailData,
              firstItem,
              firstItem.keyword,
            );
          });
        }
      }
    }
  } catch (error) {
    console.error("[CHAT] 문서 검색 오류:", error);
  }
};
```

**Step 3: nlp:complete 분기에서 기존 검색 주석 처리 + 새 검색 호출**

`index.vue` 약 1540행 부근, 기존 코드:
```typescript
if (isUser && intentId && intentId !== 'no_intent') {
  handleAutoSelectKeywordV2(messageData, intentId, String(newMsg.id));
}
```

변경:
```typescript
// [주석 처리] 기존 intent 기반 CE서비스 검색
// if (isUser && intentId && intentId !== 'no_intent') {
//   handleAutoSelectKeywordV2(messageData, intentId, String(newMsg.id));
// }

// 새 문서 검색 (고객 발화 시 검색엔진 호출)
if (isUser) {
  handleDocumentSearch(messageData.origin_text, String(newMsg.id));
}
```

**Step 4: 린트**

```bash
cd asst-web && npm run lint
```

**Step 5: 커밋**

```bash
git add asst-web/src/view/advisor/components/chat/index.vue
git commit -m "feat: 고객 발화 기반 문서 검색 연동 (기존 intent 검색 주석 처리)"
```

---

## Task 6: 검증

**Step 1: 백엔드 빌드 확인**

```bash
cd asst-service && npm run build
```

**Step 2: 프론트엔드 빌드 확인**

```bash
cd asst-web && npm run build:dev
```

**Step 3: 최종 커밋 (필요 시)**

빌드 오류 수정 후 추가 커밋.
